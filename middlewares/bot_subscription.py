from __future__ import annotations

from datetime import UTC, datetime
import logging
from time import monotonic
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import OWNER_ID
from database.bots_repo import get_reseller_id_for_bot
from services.subscriptions.bot_subscription_service import get_bot_subscription
from utils.bot_menu_context import is_card_ex_bot, is_digital_products_bot, is_main_bot, is_numbers_bot, resolve_runtime_bot_id


logger = logging.getLogger(__name__)
_SLOW_SUBSCRIPTION_MW_MS = 250.0


def _fmt_dt(value) -> str:
    if not isinstance(value, datetime):
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _subscription_block_text(subscription: dict, *, lang: str) -> str:
    renewal_amount = float(subscription.get("renewal_charge_usd") or subscription.get("monthly_price_usd") or 10.0)
    trial_amount = float(subscription.get("trial_price_usd") or 1.0)
    status = str(subscription.get("status") or "").strip().lower()
    grace_ends_at = subscription.get("grace_ends_at")
    required_amount = trial_amount if bool(subscription.get("trial_available")) else renewal_amount
    is_ar = str(lang or "").lower().startswith("ar")

    if is_ar:
        if status == "payment_required":
            return (
                "هذا البوت موقوف لأن الاشتراك غير مدفوع.\n\n"
                f"الدفعة المطلوبة الآن: ${required_amount:.2f}.\n"
                "يرجى شحن رصيد الريسيلر في البوت الرئيسي لإعادة تفعيل البوت."
            )
        return (
            "هذا البوت موقوف لأن الاشتراك غير مدفوع.\n\n"
            f"قيمة التجديد الحالية: ${renewal_amount:.2f}.\n"
            f"انتهت مهلة السماح بتاريخ: {_fmt_dt(grace_ends_at)}\n"
            "سيعود البوت للعمل بعد شحن رصيد الريسيلر في البوت الرئيسي وتحصيل قيمة الاشتراك."
        )

    if status == "payment_required":
        return (
            "This bot is suspended because the subscription has not been paid.\n\n"
            f"Current required payment: ${required_amount:.2f}.\n"
            "Top up the reseller balance in the main bot to reactivate the bot."
        )
    return (
        "This bot is suspended because the subscription has not been paid.\n\n"
        f"Current renewal amount: ${renewal_amount:.2f}.\n"
        f"Grace ended at: {_fmt_dt(grace_ends_at)}\n"
        "The bot will be reactivated after the reseller balance in the main bot is topped up and renewal is collected."
    )


