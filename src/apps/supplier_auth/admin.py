from django import forms
from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.http import JsonResponse
from django.urls import path
from django.utils.html import format_html

from apps.supplier_auth.models import (Permission, SupplierAuth, SupplierGroup,
                                       TransformationSupplier)
from apps.supplier_auth.repositories.auth_repository import AuthRepository

# Remove built-in Django auth models — this admin manages supplier_auth only
admin.site.unregister(User)
admin.site.unregister(Group)

_repo = AuthRepository()


# ── Autocomplete widget ───────────────────────────────────────────────────────


class SupplierAutocompleteWidget(forms.Select):
    """
    Select widget using Django admin's already-loaded Select2.
    Only the current selection is rendered server-side; all other options are
    fetched on demand via the supplier-autocomplete endpoint.
    """

    class Media:
        js = ("admin/js/vendor/select2/select2.full.min.js", "admin/js/autocomplete.js")
        css = {
            "screen": (
                "admin/css/vendor/select2/select2.min.css",
                "admin/css/autocomplete.css",
            )
        }

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        attrs.update(
            {
                "data-ajax--url": "/admin/supplier_auth/supplierauth/supplier-autocomplete/",
                "data-ajax--cache": "true",
                "data-ajax--type": "GET",
                "data-placeholder": "Search by supplier name…",
                "class": "admin-autocomplete",
            }
        )
        return attrs

    def optgroups(self, name, value, attrs=None):
        # Render only the currently selected supplier — never loads the full list
        groups = [(None, [], 0)]
        if value and value[0]:
            try:
                pk = int(value[0])
                supplier = TransformationSupplier.objects.get(pk=pk)
                groups[0][1].append(
                    self.create_option(
                        name,
                        pk,
                        f"{supplier.name} (#{pk})",
                        selected=True,
                        index=0,
                        attrs=attrs,
                    )
                )
            except (TransformationSupplier.DoesNotExist, ValueError, TypeError):
                pass
        return groups


# ── Form ──────────────────────────────────────────────────────────────────────


class SupplierChoiceField(forms.ModelChoiceField):
    """
    ModelChoiceField backed by TransformationSupplier.
    Validation is a single PK lookup (no full queryset load).
    Display is delegated to SupplierAutocompleteWidget.
    """

    widget = SupplierAutocompleteWidget

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("queryset", TransformationSupplier.objects.all())
        kwargs.setdefault("label", "Supplier")
        super().__init__(*args, **kwargs)

    def label_from_instance(self, obj):
        return f"{obj.name} (#{obj.pk})"


class SupplierAuthForm(forms.ModelForm):
    supplier = SupplierChoiceField()
    new_password = forms.CharField(
        label="Set new password",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Leave blank to keep the current password.",
    )

    class Meta:
        model = SupplierAuth
        fields = ("email", "is_active", "groups")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            try:
                self.fields["supplier"].initial = TransformationSupplier.objects.get(
                    pk=self.instance.supplier_id
                )
            except TransformationSupplier.DoesNotExist:
                pass

    def save(self, commit=True):
        obj = super().save(commit=False)
        supplier = self.cleaned_data.get("supplier")
        if supplier:
            obj.supplier_id = supplier.pk
        raw = self.cleaned_data.get("new_password")
        if raw:
            obj.set_password(raw)
        elif not obj.pk:
            raise forms.ValidationError(
                "A password is required when creating a new account."
            )
        if commit:
            obj.save()
            self.save_m2m()
        return obj


# ── Admin classes ─────────────────────────────────────────────────────────────


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("codename", "label")
    search_fields = ("codename", "label")
    ordering = ("codename",)


@admin.register(SupplierGroup)
class SupplierGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "permission_count")
    search_fields = ("name",)
    filter_horizontal = ("permissions",)

    @admin.display(description="Permissions")
    def permission_count(self, obj):
        return obj.permissions.count()


@admin.register(SupplierAuth)
class SupplierAuthAdmin(admin.ModelAdmin):
    form = SupplierAuthForm
    list_display = (
        "email",
        "supplier_name",
        "supplier_id",
        "group_list",
        "is_active",
        "last_login",
        "created_at",
    )
    list_filter = ("is_active", "groups")
    search_fields = ("email",)
    filter_horizontal = ("groups",)
    readonly_fields = ("password_display", "last_login", "created_at")
    ordering = ("email",)

    fieldsets = (
        (
            "Identity",
            {
                "fields": ("supplier", "email", "is_active"),
            },
        ),
        (
            "Password",
            {
                "fields": ("password_display", "new_password"),
                "description": "The stored value is a PBKDF2 hash — never stored in plain text.",
            },
        ),
        (
            "Groups & permissions",
            {
                "fields": ("groups",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("last_login", "created_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_urls(self):
        return [
            path(
                "supplier-autocomplete/",
                self.admin_site.admin_view(self.supplier_autocomplete),
                name="supplier_auth_supplierauth_supplier_autocomplete",
            ),
        ] + super().get_urls()

    def supplier_autocomplete(self, request):
        term = request.GET.get("term", "")
        suppliers = _repo.search_suppliers_by_name(term)
        return JsonResponse(
            {
                "results": [
                    {"id": s.pk, "text": f"{s.name} (#{s.pk})"} for s in suppliers
                ],
                "pagination": {"more": False},
            }
        )

    def get_queryset(self, request):
        return _repo.annotate_supplier_name(super().get_queryset(request))

    def get_search_results(self, request, queryset, search_term):
        if not search_term:
            return queryset, False
        supplier_ids = _repo.get_supplier_ids_by_name(search_term)
        return (
            _repo.search_by_email_or_supplier_ids(queryset, search_term, supplier_ids),
            False,
        )

    @admin.display(description="Supplier", ordering="_supplier_name")
    def supplier_name(self, obj):
        return getattr(obj, "_supplier_name", None) or f"#{obj.supplier_id}"

    @admin.display(description="Password hash")
    def password_display(self, obj):
        if obj.pk and obj.password:
            return format_html(
                '<code style="font-size:11px;color:#666">{}</code>',
                obj.password[:40] + "…",
            )
        return "—"

    @admin.display(description="Groups")
    def group_list(self, obj):
        names = [g.name for g in obj.groups.all()]
        return ", ".join(names) if names else "—"
