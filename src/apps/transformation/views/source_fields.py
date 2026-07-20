from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.transformation.factories.service_factory import \
    SourceFieldServiceFactory
from apps.transformation.serializers.outbound import SourceFieldSerializer
from apps.transformation.services.source_field_service import SourceFieldResult
from apps.transformation.views.base import InternalAPIView


def _field_response(result: SourceFieldResult) -> Response:
    if result.not_found:
        return Response(
            {"error": result.error or "Not found"}, status=status.HTTP_404_NOT_FOUND
        )
    if not result.ok:
        return Response({"error": result.error}, status=status.HTTP_409_CONFLICT)
    return Response(SourceFieldSerializer(result.field_item).data)


class SourceFieldListView(InternalAPIView):
    def get(self, request: Request, template_id: int) -> Response:
        supplier_account_id = request.query_params.get("supplier_account_id")
        result = SourceFieldServiceFactory.create().list(
            template_id, supplier_account_id
        )
        if not result.ok:
            return Response(
                {"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(SourceFieldSerializer(result.fields, many=True).data)

    def post(self, request: Request, template_id: int) -> Response:
        supplier_account_id = request.data.get("supplier_account_id")
        result = SourceFieldServiceFactory.create().create(
            template_id, supplier_account_id, request.data
        )
        if result.not_found:
            return Response(
                {"error": result.error or "Not found"}, status=status.HTTP_404_NOT_FOUND
            )
        if not result.ok:
            return Response({"error": result.error}, status=status.HTTP_409_CONFLICT)
        return Response(
            SourceFieldSerializer(result.field_item).data,
            status=status.HTTP_201_CREATED,
        )


class SourceFieldDetailView(InternalAPIView):
    def patch(self, request: Request, template_id: int, field_id: int) -> Response:
        supplier_account_id = request.data.get("supplier_account_id")
        result = SourceFieldServiceFactory.create().update(
            template_id, field_id, supplier_account_id, request.data
        )
        return _field_response(result)

    def delete(self, request: Request, template_id: int, field_id: int) -> Response:
        supplier_account_id = request.data.get("supplier_account_id")
        result = SourceFieldServiceFactory.create().delete(
            template_id, field_id, supplier_account_id
        )
        if result.not_found:
            return Response(
                {"error": result.error or "Not found"}, status=status.HTTP_404_NOT_FOUND
            )
        if not result.ok:
            return Response({"error": result.error}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)
