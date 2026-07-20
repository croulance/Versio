import logging
from enum import Enum

from apps.transformation.enums import JobStatus
from apps.transformation.interfaces.merger import MergerInterface
from apps.transformation.interfaces.repository import (
    JobRepositoryInterface, TemplateRepositoryInterface)
from apps.transformation.interfaces.storage import StorageInterface
from apps.transformation.services.job_lifecycle_service import \
    JobLifecycleService
from apps.transformation.utils.chunking import final_errors_key

logger = logging.getLogger(__name__)


class MergeResultStatus(Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    NO_CHUNKS = "no_chunks"
    UNSUPPORTED_FORMAT = "unsupported_format"
    ALREADY_DONE = "already_done"


class MergeService:
    """Merges a job's per-chunk output files in storage into the final output file."""

    def __init__(
        self,
        template_repository: TemplateRepositoryInterface,
        job_repository: JobRepositoryInterface,
        mergers: dict[str, MergerInterface],
        storage: StorageInterface,
        lifecycle: JobLifecycleService,
    ):
        self._template_repo = template_repository
        self._job_repo = job_repository
        self._mergers = mergers
        self._storage = storage
        self._lifecycle = lifecycle

    def merge(self, job_id: str, format: str) -> MergeResultStatus:
        job = self._job_repo.get(job_id)
        if not job:
            logger.error(f"merge_output: job {job_id} not found")
            return MergeResultStatus.NOT_FOUND

        if job.status == JobStatus.DONE:
            # task_acks_late makes merge_output redeliverable — a worker can
            # finish a merge and die before the broker sees the ack. Without
            # this, a redelivery would re-list, re-merge, and re-write the
            # exact same output for no reason.
            logger.info(f"merge_output: job {job_id} already DONE — skipping re-merge")
            return MergeResultStatus.ALREADY_DONE

        template = self._template_repo.get_with_mappings_by_id(job.template_id)
        metadata = template.metadata if template else {}

        keys = self._list_chunk_keys(job_id, f".{format}")
        if not keys:
            logger.error(f"merge_output: no chunk files found for job {job_id}")
            return MergeResultStatus.NO_CHUNKS

        merger = self._mergers.get(format)
        if not merger:
            logger.error(f"merge_output: no merger for format {format}")
            return MergeResultStatus.UNSUPPORTED_FORMAT

        content = merger.merge(keys, metadata)

        final_key = f"outputs/{job_id}/final.{format}"
        self._storage.put_object(final_key, content)
        logger.info(f"Merged output written to {final_key} ({len(content)} bytes)")

        self._merge_errors(job_id)

        self._lifecycle.completed(job_id, final_key)
        logger.info(f"Job {job_id} marked DONE")
        return MergeResultStatus.OK

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _merge_errors(self, job_id: str) -> None:
        """Best-effort: merges per-chunk skip-trace files into
        final.errors.json via the same MergerInterface/registry machinery as
        real output, reusing _list_chunk_keys(".errors.json") for discovery.
        Runs before _lifecycle.completed() so has_errors_file (JobView) never
        reads True ahead of the file actually existing. A failure here is
        logged, not raised — losing the error trace must never take down an
        otherwise-successful merge/job completion."""
        try:
            error_keys = self._list_chunk_keys(job_id, ".errors.json")
            if not error_keys:
                return
            errors_merger = self._mergers.get("errors")
            if not errors_merger:
                logger.error("merge_output: no merger registered for errors")
                return
            content = errors_merger.merge(error_keys, {})
            errors_key = final_errors_key(job_id)
            self._storage.put_object(errors_key, content)
            logger.info(f"Merged errors written to {errors_key} ({len(content)} bytes)")
        except Exception:
            logger.exception(
                f"merge_output: failed to merge error files for job {job_id}"
            )

    def _list_chunk_keys(self, job_id: str, suffix: str) -> list[str]:
        prefix = f"outputs/{job_id}/"
        keys = [
            key
            for key in self._storage.list_keys(prefix)
            if key.endswith(suffix) and "final" not in key
        ]

        def _start(key):
            try:
                return int(key.rsplit("_", 2)[-2])
            except (ValueError, IndexError):
                return 0

        return sorted(keys, key=_start)
