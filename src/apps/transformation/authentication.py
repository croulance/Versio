import hmac

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission


class InternalServiceAuthentication(BaseAuthentication):
    """
    Validates the shared-secret Bearer token used by trusted internal callers
    (the dashboard backend proxy). The dashboard has already authenticated the
    supplier via their own session token before making this call, so the
    caller here is identified as the service itself, not a specific supplier.
    """

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header[7:].strip()
        if not hmac.compare_digest(token, settings.INTERNAL_SERVICE_TOKEN):
            return None
        return ({"internal_service": True}, token)


class IsInternalService(BasePermission):
    """Grants access only to the trusted internal service (dashboard proxy)."""

    def has_permission(self, request, view):
        return isinstance(request.user, dict) and bool(
            request.user.get("internal_service")
        )
