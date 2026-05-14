import asyncio
import atexit
import importlib.util
import json
import logging
from datetime import UTC, datetime, timedelta
import os
import sys
from contextlib import suppress
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo

from config import settings, validate_runtime_security, enforce_openrouter_only_mode
from database.bots_repo import bootstrap_bot_indexes, get_verified_bots
from database.custom_services_repo import bootstrap_custom_services_indexes
from database.user_repo import bootstrap_user_indexes, bootstrap_user_links_indexes
from database.mongo import db
from database.cardex_repo import bootstrap_cardex_indexes, release_due_cards
from database.financial_ledger import bootstrap_financial_indexes
from database.recharge_repo import (
    bootstrap_recharge_indexes,
    purge_accepted_recharge_proofs,
    recover_stuck_processing_recharges,
)
from database.provider_balance_alert_repo import get_provider_balance_alert_settings
from database.proxy_telemetry_repo import summarize_proxy_events
from database.bot_logs_repo import get_bot_logs_target
from database.proxy_telemetry_repo import bootstrap_proxy_events_indexes
from database.usage_stats_repo import bootstrap_usage_stats_indexes
from database.lifecycle_repo import ensure_schema_markers, run_lifecycle_cleanup
from database.number_events_repo import bootstrap_number_events_indexes
from database.temp_number_stats_repo import bootstrap_temp_number_stats_indexes
from services.subscriptions.bot_subscription_service import (
    mark_bot_subscription_expiry_notice,
    mark_bot_subscription_grace_notice,
    run_bot_subscription_sweep,
)
from handlers.custom_services import router as custom_services_router
from handlers.admin_services import router as admin_services_router
from handlers.owner_requests import router as owner_requests_router
from handlers.store_sections import router as store_sections_router
from keyboards.main_menu_kb import _digital_store_webapp_url
from services.cards_bot.handlers import router as card_ex_bot_router
from handlers.language import router as language_base
from handlers.main_menu import router as main_menu_base
from handlers.main_bot_redirects import router as main_bot_redirects_router
from handlers.reseller_recharge import router as reseller_recharge_router
from handlers.support_admin import router as support_admin_router
from handlers.start import router as start_base
from handlers.subscription import router as subscription_base
from handlers.verify_reseller import router as verify_reseller_base
from middlewares.financial_compliance import FinancialComplianceMiddleware
from middlewares.interaction_lock import InteractionLockMiddleware
from middlewares.bot_subscription import BotSubscriptionMiddleware
from middlewares.version_check import VersionCheckMiddleware
from services.numbers.handlers.core_numbers import router as core_numbers_router
from services.numbers.handlers.core_numbers_buy import (
    router as core_numbers_buy_router,
    run_rental_protection_sweep,
    run_temp_wait_recovery_sweep,
    run_unprovisioned_number_order_recovery_sweep,
)
from services.numbers.handlers.numbers_inline import router as numbers_inline_router
from services.numbers.manager import PROVIDERS
from services.numbers.core.session_manager import SessionManager
from services.proxies.handlers.proxy_flow import router as proxy_flow_router
from services.proxies.handlers.proxy_inline import router as proxy_inline_router
from services.digital_products.recovery import run_digital_products_pending_recovery_sweep
from services.digital_products.miniapp import start_miniapp_server
from services.proxies.catalog_cache import set_offers_cache
from services.proxies.manager import get_proxy_catalog
from services.proxies.validation import run_proxy_catalog_validation
from services.digital_products.validation import run_digital_products_validation
from utils.provider_alias import provider_public_id
from utils.sentry_reporting import init_sentry
from utils.log_noise import install_transient_noise_filter
from utils.telegram_error_reporting import install_telegram_error_handler
from utils.bot_kind_filter import BotKindFilter
from utils.bot_menu_context import BOT_KIND_ADMIN, BOT_KIND_CARD, BOT_KIND_DIGITAL, BOT_KIND_MAIN, BOT_KIND_NUMBERS, BOT_KIND_RESELLER

_public_dispatcher_built = False
_main_dispatcher_built = False
_numbers_dispatcher_built = False
_digital_products_dispatcher_built = False
_card_ex_dispatcher_built = False
_admin_alert_bot: Bot | None = None
_LOCK_FILE = Path(gettempdir()) / "shop_project_bot_manager.lock"
_SCHED_STATE_FILE = Path(gettempdir()) / "shop_project_bot_manager.schedule.json"
_LOCK_ACQUIRED = False
_cached_main_bot_id: int | None = None
_cached_numbers_bot_id: int | None = None
_cached_admin_bot_id: int | None = None
_cached_card_ex_bot_id: int | None = None


def _restrict_router_to_kinds(router, *allowed_kinds: str):
    kind_filter = BotKindFilter(*allowed_kinds)
    router.message.filter(kind_filter)
    router.callback_query.filter(kind_filter)
    return router


