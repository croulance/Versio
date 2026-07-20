def flatten_fields(fields: list) -> list:
    """Depth-first flatten of a source-fields tree (each dict has a 'children'
    list, per the API's SourceFieldSnapshot shape) into one flat list — each
    node keeps its already-computed 'path' from the API response."""
    flat = []
    for f in fields:
        flat.append(f)
        flat.extend(flatten_fields(f.get("children") or []))
    return flat
