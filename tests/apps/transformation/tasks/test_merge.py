import pytest
from celery.exceptions import Retry

import apps.transformation.tasks.merge as merge_task
from apps.transformation.services.merge_service import MergeResultStatus


class StubMergeService:
    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises

    def merge(self, job_id, format):
        if self._raises:
            raise self._raises
        return self._result


class StubMergeFactory:
    def __init__(self, service):
        self._service = service

    def create(self):
        return self._service


def _run(monkeypatch, service):
    monkeypatch.setattr(merge_task, "MergeServiceFactory", StubMergeFactory(service))
    return merge_task.merge_output.apply(args=["job-1", "csv"], throw=True)


class TestMergeOutputRetryableResults:
    # Before this, tasks/merge.py discarded MergeService.merge()'s
    # return value entirely -- NO_CHUNKS/UNSUPPORTED_FORMAT (neither of
    # which raises) silently completed the task with the job left stuck at
    # PROCESSING, 100% chunks done, forever.

    def test_no_chunks_triggers_a_retry(self, monkeypatch):
        service = StubMergeService(result=MergeResultStatus.NO_CHUNKS)

        with pytest.raises(Retry):
            _run(monkeypatch, service)

    def test_unsupported_format_triggers_a_retry(self, monkeypatch):
        service = StubMergeService(result=MergeResultStatus.UNSUPPORTED_FORMAT)

        with pytest.raises(Retry):
            _run(monkeypatch, service)

    def test_ok_does_not_retry(self, monkeypatch):
        service = StubMergeService(result=MergeResultStatus.OK)

        result = _run(monkeypatch, service)

        assert result.successful()

    def test_not_found_does_not_retry(self, monkeypatch):
        service = StubMergeService(result=MergeResultStatus.NOT_FOUND)

        result = _run(monkeypatch, service)

        assert result.successful()

    def test_already_done_does_not_retry(self, monkeypatch):
        # The redelivery guard -- a redelivered task finding the job
        # already DONE must not retry, just complete quietly.
        service = StubMergeService(result=MergeResultStatus.ALREADY_DONE)

        result = _run(monkeypatch, service)

        assert result.successful()

    def test_a_real_exception_still_retries(self, monkeypatch):
        # Existing behavior, unchanged by this fix.
        service = StubMergeService(raises=ValueError("boom"))

        with pytest.raises(Retry):
            _run(monkeypatch, service)
