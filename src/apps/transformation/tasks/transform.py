import logging

from celery import shared_task
from django.conf import settings

import apps.transformation.converters  # noqa: F401 — triggers @register_converter decorators
import apps.transformation.handlers  # noqa: F401 — registers all handlers
from apps.transformation.factories.service_factory import (
    ChunkProcessingServiceFactory, TransformationServiceFactory)
from apps.transformation.services.chunk_processing_service import (
    ChunkResultStatus, PermanentChunkError)

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="default")
def split_and_dispatch_chunks(
    self,
    job_id: str,
    storage_path: str,
    source_path: str,
    chunk_size: int,
    template_id: int,
    format: str,
):
    """Splits a job's source file into one storage object per chunk and
    dispatches that chunk's process_chunk task, all in a single pass —
    dispatched from TransformationService.submit() instead of
    running inline there, since it's too slow (a full sequential file read
    plus total_chunks storage writes) to do inside the submission request.
    Also re-dispatched by JobRetryView/retry_stuck_jobs to recover a job
    whose chunks were dropped before ever being split."""
    try:
        TransformationServiceFactory.create().split_and_dispatch_chunks(
            job_id, storage_path, source_path, chunk_size, template_id, format
        )
    except Exception as exc:
        logger.exception(f"split_and_dispatch_chunks failed for job {job_id}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="chunks")
def process_chunk(
    self,
    job_id: str,
    chunk_storage_key: str,
    start: int,
    end: int,
    template_id: int,
    format: str,
):
    service = ChunkProcessingServiceFactory.create()
    try:
        result = service.process(
            job_id, chunk_storage_key, start, end, template_id, format
        )
    except PermanentChunkError as exc:
        # Will fail identically on every retry (missing template, no
        # converter for this format) — recording it and stopping here saves
        # 3 x default_retry_delay of Celery retrying a certain repeat
        # failure. Only a human fixing the underlying config and triggering
        # a manual retry can resolve this; the automatic PARTIAL sweep
        # skips entries marked non-retryable for the same reason.
        service.record_failure(
            job_id, start, end, exc, self.request.retries, retryable=False
        )
        logger.exception(f"Chunk [{start}:{end}] for job {job_id} failed permanently")
        return
    except Exception as exc:
        service.record_failure(
            job_id, start, end, exc, self.request.retries, retryable=True
        )
        logger.exception(f"Chunk [{start}:{end}] for job {job_id} failed")
        raise self.retry(exc=exc)

    if result.status == ChunkResultStatus.LOCK_CONFLICT:
        # Not a domain failure — the only realistic cause is a genuinely
        # concurrent duplicate delivery of this exact task, where the lock's
        # current holder is expected to finish the work. Retrying (rather
        # than the previous silent no-op) means a redelivery that instead
        # raced a *stale* lock — the original holder's worker was killed
        # mid-task — doesn't just give up; it comes back after the lock's
        # TTL has had a chance to expire. Not recorded via record_failure:
        # that would surface as a misleading domain error for what is really
        # just contention.
        logger.info(f"Chunk [{start}:{end}] job={job_id} lock conflict — retrying")
        raise self.retry(countdown=60)

    if result.job_complete:
        from apps.transformation.tasks.merge import merge_output

        merge_output.apply_async(
            args=[job_id, format], queue=settings.CELERY_MERGE_QUEUE
        )
        logger.info(f"Job {job_id} all chunks done — merge dispatched")
