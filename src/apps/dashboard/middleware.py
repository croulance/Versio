import datetime
import logging

import httpx
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.dashboard import auth_client

logger = logging.getLogger(__name__)

_EXEMPT = {"/login/", "/logout/"}
_REFRESH_THRESHOLD = datetime.timedelta(
    hours=settings.SUPPLIER_TOKEN_REFRESH_THRESHOLD_HOURS
)


class SupplierAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in _EXEMPT or request.path.startswith("/static/"):
            return self.get_response(request)

        token = request.session.get("token")
        if not token:
            return self._redirect_to_login(request)

        # The token is opaque — the dashboard has no DB, so it asks the auth
        # service to look it up and vouch for the supplier identity behind it.
        supplier = auth_client.introspect(token)
        if supplier is None:
            request.session.flush()
            return self._redirect_to_login(request)

        # Transparently refresh when less than SUPPLIER_TOKEN_REFRESH_THRESHOLD_HOURS remain
        expires_at = datetime.datetime.fromisoformat(supplier["expires_at"])
        if (
            expires_at - datetime.datetime.now(datetime.timezone.utc)
            < _REFRESH_THRESHOLD
        ):
            new_token = auth_client.refresh(token)
            if new_token:
                request.session["token"] = new_token
                token = new_token

        request.supplier = supplier
        return self.get_response(request)

    @staticmethod
    def _redirect_to_login(request) -> HttpResponse:
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=204)
            response["HX-Redirect"] = "/login/"
            return response
        return redirect("/login/")


class UpstreamErrorMiddleware:
    """Catches an httpx failure that reached Django uncaught — i.e. every
    api_client call site that has no view-specific handling of its own (the
    two 409-specific `except httpx.HTTPStatusError` blocks in
    views/templates.py run first and are never seen here; this only ever
    sees what those don't already catch). Without this, a transformation-API
    outage or an unexpected upstream error surfaces as Django's raw 500/debug
    page with no application-level log line."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, (httpx.HTTPStatusError, httpx.RequestError)):
            return None

        logger.exception(f"Upstream request failed for {request.path}")

        if request.headers.get("HX-Request"):
            response = HttpResponse(status=204)
            response["HX-Trigger"] = "upstreamError"
            return response
        return render(request, "dashboard/_upstream_error.html", status=502)
