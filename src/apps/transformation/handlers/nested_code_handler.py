from apps.transformation.interfaces.handler import FieldHandler

from .registry import register_handler


@register_handler
class NestedCodeHandler(FieldHandler):
    """Extracts the code from a nested status object, e.g. complianceStatus.masterPlotComplianceStatusCode."""

    name = "nested_code"

    def apply(self, source_data: dict, handler_data: dict | None) -> str | None:
        field = handler_data.get("field") if handler_data else None
        code_key = handler_data.get("code_key") if handler_data else None
        if not field or not code_key:
            return None
        nested = source_data.get(field)
        if not isinstance(nested, dict):
            return None
        return nested.get(code_key)
