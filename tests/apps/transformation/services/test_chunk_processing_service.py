import io
import json

import openpyxl
import pytest

from apps.transformation.converters.csv_converter import CSVConverter
from apps.transformation.converters.xlsx_converter import XLSXConverter
from apps.transformation.enums import JobStatus
from apps.transformation.handlers.direct_handler import DirectHandler
from apps.transformation.interfaces.storage import ObjectNotFoundError
from apps.transformation.services.chunk_processing_service import (
    ChunkProcessingService, ChunkResultStatus, PermanentChunkError)
from apps.transformation.services.job_lifecycle_service import \
    JobLifecycleService


class FakeJob:
    def __init__(self, status=JobStatus.PENDING):
        self.status = status


class FakeJobRepository:
    """Mirrors the real JobRepository's guard semantics closely enough that
    running ChunkProcessingService through a real JobLifecycleService wired
    to this fake exercises the actual state-transition rules, not just
    recorded call arguments -- this is what makes the Finding-1 regression
    test below meaningful rather than tautological."""

    def __init__(self, job=None):
        self._job = job if job is not None else FakeJob()
        self.status_calls = []
        self.increment_calls = 0
        self.increment_returns = True
        self.is_complete_returns = True
        self.failed_chunks = []
        self.reverted_to_processing = False
        self.skipped_items_increments = []

    def get(self, job_id):
        return self._job

    def increment_skipped_items(self, job_id, count):
        if count <= 0:
            return
        self.skipped_items_increments.append(count)

    def start_processing(self, job_id):
        # Atomic-in-spirit: only ever leaves PENDING, exactly like the real
        # repository's WHERE status=PENDING update -- never stomps PARTIAL.
        if self._job.status == JobStatus.PENDING:
            self._job.status = JobStatus.PROCESSING
            self.status_calls.append(JobStatus.PROCESSING)

    def set_status(self, job_id, status):
        self._job.status = status
        self.status_calls.append(status)

    def increment_processed_chunks(self, job_id):
        if self._job.status in (JobStatus.DONE, JobStatus.FAILED):
            return False
        self.increment_calls += 1
        return self.increment_returns

    def is_complete(self, job_id):
        return self.is_complete_returns

    def append_failed_chunk(self, job_id, chunk):
        if self._job.status in (JobStatus.DONE, JobStatus.FAILED):
            return
        self.failed_chunks.append(chunk)
        self._job.status = JobStatus.PARTIAL

    def clear_failed_chunk(self, job_id, start, end):
        if self._job.status in (JobStatus.DONE, JobStatus.FAILED):
            return
        remaining = [
            c
            for c in self.failed_chunks
            if not (c["start"] == start and c["end"] == end)
        ]
        if len(remaining) == len(self.failed_chunks):
            return
        self.failed_chunks = remaining
        if not remaining and self._job.status == JobStatus.PARTIAL:
            self._job.status = JobStatus.PROCESSING
            self.reverted_to_processing = True


class FakeCache:
    def __init__(self):
        self.chunk_locks_acquired = []
        self.chunk_locks_released = []
        self.invalidate_calls = 0
        self.chunk_lock_should_succeed = True
        self._template_cache = {}
        self._source_fields_cache = {}

    def acquire_chunk_lock(self, job_id, start, end, ttl):
        self.chunk_locks_acquired.append((job_id, start, end))
        return self.chunk_lock_should_succeed

    def release_chunk_lock(self, job_id, start, end):
        self.chunk_locks_released.append((job_id, start, end))

    def invalidate_job_report(self, job_id):
        self.invalidate_calls += 1

    def get_template_cache(self, template_id):
        return self._template_cache.get(template_id)

    def set_template_cache(self, template_id, data, ttl):
        self._template_cache[template_id] = data

    def get_source_fields_cache(self, template_id):
        return self._source_fields_cache.get(template_id)

    def set_source_fields_cache(self, template_id, data, ttl):
        self._source_fields_cache[template_id] = data


