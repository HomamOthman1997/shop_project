from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from database.redis_client import redis


USER_CACHE_TTL = timedelta(seconds=45)

# In-process cache: {user_id: {"data": {...}, "last_update": datetime}}
ram_cache: dict[int, dict[str, Any]] = {}


def _as_utc(dt: datetime | None) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def user_cache_key(user_id: int) -> str:
    return f"user:{int(user_id)}"


def get_ram_cached_user(user_id: int, now: datetime) -> dict | None:
    ram_obj = ram_cache.get(int(user_id))
    if not ram_obj:
        return None
    last_ram_update = _as_utc(ram_obj.get("last_update"))
    if not last_ram_update or now - last_ram_update > USER_CACHE_TTL:
        return None
    user = ram_obj.get("data")
    return user if isinstance(user, dict) else None


def set_ram_cached_user(user_id: int, user: dict, now: datetime) -> None:
    ram_cache[int(user_id)] = {
        "data": dict(user),
        "last_update": now,
    }


def invalidate_ram_cached_user(user_id: int) -> None:
    ram_cache.pop(int(user_id), None)


async def get_redis_cached_user(user_id: int, now: datetime) -> dict | None:
    cached = await redis.get(user_cache_key(user_id))
    if not cached:
        return None
    obj = json.loads(cached)
    cached_user = obj.get("data")
    last_update_raw = obj.get("last_update")
    last_update = _as_utc(datetime.fromisoformat(last_update_raw)) if last_update_raw else None
    if not (isinstance(cached_user, dict) and last_update and now - last_update <= USER_CACHE_TTL):
        return None
    return cached_user


async def set_redis_cached_user(user_id: int, user: dict, now: datetime) -> None:
    await redis.set(
        user_cache_key(user_id),
        json.dumps(
            {
                "data": user,
                "last_update": now.isoformat(),
            },
            default=str,
        ),
        ex=max(1, int(USER_CACHE_TTL.total_seconds())),
    )


async def invalidate_user_cache(user_id: int) -> None:
    invalidate_ram_cached_user(user_id)
    await redis.delete(user_cache_key(user_id))
