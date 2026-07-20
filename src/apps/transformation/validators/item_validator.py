import json
from datetime import date, datetime


class DynamicItemValidator:
    """
    Validates and coerces a raw item dict against a list of source field definition dicts.

    Field defs are plain dicts (from cache or repository) with keys:
      name, field_type, required, nullable, default_value,
      max_length, allowed_values, min_value, max_value, date_format,
      children (list of nested field defs, same shape — only meaningful when
      field_type == "object"; an object field with no children is validated as
      an opaque, unvalidated blob, same as before nested schemas existed)

    Returns (validated_data: dict, errors: dict). `validated_data` mirrors the
    input's nesting (an object field's value is itself a validated dict, keyed
    by the children's plain names). `errors` is flat, keyed by full dot-path
    (e.g. "complianceStatus.label") so a nested failure is unambiguous; empty
    on success.
    """

    def validate(
        self, item: dict, field_defs: list[dict], _prefix: str = ""
    ) -> tuple[dict, dict]:
        errors: dict = {}
        result: dict = {}

        for f in field_defs:
            name = f["name"]
            path = f"{_prefix}{name}"
            raw = item.get(name)

            # ── Absence ────────────────────────────────────────────────
            if raw is None:
                if f.get("required", True):
                    errors[path] = "required field is absent"
                    continue
                default = f.get("default_value")
                if default is not None:
                    result[name] = default
                continue

            # ── Null / empty value ─────────────────────────────────────
            if raw == "" or raw is None:
                if not f.get("nullable", False):
                    errors[path] = "non-nullable field received empty value"
                    continue
                result[name] = None
                continue

            # ── Type coercion ──────────────────────────────────────────
            try:
                coerced = self._coerce(raw, f)
            except (ValueError, TypeError) as exc:
                errors[path] = f"type error ({f['field_type']}): {exc}"
                continue

            # ── Recurse into a described nested object ────────────────
            children = f.get("children")
            if f["field_type"] == "object" and children:
                if not isinstance(coerced, dict):
                    errors[path] = "expected an object"
                    continue
                nested_result, nested_errors = self.validate(
                    coerced, children, _prefix=f"{path}."
                )
                if nested_errors:
                    errors.update(nested_errors)
                    continue
                result[name] = nested_result
                continue

            # ── Constraint validation ──────────────────────────────────
            err = self._check_constraints(coerced, f)
            if err:
                errors[path] = err
                continue

            result[name] = coerced

        return result, errors

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _coerce(self, value, f: dict):
        field_type = f["field_type"]

        match field_type:
            case "string" | "email" | "url":
                return str(value)
            case "number":
                return float(value)
            case "integer":
                return int(value)
            case "boolean":
                if isinstance(value, bool):
                    return value
                return str(value).lower() in ("true", "1", "yes")
            case "geojson" | "object":
                return json.loads(value) if isinstance(value, str) else value
            case "date":
                fmt = f.get("date_format") or None
                s = str(value)
                return (
                    datetime.strptime(s, fmt).date() if fmt else date.fromisoformat(s)
                )
            case "datetime":
                return datetime.fromisoformat(str(value))
            case _:
                return value

    def _check_constraints(self, value, f: dict) -> str | None:
        field_type = f["field_type"]

        if field_type in ("string", "email", "url"):
            max_len = f.get("max_length")
            if max_len and len(str(value)) > max_len:
                return f"exceeds max_length={max_len} (got {len(str(value))})"
            allowed = f.get("allowed_values") or []
            if allowed and value not in allowed:
                return f"'{value}' not in allowed values"

        if field_type in ("number", "integer"):
            min_v = f.get("min_value")
            max_v = f.get("max_value")
            if min_v is not None and value < min_v:
                return f"below min_value={min_v}"
            if max_v is not None and value > max_v:
                return f"above max_value={max_v}"

        return None
