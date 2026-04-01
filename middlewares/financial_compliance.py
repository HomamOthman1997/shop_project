from datetime import UTC, datetime
import logging
from time import monotonic
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import OWNER_ID
from database.bots_repo import get_reseller_id_for_bot


logger = logging.getLogger("financial_compliance")


class FinancialComplianceMiddleware(BaseMiddleware):
    _last_notice_at: dict[tuple[int, int], float] = {}
    _bot_id_cache: dict[int, tuple[int, float]] = {}
    _reseller_cache: dict[int, tuple[int, float]] = {}
    _lock_cache: dict[tuple[int, int], tuple[dict | None, float]] = {}

    _BOT_ID_TTL_SEC = 300.0
    _RESELLER_TTL_SEC = 60.0
    _LOCK_TTL_SEC = 15.0

    @classmethod
    def _get_cached_bot_id(cls, bot_runtime_key: int, now_ts: float) -> int | None:
        cached = cls._bot_id_cache.get(bot_runtime_key)
        if not cached:
            return None
        bot_id, ts = cached
        if now_ts - ts > cls._BOT_ID_TTL_SEC:
            return None
        return int(bot_id)

    @classmethod
    def _set_cached_bot_id(cls, bot_runtime_key: int, bot_id: int, now_ts: float) -> None:
        cls._bot_id_cache[bot_runtime_key] = (int(bot_id), float(now_ts))

    @classmethod
    def _get_cached_reseller_id(cls, bot_id: int, now_ts: float) -> int | None:
        cached = cls._reseller_cache.get(int(bot_id))
        if not cached:
            return None
        reseller_id, ts = cached
        if now_ts - ts > cls._RESELLER_TTL_SEC:
            return None
        return int(reseller_id)

    @classmethod
    def _set_cached_reseller_id(cls, bot_id: int, reseller_id: int, now_ts: float) -> None:
        cls._reseller_cache[int(bot_id)] = (int(reseller_id), float(now_ts))

    @classmethod
    def _get_cached_lock(cls, reseller_id: int, bot_id: int, now_ts: float) -> dict | None | bool:
        cached = cls._lock_cache.get((int(reseller_id), int(bot_id)))
        if not cached:
            return False
        lock, ts = cached
        if now_ts - ts > cls._LOCK_TTL_SEC:
            return False
        return lock

    @classmethod
    def _set_cached_lock(cls, reseller_id: int, bot_id: int, lock: dict | None, now_ts: float) -> None:
        cls._lock_cache[(int(reseller_id), int(bot_id))] = (lock, float(now_ts))

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        return await handler(event, data)
