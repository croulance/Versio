from apps.transformation.enums import JobStatus
from apps.transformation.services.job_lifecycle_service import \
    JobLifecycleService
from apps.transformation.services.merge_service import (MergeResultStatus,
                                                         MergeService)


class FakeJob:
    def __init__(self, template_id=3, status=JobStatus.PROCESSING):
        self.template_id = template_id
        self.status = status


class FakeJobRepository:
    def __init__(self, job=None):
        self._job = job if job is not None else FakeJob()
        self.mark_done_calls = []

    def get(self, job_id):
        return self._job

    def mark_done(self, job_id, output_storage_path):
        self.mark_done_calls.append((job_id, output_storage_path))
        if self._job:
            self._job.status = JobStatus.DONE


class FakeTemplate:
    def __init__(self, metadata):
        self.metadata = metadata


class FakeTemplateRepository:
    def __init__(self, template=None):
        self._template = template

    def get_with_mappings_by_id(self, template_id):
        return self._template


class FakeCache:
    def __init__(self):
        self.invalidate_calls = []

    def invalidate_job_report(self, job_id):
        self.invalidate_calls.append(job_id)


class FakeStorage:
    def __init__(self, keys):
        self._keys = keys
        self.written = {}

    def list_keys(self, prefix):
        return [k for k in self._keys if k.startswith(prefix)]

    def put_object(self, key, body):
        self.written[key] = body


class FakeMerger:
    def __init__(self, output=b"merged-content"):
        self.output = output
        self.calls = []

    def merge(self, keys, metadata):
        self.calls.append((keys, metadata))
        return self.output


def _service(job=None, template=None, keys=None, merger=None, errors_merger=None):
    job_repo = FakeJobRepository(job)
    template_repo = FakeTemplateRepository(template)
    cache = FakeCache()
    storage = FakeStorage(keys or [])
    mergers = {"csv": merger or FakeMerger()}
    if errors_merger is not None:
        mergers["errors"] = errors_merger
    lifecycle = JobLifecycleService(job_repository=job_repo, cache=cache)
    service = MergeService(
        template_repository=template_repo,
        job_repository=job_repo,
        mergers=mergers,
        storage=storage,
        lifecycle=lifecycle,
    )
    return service, job_repo, template_repo, cache, storage


class TestMerge:
    def test_job_not_found(self):
        service, job_repo, *_ = _service(job=None)
        job_repo._job = None

        assert service.merge("job-1", "csv") == MergeResultStatus.NOT_FOUND

    def test_already_done_job_is_a_no_op(self):
        # Celery's task_acks_late means merge_output can be redelivered (a
        # worker dies after finishing the merge but before the broker sees
        # the ack). Re-running a full merge is wasted work at best; this
        # guard makes it a clean no-op instead.
        merger = FakeMerger()
        job = FakeJob(status=JobStatus.DONE)
        service, job_repo, *_ = _service(
            job=job, keys=["outputs/job-1/job-1_0_1.csv"], merger=merger
        )

        result = service.merge("job-1", "csv")

        assert result == MergeResultStatus.ALREADY_DONE
        assert merger.calls == []
        assert job_repo.mark_done_calls == []

    def test_no_chunk_files_found(self):
        service, *_ = _service(keys=[])

        assert service.merge("job-1", "csv") == MergeResultStatus.NO_CHUNKS

    def test_unsupported_format_has_no_merger_registered(self):
        service, *_ = _service(keys=["outputs/job-1/job-1_0_1.geojson"])

        assert service.merge("job-1", "geojson") == MergeResultStatus.UNSUPPORTED_FORMAT

    def test_successful_merge_writes_output_and_marks_done(self):
        merger = FakeMerger(output=b"final-bytes")
        keys = ["outputs/job-1/job-1_0_1.csv"]
        service, job_repo, template_repo, cache, storage = _service(
            keys=keys, merger=merger, template=FakeTemplate({"headers": ["Name"]})
        )

        result = service.merge("job-1", "csv")

        assert result == MergeResultStatus.OK
        assert storage.written["outputs/job-1/final.csv"] == b"final-bytes"
        assert job_repo.mark_done_calls == [("job-1", "outputs/job-1/final.csv")]
        assert cache.invalidate_calls == ["job-1"]
        assert merger.calls[0][1] == {
            "headers": ["Name"]
        }  # template metadata passed through

    def test_metadata_is_empty_dict_when_template_missing(self):
        merger = FakeMerger()
        service, *_ = _service(
            keys=["outputs/job-1/job-1_0_1.csv"], merger=merger, template=None
        )

        service.merge("job-1", "csv")

        assert merger.calls[0][1] == {}

    def test_chunk_keys_filtered_by_format_and_final_excluded(self):
        merger = FakeMerger()
        keys = [
            "outputs/job-1/job-1_0_499.csv",
            "outputs/job-1/job-1_500_999.csv",
            "outputs/job-1/job-1_0_499.geojson",  # different format, must be excluded
            "outputs/job-1/final.csv",  # a stale final file, must be excluded
        ]
        service, *_ = _service(keys=keys, merger=merger)

        service.merge("job-1", "csv")

        assert merger.calls[0][0] == [
            "outputs/job-1/job-1_0_499.csv",
            "outputs/job-1/job-1_500_999.csv",
        ]

    def test_chunk_keys_sorted_by_embedded_start_index_not_string_order(self):
        merger = FakeMerger()
        keys = [
            "outputs/job-1/job-1_1000_1499.csv",
            "outputs/job-1/job-1_0_499.csv",
            "outputs/job-1/job-1_500_999.csv",
        ]
        service, *_ = _service(keys=keys, merger=merger)

        service.merge("job-1", "csv")

        assert merger.calls[0][0] == [
            "outputs/job-1/job-1_0_499.csv",
            "outputs/job-1/job-1_500_999.csv",
            "outputs/job-1/job-1_1000_1499.csv",
        ]


