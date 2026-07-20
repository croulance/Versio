from datetime import timedelta

from django.utils import timezone

from apps.transformation.enums import JobStatus


def safe_to_reset(job) -> bool:
    """True only if resetting processed_chunks to 0 costs nothing real.

    A job with processed_chunks == 0 has never incremented the counter, so
    zeroing it again is a no-op. A job with processed_chunks > 0 has real
    chunk output files already sitting in storage — resetting the counter
    would make those chunks look unprocessed to a human, but re-dispatching
    them would still hit the output-existence guard and return
    ALREADY_DONE without incrementing anything, permanently capping
    processed_chunks below total_chunks. Recovery for that case must resume
    dispatch without resetting instead (see JobLifecycleService.resume)."""
    return job.processed_chunks == 0


def is_processing_stalled(job, stall_minutes: int, now=None) -> bool:
    """True if a PROCESSING job has been running long enough that it's more
    likely stuck (a lost chunk task) than genuinely still working. Only
    meaningful for PROCESSING jobs with a recorded start time — anything
    else is never considered stalled by this check."""
    if job.status != JobStatus.PROCESSING or not job.started_at:
        return False
    now = now or timezone.now()
    return (now - job.started_at) >= timedelta(minutes=stall_minutes)
