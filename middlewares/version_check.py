import json
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, types

from config import settings
from database.redis_client import redis
from database.user_repo import get_user
from keyboards.update_required_kb import update_required_keyboard
from utils.translations import t

# In-process cache: {user_id: {"data": {...}, "last_update": datetime}}
ram_cache: dict[int, dict[str, Any]] = {}

RAM_FRESH_TTL = timedelta(seconds=45)
CACHE_MAX_AGE = timedelta(hours=1)


def _as_utc(dt: datetime | None) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _ram_cached_user(user_id: int, now: datetime, *, fresh_only: bool) -> dict | None:
    ram_obj = ram_cache.get(user_id)
    if not ram_obj:
        return None
    last_ram_update = _as_utc(ram_obj.get("last_update"))
    if not last_ram_update:
        return None
    max_age = RAM_FRESH_TTL if fresh_only else CACHE_MAX_AGE
    if now - last_ram_update > max_age:
        return None
    user = ram_obj.get("data")
    return user if isinstance(user, dict) else None


class VersionCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.Update, Dict[str, Any]], Awaitable[Any]],
        event: types.Update,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, types.Message):
            user_id = event.from_user.id
            message = event
        elif isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id
            message = event.message
        elif isinstance(event, types.InlineQuery):
            # Keep inline responses fast and avoid extra cache/DB round-trips.
            return await handler(event, data)
        else:
            return await handler(event, data)

        now = datetime.now(UTC)
        cache_key = f"user:{user_id}"
        user: dict | None = _ram_cached_user(user_id, now, fresh_only=True)
        redis_ok = True

        # Redis is a secondary layer now, not a hard dependency on each update.
        if not user:
            try:
                cached = await redis.get(cache_key)
                if cached:
                    obj = json.loads(cached)
                    cached_user = obj.get("data")
                    last_update_raw = obj.get("last_update")
                    last_update = _as_utc(datetime.fromisoformat(last_update_raw)) if last_update_raw else None
                    if isinstance(cached_user, dict) and last_update and now - last_update <= CACHE_MAX_AGE:
                        user = cached_user
                        ram_cache[user_id] = {
                            "data": cached_user,
                            "last_update": now,
                        }
            except Exception:
                redis_ok = False

        # If Redis is unavailable, allow stale RAM cache up to max cache age.
        if not user and not redis_ok:
            user = _ram_cached_user(user_id, now, fresh_only=False)

        if not user:
            user = await get_user(user_id)
            if not user:
                return await handler(event, data)

            if redis_ok:
                try:
                    await redis.set(
                        cache_key,
                        json.dumps(
                            {
                                "data": user,
                                "last_update": now.isoformat(),
                            },
                            default=str,
                        ),
                    )
                except Exception:
                    pass

            ram_cache[user_id] = {
                "data": user,
                "last_update": now,
            }

        lang = user.get("language", "en")

        if user.get("banned") is True:
            if message:
                await message.answer(t(lang, "banned_msg"))
            return None

        if isinstance(event, types.CallbackQuery):
            if event.data and event.data in [
                "lang_en",
                "lang_ar",
                "lang_back",
                "lang_cancel",
                "sub:back_lang",
                "sub:cancel",
                "force_start",
                "update:cancel",
            ]:
                return await handler(event, data)

        if message and hasattr(message, "text") and message.text:
            txt = message.text.strip()
            if txt.startswith("\U0001f504") or txt.lower() == "/start" or txt.lower() == "start":
                return await handler(event, data)

            if txt.lower() in {"/clean_keyboard", "/clean_kb", "/rkoff"}:
                return await handler(event, data)

            if txt.startswith("/select_"):
                return await handler(event, data)

        bot_version = user.get("bot_version")
        if bot_version is None:
            return await handler(event, data)

        if bot_version != settings.bot_version:
            if message:
                await message.answer(
                    t(lang, "update_msg"),
                    reply_markup=update_required_keyboard(lang),
                )
            return None

        return await handler(event, data)
