from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.transformation.factories.service_factory import \
    JobLifecycleServiceFactory
from apps.transformation.models import TransformationJob
from apps.transformation.repositories.job_repository import JobRepository
from apps.transformation.services.job_lifecycle_service import ResumeAction
from apps.transformation.views.base import InternalAPIView
from apps.transformation.views.job import owns_job


class JobRetryView(InternalAPIView):
    """
    POST /api/jobs/{job_id}/retry/

    Body: {"supplier_account_id": ..., "chunks": [{start, end}, ...]}

    All the decision logic (which transition applies, reset vs. resume,
    what to dispatch) lives in JobLifecycleService — this view
    only resolves the job, picks the branch, and formats the response.

    Four cases, in order:
    - "chunks" present  → retry those specific failed chunks only
    - "chunks" absent + failed_chunks exist → retry all failed_chunks
    - neither + job incomplete (processed_chunks < total_chunks) → resume
      (reset only if nothing would be lost) and re-trigger split+dispatch
    - neither + fully processed but not DONE → the merge itself never
      completed; re-dispatch it directly, not the whole split+chunk pipeline

    A PROCESSING job is normally rejected with 409 (something else is
    already working it) unless it's been PROCESSING long enough to be
    considered stalled (JobLifecycleService.can_retry).
    """

    def post(self, request: Request, job_id: str) -> Response:
        repo = JobRepository()
        lifecycle = JobLifecycleServiceFactory.create()
        job = repo.get(job_id)

        if not job or not owns_job(job, request.data.get("supplier_account_id")):
            return Response(
                {"error": f"Job {job_id} not found"}, status=status.HTTP_404_NOT_FOUND
            )

        if not lifecycle.can_retry(job):
            return Response(
                {"error": "Job is currently processing"},
                status=status.HTTP_409_CONFLICT,
            )

        failed_chunks = job.failed_chunks or []
        requested = request.data.get("chunks")

        if requested:
            chunks_to_retry = [
                c
                for c in failed_chunks
                if {"start": c["start"], "end": c["end"]} in requested
            ]
            if not chunks_to_retry:
                return Response(
                    {"error": "No matching chunks found"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            dispatched = lifecycle.mark_retrying(job, chunks_to_retry)

        elif failed_chunks:
            dispatched = lifecycle.mark_retrying(job, failed_chunks)

        elif job.processed_chunks < job.total_chunks:
            action = lifecycle.resume(job)
            return Response(
                {
                    "job_id": job_id,
                    "detail": (
                        "Job reset — split and chunk dispatch re-triggered"
                        if action == ResumeAction.RESET
                        else "Split and chunk dispatch re-triggered — existing progress preserved"
                    ),
                },
                status=status.HTTP_202_ACCEPTED,
            )

        elif job.status != TransformationJob.Status.DONE:
            # processed_chunks == total_chunks but never reached DONE — the
            # merge itself is what's stuck, not any chunk. Re-splitting
            # would accomplish nothing here: every chunk would immediately
            # hit the idempotency ALREADY_DONE guard and return early without
            # ever recomputing job_complete, so it would never re-trigger
            # merge_output.
            lifecycle.resume_merge(job)
            return Response(
                {
                    "job_id": job_id,
                    "detail": "All chunks already processed — merge re-dispatched",
                },
                status=status.HTTP_202_ACCEPTED,
            )

        else:
            return Response(
                {"error": "Nothing to retry — job is complete"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "job_id": job_id,
                "retried_chunks": dispatched,
                "detail": f"{len(dispatched)} chunk(s) re-dispatched",
            },
            status=status.HTTP_202_ACCEPTED,
        )
