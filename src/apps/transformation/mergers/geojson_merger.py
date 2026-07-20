import json

from apps.transformation.interfaces.merger import MergerInterface
from apps.transformation.interfaces.storage import StorageInterface

from .registry import register_merger


@register_merger
class GeoJsonMerger(MergerInterface):
    format = "geojson"

    def __init__(self, storage: StorageInterface):
        self._storage = storage

    def merge(self, keys: list[str], metadata: dict) -> bytes:
        features = []
        for key in keys:
            doc = json.loads(self._storage.get_object(key).read().decode("utf-8"))
            features.extend(doc.get("features", []))

        crs = metadata.get(
            "crs",
            {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
            },
        )
        collection = {
            "type": "FeatureCollection",
            "name": metadata.get("name", "Versio Export"),
            "crs": crs,
            "features": features,
        }
        return json.dumps(collection, ensure_ascii=False).encode("utf-8")
