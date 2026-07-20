import io

import requests
from django import forms
from django.contrib import admin, messages
from django.db import models as db_models
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

import apps.transformation.handlers  # noqa: F401 — populates handler registry
from apps.transformation.handlers.registry import list_handlers
from apps.transformation.models import (FieldMapping, SourceFieldDefinition,
                                        Supplier, TargetTemplate,
                                        TransformationJob)


class FieldMappingInlineForm(forms.ModelForm):
    handler_method = forms.ChoiceField(choices=[])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["handler_method"].choices = [
            (name, name) for name in list_handlers()
        ]

    class Meta:
        model = FieldMapping
        fields = "__all__"


STATUS_COLORS = {
    TransformationJob.Status.PENDING: "#888888",
    TransformationJob.Status.PROCESSING: "#1a73e8",
    TransformationJob.Status.PARTIAL: "#f9a825",
    TransformationJob.Status.DONE: "#2e7d32",
    TransformationJob.Status.FAILED: "#c62828",
}


class SourceFieldDefinitionInline(admin.TabularInline):
    model = SourceFieldDefinition
    fk_name = "template"
    extra = 0
    readonly_fields = ("edit_link",)
    autocomplete_fields = ("parent",)
    fields = (
        "order",
        "name",
        "field_type",
        "parent",
        "required",
        "nullable",
        "description",
        "edit_link",
    )

    def edit_link(self, obj):
        if not obj.pk:
            return "—"
        url = reverse(
            "admin:transformation_sourcefielddefinition_change", args=[obj.pk]
        )
        return format_html(
            '<a href="{}" style="display:inline-block;padding:3px 10px;background:#1a73e8;'
            "color:white;border-radius:4px;text-decoration:none;font-size:11px;"
            'white-space:nowrap;font-weight:500">✏ Edit</a>',
            url,
        )

    edit_link.short_description = ""


class FieldMappingInline(admin.TabularInline):
    model = FieldMapping
    form = FieldMappingInlineForm
    extra = 0
    fields = (
        "order",
        "source_field",
        "target_field",
        "handler_method",
        "handler_data",
        "sheet_name",
    )
    autocomplete_fields = ("source_field",)
    formfield_overrides = {
        db_models.JSONField: {
            "widget": forms.Textarea(
                attrs={
                    "rows": 2,
                    "style": "width:220px;font-size:11px;font-family:monospace;resize:vertical",
                }
            )
        },
    }


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "supplier_account_id", "created_at")
    search_fields = ("name", "supplier_account_id")


@admin.register(TargetTemplate)
class TargetTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "supplier", "format", "version", "updated_at")
    list_filter = ("format", "supplier", "version")
    search_fields = ("name",)
    autocomplete_fields = ("supplier",)
    inlines = [SourceFieldDefinitionInline, FieldMappingInline]

    class Media:
        css = {"all": ("transformation/admin.css",)}


@admin.register(SourceFieldDefinition)
class SourceFieldDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "path",
        "template",
        "field_type",
        "parent",
        "required",
        "nullable",
        "order",
    )
    list_filter = ("template__format", "field_type", "required", "nullable")
    search_fields = ("name", "template__name")
    autocomplete_fields = ("template", "parent")


@admin.register(FieldMapping)
class FieldMappingAdmin(admin.ModelAdmin):
    list_display = (
        "template",
        "source_field_name",
        "target_field",
        "handler_method",
        "sheet_name",
        "order",
    )
    list_filter = ("template__format", "handler_method")
    search_fields = ("source_field__name", "target_field")
    autocomplete_fields = ("template", "source_field")

    def source_field_name(self, obj):
        return obj.source_field.name

    source_field_name.short_description = "Source field"
    source_field_name.admin_order_field = "source_field__name"


