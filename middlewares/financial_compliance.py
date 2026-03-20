from datetime import UTC, datetime
import logging
from time import monotonic
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import OWNER_ID
from database.bots_repo import get_reseller_id_for_bot
from database.financial_ledger import get_reseller_financial_lock


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
        bot = data.get("bot")
        if bot is None:
            return await handler(event, data)

        from_user = getattr(event, "from_user", None)
        if from_user and int(from_user.id) == int(OWNER_ID):
            return await handler(event, data)

        now_ts = monotonic()
        bot_runtime_key = id(bot)

        bot_id = self._get_cached_bot_id(bot_runtime_key, now_ts)
        if bot_id is None:
            bot_id = int((await bot.get_me()).id)
            self._set_cached_bot_id(bot_runtime_key, bot_id, now_ts)

        reseller_id = self._get_cached_reseller_id(bot_id, now_ts)
        if reseller_id is None:
            resolved = await get_reseller_id_for_bot(int(bot_id))
            reseller_id = int(resolved or 0)
            self._set_cached_reseller_id(bot_id, reseller_id, now_ts)
        if not reseller_id:
            return await handler(event, data)

        lock = self._get_cached_lock(reseller_id, bot_id, now_ts)
        if lock is False:
            lock = await get_reseller_financial_lock(int(reseller_id), bot_id=int(bot_id))
            self._set_cached_lock(reseller_id, bot_id, lock if isinstance(lock, dict) else None, now_ts)
        if not lock:
            return await handler(event, data)

        cycle_key = str(lock.get("cycle_key") or "-")
        due_at = lock.get("payment_due_at")
        if isinstance(due_at, datetime):
            due_at = due_at if due_at.tzinfo else due_at.replace(tzinfo=UTC)
            due_txt = due_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        else:
            due_txt = "-"

        amount_due = float(lock.get("net_due") or 0.0)
        text = (
            "Services are temporarily suspended for this reseller bot due to unpaid monthly obligations.\n\n"
            f"Cycle: {cycle_key}\n"
            f"Reseller ID: {int(reseller_id)}\n"
            f"Bot ID: {int(bot_id)}\n"
            f"Amount due: {amount_due:.2f}$\n"
            f"Payment deadline was: {due_txt}\n\n"
            "This lock applies only to this reseller and this bot.\n"
            "Services will be re-enabled after the owner confirms full payment."
        )

        user_id = int(getattr(from_user, "id", 0) or 0)
        cooldown_key = (user_id, int(bot_id))
        last_ts = self._last_notice_at.get(cooldown_key, 0.0)
        should_notify = (now_ts - last_ts) >= 20.0

        if isinstance(event, Message):
            if should_notify:
                self._last_notice_at[cooldown_key] = now_ts
                logger.warning(
                    "financial lock blocked message | reseller_id=%s bot_id=%s user_id=%s cycle=%s due=%s amount_due=%.2f",
                    reseller_id,
                    bot_id,
                    user_id,
                    cycle_key,
                    due_txt,
                    amount_due,
                )
                await event.answer(text)
            return None

        if isinstance(event, CallbackQuery):
            if should_notify:
                self._last_notice_at[cooldown_key] = now_ts
                logger.warning(
                    "financial lock blocked callback | reseller_id=%s bot_id=%s user_id=%s cycle=%s due=%s amount_due=%.2f",
                    reseller_id,
                    bot_id,
                    user_id,
                    cycle_key,
                    due_txt,
                    amount_due,
                )
                await event.answer("Services are suspended until monthly dues are paid.", show_alert=True)
            else:
                await event.answer()
            return None

        return await handler(event, data)
