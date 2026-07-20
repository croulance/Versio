from rest_framework.views import APIView

from apps.transformation.authentication import (InternalServiceAuthentication,
                                                IsInternalService)


class InternalAPIView(APIView):
    """
    Base for every transformation-API view. Only the trusted internal caller
    (the dashboard backend proxy) may reach these endpoints; it authenticates
    with a shared-secret Bearer token, never the supplier's own session token.
    """

    authentication_classes = [InternalServiceAuthentication]
    permission_classes = [IsInternalService]
