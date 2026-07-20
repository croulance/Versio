import json

import pytest

from apps.transformation.handlers import (CentroidFromPolygonHandler,
                                          CentroidLatitudeHandler,
                                          CentroidLongitudeHandler,
                                          DirectHandler,
                                          GeoJsonGeometryHandler,
                                          NestedCodeHandler,
                                          StringToBoolHandler)
from apps.transformation.handlers.path_utils import resolve_path
from apps.transformation.handlers.registry import (all_handlers, list_handlers,
                                                   register_handler)


class TestResolvePath:
    def test_single_segment_is_a_flat_lookup(self):
        assert resolve_path({"name": "Acme"}, "name") == "Acme"

    def test_missing_top_level_key_returns_none(self):
        assert resolve_path({"name": "Acme"}, "missing") is None

    def test_nested_leaf_is_resolved(self):
        data = {"complianceStatus": {"code": "PENDING", "label": "Pending"}}
        assert resolve_path(data, "complianceStatus.label") == "Pending"

    def test_missing_nested_key_returns_none(self):
        assert resolve_path({"complianceStatus": {}}, "complianceStatus.label") is None

    def test_missing_intermediate_object_returns_none(self):
        assert resolve_path({}, "complianceStatus.label") is None

    def test_intermediate_value_not_a_dict_returns_none(self):
        assert resolve_path({"complianceStatus": "flat"}, "complianceStatus.label") is None

    def test_arbitrary_depth(self):
        data = {"a": {"b": {"c": {"d": "deep"}}}}
        assert resolve_path(data, "a.b.c.d") == "deep"


class TestDirectHandler:
    def test_returns_field_value(self):
        result = DirectHandler().apply(
            {"producerName": "Acme"}, {"field": "producerName"}
        )
        assert result == "Acme"

    def test_missing_field_returns_none(self):
        result = DirectHandler().apply(
            {"producerName": "Acme"}, {"field": "missingField"}
        )
        assert result is None

    def test_no_field_in_handler_data_returns_none(self):
        assert DirectHandler().apply({"name": "Acme"}, {}) is None
        assert DirectHandler().apply({"name": "Acme"}, None) is None

    def test_resolves_a_nested_leaf_by_dot_path(self):
        source = {"complianceStatus": {"code": "PENDING", "label": "Pending"}}
        result = DirectHandler().apply(
            source, {"field": "complianceStatus.label"}
        )
        assert result == "Pending"

    def test_returns_a_nested_object_whole_when_path_is_the_branch(self):
        source = {"complianceStatus": {"code": "PENDING", "label": "Pending"}}
        result = DirectHandler().apply(source, {"field": "complianceStatus"})
        assert result == {"code": "PENDING", "label": "Pending"}


class TestCentroidFromPolygonHandler:
    def test_returns_existing_geo_location_coordinates_untouched(self):
        source = {"geoLocationCoordinates": "POINT (1 2)", "polygon": "[[0,0],[1,1]]"}
        result = CentroidFromPolygonHandler().apply(source, None)
        assert result == "POINT (1 2)"

    def test_computes_centroid_from_polygon(self):
        polygon = json.dumps([[0, 0], [2, 0], [2, 2], [0, 2]])
        source = {"geoLocationCoordinates": "", "polygon": polygon}
        result = CentroidFromPolygonHandler().apply(source, None)
        assert result == "POINT (1.000000 1.000000)"

    def test_missing_polygon_returns_empty_string(self):
        result = CentroidFromPolygonHandler().apply({}, None)
        assert result == ""

    def test_invalid_polygon_json_returns_empty_string(self):
        result = CentroidFromPolygonHandler().apply({"polygon": "not-json"}, None)
        assert result == ""

    def test_empty_polygon_list_returns_empty_string(self):
        result = CentroidFromPolygonHandler().apply({"polygon": "[]"}, None)
        assert result == ""

    def test_polygon_as_an_already_parsed_list_computes_the_centroid_directly(self):
        # Regression test: an `object`-typed source field with no declared
        # children (an opaque, unvalidated blob) reaches this handler
        # unchanged -- if the raw item's `polygon` value is already a parsed
        # list (not a JSON string), json.loads() used to raise TypeError,
        # which wasn't in this handler's except tuple (same bug shape as the
        # NestedCodeHandler fix). Fixed the same way
        # GeoJsonGeometryHandler already handles this: a non-string value is
        # treated as already-parsed rather than as an error, so a genuinely
        # valid pre-parsed polygon still computes a real centroid instead of
        # being defensively discarded.
        result = CentroidFromPolygonHandler().apply(
            {"polygon": [[0, 0], [1, 1], [1, 0]]}, None
        )
        assert result == "POINT (0.666667 0.333333)"

    def test_polygon_as_a_dict_returns_empty_string_instead_of_crashing(self):
        # A dict isn't a valid coordinate list either way -- this exercises
        # the same non-string branch but with genuinely malformed data,
        # confirming it still fails safe (empty string) rather than crashing.
        result = CentroidFromPolygonHandler().apply({"polygon": {"not": "a list"}}, None)
        assert result == ""


