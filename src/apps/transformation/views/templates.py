from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.transformation.factories.service_factory import (
    TemplateLifecycleServiceFactory, TemplateServiceFactory)
from apps.transformation.serializers.outbound import TemplateSerializer
from apps.transformation.services.template_lifecycle_service import \
    LifecycleResult
from apps.transformation.services.template_service import (
    TemplateDetailResult, TemplateResult)
from apps.transformation.views.base import InternalAPIView


def _lifecycle_response(result: LifecycleResult) -> Response:
    if result.not_found:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
    if not result.ok:
        return Response({"error": result.error}, status=status.HTTP_409_CONFLICT)
    return Response(TemplateSerializer(result.template).data)


def _template_response(
    result: TemplateResult,
    not_found_status=status.HTTP_404_NOT_FOUND,
    ok_status=status.HTTP_200_OK,
) -> Response:
    if result.not_found:
        return Response({"error": result.error or "Not found"}, status=not_found_status)
    if not result.ok:
        return Response({"error": result.error}, status=status.HTTP_409_CONFLICT)
    return Response(TemplateSerializer(result.template).data, status=ok_status)


class TemplateListView(InternalAPIView):
    def get(self, request: Request) -> Response:
        supplier_id = request.query_params.get("supplier_id")
        template_status = request.query_params.get("status")
        ordering = request.query_params.get("ordering")

        templates = TemplateServiceFactory.create().list(
            supplier_id=int(supplier_id) if supplier_id else None,
            status=template_status,
            ordering=ordering,
        )
        return Response(TemplateSerializer(templates, many=True).data)

    def post(self, request: Request) -> Response:
        data = request.data
        result: TemplateResult = TemplateServiceFactory.create().create(
            supplier_account_id=data.get("supplier_account_id"),
            format=data.get("format", ""),
            version=int(data.get("version", 1)),
            name=data.get("name", ""),
            source_path=data.get("source_path", ""),
            metadata=data.get("metadata", {}),
        )
        return _template_response(
            result,
            not_found_status=status.HTTP_404_NOT_FOUND,
            ok_status=status.HTTP_201_CREATED,
        )


class TemplateDetailView(InternalAPIView):
    def get(self, request: Request, template_id: int) -> Response:
        supplier_account_id = request.query_params.get("supplier_account_id")
        result: TemplateDetailResult = TemplateServiceFactory.create().get_detail(
            template_id, supplier_account_id
        )
        if not result.ok:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        data = TemplateSerializer(result.template).data
        data["source_fields"] = result.source_fields
        data["mappings"] = result.mappings
        return Response(data)

    def patch(self, request: Request, template_id: int) -> Response:
        supplier_account_id = request.data.get("supplier_account_id")
        result = TemplateServiceFactory.create().update(
            template_id, supplier_account_id, request.data
        )
        return _template_response(result)


# ── Template lifecycle ──────────────────────────────────────────────────────


class TemplatePublishView(InternalAPIView):
    def post(self, request: Request, template_id: int) -> Response:
        return _lifecycle_response(
            TemplateLifecycleServiceFactory.create().publish(
                template_id, request.data.get("supplier_account_id")
            )
        )


class TemplateDeprecateView(InternalAPIView):
    def post(self, request: Request, template_id: int) -> Response:
        return _lifecycle_response(
            TemplateLifecycleServiceFactory.create().deprecate(
                template_id, request.data.get("supplier_account_id")
            )
        )


class TemplateRevertToDraftView(InternalAPIView):
    def post(self, request: Request, template_id: int) -> Response:
        return _lifecycle_response(
            TemplateLifecycleServiceFactory.create().revert_to_draft(
                template_id, request.data.get("supplier_account_id")
            )
        )