class BotSubscriptionMiddleware(BaseMiddleware):
    _bot_id_cache: dict[int, tuple[int, float]] = {}
    _reseller_cache: dict[int, tuple[int, float]] = {}
    _subscription_cache: dict[int, tuple[dict, float]] = {}
    _notice_cache: dict[tuple[int, int, str], float] = {}

    _BOT_ID_TTL = 300.0
    _RESELLER_TTL = 60.0
    _SUB_TTL = 20.0
    _BLOCKED_SUB_TTL = 3.0
    _BLOCKED_NOTICE_TTL = 20.0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        started_at = monotonic()
        stage_ms: dict[str, float] = {}
        bot = data.get("bot")
        if bot is None:
            return await handler(event, data)

        from_user = getattr(event, "from_user", None)
        if from_user and int(from_user.id) == int(OWNER_ID):
            return await handler(event, data)

        now_ts = monotonic()
        bot_runtime_key = id(bot)
        bot_id = self._cached_bot_id(bot_runtime_key, now_ts)
        if bot_id is None:
            stage_started = monotonic()
            bot_id = int(await resolve_runtime_bot_id(bot) or 0)
            self._bot_id_cache[bot_runtime_key] = (bot_id, now_ts)
            stage_ms["bot_id"] = (monotonic() - stage_started) * 1000.0
        if await self._is_platform_bot(bot_id):
            result = await handler(event, data)
            self._log_if_slow(event, bot_id, stage_ms, started_at, "platform_bot")
            return result

        reseller_id = self._cached_reseller_id(bot_id, now_ts)
        if reseller_id is None:
            stage_started = monotonic()
            reseller_id = int(await get_reseller_id_for_bot(bot_id) or 0)
            self._reseller_cache[bot_id] = (reseller_id, now_ts)
            stage_ms["reseller_id"] = (monotonic() - stage_started) * 1000.0
        if reseller_id <= 0:
            result = await handler(event, data)
            self._log_if_slow(event, bot_id, stage_ms, started_at, "not_reseller")
            return result

        subscription = self._cached_subscription(bot_id, now_ts)
        if subscription is None:
            stage_started = monotonic()
            subscription = await get_bot_subscription(bot_id)
            self._subscription_cache[bot_id] = (subscription, now_ts)
            stage_ms["subscription"] = (monotonic() - stage_started) * 1000.0

        status = str(subscription.get("status") or "").strip().lower()
        user_id = int(getattr(from_user, "id", 0) or 0)
        lang = str(data.get("lang") or await self._resolve_lang(user_id) or "en")

        if status == "grace_period":
            result = await handler(event, data)
            self._log_if_slow(event, bot_id, stage_ms, started_at, "grace")
            return result

        if status not in {"payment_required", "suspended"}:
            result = await handler(event, data)
            self._log_if_slow(event, bot_id, stage_ms, started_at, f"pass:{status or 'active'}")
            return result

        await self._notify_if_needed(
            event=event,
            bot_id=bot_id,
            user_id=user_id,
            key="blocked",
            ttl=self._BLOCKED_NOTICE_TTL,
            text=_subscription_block_text(subscription, lang=lang),
            short_text="الاشتراك غير مدفوع." if lang.startswith("ar") else "Subscription unpaid.",
            block=True,
        )
        self._log_if_slow(event, bot_id, stage_ms, started_at, f"blocked:{status}")
        return None

    async def _notify_if_needed(
        self,
        *,
        event: TelegramObject,
        bot_id: int,
        user_id: int,
        key: str,
        ttl: float,
        text: str,
        short_text: str,
        block: bool = False,
    ) -> None:
        now_ts = monotonic()
        cache_key = (user_id, bot_id, key)
        should_notify = (now_ts - self._notice_cache.get(cache_key, 0.0)) >= ttl
        if should_notify:
            self._notice_cache[cache_key] = now_ts
        if isinstance(event, Message):
            if should_notify:
                await event.answer(text)
            return
        if isinstance(event, CallbackQuery):
            if should_notify:
                await event.answer(text if len(text) <= 180 else short_text, show_alert=block or True)
            else:
                await event.answer()

    @classmethod
    def _cached_bot_id(cls, key: int, now_ts: float) -> int | None:
        cached = cls._bot_id_cache.get(key)
        if not cached:
            return None
        value, ts = cached
        return value if (now_ts - ts) <= cls._BOT_ID_TTL else None

    @classmethod
    def _cached_reseller_id(cls, bot_id: int, now_ts: float) -> int | None:
        cached = cls._reseller_cache.get(bot_id)
        if not cached:
            return None
        value, ts = cached
        return value if (now_ts - ts) <= cls._RESELLER_TTL else None

    @classmethod
    def _cached_subscription(cls, bot_id: int, now_ts: float) -> dict | None:
        cached = cls._subscription_cache.get(bot_id)
        if not cached:
            return None
        value, ts = cached
        status = str((value or {}).get("status") or "").strip().lower()
        ttl = cls._BLOCKED_SUB_TTL if status in {"payment_required", "suspended"} else cls._SUB_TTL
        return value if (now_ts - ts) <= ttl else None

    @staticmethod
    async def _resolve_lang(user_id: int) -> str:
        try:
            from database.user_repo import get_user

            user = await get_user(int(user_id))
            return str((user or {}).get("language") or "en")
        except Exception:
            return "en"

    @staticmethod
    async def _is_platform_bot(bot_id: int) -> bool:
        return (
            await is_main_bot(bot_id)
            or await is_numbers_bot(bot_id)
            or await is_digital_products_bot(bot_id)
            or await is_card_ex_bot(bot_id)
        )

    @staticmethod
    def _log_if_slow(event: TelegramObject, bot_id: int, stage_ms: dict[str, float], started_at: float, outcome: str) -> None:
        total_ms = (monotonic() - started_at) * 1000.0
        if total_ms < _SLOW_SUBSCRIPTION_MW_MS:
            return
        logger.info(
            "perf.bot_subscription slow total=%.1fms bot_id=%s event=%s outcome=%s %s",
            total_ms,
            bot_id,
            type(event).__name__,
            outcome,
            ", ".join(f"{k}={v:.1f}ms" for k, v in stage_ms.items()),
        )