class TestCentroidLatitudeLongitudeHandlers:
    def test_latitude_from_geo_location_coordinates(self):
        source = {"geoLocationCoordinates": "POINT (1 2)", "polygon": "[[0,0],[9,9]]"}
        assert CentroidLatitudeHandler().apply(source, None) == 2.0

    def test_longitude_from_geo_location_coordinates(self):
        source = {"geoLocationCoordinates": "POINT (1 2)", "polygon": "[[0,0],[9,9]]"}
        assert CentroidLongitudeHandler().apply(source, None) == 1.0

    def test_latitude_falls_back_to_polygon_centroid(self):
        polygon = json.dumps([[0, 0], [2, 0], [2, 2], [0, 2]])
        source = {"geoLocationCoordinates": "", "polygon": polygon}
        assert CentroidLatitudeHandler().apply(source, None) == 1.0

    def test_longitude_falls_back_to_polygon_centroid(self):
        polygon = json.dumps([[0, 0], [2, 0], [2, 2], [0, 2]])
        source = {"geoLocationCoordinates": "", "polygon": polygon}
        assert CentroidLongitudeHandler().apply(source, None) == 1.0

    def test_missing_polygon_and_geo_location_returns_none(self):
        assert CentroidLatitudeHandler().apply({}, None) is None
        assert CentroidLongitudeHandler().apply({}, None) is None

    def test_invalid_polygon_json_returns_none(self):
        assert CentroidLatitudeHandler().apply({"polygon": "not-json"}, None) is None
        assert CentroidLongitudeHandler().apply({"polygon": "not-json"}, None) is None


class TestGeoJsonGeometryHandler:
    def test_wraps_polygon_into_multipolygon(self):
        feature = {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 0]]],
            }
        }
        source = {"plotGeoJson": json.dumps(feature)}
        result = GeoJsonGeometryHandler().apply(source, None)
        assert result == {
            "type": "MultiPolygon",
            "coordinates": [[[[0, 0], [1, 1], [1, 0], [0, 0]]]],
        }

    def test_non_polygon_geometry_passes_through(self):
        feature = {"geometry": {"type": "Point", "coordinates": [1, 2]}}
        source = {"plotGeoJson": json.dumps(feature)}
        result = GeoJsonGeometryHandler().apply(source, None)
        assert result == {"type": "Point", "coordinates": [1, 2]}

    def test_missing_field_returns_empty_dict(self):
        assert GeoJsonGeometryHandler().apply({}, None) == {}

    def test_invalid_json_returns_empty_dict(self):
        assert GeoJsonGeometryHandler().apply({"plotGeoJson": "{bad"}, None) == {}


class TestStringToBoolHandler:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("yes", True),
            ("Yes", True),
            ("YES", True),
            ("no", False),
            ("", False),
            ("maybe", False),
        ],
    )
    def test_conversion(self, raw, expected):
        result = StringToBoolHandler().apply({"flag": raw}, {"field": "flag"})
        assert result is expected

    def test_missing_field_treated_as_false(self):
        assert StringToBoolHandler().apply({}, {"field": "flag"}) is False

    def test_resolves_a_nested_leaf_by_dot_path(self):
        source = {"complianceStatus": {"isActive": "yes"}}
        result = StringToBoolHandler().apply(
            source, {"field": "complianceStatus.isActive"}
        )
        assert result is True


class TestNestedCodeHandler:
    def test_extracts_nested_code(self):
        source = {"complianceStatus": {"masterPlotComplianceStatusCode": "OK"}}
        result = NestedCodeHandler().apply(
            source,
            {"field": "complianceStatus", "code_key": "masterPlotComplianceStatusCode"},
        )
        assert result == "OK"

    def test_missing_nested_object_returns_none(self):
        result = NestedCodeHandler().apply(
            {}, {"field": "complianceStatus", "code_key": "code"}
        )
        assert result is None

    def test_missing_handler_data_keys_returns_none(self):
        assert (
            NestedCodeHandler().apply(
                {"complianceStatus": {"code": "OK"}}, {"field": "complianceStatus"}
            )
            is None
        )
        assert (
            NestedCodeHandler().apply({"complianceStatus": {"code": "OK"}}, None)
            is None
        )

    def test_non_dict_nested_value_returns_none_instead_of_crashing(self):
        # Regression test: an `object`-typed source field with no declared
        # children (an opaque, unvalidated blob) isn't checked by
        # the validator, so a source item where this field is a truthy
        # non-dict (a stray string, a list -- a real-world data-quality
        # issue, not a hypothetical) used to reach `.get()` on it and raise
        # AttributeError, crashing every other item in the same chunk.
        assert (
            NestedCodeHandler().apply(
                {"complianceStatus": "not-an-object"},
                {"field": "complianceStatus", "code_key": "code"},
            )
            is None
        )
        assert (
            NestedCodeHandler().apply(
                {"complianceStatus": ["also", "not", "an", "object"]},
                {"field": "complianceStatus", "code_key": "code"},
            )
            is None
        )


class TestHandlerRegistry:
    def test_all_expected_handlers_are_registered(self):
        assert list_handlers() == sorted(
            [
                "direct",
                "centroid_from_polygon",
                "centroid_latitude",
                "centroid_longitude",
                "parse_geojson_geometry",
                "string_to_bool",
                "nested_code",
            ]
        )

    def test_all_handlers_returns_one_fresh_map_each_call(self):
        first = all_handlers()
        second = all_handlers()
        assert isinstance(first["direct"], DirectHandler)
        assert first["direct"] is not second["direct"]  # each call builds new instances

    def test_register_handler_rejects_duplicate_name(self):
        class _Dummy:
            name = "__test_dummy_handler__"

            def apply(self, source_data, handler_data):
                return None

        register_handler(_Dummy)
        try:
            with pytest.raises(TypeError):
                register_handler(_Dummy)
        finally:
            from apps.transformation.handlers import registry

            registry._registry.pop("__test_dummy_handler__", None)
