import csv
import io

from apps.transformation.interfaces.converter import \
    StreamingConverterInterface
from apps.transformation.interfaces.handler import FieldHandler

from .registry import register_converter


@register_converter
class CSVConverter(StreamingConverterInterface):
    format = "csv"

    def __init__(self, handlers: dict[str, FieldHandler]):
        self._handlers = handlers

    def convert_item(self, item: dict, field_mappings: list, metadata: dict) -> str:
        row = {}
        for mapping in field_mappings:
            handler = self._handlers[mapping["handler_method"]]
            value = handler.apply(
                item, mapping.get("handler_data") or {"field": mapping["source_field"]}
            )
            row[mapping["target_field"]] = value

        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=[m["target_field"] for m in field_mappings]
        )
        writer.writerow(row)
        return buf.getvalue().rstrip("\r\n")

    def open_stream(self, metadata: dict) -> str:
        headers = metadata.get("headers", [])
        return ",".join(headers) + "\n"

    def close_stream(self, metadata: dict) -> str:
        return ""

    def separator(self) -> str:
        return "\n"
