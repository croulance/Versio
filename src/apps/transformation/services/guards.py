def editable_conflict(repo, template) -> str | None:
    """Return a 409-worthy error message if the template is not editable, else None."""
    if repo.is_editable(template):
        return None
    return f"Template is {template.status} and cannot be edited"
