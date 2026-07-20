import datetime

from apps.transformation.enums import JobStatus
from apps.transformation.services.job_lifecycle_service import (
    JobLifecycleService, ResumeAction)


class FakeJob:
    def __init__(
        self,
        id="job-1",
        status=JobStatus.PENDING,
        processed_chunks=0,
        total_chunks=3,
        started_at=None,
        storage_path="inputs/x/x.json",
        source_path="data.items.item",
        chunk_size=1000,
        template_id=3,
        format="csv",
        failed_chunks=None,
    ):
        self.id = id
        self.status = status
        self.processed_chunks = processed_chunks
        self.total_chunks = total_chunks
        self.started_at = started_at
        self.storage_path = storage_path
        self.source_path = source_path
        self.chunk_size = chunk_size
        self.template_id = template_id
        self.format = format
        self.failed_chunks = failed_chunks or []


class FakeJobRepository:
    def __init__(self, job=None):
        self._job = job
        self.start_processing_calls = []
        self.set_status_calls = []
        self.reset_calls = []
        self.mark_done_calls = []
        self.mark_failed_calls = []

    def get(self, job_id):
        return self._job

    def start_processing(self, job_id):
        self.start_processing_calls.append(job_id)
        if self._job and self._job.status == JobStatus.PENDING:
            self._job.status = JobStatus.PROCESSING

    def set_status(self, job_id, status):
        self.set_status_calls.append(status)
        if self._job:
            self._job.status = status

    def reset(self, job_id):
        self.reset_calls.append(job_id)
        if self._job:
            self._job.status = JobStatus.PENDING
            self._job.processed_chunks = 0

    def mark_done(self, job_id, output_storage_path):
        self.mark_done_calls.append((job_id, output_storage_path))
        if self._job:
            self._job.status = JobStatus.DONE

    def mark_failed(self, job_id):
        self.mark_failed_calls.append(job_id)
        if self._job:
            self._job.status = JobStatus.FAILED

    def clear_failed_chunk(self, job_id, start, end):
        pass

    def append_failed_chunk(self, job_id, chunk):
        pass


class FakeCache:
    def __init__(self):
        self.invalidate_calls = []

    def invalidate_job_report(self, job_id):
        self.invalidate_calls.append(job_id)


def _service(job=None):
    repo = FakeJobRepository(job)
    cache = FakeCache()
    return JobLifecycleService(job_repository=repo, cache=cache), repo, cache


class TestBegin:
    def test_starts_a_pending_job(self):
        job = FakeJob(status=JobStatus.PENDING)
        service, repo, cache = _service(job)

        service.begin("job-1")

        assert job.status == JobStatus.PROCESSING
        assert cache.invalidate_calls == ["job-1"]


class TestCompleted:
    def test_marks_done(self):
        job = FakeJob(status=JobStatus.PROCESSING)
        service, repo, cache = _service(job)

        result = service.completed("job-1", "outputs/job-1/final.csv")

        assert result is True
        assert job.status == JobStatus.DONE
        assert repo.mark_done_calls == [("job-1", "outputs/job-1/final.csv")]

    def test_no_op_if_already_done(self):
        # A redelivered merge_output task must not re-run.
        job = FakeJob(status=JobStatus.DONE)
        service, repo, cache = _service(job)

        result = service.completed("job-1", "outputs/job-1/final.csv")

        assert result is False
        assert repo.mark_done_calls == []
        assert cache.invalidate_calls == []


class TestAbandon:
    def test_marks_failed(self):
        job = FakeJob(status=JobStatus.PROCESSING)
        service, repo, cache = _service(job)

        service.abandon("job-1")

        assert job.status == JobStatus.FAILED
        assert repo.mark_failed_calls == ["job-1"]
        assert cache.invalidate_calls == ["job-1"]


class TestCanRetry:
    # can_retry has no injectable clock (correctly, for production use), so
    # these use real relative time rather than a fixed historical anchor.
    def _now(self):
        return datetime.datetime.now(datetime.timezone.utc)

    def test_non_processing_job_can_always_be_retried(self):
        for status in (JobStatus.PENDING, JobStatus.PARTIAL, JobStatus.FAILED):
            job = FakeJob(status=status)
            service, *_ = _service(job)
            assert service.can_retry(job) is True

    def test_recently_started_processing_job_cannot_be_retried(self):
        job = FakeJob(
            status=JobStatus.PROCESSING,
            started_at=self._now() - datetime.timedelta(minutes=5),
        )
        service, *_ = _service(job)
        assert service.can_retry(job) is False

    def test_stalled_processing_job_can_be_retried(self):
        job = FakeJob(
            status=JobStatus.PROCESSING,
            started_at=self._now() - datetime.timedelta(hours=3),
        )
        service, *_ = _service(job)
        assert service.can_retry(job) is True


