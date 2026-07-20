from abc import ABC, abstractmethod
from typing import BinaryIO


class CacheAdapterInterface(ABC):
    """
    Port definition for the application-layer cache adapter.
    Allows swapping the Redis implementation for tests or alternative backends.
    """

    @abstractmethod
    def build_idempotency_key(
        self, supplier_account_id: int, template_id: int, file_stream: BinaryIO
    ) -> str:
        """Deterministic key derived from submission content — used to detect duplicate jobs."""

    @abstractmethod
    def get_idempotency_job_id(self, key: str) -> str | None:
        """The resolved job_id for this key, or None if unset or still reserved-but-pending."""

    @abstractmethod
    def reserve_idempotency(self, key: str, ttl: int) -> bool:
        """Atomically claim this key (SET NX). True if this caller now owns it and must
        eventually call resolve_idempotency or release_idempotency; False if someone
        else already owns it (either still working, or already resolved)."""

    @abstractmethod
    def touch_idempotency_reservation(self, key: str, ttl: int) -> None:
        """Resets the reservation's TTL back to the full window. Called at each
        step boundary of a slow submission (counting items, uploading the
        source file) so IDEMPOTENCY_RESERVATION_TTL only ever needs to cover
        one step's duration, not the sum of every step before resolve_idempotency
        runs -- a large enough file could otherwise outlive a single fixed TTL
        while the request is still legitimately in progress, not stalled."""

    @abstractmethod
    def resolve_idempotency(self, key: str, job_id: str, ttl: int) -> None:
        """Replace the reservation with the real job_id, extending the TTL to the
        full dedup window. Only the caller that won reserve_idempotency should call this.
        """

    @abstractmethod
    def release_idempotency(self, key: str) -> None:
        """Abandon a reservation that didn't result in a job (e.g. supplier/template not
        found), so a corrected retry isn't blocked by a stale placeholder."""

    @abstractmethod
    def acquire_chunk_lock(
        self, job_id: str, start: int, end: int, ttl: int
    ) -> bool: ...

    @abstractmethod
    def release_chunk_lock(self, job_id: str, start: int, end: int) -> None: ...

    # ── Template field mappings ────────────────────────────────────────

    @abstractmethod
    def get_template_cache(self, template_id: int) -> list | None: ...

    @abstractmethod
    def set_template_cache(self, template_id: int, data: list, ttl: int) -> None: ...

    @abstractmethod
    def invalidate_template_cache(self, template_id: int) -> None: ...

    # ── Source field definitions ───────────────────────────────────────

    @abstractmethod
    def get_source_fields_cache(self, template_id: int) -> list | None: ...

    @abstractmethod
    def set_source_fields_cache(
        self, template_id: int, data: list, ttl: int
    ) -> None: ...

    @abstractmethod
    def invalidate_source_fields_cache(self, template_id: int) -> None: ...

    # ── Job report ────────────────────────────────────────────────────

    @abstractmethod
    def get_job_report(self, job_id: str) -> dict | None: ...

    @abstractmethod
    def set_job_report(self, job_id: str, data: dict, ttl: int) -> None: ...

    @abstractmethod
    def invalidate_job_report(self, job_id: str) -> None: ...