class FakeTemplate:
    def __init__(self, metadata=None):
        self.metadata = metadata or {}


class FakeTemplateRepository:
    def __init__(self, field_mappings, source_fields, metadata=None):
        self._field_mappings = field_mappings
        self._source_fields = source_fields
        self._template = FakeTemplate(metadata)
        self.serialize_mappings_calls = 0
        self.serialize_source_fields_calls = 0

    def get_with_mappings_by_id(self, template_id):
        return self._template

    def serialize_mappings(self, template):
        self.serialize_mappings_calls += 1
        return self._field_mappings

    def serialize_source_fields(self, template):
        self.serialize_source_fields_calls += 1
        return self._source_fields


class FakeStorage:
    def __init__(self, source_json: bytes):
        self._source = source_json
        self.written = {}
        self._fail_put_once_for = None  # predicate(key) -> bool
        self.raise_not_found = False

    def get_object(self, key):
        if self.raise_not_found:
            raise ObjectNotFoundError(key)
        return io.BytesIO(self._source)

    def put_object(self, key, body):
        if self._fail_put_once_for and self._fail_put_once_for(key):
            self._fail_put_once_for = None
            raise IOError(f"simulated storage failure writing {key}")
        self.written[key] = body

    def exists(self, key):
        return key in self.written


FIELD_MAPPINGS = [
    {
        "target_field": "Name",
        "source_field": "name",
        "handler_method": "direct",
        "handler_data": {"field": "name"},
    }
]
SOURCE_FIELDS = [
    {"name": "name", "field_type": "string", "required": True, "nullable": False}
]


def _source_bytes(items):
    # A chunk's pre-split input file is a flat top-level JSON array
    # -- exactly its own items, no wrapping structure and no start/end
    # windowing needed to read it (unlike the old whole-source-file re-parse).
    return json.dumps(items).encode("utf-8")


def _service(
    job=None, source_items=None, field_mappings=None, source_fields=None, metadata=None
):
    job_repo = FakeJobRepository(job)
    cache = FakeCache()
    template_repo = FakeTemplateRepository(
        field_mappings or FIELD_MAPPINGS, source_fields or SOURCE_FIELDS, metadata
    )
    storage = FakeStorage(
        _source_bytes(source_items if source_items is not None else [])
    )
    converters = {"csv": CSVConverter({"direct": DirectHandler()})}
    lifecycle = JobLifecycleService(job_repository=job_repo, cache=cache)
    service = ChunkProcessingService(
        template_repository=template_repo,
        job_repository=job_repo,
        cache=cache,
        converters=converters,
        storage=storage,
        lifecycle=lifecycle,
    )
    return service, job_repo, cache, template_repo, storage


