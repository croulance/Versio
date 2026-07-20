from apps.transformation.interfaces.merger import MergerInterface
from apps.transformation.interfaces.storage import StorageInterface

from .registry import register_merger


@register_merger
class XmlMerger(MergerInterface):
    format = "xml"

    def __init__(self, storage: StorageInterface):
        self._storage = storage

    def merge(self, keys: list[str], metadata: dict) -> bytes:
        root = metadata.get("root_element", "records")
        parts = [f'<?xml version="1.0" encoding="UTF-8"?>\n<{root}>']
        for key in keys:
            text = self._storage.get_object(key).read().decode("utf-8")
            inner = text.split(f"<{root}>", 1)[-1].rsplit(f"</{root}>", 1)[0]
            parts.append(inner.strip())
        parts.append(f"</{root}>")
        return "\n".join(parts).encode("utf-8")
