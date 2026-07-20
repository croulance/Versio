from abc import ABC, abstractmethod


class FieldHandler(ABC):
    """
    Base contract for all per-field value handlers.
    Single responsibility: extract and transform one value from a source item.
    """

    name: str = None

    @abstractmethod
    def apply(self, source_data: dict, handler_data: dict | None) -> any:
        """Extract and transform a value from source_data."""
