import asyncio
import atexit
import json
import logging
from datetime import UTC, datetime, timedelta
import os
from contextlib import suppress
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from aiogram import Bot, Dispatcher

from config import settings
from database.bots_repo import get_verified_bots
from database.custom_services_repo import bootstrap_custom_services_indexes
from database.user_repo import bootstrap_user_links_indexes
from database.financial_ledger import (
    bootstrap_financial_indexes,
    enforce_settlement_payment_policies,
    generate_monthly_settlement_drafts,
)
from database.recharge_repo import (
    bootstrap_recharge_indexes,
    purge_accepted_recharge_proofs,
    recover_stuck_processing_recharges,
)
from database.provider_balance_alert_repo import get_provider_balance_alert_settings
from database.bot_logs_repo import get_bot_logs_target
from database.number_events_repo import bootstrap_number_events_indexes
from database.temp_number_stats_repo import bootstrap_temp_number_stats_indexes
from handlers.custom_services import router as custom_services_router
from handlers.store_sections import router as store_sections_router
from handlers.language import router as language_base
from handlers.main_menu import router as main_menu_base
from handlers.reseller_recharge import router as reseller_recharge_router
from handlers.start import router as start_base
from handlers.subscription import router as subscription_base
from handlers.verify_reseller import router as verify_reseller_base
from middlewares.financial_compliance import FinancialComplianceMiddleware
from middlewares.interaction_lock import InteractionLockMiddleware
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
from utils.telegram_error_reporting import install_telegram_error_handler

_dispatcher_build_count = 0
_active_polling_task: asyncio.Task[None] | None = None
_admin_alert_bot: Bot | None = None
_LOCK_FILE = Path(gettempdir()) / "shop_project_bot_manager.lock"
_SCHED_STATE_FILE = Path(gettempdir()) / "shop_project_bot_manager.schedule.json"
_LOCK_ACQUIRED = False


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _month_key(dt: datetime) -> str:
    return f"{dt.year}-{dt.month:02d}"


def _previous_month_key(dt: datetime) -> str:
    first_day_current = datetime(dt.year, dt.month, 1)
    last_day_prev = first_day_current - timedelta(days=1)
    return _month_key(last_day_prev)


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
    for key in ("last_settlement_draft_at", "last_settlement_policy_at"):
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
    cfg = await get_provider_balance_alert_settings()
    chat_id = cfg.get("chat_id")
    thread_id = cfg.get("message_thread_id")
    if isinstance(chat_id, int):
        return int(chat_id), int(thread_id) if isinstance(thread_id, int) else None

    try:
        from database.mongo import db

        doc = await db.system_settings.find_one({"_id": "owner_notifications"})
        if doc and isinstance(doc.get("chat_id"), int):
            return int(doc["chat_id"]), int(doc.get("message_thread_id")) if isinstance(doc.get("message_thread_id"), int) else None
    except Exception:
        pass
    logs_target = await get_bot_logs_target()
    if logs_target and isinstance(logs_target.get("chat_id"), int):
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
    low_now: dict[str, float] = {}
    for code in provider_codes:
        provider = PROVIDERS.get(code)
        if provider is None or not hasattr(provider, "get_balance"):
            continue
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
        logging.error("provider balance alert skipped: no owner-group target is configured")
        return
    bot = await _pick_owner_bot(running_bots, current_owner_map)
    lines = [
        "Provider balance low alert",
        f"Threshold: {threshold:.2f}$",
        "",
    ]
    for code in sorted(should_alert.keys()):
        lines.append(f"- {code}: {float(should_alert[code]):.4f}$")
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
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    # Keep provider/network diagnostics but suppress per-request transport noise.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_dispatcher() -> Dispatcher:
    global _dispatcher_build_count
    _dispatcher_build_count += 1
    if _dispatcher_build_count > 1:
        msg = "Dispatcher singleton violated: attempted to build more than one Dispatcher in bot_manager process."
        logging.critical(msg)
        raise RuntimeError(msg)

    dp = Dispatcher()

    dp.message.middleware(InteractionLockMiddleware())
    dp.callback_query.middleware(InteractionLockMiddleware())

    dp.message.middleware(VersionCheckMiddleware())
    dp.callback_query.middleware(VersionCheckMiddleware())
    dp.message.middleware(FinancialComplianceMiddleware())
    dp.callback_query.middleware(FinancialComplianceMiddleware())

    dp.include_router(start_base)
    dp.include_router(proxy_inline_router)
    dp.include_router(numbers_inline_router)

    dp.include_router(language_base)
    dp.include_router(subscription_base)
    dp.include_router(main_menu_base)
    dp.include_router(store_sections_router)
    dp.include_router(proxy_flow_router)
    dp.include_router(verify_reseller_base)
    dp.include_router(reseller_recharge_router)
    dp.include_router(custom_services_router)

    dp.include_router(core_numbers_router)
    dp.include_router(core_numbers_buy_router)
    return dp