class RaisingMerger:
    def merge(self, keys, metadata):
        raise RuntimeError("errors merge blew up")


class TestMergeErrors:
    """MergeService also merges per-chunk .errors.json skip-trace
    files into final.errors.json, reusing the same MergerInterface/registry
    machinery as real output — but only ever as a best-effort side channel
    that must never block the real merge or job completion."""

    def test_no_error_chunks_means_no_errors_file_and_no_errors_merger_call(self):
        errors_merger = FakeMerger()
        keys = ["outputs/job-1/job-1_0_1.csv"]
        service, job_repo, *_, storage = _service(
            keys=keys, errors_merger=errors_merger
        )

        result = service.merge("job-1", "csv")

        assert result == MergeResultStatus.OK
        assert errors_merger.calls == []
        assert "outputs/job-1/final.errors.json" not in storage.written
        assert job_repo.mark_done_calls == [("job-1", "outputs/job-1/final.csv")]

    def test_error_chunks_present_are_merged_into_final_errors_json(self):
        errors_merger = FakeMerger(output=b'[{"position": 0, "error": "boom"}]')
        keys = [
            "outputs/job-1/job-1_0_499.csv",
            "outputs/job-1/job-1_0_499.errors.json",
            "outputs/job-1/job-1_500_999.errors.json",
        ]
        service, job_repo, *_, storage = _service(
            keys=keys, errors_merger=errors_merger
        )

        result = service.merge("job-1", "csv")

        assert result == MergeResultStatus.OK
        assert errors_merger.calls[0][0] == [
            "outputs/job-1/job-1_0_499.errors.json",
            "outputs/job-1/job-1_500_999.errors.json",
        ]
        assert (
            storage.written["outputs/job-1/final.errors.json"]
            == b'[{"position": 0, "error": "boom"}]'
        )
        # The main merge/job completion still happened.
        assert job_repo.mark_done_calls == [("job-1", "outputs/job-1/final.csv")]

    def test_missing_errors_merger_registration_does_not_break_main_merge(self):
        keys = [
            "outputs/job-1/job-1_0_499.csv",
            "outputs/job-1/job-1_0_499.errors.json",
        ]
        service, job_repo, *_, storage = _service(keys=keys)  # no errors_merger

        result = service.merge("job-1", "csv")

        assert result == MergeResultStatus.OK
        assert "outputs/job-1/final.errors.json" not in storage.written
        assert job_repo.mark_done_calls == [("job-1", "outputs/job-1/final.csv")]

    def test_errors_merger_raising_is_best_effort_and_does_not_fail_the_job(self):
        keys = [
            "outputs/job-1/job-1_0_499.csv",
            "outputs/job-1/job-1_0_499.errors.json",
        ]
        service, job_repo, *_, storage = _service(
            keys=keys, errors_merger=RaisingMerger()
        )

        result = service.merge("job-1", "csv")

        assert result == MergeResultStatus.OK
        assert "outputs/job-1/final.errors.json" not in storage.written
        assert job_repo.mark_done_calls == [("job-1", "outputs/job-1/final.csv")]
