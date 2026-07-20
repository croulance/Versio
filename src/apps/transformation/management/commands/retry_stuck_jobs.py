from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.transformation.factories.service_factory import \
    JobLifecycleServiceFactory
from apps.transformation.repositories.job_repository import JobRepository


class Command(BaseCommand):
    help = (
        "Find TransformationJobs stuck in PENDING (never picked up by a worker), "
        "PROCESSING (a chunk task was likely lost, or the merge never completed), "
        "or PARTIAL (a retryable failure nobody's retried) and recover them. "
        "Intended to run periodically via crontab or Celery beat."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-age-minutes",
            type=int,
            default=settings.STUCK_PENDING_JOB_MIN_AGE_MINUTES,
            help="Only retry PENDING jobs older than this many minutes.",
        )
        parser.add_argument(
            "--max-age-minutes",
            type=int,
            default=settings.STUCK_PENDING_JOB_MAX_AGE_MINUTES,
            help="Mark PENDING jobs older than this as FAILED instead of retrying.",
        )
        parser.add_argument(
            "--processing-min-age-minutes",
            type=int,
            default=settings.STUCK_PROCESSING_JOB_MIN_AGE_MINUTES,
            help="Only retry PROCESSING jobs stalled longer than this many minutes.",
        )
        parser.add_argument(
            "--processing-max-age-minutes",
            type=int,
            default=settings.STUCK_PROCESSING_JOB_MAX_AGE_MINUTES,
            help="Mark PROCESSING jobs stalled longer than this as FAILED instead of retrying.",
        )
        parser.add_argument(
            "--partial-min-age-minutes",
            type=int,
            default=settings.STUCK_PARTIAL_JOB_MIN_AGE_MINUTES,
            help="Only retry PARTIAL jobs whose oldest failure is older than this many minutes.",
        )
        parser.add_argument(
            "--partial-max-age-minutes",
            type=int,
            default=settings.STUCK_PARTIAL_JOB_MAX_AGE_MINUTES,
            help="Mark PARTIAL jobs whose oldest failure is older than this as FAILED.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List stuck jobs without retrying or marking them.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        repo = JobRepository()
        self._lifecycle = JobLifecycleServiceFactory.create()

        pending_retried, pending_failed = self._process(
            dry_run,
            label="PENDING",
            jobs=repo.list_stuck_pending(options["min_age_minutes"]),
            age_of=lambda job: job.created_at,
            max_age=options["max_age_minutes"],
            recover=self._lifecycle.resume,
        )
        processing_retried, processing_failed = self._process(
            dry_run,
            label="PROCESSING",
            jobs=repo.list_stuck_processing(options["processing_min_age_minutes"]),
            age_of=lambda job: job.started_at,
            max_age=options["processing_max_age_minutes"],
            recover=self._recover_processing,
        )
        partial_retried, partial_skipped, partial_failed = self._process_partial(
            dry_run,
            jobs=repo.list_stuck_partial(options["partial_min_age_minutes"]),
            max_age=options["partial_max_age_minutes"],
        )

        verb = "would be retried" if dry_run else "retried"
        self.stdout.write(
            self.style.SUCCESS(
                f"Done — PENDING: {pending_retried} {verb}, {pending_failed} marked FAILED. "
                f"PROCESSING: {processing_retried} {verb}, {processing_failed} marked FAILED. "
                f"PARTIAL: {partial_retried} {verb}, {partial_skipped} skipped "
                f"(no retryable chunks), {partial_failed} marked FAILED."
            )
        )

    def _recover_processing(self, job) -> None:
        if job.processed_chunks >= job.total_chunks:
            # Every chunk is done but the job never reached DONE — the merge
            # is what's stuck, not any chunk. Re-splitting would accomplish
            # nothing: every chunk would immediately hit the idempotency
            # ALREADY_DONE guard and return early without ever recomputing
            # job_complete, so it would never re-trigger merge_output.
            self._lifecycle.resume_merge(job)
        else:
            self._lifecycle.resume(job)

    def _process(
        self, dry_run, *, label, jobs, age_of, max_age, recover
    ) -> tuple[int, int]:
        if not jobs:
            self.stdout.write(f"No stuck {label} jobs found.")
            return 0, 0

        now = timezone.now()
        retried = 0
        failed = 0

        for job in jobs:
            age_minutes = (now - age_of(job)).total_seconds() / 60

            if max_age and age_minutes > max_age:
                failed += 1
                if dry_run:
                    self.stdout.write(
                        f"[dry-run] job {job.id} stuck {label} for {age_minutes:.0f}m "
                        f"(> {max_age}m) — would be marked FAILED"
                    )
                else:
                    self._lifecycle.abandon(str(job.id))
                    self.stderr.write(
                        self.style.WARNING(
                            f"Job {job.id} stuck {label} for {age_minutes:.0f}m "
                            f"(> --max-age-minutes={max_age}) — marked FAILED. Likely a "
                            "systemic outage (workers down?), needs manual investigation."
                        )
                    )
                continue

            if dry_run:
                self.stdout.write(
                    f"[dry-run] would retry job {job.id} — stuck {label} for "
                    f"{age_minutes:.0f}m, {job.processed_chunks}/{job.total_chunks} chunk(s) done"
                )
                continue

            recover(job)
            retried += 1
            self.stdout.write(
                f"Retried job {job.id}: recovery triggered "
                f"(was stuck {label} for {age_minutes:.0f}m)"
            )

        return retried, failed

    def _process_partial(self, dry_run, *, jobs, max_age) -> tuple[int, int, int]:
        if not jobs:
            self.stdout.write("No stuck PARTIAL jobs found.")
            return 0, 0, 0

        now = timezone.now()
        retried = 0
        skipped = 0
        failed = 0

        for job in jobs:
            failed_ats = [
                datetime.fromisoformat(c["failed_at"]) for c in job.failed_chunks
            ]
            age_minutes = (now - min(failed_ats)).total_seconds() / 60

            if max_age and age_minutes > max_age:
                failed += 1
                if dry_run:
                    self.stdout.write(
                        f"[dry-run] job {job.id} stuck PARTIAL for {age_minutes:.0f}m "
                        f"(> {max_age}m) — would be marked FAILED"
                    )
                else:
                    self._lifecycle.abandon(str(job.id))
                    self.stderr.write(
                        self.style.WARNING(
                            f"Job {job.id} stuck PARTIAL for {age_minutes:.0f}m "
                            f"(> --max-age-minutes={max_age}) — marked FAILED."
                        )
                    )
                continue

            retryable = self._lifecycle.retryable_failed_chunks(job)
            if not retryable:
                # Every failure here is permanent (a mapping/config bug) —
                # retrying accomplishes nothing until a human fixes the
                # underlying cause and retries manually. Skipped, not
                # touched at all: not retried, not escalated to FAILED just
                # for being old, since age doesn't make a config bug resolve
                # itself.
                skipped += 1
                self.stdout.write(
                    f"Job {job.id} stuck PARTIAL for {age_minutes:.0f}m but all "
                    f"{len(job.failed_chunks)} failure(s) are permanent — skipped, "
                    "needs a manual fix and retry"
                )
                continue

            if dry_run:
                self.stdout.write(
                    f"[dry-run] would retry job {job.id} — {len(retryable)} of "
                    f"{len(job.failed_chunks)} failed chunk(s) are retryable, "
                    f"stuck PARTIAL for {age_minutes:.0f}m"
                )
                continue

            self._lifecycle.mark_retrying(job, retryable)
            retried += 1
            self.stdout.write(
                f"Retried job {job.id}: {len(retryable)} retryable chunk(s) "
                f"re-dispatched (was stuck PARTIAL for {age_minutes:.0f}m)"
            )

        return retried, skipped, failed