def _load_router_clone(module_name: str, file_path: str):
    path = Path(file_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load router module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    router = getattr(module, "router", None)
    if router is None:
        raise RuntimeError(f"Router not found in module: {file_path}")
    return router


async def _run_startup_step(
    name: str,
    fn,
    *,
    attempts: int = 3,
    delay_seconds: float = 2.0,
) -> bool:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await fn()
            if attempt > 1:
                logging.info("startup step recovered: %s (attempt %s/%s)", name, attempt, attempts)
            return True
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                logging.warning(
                    "startup step failed: %s (attempt %s/%s): %s",
                    name,
                    attempt,
                    attempts,
                    exc,
                )
                await asyncio.sleep(delay_seconds)
    logging.error("startup step failed permanently: %s: %s", name, last_exc)
    return False


async def _run_startup_bootstraps() -> None:
    steps = [
        ("bot indexes", bootstrap_bot_indexes),
        ("financial indexes", bootstrap_financial_indexes),
        ("card-ex indexes", bootstrap_cardex_indexes),
        ("custom services indexes", bootstrap_custom_services_indexes),
        ("recharge indexes", bootstrap_recharge_indexes),
        ("user indexes", bootstrap_user_indexes),
        ("user links indexes", bootstrap_user_links_indexes),
        ("temp number stats indexes", bootstrap_temp_number_stats_indexes),
        ("number events indexes", bootstrap_number_events_indexes),
        ("proxy events indexes", bootstrap_proxy_events_indexes),
        ("usage stats indexes", bootstrap_usage_stats_indexes),
        ("schema markers", ensure_schema_markers),
    ]
    failed: list[str] = []
    for name, fn in steps:
        ok = await _run_startup_step(name, fn)
        if not ok:
            failed.append(name)
    if failed:
        logging.warning("starting in degraded mode (bootstrap failed): %s", ", ".join(failed))


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_utc_iso(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_sched_state() -> dict[str, str]:
    try:
        raw = json.loads(_SCHED_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    state: dict[str, str] = {}
    for key in (
        "last_financial_anomaly_at",
        "last_digital_products_recovery_at",
        "last_proxy_ops_summary_at",
        "last_proxy_validation_at",
        "last_proxy_catalog_refresh_at",
        "last_digital_products_validation_at",
        "last_lifecycle_cleanup_at",
        "last_bot_subscription_sweep_at",
    ):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            state[key] = value.strip()
    return state


def _save_sched_state(state: dict[str, str]) -> None:
    try:
        _SCHED_STATE_FILE.write_text(json.dumps(state, ensure_ascii=True), encoding="utf-8")
    except Exception:
        logging.debug("failed to persist scheduler state")


def _extract_balance_value(raw_balance: Any) -> float | None:
    if raw_balance is None:
        return None
    try:
        if isinstance(raw_balance, (int, float, str)):
            return float(raw_balance)
        if isinstance(raw_balance, dict):
            for key in ("balance", "currentBalance", "available", "amount", "value", "message"):
                if key in raw_balance:
                    return float(raw_balance.get(key))
    except Exception:
        return None
    return None


async def _get_admin_alert_bot() -> Bot | None:
    global _admin_alert_bot
    token = str(getattr(settings, "bot_admin_token", "") or "").strip()
    if not token:
        return None
    if _admin_alert_bot is None:
        _admin_alert_bot = Bot(token=token, timeout=30)
    return _admin_alert_bot


async def _close_admin_alert_bot() -> None:
    global _admin_alert_bot
    if _admin_alert_bot is not None:
        with suppress(Exception):
            await _admin_alert_bot.session.close()
        _admin_alert_bot = None


async def _owner_target_for_balance_alert() -> tuple[int | None, int | None]:
    def _is_group_chat_id(value: Any) -> bool:
        return isinstance(value, int) and int(value) < 0

    cfg = await get_provider_balance_alert_settings()
    chat_id = cfg.get("chat_id")
    thread_id = cfg.get("message_thread_id")
    if _is_group_chat_id(chat_id):
        return int(chat_id), int(thread_id) if isinstance(thread_id, int) else None

    try:
        from database.mongo import db

        doc = await db.system_settings.find_one({"_id": "owner_notifications"})
        if doc and _is_group_chat_id(doc.get("chat_id")):
            return int(doc["chat_id"]), int(doc.get("message_thread_id")) if isinstance(doc.get("message_thread_id"), int) else None
    except Exception:
        pass
    logs_target = await get_bot_logs_target()
    if logs_target and _is_group_chat_id(logs_target.get("chat_id")):
        return int(logs_target["chat_id"]), int(logs_target.get("message_thread_id")) if isinstance(logs_target.get("message_thread_id"), int) else None
    return None, None


async def _pick_owner_bot(running_bots: list[Bot], current_owner_map: dict[int, int]) -> Bot | None:
    if not running_bots:
        return None
    owner_id = int(settings.owner_id)
    for bot in running_bots:
        bot_id = getattr(bot, "_cached_bot_id", None)
        if not isinstance(bot_id, int):
            try:
                me = await bot.get_me()
                bot_id = int(me.id)
                setattr(bot, "_cached_bot_id", bot_id)
            except Exception:
                bot_id = None
        if isinstance(bot_id, int) and int(current_owner_map.get(bot_id) or 0) == owner_id:
            return bot
    return running_bots[0]


async def _send_owner_alert_via_any_bot(
    *,
    running_bots: list[Bot],
    preferred_bot: Bot | None,
    chat_id: int,
    thread_id: int | None,
    text: str,
) -> bool:
    admin_bot = await _get_admin_alert_bot()
    if not running_bots and admin_bot is None:
        return False

    ordered: list[Bot] = []
    if admin_bot is not None:
        ordered.append(admin_bot)
    if preferred_bot is not None:
        ordered.append(preferred_bot)
    for bot in running_bots:
        if bot not in ordered:
            ordered.append(bot)

    for bot in ordered:
        try:
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=text,
            )
            return True
        except Exception:
            continue
    return False


async def _run_provider_balance_alert_cycle(
    *,
    running_bots: list[Bot],
    current_owner_map: dict[int, int],
    state: dict[str, dict[str, Any]],
) -> None:
    cfg = await get_provider_balance_alert_settings()
    if not bool(cfg.get("enabled", True)):
        return
    threshold = float(cfg.get("threshold_usd") or 0.0)
    if threshold <= 0:
        return

    provider_codes = sorted(PROVIDERS.keys())
    seen_provider_objects: set[int] = set()
    low_now: dict[str, float] = {}
    for code in provider_codes:
        provider = PROVIDERS.get(code)
        if provider is None or not hasattr(provider, "get_balance"):
            continue
        object_id = id(provider)
        if object_id in seen_provider_objects:
            continue
        seen_provider_objects.add(object_id)
        try:
            raw = await asyncio.wait_for(provider.get_balance(), timeout=10.0)
        except Exception:
            continue
        balance = _extract_balance_value(raw)
        if balance is None:
            continue
        if balance <= threshold:
            low_now[str(code)] = float(balance)

    now = _utc_now()
    cooldown_minutes = max(5, int(cfg.get("cooldown_minutes") or 45))
    cooldown = timedelta(minutes=cooldown_minutes)
    should_alert: dict[str, float] = {}

    for code, balance in low_now.items():
        item = state.get(code) or {}
        last_sent_at = _parse_utc_iso(str(item.get("last_sent_at") or ""))
        is_active = bool(item.get("active"))
        if (not is_active) or (last_sent_at is None) or ((now - last_sent_at) >= cooldown):
            should_alert[code] = balance
            state[code] = {"active": True, "last_sent_at": now.isoformat(), "last_balance": balance}
        else:
            state[code] = {"active": True, "last_sent_at": str(item.get("last_sent_at") or ""), "last_balance": balance}

    for code in provider_codes:
        if code in low_now:
            continue
        if code in state and bool(state[code].get("active")):
            state[code] = {"active": False, "last_sent_at": str(state[code].get("last_sent_at") or ""), "last_balance": state[code].get("last_balance")}

    if not should_alert:
        return

    chat_id, thread_id = await _owner_target_for_balance_alert()
    if not isinstance(chat_id, int):
        logging.warning("provider balance alert skipped: no owner-group target is configured")
        return
    bot = await _pick_owner_bot(running_bots, current_owner_map)
    lines = [
        "Provider balance low alert",
        f"Threshold: {threshold:.2f}$",
        "",
    ]
    for code in sorted(should_alert.keys()):
        lines.append(f"- {provider_public_id(code)} ({code}): {float(should_alert[code]):.4f}$")
    lines.append("")
    lines.append("Please top up provider balance.")

    sent = await _send_owner_alert_via_any_bot(
        running_bots=running_bots,
        preferred_bot=bot,
        chat_id=chat_id,
        thread_id=thread_id,
        text="\n".join(lines),
    )
    if not sent:
        for code in should_alert.keys():
            item = state.get(code) or {}
            state[code] = {
                "active": False,
                "last_sent_at": str(item.get("last_sent_at") or ""),
                "last_balance": item.get("last_balance"),
            }
        logging.error(
            "provider balance alert send failed for all bots: target_chat_id=%s target_thread_id=%s",
            chat_id,
            thread_id,
        )


def _subscription_grace_notice_text(subscription: dict) -> str:
    grace_ends_at = subscription.get("grace_ends_at")
    renewal_amount = float(subscription.get("renewal_charge_usd") or subscription.get("monthly_price_usd") or 10.0)
    if isinstance(grace_ends_at, datetime):
        if grace_ends_at.tzinfo is None:
            grace_ends_at = grace_ends_at.replace(tzinfo=UTC)
        remaining = grace_ends_at.astimezone(UTC) - _utc_now()
        total_hours = max(0, int(remaining.total_seconds() // 3600))
        days_left = total_hours // 24
        hours_left = total_hours % 24
        return (
            "تنبيه اشتراك البوت\n\n"
            "دخل البوت في المهلة الإضافية.\n"
            f"سيتوقف البوت خلال {days_left} يوم و {hours_left} ساعة إذا لم يتم دفع الاشتراك.\n"
            f"قيمة التجديد الحالية: ${renewal_amount:.2f}\n"
            f"تنتهي المهلة في: {grace_ends_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')}"
        )
    return (
        "تنبيه اشتراك البوت\n\n"
        "دخل البوت في المهلة الإضافية.\n"
        f"قيمة التجديد الحالية: ${renewal_amount:.2f}\n"
        "يرجى شحن رصيدك في البوت المركزي قبل انتهاء المهلة."
    )


def _subscription_expiry_notice_text(subscription: dict) -> str:
    end_at = subscription.get("trial_ends_at") or subscription.get("subscription_ends_at")
    renewal_amount = float(subscription.get("renewal_charge_usd") or subscription.get("monthly_price_usd") or 10.0)
    if isinstance(end_at, datetime):
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=UTC)
        remaining = end_at.astimezone(UTC) - _utc_now()
        total_hours = max(0, int(remaining.total_seconds() // 3600))
        days_left = total_hours // 24
        hours_left = total_hours % 24
        return (
            "تنبيه اشتراك البوت\n\n"
            "الاشتراك الحالي يقترب من الانتهاء.\n"
            f"الوقت المتبقي: {days_left} يوم و {hours_left} ساعة.\n"
            f"قيمة التجديد الحالية: ${renewal_amount:.2f}\n"
            f"تاريخ الانتهاء: {end_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n"
            "تأكد من توفر الرصيد في البوت المركزي قبل موعد الانتهاء."
        )
    return (
        "تنبيه اشتراك البوت\n\n"
        "الاشتراك الحالي يقترب من الانتهاء.\n"
        f"قيمة التجديد الحالية: ${renewal_amount:.2f}\n"
        "تأكد من توفر الرصيد في البوت المركزي قبل موعد الانتهاء."
    )


async def _run_bot_subscription_notice_cycle(
    *,
    running_bots: list[Bot],
    current_owner_map: dict[int, int],
    limit: int = 500,
) -> None:
    admin_bot = await _get_admin_alert_bot()
    if not running_bots and admin_bot is None:
        return
    now = _utc_now()
    preferred_bot = await _pick_owner_bot(running_bots, current_owner_map)
    cursor = db.bots.find(
        {
            "active": True,
            "subscription.status": "grace_period",
        },
        {
            "bot_id": 1,
            "owner_id": 1,
            "subscription": 1,
        },
    ).limit(max(1, int(limit)))
    async for row in cursor:
        bot_id = int(row.get("bot_id") or 0)
        owner_id = int(row.get("owner_id") or 0)
        if bot_id <= 0 or owner_id <= 0:
            continue
        subscription = dict(row.get("subscription") or {})
        history = dict(subscription.get("history") or {})
        last_notice_at = _parse_utc_iso(str(history.get("last_grace_notice_at") or ""))
        if last_notice_at is not None and (now - last_notice_at) < timedelta(hours=12):
            continue
        text = _subscription_grace_notice_text(subscription)
        sent = False
        target_bot: Bot | None = None
        for bot in running_bots:
            cached_id = getattr(bot, "_cached_bot_id", None)
            if not isinstance(cached_id, int):
                try:
                    me = await bot.get_me()
                    cached_id = int(me.id)
                    setattr(bot, "_cached_bot_id", cached_id)
                except Exception:
                    cached_id = None
            if isinstance(cached_id, int) and cached_id == bot_id:
                target_bot = bot
                break
        ordered_bots = [b for b in [target_bot, preferred_bot, admin_bot] if b is not None]
        for bot in running_bots:
            if bot not in ordered_bots:
                ordered_bots.append(bot)
        for bot in ordered_bots:
            try:
                await bot.send_message(chat_id=owner_id, text=text)
                sent = True
                break
            except Exception:
                continue
        if sent:
            await mark_bot_subscription_grace_notice(bot_id, sent_at=now)


async def _run_bot_subscription_expiry_notice_cycle(
    *,
    running_bots: list[Bot],
    current_owner_map: dict[int, int],
    limit: int = 500,
) -> None:
    admin_bot = await _get_admin_alert_bot()
    if not running_bots and admin_bot is None:
        return
    now = _utc_now()
    preferred_bot = await _pick_owner_bot(running_bots, current_owner_map)
    cutoff = now + timedelta(days=3)
    cursor = db.bots.find(
        {
            "active": True,
            "subscription.status": {"$in": ["trial_active", "active"]},
            "$or": [
                {"subscription.trial_ends_at": {"$gte": now, "$lte": cutoff}},
                {"subscription.subscription_ends_at": {"$gte": now, "$lte": cutoff}},
            ],
        },
        {
            "bot_id": 1,
            "owner_id": 1,
            "subscription": 1,
        },
    ).limit(max(1, int(limit)))
    async for row in cursor:
        bot_id = int(row.get("bot_id") or 0)
        owner_id = int(row.get("owner_id") or 0)
        if bot_id <= 0 or owner_id <= 0:
            continue
        subscription = dict(row.get("subscription") or {})
        history = dict(subscription.get("history") or {})
        last_notice_at = _parse_utc_iso(str(history.get("last_expiry_notice_at") or ""))
        if last_notice_at is not None and (now - last_notice_at) < timedelta(hours=12):
            continue
        text = _subscription_expiry_notice_text(subscription)
        sent = False
        target_bot: Bot | None = None
        for bot in running_bots:
            cached_id = getattr(bot, "_cached_bot_id", None)
            if not isinstance(cached_id, int):
                try:
                    me = await bot.get_me()
                    cached_id = int(me.id)
                    setattr(bot, "_cached_bot_id", cached_id)
                except Exception:
                    cached_id = None
            if isinstance(cached_id, int) and cached_id == bot_id:
                target_bot = bot
                break
        ordered_bots = [b for b in [target_bot, preferred_bot, admin_bot] if b is not None]
        for bot in running_bots:
            if bot not in ordered_bots:
                ordered_bots.append(bot)
        for bot in ordered_bots:
            try:
                await bot.send_message(chat_id=owner_id, text=text)
                sent = True
                break
            except Exception:
                continue
        if sent:
            await mark_bot_subscription_expiry_notice(bot_id, sent_at=now)


def _acquire_single_instance_lock() -> None:
    global _LOCK_ACQUIRED

    if _LOCK_ACQUIRED:
        return

    if _LOCK_FILE.exists():
        try:
            existing_pid = int((_LOCK_FILE.read_text(encoding="utf-8").strip() or "0"))
        except Exception:
            existing_pid = 0

        if existing_pid and _pid_exists(existing_pid):
            raise RuntimeError(f"bot_manager is already running with PID={existing_pid}")

        with suppress(Exception):
            _LOCK_FILE.unlink()

    _LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    _LOCK_ACQUIRED = True


def _release_single_instance_lock() -> None:
    global _LOCK_ACQUIRED
    if not _LOCK_ACQUIRED:
        return
    with suppress(Exception):
        if _LOCK_FILE.exists():
            _LOCK_FILE.unlink()
    _LOCK_ACQUIRED = False


atexit.register(_release_single_instance_lock)


class ColorFormatter(logging.Formatter):
    RESET = "\x1b[0m"
    DIM = "\x1b[2m"
    FG_GRAY = "\x1b[90m"
    FG_YELLOW = "\x1b[33m"
    FG_RED = "\x1b[31m"
    FG_BOLD_RED = "\x1b[1;31m"

    LEVEL_COLOR = {
        logging.DEBUG: FG_GRAY,
        logging.INFO: FG_GRAY,
        logging.WARNING: FG_YELLOW,
        logging.ERROR: FG_RED,
        logging.CRITICAL: FG_BOLD_RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        color = self.LEVEL_COLOR.get(record.levelno, self.FG_GRAY)
        if record.levelno <= logging.INFO:
            return f"{self.DIM}{color}{base}{self.RESET}"
        return f"{color}{base}{self.RESET}"


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    install_transient_noise_filter(handler, cooldown_sec=45.0)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    # Keep provider/network diagnostics but suppress per-request transport noise.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_public_dispatcher() -> Dispatcher:
    global _public_dispatcher_built
    if _public_dispatcher_built:
        msg = "Public dispatcher singleton violated: attempted to build more than one public Dispatcher in bot_manager process."
        logging.critical(msg)
        raise RuntimeError(msg)
    _public_dispatcher_built = True

    dp = Dispatcher()

    dp.message.middleware(InteractionLockMiddleware())
    dp.callback_query.middleware(InteractionLockMiddleware())

    dp.message.middleware(VersionCheckMiddleware())
    dp.callback_query.middleware(VersionCheckMiddleware())
    dp.message.middleware(BotSubscriptionMiddleware())
    dp.callback_query.middleware(BotSubscriptionMiddleware())
    dp.message.middleware(FinancialComplianceMiddleware())
    dp.callback_query.middleware(FinancialComplianceMiddleware())

    dp.include_router(_restrict_router_to_kinds(support_admin_router, BOT_KIND_ADMIN))
    dp.include_router(
        _restrict_router_to_kinds(
            _load_router_clone("handlers.admin_services_admin_clone", "handlers/admin_services.py"),
            BOT_KIND_ADMIN,
        )
    )
    dp.include_router(_restrict_router_to_kinds(start_base, BOT_KIND_RESELLER))
    dp.include_router(_restrict_router_to_kinds(language_base, BOT_KIND_RESELLER))
    dp.include_router(_restrict_router_to_kinds(subscription_base, BOT_KIND_RESELLER))
    dp.include_router(_restrict_router_to_kinds(main_menu_base, BOT_KIND_RESELLER))
    dp.include_router(_restrict_router_to_kinds(main_bot_redirects_router, BOT_KIND_RESELLER))
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.custom_services_public_clone", "handlers/custom_services.py"), BOT_KIND_RESELLER))
    dp.include_router(_restrict_router_to_kinds(reseller_recharge_router, BOT_KIND_RESELLER))
    dp.include_router(_restrict_router_to_kinds(admin_services_router, BOT_KIND_RESELLER))
    dp.include_router(_restrict_router_to_kinds(owner_requests_router, BOT_KIND_RESELLER))
    return dp


def build_main_dispatcher() -> Dispatcher:
    global _main_dispatcher_built
    if _main_dispatcher_built:
        msg = "Main dispatcher singleton violated: attempted to build more than one main Dispatcher in bot_manager process."
        logging.critical(msg)
        raise RuntimeError(msg)
    _main_dispatcher_built = True

    dp = Dispatcher()

    dp.message.middleware(InteractionLockMiddleware())
    dp.callback_query.middleware(InteractionLockMiddleware())

    dp.message.middleware(VersionCheckMiddleware())
    dp.callback_query.middleware(VersionCheckMiddleware())
    dp.message.middleware(BotSubscriptionMiddleware())
    dp.callback_query.middleware(BotSubscriptionMiddleware())
    dp.message.middleware(FinancialComplianceMiddleware())
    dp.callback_query.middleware(FinancialComplianceMiddleware())

    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.start_main_clone", "handlers/start.py"), BOT_KIND_MAIN))
    dp.include_router(_restrict_router_to_kinds(proxy_inline_router, BOT_KIND_MAIN))
    dp.include_router(_restrict_router_to_kinds(numbers_inline_router, BOT_KIND_MAIN))
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.language_main_clone", "handlers/language.py"), BOT_KIND_MAIN))
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.subscription_main_clone", "handlers/subscription.py"), BOT_KIND_MAIN))
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.main_menu_main_clone", "handlers/main_menu.py"), BOT_KIND_MAIN))
    dp.include_router(_restrict_router_to_kinds(proxy_flow_router, BOT_KIND_MAIN))
    dp.include_router(_restrict_router_to_kinds(verify_reseller_base, BOT_KIND_MAIN))
    dp.include_router(_restrict_router_to_kinds(custom_services_router, BOT_KIND_MAIN))
    dp.include_router(_restrict_router_to_kinds(core_numbers_router, BOT_KIND_MAIN))
    dp.include_router(_restrict_router_to_kinds(core_numbers_buy_router, BOT_KIND_MAIN))
    return dp


def build_numbers_dispatcher() -> Dispatcher:
    global _numbers_dispatcher_built
    if _numbers_dispatcher_built:
        msg = "Numbers dispatcher singleton violated: attempted to build more than one numbers Dispatcher in bot_manager process."
        logging.critical(msg)
        raise RuntimeError(msg)
    _numbers_dispatcher_built = True

    dp = Dispatcher()
    dp.message.middleware(InteractionLockMiddleware())
    dp.callback_query.middleware(InteractionLockMiddleware())

    dp.message.middleware(VersionCheckMiddleware())
    dp.callback_query.middleware(VersionCheckMiddleware())
    dp.message.middleware(BotSubscriptionMiddleware())
    dp.callback_query.middleware(BotSubscriptionMiddleware())
    dp.message.middleware(FinancialComplianceMiddleware())
    dp.callback_query.middleware(FinancialComplianceMiddleware())

    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.start_numbers_clone", "handlers/start.py"), BOT_KIND_NUMBERS))
    dp.include_router(
        _restrict_router_to_kinds(
            _load_router_clone("services.numbers.handlers.numbers_inline_numbers_clone", "services/numbers/handlers/numbers_inline.py"),
            BOT_KIND_NUMBERS,
        )
    )
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.language_numbers_clone", "handlers/language.py"), BOT_KIND_NUMBERS))
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.subscription_numbers_clone", "handlers/subscription.py"), BOT_KIND_NUMBERS))
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.main_menu_numbers_clone", "handlers/main_menu.py"), BOT_KIND_NUMBERS))
    dp.include_router(
        _restrict_router_to_kinds(
            _load_router_clone("services.numbers.handlers.core_numbers_numbers_clone", "services/numbers/handlers/core_numbers.py"),
            BOT_KIND_NUMBERS,
        )
    )
    dp.include_router(
        _restrict_router_to_kinds(
            _load_router_clone("services.numbers.handlers.core_numbers_buy_numbers_clone", "services/numbers/handlers/core_numbers_buy.py"),
            BOT_KIND_NUMBERS,
        )
    )
    return dp


def build_digital_products_dispatcher() -> Dispatcher:
    global _digital_products_dispatcher_built
    if _digital_products_dispatcher_built:
        msg = "Digital-products dispatcher singleton violated: attempted to build more than one digital-products Dispatcher in bot_manager process."
        logging.critical(msg)
        raise RuntimeError(msg)
    _digital_products_dispatcher_built = True

    dp = Dispatcher()
    dp.message.middleware(InteractionLockMiddleware())
    dp.callback_query.middleware(InteractionLockMiddleware())

    dp.message.middleware(VersionCheckMiddleware())
    dp.callback_query.middleware(VersionCheckMiddleware())
    dp.message.middleware(BotSubscriptionMiddleware())
    dp.callback_query.middleware(BotSubscriptionMiddleware())
    dp.message.middleware(FinancialComplianceMiddleware())
    dp.callback_query.middleware(FinancialComplianceMiddleware())

    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.start_digital_products_clone", "handlers/start.py"), BOT_KIND_DIGITAL))
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.language_digital_products_clone", "handlers/language.py"), BOT_KIND_DIGITAL))
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.subscription_digital_products_clone", "handlers/subscription.py"), BOT_KIND_DIGITAL))
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.main_menu_digital_products_clone", "handlers/main_menu.py"), BOT_KIND_DIGITAL))
    dp.include_router(
        _restrict_router_to_kinds(
            _load_router_clone("handlers.store_sections_digital_clone", "handlers/store_sections.py"),
            BOT_KIND_DIGITAL,
        )
    )
    return dp


def build_card_ex_dispatcher() -> Dispatcher:
    global _card_ex_dispatcher_built
    if _card_ex_dispatcher_built:
        msg = "Card-EX dispatcher singleton violated: attempted to build more than one card-ex Dispatcher in bot_manager process."
        logging.critical(msg)
        raise RuntimeError(msg)
    _card_ex_dispatcher_built = True

    dp = Dispatcher()
    dp.message.middleware(InteractionLockMiddleware())
    dp.callback_query.middleware(InteractionLockMiddleware())

    dp.message.middleware(VersionCheckMiddleware())
    dp.callback_query.middleware(VersionCheckMiddleware())
    dp.message.middleware(BotSubscriptionMiddleware())
    dp.callback_query.middleware(BotSubscriptionMiddleware())
    dp.message.middleware(FinancialComplianceMiddleware())
    dp.callback_query.middleware(FinancialComplianceMiddleware())

    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.start_card_ex_clone", "handlers/start.py"), BOT_KIND_CARD))
    dp.include_router(_restrict_router_to_kinds(_load_router_clone("handlers.language_card_ex_clone", "handlers/language.py"), BOT_KIND_CARD))
    dp.include_router(
        _restrict_router_to_kinds(
            _load_router_clone("handlers.store_sections_card_clone", "handlers/store_sections.py"),
            BOT_KIND_CARD,
        )
    )
    dp.include_router(_restrict_router_to_kinds(card_ex_bot_router, BOT_KIND_CARD))
    return dp


build_game_dispatcher = build_digital_products_dispatcher
build_cards_dispatcher = build_card_ex_dispatcher


async def _resolve_main_bot_id() -> int | None:
    global _cached_main_bot_id
    if isinstance(_cached_main_bot_id, int) and _cached_main_bot_id > 0:
        return _cached_main_bot_id
    token = str(getattr(settings, "bot_main_token", "") or "").strip()
    if not token:
        return None
    bot = Bot(token=token, timeout=30)
    try:
        me = await bot.get_me()
        _cached_main_bot_id = int(me.id)
        return _cached_main_bot_id
    except Exception as exc:
        logging.error("failed to resolve main bot id: %s", exc)
        return None
    finally:
        with suppress(Exception):
            await bot.session.close()


async def _resolve_numbers_bot_id() -> int | None:
    global _cached_numbers_bot_id
    if isinstance(_cached_numbers_bot_id, int) and _cached_numbers_bot_id > 0:
        return _cached_numbers_bot_id
    token = str(getattr(settings, "bot_numbers_token", "") or "").strip()
    if not token:
        return None
    bot = Bot(token=token, timeout=30)
    try:
        me = await bot.get_me()
        _cached_numbers_bot_id = int(me.id)
        return _cached_numbers_bot_id
    except Exception as exc:
        logging.error("failed to resolve numbers bot id: %s", exc)
        return None
    finally:
        with suppress(Exception):
            await bot.session.close()


async def _resolve_admin_bot_id() -> int | None:
    global _cached_admin_bot_id
    if isinstance(_cached_admin_bot_id, int) and _cached_admin_bot_id > 0:
        return _cached_admin_bot_id
    token = str(getattr(settings, "bot_admin_token", "") or "").strip()
    if not token:
        return None
    bot = Bot(token=token, timeout=30)
    try:
        me = await bot.get_me()
        _cached_admin_bot_id = int(me.id)
        return _cached_admin_bot_id
    except Exception as exc:
        logging.error("failed to resolve admin bot id: %s", exc)
        return None
    finally:
        with suppress(Exception):
            await bot.session.close()


async def _resolve_digital_products_bot_id() -> int | None:
    token = str(getattr(settings, "bot_digital_products_token", "") or "").strip()
    if not token:
        return None
    bot = Bot(token=token, timeout=30)
    try:
        me = await bot.get_me()
        return int(me.id)
    except Exception as exc:
        logging.error("failed to resolve digital-products bot id: %s", exc)
        return None
    finally:
        with suppress(Exception):
            await bot.session.close()


async def _resolve_card_ex_bot_id() -> int | None:
    global _cached_card_ex_bot_id
    if isinstance(_cached_card_ex_bot_id, int) and _cached_card_ex_bot_id > 0:
        return _cached_card_ex_bot_id
    token = (
        str(getattr(settings, "bot_card_ex_token", "") or "").strip()
        or str(getattr(settings, "bot_cards_token", "") or "").strip()
    )
    if not token:
        return None
    bot = Bot(token=token, timeout=30)
    try:
        me = await bot.get_me()
        _cached_card_ex_bot_id = int(me.id)
        return _cached_card_ex_bot_id
    except Exception as exc:
        logging.error("failed to resolve card-ex bot id: %s", exc)
        return None
    finally:
        with suppress(Exception):
            await bot.session.close()


async def _fetch_verified_bot_maps() -> tuple[dict[int, str], dict[int, int], dict[int, str], dict[int, str], dict[int, str], dict[int, str]]:
    bots_data = await get_verified_bots()
    public_map: dict[int, str] = {}
    owner_map: dict[int, int] = {}
    main_map: dict[int, str] = {}
    numbers_map: dict[int, str] = {}
    digital_products_map: dict[int, str] = {}
    card_ex_map: dict[int, str] = {}
    seen_tokens: dict[str, int] = {}

    for item in bots_data:
        token = item.get("token")
        bot_id = item.get("bot_id")
        owner_id = item.get("owner_id")
        if not token or bot_id is None:
            continue

        try:
            bot_id_int = int(bot_id)
            token_str = str(token).strip()
            owner_id_int = int(owner_id)
        except Exception:
            logging.warning(
                "Skipping bot row with invalid ids/token shape: bot_id=%r owner_id=%r token_present=%s",
                bot_id,
                owner_id,
                bool(token),
            )
            continue

        if token_str in seen_tokens:
            logging.warning(
                "Skipping duplicate token for bot_id=%s (already mapped to bot_id=%s)",
                bot_id_int,
                seen_tokens[token_str],
            )
            continue

        public_map[bot_id_int] = token_str
        owner_map[bot_id_int] = owner_id_int
        seen_tokens[token_str] = bot_id_int

    main_token = str(getattr(settings, "bot_main_token", "") or "").strip()
    if main_token and main_token not in seen_tokens:
        main_bot_id = await _resolve_main_bot_id()
        if isinstance(main_bot_id, int) and main_bot_id > 0:
            main_map[main_bot_id] = main_token
            seen_tokens[main_token] = main_bot_id

    admin_token = str(getattr(settings, "bot_admin_token", "") or "").strip()
    if admin_token and admin_token not in seen_tokens:
        admin_bot_id = await _resolve_admin_bot_id()
        if isinstance(admin_bot_id, int) and admin_bot_id > 0:
            public_map[admin_bot_id] = admin_token
            owner_map[admin_bot_id] = int(getattr(settings, "owner_id", 0) or 0)
            seen_tokens[admin_token] = admin_bot_id

    numbers_token = str(getattr(settings, "bot_numbers_token", "") or "").strip()
    if numbers_token and numbers_token not in seen_tokens:
        numbers_bot_id = await _resolve_numbers_bot_id()
        if isinstance(numbers_bot_id, int) and numbers_bot_id > 0:
            numbers_map[numbers_bot_id] = numbers_token
            seen_tokens[numbers_token] = numbers_bot_id

    digital_products_token = str(getattr(settings, "bot_digital_products_token", "") or "").strip()
    if digital_products_token and digital_products_token not in seen_tokens:
        digital_products_bot_id = await _resolve_digital_products_bot_id()
        if isinstance(digital_products_bot_id, int) and digital_products_bot_id > 0:
            digital_products_map[digital_products_bot_id] = digital_products_token
            seen_tokens[digital_products_token] = digital_products_bot_id

    card_ex_token = str(getattr(settings, "bot_card_ex_token", "") or "").strip()
    if card_ex_token and card_ex_token not in seen_tokens:
        card_ex_bot_id = await _resolve_card_ex_bot_id()
        if isinstance(card_ex_bot_id, int) and card_ex_bot_id > 0:
            card_ex_map[card_ex_bot_id] = card_ex_token
            seen_tokens[card_ex_token] = card_ex_bot_id

    return public_map, owner_map, main_map, numbers_map, digital_products_map, card_ex_map


_resolve_game_bot_id = _resolve_digital_products_bot_id
_resolve_cards_bot_id = _resolve_card_ex_bot_id


async def _ensure_digital_store_menu_button(bot: Bot) -> None:
    if not bool(getattr(settings, "digital_products_miniapp_enabled", False)):
        return
    miniapp_url = _digital_store_webapp_url()
    if not miniapp_url:
        return
    with suppress(Exception):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="STORE",
                web_app=WebAppInfo(url=miniapp_url),
            )
        )


async def _start_polling_group(name: str, dp: Dispatcher, token_map: dict[int, str]) -> tuple[asyncio.Task[None] | None, list[Bot]]:
    if not token_map:
        return None, []
    bots = [Bot(token=t) for _, t in sorted(token_map.items())]

    for bot in bots:
        with suppress(Exception):
            await bot.delete_webhook(drop_pending_updates=False)
    if name == "digital-products":
        for bot in bots:
            await _ensure_digital_store_menu_button(bot)

    async def _runner() -> None:
        await dp.start_polling(*bots)

    task = asyncio.create_task(_runner(), name=f"polling-{name}")
    return task, bots


async def _stop_polling_group(dp: Dispatcher, task: asyncio.Task[None] | None, bots: list[Bot]) -> None:
    with suppress(Exception):
        await dp.stop_polling()

    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=8)
        except asyncio.TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logging.error("polling task stopped with error: %s", exc)

    for b in bots:
        with suppress(Exception):
            await b.session.close()


async def sync_bots_forever(poll_seconds: int = 20) -> None:
    public_dp = build_public_dispatcher()
    main_dp = build_main_dispatcher()
    numbers_dp = build_numbers_dispatcher()
    digital_products_dp = build_digital_products_dispatcher()
    card_ex_dp = build_card_ex_dispatcher()

    now = _utc_now()
    sched_state = _load_sched_state()
    last_financial_anomaly_at = _parse_utc_iso(sched_state.get("last_financial_anomaly_at"))
    last_digital_products_recovery_at = _parse_utc_iso(sched_state.get("last_digital_products_recovery_at"))
    last_proxy_ops_summary_at = _parse_utc_iso(sched_state.get("last_proxy_ops_summary_at"))
    last_proxy_validation_at = _parse_utc_iso(sched_state.get("last_proxy_validation_at"))
    last_proxy_catalog_refresh_at = _parse_utc_iso(sched_state.get("last_proxy_catalog_refresh_at"))
    last_digital_products_validation_at = _parse_utc_iso(sched_state.get("last_digital_products_validation_at"))
    last_lifecycle_cleanup_at = _parse_utc_iso(sched_state.get("last_lifecycle_cleanup_at"))
    last_bot_subscription_sweep_at = _parse_utc_iso(sched_state.get("last_bot_subscription_sweep_at"))

    current_public_map: dict[int, str] = {}
    current_main_map: dict[int, str] = {}
    current_numbers_map: dict[int, str] = {}
    current_digital_products_map: dict[int, str] = {}
    current_card_ex_map: dict[int, str] = {}
    current_owner_map: dict[int, int] = {}
    public_polling_task: asyncio.Task[None] | None = None
    main_polling_task: asyncio.Task[None] | None = None
    numbers_polling_task: asyncio.Task[None] | None = None
    digital_products_polling_task: asyncio.Task[None] | None = None
    card_ex_polling_task: asyncio.Task[None] | None = None
    running_public_bots: list[Bot] = []
    running_main_bots: list[Bot] = []
    running_numbers_bots: list[Bot] = []
    running_digital_products_bots: list[Bot] = []
    running_card_ex_bots: list[Bot] = []
    miniapp_runner = None
    next_proof_cleanup_at = now
    next_recovery_at = now
    next_provider_balance_alert_at = now
    next_rental_protection_at = now
    next_card_ex_release_at = now
    next_temp_recovery_sweep_at = now
    next_unprovisioned_order_recovery_at = now
    provider_balance_alert_state: dict[str, dict[str, Any]] = {}
    next_financial_anomaly_at = (
        now
        if last_financial_anomaly_at is None
        else max(
            now,
            last_financial_anomaly_at
            + timedelta(seconds=max(600, int(getattr(settings, "financial_anomaly_sweep_interval_sec", 21600) or 21600))),
        )
    )
    next_digital_products_recovery_at = (
        now
        if last_digital_products_recovery_at is None
        else max(
            now,
            last_digital_products_recovery_at
            + timedelta(
                seconds=max(
                    60,
                    int(
                        getattr(
                            settings,
                            "digital_products_recovery_sweep_interval_sec",
                            getattr(settings, "digital_products_recovery_sweep_interval_sec", 300),
                        )
                        or 300
                    ),
                )
            ),
        )
    )
    next_proxy_ops_summary_at = (
        now
        if last_proxy_ops_summary_at is None
        else max(
            now,
            last_proxy_ops_summary_at
            + timedelta(seconds=max(300, int(getattr(settings, "proxy_ops_summary_interval_sec", 3600) or 3600))),
        )
    )
    next_proxy_validation_at = (
        now
        if last_proxy_validation_at is None
        else max(
            now,
            last_proxy_validation_at
            + timedelta(seconds=max(900, int(getattr(settings, "proxy_validation_interval_sec", 21600) or 21600))),
        )
    )
    next_proxy_catalog_refresh_at = (
        now
        if last_proxy_catalog_refresh_at is None
        else max(
            now,
            last_proxy_catalog_refresh_at
            + timedelta(seconds=max(900, int(getattr(settings, "proxy_catalog_refresh_interval_sec", 3600) or 3600))),
        )
    )
    next_digital_products_validation_at = (
        now
        if last_digital_products_validation_at is None
        else max(
            now,
            last_digital_products_validation_at
            + timedelta(
                seconds=max(
                    900,
                    int(
                        getattr(
                            settings,
                            "digital_products_validation_interval_sec",
                            getattr(settings, "digital_products_validation_interval_sec", 21600),
                        )
                        or 21600
                    ),
                )
            ),
        )
    )
    next_lifecycle_cleanup_at = (
        now
        if last_lifecycle_cleanup_at is None
        else max(
            now,
            last_lifecycle_cleanup_at
            + timedelta(seconds=max(900, int(getattr(settings, "lifecycle_cleanup_interval_sec", 21600) or 21600))),
        )
    )
    next_bot_subscription_sweep_at = (
        now
        if last_bot_subscription_sweep_at is None
        else max(
            now,
            last_bot_subscription_sweep_at
            + timedelta(seconds=max(60, int(getattr(settings, "bot_subscription_sweep_interval_sec", 300) or 300))),
        )
    )

    try:
        miniapp_started = await start_miniapp_server()
        if miniapp_started is not None:
            miniapp_runner = miniapp_started[0]
            logging.info(
                "Digital-products mini app server started on %s:%s",
                getattr(settings, "digital_products_miniapp_host", "0.0.0.0"),
                getattr(settings, "digital_products_miniapp_port", 8080),
            )
        while True:
            try:
                (
                    latest_public_map,
                    latest_owner_map,
                    latest_main_map,
                    latest_numbers_map,
                    latest_digital_products_map,
                    latest_card_ex_map,
                ) = await _fetch_verified_bot_maps()
            except Exception as exc:
                logging.error("database query failed: %s", exc)
                await asyncio.sleep(poll_seconds)
                continue

            if latest_public_map != current_public_map:
                logging.info("Bot set changed. Restarting polling. bots=%s", list(latest_public_map.keys()))
                await _stop_polling_group(public_dp, public_polling_task, running_public_bots)
                public_polling_task = None
                running_public_bots = []
                current_public_map = latest_public_map
                current_owner_map = latest_owner_map

                if current_public_map:
                    public_polling_task, running_public_bots = await _start_polling_group("public", public_dp, current_public_map)
            else:
                current_owner_map = latest_owner_map

            if latest_main_map != current_main_map:
                logging.info("Main bot set changed. Restarting main polling. bots=%s", list(latest_main_map.keys()))
                await _stop_polling_group(main_dp, main_polling_task, running_main_bots)
                main_polling_task = None
                running_main_bots = []
                current_main_map = latest_main_map
                if current_main_map:
                    main_polling_task, running_main_bots = await _start_polling_group("main", main_dp, current_main_map)

            if latest_numbers_map != current_numbers_map:
                logging.info("Numbers bot set changed. Restarting numbers polling. bots=%s", list(latest_numbers_map.keys()))
                await _stop_polling_group(numbers_dp, numbers_polling_task, running_numbers_bots)
                numbers_polling_task = None
                running_numbers_bots = []
                current_numbers_map = latest_numbers_map
                if current_numbers_map:
                    numbers_polling_task, running_numbers_bots = await _start_polling_group("numbers", numbers_dp, current_numbers_map)

            if latest_digital_products_map != current_digital_products_map:
                logging.info("Digital-products bot set changed. Restarting digital-products polling. bots=%s", list(latest_digital_products_map.keys()))
                await _stop_polling_group(digital_products_dp, digital_products_polling_task, running_digital_products_bots)
                digital_products_polling_task = None
                running_digital_products_bots = []
                current_digital_products_map = latest_digital_products_map
                if current_digital_products_map:
                    digital_products_polling_task, running_digital_products_bots = await _start_polling_group("digital-products", digital_products_dp, current_digital_products_map)

            if latest_card_ex_map != current_card_ex_map:
                logging.info("Card-EX bot set changed. Restarting card-ex polling. bots=%s", list(latest_card_ex_map.keys()))
                await _stop_polling_group(card_ex_dp, card_ex_polling_task, running_card_ex_bots)
                card_ex_polling_task = None
                running_card_ex_bots = []
                current_card_ex_map = latest_card_ex_map
                if current_card_ex_map:
                    card_ex_polling_task, running_card_ex_bots = await _start_polling_group("card-ex", card_ex_dp, current_card_ex_map)

            if public_polling_task is not None and public_polling_task.done():
                err = None
                try:
                    err = public_polling_task.exception()
                except asyncio.CancelledError:
                    err = None
                except Exception as exc:
                    err = exc
                if err:
                    logging.error("Polling task crashed: %s", err)
                await _stop_polling_group(public_dp, public_polling_task, running_public_bots)
                public_polling_task = None
                running_public_bots = []
                if current_public_map:
                    public_polling_task, running_public_bots = await _start_polling_group("public", public_dp, current_public_map)

            if main_polling_task is not None and main_polling_task.done():
                err = None
                try:
                    err = main_polling_task.exception()
                except asyncio.CancelledError:
                    err = None
                except Exception as exc:
                    err = exc
                if err:
                    logging.error("Main polling task crashed: %s", err)
                await _stop_polling_group(main_dp, main_polling_task, running_main_bots)
                main_polling_task = None
                running_main_bots = []
                if current_main_map:
                    main_polling_task, running_main_bots = await _start_polling_group("main", main_dp, current_main_map)

            if numbers_polling_task is not None and numbers_polling_task.done():
                err = None
                try:
                    err = numbers_polling_task.exception()
                except asyncio.CancelledError:
                    err = None
                except Exception as exc:
                    err = exc
                if err:
                    logging.error("Numbers polling task crashed: %s", err)
                await _stop_polling_group(numbers_dp, numbers_polling_task, running_numbers_bots)
                numbers_polling_task = None
                running_numbers_bots = []
                if current_numbers_map:
                    numbers_polling_task, running_numbers_bots = await _start_polling_group("numbers", numbers_dp, current_numbers_map)

            if digital_products_polling_task is not None and digital_products_polling_task.done():
                err = None
                try:
                    err = digital_products_polling_task.exception()
                except asyncio.CancelledError:
                    err = None
                except Exception as exc:
                    err = exc
                if err:
                    logging.error("Digital-products polling task crashed: %s", err)
                await _stop_polling_group(digital_products_dp, digital_products_polling_task, running_digital_products_bots)
                digital_products_polling_task = None
                running_digital_products_bots = []
                if current_digital_products_map:
                    digital_products_polling_task, running_digital_products_bots = await _start_polling_group("digital-products", digital_products_dp, current_digital_products_map)

            if card_ex_polling_task is not None and card_ex_polling_task.done():
                err = None
                try:
                    err = card_ex_polling_task.exception()
                except asyncio.CancelledError:
                    err = None
                except Exception as exc:
                    err = exc
                if err:
                    logging.error("Card-EX polling task crashed: %s", err)
                await _stop_polling_group(card_ex_dp, card_ex_polling_task, running_card_ex_bots)
                card_ex_polling_task = None
                running_card_ex_bots = []
                if current_card_ex_map:
                    card_ex_polling_task, running_card_ex_bots = await _start_polling_group("card-ex", card_ex_dp, current_card_ex_map)

        if _utc_now() >= next_recovery_at:
            try:
                rec = await recover_stuck_processing_recharges(max_age_minutes=15, limit=500)
                if rec.get("recovered") or rec.get("requeued"):
                    logging.warning(
                        "recharge recovery scanned=%s recovered=%s requeued=%s",
                        rec.get("scanned"),
                        rec.get("recovered"),
                        rec.get("requeued"),
                    )
            except Exception as exc:
                logging.error("recharge recovery failed: %s", exc)
            finally:
                next_recovery_at = _utc_now() + timedelta(minutes=5)

        if _utc_now() >= next_proof_cleanup_at:
            try:
                purged = await purge_accepted_recharge_proofs(keep_hours=6, limit=1000)
                if purged:
                    logging.info("purged recharge proofs count=%s", purged)
            except Exception as exc:
                logging.error("recharge proof cleanup failed: %s", exc)
            finally:
                next_proof_cleanup_at = _utc_now() + timedelta(minutes=10)

        if _utc_now() >= next_provider_balance_alert_at:
            try:
                await _run_provider_balance_alert_cycle(
                    running_bots=running_public_bots,
                    current_owner_map=current_owner_map,
                    state=provider_balance_alert_state,
                )
            except Exception as exc:
                logging.error("provider balance alert cycle failed: %s", exc)
            finally:
                next_provider_balance_alert_at = _utc_now() + timedelta(minutes=5)

        if _utc_now() >= next_financial_anomaly_at:
            ran_at = _utc_now()
            sched_state["last_financial_anomaly_at"] = ran_at.isoformat()
            _save_sched_state(sched_state)
            interval_sec = max(600, int(getattr(settings, "financial_anomaly_sweep_interval_sec", 21600) or 21600))
            next_financial_anomaly_at = ran_at + timedelta(seconds=interval_sec)

        if _utc_now() >= next_digital_products_recovery_at:
            try:
                stats = await run_digital_products_pending_recovery_sweep(
                    limit=80,
                    pending_age_sec=max(
                        60,
                        int(
                            getattr(
                                settings,
                                "digital_products_recovery_pending_age_sec",
                                120,
                            )
                            or 120
                        ),
                    ),
                )
                if any(int(stats.get(k) or 0) for k in ("checked", "marked_success", "marked_refunded", "refund_failures")):
                    logging.info(
                        "digital-products recovery checked=%s marked_success=%s marked_refunded=%s pending=%s refund_failures=%s",
                        stats.get("checked"),
                        stats.get("marked_success"),
                        stats.get("marked_refunded"),
                        stats.get("pending"),
                        stats.get("refund_failures"),
                    )
            except Exception as exc:
                logging.error("digital-products recovery sweep failed: %s", exc)
            finally:
                ran_at = _utc_now()
                sched_state["last_digital_products_recovery_at"] = ran_at.isoformat()
                _save_sched_state(sched_state)
                interval_sec = max(
                    60,
                    int(
                        getattr(
                            settings,
                            "digital_products_recovery_sweep_interval_sec",
                            300,
                        )
                        or 300
                    ),
                )
                next_digital_products_recovery_at = ran_at + timedelta(seconds=interval_sec)

        if _utc_now() >= next_proxy_ops_summary_at:
            try:
                report = await summarize_proxy_events(hours=24)
                total = int(report.get("total") or 0)
                failed = int(report.get("failed") or 0)
                fail_rate = float(report.get("fail_rate_percent") or 0.0)
                logging.info(
                    "proxy ops summary total=%s failed=%s fail_rate=%.2f%%",
                    total,
                    failed,
                    fail_rate,
                )
                threshold = float(
                    getattr(settings, "proxy_ops_failure_alert_threshold_percent", 45.0) or 45.0
                )
                if total >= 20 and fail_rate >= threshold:
                    chat_id, thread_id = await _owner_target_for_balance_alert()
                    if isinstance(chat_id, int):
                        preferred_bot = await _pick_owner_bot(running_public_bots, current_owner_map)
                        reasons = report.get("top_reasons") or []
                        reasons_text = "\n".join(
                            f"- {str(item.get('reason') or 'unknown')}: {int(item.get('count') or 0)}"
                            for item in reasons[:4]
                        ) or "-"
                        alert_text = (
                            "Proxy operations alert (24h)\n\n"
                            f"Total events: {total}\n"
                            f"Failed: {failed}\n"
                            f"Fail rate: {fail_rate:.2f}%\n"
                            f"Threshold: {threshold:.2f}%\n\n"
                            f"Top reasons:\n{reasons_text}"
                        )
                        sent = await _send_owner_alert_via_any_bot(
                            running_bots=running_public_bots,
                            preferred_bot=preferred_bot,
                            chat_id=chat_id,
                            thread_id=thread_id,
                            text=alert_text,
                        )
                        if not sent:
                            logging.error("proxy ops alert send failed for all bots")
            except Exception as exc:
                logging.error("proxy ops summary failed: %s", exc)
            finally:
                ran_at = _utc_now()
                sched_state["last_proxy_ops_summary_at"] = ran_at.isoformat()
                _save_sched_state(sched_state)
                interval_sec = max(300, int(getattr(settings, "proxy_ops_summary_interval_sec", 3600) or 3600))
                next_proxy_ops_summary_at = ran_at + timedelta(seconds=interval_sec)

        if _utc_now() >= next_proxy_validation_at:
            try:
                report = await run_proxy_catalog_validation()
                issues = list(report.get("issues") or [])
                logging.info(
                    "proxy validation healthy=%s total_offers=%s issues=%s",
                    bool(report.get("healthy")),
                    int(report.get("total_offers") or 0),
                    len(issues),
                )
                if issues:
                    chat_id, thread_id = await _owner_target_for_balance_alert()
                    if isinstance(chat_id, int):
                        preferred_bot = await _pick_owner_bot(running_public_bots, current_owner_map)
                        text = (
                            "Proxy validation warning\n\n"
                            f"Total offers: {int(report.get('total_offers') or 0)}\n"
                            f"Issues: {len(issues)}\n"
                            + "\n".join(f"- {x}" for x in issues[:8])
                        )
                        await _send_owner_alert_via_any_bot(
                            running_bots=running_public_bots,
                            preferred_bot=preferred_bot,
                            chat_id=chat_id,
                            thread_id=thread_id,
                            text=text,
                        )
            except Exception as exc:
                logging.error("proxy validation sweep failed: %s", exc)
            finally:
                ran_at = _utc_now()
                sched_state["last_proxy_validation_at"] = ran_at.isoformat()
                _save_sched_state(sched_state)
                interval_sec = max(900, int(getattr(settings, "proxy_validation_interval_sec", 21600) or 21600))
                next_proxy_validation_at = ran_at + timedelta(seconds=interval_sec)

        if _utc_now() >= next_proxy_catalog_refresh_at:
            try:
                catalog = await get_proxy_catalog()
                set_offers_cache(catalog)
                logging.info("proxy catalog cache refreshed total=%s", len(catalog or []))
            except Exception as exc:
                logging.error("proxy catalog refresh failed: %s", exc)
            finally:
                ran_at = _utc_now()
                sched_state["last_proxy_catalog_refresh_at"] = ran_at.isoformat()
                _save_sched_state(sched_state)
                interval_sec = max(900, int(getattr(settings, "proxy_catalog_refresh_interval_sec", 3600) or 3600))
                next_proxy_catalog_refresh_at = ran_at + timedelta(seconds=interval_sec)

        if _utc_now() >= next_digital_products_validation_at:
            try:
                report = await run_digital_products_validation()
                issues = list(report.get("issues") or [])
                logging.info(
                    "digital-products validation healthy=%s games=%s gift_categories=%s issues=%s",
                    bool(report.get("healthy")),
                    int(report.get("games_count") or 0),
                    int(report.get("gift_categories_count") or 0),
                    len(issues),
                )
                if issues:
                    chat_id, thread_id = await _owner_target_for_balance_alert()
                    if isinstance(chat_id, int):
                        preferred_bot = await _pick_owner_bot(running_public_bots, current_owner_map)
                        text = (
                            "Digital products validation warning\n\n"
                            f"Games: {int(report.get('games_count') or 0)}\n"
                            f"Gift categories: {int(report.get('gift_categories_count') or 0)}\n"
                            f"Issues: {len(issues)}\n"
                            + "\n".join(f"- {x}" for x in issues[:8])
                        )
                        await _send_owner_alert_via_any_bot(
                            running_bots=running_public_bots,
                            preferred_bot=preferred_bot,
                            chat_id=chat_id,
                            thread_id=thread_id,
                            text=text,
                        )
            except Exception as exc:
                logging.error("digital-products validation sweep failed: %s", exc)
            finally:
                ran_at = _utc_now()
                sched_state["last_digital_products_validation_at"] = ran_at.isoformat()
                _save_sched_state(sched_state)
                interval_sec = max(
                    900,
                    int(
                        getattr(
                            settings,
                            "digital_products_validation_interval_sec",
                            21600,
                        )
                        or 21600
                    ),
                )
                next_digital_products_validation_at = ran_at + timedelta(seconds=interval_sec)

        if _utc_now() >= next_lifecycle_cleanup_at:
            try:
                cleanup = await run_lifecycle_cleanup(
                    telemetry_retention_days=max(
                        7, int(getattr(settings, "lifecycle_telemetry_retention_days", 30) or 30)
                    ),
                    number_events_retention_days=max(
                        7, int(getattr(settings, "lifecycle_number_events_retention_days", 120) or 120)
                    ),
                    usage_retention_days=max(
                        30, int(getattr(settings, "lifecycle_usage_retention_days", 180) or 180)
                    ),
                    order_archive_age_days=max(
                        30, int(getattr(settings, "lifecycle_order_archive_age_days", 120) or 120)
                    ),
                    archived_orders_retention_days=max(
                        90, int(getattr(settings, "lifecycle_orders_archive_retention_days", 365) or 365)
                    ),
                )
                logging.info(
                    "lifecycle cleanup proxy_events_deleted=%s number_events_deleted=%s usage_stats_deleted=%s orders_archived=%s orders_deleted_after_archive=%s archive_errors=%s",
                    int(cleanup.get("proxy_events_deleted") or 0),
                    int(cleanup.get("number_events_deleted") or 0),
                    int(cleanup.get("usage_stats_deleted") or 0),
                    int(cleanup.get("orders_archived") or 0),
                    int(cleanup.get("orders_deleted_after_archive") or 0),
                    int(cleanup.get("orders_archive_errors") or 0),
                )
            except Exception as exc:
                logging.error("lifecycle cleanup failed: %s", exc)
            finally:
                ran_at = _utc_now()
                sched_state["last_lifecycle_cleanup_at"] = ran_at.isoformat()
                _save_sched_state(sched_state)
                interval_sec = max(900, int(getattr(settings, "lifecycle_cleanup_interval_sec", 21600) or 21600))
                next_lifecycle_cleanup_at = ran_at + timedelta(seconds=interval_sec)

        if _utc_now() >= next_bot_subscription_sweep_at:
            try:
                report = await run_bot_subscription_sweep(
                    limit=max(50, int(getattr(settings, "bot_subscription_sweep_limit", 500) or 500))
                )
                await _run_bot_subscription_expiry_notice_cycle(
                    running_bots=running_public_bots,
                    current_owner_map=current_owner_map,
                    limit=max(50, int(getattr(settings, "bot_subscription_sweep_limit", 500) or 500)),
                )
                await _run_bot_subscription_notice_cycle(
                    running_bots=running_public_bots,
                    current_owner_map=current_owner_map,
                    limit=max(50, int(getattr(settings, "bot_subscription_sweep_limit", 500) or 500)),
                )
                if any(int(report.get(k) or 0) for k in ("renewed", "status_changed")):
                    logging.info(
                        "bot subscription sweep scanned=%s renewed=%s status_changed=%s",
                        int(report.get("scanned") or 0),
                        int(report.get("renewed") or 0),
                        int(report.get("status_changed") or 0),
                    )
            except Exception as exc:
                logging.error("bot subscription sweep failed: %s", exc)
            finally:
                ran_at = _utc_now()
                sched_state["last_bot_subscription_sweep_at"] = ran_at.isoformat()
                _save_sched_state(sched_state)
                interval_sec = max(60, int(getattr(settings, "bot_subscription_sweep_interval_sec", 300) or 300))
                next_bot_subscription_sweep_at = ran_at + timedelta(seconds=interval_sec)

        if _utc_now() >= next_rental_protection_at:
            try:
                sweep = await run_rental_protection_sweep(
                    limit=max(50, int(getattr(settings, "numbers_rental_sweep_limit", 200) or 200)),
                    alert_threshold_sec=max(
                        60,
                        int(getattr(settings, "numbers_rental_owner_alert_window_sec", 180) or 180),
                    ),
                )
                alerts = sweep.get("alerts") or []
                if alerts and running_public_bots:
                    chat_id, thread_id = await _owner_target_for_balance_alert()
                    if not isinstance(chat_id, int):
                        logging.warning("rental protection alert skipped: no owner-group target is configured")
                    else:
                        preferred_bot = await _pick_owner_bot(running_public_bots, current_owner_map)
                        for alert in alerts:
                            sent = await _send_owner_alert_via_any_bot(
                                running_bots=running_public_bots,
                                preferred_bot=preferred_bot,
                                chat_id=chat_id,
                                thread_id=thread_id,
                                text=str(alert.get("text") or "").strip(),
                            )
                            if not sent:
                                logging.error(
                                    "rental protection alert send failed for all bots: order_id=%s kind=%s",
                                    alert.get("order_id"),
                                    alert.get("kind"),
                                )
                if sweep.get("checked") or sweep.get("auto_cancelled") or sweep.get("synced_sms"):
                    logging.info(
                        "rental protection sweep checked=%s synced_sms=%s auto_cancelled=%s close_failures=%s alerts=%s",
                        sweep.get("checked"),
                        sweep.get("synced_sms"),
                        sweep.get("auto_cancelled"),
                        sweep.get("close_failures"),
                        len(alerts),
                    )
            except Exception as exc:
                logging.error("rental protection sweep failed: %s", exc)
            finally:
                interval_sec = max(30, int(getattr(settings, "numbers_rental_sweep_interval_sec", 60) or 60))
                next_rental_protection_at = _utc_now() + timedelta(seconds=interval_sec)

        if _utc_now() >= next_card_ex_release_at:
            try:
                stats = await release_due_cards(limit=200)
                if int(stats.get("released") or 0) > 0:
                    logging.info("card-ex release sweep released=%s", int(stats.get("released") or 0))
            except Exception as exc:
                logging.error("card-ex release sweep failed: %s", exc)
            finally:
                interval_sec = max(60, int(getattr(settings, "cardex_release_sweep_interval_sec", 600) or 600))
                next_card_ex_release_at = _utc_now() + timedelta(seconds=interval_sec)

        if _utc_now() >= next_temp_recovery_sweep_at:
            try:
                aggregate = {"checked": 0, "synced": 0, "code_received": 0, "timed_out": 0, "refund_retries": 0}
                limit = max(50, int(getattr(settings, "numbers_temp_recovery_sweep_limit", 200) or 200))
                for bot in running_main_bots:
                    stats = await run_temp_wait_recovery_sweep(bot=bot, limit=limit)
                    for key in aggregate.keys():
                        aggregate[key] += int(stats.get(key) or 0)
                if any(aggregate.values()):
                    logging.info(
                        "temp recovery sweep checked=%s synced=%s code_received=%s timed_out=%s refund_retries=%s",
                        aggregate.get("checked"),
                        aggregate.get("synced"),
                        aggregate.get("code_received"),
                        aggregate.get("timed_out"),
                        aggregate.get("refund_retries"),
                    )
            except Exception as exc:
                logging.error("temp recovery sweep failed: %s", exc)
            finally:
                interval_sec = max(
                    30,
                    int(getattr(settings, "numbers_temp_recovery_sweep_interval_sec", 60) or 60),
                )
                next_temp_recovery_sweep_at = _utc_now() + timedelta(seconds=interval_sec)

        if _utc_now() >= next_unprovisioned_order_recovery_at:
            try:
                stats = await run_unprovisioned_number_order_recovery_sweep(
                    limit=max(
                        20,
                        int(getattr(settings, "numbers_unprovisioned_order_recovery_limit", 100) or 100),
                    ),
                    grace_sec=max(
                        30,
                        int(getattr(settings, "numbers_unprovisioned_order_grace_sec", 120) or 120),
                    ),
                )
                if any(int(stats.get(key) or 0) for key in ("checked", "refunded", "refund_failures")):
                    logging.info(
                        "unprovisioned order recovery checked=%s refunded=%s refund_failures=%s skipped_recent=%s",
                        stats.get("checked"),
                        stats.get("refunded"),
                        stats.get("refund_failures"),
                        stats.get("skipped_recent"),
                    )
            except Exception as exc:
                logging.error("unprovisioned number order recovery failed: %s", exc)
            finally:
                interval_sec = max(
                    30,
                    int(getattr(settings, "numbers_unprovisioned_order_recovery_interval_sec", 60) or 60),
                )
                next_unprovisioned_order_recovery_at = _utc_now() + timedelta(seconds=interval_sec)

            await asyncio.sleep(poll_seconds)
    finally:
        if miniapp_runner is not None:
            with suppress(Exception):
                await miniapp_runner.cleanup()
        await _stop_polling_group(public_dp, public_polling_task, running_public_bots)
        await _stop_polling_group(main_dp, main_polling_task, running_main_bots)
        await _stop_polling_group(numbers_dp, numbers_polling_task, running_numbers_bots)
        await _stop_polling_group(digital_products_dp, digital_products_polling_task, running_digital_products_bots)
        await _stop_polling_group(card_ex_dp, card_ex_polling_task, running_card_ex_bots)


async def main() -> None:
    setup_logging()
    _acquire_single_instance_lock()
    ai_notes = enforce_openrouter_only_mode()
    for line in ai_notes:
        logging.warning("ai policy: %s", line)
    warnings = validate_runtime_security()
    for line in warnings:
        logging.warning("security warning: %s", line)
    init_sentry(service_name="bot_manager")
    telegram_error_handler = install_telegram_error_handler(bot_token=settings.bot_admin_token)
    await _run_startup_bootstraps()

    logging.info(
        "loaded settings: admin_token=%s main_token=%s numbers_token=%s smspool_key=%s herosms_key=%s smsman_key=%s",
        bool(settings.bot_admin_token),
        bool(settings.bot_main_token),
        bool(getattr(settings, "bot_numbers_token", "")),
        bool(settings.smspool_key),
        bool(settings.herosms_key),
        bool(settings.smsman_key),
    )

    try:
        poll_seconds = max(8, int(getattr(settings, "bot_sync_poll_seconds", 20) or 20))
        await sync_bots_forever(poll_seconds=poll_seconds)
    finally:
        if telegram_error_handler is not None:
            with suppress(Exception):
                await telegram_error_handler.aclose()
        await _close_admin_alert_bot()
        with suppress(Exception):
            await SessionManager.close()
        _release_single_instance_lock()


if __name__ == "__main__":
    try:
        if hasattr(asyncio, "WindowsSelectorEventLoopPolicy") and os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot manager stopped!")


