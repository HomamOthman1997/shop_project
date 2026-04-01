from upstash_redis.asyncio import Redis

from config import settings


class NullRedis:
    async def get(self, *_args, **_kwargs):
        return None

    async def set(self, *_args, **_kwargs):
        return None

    async def delete(self, *_args, **_kwargs):
        return None


if settings.redis_url and settings.redis_token:
    redis = Redis(url=settings.redis_url, token=settings.redis_token)
else:
    redis = NullRedis()
