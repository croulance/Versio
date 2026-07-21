from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.transformation.interfaces.repository import JobRepositoryInterface
from apps.transformation.models import TransformationJob

_TERMINAL_STATUSES = (TransformationJob.Status.DONE, TransformationJob.Status.FAILED)


class JobRepository(JobRepositoryInterface):

    def create(
        self,
        supplier_id: int,
        template_id: int,
        format: str,
        storage_path: str,
        source_path: str,
        total_chunks: int,
        chunk_size: int,
        total_items: int = 0,
    ) -> TransformationJob:
        return TransformationJob.objects.create(
            supplier_id=supplier_id,
            template_id=template_id,
            format=format,
            storage_path=storage_path,
            source_path=source_path,
            total_chunks=total_chunks,
            chunk_size=chunk_size,
            total_items=total_items,
            status=TransformationJob.Status.PENDING,
        )

    def get(self, job_id: str) -> TransformationJob | None:
        try:
            return TransformationJob.objects.select_related("supplier", "template").get(
                id=job_id
            )
        except TransformationJob.DoesNotExist:
            return None

    def start_processing(self, job_id: str) -> None:
        """PENDING -> PROCESSING, atomically, and only from PENDING. A plain
        read-then-write here (check job.status, then call set_status) would
        race: a chunk that reads PENDING an instant before another chunk's
        failure sets PARTIAL could still overwrite that PARTIAL back to
        PROCESSING moments later. The WHERE clause makes this a no-op for
        any job that isn't currently PENDING -- including PARTIAL, which
        must only ever leave PARTIAL via clear_failed_chunk() finding the
        failed_chunks list empty, never via an unrelated chunk merely
        starting."""
        TransformationJob.objects.filter(
            id=job_id, status=TransformationJob.Status.PENDING
        ).update(status=TransformationJob.Status.PROCESSING, started_at=timezone.now())

    def set_status(self, job_id: str, status: str) -> None:
        update = {"status": status}
        if status == TransformationJob.Status.PROCESSING:
            # Only set started_at the first time (don't overwrite if already set)
            TransformationJob.objects.filter(id=job_id, started_at__isnull=True).update(
                status=status, started_at=timezone.now()
            )
            TransformationJob.objects.filter(
                id=job_id, started_at__isnull=False
            ).update(status=status)
        else:
            TransformationJob.objects.filter(id=job_id).update(**update)

    def increment_processed_chunks(self, job_id: str) -> bool:
        """Atomically increment, only if still below total_chunks and the job
        isn't DONE/FAILED. The status exclusion matters as much as the count
        one: without it, a late chunk task for an abandoned (FAILED) job
        could silently nudge processed_chunks upward while status stays
        frozen at FAILED -- a counter quietly out of sync with the status
        next to it, which is exactly the class of bug this guard closes
        everywhere else. Returns True if incremented."""
        updated = (
            TransformationJob.objects.filter(
                id=job_id,
                processed_chunks__lt=F("total_chunks"),
            )
            .exclude(status__in=_TERMINAL_STATUSES)
            .update(processed_chunks=F("processed_chunks") + 1)
        )
        return bool(updated)

    def increment_skipped_items(self, job_id: str, count: int) -> None:
        """Atomically add `count` to skipped_items -- same
        terminal-state exclusion as increment_processed_chunks, for the same
        reason. No-op for count <= 0 so callers don't need to check first."""
        if count <= 0:
            return
        TransformationJob.objects.filter(id=job_id).exclude(
            status__in=_TERMINAL_STATUSES
        ).update(skipped_items=F("skipped_items") + count)

    def mark_done(self, job_id: str, output_storage_path: str = "") -> None:
        TransformationJob.objects.filter(id=job_id).update(
            status=TransformationJob.Status.DONE,
            output_storage_path=output_storage_path,
            completed_at=timezone.now(),
        )

    def append_failed_chunk(self, job_id: str, chunk: dict) -> None:
        # select_for_update: this is a read-modify-write on a JSON list, not an
        # atomic DB-level append -- without the row lock, two chunks failing
        # (or one failing while another's clear_failed_chunk runs) concurrently
        # can race and one appender's entry silently overwrites the other's.
        with transaction.atomic():
            job = TransformationJob.objects.select_for_update().get(id=job_id)
            if job.status in _TERMINAL_STATUSES:
                # A task still in flight when the job was marked DONE/FAILED
                # arrives late and fails -- must not regress an already
                # resolved (DONE) or already abandoned (FAILED) job back to
                # PARTIAL. Only an explicit manual retry moves a job out of
                # either state.
                return
            # Replace any existing entry for this exact range instead of
            # appending a new one -- a chunk that keeps failing the same way
            # (e.g. a permanently missing source file misclassified as
            # retryable) would otherwise grow one entry per attempt forever,
            # and the automatic PARTIAL sweep dispatches one retry
            # task per failed_chunks entry -- an unbounded list means an
            # unbounded retry-storm every time the sweep runs.
            failed = [
                c
                for c in (job.failed_chunks or [])
                if not (c["start"] == chunk["start"] and c["end"] == chunk["end"])
            ]
            failed.append(chunk)
            TransformationJob.objects.filter(id=job_id).update(
                failed_chunks=failed,
                status=TransformationJob.Status.PARTIAL,
            )

    def clear_failed_chunk(self, job_id: str, start: int, end: int) -> None:
        """Remove a now-stale failed_chunks entry once that exact chunk range
        succeeds on retry -- otherwise a transient failure that Celery quietly
        retried leaves a permanent error in the job record even after the job
        completes successfully. Reverts PARTIAL back to PROCESSING once no
        failures remain; no-op if this range never failed."""
        with transaction.atomic():
            job = TransformationJob.objects.select_for_update().get(id=job_id)
            if job.status in _TERMINAL_STATUSES:
                # Same reasoning as append_failed_chunk's guard above -- a
                # late success must not silently move a DONE/FAILED job.
                return
            failed = job.failed_chunks or []
            remaining = [
                c for c in failed if not (c["start"] == start and c["end"] == end)
            ]
            if len(remaining) == len(failed):
                return
            update = {"failed_chunks": remaining}
            if not remaining and job.status == TransformationJob.Status.PARTIAL:
                update["status"] = TransformationJob.Status.PROCESSING
            TransformationJob.objects.filter(id=job_id).update(**update)

    def is_complete(self, job_id: str) -> bool:
        job = TransformationJob.objects.get(id=job_id)
        return job.processed_chunks >= job.total_chunks

    def reset(self, job_id: str) -> None:
        TransformationJob.objects.filter(id=job_id).update(
            processed_chunks=0,
            failed_chunks=[],
            status=TransformationJob.Status.PENDING,
            started_at=None,
            completed_at=None,
            output_storage_path="",
        )

    ORDERABLE_FIELDS = {"created_at", "status", "format", "template_version"}
    # Public ordering query params stay stable even though template_version
    # is no longer a real field — translate to the FK's version at query time.
    ORDERING_FIELD_MAP = {"template_version": "template__version"}

    def list_for_supplier(
        self,
        supplier_id: int,
        status: str | None,
        page: int,
        page_size: int,
        ordering: str | None = None,
    ) -> tuple:
        qs = TransformationJob.objects.filter(supplier_id=supplier_id).select_related(
            "template"
        )
        if status:
            qs = qs.filter(status=status)

        field = (ordering or "").lstrip("-")
        if field in self.ORDERABLE_FIELDS:
            desc = ordering.startswith("-")
            internal_field = self.ORDERING_FIELD_MAP.get(field, field)
            qs = qs.order_by(
                f"-{internal_field}" if desc else internal_field, "-created_at"
            )
        else:
            qs = qs.order_by("-created_at")

        total = qs.count()
        offset = (page - 1) * page_size
        return list(qs[offset : offset + page_size]), total

    def list_stuck_pending(self, older_than_minutes: int) -> list:
        cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
        return list(
            TransformationJob.objects.filter(
                status=TransformationJob.Status.PENDING,
                created_at__lt=cutoff,
            ).order_by("created_at")
        )

    def list_stuck_processing(self, older_than_minutes: int) -> list:
        # started_at, not created_at -- a job can legitimately sit briefly
        # between creation and its first chunk starting; what matters here is
        # how long it's been actively processing without finishing.
        #
        # Deliberately NOT filtered on processed_chunks < total_chunks: a job
        # that reached 100% but never became DONE (merge_output returned a
        # non-OK result and gave up, or was lost) is just as stuck, and needs
        # a different recovery action (redispatch merge_output, not
        # re-split-and-dispatch every chunk) -- the caller branches on
        # job.processed_chunks vs job.total_chunks to pick it.
        cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
        return list(
            TransformationJob.objects.filter(
                status=TransformationJob.Status.PROCESSING,
                started_at__lt=cutoff,
            ).order_by("started_at")
        )

    def list_stuck_partial(self, older_than_minutes: int) -> list:
        """PARTIAL jobs whose oldest failed_chunks entry is older than
        older_than_minutes. failed_at lives inside the JSON list, not a
        column, so this filters in Python after a single query rather than
        trying to push a JSON-array min() into the DB query."""
        cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
        stuck = []
        for job in TransformationJob.objects.filter(
            status=TransformationJob.Status.PARTIAL
        ).order_by("created_at"):
            failed = job.failed_chunks or []
            if not failed:
                continue
            oldest = min(datetime.fromisoformat(c["failed_at"]) for c in failed)
            if oldest < cutoff:
                stuck.append(job)
        return stuck

    def mark_failed(self, job_id: str) -> None:
        TransformationJob.objects.filter(id=job_id).exclude(
            status=TransformationJob.Status.DONE
        ).update(status=TransformationJob.Status.FAILED)
