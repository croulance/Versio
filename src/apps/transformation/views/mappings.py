from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.transformation.factories.service_factory import MappingServiceFactory
from apps.transformation.serializers.outbound import MappingSerializer
from apps.transformation.services.mapping_service import MappingResult
from apps.transformation.views.base import InternalAPIView


def _mapping_response(result: MappingResult) -> Response:
    if result.not_found:
        return Response(
            {"error": result.error or "Not found"}, status=status.HTTP_404_NOT_FOUND
        )
    if not result.ok:
        return Response({"error": result.error}, status=status.HTTP_409_CONFLICT)
    return Response(MappingSerializer(result.mapping).data)


class MappingListView(InternalAPIView):
    def get(self, request: Request, template_id: int) -> Response:
        supplier_account_id = request.query_params.get("supplier_account_id")
        result = MappingServiceFactory.create().list(template_id, supplier_account_id)
        if not result.ok:
            return Response(
                {"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(MappingSerializer(result.mappings, many=True).data)

    def post(self, request: Request, template_id: int) -> Response:
        supplier_account_id = request.data.get("supplier_account_id")
        result = MappingServiceFactory.create().create(
            template_id, supplier_account_id, request.data
        )
        if result.not_found:
            return Response(
                {"error": result.error or "Not found"}, status=status.HTTP_404_NOT_FOUND
            )
        if not result.ok:
            return Response({"error": result.error}, status=status.HTTP_409_CONFLICT)
        return Response(
            MappingSerializer(result.mapping).data, status=status.HTTP_201_CREATED
        )


class MappingDetailView(InternalAPIView):
    def patch(self, request: Request, template_id: int, mapping_id: int) -> Response:
        supplier_account_id = request.data.get("supplier_account_id")
        result = MappingServiceFactory.create().update(
            template_id, mapping_id, supplier_account_id, request.data
        )
        return _mapping_response(result)

    def delete(self, request: Request, template_id: int, mapping_id: int) -> Response:
        supplier_account_id = request.data.get("supplier_account_id")
        result = MappingServiceFactory.create().delete(
            template_id, mapping_id, supplier_account_id
        )
        if result.not_found:
            return Response(
                {"error": result.error or "Not found"}, status=status.HTTP_404_NOT_FOUND
            )
        if not result.ok:
            return Response({"error": result.error}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class HandlerListView(InternalAPIView):
    def get(self, request: Request) -> Response:
        import apps.transformation.handlers  # noqa: F401 — triggers decorator registration
        from apps.transformation.handlers.registry import list_handlers

        return Response(list_handlers())
