import pytest
from celery.exceptions import Retry

import apps.transformation.tasks.transform as transform_task
from apps.transformation.services.chunk_processing_service import (
    ChunkResult, ChunkResultStatus, PermanentChunkError)


class StubChunkService:
    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.record_failure_calls = []

    def process(self, *args, **kwargs):
        if self._raises:
            raise self._raises
        return self._result

    def record_failure(self, *args, **kwargs):
        self.record_failure_calls.append({"args": args, "kwargs": kwargs})


class StubChunkFactory:
    def __init__(self, service):
        self._service = service

    def create(self):
        return self._service


def _run(monkeypatch, service):
    monkeypatch.setattr(transform_task, "ChunkProcessingServiceFactory", StubChunkFactory(service))
    return transform_task.process_chunk.apply(
        args=["job-1", "chunk-key", 0, 999, 3, "csv"], throw=True
    )


class TestProcessChunkLockConflict:
    # Regression coverage for the gap where a lock conflict — the only
    # realistic cause being a genuinely concurrent duplicate task delivery —
    # was a clean, silent return: no exception, so no Celery retry, and no
    # record of the range ever needing another attempt.

    def test_lock_conflict_triggers_a_retry(self, monkeypatch):
        service = StubChunkService(result=ChunkResult(status=ChunkResultStatus.LOCK_CONFLICT))

        with pytest.raises(Retry):
            _run(monkeypatch, service)

    def test_lock_conflict_does_not_record_a_failure(self, monkeypatch):
        # A lock conflict isn't a domain-level failure — recording it in
        # failed_chunks would show a caller a misleading "error" for what is
        # actually healthy contention, and would flip the job to PARTIAL for
        # no real reason.
        service = StubChunkService(result=ChunkResult(status=ChunkResultStatus.LOCK_CONFLICT))

        with pytest.raises(Retry):
            _run(monkeypatch, service)

        assert service.record_failure_calls == []

    def test_ok_result_does_not_retry(self, monkeypatch):
        service = StubChunkService(
            result=ChunkResult(status=ChunkResultStatus.OK, job_complete=False)
        )

        result = _run(monkeypatch, service)

        assert result.successful()

    def test_already_done_result_does_not_retry(self, monkeypatch):
        service = StubChunkService(result=ChunkResult(status=ChunkResultStatus.ALREADY_DONE))

        result = _run(monkeypatch, service)

        assert result.successful()

    def test_not_found_result_does_not_retry(self, monkeypatch):
        service = StubChunkService(result=ChunkResult(status=ChunkResultStatus.NOT_FOUND))

        result = _run(monkeypatch, service)

        assert result.successful()

    def test_a_real_exception_still_records_a_failure_and_retries(self, monkeypatch):
        # Existing behavior, unchanged by this fix — must not regress.
        service = StubChunkService(raises=ValueError("boom"))

        with pytest.raises(Retry):
            _run(monkeypatch, service)

        assert len(service.record_failure_calls) == 1
        assert service.record_failure_calls[0]["kwargs"]["retryable"] is True


class TestProcessChunkPermanentFailure:
    # A PermanentChunkError will fail identically on every retry
    # (missing template, no converter for the format) — retrying it via
    # Celery's own budget is pure waste of 3 x default_retry_delay for a
    # certain repeat failure.

    def test_does_not_retry(self, monkeypatch):
        service = StubChunkService(raises=PermanentChunkError("no converter"))

        result = _run(monkeypatch, service)

        assert result.successful()  # no Retry raised, task just completes

    def test_records_the_failure_as_not_retryable(self, monkeypatch):
        service = StubChunkService(raises=PermanentChunkError("no converter"))

        _run(monkeypatch, service)

        assert len(service.record_failure_calls) == 1
        assert service.record_failure_calls[0]["kwargs"]["retryable"] is False
