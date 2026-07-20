import apps.transformation.converters  # noqa: F401 — registers all converters
import apps.transformation.handlers  # noqa: F401 — registers all handlers
from apps.transformation.converters.csv_converter import CSVConverter
from apps.transformation.handlers.registry import all_handlers

_HANDLERS = all_handlers()


def _mapping(target_field, field, handler_method="direct"):
    return {
        "target_field": target_field,
        "source_field": field,
        "handler_method": handler_method,
        "handler_data": {"field": field},
    }


class TestCSVConverter:
    def test_convert_item_builds_one_row(self):
        item = {"producerName": "Acme", "area": "12.5"}
        mappings = [_mapping("Producer Name", "producerName"), _mapping("Area", "area")]

        row = CSVConverter(_HANDLERS).convert_item(item, mappings, metadata={})

        assert row == "Acme,12.5"

    def test_convert_item_has_no_trailing_newline(self):
        row = CSVConverter(_HANDLERS).convert_item(
            {"a": "1"}, [_mapping("A", "a")], metadata={}
        )
        assert not row.endswith("\n")
        assert not row.endswith("\r")

    def test_open_stream_joins_headers_from_metadata(self):
        header = CSVConverter(_HANDLERS).open_stream(
            {"headers": ["Producer Name", "Area"]}
        )
        assert header == "Producer Name,Area\n"

    def test_open_stream_with_no_headers_metadata_is_just_newline(self):
        assert CSVConverter(_HANDLERS).open_stream({}) == "\n"

    def test_close_stream_is_empty(self):
        assert CSVConverter(_HANDLERS).close_stream({}) == ""

    def test_separator_is_newline(self):
        assert CSVConverter(_HANDLERS).separator() == "\n"
