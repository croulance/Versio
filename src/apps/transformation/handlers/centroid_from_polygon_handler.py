import json

from apps.transformation.interfaces.handler import FieldHandler

from .registry import register_handler


@register_handler
class CentroidFromPolygonHandler(FieldHandler):
    """
    Derives a WKT POINT from the polygon field when geoLocationCoordinates is empty.
    Computes the centroid of the first ring of the polygon.
    """

    name = "centroid_from_polygon"

    def apply(self, source_data: dict, handler_data: dict | None) -> str:
        geo_loc = source_data.get("geoLocationCoordinates", "")
        if geo_loc:
            return geo_loc

        polygon_raw = source_data.get("polygon", "")
        if not polygon_raw:
            return ""

        try:
            # `polygon` can be an `object`-typed source field with no
            # declared children -- an opaque, unvalidated blob, so the raw
            # value reaching this handler may already be a parsed list/dict
            # rather than a JSON string. json.loads() raises TypeError (not
            # JSONDecodeError) for any non-str/bytes input, same bug shape as
            # the NestedCodeHandler fix.
            coords = (
                json.loads(polygon_raw) if isinstance(polygon_raw, str) else polygon_raw
            )
            lngs = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            centroid_lng = sum(lngs) / len(lngs)
            centroid_lat = sum(lats) / len(lats)
            return f"POINT ({centroid_lng:.6f} {centroid_lat:.6f})"
        except (
            json.JSONDecodeError,
            IndexError,
            ZeroDivisionError,
            TypeError,
            KeyError,
        ):
            return ""
