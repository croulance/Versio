import hashlib
import json
from typing import BinaryIO

from apps.transformation.constants import (REDIS_NS_CACHE_JOB,
                                           REDIS_NS_CACHE_SOURCE_FIELDS,
                                           REDIS_NS_CACHE_TEMPLATE,
                                           REDIS_NS_IDEMPOTENCY,
                                           REDIS_NS_LOCK_CHUNK)
from apps.transformation.interfaces.cache import CacheAdapterInterface
from infrastructure.cache.redis_client import RedisClient


class CacheAdapter(CacheAdapterInterface):
    """
    Application-layer adapter over RedisClient.
    Owns all domain key namespaces and business-aware cache operations.
    Delegates raw Redis I/O to RedisClient.
    """

    # Placeholder value written by reserve_idempotency while the winning
    # request is still doing the real work — never a valid job_id (UUID4),
    # so it can't be confused with a resolved one.
    _PENDING = "\x00PENDING\x00"

    def __init__(self, client: RedisClient):
        self._client = client

    # ------------------------------------------------------------------
    # Idempotency — prevent duplicate job submission
    # ------------------------------------------------------------------

    def build_idempotency_key(
        self, supplier_account_id: int, template_id: int, file_stream: BinaryIO
    ) -> str:
        file_stream.seek(0)
        hasher = hashlib.sha256(f"{supplier_account_id}:{template_id}:".encode())
        for block in iter(lambda: file_stream.read(1024 * 1024), b""):
            hasher.update(block)
        return hasher.hexdigest()

    def get_idempotency_job_id(self, key: str) -> str | None:
        value = self._client.get(f"{REDIS_NS_IDEMPOTENCY}:{key}")
        if value is None or value == self._PENDING:
            return None
        return value

    def reserve_idempotency(self, key: str, ttl: int) -> bool:
        return self._client.set_nx(f"{REDIS_NS_IDEMPOTENCY}:{key}", self._PENDING, ttl)

    def touch_idempotency_reservation(self, key: str, ttl: int) -> None:
        self._client.expire(f"{REDIS_NS_IDEMPOTENCY}:{key}", ttl)

    def resolve_idempotency(self, key: str, job_id: str, ttl: int) -> None:
        self._client.set(f"{REDIS_NS_IDEMPOTENCY}:{key}", job_id, ttl)

    def release_idempotency(self, key: str) -> None:
        self._client.delete(f"{REDIS_NS_IDEMPOTENCY}:{key}")

    # ------------------------------------------------------------------
    # Chunk lock — prevent two workers processing the same chunk
    # ------------------------------------------------------------------

    def acquire_chunk_lock(self, job_id: str, start: int, end: int, ttl: int) -> bool:
        return self._client.set_nx(
            f"{REDIS_NS_LOCK_CHUNK}:{job_id}:{start}:{end}", "1", ttl
        )

    def release_chunk_lock(self, job_id: str, start: int, end: int) -> None:
        self._client.delete(f"{REDIS_NS_LOCK_CHUNK}:{job_id}:{start}:{end}")

    # ------------------------------------------------------------------
    # Template cache — field mappings per template
    # ------------------------------------------------------------------

    def get_template_cache(self, template_id: int) -> list | None:
        raw = self._client.get(f"{REDIS_NS_CACHE_TEMPLATE}:{template_id}")
        return json.loads(raw) if raw else None

    def set_template_cache(self, template_id: int, data: list, ttl: int) -> None:
        self._client.set(
            f"{REDIS_NS_CACHE_TEMPLATE}:{template_id}", json.dumps(data), ttl
        )

    def invalidate_template_cache(self, template_id: int) -> None:
        self._client.delete(f"{REDIS_NS_CACHE_TEMPLATE}:{template_id}")

    # ------------------------------------------------------------------
    # Source field definitions cache — per template
    # ------------------------------------------------------------------

    def get_source_fields_cache(self, template_id: int) -> list | None:
        raw = self._client.get(f"{REDIS_NS_CACHE_SOURCE_FIELDS}:{template_id}")
        return json.loads(raw) if raw else None

    def set_source_fields_cache(self, template_id: int, data: list, ttl: int) -> None:
        self._client.set(
            f"{REDIS_NS_CACHE_SOURCE_FIELDS}:{template_id}", json.dumps(data), ttl
        )

    def invalidate_source_fields_cache(self, template_id: int) -> None:
        self._client.delete(f"{REDIS_NS_CACHE_SOURCE_FIELDS}:{template_id}")

    # ------------------------------------------------------------------
    # Job report cache — read-through for GET /api/jobs/{job_id}/
    # ------------------------------------------------------------------

    def get_job_report(self, job_id: str) -> dict | None:
        raw = self._client.get(f"{REDIS_NS_CACHE_JOB}:{job_id}")
        return json.loads(raw) if raw else None

    def set_job_report(self, job_id: str, data: dict, ttl: int) -> None:
        self._client.set(f"{REDIS_NS_CACHE_JOB}:{job_id}", json.dumps(data), ttl)

    def invalidate_job_report(self, job_id: str) -> None:
        self._client.delete(f"{REDIS_NS_CACHE_JOB}:{job_id}")
