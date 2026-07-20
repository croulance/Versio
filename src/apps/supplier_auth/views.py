from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.supplier_auth.cache.cache_adapter import AuthCacheAdapter
from apps.supplier_auth.repositories.auth_repository import AuthRepository
from apps.supplier_auth.serializers.inbound import (BearerTokenSerializer,
                                                    LoginSerializer)
from apps.supplier_auth.services.auth_service import AuthService
from infrastructure.cache.redis_client import RedisClient


def _make_service() -> AuthService:
    return AuthService(
        repository=AuthRepository(), cache=AuthCacheAdapter(RedisClient())
    )


class LoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        token = _make_service().login(
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        if token is None:
            return Response(
                {"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED
            )

        return Response({"token": token}, status=status.HTTP_200_OK)


class RefreshView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request: Request) -> Response:
        serializer = BearerTokenSerializer(data=request.META)
        if not serializer.is_valid():
            return Response(
                {"error": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED
            )

        token = _make_service().refresh(serializer.validated_data["authorization"])
        if token is None:
            return Response(
                {"error": "Invalid or expired token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response({"token": token}, status=status.HTTP_200_OK)


class MeView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request: Request) -> Response:
        serializer = BearerTokenSerializer(data=request.META)
        if not serializer.is_valid():
            return Response(
                {"error": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED
            )

        payload = _make_service().introspect(serializer.validated_data["authorization"])
        if payload is None:
            return Response(
                {"error": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED
            )

        return Response(
            {
                "supplier_id": payload["supplier_id"],
                "supplier_account_id": payload["supplier_account_id"],
                "email": payload["email"],
                "groups": payload.get("groups", []),
                "permissions": payload.get("permissions", []),
                "expires_at": payload["expires_at"],
            }
        )
