import json

from apps.transformation.interfaces.handler import FieldHandler

from .registry import register_handler


@register_handler
class GeoJsonGeometryHandler(FieldHandler):
    """
    Parses the plotGeoJson string and returns the geometry dict,
    converting Polygon to MultiPolygon by wrapping coordinates one level deeper.
    """

    name = "parse_geojson_geometry"

    def apply(self, source_data: dict, handler_data: dict | None) -> dict:
        raw = source_data.get("plotGeoJson", "")
        if not raw:
            return {}

        try:
            feature = json.loads(raw) if isinstance(raw, str) else raw
            geometry = feature.get("geometry", {})

            if geometry.get("type") == "Polygon":
                geometry = {
                    "type": "MultiPolygon",
                    "coordinates": [geometry["coordinates"]],
                }

            return geometry
        except (json.JSONDecodeError, KeyError, AttributeError):
            return {}
