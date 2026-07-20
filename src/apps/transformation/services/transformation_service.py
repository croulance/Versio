import json
import logging
import math
import time
import uuid
from typing import BinaryIO

import ijson
from django.conf import settings

from apps.transformation.dtos.result import TransformResult
from apps.transformation.interfaces.cache import CacheAdapterInterface
from apps.transformation.interfaces.repository import (
    JobRepositoryInterface, SupplierRepositoryInterface,
    TemplateRepositoryInterface)
from apps.transformation.interfaces.storage import StorageInterface
from apps.transformation.utils.chunking import (chunk_input_key,
                                                compute_chunk_size)
from apps.transformation.utils.source_path_detector import detect_source_path

logger = logging.getLogger(__name__)


class TransformationService:
    """
    Orchestrates the transformation pipeline.

    Responsibilities:
    - Idempotency check via cache
    - Source path resolution (configured on template → auto-detected → fallback)
    - Source file upload to storage
    - Supplier + template resolution
    - Job creation
    - Chunk task dispatch
    """

    def __init__(
        self,
        supplier_repository: SupplierRepositoryInterface,
        template_repository: TemplateRepositoryInterface,
        job_repository: JobRepositoryInterface,
        cache: CacheAdapterInterface,
        storage: StorageInterface,
    ):
        self._supplier_repo = supplier_repository
        self._template_repo = template_repository
        self._job_repo = job_repository
        self._cache = cache
        self._storage = storage

    def submit(
        self,
        supplier_account_id: int,
        template_id: int,
        filename: str,
        file_stream: BinaryIO,
    ) -> TransformResult:
        idempotency_key = self._cache.build_idempotency_key(
            supplier_account_id, template_id, file_stream
        )

        # Atomic claim (SET NX) — the only safe way to dedupe concurrent identical
        # submissions. A plain GET-then-SET leaves a window wide enough for every
        # concurrent duplicate to pass the check before any of them writes.
        if not self._cache.reserve_idempotency(
            idempotency_key, settings.IDEMPOTENCY_RESERVATION_TTL
        ):
            job_id = self._await_idempotent_job(idempotency_key)
            if job_id:
                logger.info(f"Duplicate submission detected, returning job {job_id}")
                return TransformResult.duplicate(job_id)
            return TransformResult.invalid(
                "An identical submission is already being processed — retry shortly"
            )

        resolved = False
        try:
            supplier = self._supplier_repo.get_by_account_id(supplier_account_id)
            if not supplier:
                return TransformResult.not_found(
                    f"Supplier with account_id={supplier_account_id} not found"
                )

            template = self._template_repo.get_published_template_by_id(
                supplier.id, template_id
            )
            if not template:
                return TransformResult.not_found(
                    f"No published template with id={template_id} found for supplier={supplier_account_id}"
                )
            format = template.format

            source_path, total_items = self._resolve_source_path(
                template.source_path, file_stream
            )
            if total_items == 0:
                return TransformResult.invalid(
                    f"No items found at source path '{source_path}'. "
                    "Check the template source_path or the file structure."
                )

            # Counting a large file can take a while, and the slower upload
            # step is still ahead — refresh so the reservation doesn't expire
            # mid-request while genuinely still in progress, not stalled.
            self._cache.touch_idempotency_reservation(
                idempotency_key, settings.IDEMPOTENCY_RESERVATION_TTL
            )

            storage_path = self._upload_to_storage(filename, file_stream)

            # Upload is typically the slowest step for a large file — refresh
            # once more before the (fast) remaining work and resolve_idempotency.
            self._cache.touch_idempotency_reservation(
                idempotency_key, settings.IDEMPOTENCY_RESERVATION_TTL
            )

            chunk_size = compute_chunk_size(
                total_items,
                settings.CHUNK_TARGET_COUNT,
                settings.CHUNK_SIZE_MIN,
                settings.CHUNK_SIZE_MAX,
            )
            total_chunks = math.ceil(total_items / chunk_size)

            job = self._job_repo.create(
                supplier_id=supplier.id,
                template_id=template.id,
                format=format,
                storage_path=storage_path,
                source_path=source_path,
                total_chunks=total_chunks,
                chunk_size=chunk_size,
            )

            self._cache.resolve_idempotency(
                idempotency_key, str(job.id), settings.IDEMPOTENCY_TTL
            )
            resolved = True

            # Splitting the source into one file per chunk is a full
            # sequential pass plus total_chunks storage writes — too slow to do
            # inside this request, so it's dispatched as a single
            # async task that does the split AND the per-chunk dispatch itself,
            # instead of doing either synchronously here.
            from apps.transformation.tasks.transform import \
                split_and_dispatch_chunks

            split_and_dispatch_chunks.apply_async(
                args=[
                    str(job.id),
                    storage_path,
                    source_path,
                    chunk_size,
                    template.id,
                    format,
                ],
                queue=settings.CELERY_MERGE_QUEUE,
            )

            logger.info(
                f"Job {job.id} created — {total_chunks} chunks, "
                f"source_path='{source_path}', template_id={template.id}"
            )
            return TransformResult.success(str(job.id))
        finally:
            # Any early return above (not_found/invalid) or unexpected exception
            # leaves the reservation unresolved — release it so a corrected retry
            # isn't blocked by a stale placeholder for IDEMPOTENCY_RESERVATION_TTL.
            if not resolved:
                self._cache.release_idempotency(idempotency_key)

    def _await_idempotent_job(self, idempotency_key: str) -> str | None:
        """Poll for the winning request's job_id while it finishes the work we
        lost the race for. Bounded by IDEMPOTENCY_WAIT_TIMEOUT so a caller never
        hangs indefinitely behind someone else's slow upload."""
        deadline = time.monotonic() + settings.IDEMPOTENCY_WAIT_TIMEOUT
        while time.monotonic() < deadline:
            job_id = self._cache.get_idempotency_job_id(idempotency_key)
            if job_id:
                return job_id
            time.sleep(settings.IDEMPOTENCY_WAIT_POLL_INTERVAL)
        return self._cache.get_idempotency_job_id(idempotency_key)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_source_path(
        self, configured: str, file_stream: BinaryIO
    ) -> tuple[str, int]:
        """
        Returns the effective (source_path, total_items):
        1. Template source_path if configured and valid (yields items).
        2. Auto-detected path from file structure.
        3. Fallback 'data.items.item' if detection fails.

        Each candidate path is counted at most once — the count that proves
        a path is valid is the same count the caller needs for total_items,
        so it's returned rather than re-derived with a second full parse.
        """
        if configured:
            count = self._count_items(file_stream, configured)
            if count > 0:
                logger.debug(f"Using configured source_path: '{configured}'")
                return configured, count
            logger.warning(
                f"Configured source_path '{configured}' yielded 0 items — falling back to auto-detection"
            )

        detected = detect_source_path(file_stream)
        if detected:
            logger.info(f"Auto-detected source_path: '{detected}'")
            return detected, self._count_items(file_stream, detected)

        logger.warning(
            f"Auto-detection failed — using fallback '{settings.DEFAULT_SOURCE_PATH}'"
        )
        return settings.DEFAULT_SOURCE_PATH, self._count_items(
            file_stream, settings.DEFAULT_SOURCE_PATH
        )

    def _count_items(self, file_stream: BinaryIO, source_path: str) -> int:
        file_stream.seek(0)
        count = 0
        try:
            for _ in ijson.items(file_stream, source_path):
                count += 1
        except Exception as exc:
            logger.warning(f"Item count failed for source_path={source_path!r}: {exc}")
            return 0
        return count

    def _upload_to_storage(self, filename: str, file_stream: BinaryIO) -> str:
        file_stream.seek(0)
        key = f"inputs/{uuid.uuid4()}/{filename}"
        self._storage.upload_stream(key, file_stream)
        return key

    def split_and_dispatch_chunks(
        self,
        job_id: str,
        storage_path: str,
        source_path: str,
        chunk_size: int,
        template_id: int,
        format: str,
    ) -> None:
        """Runs inside the split_and_dispatch_chunks Celery task, not
        the submission request — reads the already-uploaded source back from
        storage (a live request's file_stream can't cross a task boundary).
        One sequential ijson pass, buffering up to chunk_size items at a time;
        each buffer is flushed to its own storage object and that
        chunk's process_chunk task is dispatched immediately, in the same pass
        — no separate total_items bookkeeping needed, and no second pass.

        Public (not a private helper) because JobRetryView/retry_stuck_jobs
        re-dispatch the split_and_dispatch_chunks task (which calls this) to
        recover a job whose chunks were dropped entirely — re-running it is
        safe: the same source always produces the same chunk files, and each
        process_chunk dispatch is independently idempotent via its own chunk
        lock.
        """
        from apps.transformation.tasks.transform import process_chunk

        stream = self._storage.get_object(storage_path)
        buffer = []
        start = 0

        def _flush():
            nonlocal start, buffer
            end = start + len(buffer) - 1
            key = chunk_input_key(job_id, start, end)
            self._storage.put_object(key, json.dumps(buffer, default=float).encode())
            process_chunk.apply_async(
                args=[job_id, key, start, end, template_id, format],
                queue=settings.CELERY_CHUNK_QUEUE,
            )
            start = end + 1
            buffer = []

        for item in ijson.items(stream, source_path):
            buffer.append(item)
            if len(buffer) == chunk_size:
                _flush()
        if buffer:
            _flush()