async def _fetch_verified_bot_maps() -> tuple[dict[int, str], dict[int, int]]:
    bots_data = await get_verified_bots()
    token_map: dict[int, str] = {}
    owner_map: dict[int, int] = {}
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

        token_map[bot_id_int] = token_str
        owner_map[bot_id_int] = owner_id_int
        seen_tokens[token_str] = bot_id_int

    return token_map, owner_map


async def _start_polling(dp: Dispatcher, token_map: dict[int, str]) -> tuple[asyncio.Task[None], list[Bot]]:
    global _active_polling_task
    if _active_polling_task is not None and not _active_polling_task.done():
        msg = "Polling singleton violated: attempted to start a second polling task before stopping the first one."
        logging.critical(msg)
        raise RuntimeError(msg)

    bots = [Bot(token=t) for _, t in sorted(token_map.items())]

    for bot in bots:
        with suppress(Exception):
            await bot.delete_webhook(drop_pending_updates=False)

    async def _runner() -> None:
        await dp.start_polling(*bots)

    task = asyncio.create_task(_runner(), name="polling-main")
    _active_polling_task = task
    return task, bots


async def _stop_polling(dp: Dispatcher, task: asyncio.Task[None] | None, bots: list[Bot]) -> None:
    global _active_polling_task

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
    _active_polling_task = None


