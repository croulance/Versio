from apps.transformation.interfaces.merger import MergerInterface
from apps.transformation.interfaces.storage import StorageInterface

from .registry import register_merger


@register_merger
class CsvMerger(MergerInterface):
    format = "csv"

    def __init__(self, storage: StorageInterface):
        self._storage = storage

    def merge(self, keys: list[str], metadata: dict) -> bytes:
        lines = []
        for i, key in enumerate(keys):
            rows = self._storage.get_object(key).read().decode("utf-8").splitlines()
            if i == 0:
                lines.extend(rows)
            else:
                lines.extend(rows[1:])  # skip header on subsequent chunks
        return "\n".join(lines).encode("utf-8")
