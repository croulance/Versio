import json

from apps.transformation.interfaces.merger import MergerInterface
from apps.transformation.interfaces.storage import StorageInterface

from .registry import register_merger


@register_merger
class ErrorsMerger(MergerInterface):
    """Merges per-chunk skip-trace files into one combined JSON
    array. Registered the same way as the real output-format mergers
    (format='errors') so MergeService can pull it from the same
    {format: MergerInterface} map — but no job's own `format` is ever
    "errors"; MergeService calls this one directly as a side-channel
    alongside the real output merge, not through per-job format dispatch."""

    format = "errors"

    def __init__(self, storage: StorageInterface):
        self._storage = storage

    def merge(self, keys: list[str], metadata: dict) -> bytes:
        combined = []
        for key in keys:
            combined.extend(json.loads(self._storage.get_object(key).read()))
        return json.dumps(combined).encode("utf-8")