@admin.register(TransformationJob)
class TransformationJobAdmin(admin.ModelAdmin):
    change_list_template = "admin/transformation/transformationjob/change_list.html"
    change_form_template = "admin/transformation/transformationjob/change_form.html"

    list_display = (
        "short_id",
        "supplier",
        "format",
        "template",
        "colored_status",
        "progress",
        "failed_count",
        "created_at",
        "source_download_btn",
        "output_download_btn",
    )
    list_filter = ("status", "format", "supplier")
    search_fields = ("id",)
    readonly_fields = (
        "id",
        "supplier",
        "format",
        "template",
        "storage_path",
        "status",
        "total_chunks",
        "processed_chunks",
        "skipped_items",
        "failed_chunks",
        "output_storage_path",
        "completed_at",
        "started_at",
        "created_at",
    )
    actions = ["retry_failed_chunks"]

    # ------------------------------------------------------------------
    # List display helpers
    # ------------------------------------------------------------------

    def short_id(self, obj):
        return str(obj.id)[:8] + "…"

    short_id.short_description = "Job ID"

    def colored_status(self, obj):
        color = STATUS_COLORS.get(obj.status, "#888")
        return format_html(
            '<span style="color:white;background:{};padding:2px 8px;border-radius:4px;font-size:11px">{}</span>',
            color,
            obj.status,
        )

    colored_status.short_description = "Status"

    def progress(self, obj):
        if not obj.total_chunks:
            return "—"
        pct = int((obj.processed_chunks / obj.total_chunks) * 100)
        return format_html(
            '<div style="width:100px;background:#ddd;border-radius:4px">'
            '<div style="width:{}px;background:{};height:14px;border-radius:4px"></div>'
            "</div> {}%",
            pct,
            STATUS_COLORS.get(obj.status, "#888"),
            pct,
        )

    progress.short_description = "Progress"

    def failed_count(self, obj):
        n = len(obj.failed_chunks or [])
        if n == 0:
            return "—"
        return format_html(
            '<span style="color:#c62828;font-weight:bold">{} failed</span>', n
        )

    failed_count.short_description = "Failed chunks"

    def source_download_btn(self, obj):
        url = reverse("admin:download-source", args=[obj.id])
        return format_html(
            '<a href="{}" style="display:inline-block;padding:3px 10px;background:#455a64;color:white;'
            'border-radius:4px;text-decoration:none;font-size:11px;white-space:nowrap">⬇ Source</a>',
            url,
        )

    source_download_btn.short_description = "Source"

    def output_download_btn(self, obj):
        if not obj.output_storage_path:
            return format_html('<span style="color:#bbb;font-size:11px">Pending</span>')
        url = reverse("admin:download-output", args=[obj.id])
        return format_html(
            '<a href="{}" style="display:inline-block;padding:3px 10px;background:#2e7d32;color:white;'
            'border-radius:4px;text-decoration:none;font-size:11px;white-space:nowrap">⬇ {}</a>',
            url,
            obj.format.upper(),
        )

    output_download_btn.short_description = "Output"

    # ------------------------------------------------------------------
    # Bulk retry action
    # ------------------------------------------------------------------

    @admin.action(description="Retry all failed chunks for selected jobs")
    def retry_failed_chunks(self, request, queryset):
        retried = 0
        for job in queryset:
            if not job.failed_chunks:
                continue
            api_url = request.build_absolute_uri(f"/api/jobs/{job.id}/retry/")
            response = requests.post(api_url)
            if response.status_code == 202:
                retried += len(job.failed_chunks)
            else:
                messages.error(request, f"Job {str(job.id)[:8]}: {response.text}")
        if retried:
            messages.success(request, f"{retried} chunk(s) re-dispatched.")

    # ------------------------------------------------------------------
    # Custom URLs
    # ------------------------------------------------------------------

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "submit/",
                self.admin_site.admin_view(self.submit_view),
                name="submit-transform",
            ),
            path(
                "<str:job_id>/retry-chunk/",
                self.admin_site.admin_view(self.retry_chunk_view),
                name="retry-chunk",
            ),
            path(
                "<str:job_id>/download/",
                self.admin_site.admin_view(self.download_view),
                name="download-output",
            ),
            path(
                "<str:job_id>/download-source/",
                self.admin_site.admin_view(self.download_source_view),
                name="download-source",
            ),
        ]
        return custom + urls

    # ------------------------------------------------------------------
    # Submit view
    # ------------------------------------------------------------------

    def submit_view(self, request):
        if request.method == "POST":
            uploaded_file = request.FILES.get("file")
            supplier_account_id = request.POST.get("supplier_account_id")
            template_id = request.POST.get("template_id")

            if not uploaded_file or not supplier_account_id or not template_id:
                messages.error(request, "All fields are required.")
                return redirect("admin:submit-transform")

            api_url = request.build_absolute_uri("/api/transform/")
            response = requests.post(
                api_url,
                data={
                    "supplier_account_id": supplier_account_id,
                    "template_id": template_id,
                },
                files={
                    "file": (
                        uploaded_file.name,
                        uploaded_file.read(),
                        uploaded_file.content_type,
                    )
                },
            )

            if response.status_code in (200, 202):
                data = response.json()
                job_id = data.get("job_id")
                detail = data.get("detail", "Job dispatched")
                messages.success(request, f"Job submitted: {job_id} — {detail}")
                return redirect(
                    reverse(
                        "admin:transformation_transformationjob_change", args=[job_id]
                    )
                )
            else:
                messages.error(request, f"Error: {response.text}")
                return redirect("admin:submit-transform")

        from apps.transformation.repositories.supplier_repository import \
            SupplierRepository
        from apps.transformation.repositories.template_repository import \
            TemplateRepository

        context = {
            **self.admin_site.each_context(request),
            "title": "Submit Transformation",
            "suppliers": SupplierRepository().get_all(),
            "templates": TemplateRepository().list_templates(
                status=TargetTemplate.Status.PUBLISHED
            ),
        }
        return render(request, "admin/transformation/submit.html", context)

    # ------------------------------------------------------------------
    # Per-chunk retry view (called from detail page)
    # ------------------------------------------------------------------

    def retry_chunk_view(self, request, job_id):
        if request.method != "POST":
            return redirect(
                reverse("admin:transformation_transformationjob_change", args=[job_id])
            )

        api_url = request.build_absolute_uri(f"/api/jobs/{job_id}/retry/")
        start_raw = request.POST.get("start")
        end_raw = request.POST.get("end")

        if start_raw and end_raw:
            payload = {"chunks": [{"start": int(start_raw), "end": int(end_raw)}]}
            label = f"Chunk [{start_raw}:{end_raw}]"
        else:
            payload = {}
            label = "All failed chunks"

        response = requests.post(api_url, json=payload)

        if response.status_code == 202:
            messages.success(request, f"{label} re-dispatched.")
        else:
            messages.error(request, f"Retry failed: {response.text}")

        return redirect(
            reverse("admin:transformation_transformationjob_change", args=[job_id])
        )

    # ------------------------------------------------------------------
    # Source file download (input JSON — streams from MinIO)
    # ------------------------------------------------------------------

    def download_source_view(self, request, job_id):
        from apps.transformation.factories.storage_factory import \
            StorageFactory
        from apps.transformation.repositories.job_repository import \
            JobRepository

        job = JobRepository().get(job_id)

        if not job or not job.storage_path:
            messages.error(request, "Source file not available.")
            return redirect(
                reverse("admin:transformation_transformationjob_change", args=[job_id])
            )

        body = StorageFactory.create().get_object(job.storage_path).read()
        filename = f"source_{job_id[:8]}.json"

        response = FileResponse(io.BytesIO(body), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    # ------------------------------------------------------------------
    # Output file download (streams from MinIO through Django)
    # ------------------------------------------------------------------

    def download_view(self, request, job_id):
        from apps.transformation.factories.storage_factory import \
            StorageFactory
        from apps.transformation.repositories.job_repository import \
            JobRepository

        job = JobRepository().get(job_id)

        if not job or not job.output_storage_path:
            messages.error(request, "Output file not available yet.")
            return redirect(
                reverse("admin:transformation_transformationjob_change", args=[job_id])
            )

        body = StorageFactory.create().get_object(job.output_storage_path).read()

        ext = job.output_storage_path.rsplit(".", 1)[-1]
        content_types = {
            "csv": "text/csv",
            "geojson": "application/geo+json",
            "xml": "application/xml",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        content_type = content_types.get(ext, "application/octet-stream")
        filename = f"versio_{job_id[:8]}.{ext}"

        response = FileResponse(io.BytesIO(body), content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