class TestProcess:
    def test_job_not_found(self):
        service, job_repo, cache, *_ = _service(job=None)
        job_repo._job = None

        result = service.process("job-1", "path", 0, 0, 3, "csv")

        assert result.status == ChunkResultStatus.NOT_FOUND
        assert cache.chunk_locks_acquired == []

    def test_job_already_done_is_discarded(self):
        service, job_repo, cache, *_ = _service(job=FakeJob(status="DONE"))

        result = service.process("job-1", "path", 0, 0, 3, "csv")

        assert result.status == ChunkResultStatus.ALREADY_DONE
        assert cache.chunk_locks_acquired == []

    def test_job_already_failed_is_discarded_too(self):
        # FAILED is terminal the same way DONE is -- a task still
        # in flight when the sweep marked the job FAILED must not silently
        # resurrect it. Only a manual retry does that.
        service, job_repo, cache, *_ = _service(job=FakeJob(status=JobStatus.FAILED))

        result = service.process("job-1", "path", 0, 0, 3, "csv")

        assert result.status == ChunkResultStatus.ALREADY_DONE
        assert cache.chunk_locks_acquired == []

    def test_lock_conflict_does_not_release_a_lock_never_acquired(self):
        service, job_repo, cache, *_ = _service(source_items=[{"name": "Acme"}])
        cache.chunk_lock_should_succeed = False

        result = service.process("job-1", "path", 0, 0, 3, "csv")

        assert result.status == ChunkResultStatus.LOCK_CONFLICT
        assert cache.chunk_locks_released == []

    def test_duplicate_dispatch_is_skipped_when_output_already_exists(self):
        # Regression test: a stale/duplicate process_chunk dispatch for a
        # range that already completed (e.g. a leftover task surviving a
        # stuck-job reset) must not redo the work or re-increment
        # processed_chunks -- that would let a job falsely reach "complete"
        # while a different, never-actually-processed range's output is
        # missing. See the failed-chunk-cleanup ADR line for the read on
        # this class of bug.
        service, job_repo, cache, template_repo, storage = _service(
            source_items=[{"name": "Acme"}]
        )
        storage.written["outputs/job-1/job-1_0_0.csv"] = b"Name\nAcme"

        result = service.process("job-1", "path", 0, 0, 3, "csv")

        assert result.status == ChunkResultStatus.ALREADY_DONE
        assert job_repo.increment_calls == 0
        assert job_repo.status_calls == []  # never even got to set_status(PROCESSING)
        # The lock was still acquired (needed to safely check existence) and
        # still released -- this isn't the job-level "already DONE" shortcut,
        # which returns before the lock is touched at all.
        assert cache.chunk_locks_acquired == [("job-1", 0, 0)]
        assert cache.chunk_locks_released == [("job-1", 0, 0)]

    def test_successful_chunk_converts_all_items_and_writes_output(self):
        items = [{"name": "Acme"}, {"name": "Beta"}]
        service, job_repo, cache, template_repo, storage = _service(
            source_items=items, metadata={"headers": ["Name"]}
        )

        result = service.process("job-1", "path", 0, 1, 3, "csv")

        assert result.status == ChunkResultStatus.OK
        assert result.converted_count == 2
        assert result.skipped_count == 0
        assert job_repo.status_calls == [JobStatus.PROCESSING]
        assert job_repo.increment_calls == 1
        assert cache.chunk_locks_released == [
            ("job-1", 0, 1)
        ]  # lock released even on success

        [written] = storage.written.values()
        assert written.decode("utf-8") == "Name\nAcme\nBeta"

    def test_successful_chunk_clears_its_own_stale_failed_chunk_entry(self):
        # Regression test: a chunk that failed once (Celery's automatic retry
        # kicks in) and succeeds on the retry must not leave a phantom error
        # behind once it resolves -- otherwise a job that fully completes can
        # still show failed_chunks for a problem that no longer exists.
        items = [{"name": "Acme"}]
        service, job_repo, *_ = _service(source_items=items)
        job_repo.failed_chunks = [
            {"start": 0, "end": 0, "error": "boom", "failed_at": "t", "retry_count": 1}
        ]

        result = service.process("job-1", "path", 0, 0, 3, "csv")

        assert result.status == ChunkResultStatus.OK
        assert job_repo.failed_chunks == []

    def test_successful_chunk_only_clears_its_own_range_not_other_chunks(self):
        items = [{"name": "Acme"}]
        service, job_repo, *_ = _service(source_items=items)
        other_entry = {
            "start": 500,
            "end": 999,
            "error": "boom",
            "failed_at": "t",
            "retry_count": 1,
        }
        job_repo.failed_chunks = [other_entry]

        service.process("job-1", "path", 0, 0, 3, "csv")

        # [0:0] succeeded and had no prior failure -- the unrelated [500:999]
        # entry (a different chunk still failing) must survive untouched.
        assert job_repo.failed_chunks == [other_entry]

    def test_unrelated_chunk_succeeding_does_not_move_a_partial_job_off_partial(self):
        # Core regression test for this behavior. Before this fix, process() called
        # set_status(PROCESSING) unconditionally on every successful chunk --
        # so a job sitting PARTIAL because of chunk [500:999]'s real,
        # unresolved failure would silently flip back to PROCESSING the
        # instant ANY other, unrelated chunk (like [0:0] here) merely
        # started. failed_chunks would still list a live problem while
        # status quietly claimed everything was fine.
        items = [{"name": "Acme"}]
        job = FakeJob(status=JobStatus.PARTIAL)
        service, job_repo, *_ = _service(job=job, source_items=items)
        job_repo.failed_chunks = [
            {"start": 500, "end": 999, "error": "boom", "failed_at": "t", "retry_count": 1}
        ]

        result = service.process("job-1", "path", 0, 0, 3, "csv")

        assert result.status == ChunkResultStatus.OK
        assert job.status == JobStatus.PARTIAL  # NOT silently PROCESSING
        assert job_repo.status_calls == []  # start_processing was a no-op
        assert len(job_repo.failed_chunks) == 1  # chunk 3's real failure untouched

    def test_the_actually_failed_chunk_succeeding_does_move_partial_to_processing(self):
        # The mirror case: when the chunk that WAS failing is the one that
        # succeeds, and it's the only entry in failed_chunks, PARTIAL should
        # move to PROCESSING -- via clear_failed_chunk finding the list
        # empty, not via an unconditional status stomp.
        items = [{"name": "Acme"}]
        job = FakeJob(status=JobStatus.PARTIAL)
        service, job_repo, *_ = _service(job=job, source_items=items)
        job_repo.failed_chunks = [
            {"start": 0, "end": 0, "error": "boom", "failed_at": "t", "retry_count": 1}
        ]

        service.process("job-1", "path", 0, 0, 3, "csv")

        assert job.status == JobStatus.PROCESSING
        assert job_repo.failed_chunks == []

    def test_successful_chunk_with_no_prior_failure_is_a_noop(self):
        items = [{"name": "Acme"}]
        service, job_repo, *_ = _service(source_items=items)

        service.process("job-1", "path", 0, 0, 3, "csv")

        assert job_repo.failed_chunks == []
        assert job_repo.reverted_to_processing is False

    def test_all_items_in_the_chunk_file_are_processed_start_end_are_bookkeeping_only(
        self,
    ):
        # Regression test: the chunk file IS the window (it's
        # pre-split at submission time, one file per chunk) -- process() must
        # not re-filter by start/end the way it used to when it re-parsed the
        # whole source file. Passing start/end that don't match the item count
        # must not drop or add anything; they're only used for lock/failure
        # bookkeeping.
        items = [{"name": f"P{i}"} for i in range(3)]
        service, *_, storage = _service(
            source_items=items, metadata={"headers": ["Name"]}
        )

        result = service.process("job-1", "path", 100, 102, 3, "csv")

        assert result.converted_count == 3
        [written] = storage.written.values()
        assert written.decode("utf-8") == "Name\nP0\nP1\nP2"

    def test_preserves_item_order_despite_threaded_conversion(self):
        items = [{"name": f"P{i}"} for i in range(20)]
        service, *_, storage = _service(source_items=items)

        service.process("job-1", "path", 0, 19, 3, "csv")

        [written] = storage.written.values()
        rows = written.decode("utf-8").splitlines()[1:]
        assert rows == [f"P{i}" for i in range(20)]

    def test_item_failing_validation_is_skipped_not_errored(self):
        items = [{"name": "Acme"}, {}]  # second item missing required 'name'
        service, job_repo, cache, template_repo, storage = _service(
            source_items=items
        )

        result = service.process("job-1", "path", 0, 1, 3, "csv")

        assert result.status == ChunkResultStatus.OK
        assert result.converted_count == 1
        assert result.skipped_count == 1
        assert job_repo.skipped_items_increments == [1]

        [errors_key] = [k for k in storage.written if k.endswith(".errors.json")]
        [entry] = json.loads(storage.written[errors_key])
        assert entry["position"] == 1  # second item, 0-indexed
        assert "validation" in entry["error"]

    def test_no_skips_means_no_errors_file_written(self):
        items = [{"name": "Acme"}, {"name": "Beta"}]
        service, job_repo, *_, storage = _service(source_items=items)

        service.process("job-1", "path", 0, 1, 3, "csv")

        assert not any(k.endswith(".errors.json") for k in storage.written)
        assert job_repo.skipped_items_increments == []

    def test_a_single_items_conversion_error_is_skipped_not_crashing_the_chunk(self):
        # Regression test: a source field validated as an opaque, unvalidated
        # blob (an `object` type with no declared children) can
        # still be malformed for a specific item in a way a handler doesn't
        # expect -- previously that handler's exception propagated out of
        # convert_item(), crashing every other item in the same chunk, not
        # just the one bad record.
        class RaisingHandler:
            def apply(self, source_data, handler_data):
                if source_data.get("name") == "Bad":
                    raise AttributeError("'str' object has no attribute 'get'")
                return source_data.get("name")

        items = [{"name": "Acme"}, {"name": "Bad"}, {"name": "Beta"}]
        service, job_repo, *_, storage = _service(source_items=items)
        service._converters = {"csv": CSVConverter({"direct": RaisingHandler()})}

        result = service.process("job-1", "path", 0, 2, 3, "csv")

        assert result.status == ChunkResultStatus.OK
        assert result.converted_count == 2
        assert result.skipped_count == 1
        assert job_repo.skipped_items_increments == [1]

        [errors_key] = [k for k in storage.written if k.endswith(".errors.json")]
        [entry] = json.loads(storage.written[errors_key])
        assert entry["position"] == 1  # "Bad" is the second item, 0-indexed
        assert "conversion" in entry["error"]

    def test_a_failure_writing_real_output_does_not_double_count_skipped_items_on_retry(
        self,
    ):
        # Regression test, same failure shape as the idempotency guard:
        # process() has exactly one idempotency checkpoint (does the chunk's
        # real output key already exist?), checked once at the top. Any write
        # that happens *before* that key is durably written will re-run in
        # full on a retry -- so skip-tracing (the errors file + the
        # skipped_items counter) must happen *after* the real output write
        # succeeds, never before it, or a retry after a transient output-write
        # failure double-counts the same skip.
        items = [{"name": "Acme"}, {}]  # second item skipped (missing 'name')
        service, job_repo, cache, template_repo, storage = _service(
            source_items=items
        )
        storage._fail_put_once_for = lambda key: key.endswith(".csv")

        with pytest.raises(IOError):
            service.process("job-1", "path", 0, 1, 3, "csv")

        result = service.process("job-1", "path", 0, 1, 3, "csv")

        assert result.status == ChunkResultStatus.OK
        assert job_repo.skipped_items_increments == [1]  # not [1, 1]

    def test_duplicate_master_plot_ids_in_the_same_chunk_all_convert(self):
        # Regression test: a per-masterPlotId lock used to skip an item outright
        # if another item with the same id was mid-conversion in a sibling
        # thread — but conversion never touches shared state (each chunk's
        # output is an isolated storage key), so nothing should be dropped.
        items = [{"name": f"P{i}", "masterPlotId": "SAME-ID"} for i in range(20)]
        service, job_repo, cache, *_ = _service(source_items=items)

        result = service.process("job-1", "path", 0, 19, 3, "csv")

        assert result.status == ChunkResultStatus.OK
        assert result.converted_count == 20
        assert result.skipped_count == 0

    def test_unknown_format_raises_but_still_releases_chunk_lock(self):
        service, job_repo, cache, *_ = _service(source_items=[{"name": "Acme"}])

        with pytest.raises(PermanentChunkError, match="No converter registered"):
            service.process("job-1", "path", 0, 0, 3, "xml")

        assert cache.chunk_locks_released == [("job-1", 0, 0)]

    def test_missing_chunk_source_file_raises_permanent_not_retryable(self):
        # Regression test: a missing source file (ObjectNotFoundError) used to
        # surface as a generic Exception, classified retryable=True by the
        # Celery task despite being permanent -- retrying it can never
        # succeed, since the file will never appear on its own.
        service, job_repo, cache, template_repo, storage = _service(
            source_items=[{"name": "Acme"}]
        )
        storage.raise_not_found = True

        with pytest.raises(PermanentChunkError, match="missing in storage"):
            service.process("job-1", "path", 0, 0, 3, "csv")

        assert cache.chunk_locks_released == [("job-1", 0, 0)]

    def test_field_mappings_and_source_fields_are_cached_after_first_load(self):
        service, job_repo, cache, template_repo, storage = _service(
            source_items=[{"name": "Acme"}]
        )

        service.process("job-1", "path", 0, 0, 3, "csv")
        assert template_repo.serialize_mappings_calls == 1
        assert template_repo.serialize_source_fields_calls == 1

        # A different chunk range -- not a duplicate of the first -- so this
        # exercises a genuine second processing pass, not the idempotency
        # guard's duplicate-dispatch short-circuit (see the test above).
        service.process("job-1", "path", 1, 1, 3, "csv")
        # second call must hit the cache, not the repository again
        assert template_repo.serialize_mappings_calls == 1
        assert template_repo.serialize_source_fields_calls == 1

    def test_job_complete_true_when_last_chunk_and_increment_succeeds(self):
        service, job_repo, *_ = _service(source_items=[{"name": "Acme"}])
        job_repo.increment_returns = True
        job_repo.is_complete_returns = True

        result = service.process("job-1", "path", 0, 0, 3, "csv")

        assert result.job_complete is True

    def test_job_complete_false_when_increment_lost_the_race(self):
        service, job_repo, *_ = _service(source_items=[{"name": "Acme"}])
        job_repo.increment_returns = False

        result = service.process("job-1", "path", 0, 0, 3, "csv")

        assert result.job_complete is False

    def test_xlsx_converter_routes_to_flush_xlsx(self):
        items = [{"name": "Acme"}, {"name": "Beta"}]
        service, job_repo, cache, template_repo, storage = _service(source_items=items)
        service._converters = {"xlsx": XLSXConverter({"direct": DirectHandler()})}

        result = service.process("job-1", "path", 0, 1, 3, "xlsx")

        assert result.status == ChunkResultStatus.OK
        [written] = storage.written.values()
        wb = openpyxl.load_workbook(io.BytesIO(written))
        rows = list(wb.active.iter_rows(values_only=True))
        assert rows == [("Name",), ("Acme",), ("Beta",)]


