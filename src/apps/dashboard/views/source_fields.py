import json

from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from apps.dashboard import api_client as api
from apps.dashboard.field_tree import flatten_fields
from apps.dashboard.views.guards import is_editable

FIELD_TYPES = [
    "string",
    "number",
    "integer",
    "boolean",
    "date",
    "datetime",
    "geojson",
    "object",
    "email",
    "url",
]


def _parse_field_post(post) -> dict:
    """Parse all SourceFieldDefinition fields from a POST payload."""

    def _opt_int(key):
        v = post.get(key, "").strip()
        return int(v) if v else None

    def _opt_float(key):
        v = post.get(key, "").strip()
        return float(v) if v else None

    def _opt_json(key):
        v = post.get(key, "").strip()
        if not v:
            return None
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v

    allowed_raw = post.get("allowed_values", "").strip()
    allowed = [line.strip() for line in allowed_raw.splitlines() if line.strip()]

    return {
        "name": post.get("name", ""),
        "field_type": post.get("field_type", "string"),
        "parent_id": _opt_int("parent_id"),
        "required": post.get("required") == "on",
        "nullable": post.get("nullable") == "on",
        "description": post.get("description", ""),
        "order": _opt_int("order") or 0,
        "default_value": _opt_json("default_value"),
        "max_length": _opt_int("max_length"),
        "allowed_values": allowed,
        "min_value": _opt_float("min_value"),
        "max_value": _opt_float("max_value"),
        "date_format": post.get("date_format", ""),
    }


def _field_modal_ctx(
    field: dict | None,
    template_id: int,
    all_fields: list | None = None,
    fixed_parent: dict | None = None,
) -> dict:
    allowed_values_text = "\n".join(field.get("allowed_values") or []) if field else ""
    raw_default = field.get("default_value") if field else None
    default_value_json = json.dumps(raw_default) if raw_default is not None else ""

    # Parent is only settable at creation (the API doesn't support reparenting).
    # On add-a-child (via the "+" button on an object field's row), fixed_parent
    # is passed straight through — no picker, it's implicit from which row was
    # clicked. On edit, just show the existing parent (if any) as read-only context.
    parent_path = None
    if field is not None and field.get("parent_id") and all_fields is not None:
        flat = flatten_fields(all_fields)
        parent = next((f for f in flat if f["id"] == field["parent_id"]), None)
        parent_path = parent["path"] if parent else None

    return {
        "field": field,
        "template_id": template_id,
        "field_types": FIELD_TYPES,
        "allowed_values_text": allowed_values_text,
        "default_value_json": default_value_json,
        "fixed_parent": fixed_parent,
        "parent_path": parent_path,
    }


def _fields_body_response(request, template_id: int) -> HttpResponse:
    """Re-render the whole fields table body from a fresh fetch. A single-row
    swap can't correctly place a newly nested child near its parent, so every
    mutation just re-renders the full (small) tree instead of patching one row."""
    supplier_account_id = request.supplier["supplier_account_id"]
    fields = api.list_source_fields(template_id, supplier_account_id)
    template = api.get_template(template_id, supplier_account_id)
    response = render(
        request,
        "dashboard/_source_fields_body.html",
        {
            "fields": fields,
            "template_id": template_id,
            "editable": is_editable(template),
        },
    )
    response["HX-Trigger"] = "closeModal"
    return response


class SourceFieldRowView(View):
    def get(self, request, template_id: int, field_id: int):
        fields = api.list_source_fields(
            template_id, request.supplier["supplier_account_id"]
        )
        field = next((f for f in flatten_fields(fields) if f["id"] == field_id), None)
        return render(
            request,
            "dashboard/_source_field_row.html",
            {
                "field": field,
                "template_id": template_id,
            },
        )


class SourceFieldEditView(View):
    def get(self, request, template_id: int, field_id: int):
        fields = api.list_source_fields(
            template_id, request.supplier["supplier_account_id"]
        )
        field = next((f for f in flatten_fields(fields) if f["id"] == field_id), None)
        return render(
            request,
            "dashboard/_source_field_modal_form.html",
            _field_modal_ctx(field, template_id, fields),
        )

    def post(self, request, template_id: int, field_id: int):
        api.update_source_field(
            template_id,
            field_id,
            request.supplier["supplier_account_id"],
            _parse_field_post(request.POST),
        )
        return _fields_body_response(request, template_id)


class SourceFieldAddView(View):
    def get(self, request, template_id: int):
        fields = api.list_source_fields(
            template_id, request.supplier["supplier_account_id"]
        )
        fixed_parent = None
        parent_id = request.GET.get("parent_id")
        if parent_id:
            fixed_parent = next(
                (f for f in flatten_fields(fields) if str(f["id"]) == parent_id), None
            )
        return render(
            request,
            "dashboard/_source_field_modal_form.html",
            _field_modal_ctx(None, template_id, fields, fixed_parent=fixed_parent),
        )

    def post(self, request, template_id: int):
        api.create_source_field(
            template_id,
            request.supplier["supplier_account_id"],
            _parse_field_post(request.POST),
        )
        return _fields_body_response(request, template_id)


class SourceFieldDeleteView(View):
    def post(self, request, template_id: int, field_id: int):
        status_code = api.delete_source_field(
            template_id, field_id, request.supplier["supplier_account_id"]
        )
        if status_code == 409:
            return HttpResponse(
                '<tr><td colspan="7" class="px-4 py-3 text-center text-sm text-red-500">'
                "Cannot delete: this field is used in a mapping.</td></tr>"
            )
        return HttpResponse("")
