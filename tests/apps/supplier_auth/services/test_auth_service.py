import datetime

import pytest
from django.conf import settings

from apps.supplier_auth.dtos.auth import IssuedToken, SupplierIdentity
from apps.supplier_auth.services.auth_service import AuthService


@pytest.fixture(autouse=True)
def auth_settings(monkeypatch):
    # SUPPLIER_TOKEN_TTL_DAYS / AUTH_INTROSPECTION_CACHE_TTL are only defined
    # under versio.settings.auth, but the test suite runs under
    # versio.settings.dev — set them explicitly so AuthService has something
    # to read, same as it would in the real auth container.
    monkeypatch.setattr(settings, "SUPPLIER_TOKEN_TTL_DAYS", 15, raising=False)
    monkeypatch.setattr(settings, "AUTH_INTROSPECTION_CACHE_TTL", 10, raising=False)


class FakeAuthRepository:
    def __init__(
        self, login_returns=None, refresh_returns=None, introspect_returns=None
    ):
        self._login_returns = login_returns
        self._refresh_returns = refresh_returns
        self._introspect_returns = introspect_returns
        self.login_calls = []
        self.refresh_calls = []
        self.introspect_calls = []

    def login(self, email, password, ttl):
        self.login_calls.append((email, password, ttl))
        return self._login_returns

    def refresh(self, token, ttl):
        self.refresh_calls.append((token, ttl))
        return self._refresh_returns

    def introspect(self, token):
        self.introspect_calls.append(token)
        return self._introspect_returns


class FakeAuthCache:
    def __init__(self, seed: dict | None = None):
        self._store = dict(seed or {})
        self.set_calls = []
        self.invalidate_calls = []

    def get_introspection(self, token_key):
        return self._store.get(token_key)

    def set_introspection(self, token_key, data, ttl):
        self.set_calls.append((token_key, ttl))
        self._store[token_key] = data

    def invalidate_introspection(self, token_key):
        self.invalidate_calls.append(token_key)
        self._store.pop(token_key, None)


class TestLogin:
    def test_valid_credentials_return_the_issued_token_key(self):
        repo = FakeAuthRepository(
            login_returns=IssuedToken(
                key="abc123", expires_at=datetime.datetime(2026, 8, 1)
            )
        )
        service = AuthService(repo, FakeAuthCache())

        result = service.login("supplier@example.com", "correct-password")

        assert result == "abc123"

    def test_invalid_credentials_return_none(self):
        repo = FakeAuthRepository(login_returns=None)
        service = AuthService(repo, FakeAuthCache())

        result = service.login("supplier@example.com", "wrong-password")

        assert result is None

    def test_invalid_credentials_log_a_warning(self, caplog):
        repo = FakeAuthRepository(login_returns=None)
        service = AuthService(repo, FakeAuthCache())

        with caplog.at_level("WARNING"):
            service.login("supplier@example.com", "wrong-password")

        assert "Failed login attempt for supplier@example.com" in caplog.text

    def test_valid_credentials_do_not_log_a_warning(self, caplog):
        repo = FakeAuthRepository(
            login_returns=IssuedToken(
                key="abc123", expires_at=datetime.datetime(2026, 8, 1)
            )
        )
        service = AuthService(repo, FakeAuthCache())

        with caplog.at_level("WARNING"):
            service.login("supplier@example.com", "correct-password")

        assert caplog.text == ""

    def test_ttl_passed_to_repository_matches_configured_days(self):
        repo = FakeAuthRepository(login_returns=None)
        service = AuthService(repo, FakeAuthCache())

        service.login("a@b.com", "pw")

        [(_, _, ttl)] = repo.login_calls
        assert ttl == datetime.timedelta(days=15)


