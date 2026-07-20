from apps.transformation.interfaces.handler import FieldHandler

from .path_utils import resolve_path
from .registry import register_handler


@register_handler
class DirectHandler(FieldHandler):
    """Returns the source field value as-is. `handler_data['field']` is the
    field's full dot-path (e.g. 'complianceStatus.label' for a nested leaf,
    just 'name' for a top-level field) — resolve_path makes both work identically."""

    name = "direct"

    def apply(self, source_data: dict, handler_data: dict | None) -> any:
        field = handler_data.get("field") if handler_data else None
        return resolve_path(source_data, field) if field else None
