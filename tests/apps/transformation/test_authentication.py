import pytest
from django.conf import settings

from apps.transformation.authentication import (InternalServiceAuthentication,
                                                 IsInternalService)


class FakeRequest:
    def __init__(self, headers=None, user=None):
        self.headers = headers or {}
        self.user = user


@pytest.fixture(autouse=True)
def internal_service_token(monkeypatch):
    # Tests must not depend on whatever INTERNAL_SERVICE_TOKEN happens to be
    # configured in the running environment.
    monkeypatch.setattr(settings, "INTERNAL_SERVICE_TOKEN", "test-secret-token")


class TestInternalServiceAuthentication:
    def test_valid_bearer_token_authenticates_as_internal_service(self):
        request = FakeRequest(headers={"Authorization": "Bearer test-secret-token"})

        result = InternalServiceAuthentication().authenticate(request)

        assert result == ({"internal_service": True}, "test-secret-token")

    def test_wrong_token_is_rejected(self):
        request = FakeRequest(headers={"Authorization": "Bearer wrong-token"})
        assert InternalServiceAuthentication().authenticate(request) is None

    def test_missing_authorization_header_is_rejected(self):
        request = FakeRequest(headers={})
        assert InternalServiceAuthentication().authenticate(request) is None

    def test_non_bearer_scheme_is_rejected(self):
        request = FakeRequest(headers={"Authorization": "Basic dGVzdA=="})
        assert InternalServiceAuthentication().authenticate(request) is None

    def test_empty_bearer_token_is_rejected(self):
        request = FakeRequest(headers={"Authorization": "Bearer "})
        assert InternalServiceAuthentication().authenticate(request) is None

    def test_token_with_incidental_whitespace_is_still_accepted(self):
        request = FakeRequest(headers={"Authorization": "Bearer  test-secret-token "})
        # header[7:].strip() strips the extra space either side of the token
        result = InternalServiceAuthentication().authenticate(request)
        assert result == ({"internal_service": True}, "test-secret-token")


class TestIsInternalService:
    def test_grants_access_when_user_is_the_internal_service_marker(self):
        request = FakeRequest(user={"internal_service": True})
        assert IsInternalService().has_permission(request, view=None) is True

    def test_denies_access_when_flag_is_false(self):
        request = FakeRequest(user={"internal_service": False})
        assert IsInternalService().has_permission(request, view=None) is False

    def test_denies_access_when_user_is_not_a_dict(self):
        request = FakeRequest(user=object())
        assert IsInternalService().has_permission(request, view=None) is False

    def test_denies_access_when_user_is_none(self):
        request = FakeRequest(user=None)
        assert IsInternalService().has_permission(request, view=None) is False
