def resolve_path(data: dict, path: str):
    """Walk a dot-notation path into a nested dict, e.g. 'complianceStatus.label'.
    Returns None if any segment is missing or the value at that point isn't a
    dict. A single-segment path (no dot) is a flat top-level lookup — identical
    behavior to a plain dict.get() for every pre-existing, non-nested mapping."""
    current = data
    for segment in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current
