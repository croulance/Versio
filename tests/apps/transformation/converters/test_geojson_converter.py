import json

import apps.transformation.converters  # noqa: F401 — registers all converters
import apps.transformation.handlers  # noqa: F401 — registers all handlers
from apps.transformation.converters.geojson_converter import GeoJSONConverter
from apps.transformation.handlers.registry import all_handlers

_HANDLERS = all_handlers()


def _mapping(target_field, field, handler_method="direct"):
    return {
        "target_field": target_field,
        "source_field": field,
        "handler_method": handler_method,
        "handler_data": {"field": field},
    }


class TestGeoJSONConverter:
    def test_convert_item_splits_geometry_from_properties(self):
        item = {"producerName": "Acme", "plotGeoJson": None}
        mappings = [
            _mapping("producerName", "producerName"),
            _mapping(
                "__geometry__", "plotGeoJson", handler_method="parse_geojson_geometry"
            ),
        ]

        feature = GeoJSONConverter(_HANDLERS).convert_item(item, mappings, metadata={})

        assert feature["type"] == "Feature"
        assert feature["properties"] == {"producerName": "Acme"}
        assert feature["geometry"] == {}

    def test_open_stream_default_crs(self):
        header = GeoJSONConverter(_HANDLERS).open_stream({})
        parsed = json.loads(header.split(', "features"')[0] + "}")
        assert parsed["type"] == "FeatureCollection"
        assert parsed["crs"]["properties"]["name"] == "urn:ogc:def:crs:OGC:1.3:CRS84"
        assert header.endswith(', "features": [')

    def test_open_stream_custom_crs_and_name(self):
        metadata = {
            "name": "Peru Export",
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS999"},
            },
        }
        header = GeoJSONConverter(_HANDLERS).open_stream(metadata)
        assert '"Peru Export"' in header
        assert "CRS999" in header

    def test_close_stream(self):
        assert GeoJSONConverter(_HANDLERS).close_stream({}) == "]}"

    def test_separator_is_comma(self):
        assert GeoJSONConverter(_HANDLERS).separator() == ","

    def test_full_stream_assembly_is_valid_json(self):
        converter = GeoJSONConverter(_HANDLERS)
        mappings = [_mapping("name", "producerName")]
        items = [{"producerName": "Acme"}, {"producerName": "Beta Farms"}]

        body = converter.separator().join(
            json.dumps(converter.convert_item(item, mappings, metadata={}))
            for item in items
        )
        full = converter.open_stream({}) + body + converter.close_stream({})

        parsed = json.loads(full)
        assert parsed["type"] == "FeatureCollection"
        assert [f["properties"]["name"] for f in parsed["features"]] == [
            "Acme",
            "Beta Farms",
        ]