class TestRefresh:
    def test_valid_token_returns_new_key(self):
        repo = FakeAuthRepository(
            refresh_returns=IssuedToken(
                key="new-token", expires_at=datetime.datetime(2026, 8, 1)
            )
        )
        service = AuthService(repo, FakeAuthCache())

        assert service.refresh("old-token") == "new-token"
        assert repo.refresh_calls[0][0] == "old-token"

    def test_expired_or_unknown_token_returns_none(self):
        repo = FakeAuthRepository(refresh_returns=None)
        service = AuthService(repo, FakeAuthCache())

        assert service.refresh("stale-token") is None

    def test_rotation_invalidates_the_old_tokens_cache_entry(self):
        # Regression test: a cache-aside layer over introspect() must never let
        # a rotated-out token keep authenticating past its DB deletion, even
        # for the cache's TTL window — refresh() invalidates unconditionally.
        repo = FakeAuthRepository(
            refresh_returns=IssuedToken(
                key="new-token", expires_at=datetime.datetime(2026, 8, 1)
            )
        )
        cache = FakeAuthCache(seed={"old-token": {"supplier_id": 1}})
        service = AuthService(repo, cache)

        service.refresh("old-token")

        assert cache.invalidate_calls == ["old-token"]
        assert cache.get_introspection("old-token") is None

    def test_invalidates_even_when_the_token_being_refreshed_is_invalid(self):
        # Deleting a cache key that isn't set (or is already gone) is a
        # harmless no-op — invalidation happens unconditionally, before the
        # repository call, to keep the logic simple rather than conditional
        # on whether the refresh itself succeeded.
        repo = FakeAuthRepository(refresh_returns=None)
        cache = FakeAuthCache()
        service = AuthService(repo, cache)

        service.refresh("never-cached-token")

        assert cache.invalidate_calls == ["never-cached-token"]


class TestIntrospect:
    def test_valid_token_returns_identity_dict_with_iso_expiry(self):
        identity = SupplierIdentity(
            supplier_id=1,
            supplier_account_id=199,
            email="supplier@example.com",
            groups=["editors"],
            permissions=["publish_template"],
            expires_at=datetime.datetime(2026, 8, 1, 12, 0, 0),
        )
        repo = FakeAuthRepository(introspect_returns=identity)
        service = AuthService(repo, FakeAuthCache())

        result = service.introspect("valid-token")

        assert result == {
            "supplier_id": 1,
            "supplier_account_id": 199,
            "email": "supplier@example.com",
            "groups": ["editors"],
            "permissions": ["publish_template"],
            "expires_at": "2026-08-01T12:00:00",
        }

    def test_invalid_or_expired_token_returns_none(self):
        repo = FakeAuthRepository(introspect_returns=None)
        service = AuthService(repo, FakeAuthCache())

        assert service.introspect("bad-token") is None

    def test_cache_hit_never_calls_the_repository(self):
        repo = FakeAuthRepository(introspect_returns=None)  # would return None if hit
        cache = FakeAuthCache(seed={"cached-token": {"supplier_id": 42}})
        service = AuthService(repo, cache)

        result = service.introspect("cached-token")

        assert result == {"supplier_id": 42}
        assert repo.introspect_calls == []

    def test_cache_miss_falls_back_to_repository_and_populates_cache(self):
        identity = SupplierIdentity(
            supplier_id=1,
            supplier_account_id=199,
            email="supplier@example.com",
            groups=[],
            permissions=[],
            expires_at=datetime.datetime(2026, 8, 1, 12, 0, 0),
        )
        repo = FakeAuthRepository(introspect_returns=identity)
        cache = FakeAuthCache()
        service = AuthService(repo, cache)

        result = service.introspect("fresh-token")

        assert repo.introspect_calls == ["fresh-token"]
        assert cache.set_calls == [("fresh-token", 10)]
        assert cache.get_introspection("fresh-token") == result

    def test_cache_miss_with_invalid_token_does_not_populate_cache(self):
        repo = FakeAuthRepository(introspect_returns=None)
        cache = FakeAuthCache()
        service = AuthService(repo, cache)

        assert service.introspect("bad-token") is None
        assert cache.set_calls == []
