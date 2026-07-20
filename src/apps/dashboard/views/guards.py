def owns_template(request, template: dict | None) -> bool:
    return (
        bool(template) and template["supplier"]["id"] == request.supplier["supplier_id"]
    )


def is_editable(template: dict) -> bool:
    return template["status"] == "DRAFT"