class TestRecordFailure:
    def test_appends_failed_chunk_entry_and_invalidates_cache(self):
        service, job_repo, cache, *_ = _service()

        service.record_failure(
            "job-1", 0, 499, ValueError("boom"), retry_count=2, retryable=True
        )

        [entry] = job_repo.failed_chunks
        assert entry["start"] == 0
        assert entry["end"] == 499
        assert entry["error"] == "boom"
        assert entry["retry_count"] == 2
        assert entry["retryable"] is True
        assert "failed_at" in entry
        assert cache.invalidate_calls == 1

    def test_permanent_failure_is_recorded_as_not_retryable(self):
        service, job_repo, *_ = _service()

        service.record_failure(
            "job-1", 0, 499, PermanentChunkError("no converter"), retry_count=0,
            retryable=False,
        )

        [entry] = job_repo.failed_chunks
        assert entry["retryable"] is False

    def test_does_not_record_against_an_already_done_job(self):
        # A task still in flight when the job resolved must not
        # regress it -- the repository-level guard, exercised here through
        # the real lifecycle service, not just asserted in isolation.
        job = FakeJob(status=JobStatus.DONE)
        service, job_repo, *_ = _service(job=job)

        service.record_failure(
            "job-1", 0, 499, ValueError("boom"), retry_count=1, retryable=True
        )

        assert job_repo.failed_chunks == []
        assert job.status == JobStatus.DONE
