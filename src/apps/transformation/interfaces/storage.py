from abc import ABC, abstractmethod
from typing import BinaryIO


class ObjectNotFoundError(Exception):
    """Raised by get_object() when the key doesn't exist. Backend-agnostic —
    adapters translate their own client's not-found exception into this one,
    so callers never need to know which storage backend is behind the
    interface to tell "genuinely missing" apart from a transient failure."""


class StorageInterface(ABC):
    """
    Port definition for the application-layer file storage adapter.
    Allows swapping the S3 implementation for tests or alternative backends.
    """

    @abstractmethod
    def get_object(self, key: str) -> BinaryIO:
        """Returns a readable, streamable file-like object for the object at
        key. Raises ObjectNotFoundError if key doesn't exist."""

    @abstractmethod
    def put_object(self, key: str, body: bytes) -> None:
        """Writes body as the object at key."""

    @abstractmethod
    def upload_stream(self, key: str, file_stream: BinaryIO) -> None:
        """Streams file_stream to the object at key without buffering it fully in memory."""

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]:
        """Returns all object keys under prefix."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """True if an object exists at key, without reading its body."""
