import redis
from django.conf import settings


class RedisClient:
    """
    Generic Redis infrastructure client.
    Knows nothing about the domain — only keys, values, TTLs and atomicity.
    """

    def __init__(self):
        self._client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ttl: int) -> None:
        self._client.set(key, value, ex=ttl)

    def set_nx(self, key: str, value: str, ttl: int) -> bool:
        return bool(self._client.set(key, value, nx=True, ex=ttl))

    def expire(self, key: str, ttl: int) -> bool:
        """Resets an existing key's TTL without touching its value. False if
        the key doesn't exist (e.g. already expired) -- callers shouldn't
        treat that as an error, just as "too late to renew"."""
        return bool(self._client.expire(key, ttl))

    def delete(self, key: str) -> None:
        self._client.delete(key)