async def sync_bots_forever(poll_seconds: int = 20) -> None:
    dp = build_dispatcher()

    now = _utc_now()
    sched_state = _load_sched_state()
    last_draft_at = _parse_utc_iso(sched_state.get("last_settlement_draft_at"))
    last_policy_at = _parse_utc_iso(sched_state.get("last_settlement_policy_at"))

    current_map: dict[int, str] = {}
    current_owner_map: dict[int, int] = {}
    polling_task: asyncio.Task[None] | None = None
    running_bots: list[Bot] = []
    next_proof_cleanup_at = now
    next_recovery_at = now
    next_provider_balance_alert_at = now
    next_rental_protection_at = now
    next_temp_recovery_sweep_at = now
    next_unprovisioned_order_recovery_at = now
    provider_balance_alert_state: dict[str, dict[str, Any]] = {}
    next_settlement_draft_at = now if last_draft_at is None else max(now, last_draft_at + timedelta(hours=6))
    next_settlement_policy_at = now if last_policy_at is None else max(now, last_policy_at + timedelta(hours=1))

    while True:
        try:
            latest_map, latest_owner_map = await _fetch_verified_bot_maps()
        except Exception as exc:
            logging.error("database query failed: %s", exc)
            await asyncio.sleep(poll_seconds)
            continue

        if latest_map != current_map:
            logging.info("Bot set changed. Restarting polling. bots=%s", list(latest_map.keys()))
            await _stop_polling(dp, polling_task, running_bots)
            polling_task = None
            running_bots = []
            current_map = latest_map
            current_owner_map = latest_owner_map

            if current_map:
                polling_task, running_bots = await _start_polling(dp, current_map)
        else:
            current_owner_map = latest_owner_map

        if polling_task is not None and polling_task.done():
            err = None
            try:
                err = polling_task.exception()
            except asyncio.CancelledError:
                err = None
            except Exception as exc:
                err = exc
            if err:
                logging.error("Polling task crashed: %s", err)
            await _stop_polling(dp, polling_task, running_bots)
            polling_task = None
            running_bots = []
            if current_map:
                polling_task, running_bots = await _start_polling(dp, current_map)

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

        if _utc_now() >= next_settlement_draft_at:
            now = _utc_now()
            target_cycle = _previous_month_key(now)
            try:
                draft_stats = await generate_monthly_settlement_drafts(cycle_key=target_cycle)
                logging.info(
                    "settlement drafts cycle=%s total=%s drafted=%s skipped_confirmed=%s",
                    draft_stats.get("cycle_key"),
                    draft_stats.get("total"),
                    draft_stats.get("drafted"),
                    draft_stats.get("skipped_confirmed"),
                )
            except Exception as exc:
                logging.error("settlement draft generation failed: %s", exc)
            finally:
                ran_at = _utc_now()
                sched_state["last_settlement_draft_at"] = ran_at.isoformat()
                _save_sched_state(sched_state)
                next_settlement_draft_at = ran_at + timedelta(hours=6)

        if _utc_now() >= next_settlement_policy_at:
            now = _utc_now()
            target_cycle = _previous_month_key(now)
            try:
                policy = await enforce_settlement_payment_policies(cycle_key=target_cycle, grace_days=4)
                notices = policy.get("notices") or []
                if notices and running_bots:
                    bot_by_owner: dict[int, Bot] = {}
                    for b in running_bots:
                        me = await b.get_me()
                        owner_id = current_owner_map.get(int(me.id))
                        if owner_id is not None and owner_id not in bot_by_owner:
                            bot_by_owner[int(owner_id)] = b

                    for notice in notices:
                        reseller_id = int(notice.get("reseller_id") or 0)
                        bot_for_reseller = bot_by_owner.get(reseller_id)
                        if not bot_for_reseller:
                            continue
                        due_at = notice.get("payment_due_at")
                        due_txt = due_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(due_at, "strftime") else "-"
                        amount_due = float(notice.get("amount_due") or 0.0)
                        if notice.get("kind") == "cycle_end":
                            txt = (
                                "Monthly cycle ended.\n\n"
                                f"Cycle: {notice.get('cycle_key')}\n"
                                f"Reseller ID: {reseller_id}\n"
                                f"Amount due: {amount_due:.2f}$\n"
                                f"Payment deadline: {due_txt}\n\n"
                                "Grace period is 4 days from cycle end.\n"
                                "If payment is not confirmed by the deadline, all services will be suspended.\n"
                                "Owner action path: Owner Panel -> Settlements -> Confirm Payment."
                            )
                        else:
                            txt = (
                                "Monthly payment is overdue.\n\n"
                                f"Cycle: {notice.get('cycle_key')}\n"
                                f"Reseller ID: {reseller_id}\n"
                                f"Amount due: {amount_due:.2f}$\n"
                                f"Deadline passed: {due_txt}\n\n"
                                "All services are now suspended until full payment is confirmed by the owner.\n"
                                "Ask the owner to confirm payment from the settlements panel."
                            )
                        with suppress(Exception):
                            await bot_for_reseller.send_message(chat_id=reseller_id, text=txt)

                logging.info(
                    "settlement policy cycle=%s checked=%s locked_now=%s notices=%s",
                    policy.get("cycle_key"),
                    policy.get("count"),
                    policy.get("locked_now"),
                    len(policy.get("notices") or []),
                )
            except Exception as exc:
                logging.error("settlement payment policy failed: %s", exc)
            finally:
                ran_at = _utc_now()
                sched_state["last_settlement_policy_at"] = ran_at.isoformat()
                _save_sched_state(sched_state)
                next_settlement_policy_at = ran_at + timedelta(hours=1)

        if _utc_now() >= next_provider_balance_alert_at:
            try:
                await _run_provider_balance_alert_cycle(
                    running_bots=running_bots,
                    current_owner_map=current_owner_map,
                    state=provider_balance_alert_state,
                )
            except Exception as exc:
                logging.error("provider balance alert cycle failed: %s", exc)
            finally:
                next_provider_balance_alert_at = _utc_now() + timedelta(minutes=5)

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
                if alerts and running_bots:
                    chat_id, thread_id = await _owner_target_for_balance_alert()
                    if not isinstance(chat_id, int):
                        logging.error("rental protection alert skipped: no owner-group target is configured")
                    else:
                        preferred_bot = await _pick_owner_bot(running_bots, current_owner_map)
                        for alert in alerts:
                            sent = await _send_owner_alert_via_any_bot(
                                running_bots=running_bots,
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

        if _utc_now() >= next_temp_recovery_sweep_at:
            try:
                aggregate = {"checked": 0, "synced": 0, "code_received": 0, "timed_out": 0, "refund_retries": 0}
                limit = max(50, int(getattr(settings, "numbers_temp_recovery_sweep_limit", 200) or 200))
                for bot in running_bots:
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


async def main() -> None:
    setup_logging()
    _acquire_single_instance_lock()
    telegram_error_handler = install_telegram_error_handler(bot_token=settings.bot_admin_token)
    await bootstrap_financial_indexes()
    await bootstrap_custom_services_indexes()
    await bootstrap_recharge_indexes()
    await bootstrap_user_links_indexes()
    await bootstrap_temp_number_stats_indexes()
    await bootstrap_number_events_indexes()

    logging.info(
        "loaded settings: admin_token=%s main_token=%s smspool_key=%s herosms_key=%s smsman_key=%s",
        bool(settings.bot_admin_token),
        bool(settings.bot_main_token),
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
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot manager stopped!")


