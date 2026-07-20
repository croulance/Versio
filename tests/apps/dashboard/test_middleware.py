import httpx
from django.conf import settings
from django.test import RequestFactory

# apps.dashboard.middleware reads SUPPLIER_TOKEN_REFRESH_THRESHOLD_HOURS at
# import time (module-level constant on SupplierAuthMiddleware) but the test
# suite runs under versio.settings.dev, where only the transformation
# service's settings are loaded — same situation as
# test_auth_service.py's auth_settings fixture, just needed before import
# rather than per test.
if not hasattr(settings, "SUPPLIER_TOKEN_REFRESH_THRESHOLD_HOURS"):
    settings.SUPPLIER_TOKEN_REFRESH_THRESHOLD_HOURS = 24

from apps.dashboard.middleware import UpstreamErrorMiddleware  # noqa: E402

rf = RequestFactory()


def _middleware():
    return UpstreamErrorMiddleware(get_response=lambda request: None)


class TestProcessException:
    def test_ignores_exceptions_that_are_not_httpx_errors(self):
        mw = _middleware()
        request = rf.get("/templates/")

        assert mw.process_exception(request, ValueError("unrelated")) is None

    def test_http_status_error_on_a_full_page_request_renders_a_502_page(self):
        mw = _middleware()
        request = rf.get("/templates/")

        response = mw.process_exception(
            request, httpx.HTTPStatusError("boom", request=None, response=None)
        )

        assert response.status_code == 502

    def test_request_error_on_a_full_page_request_renders_a_502_page(self):
        mw = _middleware()
        request = rf.get("/templates/")

        response = mw.process_exception(request, httpx.RequestError("boom"))

        assert response.status_code == 502

    def test_request_error_on_an_htmx_request_returns_204_with_toast_trigger(self):
        mw = _middleware()
        request = rf.get("/templates/", HTTP_HX_REQUEST="true")

        response = mw.process_exception(request, httpx.RequestError("boom"))

        assert response.status_code == 204
        assert response["HX-Trigger"] == "upstreamError"

    def test_upstream_failure_is_logged(self, caplog):
        mw = _middleware()
        request = rf.get("/templates/")

        with caplog.at_level("ERROR"):
            mw.process_exception(request, httpx.RequestError("boom"))

        assert "Upstream request failed for /templates/" in caplog.text

    def test_unrelated_exception_is_not_logged(self, caplog):
        mw = _middleware()
        request = rf.get("/templates/")

        with caplog.at_level("ERROR"):
            mw.process_exception(request, ValueError("unrelated"))

        assert caplog.text == ""
