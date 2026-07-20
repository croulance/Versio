from abc import ABC, abstractmethod


class AuthCacheInterface(ABC):
    """
    Port for caching token introspection lookups — the only thing worth
    caching in this service. `login`/`refresh` always do a real, uncached DB
    check (they mutate state), so there's nothing to cache there.
    """

    @abstractmethod
    def get_introspection(self, token_key: str) -> dict | None: ...

    @abstractmethod
    def set_introspection(self, token_key: str, data: dict, ttl: int) -> None: ...

    @abstractmethod
    def invalidate_introspection(self, token_key: str) -> None:
        """Must be called whenever a token_key stops being valid before its
        natural TTL — currently only on rotation (refresh() deletes the old
        token row and issues a new one), so a cached entry never outlives the
        row it was read from."""
