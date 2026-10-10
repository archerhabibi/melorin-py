from functools import lru_cache

from melorin.core.config import get_settings


@lru_cache
def get_redis():
    url = get_settings().redis_url
    if not url:
        return None
    import redis.asyncio as aioredis

    return aioredis.from_url(url, decode_responses=True)
