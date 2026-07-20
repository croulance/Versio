from apps.transformation.cache.cache_adapter import CacheAdapter
from apps.transformation.interfaces.cache import CacheAdapterInterface
from infrastructure.cache.redis_client import RedisClient


class CacheAdapterFactory:
    @staticmethod
    def create() -> CacheAdapterInterface:
        return CacheAdapter(RedisClient())
