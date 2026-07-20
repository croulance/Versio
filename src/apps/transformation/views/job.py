import math

from django.conf import settings
from django.http import FileResponse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.transformation.factories.cache_factory import CacheAdapterFactory
from apps.transformation.factories.storage_factory import StorageFactory
from apps.transformation.models import TransformationJob
from apps.transformation.repositories.job_repository import JobRepository
from apps.transformation.repositories.supplier_repository import \
    SupplierRepository
from apps.transformation.serializers.outbound import (JobListItemSerializer,
                                                      JobReportSerializer)
from apps.transformation.utils.chunking import final_errors_key
from apps.transformation.views.base import InternalAPIView

_TERMINAL_STATUSES = {TransformationJob.Status.DONE, TransformationJob.Status.FAILED}
_PAGE_SIZE = 10


def owns_job(job, supplier_account_id) -> bool:
    """True only if supplier_account_id resolves to the supplier that owns job.
    Used by every per-job view except JobListView (already supplier-scoped by
    query) to stop one supplier from reading/retrying another's job by guessing
    or reusing a job_id."""
    if not supplier_account_id:
        return False
    try:
        supplier = SupplierRepository().get_by_account_id(int(supplier_account_id))
    except (TypeError, ValueError):
        return False
    return bool(supplier) and job.supplier_id == supplier.id


