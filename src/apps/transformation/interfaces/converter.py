from abc import ABC, abstractmethod
from typing import Generic, TypeVar

TItem = TypeVar("TItem")
TOutput = TypeVar("TOutput")


class ConverterInterface(ABC, Generic[TItem, TOutput]):
    """
    Base contract for all format converters.
    Single responsibility: convert one source item into the target format.
    """

    @abstractmethod
    def convert_item(self, item: dict, field_mappings: list, metadata: dict) -> TOutput:
        """Transform a single source item using the provided field mappings."""


class StreamingConverterInterface(ConverterInterface[TItem, str]):
    """
    Extended contract for text-based streaming formats (CSV, GeoJSON, XML).

    Adds the three methods needed to assemble a chunk file by concatenation:
      open_stream → items separated by separator() → close_stream

    Binary formats (XLSX) implement ConverterInterface directly and bypass
    this contract — they return plain dicts and are assembled by the task.
    """

    @abstractmethod
    def open_stream(self, metadata: dict) -> str:
        """Opening wrapper for the format (e.g. FeatureCollection header, XML root)."""

    @abstractmethod
    def close_stream(self, metadata: dict) -> str:
        """Closing wrapper for the format."""

    @abstractmethod
    def separator(self) -> str:
        """Separator between items (e.g. ',' for JSON arrays, '\\n' for CSV/XML rows)."""
