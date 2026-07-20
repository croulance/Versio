import datetime
from dataclasses import dataclass

from apps.transformation.enums import JobStatus
from apps.transformation.utils.job_recovery import (is_processing_stalled,
                                                     safe_to_reset)


@dataclass
class FakeJob:
    status: str
    processed_chunks: int = 0
    started_at: datetime.datetime | None = None


class TestSafeToReset:
    def test_no_progress_is_safe_to_reset(self):
        assert safe_to_reset(FakeJob(status=JobStatus.PENDING, processed_chunks=0)) is True

    def test_any_real_progress_is_not_safe_to_reset(self):
        # Resetting would zero the counter while the chunks' real output
        # files stay in storage — the idempotency guard would then make those
        # chunks re-report ALREADY_DONE without ever incrementing the
        # reset counter back up, permanently capping the job below
        # total_chunks. This is the exact bug this function exists to prevent.
        assert safe_to_reset(FakeJob(status=JobStatus.PROCESSING, processed_chunks=1)) is False

    def test_large_progress_is_not_safe_to_reset(self):
        assert safe_to_reset(FakeJob(status=JobStatus.PROCESSING, processed_chunks=7)) is False


class TestIsProcessingStalled:
    NOW = datetime.datetime(2026, 7, 17, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def test_non_processing_job_is_never_stalled(self):
        job = FakeJob(
            status=JobStatus.PARTIAL,
            started_at=self.NOW - datetime.timedelta(hours=5),
        )
        assert is_processing_stalled(job, stall_minutes=60, now=self.NOW) is False

    def test_processing_job_with_no_started_at_is_not_stalled(self):
        # Shouldn't happen in practice (set_status(PROCESSING) always sets
        # started_at) but a missing timestamp must never be treated as
        # "infinitely old" and misfire.
        job = FakeJob(status=JobStatus.PROCESSING, started_at=None)
        assert is_processing_stalled(job, stall_minutes=60, now=self.NOW) is False

    def test_recently_started_processing_job_is_not_stalled(self):
        job = FakeJob(
            status=JobStatus.PROCESSING,
            started_at=self.NOW - datetime.timedelta(minutes=5),
        )
        assert is_processing_stalled(job, stall_minutes=60, now=self.NOW) is False

    def test_long_running_processing_job_is_stalled(self):
        job = FakeJob(
            status=JobStatus.PROCESSING,
            started_at=self.NOW - datetime.timedelta(hours=3),
        )
        assert is_processing_stalled(job, stall_minutes=60, now=self.NOW) is True

    def test_exactly_at_the_threshold_counts_as_stalled(self):
        job = FakeJob(
            status=JobStatus.PROCESSING,
            started_at=self.NOW - datetime.timedelta(minutes=60),
        )
        assert is_processing_stalled(job, stall_minutes=60, now=self.NOW) is True

    def test_one_minute_under_the_threshold_is_not_stalled(self):
        job = FakeJob(
            status=JobStatus.PROCESSING,
            started_at=self.NOW - datetime.timedelta(minutes=59),
        )
        assert is_processing_stalled(job, stall_minutes=60, now=self.NOW) is False
