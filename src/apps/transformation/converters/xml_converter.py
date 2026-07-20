from xml.sax.saxutils import escape

from apps.transformation.interfaces.converter import \
    StreamingConverterInterface
from apps.transformation.interfaces.handler import FieldHandler

from .registry import register_converter


@register_converter
class XMLConverter(StreamingConverterInterface):
    format = "xml"

    def __init__(self, handlers: dict[str, FieldHandler]):
        self._handlers = handlers

    def convert_item(self, item: dict, field_mappings: list, metadata: dict) -> str:
        lines = ["  <record>"]
        for mapping in field_mappings:
            handler = self._handlers[mapping["handler_method"]]
            value = handler.apply(
                item, mapping.get("handler_data") or {"field": mapping["source_field"]}
            )
            tag = mapping["target_field"].replace(" ", "_")
            safe_value = escape(str(value)) if value is not None else ""
            lines.append(f"    <{tag}>{safe_value}</{tag}>")
        lines.append("  </record>")
        return "\n".join(lines)

    def open_stream(self, metadata: dict) -> str:
        root = metadata.get("root_element", "records")
        return f'<?xml version="1.0" encoding="UTF-8"?>\n<{root}>'

    def close_stream(self, metadata: dict) -> str:
        root = metadata.get("root_element", "records")
        return f"</{root}>"

    def separator(self) -> str:
        return "\n"
