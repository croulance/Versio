import json

from apps.supplier_auth.interfaces.cache import AuthCacheInterface
from infrastructure.cache.redis_client import RedisClient

_REDIS_NS_AUTH_INTROSPECT = "auth:introspect"


class AuthCacheAdapter(AuthCacheInterface):
    """Application-layer adapter over the generic RedisClient (reused as-is —
    it's already domain-free, same client the transformation app uses)."""

    def __init__(self, client: RedisClient):
        self._client = client

    def get_introspection(self, token_key: str) -> dict | None:
        raw = self._client.get(f"{_REDIS_NS_AUTH_INTROSPECT}:{token_key}")
        return json.loads(raw) if raw else None

    def set_introspection(self, token_key: str, data: dict, ttl: int) -> None:
        self._client.set(
            f"{_REDIS_NS_AUTH_INTROSPECT}:{token_key}", json.dumps(data), ttl
        )

    def invalidate_introspection(self, token_key: str) -> None:
        self._client.delete(f"{_REDIS_NS_AUTH_INTROSPECT}:{token_key}")
