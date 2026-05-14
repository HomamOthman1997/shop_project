import asyncio
from datetime import UTC, datetime
import logging
from time import monotonic
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, types

from config import settings
from database.user_repo import get_user
from keyboards.update_required_kb import update_required_keyboard
from utils.translations import t
from utils.user_cache import (
    get_ram_cached_user,
    get_redis_cached_user,
    set_ram_cached_user,
    set_redis_cached_user,
)


logger = logging.getLogger(__name__)
_SLOW_VERSION_CHECK_MS = 250.0


def _as_utc(dt: datetime | None) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _allow_owner_panel_callback(user_id: int, callback_data: str | None) -> bool:
    raw = str(callback_data or "").strip()
    if not raw:
        return False
    if int(user_id) != int(getattr(settings, "owner_id", 0) or 0):
        return False
    allowed_prefixes = (
        "owner_panel:",
        "owner_pm:",
        "owner_quick:",
        "owner_deposit:",
        "owner_rchg:",
        "verify_owner:",
        "support:",
        "custom_preorder:",
    )
    return raw.startswith(allowed_prefixes)


class VersionCheckMiddleware(BaseMiddleware):
    @staticmethod
    async def _is_admin_operation_state(data: Dict[str, Any]) -> bool:
        state = data.get("state")
        if state is None or not hasattr(state, "get_state"):
            return False
        try:
            current_state = str(await state.get_state() or "")
        except Exception:
            return False
        return any(
            name in current_state
            for name in (
                "SupportOwnerReplyFlow",
                "OwnerResellerTopupFSM",
            )
        )

    async def __call__(
        self,
        handler: Callable[[types.Update, Dict[str, Any]], Awaitable[Any]],
        event: types.Update,
        data: Dict[str, Any],
    ) -> Any:
        started_at = monotonic()
        stage_ms: dict[str, float] = {}
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
        stage_started = monotonic()
        user: dict | None = get_ram_cached_user(user_id, now)
        stage_ms["ram_cache"] = (monotonic() - stage_started) * 1000.0
        if not user:
            async def _timed_redis() -> dict | None:
                redis_started = monotonic()
                try:
                    return await get_redis_cached_user(user_id, now)
                finally:
                    stage_ms["redis_cache"] = (monotonic() - redis_started) * 1000.0

            async def _timed_mongo() -> dict | None:
                mongo_started = monotonic()
                try:
                    return await get_user(user_id)
                finally:
                    stage_ms["mongo_user"] = (monotonic() - mongo_started) * 1000.0

            redis_result = await _timed_redis()
            cached_user = redis_result if isinstance(redis_result, dict) else None
            if cached_user:
                user = cached_user
                set_ram_cached_user(user_id, cached_user, now)
            else:
                mongo_result = await _timed_mongo()
                user = mongo_result if isinstance(mongo_result, dict) else None

        if not user:
            if not user:
                result = await handler(event, data)
                self._log_if_slow(event, user_id, started_at, stage_ms, "no_user")
                return result

        if user and not get_ram_cached_user(user_id, now):
            set_ram_cached_user(user_id, user, now)
            async def _persist_cache() -> None:
                redis_set_started = monotonic()
                try:
                    await set_redis_cached_user(user_id, user, now)
                except Exception:
                    pass
                finally:
                    stage_ms["redis_set"] = (monotonic() - redis_set_started) * 1000.0
            asyncio.create_task(_persist_cache())

        lang = user.get("language", "en")
        data["cached_user"] = user
        data["lang"] = lang

        if user.get("banned") is True:
            if message:
                await message.answer(t(lang, "banned_msg"))
            self._log_if_slow(event, user_id, started_at, stage_ms, "banned")
            return None

        if isinstance(event, types.CallbackQuery):
            if _allow_owner_panel_callback(user_id, event.data):
                result = await handler(event, data)
                self._log_if_slow(event, user_id, started_at, stage_ms, "owner_panel")
                return result
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
                result = await handler(event, data)
                self._log_if_slow(event, user_id, started_at, stage_ms, "allowed_callback")
                return result

        if message and hasattr(message, "text") and message.text:
            txt = message.text.strip()
            if txt.startswith("\U0001f504") or txt.lower() == "/start" or txt.lower() == "start":
                result = await handler(event, data)
                self._log_if_slow(event, user_id, started_at, stage_ms, "start_like")
                return result

            if txt.lower() in {"/clean_keyboard", "/clean_kb", "/rkoff"}:
                result = await handler(event, data)
                self._log_if_slow(event, user_id, started_at, stage_ms, "clean_keyboard")
                return result

            if txt.startswith("/select_"):
                result = await handler(event, data)
                self._log_if_slow(event, user_id, started_at, stage_ms, "select")
                return result

        bot_version = user.get("bot_version")
        if bot_version is None:
            result = await handler(event, data)
            self._log_if_slow(event, user_id, started_at, stage_ms, "no_version")
            return result

        if await self._is_admin_operation_state(data):
            result = await handler(event, data)
            self._log_if_slow(event, user_id, started_at, stage_ms, "admin_operation_state")
            return result

        if bot_version != settings.bot_version:
            if message:
                await message.answer(
                    t(lang, "update_msg"),
                    reply_markup=update_required_keyboard(lang),
                )
            self._log_if_slow(event, user_id, started_at, stage_ms, "update_required")
            return None

        result = await handler(event, data)
        self._log_if_slow(event, user_id, started_at, stage_ms, "pass")
        return result

    @staticmethod
    def _log_if_slow(event: types.Update, user_id: int, started_at: float, stage_ms: dict[str, float], outcome: str) -> None:
        total_ms = (monotonic() - started_at) * 1000.0
        if total_ms < _SLOW_VERSION_CHECK_MS:
            return
        event_name = type(event).__name__
        detail = ", ".join(f"{k}={v:.1f}ms" for k, v in stage_ms.items())
        logger.info(
            "perf.version_check slow total=%.1fms user_id=%s event=%s outcome=%s %s",
            total_ms,
            user_id,
            event_name,
            outcome,
            detail,
        )
