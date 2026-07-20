import io
import json

from apps.transformation.mergers.geojson_merger import GeoJsonMerger


class FakeStorage:
    def __init__(self, objects: dict):
        self._objects = objects

    def get_object(self, key):
        return io.BytesIO(self._objects[key])


def _chunk_doc(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode(
        "utf-8"
    )


class TestGeoJsonMerger:
    def test_combines_features_from_all_chunks(self):
        storage = FakeStorage(
            {
                "c1": _chunk_doc([{"type": "Feature", "properties": {"name": "Acme"}}]),
                "c2": _chunk_doc([{"type": "Feature", "properties": {"name": "Beta"}}]),
            }
        )
        merger = GeoJsonMerger(storage)

        result = json.loads(merger.merge(["c1", "c2"], metadata={}))

        assert result["type"] == "FeatureCollection"
        assert [f["properties"]["name"] for f in result["features"]] == ["Acme", "Beta"]

    def test_default_crs_and_name(self):
        storage = FakeStorage({"c1": _chunk_doc([])})
        merger = GeoJsonMerger(storage)

        result = json.loads(merger.merge(["c1"], metadata={}))

        assert result["name"] == "Versio Export"
        assert result["crs"]["properties"]["name"] == "urn:ogc:def:crs:OGC:1.3:CRS84"

    def test_metadata_overrides_crs_and_name(self):
        storage = FakeStorage({"c1": _chunk_doc([])})
        merger = GeoJsonMerger(storage)
        metadata = {
            "name": "Peru Export",
            "crs": {"type": "name", "properties": {"name": "CRS999"}},
        }

        result = json.loads(merger.merge(["c1"], metadata=metadata))

        assert result["name"] == "Peru Export"
        assert result["crs"]["properties"]["name"] == "CRS999"

    def test_empty_chunk_list_produces_empty_feature_collection(self):
        storage = FakeStorage({})
        merger = GeoJsonMerger(storage)

        result = json.loads(merger.merge([], metadata={}))

        assert result == {
            "type": "FeatureCollection",
            "name": "Versio Export",
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
            },
            "features": [],
        }