class TestResume:
    def test_no_progress_resets_and_dispatches_split(self, monkeypatch):
        import apps.transformation.tasks.transform as transform_task

        dispatched = []
        monkeypatch.setattr(
            transform_task.split_and_dispatch_chunks,
            "apply_async",
            lambda args, queue: dispatched.append({"args": args, "queue": queue}),
        )
        job = FakeJob(status=JobStatus.PENDING, processed_chunks=0)
        service, repo, cache = _service(job)

        action = service.resume(job)

        assert action == ResumeAction.RESET
        assert repo.reset_calls == ["job-1"]
        assert len(dispatched) == 1
        assert dispatched[0]["args"][0] == "job-1"

    def test_real_progress_resumes_in_place_without_resetting(self, monkeypatch):
        # A job with real chunk output already in storage must never have
        # its counter reset -- the idempotency guard would then permanently
        # cap it below total_chunks on redispatch.
        import apps.transformation.tasks.transform as transform_task

        monkeypatch.setattr(
            transform_task.split_and_dispatch_chunks, "apply_async", lambda args, queue: None
        )
        job = FakeJob(status=JobStatus.PROCESSING, processed_chunks=5, total_chunks=10)
        service, repo, cache = _service(job)

        action = service.resume(job)

        assert action == ResumeAction.RESUME_IN_PLACE
        assert repo.reset_calls == []
        assert job.processed_chunks == 5  # untouched
        assert job.status == JobStatus.PROCESSING


class TestResumeMerge:
    def test_redispatches_merge_without_resplitting(self, monkeypatch):
        import apps.transformation.tasks.merge as merge_task

        dispatched = []
        monkeypatch.setattr(
            merge_task.merge_output,
            "apply_async",
            lambda args, queue: dispatched.append({"args": args, "queue": queue}),
        )
        job = FakeJob(status=JobStatus.PROCESSING, processed_chunks=10, total_chunks=10)
        service, repo, cache = _service(job)

        service.resume_merge(job)

        assert len(dispatched) == 1
        assert dispatched[0]["args"] == ["job-1", "csv"]

    def test_sets_processing_if_the_job_was_stalled_past_a_status_that_isnt_processing(
        self, monkeypatch
    ):
        import apps.transformation.tasks.merge as merge_task

        monkeypatch.setattr(merge_task.merge_output, "apply_async", lambda args, queue: None)
        job = FakeJob(status=JobStatus.FAILED, processed_chunks=10, total_chunks=10)
        service, repo, cache = _service(job)

        service.resume_merge(job)

        assert job.status == JobStatus.PROCESSING


class TestMarkRetrying:
    def test_dispatching_every_known_failure_sets_processing(self, monkeypatch):
        import apps.transformation.tasks.transform as transform_task

        dispatched = []
        monkeypatch.setattr(
            transform_task.process_chunk,
            "apply_async",
            lambda args, queue: dispatched.append({"args": args, "queue": queue}),
        )
        chunks = [{"start": 0, "end": 499}, {"start": 500, "end": 999}]
        job = FakeJob(status=JobStatus.PARTIAL, failed_chunks=list(chunks))
        service, repo, cache = _service(job)

        result = service.mark_retrying(job, chunks)

        assert job.status == JobStatus.PROCESSING
        assert result == chunks
        assert len(dispatched) == 2

    def test_dispatching_only_a_subset_leaves_status_at_partial(self, monkeypatch):
        # Regression test: the PARTIAL sweep only ever dispatches the
        # *retryable* subset of failed_chunks, deliberately leaving
        # permanent failures behind. If this optimistically set PROCESSING
        # anyway, a real, still-unresolved permanent failure would sit
        # silently behind a status claiming nothing is wrong -- exactly the
        # class of bug this whole service exists to prevent, just via a new
        # code path instead of the original one (chunk_processing_service's
        # unconditional set_status).
        import apps.transformation.tasks.transform as transform_task

        monkeypatch.setattr(
            transform_task.process_chunk, "apply_async", lambda args, queue: None
        )
        retryable_chunk = {"start": 0, "end": 499, "retryable": True}
        permanent_chunk = {"start": 500, "end": 999, "retryable": False}
        job = FakeJob(
            status=JobStatus.PARTIAL,
            failed_chunks=[retryable_chunk, permanent_chunk],
        )
        service, repo, cache = _service(job)

        service.mark_retrying(job, [retryable_chunk])

        assert job.status == JobStatus.PARTIAL  # NOT silently PROCESSING
        assert repo.set_status_calls == []


class TestRetryableFailedChunks:
    def test_filters_out_permanent_entries(self):
        job = FakeJob(
            failed_chunks=[
                {"start": 0, "end": 499, "retryable": True},
                {"start": 500, "end": 999, "retryable": False},
            ]
        )
        service, *_ = _service(job)

        result = service.retryable_failed_chunks(job)

        assert result == [{"start": 0, "end": 499, "retryable": True}]

    def test_entries_without_a_retryable_key_default_to_retryable(self):
        # Backward compatibility with any failed_chunks entry written before
        # this field existed.
        job = FakeJob(failed_chunks=[{"start": 0, "end": 499}])
        service, *_ = _service(job)

        result = service.retryable_failed_chunks(job)

        assert result == [{"start": 0, "end": 499}]
