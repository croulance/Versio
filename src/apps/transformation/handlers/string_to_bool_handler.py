from apps.transformation.interfaces.handler import FieldHandler

from .path_utils import resolve_path
from .registry import register_handler


@register_handler
class StringToBoolHandler(FieldHandler):
    """Converts 'yes'/'no' string to boolean. `handler_data['field']` may be a
    dot-path for a nested leaf, same as DirectHandler."""

    name = "string_to_bool"

    def apply(self, source_data: dict, handler_data: dict | None) -> bool:
        field = handler_data.get("field") if handler_data else None
        value = resolve_path(source_data, field) if field else None
        return str(value or "").lower() == "yes"
