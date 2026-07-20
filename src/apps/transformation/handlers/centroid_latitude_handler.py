import json
import re

from apps.transformation.interfaces.handler import FieldHandler

from .registry import register_handler

_POINT_RE = re.compile(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", re.IGNORECASE)


@register_handler
class CentroidLatitudeHandler(FieldHandler):
    """
    Latitude half of the same centroid derivation as CentroidFromPolygonHandler
    -- returns a bare number instead of a WKT POINT string, for a target field
    that expects a numeric latitude column. Prefers geoLocationCoordinates
    (parsed as "POINT (lng lat)") when present, falling back to the polygon's
    own centroid otherwise.
    """

    name = "centroid_latitude"

    def apply(self, source_data: dict, handler_data: dict | None):
        geo_loc = source_data.get("geoLocationCoordinates", "")
        if geo_loc:
            match = _POINT_RE.search(geo_loc)
            return float(match.group(2)) if match else None

        polygon_raw = source_data.get("polygon", "")
        if not polygon_raw:
            return None
        try:
            coords = (
                json.loads(polygon_raw) if isinstance(polygon_raw, str) else polygon_raw
            )
            lats = [c[1] for c in coords]
            return sum(lats) / len(lats)
        except (
            json.JSONDecodeError,
            IndexError,
            ZeroDivisionError,
            TypeError,
            KeyError,
        ):
            return None
