import json

import httpx
from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from apps.dashboard import api_client as api
from apps.dashboard.views.guards import is_editable, owns_template
from apps.dashboard.views.source_fields import FIELD_TYPES

TEMPLATE_FORMATS = ["geojson", "csv", "xml", "xlsx"]


def _metadata_text(template: dict) -> str:
    return json.dumps(template.get("metadata") or {}, indent=2)


def _enrich_template(template: dict, supplier_account_id: int) -> dict:
    tid = template["id"]
    template["source_fields"] = api.list_source_fields(tid, supplier_account_id)
    template["mappings"] = api.list_mappings(tid, supplier_account_id)
    template["editable"] = is_editable(template)
    template["metadata_text"] = _metadata_text(template)
    return template


def _render_editor(request, template_id: int) -> HttpResponse:
    supplier_account_id = request.supplier["supplier_account_id"]
    template = _enrich_template(
        api.get_template(template_id, supplier_account_id), supplier_account_id
    )
    return render(
        request,
        "dashboard/_editor.html",
        {
            "template": template,
            "handlers": api.list_handlers(),
            "field_types": FIELD_TYPES,
        },
    )


# ── Dashboard main ─────────────────────────────────────────────────────────────


class TemplateDashboardView(View):
    def get(self, request):
        supplier_id = request.supplier["supplier_id"]
        status_filter = request.GET.get("status") or ""
        ordering = request.GET.get("ordering") or ""
        templates = api.list_templates(
            supplier_id=supplier_id,
            status=status_filter or None,
            ordering=ordering or None,
        )

        active_id = request.GET.get("t")
        active = None
        if active_id and not request.headers.get("HX-Request"):
            template = api.get_template(
                int(active_id), request.supplier["supplier_account_id"]
            )
            if template and template["supplier"]["id"] == supplier_id:
                active = _enrich_template(
                    template, request.supplier["supplier_account_id"]
                )

        ctx = {
            "templates": templates,
            "active": active,
            "active_id": active_id,
            "status_filter": status_filter,
            "ordering": ordering,
            "handlers": api.list_handlers(),
            "field_types": FIELD_TYPES,
            "active_nav": "templates",
        }

        if request.headers.get("HX-Request"):
            return render(request, "dashboard/_template_list.html", ctx)
        return render(request, "dashboard/templates.html", ctx)


class TemplateCreateView(View):
    def get(self, request):
        return render(
            request,
            "dashboard/_template_create_form.html",
            {
                "formats": TEMPLATE_FORMATS,
            },
        )

    def post(self, request):
        format = request.POST.get("format", "")
        version = int(request.POST.get("version") or 1)
        name = request.POST.get("name", "")
        try:
            template = api.create_template(
                supplier_account_id=request.supplier["supplier_account_id"],
                format=format,
                version=version,
                name=name,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise
            return render(
                request,
                "dashboard/_template_create_form.html",
                {
                    "formats": TEMPLATE_FORMATS,
                    "format": format,
                    "version": version,
                    "name": name,
                    "field_error": f"A {format} template already exists at version {version} — pick a different version.",
                },
            )
        response = HttpResponse(status=204)
        response["HX-Redirect"] = f"/templates/?t={template['id']}"
        return response


class TemplateEditorView(View):
    def get(self, request, template_id: int):
        supplier_account_id = request.supplier["supplier_account_id"]
        template = api.get_template(template_id, supplier_account_id)
        if not owns_template(request, template):
            return HttpResponse(status=403)
        template = _enrich_template(template, supplier_account_id)
        return render(
            request,
            "dashboard/_editor.html",
            {
                "template": template,
                "handlers": api.list_handlers(),
                "field_types": FIELD_TYPES,
            },
        )


# ── Template lifecycle ─────────────────────────────────────────────────────────


class TemplatePublishView(View):
    def post(self, request, template_id: int):
        supplier_account_id = request.supplier["supplier_account_id"]
        template = api.get_template(template_id, supplier_account_id)
        if not owns_template(request, template):
            return HttpResponse(status=403)
        api.publish_template(template_id, supplier_account_id)
        return _render_editor(request, template_id)


class TemplateDeprecateView(View):
    def post(self, request, template_id: int):
        supplier_account_id = request.supplier["supplier_account_id"]
        template = api.get_template(template_id, supplier_account_id)
        if not owns_template(request, template):
            return HttpResponse(status=403)
        api.deprecate_template(template_id, supplier_account_id)
        return _render_editor(request, template_id)


class TemplateRevertToDraftView(View):
    def post(self, request, template_id: int):
        supplier_account_id = request.supplier["supplier_account_id"]
        template = api.get_template(template_id, supplier_account_id)
        if not owns_template(request, template):
            return HttpResponse(status=403)
        api.revert_template_to_draft(template_id, supplier_account_id)
        return _render_editor(request, template_id)


# ── Single-field autosave (name / source_path / metadata) ─────────────────────


def _parse_metadata(raw: str) -> dict:
    raw = raw.strip() or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON — changes not saved.")


def _save_template_field(
    request, template_id: int, field: str, display_template: str, parse=None
) -> HttpResponse:
    """Shared handler behind the header-level autosave inputs (name,
    source_path, metadata). `parse`, when given, converts the raw POST value
    and may raise ValueError with a user-facing message to reject it before
    it's ever sent upstream (e.g. malformed metadata JSON)."""
    supplier_account_id = request.supplier["supplier_account_id"]
    template = api.get_template(template_id, supplier_account_id)
    if not owns_template(request, template):
        return HttpResponse(status=403)

    raw = request.POST.get(field, "")
    if parse:
        try:
            value = parse(raw)
        except ValueError as exc:
            template["editable"] = is_editable(template)
            if field == "metadata":
                template["metadata_text"] = raw
            return render(
                request,
                display_template,
                {"template": template, "field_error": str(exc)},
            )
    else:
        value = raw

    try:
        template = api.update_template(template_id, supplier_account_id, {field: value})
    except httpx.HTTPStatusError:
        # Most likely a 409: the template was published/deprecated elsewhere
        # between the page loading and this save. Re-fetch to show its real
        # current state instead of crashing.
        template = api.get_template(template_id, supplier_account_id)
        template["editable"] = is_editable(template)
        if field == "metadata":
            template["metadata_text"] = _metadata_text(template)
        return render(
            request,
            display_template,
            {
                "template": template,
                "field_error": "Could not save — this template may have changed. Refresh and try again.",
            },
        )

    template["editable"] = is_editable(template)
    if field == "metadata":
        template["metadata_text"] = _metadata_text(template)
    return render(request, display_template, {"template": template, "saved": True})


class TemplateNameView(View):
    def post(self, request, template_id: int):
        return _save_template_field(
            request, template_id, "name", "dashboard/_name_display.html"
        )


class TemplateSourcePathView(View):
    def post(self, request, template_id: int):
        return _save_template_field(
            request, template_id, "source_path", "dashboard/_source_path_display.html"
        )


class TemplateMetadataView(View):
    def post(self, request, template_id: int):
        return _save_template_field(
            request,
            template_id,
            "metadata",
            "dashboard/_metadata_display.html",
            parse=_parse_metadata,
        )
