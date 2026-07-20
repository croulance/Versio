import logging

from celery import shared_task

from apps.transformation.factories.service_factory import MergeServiceFactory
from apps.transformation.services.merge_service import MergeResultStatus

logger = logging.getLogger(__name__)

_RETRYABLE_RESULTS = (MergeResultStatus.NO_CHUNKS, MergeResultStatus.UNSUPPORTED_FORMAT)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="default")
def merge_output(self, job_id: str, format: str):
    try:
        result = MergeServiceFactory.create().merge(job_id, format)
    except Exception as exc:
        logger.exception(f"merge_output failed for job {job_id}")
        raise self.retry(exc=exc)

    if result in _RETRYABLE_RESULTS:
        # NO_CHUNKS in particular is plausibly just storage-listing lag
        # right after the last chunk's write, not a real absence of output —
        # worth a few retries before giving up. If every chunk truly has no
        # merger (UNSUPPORTED_FORMAT), retrying won't fix that either, but
        # the cost is bounded by max_retries either way, and the stuck-job
        # sweep is the backstop if this job is still stuck at
        # processed_chunks == total_chunks after this task gives up.
        logger.warning(f"merge_output for job {job_id} returned {result} — retrying")
        raise self.retry(countdown=60)
