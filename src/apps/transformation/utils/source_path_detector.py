import logging
from typing import BinaryIO

import ijson
from django.conf import settings

logger = logging.getLogger(__name__)


def detect_source_path(file_stream: BinaryIO) -> str | None:
    """
    Scans a JSON file to find the ijson path to the first array of objects.

    Strategy: parse events until we see a 'start_array' immediately followed
    by a 'start_map' — that array contains objects and is the likely source list.

    Returns a dotted ijson path (e.g. 'data.items.item') or None if not found.
    Stops after SOURCE_PATH_SCAN_LIMIT events (settings) so large files are not fully traversed.

    Examples:
        {"data": {"items": [{"id": 1}]}}  →  "data.items.item"
        {"results": [{"name": "a"}]}       →  "results.item"
        {"tags": ["a"], "rows": [{"id":1}]}→  "rows.item"  (skips primitive arrays)
    """
    file_stream.seek(0)
    in_array = False
    array_prefix = None
    event_count = 0

    try:
        for prefix, event, _ in ijson.parse(file_stream):
            event_count += 1
            if event_count > settings.SOURCE_PATH_SCAN_LIMIT:
                break

            if event == "start_array":
                in_array = True
                array_prefix = prefix
            elif event == "end_array":
                in_array = False
                array_prefix = None
            elif event == "start_map" and in_array:
                return f"{array_prefix}.item" if array_prefix else "item"

    except Exception as exc:
        logger.warning(f"Source path detection failed: {exc}")
        return None

    return None
