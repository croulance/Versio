import apps.transformation.converters  # noqa: F401 — registers all converters
import apps.transformation.handlers  # noqa: F401 — registers all handlers
from apps.transformation.converters.xml_converter import XMLConverter
from apps.transformation.handlers.registry import all_handlers

_HANDLERS = all_handlers()


def _mapping(target_field, field, handler_method="direct"):
    return {
        "target_field": target_field,
        "source_field": field,
        "handler_method": handler_method,
        "handler_data": {"field": field},
    }


class TestXMLConverter:
    def test_convert_item_builds_record_block(self):
        item = {"producerName": "Acme"}
        mappings = [_mapping("Producer Name", "producerName")]

        record = XMLConverter(_HANDLERS).convert_item(item, mappings, metadata={})

        assert (
            record == "  <record>\n    <Producer_Name>Acme</Producer_Name>\n  </record>"
        )

    def test_target_field_spaces_become_underscores_in_tag(self):
        record = XMLConverter(_HANDLERS).convert_item(
            {"a": "1"}, [_mapping("Field With Spaces", "a")], metadata={}
        )
        assert "<Field_With_Spaces>" in record

    def test_special_characters_are_escaped(self):
        record = XMLConverter(_HANDLERS).convert_item(
            {"a": "Tom & Jerry <ok>"}, [_mapping("Name", "a")], metadata={}
        )
        assert "Tom &amp; Jerry &lt;ok&gt;" in record
        assert "<ok>" not in record.split("<Name>")[1]

    def test_none_value_renders_as_empty_element(self):
        record = XMLConverter(_HANDLERS).convert_item(
            {}, [_mapping("Missing", "does_not_exist")], metadata={}
        )
        assert "<Missing></Missing>" in record

    def test_open_stream_default_root(self):
        header = XMLConverter(_HANDLERS).open_stream({})
        assert header == '<?xml version="1.0" encoding="UTF-8"?>\n<records>'

    def test_open_stream_custom_root(self):
        header = XMLConverter(_HANDLERS).open_stream({"root_element": "plots"})
        assert header.endswith("<plots>")

    def test_close_stream_matches_root(self):
        assert (
            XMLConverter(_HANDLERS).close_stream({"root_element": "plots"})
            == "</plots>"
        )

    def test_separator_is_newline(self):
        assert XMLConverter(_HANDLERS).separator() == "\n"