class JobListView(InternalAPIView):
    """
    GET /api/jobs/?supplier_account_id=...&status=...&page=...

    Paginated list of a supplier's own submitted jobs ("batches"), newest first.
    supplier_account_id is required — this endpoint is always scoped to one supplier.
    """

    def get(self, request: Request) -> Response:
        supplier_account_id = request.query_params.get("supplier_account_id")
        if not supplier_account_id:
            return Response(
                {"error": "supplier_account_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        supplier = SupplierRepository().get_by_account_id(int(supplier_account_id))
        if not supplier:
            return Response(
                {"error": "Supplier not found"}, status=status.HTTP_404_NOT_FOUND
            )

        job_status = request.query_params.get("status") or None
        page = max(int(request.query_params.get("page", 1)), 1)
        ordering = request.query_params.get("ordering") or None

        jobs, total = JobRepository().list_for_supplier(
            supplier_id=supplier.id,
            status=job_status,
            page=page,
            page_size=_PAGE_SIZE,
            ordering=ordering,
        )

        results = [
            dict(
                JobListItemSerializer(
                    {
                        "job_id": job.id,
                        "status": job.status,
                        "format": job.format,
                        "template_id": job.template_id,
                        "template_version": job.template.version,
                        "total_chunks": job.total_chunks,
                        "processed_chunks": job.processed_chunks,
                        "progress_pct": int(
                            (job.processed_chunks / (job.total_chunks or 1)) * 100
                        ),
                        "processing_duration": job.processing_duration,
                        "created_at": job.created_at,
                        "has_source_file": bool(job.storage_path),
                        "has_output_file": bool(job.output_storage_path),
                        "skipped_items": job.skipped_items,
                    }
                ).data
            )
            for job in jobs
        ]

        return Response(
            {
                "results": results,
                "count": total,
                "page": page,
                "num_pages": max(math.ceil(total / _PAGE_SIZE), 1),
            }
        )


class JobView(InternalAPIView):
    """
    GET /api/jobs/{job_id}/?supplier_account_id=...

    Returns the full status report of a transformation job.
    Designed for polling — clients submit then poll until status is DONE or FAILED.

    Cache strategy:
    - Read-through: Redis checked before DB hit.
    - In-progress jobs: short TTL (JOB_REPORT_CACHE_TTL, default 5s) + explicit
      invalidation on every state mutation in tasks/retry.
    - Terminal jobs (DONE/FAILED): long TTL (JOB_REPORT_DONE_CACHE_TTL, default 1h)
      since they will never change.

    supplier_account_id is required and is checked against the cached report
    on a cache hit (it's stored in the payload precisely for this) so the
    ownership check never costs an extra DB round-trip.
    """

    def get(self, request: Request, job_id: str) -> Response:
        supplier_account_id = request.query_params.get("supplier_account_id")
        if not supplier_account_id:
            return Response(
                {"error": "supplier_account_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache = CacheAdapterFactory.create()

        cached = cache.get_job_report(job_id)
        if cached is not None:
            if str(cached.get("supplier_account_id")) != str(supplier_account_id):
                return Response(
                    {"error": f"Job {job_id} not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response(cached, status=status.HTTP_200_OK)

        job = JobRepository().get(job_id)
        if not job or not owns_job(job, supplier_account_id):
            return Response(
                {"error": f"Job {job_id} not found"}, status=status.HTTP_404_NOT_FOUND
            )

        total = job.total_chunks or 1
        progress_pct = int((job.processed_chunks / total) * 100)

        # _merge_errors() (MergeService) is deliberately best-effort
        # -- a storage failure there is logged, not raised, so it must never
        # block the real output or stop the job from reaching DONE. That
        # means output_storage_path being set does NOT guarantee
        # final.errors.json was actually written (unlike has_output_file,
        # which is safe precisely because the real-output write it reflects
        # is NOT best-effort). Only pay the extra storage round-trip in the
        # case where the derived answer would otherwise be a possibly-false
        # "yes" -- skip it entirely once there's nothing to check.
        has_errors_file = False
        if job.output_storage_path and job.skipped_items > 0:
            has_errors_file = StorageFactory.create().exists(final_errors_key(job_id))

        payload = {
            "job_id": job.id,
            "status": job.status,
            "supplier": job.supplier.name,
            "supplier_account_id": job.supplier.supplier_account_id,
            "format": job.format,
            "template_id": job.template_id,
            "template_name": job.template.name,
            "template_version": job.template.version,
            "source_path": job.source_path,
            "total_chunks": job.total_chunks,
            "chunk_size": job.chunk_size,
            "processed_chunks": job.processed_chunks,
            "progress_pct": progress_pct,
            "failed_chunks": job.failed_chunks or [],
            "skipped_items": job.skipped_items,
            "has_source_file": bool(job.storage_path),
            "has_output_file": bool(job.output_storage_path),
            "has_errors_file": has_errors_file,
            "output_storage_path": job.output_storage_path,
            "processing_duration": job.processing_duration,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "created_at": job.created_at,
        }

        serializer = JobReportSerializer(payload)
        data = dict(serializer.data)

        ttl = (
            settings.JOB_REPORT_DONE_CACHE_TTL
            if job.status in _TERMINAL_STATUSES
            else settings.JOB_REPORT_CACHE_TTL
        )
        cache.set_job_report(job_id, data, ttl)

        return Response(data, status=status.HTTP_200_OK)


_OUTPUT_CONTENT_TYPES = {
    "csv": "text/csv",
    "geojson": "application/geo+json",
    "xml": "application/xml",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class JobDownloadSourceView(InternalAPIView):
    """GET /api/jobs/{job_id}/download-source/?supplier_account_id=... — streams the originally uploaded source file."""

    def get(self, request: Request, job_id: str):
        job = JobRepository().get(job_id)
        if not job or not job.storage_path:
            return Response(
                {"error": "Source file not available."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not owns_job(job, request.query_params.get("supplier_account_id")):
            return Response(
                {"error": "Source file not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        stream = StorageFactory.create().get_object(job.storage_path)

        response = FileResponse(stream, content_type="application/json")
        response["Content-Disposition"] = (
            f'attachment; filename="source_{job_id[:8]}.json"'
        )
        return response


class JobDownloadResultView(InternalAPIView):
    """GET /api/jobs/{job_id}/download/?supplier_account_id=... — streams the transformed output file."""

    def get(self, request: Request, job_id: str):
        job = JobRepository().get(job_id)
        if not job or not job.output_storage_path:
            return Response(
                {"error": "Output file not available yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not owns_job(job, request.query_params.get("supplier_account_id")):
            return Response(
                {"error": "Output file not available yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        stream = StorageFactory.create().get_object(job.output_storage_path)

        ext = job.output_storage_path.rsplit(".", 1)[-1]
        content_type = _OUTPUT_CONTENT_TYPES.get(ext, "application/octet-stream")
        filename = f"versio_{job_id[:8]}.{ext}"

        response = FileResponse(stream, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class JobDownloadErrorsView(InternalAPIView):
    """GET /api/jobs/{job_id}/download-errors/?supplier_account_id=... —
    streams the merged skip-trace file: every item skipped
    across every chunk, with its position and the reason. No stored path —
    the key is deterministic (final_errors_key), so existence is checked
    directly against storage rather than a DB field."""

    def get(self, request: Request, job_id: str):
        job = JobRepository().get(job_id)
        if not job:
            return Response(
                {"error": "Errors file not available."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not owns_job(job, request.query_params.get("supplier_account_id")):
            return Response(
                {"error": "Errors file not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        storage = StorageFactory.create()
        key = final_errors_key(job_id)
        if not storage.exists(key):
            return Response(
                {"error": "Errors file not available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        stream = storage.get_object(key)
        response = FileResponse(stream, content_type="application/json")
        response["Content-Disposition"] = (
            f'attachment; filename="versio_{job_id[:8]}_errors.json"'
        )
        return response
