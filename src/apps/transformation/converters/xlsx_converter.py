from apps.transformation.interfaces.converter import ConverterInterface
from apps.transformation.interfaces.handler import FieldHandler

from .registry import register_converter

_DEFAULT_SHEET = "Export"


@register_converter
class XLSXConverter(ConverterInterface):
    """
    XLSX converter returns a dict of rows keyed by sheet name:
    {sheet_name: {target_field: value, ...}, ...}. Each mapping declares
    which sheet its column belongs to (FieldMapping.sheet_name, required for
    xlsx mappings going forward -- see MappingService) so a single item can
    contribute columns to more than one output sheet.
    The task detects the type via isinstance(converter, StreamingConverterInterface)
    and routes to _flush_xlsx, which assembles the openpyxl workbook.
    Does not implement the streaming interface — XLSX is not text-based.
    """

    format = "xlsx"

    def __init__(self, handlers: dict[str, FieldHandler]):
        self._handlers = handlers

    def convert_item(self, item: dict, field_mappings: list, metadata: dict) -> dict:
        sheets: dict[str, dict] = {}
        for mapping in field_mappings:
            handler = self._handlers[mapping["handler_method"]]
            value = handler.apply(
                item, mapping.get("handler_data") or {"field": mapping["source_field"]}
            )
            # Falls back to a default sheet only for mappings created before
            # sheet_name existed -- new/edited xlsx mappings require it
            # (MappingService), this is a read-path safety net, not a
            # supported ongoing pattern.
            sheet = mapping.get("sheet_name") or _DEFAULT_SHEET
            sheets.setdefault(sheet, {})[mapping["target_field"]] = value
        return sheets
