import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum

import ijson
import openpyxl
from django.conf import settings

from apps.transformation.enums import JobStatus
from apps.transformation.interfaces.cache import CacheAdapterInterface
from apps.transformation.interfaces.converter import (
    ConverterInterface, StreamingConverterInterface)
from apps.transformation.interfaces.repository import (
    JobRepositoryInterface, TemplateRepositoryInterface)
from apps.transformation.interfaces.storage import (ObjectNotFoundError,
                                                    StorageInterface)
from apps.transformation.services.job_lifecycle_service import \
    JobLifecycleService
from apps.transformation.validators.item_validator import DynamicItemValidator

logger = logging.getLogger(__name__)

_DEFAULT_XLSX_SHEET = "Export"  # matches XLSXConverter's fallback for a zero-item chunk


class PermanentChunkError(Exception):
    """A chunk failure that will fail identically on every retry — a missing
    template, a format with no registered converter. Retrying wastes Celery's
    retry budget on a certain repeat failure; the caller should record it as
    non-retryable and skip automatic retry (Celery's own, and the later
    stuck-job sweep) entirely. Only a human fixing the underlying config and
    triggering a manual retry can resolve this."""


class ChunkResultStatus(Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    ALREADY_DONE = "already_done"
    LOCK_CONFLICT = "lock_conflict"


@dataclass
class ChunkResult:
    status: ChunkResultStatus
    converted_count: int = 0
    skipped_count: int = 0
    job_complete: bool = False


class ChunkProcessingService:
    """Validates, converts, and flushes a single chunk of a transformation job to storage."""

    def __init__(
        self,
        template_repository: TemplateRepositoryInterface,
        job_repository: JobRepositoryInterface,
        cache: CacheAdapterInterface,
        converters: dict[str, ConverterInterface],
        storage: StorageInterface,
        lifecycle: JobLifecycleService,
        validator: DynamicItemValidator | None = None,
    ):
        self._template_repo = template_repository
        self._job_repo = job_repository
        self._cache = cache
        self._converters = converters
        self._storage = storage
        self._lifecycle = lifecycle
        self._validator = validator or DynamicItemValidator()

    def process(
        self,
        job_id: str,
        chunk_storage_key: str,
        start: int,
        end: int,
        template_id: int,
        format: str,
    ) -> ChunkResult:
        job = self._job_repo.get(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found — discarding chunk [{start}:{end}]")
            return ChunkResult(status=ChunkResultStatus.NOT_FOUND)
        if job.status in (JobStatus.DONE, JobStatus.FAILED):
            # Terminal either way: DONE has nothing left to do,
            # and FAILED has been explicitly abandoned by the stuck-job
            # sweep — a stale task still in flight from before that must not
            # silently resurrect it. Only a manual retry does that.
            logger.info(
                f"Job {job_id} already {job.status} — discarding stale chunk [{start}:{end}]"
            )
            return ChunkResult(status=ChunkResultStatus.ALREADY_DONE)

        if not self._cache.acquire_chunk_lock(
            job_id, start, end, settings.CHUNK_LOCK_TTL
        ):
            logger.warning(
                f"Chunk lock not acquired for job={job_id} [{start}:{end}] — skipping"
            )
            return ChunkResult(status=ChunkResultStatus.LOCK_CONFLICT)

        try:
            # Idempotency guard: this exact chunk can be dispatched more than
            # once (a stale task surviving a stuck-job reset, an at-least-once
            # queue redelivery) — the TTL-based lock above only stops two
            # dispatches running *concurrently*, not a later one running after
            # the first already finished and released it. If this range's
            # output already exists, it was already counted toward
            # processed_chunks; redoing the work would double-count it,
            # letting the job falsely reach "complete" while a different,
            # never-actually-processed range's output never gets written.
            output_key = self._chunk_output_key(job_id, format, start, end)
            if self._storage.exists(output_key):
                logger.info(
                    f"Chunk [{start}:{end}] job={job_id} already has output — "
                    "skipping (duplicate dispatch)"
                )
                return ChunkResult(status=ChunkResultStatus.ALREADY_DONE)

            self._lifecycle.begin(job_id)

            field_mappings = self._load_field_mappings(template_id)
            source_fields = self._load_source_fields(template_id)

            template = self._template_repo.get_with_mappings_by_id(template_id)
            metadata = template.metadata if template else {}

            converter = self._converters.get(format)
            if not converter:
                raise PermanentChunkError(
                    f"No converter registered for format '{format}'"
                )
            items, skipped = self._convert_chunk(
                job_id,
                chunk_storage_key,
                source_fields,
                field_mappings,
                converter,
                metadata,
            )

            self._flush_output(job_id, format, start, end, items, converter, metadata)

            if skipped:
                # Written *after* the real output (whose key is this method's
                # only idempotency checkpoint, checked once at the top) —
                # never before it. A write here that happened before the real
                # output existed would re-run in full on any retry (the
                # checkpoint wouldn't have tripped yet), double-counting the
                # same skip into skipped_items. Found live: a transient
                # failure writing the real output, after skip-tracing already
                # ran, replayed the whole chunk on retry and counted the same
                # skipped item twice.
                logger.info(
                    f"Chunk [{start}:{end}] job={job_id}: {len(items)} converted, {len(skipped)} skipped"
                )
                self._write_errors_to_storage(job_id, start, end, skipped)
                self._job_repo.increment_skipped_items(job_id, len(skipped))

            # A chunk that failed on an earlier attempt and succeeds on this one
            # (Celery's automatic retry) leaves a stale entry in failed_chunks
            # unless it's explicitly cleared here — otherwise a job that fully
            # completes can still show a phantom error for a problem that
            # already resolved itself.
            self._lifecycle.chunk_succeeded(job_id, start, end)

            incremented = self._job_repo.increment_processed_chunks(job_id)
            self._cache.invalidate_job_report(job_id)

            job_complete = bool(incremented and self._job_repo.is_complete(job_id))
            return ChunkResult(
                status=ChunkResultStatus.OK,
                converted_count=len(items),
                skipped_count=len(skipped),
                job_complete=job_complete,
            )
        finally:
            self._cache.release_chunk_lock(job_id, start, end)

    def record_failure(
        self,
        job_id: str,
        start: int,
        end: int,
        error: Exception,
        retry_count: int,
        retryable: bool,
    ) -> None:
        self._lifecycle.chunk_failed(job_id, start, end, error, retry_count, retryable)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_field_mappings(self, template_id: int) -> list:
        cached = self._cache.get_template_cache(template_id)
        if cached:
            return cached

        template = self._template_repo.get_with_mappings_by_id(template_id)
        if not template:
            raise PermanentChunkError(f"No template with id={template_id}")

        mappings = self._template_repo.serialize_mappings(template)
        self._cache.set_template_cache(
            template_id, mappings, settings.TEMPLATE_CACHE_TTL
        )
        return mappings

    def _load_source_fields(self, template_id: int) -> list:
        cached = self._cache.get_source_fields_cache(template_id)
        if cached:
            return cached

        template = self._template_repo.get_with_mappings_by_id(template_id)
        if not template:
            raise PermanentChunkError(f"No template with id={template_id}")

        fields = self._template_repo.serialize_source_fields(template)
        self._cache.set_source_fields_cache(
            template_id, fields, settings.TEMPLATE_CACHE_TTL
        )
        return fields

    def _stream_chunk(self, chunk_storage_key: str):
        """Reads this chunk's own pre-split file — a plain top-level
        JSON array, written once at submission time by
        TransformationService._split_into_chunks, so no start/end windowing is
        needed here: every item in the file belongs to this chunk."""
        try:
            stream = self._storage.get_object(chunk_storage_key)
        except ObjectNotFoundError as exc:
            # A missing chunk file is permanent, not a transient infra
            # hiccup -- it will never appear on its own, so retrying it
            # (Celery's default, or the automatic PARTIAL sweep) accomplishes
            # nothing and only piles up retry tasks for a chunk that can
            # never succeed.
            raise PermanentChunkError(
                f"Chunk source file missing in storage: {chunk_storage_key}"
            ) from exc
        yield from ijson.items(stream, "item")

    def _convert_chunk(
        self,
        job_id,
        chunk_storage_key,
        source_fields,
        field_mappings,
        converter,
        metadata,
    ):
        """Returns (items, skipped) where `skipped` is a list of
        {"position": int, "error": str} — position is 0-indexed into this
        chunk's own item stream. ThreadPoolExecutor.map()
        preserves input order in its results even though execution is
        concurrent, so enumerate()'d positions stay meaningful despite the
        threading below."""
        items = []
        skipped = []

        def _process(indexed_item):
            position, item = indexed_item
            validated, errors = self._validator.validate(item, source_fields)
            if errors:
                logger.warning(
                    f"Item validation errors (job={job_id}): {errors} — skipping item"
                )
                return None, {"position": position, "error": f"validation: {errors}"}

            try:
                return (
                    converter.convert_item(validated, field_mappings, metadata),
                    None,
                )
            except Exception as exc:
                # A field that passed validation (e.g. an `object`-typed
                # field with no declared children -- an opaque, unvalidated
                # blob) can still be malformed for this one item in a way
                # a handler doesn't expect. Without this, that handler's
                # exception would propagate out of the ThreadPoolExecutor
                # and crash every other item in the same chunk, not just
                # this one record.
                logger.warning(
                    f"Item conversion error (job={job_id}): {exc} — skipping item"
                )
                return None, {"position": position, "error": f"conversion: {exc}"}

        with ThreadPoolExecutor(max_workers=settings.ITEM_THREAD_POOL_SIZE) as pool:
            for converted, skip_detail in pool.map(
                _process, enumerate(self._stream_chunk(chunk_storage_key))
            ):
                if skip_detail is not None:
                    skipped.append(skip_detail)
                else:
                    items.append(converted)

        return items, skipped

    @staticmethod
    def _chunk_output_key(job_id: str, format: str, start: int, end: int) -> str:
        """The one place this key format is defined — shared by the
        idempotency check in process() and every actual write below, so the
        two can never drift out of sync with each other."""
        return f"outputs/{job_id}/{job_id}_{start}_{end}.{format}"

    @staticmethod
    def _chunk_errors_key(job_id: str, start: int, end: int) -> str:
        """Deterministic key for this chunk's skip trace — always
        `.errors.json` regardless of the job's output format, so it's
        automatically excluded from MergeService's `.{format}`-filtered
        chunk listing with no change needed there."""
        return f"outputs/{job_id}/{job_id}_{start}_{end}.errors.json"

    def _write_errors_to_storage(
        self, job_id: str, start: int, end: int, skipped: list[dict]
    ) -> None:
        key = self._chunk_errors_key(job_id, start, end)
        self._storage.put_object(key, json.dumps(skipped).encode("utf-8"))

    def _write_output_to_storage(
        self, job_id: str, format: str, content: str | bytes, start: int, end: int
    ) -> str:
        key = self._chunk_output_key(job_id, format, start, end)
        body = content.encode("utf-8") if isinstance(content, str) else content
        self._storage.put_object(key, body)
        return key

    def _flush_output(
        self,
        job_id: str,
        format: str,
        start: int,
        end: int,
        items: list,
        converter,
        metadata: dict,
    ) -> None:
        if isinstance(converter, StreamingConverterInterface):
            parts = [converter.open_stream(metadata)]
            for i, item in enumerate(items):
                serialized = json.dumps(item) if isinstance(item, dict) else str(item)
                if i > 0:
                    parts.append(converter.separator())
                parts.append(serialized)
            parts.append(converter.close_stream(metadata))
            self._write_output_to_storage(job_id, format, "".join(parts), start, end)
        else:
            self._flush_xlsx(job_id, items, metadata, start, end)

    def _flush_xlsx(
        self, job_id: str, rows: list, metadata: dict, start: int, end: int
    ) -> None:
        # Each row is {sheet_name: {target_field: value, ...}, ...}
        # (XLSXConverter) -- sheet order comes from the first row's key
        # order, which is stable across every row and every chunk of the
        # same job since all of them iterate the same field_mappings in the
        # same order (per-mapping sheet_name replaces the old single
        # metadata.sheet_name). openpyxl's write-only API only appends one
        # row at a time per sheet, so writing N sheets of M rows each is
        # inherently a nested loop -- kept in one place, honestly, rather
        # than split across a helper that would just hide the same two
        # loops behind an extra call.
        wb = openpyxl.Workbook(write_only=True)
        sheet_names = rows[0].keys() if rows else [_DEFAULT_XLSX_SHEET]
        by_sheet = {name: [row[name] for row in rows] for name in sheet_names}

        for sheet_name, sheet_rows in by_sheet.items():
            ws = wb.create_sheet(title=sheet_name)
            if sheet_rows:
                ws.append(list(sheet_rows[0].keys()))
                for sheet_row in sheet_rows:
                    ws.append(list(sheet_row.values()))

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        self._write_output_to_storage(job_id, "xlsx", buf.read(), start, end)
