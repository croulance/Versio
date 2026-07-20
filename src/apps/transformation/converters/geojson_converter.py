import json

from apps.transformation.interfaces.converter import \
    StreamingConverterInterface
from apps.transformation.interfaces.handler import FieldHandler

from .registry import register_converter


@register_converter
class GeoJSONConverter(StreamingConverterInterface):
    format = "geojson"

    def __init__(self, handlers: dict[str, FieldHandler]):
        self._handlers = handlers

    def convert_item(self, item: dict, field_mappings: list, metadata: dict) -> dict:
        properties = {}
        geometry = {}

        for mapping in field_mappings:
            handler = self._handlers[mapping["handler_method"]]
            value = handler.apply(
                item, mapping.get("handler_data") or {"field": mapping["source_field"]}
            )

            if mapping["target_field"] == "__geometry__":
                geometry = value
            else:
                properties[mapping["target_field"]] = value

        return {"type": "Feature", "properties": properties, "geometry": geometry}

    def open_stream(self, metadata: dict) -> str:
        crs = metadata.get(
            "crs",
            {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
            },
        )
        header = {
            "type": "FeatureCollection",
            "name": metadata.get("name", "Versio Export"),
            "crs": crs,
        }
        return json.dumps(header)[:-1] + ', "features": ['

    def close_stream(self, metadata: dict) -> str:
        return "]}"

    def separator(self) -> str:
        return ","
