from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.transformation.dtos.result import TransformStatus
from apps.transformation.factories.service_factory import \
    TransformationServiceFactory
from apps.transformation.serializers.inbound import TransformRequestSerializer
from apps.transformation.views.base import InternalAPIView


class TransformView(InternalAPIView):
    """
    POST /api/transform/

    Called only by the dashboard backend, authenticated with the internal
    service token. The dashboard has already verified the supplier via their
    own session token, so the body's supplier_account_id is trusted here.
    """

    def post(self, request: Request) -> Response:
        serializer = TransformRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        supplier_account_id = data["supplier_account_id"]
        uploaded_file = data["file"]

        service = TransformationServiceFactory.create()
        result = service.submit(
            supplier_account_id=supplier_account_id,
            template_id=data["template_id"],
            filename=uploaded_file.name,
            file_stream=uploaded_file,
        )

        if result.status == TransformStatus.INVALID:
            return Response(
                {"error": result.message}, status=status.HTTP_400_BAD_REQUEST
            )

        if result.status == TransformStatus.NOT_FOUND:
            return Response({"error": result.message}, status=status.HTTP_404_NOT_FOUND)

        if result.status == TransformStatus.DUPLICATE:
            return Response(
                {"job_id": result.job_id, "detail": result.message},
                status=status.HTTP_200_OK,
            )

        return Response({"job_id": result.job_id}, status=status.HTTP_202_ACCEPTED)
