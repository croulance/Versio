from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from apps.dashboard import api_client as api
from apps.dashboard.field_tree import flatten_fields


def _template_format(request, template_id: int) -> str:
    template = api.get_template(template_id, request.supplier["supplier_account_id"])
    return template["format"] if template else ""


class MappingRowView(View):
    def get(self, request, template_id: int, mapping_id: int):
        mappings = api.list_mappings(
            template_id, request.supplier["supplier_account_id"]
        )
        mapping = next((m for m in mappings if m["id"] == mapping_id), None)
        return render(
            request,
            "dashboard/_mapping_row.html",
            {
                "m": mapping,
                "template_id": template_id,
                "template_format": _template_format(request, template_id),
            },
        )


class MappingEditView(View):
    def get(self, request, template_id: int, mapping_id: int):
        supplier_account_id = request.supplier["supplier_account_id"]
        mappings = api.list_mappings(template_id, supplier_account_id)
        mapping = next((m for m in mappings if m["id"] == mapping_id), None)
        source_fields = flatten_fields(
            api.list_source_fields(template_id, supplier_account_id)
        )
        return render(
            request,
            "dashboard/_mapping_form_row.html",
            {
                "m": mapping,
                "template_id": template_id,
                "source_fields": source_fields,
                "handlers": api.list_handlers(),
                "template_format": _template_format(request, template_id),
            },
        )

    def post(self, request, template_id: int, mapping_id: int):
        data = {
            "source_field_id": int(request.POST.get("source_field_id")),
            "target_field": request.POST.get("target_field", ""),
            "handler_method": request.POST.get("handler_method", "direct"),
            "sheet_name": request.POST.get("sheet_name") or None,
        }
        mapping = api.update_mapping(
            template_id, mapping_id, request.supplier["supplier_account_id"], data
        )
        return render(
            request,
            "dashboard/_mapping_row.html",
            {
                "m": mapping,
                "template_id": template_id,
                "template_format": _template_format(request, template_id),
            },
        )


class MappingAddView(View):
    def get(self, request, template_id: int):
        if request.GET.get("cancel"):
            return HttpResponse("")
        source_fields = flatten_fields(
            api.list_source_fields(template_id, request.supplier["supplier_account_id"])
        )
        return render(
            request,
            "dashboard/_mapping_form_row.html",
            {
                "m": None,
                "template_id": template_id,
                "source_fields": source_fields,
                "handlers": api.list_handlers(),
                # Passed straight from the "Add mapping" button's query string
                # (set from template.format already in context there) so this
                # GET doesn't need its own extra API round trip just for this.
                "template_format": request.GET.get("template_format", ""),
            },
        )

    def post(self, request, template_id: int):
        data = {
            "source_field_id": int(request.POST.get("source_field_id")),
            "target_field": request.POST.get("target_field", ""),
            "handler_method": request.POST.get("handler_method", "direct"),
            "sheet_name": request.POST.get("sheet_name") or None,
        }
        mapping = api.create_mapping(
            template_id, request.supplier["supplier_account_id"], data
        )
        return render(
            request,
            "dashboard/_mapping_row.html",
            {
                "m": mapping,
                "template_id": template_id,
                "template_format": _template_format(request, template_id),
            },
        )


class MappingDeleteView(View):
    def post(self, request, template_id: int, mapping_id: int):
        api.delete_mapping(
            template_id, mapping_id, request.supplier["supplier_account_id"]
        )
        return HttpResponse("")
