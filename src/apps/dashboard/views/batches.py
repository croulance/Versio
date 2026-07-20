import json

from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from apps.dashboard import api_client as api


class BatchListView(View):
    def get(self, request):
        templates = api.list_templates(
            supplier_id=request.supplier["supplier_id"], status="PUBLISHED"
        )

        status_filter = request.GET.get("status") or ""
        page = max(int(request.GET.get("page", 1) or 1), 1)
        ordering = request.GET.get("ordering") or ""
        batches = api.list_batches(
            supplier_account_id=request.supplier["supplier_account_id"],
            status=status_filter or None,
            page=page,
            ordering=ordering or None,
        )

        ctx = {
            "templates": templates,
            "batches": batches.get("results", []),
            "status_filter": status_filter,
            "page": batches.get("page", 1),
            "num_pages": batches.get("num_pages", 1),
            "count": batches.get("count", 0),
            "ordering": ordering,
            "active_nav": "batches",
        }

        if request.headers.get("HX-Request"):
            return render(request, "dashboard/_batch_list.html", ctx)
        return render(request, "dashboard/batches.html", ctx)


class BatchSubmitView(View):
    def post(self, request):
        template_id = request.POST.get("template_id")
        if not template_id:
            return _error("Please select a template.")

        template = api.get_template(
            int(template_id), request.supplier["supplier_account_id"]
        )
        if (
            not template
            or template["supplier"]["id"] != request.supplier["supplier_id"]
        ):
            return HttpResponse(status=403)

        file_obj = request.FILES.get("file")
        if not file_obj:
            return _error("Please upload a file.")

        result = api.submit_batch(
            supplier_account_id=request.supplier["supplier_account_id"],
            template_id=template["id"],
            file_obj=file_obj,
        )

        if not result or "job_id" not in result:
            return _error("Submission failed — check file format and try again.")

        response = HttpResponse(status=204)
        response["HX-Redirect"] = f"/batches/{result['job_id']}/"
        return response


class BatchStatusView(View):
    def get(self, request, job_id: str):
        batch = api.get_batch(job_id, request.supplier["supplier_account_id"])
        if not batch:
            return _error(f"Batch {job_id} not found.")
        return render(request, "dashboard/_batch_status.html", {"job": batch})


class BatchDetailView(View):
    def get(self, request, job_id: str):
        batch = api.get_batch(job_id, request.supplier["supplier_account_id"])
        if not batch:
            return HttpResponse(status=404)
        return render(
            request,
            "dashboard/batch_detail.html",
            {
                "job": batch,
                "active_nav": "batches",
            },
        )


class BatchDownloadSourceView(View):
    def get(self, request, job_id: str):
        return _proxy_file(
            api.download_source(job_id, request.supplier["supplier_account_id"])
        )


class BatchDownloadResultView(View):
    def get(self, request, job_id: str):
        return _proxy_file(
            api.download_result(job_id, request.supplier["supplier_account_id"])
        )


class BatchDownloadErrorsView(View):
    def get(self, request, job_id: str):
        return _proxy_file(
            api.download_errors(job_id, request.supplier["supplier_account_id"])
        )


class BatchErrorsView(View):
    """Renders the skip-trace file as a table inline in a modal,
    for the "View" action next to the raw-file "Download" one — the file
    itself is just a JSON array, not something a supplier should have to
    open in a text editor to make sense of."""

    def get(self, request, job_id: str):
        upstream = api.download_errors(job_id, request.supplier["supplier_account_id"])
        if upstream.status_code != 200:
            return render(
                request,
                "dashboard/_batch_errors.html",
                {"errors": None},
            )
        try:
            errors = json.loads(upstream.content)
        except ValueError:
            errors = None
        return render(request, "dashboard/_batch_errors.html", {"errors": errors})


def _proxy_file(upstream) -> HttpResponse:
    if upstream.status_code != 200:
        return HttpResponse("File not available.", status=upstream.status_code)
    response = HttpResponse(
        upstream.content,
        content_type=upstream.headers.get("content-type", "application/octet-stream"),
    )
    if "content-disposition" in upstream.headers:
        response["Content-Disposition"] = upstream.headers["content-disposition"]
    return response


def _error(message: str) -> HttpResponse:
    return HttpResponse(
        f'<div id="job-status" class="text-red-500 text-sm mt-2">{message}</div>'
    )
