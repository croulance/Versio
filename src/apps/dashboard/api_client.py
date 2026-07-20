import httpx
from django.conf import settings


def _base() -> str:
    return settings.TRANSFORMATION_API_URL.rstrip("/") + "/api"


def _headers() -> dict:
    """The dashboard is a trusted internal caller — it authenticates itself
    with a shared service token, never with the supplier's own session token."""
    return {"Authorization": f"Bearer {settings.INTERNAL_SERVICE_TOKEN}"}


def _get(path: str, params: dict = None) -> httpx.Response:
    return httpx.get(f"{_base()}{path}", params=params, headers=_headers(), timeout=10)


def _post(path: str, json: dict = None) -> httpx.Response:
    return httpx.post(f"{_base()}{path}", json=json, headers=_headers(), timeout=10)


def _patch(path: str, json: dict) -> httpx.Response:
    return httpx.patch(f"{_base()}{path}", json=json, headers=_headers(), timeout=10)


def _delete(path: str, json: dict = None) -> httpx.Response:
    return httpx.request(
        "DELETE", f"{_base()}{path}", json=json, headers=_headers(), timeout=10
    )


def _json(response: httpx.Response):
    """Raise loudly on an unexpected upstream error instead of returning its
    error body as if it were the requested resource."""
    response.raise_for_status()
    return response.json()


# ── Suppliers ─────────────────────────────────────────────────────────────────


def list_suppliers() -> list:
    return _json(_get("/suppliers/"))


# ── Templates ─────────────────────────────────────────────────────────────────


def list_templates(
    supplier_id: int | None = None,
    status: str | None = None,
    ordering: str | None = None,
) -> list:
    params = {}
    if supplier_id:
        params["supplier_id"] = supplier_id
    if status:
        params["status"] = status
    if ordering:
        params["ordering"] = ordering
    return _json(_get("/templates/", params=params or None))


def get_template(template_id: int, supplier_account_id: int) -> dict:
    return _json(
        _get(
            f"/templates/{template_id}/",
            params={"supplier_account_id": supplier_account_id},
        )
    )


def create_template(
    supplier_account_id: int, format: str, version: int, name: str
) -> dict:
    return _json(
        _post(
            "/templates/",
            json={
                "supplier_account_id": supplier_account_id,
                "format": format,
                "version": version,
                "name": name,
            },
        )
    )


def update_template(template_id: int, supplier_account_id: int, data: dict) -> dict:
    return _json(
        _patch(
            f"/templates/{template_id}/",
            json={**data, "supplier_account_id": supplier_account_id},
        )
    )


def publish_template(template_id: int, supplier_account_id: int) -> httpx.Response:
    return _post(
        f"/templates/{template_id}/publish/",
        json={"supplier_account_id": supplier_account_id},
    )


def deprecate_template(template_id: int, supplier_account_id: int) -> httpx.Response:
    return _post(
        f"/templates/{template_id}/deprecate/",
        json={"supplier_account_id": supplier_account_id},
    )


def revert_template_to_draft(
    template_id: int, supplier_account_id: int
) -> httpx.Response:
    return _post(
        f"/templates/{template_id}/revert-to-draft/",
        json={"supplier_account_id": supplier_account_id},
    )


# ── Source fields ─────────────────────────────────────────────────────────────


def list_source_fields(template_id: int, supplier_account_id: int) -> list:
    return _json(
        _get(
            f"/templates/{template_id}/source-fields/",
            params={"supplier_account_id": supplier_account_id},
        )
    )


def create_source_field(template_id: int, supplier_account_id: int, data: dict) -> dict:
    return _json(
        _post(
            f"/templates/{template_id}/source-fields/",
            json={**data, "supplier_account_id": supplier_account_id},
        )
    )


def update_source_field(
    template_id: int, field_id: int, supplier_account_id: int, data: dict
) -> dict:
    return _json(
        _patch(
            f"/templates/{template_id}/source-fields/{field_id}/",
            json={**data, "supplier_account_id": supplier_account_id},
        )
    )


def delete_source_field(
    template_id: int, field_id: int, supplier_account_id: int
) -> int:
    return _delete(
        f"/templates/{template_id}/source-fields/{field_id}/",
        json={"supplier_account_id": supplier_account_id},
    ).status_code


# ── Mappings ──────────────────────────────────────────────────────────────────


def list_mappings(template_id: int, supplier_account_id: int) -> list:
    return _json(
        _get(
            f"/templates/{template_id}/mappings/",
            params={"supplier_account_id": supplier_account_id},
        )
    )


def create_mapping(template_id: int, supplier_account_id: int, data: dict) -> dict:
    return _json(
        _post(
            f"/templates/{template_id}/mappings/",
            json={**data, "supplier_account_id": supplier_account_id},
        )
    )


def update_mapping(
    template_id: int, mapping_id: int, supplier_account_id: int, data: dict
) -> dict:
    return _json(
        _patch(
            f"/templates/{template_id}/mappings/{mapping_id}/",
            json={**data, "supplier_account_id": supplier_account_id},
        )
    )


def delete_mapping(template_id: int, mapping_id: int, supplier_account_id: int) -> int:
    return _delete(
        f"/templates/{template_id}/mappings/{mapping_id}/",
        json={"supplier_account_id": supplier_account_id},
    ).status_code


# ── Handlers ──────────────────────────────────────────────────────────────────


def list_handlers() -> list:
    return _json(_get("/handlers/"))


# ── Batches ───────────────────────────────────────────────────────────────────


def submit_batch(supplier_account_id: int, template_id: int, file_obj) -> dict | None:
    """POST /api/transform/ using the internal service token — the dashboard
    has already verified the supplier via their own session token, so it
    vouches for supplier_account_id here."""
    r = httpx.post(
        f"{_base()}/transform/",
        headers=_headers(),
        data={
            "supplier_account_id": str(supplier_account_id),
            "template_id": str(template_id),
        },
        files={"file": (file_obj.name, file_obj, file_obj.content_type)},
        timeout=180,
    )
    return r.json() if r.status_code in (200, 202) else None


def get_batch(job_id: str, supplier_account_id: int) -> dict | None:
    r = _get(f"/jobs/{job_id}/", params={"supplier_account_id": supplier_account_id})
    return r.json() if r.status_code == 200 else None


def list_batches(
    supplier_account_id: int,
    status: str | None = None,
    page: int = 1,
    ordering: str | None = None,
) -> dict:
    params = {"supplier_account_id": supplier_account_id, "page": page}
    if status:
        params["status"] = status
    if ordering:
        params["ordering"] = ordering
    return _json(_get("/jobs/", params=params))


def download_source(job_id: str, supplier_account_id: int) -> httpx.Response:
    return _get(
        f"/jobs/{job_id}/download-source/",
        params={"supplier_account_id": supplier_account_id},
    )


def download_result(job_id: str, supplier_account_id: int) -> httpx.Response:
    return _get(
        f"/jobs/{job_id}/download/",
        params={"supplier_account_id": supplier_account_id},
    )


def download_errors(job_id: str, supplier_account_id: int) -> httpx.Response:
    return _get(
        f"/jobs/{job_id}/download-errors/",
        params={"supplier_account_id": supplier_account_id},
    )
