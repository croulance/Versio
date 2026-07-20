import datetime
import logging

from django.conf import settings

from apps.supplier_auth.interfaces.cache import AuthCacheInterface
from apps.supplier_auth.repositories.auth_repository import AuthRepository

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, repository: AuthRepository, cache: AuthCacheInterface) -> None:
        self._repo = repository
        self._cache = cache

    def login(self, email: str, password: str) -> str | None:
        """Return an opaque, DB-backed token on success, None on invalid credentials."""
        issued = self._repo.login(email, password, ttl=self._token_ttl())
        if not issued:
            logger.warning(f"Failed login attempt for {email}")
            return None
        return issued.key

    def refresh(self, token: str) -> str | None:
        """Exchange a still-valid token for a new one with a fresh expiry window."""
        # The old token is deleted as part of rotation (single active token per
        # supplier) — invalidate its cache entry too, so a cached introspection
        # can never outlive the row it was read from. Unconditional: deleting a
        # cache key that was never set (or already gone) is a harmless no-op.
        self._cache.invalidate_introspection(token)
        issued = self._repo.refresh(token, ttl=self._token_ttl())
        return issued.key if issued else None

    def introspect(self, token: str) -> dict | None:
        """Look up the token and return the supplier identity it carries, or None.
        Cache-aside, same pattern as ChunkProcessingService's template/source-field
        cache: check cache, fall back to the repository on a miss, populate on the
        way out. Short TTL — this is a performance layer over a real DB lookup that
        runs on every dashboard request, not a source of truth in its own right."""
        cached = self._cache.get_introspection(token)
        if cached is not None:
            return cached

        identity = self._repo.introspect(token)
        if identity is None:
            return None
        data = {
            "supplier_id": identity.supplier_id,
            "supplier_account_id": identity.supplier_account_id,
            "email": identity.email,
            "groups": identity.groups,
            "permissions": identity.permissions,
            "expires_at": identity.expires_at.isoformat(),
        }
        self._cache.set_introspection(
            token, data, settings.AUTH_INTROSPECTION_CACHE_TTL
        )
        return data

    # ── private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _token_ttl() -> datetime.timedelta:
        return datetime.timedelta(days=settings.SUPPLIER_TOKEN_TTL_DAYS)
