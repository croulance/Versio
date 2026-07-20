import logging
from datetime import datetime, timezone
from enum import Enum

from django.conf import settings

from apps.transformation.enums import JobStatus
from apps.transformation.interfaces.cache import CacheAdapterInterface
from apps.transformation.interfaces.repository import JobRepositoryInterface
from apps.transformation.utils.chunking import chunk_input_key
from apps.transformation.utils.job_recovery import (is_processing_stalled,
                                                    safe_to_reset)

logger = logging.getLogger(__name__)


class ResumeAction(Enum):
    RESET = "reset"
    RESUME_IN_PLACE = "resume_in_place"


class JobLifecycleService:
    """The single place that knows which TransformationJob status
    transitions are legal and applies them — replacing
    status-writing calls that used to be scattered across
    ChunkProcessingService, tasks/merge.py, views/retry.py, and
    retry_stuck_jobs.py. Repositories still own the actual atomic writes
    and their terminal-state (DONE/FAILED) guards; this service owns the
    decision of when to call them and the side effects (Celery dispatch,
    cache invalidation) that go with each transition."""

    def __init__(
        self,
        job_repository: JobRepositoryInterface,
        cache: CacheAdapterInterface,
    ):
        self._repo = job_repository
        self._cache = cache

    # ------------------------------------------------------------------
    # Per-chunk lifecycle events
    # ------------------------------------------------------------------

    def begin(self, job_id: str) -> None:
        """PENDING -> PROCESSING. No-op if the job isn't currently PENDING —
        in particular, never stomps PARTIAL. Before this existed, a plain
        unconditional set_status(PROCESSING) ran on every chunk regardless
        of the job's current status, silently overwriting a real unresolved
        PARTIAL the moment any unrelated chunk started."""
        self._repo.start_processing(job_id)
        self._cache.invalidate_job_report(job_id)

    def chunk_succeeded(self, job_id: str, start: int, end: int) -> None:
        """Clears this range from failed_chunks if present. PARTIAL only
        ever moves to PROCESSING here, and only when that clear empties the
        list entirely — never as a side effect of an unrelated chunk merely
        starting or succeeding. No-op against a DONE/FAILED job
        (repository-enforced)."""
        self._repo.clear_failed_chunk(job_id, start, end)
        self._cache.invalidate_job_report(job_id)

    def chunk_failed(
        self,
        job_id: str,
        start: int,
        end: int,
        error: Exception,
        retry_count: int,
        retryable: bool,
    ) -> None:
        """-> PARTIAL. No-op against a DONE/FAILED job (repository-enforced,
        inside the same locked transaction as the write) — a task still in
        flight when the job was resolved or abandoned must not regress it.
        `retryable` is what later lets the automatic PARTIAL sweep tell a
        transient failure (worth another shot) from a permanent one (a
        mapping bug that will fail identically every time, that only a
        human fixing the config and retrying manually can resolve)."""
        entry = {
            "start": start,
            "end": end,
            "error": str(error),
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": retry_count,
            "retryable": retryable,
        }
        self._repo.append_failed_chunk(job_id, entry)
        self._cache.invalidate_job_report(job_id)

    # ------------------------------------------------------------------
    # Job-level lifecycle events
    # ------------------------------------------------------------------

    def completed(self, job_id: str, output_storage_path: str) -> bool:
        """-> DONE. No-op (returns False) if already DONE — covers a
        redelivered merge_output task (task_acks_late)."""
        job = self._repo.get(job_id)
        if job and job.status == JobStatus.DONE:
            return False
        self._repo.mark_done(job_id, output_storage_path)
        self._cache.invalidate_job_report(job_id)
        return True

    def abandon(self, job_id: str) -> None:
        """-> FAILED. Sweep-only — a job past its max-age ceiling that
        automated recovery gave up on. Still retriable manually afterward;
        FAILED never forecloses recovery, it just makes "nobody's actively
        retrying this anymore" visible instead of leaving it indistinguishable
        from a healthy job."""
        self._repo.mark_failed(job_id)
        self._cache.invalidate_job_report(job_id)

    def can_retry(self, job) -> bool:
        """False only for a genuinely still-active PROCESSING job — not
        stalled long enough to be considered abandoned. Every other status
        can attempt a retry; which branch applies depends on what's actually
        wrong (see resume/resume_merge/mark_retrying)."""
        if job.status != JobStatus.PROCESSING:
            return True
        return is_processing_stalled(job, settings.STUCK_PROCESSING_JOB_MIN_AGE_MINUTES)

    def resume(self, job) -> ResumeAction:
        """Bring an incomplete job (processed_chunks < total_chunks, no
        pending failed_chunks) back to active work, and dispatch the
        split+chunk pipeline. Full reset only if nothing would be lost
        (safe_to_reset) — a job with real progress resumes in place (set
        PROCESSING, counter untouched) instead, since resetting would make
        the idempotency guard silently skip re-counting already-done
        chunks on redispatch, permanently capping the job below
        total_chunks."""
        job_id = str(job.id)
        if safe_to_reset(job):
            self._repo.reset(job_id)
            action = ResumeAction.RESET
        else:
            if job.status != JobStatus.PROCESSING:
                self._repo.set_status(job_id, JobStatus.PROCESSING)
            action = ResumeAction.RESUME_IN_PLACE
        self._cache.invalidate_job_report(job_id)
        self._retrigger_split_and_dispatch(job)
        return action

    def resume_merge(self, job) -> None:
        """A job at processed_chunks == total_chunks but not DONE — the
        merge never completed (its own retries exhausted, or the task was
        lost). Re-splitting here would accomplish nothing: every chunk
        would immediately hit the idempotency ALREADY_DONE guard and return
        early without recomputing job_complete, so it would never
        re-trigger merge_output. The only useful recovery action is to
        redispatch the merge directly."""
        job_id = str(job.id)
        if job.status != JobStatus.PROCESSING:
            self._repo.set_status(job_id, JobStatus.PROCESSING)
            self._cache.invalidate_job_report(job_id)
        self._redispatch_merge(job)

    def mark_retrying(self, job, chunks: list) -> list:
        """Explicit retry of specific/all failed chunks — operator- or
        sweep-triggered. Dispatches the chunks and returns what was
        dispatched.

        Only sets PROCESSING immediately if this dispatch covers every
        currently-known failure — a deliberate, transient decoupling from
        failed_chunks (not cleared until each dispatched chunk actually
        resolves), accepted so a caller re-polling right after sees active
        progress instead of a stale PARTIAL. If something is NOT covered
        (the PARTIAL sweep deliberately leaving permanent failures behind,
        e.g.) status stays PARTIAL — that failure is still genuinely
        unresolved, and setting PROCESSING here would hide a real, lasting
        problem behind a status that claims nothing is wrong. clear_failed_chunk
        is what correctly moves it to PROCESSING later, once the list is
        truly empty."""
        job_id = str(job.id)
        dispatching = {(c["start"], c["end"]) for c in chunks}
        left_behind = [
            c
            for c in (job.failed_chunks or [])
            if (c["start"], c["end"]) not in dispatching
        ]
        if not left_behind:
            self._repo.set_status(job_id, JobStatus.PROCESSING)
            self._cache.invalidate_job_report(job_id)
        return self._dispatch_chunks(job, chunks)

    def retryable_failed_chunks(self, job) -> list:
        """Only failed_chunks entries not marked permanent — what an
        automatic sweep is allowed to touch. Manual retry (JobRetryView)
        bypasses this filter entirely and may request anything in
        failed_chunks, on the assumption a human just fixed the underlying
        cause and knows better than the sweep's own judgment."""
        return [c for c in (job.failed_chunks or []) if c.get("retryable", True)]

    # ------------------------------------------------------------------
    # Dispatch helpers — Celery/queue concerns, not view or command
    # concerns, shared by JobRetryView and retry_stuck_jobs
    # ------------------------------------------------------------------

    @staticmethod
    def _retrigger_split_and_dispatch(job) -> None:
        """Re-run the split+dispatch pipeline for a job whose
        chunks were dropped entirely. Safe to re-run: the same source file
        always produces the same chunk files, so this can't corrupt a job
        even if the original split partially completed before whatever
        interrupted it."""
        from apps.transformation.tasks.transform import \
            split_and_dispatch_chunks

        split_and_dispatch_chunks.apply_async(
            args=[
                str(job.id),
                job.storage_path,
                job.source_path,
                job.chunk_size,
                job.template_id,
                job.format,
            ],
            queue=settings.CELERY_MERGE_QUEUE,
        )

    @staticmethod
    def _redispatch_merge(job) -> None:
        from apps.transformation.tasks.merge import merge_output

        merge_output.apply_async(
            args=[str(job.id), job.format], queue=settings.CELERY_MERGE_QUEUE
        )

    @staticmethod
    def _dispatch_chunks(job, chunks: list) -> list:
        """Re-dispatch a list of {start, end} chunk ranges. The chunk's
        input file is re-derived, not looked up — it's never
        deleted, so a retry re-reads the exact same pre-split data a first
        attempt would."""
        from apps.transformation.tasks.transform import process_chunk

        dispatched = []
        for chunk in chunks:
            process_chunk.apply_async(
                args=[
                    str(job.id),
                    chunk_input_key(str(job.id), chunk["start"], chunk["end"]),
                    chunk["start"],
                    chunk["end"],
                    job.template_id,
                    job.format,
                ],
                queue=settings.CELERY_CHUNK_QUEUE,
            )
            dispatched.append({"start": chunk["start"], "end": chunk["end"]})
            logger.info(
                f"Retrying chunk [{chunk['start']}:{chunk['end']}] for job {job.id}"
            )
        return dispatched
