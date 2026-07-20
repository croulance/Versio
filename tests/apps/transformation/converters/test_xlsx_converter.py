import apps.transformation.converters  # noqa: F401 — registers all converters
import apps.transformation.handlers  # noqa: F401 — registers all handlers
from apps.transformation.converters.xlsx_converter import XLSXConverter
from apps.transformation.handlers.registry import all_handlers
from apps.transformation.interfaces.converter import \
    StreamingConverterInterface

_HANDLERS = all_handlers()


def _mapping(target_field, field, sheet_name="Export", handler_method="direct"):
    return {
        "target_field": target_field,
        "source_field": field,
        "handler_method": handler_method,
        "handler_data": {"field": field},
        "sheet_name": sheet_name,
    }


class TestXLSXConverter:
    def test_convert_item_returns_a_dict_of_rows_keyed_by_sheet(self):
        item = {"producerName": "Acme", "area": "12.5"}
        mappings = [_mapping("Producer Name", "producerName"), _mapping("Area", "area")]

        row = XLSXConverter(_HANDLERS).convert_item(item, mappings, metadata={})

        assert row == {"Export": {"Producer Name": "Acme", "Area": "12.5"}}

    def test_missing_field_yields_none_value(self):
        row = XLSXConverter(_HANDLERS).convert_item(
            {}, [_mapping("Missing", "does_not_exist")], metadata={}
        )
        assert row == {"Export": {"Missing": None}}

    def test_mappings_with_different_sheet_names_split_into_separate_sheets(self):
        # A mapping declares which output sheet its column belongs to
        # (FieldMapping.sheet_name) -- a single item can contribute columns
        # to more than one sheet in the generated workbook.
        item = {"producerName": "Acme", "area": "12.5"}
        mappings = [
            _mapping("Producer Name", "producerName", sheet_name="Identity"),
            _mapping("Area", "area", sheet_name="Metrics"),
        ]

        row = XLSXConverter(_HANDLERS).convert_item(item, mappings, metadata={})

        assert row == {
            "Identity": {"Producer Name": "Acme"},
            "Metrics": {"Area": "12.5"},
        }

    def test_mapping_without_a_sheet_name_falls_back_to_export(self):
        # Read-path safety net for mappings created before sheet_name
        # existed -- new/edited xlsx mappings require it (MappingService).
        item = {"producerName": "Acme"}
        mapping = _mapping("Producer Name", "producerName", sheet_name=None)

        row = XLSXConverter(_HANDLERS).convert_item(item, [mapping], metadata={})

        assert row == {"Export": {"Producer Name": "Acme"}}

    def test_is_not_a_streaming_converter(self):
        assert not isinstance(XLSXConverter(_HANDLERS), StreamingConverterInterface)
