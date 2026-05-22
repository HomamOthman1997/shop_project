import asyncio
import html
import logging
import re
from contextvars import ContextVar
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import BaseMiddleware, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from bson import ObjectId

from config import settings
from database import reservations_repo
from database import temp_number_stats_repo
from database import number_events_repo
from database.orders_repo import (
    create_order,
    extract_order_amounts,
    get_order,
    list_open_rental_orders_without_sms,
    list_open_temp_orders_for_recovery,
    list_paid_number_orders_missing_provider,
    list_user_open_temp_and_voice_orders,
    list_user_open_temp_orders,
    list_user_open_rental_orders_without_sms,
    list_user_rental_orders,
    update_order_details,
    update_order_status,
)
from database.user_repo import get_user
from database.financial_ledger import get_user_wallet_balance
from services.numbers.shared.temp_order import (
    TEMP_CANCEL_AFTER_SEC,
    TEMP_POLL_INTERVALS,
    TEMP_PROVIDER_SAFETY_BUFFER_SEC,
    TEMP_REFRESH_COOLDOWN_SEC,
    TEMP_REFUND_RETRY_WINDOW_SEC,
    TEMP_REUSE_WARRANTY_FALLBACK_SEC,
    TEMP_REUSE_WARRANTY_SEC_BY_PROVIDER,
    TEMP_WAIT_TIMEOUT_SEC,
    _as_float,
    _as_int,
    _bool_text,
    _clean_provider_error_text,
    _coerce_utc_datetime,
    _country_display_name,
    _extract_explicit_reuse_warranty_sec,
    _extract_new_sms_code,
    _extract_provider_wait_timeout_sec,
    _format_number_for_copy_html,
    _format_number_for_copy_text,
    _format_wait_time_short,
    _is_expected_provider_failure,
    _is_retryable_provider_cancel,
    _is_temp_order_active_for_trust_gate,
    _normalize_warranty_sec,
    _order_reuse_warranty_sec,
    _order_temp_timeout_sec,
    _parse_provider_dt,
    _poll_interval_for_provider,
    _provider_default_reuse_warranty_sec,
    _provider_error_text,
    _resolve_reuse_warranty_sec,
    _safe_code_text,
    _seconds_between,
    _seconds_from_text,
    _seconds_left_until,
    _seconds_until_timestamp,
    _split_number_for_copy,
    _temp_code_received_text,
    _temp_elapsed_sec,
    _temp_order_has_received_code,
    _temp_refresh_cooldown_left,
    _temp_reuse_policy_text,
    _temp_waiting_text,
    _to_utc_datetime,
    _utc_now,
    _warranty_minutes_text_value,
)
from services.numbers.shared.rental_policy import (
    HERO_RENTAL_CANCEL_WINDOW_SEC,
    RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC,
    _is_within_hero_rental_cancel_window as _policy_is_within_hero_rental_cancel_window,
    _rental_deadline_at as _policy_rental_deadline_at,
    _rental_no_sms_yet,
    _rental_protection_policy as _policy_rental_protection_policy,
    _rental_safe_cutoff_at as _policy_rental_safe_cutoff_at,
)
from services.numbers.shared.provider_io import (
    fetch_provider_sms as _fetch_provider_sms_impl,
    provider_resend as _provider_resend_impl,
)
from services.numbers.shared.temp_refund import (
    cancel_and_refund_temp_order as _shared_cancel_and_refund_temp_order,
)
from services.numbers.shared.temp_second_code import request_second_code_for_order as _shared_request_second_code_for_order
from services.numbers.shared.temp_replacement import (
    pick_retry_provider as _shared_pick_retry_provider,
    provider_retry_score as _shared_provider_retry_score,
    temp_replacement_fields as _shared_temp_replacement_fields,
)
from services.numbers.handlers.temp_waiter_runtime import (
    queue_temp_waiter as _queue_temp_waiter_impl,
    send_temp_timeout_state as _send_temp_timeout_state_impl,
    start_temp_waiter as _start_temp_waiter_impl,
)
from services.numbers.handlers.recovery_runtime import (
    run_temp_wait_recovery_sweep as _run_temp_wait_recovery_sweep_impl,
    run_unprovisioned_number_order_recovery_sweep as _run_unprovisioned_number_order_recovery_sweep_impl,
)
from services.numbers.shared.events import (
    _log_number_event_from_order as _log_number_event_from_order_impl,
    _log_rental_event as _log_rental_event_impl,
    _log_temp_event as _log_temp_event_impl,
    _number_event_context_from_order as _number_event_context_from_order_impl,
)
from services.numbers.keyboards.core_numbers_kb import (
    confirm_buy_kb,
    provider_choice_kb,
    temp_code_received_kb,
    temp_wait_timeout_kb,
    rental_confirm_kb,
    rental_providers_kb,
    rental_warning_kb,
    service_kb,
    tv_renewable_kb,
)
from services.numbers.manager import (
    PROVIDERS,
    buy_number_from_provider,
    finish_rental_from_provider,
    get_all_prices,
    get_calls_from_provider,
    get_recording_from_provider,
    get_rental_info_from_provider,
    get_rental_sms_from_provider,
    notes_tags_from_provider,
    rent_number_from_provider,
    renew_rental_from_provider,
    wake_rental_from_provider,
)
from services.numbers.states.core_numbers_states import NumberFlow
from utils.financial_manager import FinancialManager
from utils.bot_menu_context import menu_for_current_bot
from utils.core_service_guard import finance_error_public_text
from utils.provider_alias import provider_generic_error, provider_public_id
from utils.translations import t
from utils.user_money import format_usd

logger = logging.getLogger("numbers_buy")
router = Router()
_CURRENT_CALLBACK: ContextVar[types.CallbackQuery | None] = ContextVar("core_numbers_buy_current_callback", default=None)


class _CallbackContextMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        token = _CURRENT_CALLBACK.set(event if isinstance(event, types.CallbackQuery) else None)
        try:
            return await handler(event, data)
        finally:
            _CURRENT_CALLBACK.reset(token)


router.callback_query.middleware(_CallbackContextMiddleware())

TEMP_REFUND_RETRY_INTERVAL_SEC = 45
RENTAL_OWNER_ALERT_WINDOW_SEC = 180
TEMP_MY_NUMBERS_RETENTION_DAYS = 5
_HIDDEN_TEMP_PROVIDER_CODES = {"smsman", "smsman_s6"}


def _main_reseller_bot_link() -> str | None:
    username = str(settings.main_bot_username or "").strip().lstrip("@")
    if not username:
        return None
    return f"https://t.me/{username}"


def _rental_provider_period_title(lang: str) -> str:
    return t(lang, "rental_provider_period_title_short")


def _rental_server_warning_lines(lang: str) -> list[str]:
    return [
        t(lang, "numbers_important_notice"),
        t(lang, "numbers_server1_state_notice"),
        t(lang, "numbers_server2_state_notice"),
    ]


def _numbers_provider_block_reason_text(lang: str, reason: str | None) -> str:
    code = str(reason or "").strip().lower()
    if code == "provider_balance_low":
        return t(lang, "numbers_provider_reason_balance_low")
    if code == "provider_balance_unknown":
        return t(lang, "numbers_provider_reason_balance_unknown")
    if code in {"service_not_supported", "rental_not_supported"}:
        return t(lang, "numbers_provider_reason_not_supported")
    if code in {"provider_timeout", "provider_error", "price_fetch_failed"}:
        return t(lang, "numbers_provider_reason_temporary")
    return t(lang, "numbers_testing_only_provider")


def _rental_refund_warning_kind(
    provider_code: str | None,
    selected_option: dict | None = None,
) -> str:
    option = selected_option or {}
    explicit_kind = str(
        option.get("refund_warning_kind")
        or option.get("refund_policy_kind")
        or option.get("refund_class")
        or ""
    ).strip().lower()
    if explicit_kind in {"protected", "uncertain", "non_refundable"}:
        return explicit_kind
    if bool(option.get("refund_known_false") or option.get("provider_can_refund") is False):
        return "non_refundable"
    if option.get("provider_can_refund") is True:
        return "protected"
    if option.get("refund_refundable_until") not in (None, ""):
        return "protected"
    code = str(provider_code or "").strip().lower()
    if code == "herosms":
        # HeroSMS rentals follow the protected close/cancel path in current policy.
        return "protected"
    if code == "smspool":
        # SMSPool exposes the actual refundability window after reservation creation.
        return "uncertain"
    if code == "textverified":
        # TextVerified exposes refundability per reservation/order response, not at price-list time.
        return "uncertain"
    return "uncertain"


def _rental_refund_warning_text(
    lang: str,
    *,
    provider_code: str | None,
    selected_option: dict | None = None,
    data: dict | None = None,
) -> str:
    data = data or {}
    provider_label = provider_public_id(provider_code)
    kind = _rental_refund_warning_kind(provider_code, selected_option)
    option = selected_option or {}
    heading_map = {
        "protected": t(lang, "rental_refund_heading_protected"),
        "uncertain": t(lang, "rental_refund_heading_uncertain"),
        "non_refundable": t(lang, "rental_refund_heading_non_refundable"),
    }
    body_map = {
        "protected": t(lang, "rental_refund_body_protected"),
        "uncertain": t(lang, "rental_refund_body_uncertain"),
        "non_refundable": t(lang, "rental_refund_body_non_refundable"),
    }
    footer = t(lang, "confirm_purchase_question")
    context_lines = [
        f"{t(lang, 'service_label')}: {data.get('service') or option.get('service_id') or '-'}",
        f"{t(lang, 'country_label')}: {_country_display_name(option.get('country') or data.get('country'), country_name=option.get('country_name'))}",
    ]
    state_code = str(option.get("state_code") or data.get("state") or "").strip()
    if state_code:
        context_lines.append(f"{t(lang, 'state_label')}: {t(lang, 'state_any') if state_code.lower() == 'none' else state_code}")
    context_lines.append(f"{t(lang, 'provider_label')}: {provider_label}")
    return "\n".join(
        [
            heading_map[kind],
            "",
            *context_lines,
            "",
            body_map[kind],
            "",
            footer,
        ]
    )


def _rental_confirm_text(lang: str, data: dict, selected_option: dict) -> str:
    duration_text = _duration_text(selected_option, lang)
    renewable = bool(selected_option.get("tv_is_renewable"))
    billing_cycle = str(selected_option.get("rental_billing_cycle_label") or "-")
    if not renewable:
        billing_cycle = "-"
    provider_code = str(selected_option.get("provider") or data.get("selected_rental_provider") or "").strip().lower()
    refund_kind = _rental_refund_warning_kind(provider_code, selected_option)
    refund_status_map = {
        "protected": t(lang, "rental_refund_status_protected"),
        "uncertain": t(lang, "rental_refund_status_uncertain"),
        "non_refundable": t(lang, "rental_refund_status_non_refundable"),
    }
    refund_body_map = {
        "protected": t(lang, "rental_refund_body_protected"),
        "uncertain": t(lang, "rental_refund_body_uncertain"),
        "non_refundable": t(lang, "rental_refund_body_non_refundable"),
    }
    state_code = str(selected_option.get("state_code") or data.get("state") or "").strip()
    lines = [
        f"{t(lang, 'service_label')}: {data.get('service')}",
        f"{t(lang, 'country_label')}: {_country_display_name(selected_option.get('country'), country_name=selected_option.get('country_name'))}",
    ]
    if state_code:
        state_label = t(lang, "state_any") if state_code.lower() == "none" else state_code
        lines.append(f"{t(lang, 'state_label')}: {state_label}")
    if provider_code:
        lines.append(f"{t(lang, 'provider_label')}: {provider_public_id(provider_code)}")
    lines.extend(
        [
            "",
            f"{t(lang, 'rental_duration_label')}: {duration_text}",
            f"{t(lang, 'rental_renewable_label')}: {_bool_text(renewable, lang)}",
            f"{t(lang, 'rental_billing_cycle_label')}: {billing_cycle}",
            f"{t(lang, 'price_label')}: {format_usd(float(selected_option.get('price', 0)))}",
            f"{t(lang, 'refund_status_label')}: {refund_status_map.get(refund_kind, t(lang, 'rental_refund_status_uncertain'))}",
            "",
            *_rental_server_warning_lines(lang),
            "",
            t(lang, "important_notice_label"),
            refund_body_map.get(refund_kind, t(lang, "rental_refund_body_uncertain")),
            "",
            t(lang, "confirm_purchase_question"),
        ]
    )
    return "\n".join(lines)


def _purchase_refunded_notice_text(lang: str, *, amount: float, balance: float) -> str:
    return t(lang, "numbers_purchase_refunded_notice").format(amount=float(amount), balance=float(balance))


def _purchase_charge_confirmed_notice_text(lang: str, *, amount: float, balance: float) -> str:
    return t(lang, "numbers_purchase_charge_confirmed_notice").format(amount=float(amount), balance=float(balance))


def _order_bot_id(order: dict | None) -> int | None:
    order = order or {}
    raw = order.get("telegram_bot_id")
    try:
        if raw is None:
            return None
        return int(raw)
    except Exception:
        return None


def _rental_manage_kb(order_id: str, lang: str, can_renew: bool = False, back_callback: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t(lang, "rental_btn_sms"), callback_data=f"rent:sms:{order_id}")],
        [InlineKeyboardButton(text=t(lang, "rental_btn_finish"), callback_data=f"rent:finish:{order_id}")],
    ]
    if can_renew:
        rows.append([InlineKeyboardButton(text=t(lang, "rental_btn_renew"), callback_data=f"rent:renew:{order_id}")])
    rows.append([InlineKeyboardButton(text=t(lang, "rental_btn_wake"), callback_data=f"rent:wake:{order_id}")])
    rows.append([InlineKeyboardButton(text=t(lang, "rental_btn_notes"), callback_data=f"rent:notes:{order_id}")])
    if back_callback:
        rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _rental_result_kb(order_id: str, lang: str, can_renew: bool = False) -> InlineKeyboardMarkup:
    kb = _rental_manage_kb(order_id=order_id, lang=lang, can_renew=can_renew)
    return kb


def _rental_exit_guard_kb(order_scope: str, *, target: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "numbers_keep_number"), callback_data=f"rentguard:keep:{target}:{order_scope}", style="primary")],
            [InlineKeyboardButton(text=t(lang, "temp_cancel_refund"), callback_data=f"rentguard:cancel:{target}:{order_scope}", style="danger")],
        ]
    )


def _rental_exit_guard_text(lang: str, provider_code: str, active_count: int = 1) -> str:
    provider_label = provider_public_id(provider_code)
    count = max(1, int(active_count or 1))
    if count > 1:
        return t(lang, "rental_exit_guard_many").format(count=count, provider=provider_label)
    return t(lang, "rental_exit_guard_one").format(provider=provider_label)


def _rental_auto_cancelled_notice(lang: str, count: int) -> str:
    return t(lang, "rental_auto_cancelled_refunded_notice").format(count=max(1, int(count or 1)))


def _rental_cancelled_notice(lang: str, count: int) -> str:
    return t(lang, "rental_cancelled_refunded_many_notice").format(count=max(1, int(count or 1)))


def _rental_close_failed_alert_text(order_id: Any, provider_label: str, user_id: Any, reason: str) -> str:
    return t("en", "rental_close_failed_alert_text").format(
        order_id=order_id,
        provider=provider_label,
        user_id=user_id,
        reason=reason,
    )


def _rental_near_cutoff_alert_text(order_id: Any, provider_label: str, user_id: Any, deadline: str, seconds_left: int) -> str:
    return t("en", "rental_near_cutoff_alert_text").format(
        order_id=order_id,
        provider=provider_label,
        user_id=user_id,
        deadline=deadline,
        seconds_left=seconds_left,
    )


def _provider_info_alert_text(lang: str, provider_code: str, info: dict[str, Any]) -> str:
    info = info or {}
    lines = [f"{t(lang, 'provider_label')}: {provider_public_id(provider_code)}"]
    provider_country_iso = str(info.get("provider_country_iso") or "").strip().upper()
    provider_state_code = str(info.get("provider_state_code") or "").strip().upper()
    if provider_state_code:
        lines.append(f"{t(lang, 'state_label')}: {provider_state_code}")
    elif provider_country_iso:
        lines.append(f"{t(lang, 'country_label')}: {provider_country_iso}")
    try:
        price_val = float(info.get("price") or 0)
    except Exception:
        price_val = 0.0
    if price_val > 0:
        lines.append(f"{t(lang, 'price_label')}: {format_usd(price_val)}")
    success_rate = info.get("success_rate")
    attempts = int(info.get("success_attempts") or 0)
    rate_text = "-" if attempts < 1 else f"{float(success_rate or 0):.0f}%"
    lines.append(f"{t(lang, 'success_rate_short')}: {rate_text}")
    api_service = str(info.get("api_service_name") or "").strip()
    if api_service:
        lines.append(f"API: {api_service}")
    if not bool(info.get("available_for_buy", True)):
        reason = str(info.get("provider_reason") or "").strip()
        if reason:
            lines.append(reason)
    return "\n".join(lines)


def _rental_provider_info_alert_text(lang: str, provider_code: str, options: list[dict], summary: dict | None = None) -> str:
    summary = summary or {}
    lines = [f"{t(lang, 'provider_label')}: {provider_public_id(provider_code)}"]
    durations: list[str] = []
    for row in options or []:
        try:
            dur = int(row.get("duration") or 0)
        except Exception:
            dur = 0
        if dur <= 0:
            continue
        label = str(row.get("duration_label") or _duration_text({"duration": dur}, lang)).strip()
        if label and label not in durations:
            durations.append(label)
    if durations:
        lines.append(f"{t(lang, 'provider_duration')}: {', '.join(durations[:6])}")
    try:
        avg_price = float(summary.get('avg_price') or 0)
    except Exception:
        avg_price = 0.0
    if avg_price > 0:
        lines.append(f"{t(lang, 'price_label')}: {format_usd(avg_price)}")
    return "\n".join(lines)


async def _return_to_main_menu_from_buy(callback: types.CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.clear()
    if not callback.message:
        return
    bot_id = (await callback.bot.get_me()).id
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(t(lang, "main_menu"), reply_markup=await menu_for_current_bot(lang, bot_id))


async def _show_main_menu_message(message: types.Message, lang: str) -> None:
    bot_id = (await message.bot.get_me()).id
    await message.answer(t(lang, "main_menu"), reply_markup=await menu_for_current_bot(lang, bot_id))


async def _show_purchase_failed_then_main_menu(
    message: types.Message,
    state: FSMContext,
    lang: str,
) -> None:
    await _best_effort_edit_text(
        message,
        t(lang, "purchase_failed").format(error=provider_generic_error(lang)),
    )
    try:
        await state.clear()
    except Exception as exc:
        logger.warning("Failed to clear number purchase state after provider failure: %s", exc)
    try:
        await _show_main_menu_message(message, lang)
    except Exception as exc:
        logger.warning("Failed to show main menu after provider failure: %s", exc)


async def _return_after_rental_exit_message(
    message: types.Message,
    state: FSMContext,
    *,
    target: str,
    lang: str,
) -> None:
    await state.clear()
    await _show_main_menu_message(message, lang)


async def _return_after_rental_exit_callback(
    callback: types.CallbackQuery,
    state: FSMContext,
    *,
    target: str,
    lang: str,
) -> None:
    await _return_to_main_menu_from_buy(callback, state, lang)


async def _user_open_rentals_without_sms(user_id: int) -> list[dict]:
    orders = await list_user_open_rental_orders_without_sms(int(user_id), limit=20)
    return [order for order in orders if _rental_no_sms_yet(order)]


async def _cancel_and_refund_rental_orders(
    *,
    orders: list[dict],
    actor_user_id: int,
    reason: str,
) -> dict[str, Any]:
    success_count = 0
    sms_received_count = 0
    failed_count = 0
    results: list[dict[str, Any]] = []
    for order in orders:
        order_id = order.get("_id")
        if not order_id:
            continue
        result = await _cancel_and_refund_rental_order(
            order_id=order_id,
            order=order,
            actor_user_id=int(actor_user_id),
            reason=reason,
            require_no_sms=True,
        )
        results.append({"order_id": str(order_id), **result})
        if result.get("success"):
            success_count += 1
        elif result.get("reason") == "sms_received":
            sms_received_count += 1
        else:
            failed_count += 1
    return {
        "success_count": success_count,
        "sms_received_count": sms_received_count,
        "failed_count": failed_count,
        "results": results,
    }


async def _handle_rental_exit_message_guard(
    message: types.Message,
    state: FSMContext,
    *,
    target: str,
    lang: str,
) -> bool:
    orders = await _user_open_rentals_without_sms(message.from_user.id)
    if not orders:
        return False
    refreshed_orders: list[dict] = []
    for order in orders:
        provider_code = str(order.get("provider") or "").strip().lower()
        if provider_code in {"textverified", "smspool"}:
            await _sync_rental_protection_snapshot(order.get("_id"), order)
            refreshed_orders.append(await get_order(order.get("_id")) or order)
        else:
            refreshed_orders.append(order)
    orders = [order for order in refreshed_orders if _rental_no_sms_yet(order)]
    if not orders:
        await _return_after_rental_exit_message(message, state, target=target, lang=lang)
        return True

    now_dt = _utc_now()
    due_orders = [order for order in orders if (_rental_safe_cutoff_at(order) and now_dt >= _rental_safe_cutoff_at(order))]
    if due_orders:
        result = await _cancel_and_refund_rental_orders(
            orders=due_orders,
            actor_user_id=int(message.from_user.id),
            reason=f"exit_guard_{target}_cutoff",
        )
        if result.get("success_count"):
            notice = _rental_auto_cancelled_notice(lang, int(result.get("success_count") or 0))
            await message.answer(notice)
        orders = await _user_open_rentals_without_sms(message.from_user.id)
        if not orders:
            await _return_after_rental_exit_message(message, state, target=target, lang=lang)
            return True

    await message.answer(
        _rental_exit_guard_text(lang, str(orders[0].get("provider") or ""), len(orders)),
        reply_markup=_rental_exit_guard_kb("all", target=target, lang=lang),
    )
    return True


async def _handle_rental_exit_callback_guard(
    callback: types.CallbackQuery,
    state: FSMContext,
    *,
    target: str,
    lang: str,
) -> bool:
    orders = await _user_open_rentals_without_sms(callback.from_user.id)
    if not orders or not callback.message:
        return False
    refreshed_orders: list[dict] = []
    for order in orders:
        provider_code = str(order.get("provider") or "").strip().lower()
        if provider_code in {"textverified", "smspool"}:
            await _sync_rental_protection_snapshot(order.get("_id"), order)
            refreshed_orders.append(await get_order(order.get("_id")) or order)
        else:
            refreshed_orders.append(order)
    orders = [order for order in refreshed_orders if _rental_no_sms_yet(order)]
    if not orders:
        await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
        return True

    now_dt = _utc_now()
    due_orders = [order for order in orders if (_rental_safe_cutoff_at(order) and now_dt >= _rental_safe_cutoff_at(order))]
    if due_orders:
        result = await _cancel_and_refund_rental_orders(
            orders=due_orders,
            actor_user_id=int(callback.from_user.id),
            reason=f"exit_guard_{target}_cutoff",
        )
        await _safe_callback_answer()
        if result.get("success_count"):
            notice = _rental_auto_cancelled_notice(lang, int(result.get("success_count") or 0))
            try:
                await callback.message.edit_text(notice)
            except Exception:
                await callback.message.answer(notice)
        orders = await _user_open_rentals_without_sms(callback.from_user.id)
        if not orders:
            await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
            return True

    try:
        await callback.message.edit_text(
            _rental_exit_guard_text(lang, str(orders[0].get("provider") or ""), len(orders)),
            reply_markup=_rental_exit_guard_kb("all", target=target, lang=lang),
        )
    except Exception:
        await callback.message.answer(
            _rental_exit_guard_text(lang, str(orders[0].get("provider") or ""), len(orders)),
            reply_markup=_rental_exit_guard_kb("all", target=target, lang=lang),
        )
    await _safe_callback_answer()
    return True


def _trust_alert_text(lang: str, *, mode: str, wait_sec: int) -> str:
    wait_txt = _format_wait_time_short(wait_sec)
    if mode == "active_order":
        return t(lang, "temp_trust_active_order_notice")
    return t(lang, "temp_trust_purchase_cooldown_notice").format(wait=wait_txt)


async def _evaluate_temp_trust_gate(
    *,
    user_id: int,
    service_id: str,
    provider_code: str,
) -> dict:
    if not bool(getattr(settings, "numbers_trust_enabled", True)):
        return {"allowed": True}

    service = str(service_id or "").strip()
    provider = str(provider_code or "").strip().lower()
    if not service or not provider:
        return {"allowed": True}

    open_orders = await list_user_open_temp_orders(int(user_id), limit=5)
    active_orders = [
        item for item in (open_orders or [])
        if _is_temp_order_active_for_trust_gate(item)
    ]
    if active_orders:
        return {"allowed": False, "mode": "active_order", "wait_sec": 0}

    purchase_lock = await temp_number_stats_repo.get_active_user_temp_lock(
        user_id=int(user_id),
        service_id=service,
        provider=provider,
        lock_type="purchase_cooldown",
    )
    if purchase_lock:
        return {
            "allowed": False,
            "mode": "purchase",
            "wait_sec": _seconds_left_until(purchase_lock.get("expires_at")),
        }

    snapshot_1h = await temp_number_stats_repo.get_user_trust_snapshot(
        user_id=int(user_id),
        service_id=service,
        provider=provider,
        lookback_hours=1,
    )
    snapshot_24h = await temp_number_stats_repo.get_user_trust_snapshot(
        user_id=int(user_id),
        service_id=service,
        provider=provider,
        lookback_hours=24,
    )
    score_1h = int(snapshot_1h.get("score") or 0)
    score_24h = int(snapshot_24h.get("score") or 0)

    short_window_minutes = max(1, int(getattr(settings, "numbers_trust_attempt_window_minutes", 15) or 15))
    allowed_recent_attempts = max(1, int(getattr(settings, "numbers_trust_allowed_no_code_attempts", 2) or 2))
    recent_negative_attempts = await temp_number_stats_repo.count_recent_negative_attempts(
        user_id=int(user_id),
        service_id=service,
        provider=provider,
        lookback_minutes=short_window_minutes,
    )
    if recent_negative_attempts >= allowed_recent_attempts:
        ttl = max(60, int(getattr(settings, "numbers_trust_1h_cooldown_sec", 900) or 900))
        await temp_number_stats_repo.set_user_temp_lock(
            user_id=int(user_id),
            service_id=service,
            provider=provider,
            lock_type="purchase_cooldown",
            ttl_sec=ttl,
            reason="recent_no_code_attempts_limit",
            payload={
                "recent_negative_attempts": recent_negative_attempts,
                "allowed_recent_attempts": allowed_recent_attempts,
                "attempt_window_minutes": short_window_minutes,
                "snapshot_1h": snapshot_1h,
                "snapshot_24h": snapshot_24h,
            },
        )
        return {"allowed": False, "mode": "purchase", "wait_sec": ttl}

    score_1h_limit = max(1, int(getattr(settings, "numbers_trust_1h_score_limit", 2) or 2))
    score_24h_limit = max(1, int(getattr(settings, "numbers_trust_24h_score_limit", 8) or 8))
    if score_1h >= score_1h_limit:
        ttl = max(60, int(getattr(settings, "numbers_trust_1h_cooldown_sec", 900) or 900))
        await temp_number_stats_repo.set_user_temp_lock(
            user_id=int(user_id),
            service_id=service,
            provider=provider,
            lock_type="purchase_cooldown",
            ttl_sec=ttl,
            reason="trust_cooldown_1h",
            payload={"snapshot_1h": snapshot_1h, "snapshot_24h": snapshot_24h},
        )
        return {"allowed": False, "mode": "purchase", "wait_sec": ttl}

    if score_24h >= score_24h_limit:
        ttl = max(60, int(getattr(settings, "numbers_trust_24h_cooldown_sec", 2700) or 2700))
        await temp_number_stats_repo.set_user_temp_lock(
            user_id=int(user_id),
            service_id=service,
            provider=provider,
            lock_type="purchase_cooldown",
            ttl_sec=ttl,
            reason="trust_cooldown_24h",
            payload={"snapshot_1h": snapshot_1h, "snapshot_24h": snapshot_24h},
        )
        return {"allowed": False, "mode": "purchase", "wait_sec": ttl}

    return {"allowed": True}


def _temp_code_notice_text(lang: str, *, code: str, amount: float, balance: float) -> str:
    code_value = _safe_code_text(code)
    return "\n".join(
        [
            t(lang, "temp_code_received").format(code=code_value),
            _purchase_charge_confirmed_notice_text(
                lang,
                amount=float(amount),
                balance=float(balance),
            ),
        ]
    )


def _build_temp_action_keyboard(order: dict, lang: str) -> InlineKeyboardMarkup:
    elapsed = _temp_elapsed_sec(order)
    allow_cancel = elapsed >= TEMP_CANCEL_AFTER_SEC
    allow_replace = elapsed >= _order_temp_timeout_sec(order) or bool(order.get("temp_replace_enabled"))
    return temp_wait_timeout_kb(
        str(order.get("_id")),
        lang=lang,
        allow_refresh=False,
        allow_cancel=allow_cancel,
        allow_replace=allow_replace,
        refresh_cooldown_sec=0,
    )


def _temp_post_refund_kb(order_id: str, lang: str, *, allow_replace: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if allow_replace:
        rows.append([InlineKeyboardButton(text=t(lang, "temp_request_another"), callback_data=f"temp:replace:{order_id}")])
        rows.append(
            [
                InlineKeyboardButton(
                    text=_numbers_text(lang, "Try another provider", "جرّب مزود آخر"),
                    callback_data=f"temp:alt:{order_id}",
                    style="success",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="flow:main:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _numbers_text(lang: str, en: str, ar: str) -> str:
    return ar if str(lang or "").lower().startswith("ar") else en


def _voice_waiting_text(
    *,
    lang: str,
    provider_code: str,
    number: str,
    interval_sec: int,
    service_name: str,
) -> str:
    return "\n".join(
        [
            _numbers_text(lang, "Call number is ready.", "رقم الاتصال جاهز."),
            "",
            f"{t(lang, 'service_label')}: {service_name}",
            f"{_numbers_text(lang, 'Number', 'الرقم')}: <code>{html.escape(str(number or ''))}</code>",
            "",
            _numbers_text(
                lang,
                f"Send the voice call now. I will check for the call recording every {int(interval_sec)} seconds.",
                f"اطلب مكالمة التفعيل الآن. سأفحص تسجيل المكالمة كل {int(interval_sec)} ثانية.",
            ),
        ]
    )


def _voice_received_text(lang: str, order: dict, *, recording_sent: bool) -> str:
    number = str(order.get("provider_number") or "")
    status_line = _numbers_text(
        lang,
        "The recording was sent as a file below.",
        "تم إرسال التسجيل كملف بالأسفل.",
    )
    if not recording_sent:
        status_line = _numbers_text(
            lang,
            "The call was found, but the recording could not be sent automatically. Contact support for this order.",
            "تم العثور على المكالمة، لكن تعذر إرسال التسجيل تلقائيا. تواصل مع الدعم بخصوص هذا الطلب.",
        )
    return "\n".join(
        [
            _numbers_text(lang, "Call received.", "وصلت المكالمة."),
            "",
            f"{_numbers_text(lang, 'Number', 'الرقم')}: <code>{html.escape(number)}</code>",
            status_line,
        ]
    )


def _voice_recording_filename(content_type: str | None) -> str:
    content_type = str(content_type or "").lower()
    if "mpeg" in content_type or "mp3" in content_type:
        return "call-recording.mp3"
    if "wav" in content_type:
        return "call-recording.wav"
    if "ogg" in content_type:
        return "call-recording.ogg"
    if "mp4" in content_type or "m4a" in content_type:
        return "call-recording.m4a"
    return "call-recording.bin"


async def _send_voice_recording_file(*, bot, chat_id: int, provider_code: str, recording_uri: str, lang: str) -> bool:
    try:
        data = await get_recording_from_provider(provider_code, recording_uri)
    except Exception:
        logger.exception("voice recording download failed")
        return False
    if not isinstance(data, dict) or not data.get("success") or not data.get("content"):
        return False
    content = bytes(data.get("content") or b"")
    if not content:
        return False
    content_type = str(data.get("content_type") or "")
    file = BufferedInputFile(content, filename=_voice_recording_filename(content_type))
    caption = _numbers_text(lang, "Call recording", "تسجيل المكالمة")
    try:
        await bot.send_document(chat_id=chat_id, document=file, caption=caption)
        return True
    except Exception:
        logger.exception("voice recording telegram send failed")
        return False


def _provider_retry_score(info: dict, cheapest: float) -> float:
    return _shared_provider_retry_score(info, cheapest)


def _pick_retry_provider(prices: dict, *, exclude_provider: str | None = None) -> tuple[str, dict] | None:
    return _shared_pick_retry_provider(
        prices,
        exclude_provider=exclude_provider,
        hidden_provider_codes=_HIDDEN_TEMP_PROVIDER_CODES,
    )


async def _safe_callback_answer(
    callback: types.CallbackQuery | str | None = None,
    text: str | None = None,
    *,
    show_alert: bool | None = None,
) -> bool:
    target_callback: types.CallbackQuery | None
    if callback is not None and hasattr(callback, "answer"):
        target_callback = callback
    else:
        target_callback = _CURRENT_CALLBACK.get()
        if isinstance(callback, str) and text is None:
            text = callback

    if target_callback is None:
        return False

    kwargs: dict[str, Any] = {}
    if text is not None:
        kwargs["text"] = text
    if show_alert is not None:
        kwargs["show_alert"] = show_alert
    try:
        await target_callback.answer(**kwargs)
        return True
    except TelegramBadRequest as exc:
        msg = str(exc).lower()
        if "query is too old" in msg or "query id is invalid" in msg or "response timeout expired" in msg:
            return False
        raise


async def _safe_callback_answer_or_message(
    callback: types.CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool | None = None,
) -> None:
    try:
        delivered = await _safe_callback_answer(callback, text, show_alert=show_alert)
        if delivered:
            return
    except TelegramBadRequest:
        pass
    if text and callback.message:
        with suppress(Exception):
            await callback.message.answer(text)


async def _sync_temp_wait_controls(bot, order: dict, lang: str):
    chat_id = int(order.get("temp_wait_chat_id") or 0)
    msg_id = int(order.get("temp_wait_message_id") or 0)
    if not chat_id or not msg_id:
        return
    elapsed = _temp_elapsed_sec(order)
    timeout_sec = _order_temp_timeout_sec(order)
    reuse_warranty_sec = _order_reuse_warranty_sec(order)
    text = t(lang, "temp_no_code_timeout") if elapsed >= timeout_sec else _temp_waiting_text(
        lang=lang,
        provider_code=str(order.get("provider") or ""),
        number=str(order.get("provider_number") or ""),
        country_code=str(order.get("temp_country") or ""),
        interval_sec=_poll_interval_for_provider(str(order.get("provider") or "")),
        elapsed_sec=elapsed,
        reuse_warranty_sec=reuse_warranty_sec,
        service_name=str(order.get("temp_service_key") or order.get("service_id") or ""),
    )
    await _safe_edit_message(
        bot,
        chat_id=chat_id,
        message_id=msg_id,
        text=text,
        reply_markup=_build_temp_action_keyboard(order, lang),
        parse_mode="HTML",
    )


async def _cancel_and_refund_temp_order(
    *,
    order_id,
    order: dict,
    actor_user_id: int,
    reason: str,
    require_no_sms: bool = True,
) -> dict:
    return await _shared_cancel_and_refund_temp_order(
        order_id=order_id,
        order=order,
        actor_user_id=actor_user_id,
        reason=reason,
        providers=PROVIDERS,
        financial_manager=FinancialManager,
        update_order_status_fn=update_order_status,
        update_order_details_fn=update_order_details,
        log_temp_event_fn=_log_temp_event,
        log_number_event_from_order_fn=_log_number_event_from_order,
        require_no_sms=require_no_sms,
        source="",
        final_status="cancelled",
        sleep_fn=asyncio.sleep,
    )


async def _retry_temp_refund_until_success(
    *,
    bot,
    order_id,
    actor_user_id: int,
    lang: str,
    source_reason: str,
) -> None:
    deadline_ts = _utc_now().timestamp() + max(120, int(getattr(settings, "numbers_temp_refund_retry_window_sec", TEMP_REFUND_RETRY_WINDOW_SEC) or TEMP_REFUND_RETRY_WINDOW_SEC))
    interval = max(20, int(getattr(settings, "numbers_temp_refund_retry_interval_sec", TEMP_REFUND_RETRY_INTERVAL_SEC) or TEMP_REFUND_RETRY_INTERVAL_SEC))
    attempts = 0

    while _utc_now().timestamp() < deadline_ts:
        order = await get_order(order_id)
        if not order:
            return
        if str(order.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
            return
        if _temp_order_has_received_code(order):
            # Once code arrives, refund path must stop.
            await update_order_details(order_id, {"temp_wait_state": "code_received"})
            return

        attempts += 1
        result = await _cancel_and_refund_temp_order(
            order_id=order_id,
            order=order,
            actor_user_id=int(actor_user_id),
            reason=f"{source_reason}_retry",
            require_no_sms=True,
        )
        if result.get("success"):
            try:
                await _safe_edit_message(
                    bot,
                    chat_id=int(order.get("temp_wait_chat_id") or 0),
                    message_id=int(order.get("temp_wait_message_id") or 0),
                    text=t(lang, "temp_timeout_refunded_retry"),
                    reply_markup=_temp_post_refund_kb(str(order_id), lang=lang, allow_replace=True),
                )
            except Exception:
                pass
            await _log_temp_event(order, "auto_refund_retry_success", {"attempt": attempts, "source": source_reason})
            return

        await update_order_details(
            order_id,
            {
                "temp_wait_state": "refund_pending",
                "temp_refund_retry_attempts": attempts,
                "temp_refund_retry_last_at": _utc_now(),
                "temp_refund_retry_reason": str(result.get("reason") or "provider_cancel_failed"),
            },
        )
        await asyncio.sleep(interval)

    order = await get_order(order_id)
    if order:
        await _log_temp_event(
            order,
            "auto_refund_retry_exhausted",
            {"source": source_reason, "attempts": attempts},
        )


async def _safe_edit_message(
    bot,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
):
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


async def _best_effort_safe_edit_message(
    bot,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    try:
        await _safe_edit_message(
            bot,
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as exc:
        logger.warning("Best-effort bot edit_message_text failed: %s", exc)


async def _best_effort_edit_text(
    message: types.Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as exc:
        logger.warning("Best-effort edit_text failed: %s", exc)


def _number_mode_label(order: dict, lang: str) -> str:
    mode = str(order.get("number_mode") or "").strip().lower()
    if mode == "rental":
        return _numbers_text(lang, "Rental", "إيجار")
    if mode == "voice":
        return _numbers_text(lang, "Call", "اتصال")
    return _numbers_text(lang, "Temp", "مؤقت")


def _my_number_short_label(order: dict, lang: str) -> str:
    country_code = str(order.get("rental_country") or order.get("temp_country") or "")
    number = _format_number_for_copy_text(str(order.get("provider_number") or "?"), country_code)
    service = str(order.get("service_id") or order.get("temp_service_key") or "").replace(":rental", "")
    label = f"{_number_mode_label(order, lang)} | {number} | {service or '-'}"
    if len(label) > 60:
        label = label[:57] + "..."
    return label


def _compact_datetime(value: Any) -> str:
    dt = _to_utc_datetime(value)
    if not dt:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _temp_my_numbers_expires_at(order: dict) -> datetime | None:
    created_at = _to_utc_datetime((order or {}).get("created_at"))
    if not created_at:
        return None
    return created_at + timedelta(days=TEMP_MY_NUMBERS_RETENTION_DAYS)


def _temp_my_numbers_active(order: dict) -> bool:
    mode = str((order or {}).get("number_mode") or "").strip().lower()
    if mode != "temp":
        return False
    if str((order or {}).get("status") or "").strip().lower() != "success":
        return False
    if str((order or {}).get("provisioning_state") or "").strip().lower() != "provisioned":
        return False
    if not str((order or {}).get("provider_order_id") or "").strip():
        return False
    number = str((order or {}).get("provider_number") or "").strip()
    if not number or number == "?":
        return False
    expires_at = _temp_my_numbers_expires_at(order)
    if not expires_at:
        return True
    return _seconds_left_until(expires_at) > 0


def _my_number_detail_text(order: dict, lang: str) -> str:
    mode = str(order.get("number_mode") or "").strip().lower()
    is_rental = mode == "rental"
    is_voice = mode == "voice"
    country = _country_display_name(
        order.get("rental_country") if is_rental else order.get("temp_country"),
        country_name=order.get("rental_country_name") if is_rental else order.get("temp_country_name"),
    )
    number = _format_number_for_copy_text(
        order.get("provider_number") or "-",
        order.get("rental_country") if is_rental else order.get("temp_country"),
    )
    lines = [
        t(lang, "my_numbers_detail_title"),
        "",
        f"{t(lang, 'my_numbers_type_label')}: {_number_mode_label(order, lang)}",
        f"{t(lang, 'service_label')}: {str(order.get('service_id') or order.get('temp_service_key') or '-').replace(':rental', '')}",
        f"{t(lang, 'country_label')}: {country}",
        f"{t(lang, 'rental_number_label')}: {number}",
    ]
    if is_rental:
        lines.extend(
            [
                f"{t(lang, 'rental_duration_label')}: {str(order.get('rental_duration_label') or '-')}",
                f"{t(lang, 'rental_renewable_label')}: {_bool_text(bool(order.get('rental_is_renewable')), lang)}",
                f"{t(lang, 'my_numbers_expires_label')}: {_compact_datetime(order.get('rental_end_date'))}",
            ]
        )
    elif is_voice:
        state = str(order.get("temp_wait_state") or order.get("status") or "-")
        if state == "waiting_for_call":
            status = _numbers_text(lang, "Waiting for call", "بانتظار المكالمة")
        elif state == "call_received":
            status = _numbers_text(lang, "Call received", "وصلت المكالمة")
        else:
            status = state
        lines.append(f"{t(lang, 'my_numbers_status_label')}: {status}")
        if order.get("voice_recording_uri"):
            recording_status = _numbers_text(lang, "Available", "متوفر")
            if order.get("voice_recording_sent_to_user"):
                recording_status = _numbers_text(lang, "Sent", "تم الإرسال")
            lines.append(f"{_numbers_text(lang, 'Recording', 'التسجيل')}: {recording_status}")
    else:
        lines.append(f"{t(lang, 'my_numbers_status_label')}: {str(order.get('temp_wait_state') or order.get('status') or '-')}")
        lines.append(f"{t(lang, 'my_numbers_resend_window_label')}: {_compact_datetime(order.get('temp_reuse_warranty_until'))}")
    return "\n".join(lines)


def _temp_resend_available(order: dict) -> bool:
    return _temp_my_numbers_active(order)


def _my_number_manage_kb(order: dict, order_id: str, lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    mode = str(order.get("number_mode") or "").strip().lower()
    if mode == "rental":
        return _rental_manage_kb(
            order_id=order_id,
            lang=lang,
            can_renew=bool(order.get("rental_is_renewable")),
            back_callback="flow:rental:my",
        )
    elif mode == "voice":
        rows.append([InlineKeyboardButton(text=_numbers_text(lang, "Check call", "فحص المكالمة"), callback_data=f"voice:check:{order_id}")])
    elif _temp_resend_available(order):
        rows.append([InlineKeyboardButton(text=t(lang, "temp_second_code"), callback_data=f"temp:second:{order_id}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:rental:my")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _is_manageable_my_number(order: dict) -> bool:
    number = str(order.get("provider_number") or "").strip()
    if not number or number == "?":
        return False
    mode = str(order.get("number_mode") or "").strip().lower()
    if mode in {"temp", "voice"}:
        if mode == "temp":
            return _temp_my_numbers_active(order)
        return (
            str(order.get("status") or "").strip().lower() == "success"
            and str(order.get("provisioning_state") or "").strip().lower() == "provisioned"
            and bool(str(order.get("provider_order_id") or "").strip())
        )
    if mode == "rental":
        return (
            str(order.get("status") or "").strip().lower() in {"success", "done"}
            and str(order.get("provisioning_state") or "").strip().lower() == "provisioned"
            and bool(str(order.get("provider_order_id") or "").strip())
        )
    return False


def _duration_text(option: dict, lang: str) -> str:
    label = str(option.get("duration_label") or "").strip()
    if label:
        return label
    try:
        duration = int(option.get("duration") or 0)
    except Exception:
        duration = 0
    if duration > 0:
        if duration % 24 == 0:
            return f"{duration}h ({duration // 24}d)"
        return f"{duration}h"
    return t(lang, "provider_duration")


def _pick_rental_option_by_duration(
    provider_options: dict[str, list[dict]],
    provider_code: str,
    duration_hours: int,
) -> dict | None:
    rows = provider_options.get(str(provider_code or "").strip().lower()) or []
    candidates: list[dict] = []
    for row in rows:
        try:
            row_duration = int(row.get("duration") or 0)
        except Exception:
            row_duration = 0
        if row_duration != int(duration_hours):
            continue
        candidates.append(dict(row))
    if not candidates:
        return None

    def _sort_key(item: dict) -> tuple[int, float]:
        # Prefer non-renewable first for a cleaner default confirmation flow.
        renewable_rank = 1 if bool(item.get("tv_is_renewable")) else 0
        try:
            price = float(item.get("price") or 0)
        except Exception:
            price = 0.0
        return (renewable_rank, price)

    candidates.sort(key=_sort_key)
    return candidates[0]


async def _resolve_user_reseller(user_id: int, bot_id: int) -> int:
    _ = bot_id
    return user_id


async def _load_user_order(raw_id: str, user_id: int) -> tuple[ObjectId | None, dict | None]:
    try:
        order_oid = ObjectId(raw_id)
    except Exception:
        return None, None
    order = await get_order(order_oid)
    if not order or int(order.get("user_id") or 0) != int(user_id):
        return None, None
    return order_oid, order


def _number_event_context_from_order(order: dict | None, *, number_mode: str | None = None) -> dict[str, Any]:
    return _number_event_context_from_order_impl(
        order,
        number_mode=number_mode,
        extract_order_amounts=extract_order_amounts,
    )


async def _log_number_event_from_order(
    order: dict | None,
    event: str,
    *,
    payload: dict | None = None,
    status_after: str | None = None,
    number_mode: str | None = None,
) -> None:
    await _log_number_event_from_order_impl(
        order,
        event,
        payload=payload,
        status_after=status_after,
        number_mode=number_mode,
        extract_order_amounts=extract_order_amounts,
        number_events_repo_obj=number_events_repo,
    )


async def _log_temp_event(order: dict, event: str, payload: dict | None = None):
    await _log_temp_event_impl(
        order,
        event,
        payload=payload,
        temp_number_stats_repo_obj=temp_number_stats_repo,
        log_number_event_from_order_cb=_log_number_event_from_order,
    )


async def _log_rental_event(
    *,
    order_id: Any,
    user_id: int,
    provider: str,
    service_id: str,
    event: str,
    payload: dict | None = None,
):
    await _log_rental_event_impl(
        order_id=order_id,
        user_id=user_id,
        provider=provider,
        service_id=service_id,
        event=event,
        payload=payload,
        log_number_event_from_order_cb=_log_number_event_from_order,
    )


async def _maybe_send_purchase_charge_confirmed_notice(
    *,
    bot,
    chat_id: int,
    order: dict,
    lang: str,
    code: str | None = None,
) -> None:
    order = order or {}
    if order.get("purchase_debit_notice_sent_at"):
        return
    try:
        user_id = int(order.get("user_id") or 0)
        reseller_id = int(order.get("reseller_id") or user_id)
        sale_price, _cost_price = extract_order_amounts(order)
        current_balance = await get_user_wallet_balance(user_id, reseller_id)
        code_value = str(code or order.get("temp_last_code") or "").strip()
        if code_value:
            notice_text = _temp_code_notice_text(
                lang,
                code=code_value,
                amount=float(sale_price),
                balance=float(current_balance),
            )
        else:
            notice_text = _purchase_charge_confirmed_notice_text(
                lang,
                amount=float(sale_price),
                balance=float(current_balance),
            )
        await bot.send_message(
            chat_id=chat_id,
            text=notice_text,
        )
        await update_order_details(order.get("_id"), {"purchase_debit_notice_sent_at": _utc_now()})
    except Exception:
        logger.exception("failed to send deferred purchase debit notice for order=%s", order.get("_id"))


def _rental_protection_policy(provider_code: str | None) -> dict[str, Any]:
    return _policy_rental_protection_policy(
        provider_code,
        rental_watch_poll_sec=getattr(settings, "numbers_rental_watch_poll_sec", 30),
        rental_guard_fallback_sync_window_sec=getattr(
            settings,
            "numbers_rental_guard_fallback_sync_window_sec",
            RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC,
        ),
        rental_safe_cutoff_sec=getattr(settings, "numbers_rental_safe_cutoff_sec", 60),
        hero_cancel_window_sec=getattr(settings, "numbers_hero_rental_cancel_window_sec", HERO_RENTAL_CANCEL_WINDOW_SEC),
        smspool_refund_window_sec=getattr(settings, "numbers_smspool_rental_refund_window_sec", None),
        textverified_refund_window_sec=getattr(settings, "numbers_textverified_rental_refund_window_sec", None),
    )


def _is_within_hero_rental_cancel_window(order: dict | None) -> bool:
    return _policy_is_within_hero_rental_cancel_window(
        order,
        hero_cancel_window_sec=getattr(
            settings,
            "numbers_hero_rental_cancel_window_sec",
            HERO_RENTAL_CANCEL_WINDOW_SEC,
        ),
    )


def _rental_deadline_at(order: dict | None) -> datetime | None:
    order = dict(order or {})
    order.setdefault("rental_protection_policy", _rental_protection_policy(order.get("provider")))
    return _policy_rental_deadline_at(order)


def _rental_safe_cutoff_at(order: dict | None) -> datetime | None:
    order = dict(order or {})
    order.setdefault("rental_protection_policy", _rental_protection_policy(order.get("provider")))
    return _policy_rental_safe_cutoff_at(order)


async def _sync_rental_sms_snapshot(order_id, order: dict | None) -> dict[str, Any]:
    order = order or {}
    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        return {"success": False, "messages": [], "has_sms": False, "reason": "provider_order_missing"}

    try:
        sms_data = await get_rental_sms_from_provider(provider, provider_order_id)
    except Exception as exc:
        return {"success": False, "messages": [], "has_sms": False, "raw": str(exc)}

    messages = [str(x) for x in (sms_data.get("messages") or []) if x not in (None, "")]
    has_sms = bool(messages)
    if has_sms:
        now = _utc_now()
        try:
            await update_order_details(
                order_id,
                {
                    "rental_sms_received_at": now,
                    "rental_sms_count": len(messages),
                    "rental_last_sms_sync_at": now,
                },
            )
        except Exception:
            logger.exception("failed to persist rental sms snapshot: order=%s", order_id)
        try:
            await _log_rental_event(
                order_id=order_id,
                user_id=int(order.get("user_id") or 0),
                provider=provider,
                service_id=str(order.get("service_id") or ""),
                event="guard_sms_detected",
                payload={"messages_count": len(messages)},
            )
        except Exception:
            pass
    elif sms_data.get("success"):
        try:
            await update_order_details(order_id, {"rental_last_sms_sync_at": _utc_now()})
        except Exception:
            pass
    return {"success": bool(sms_data.get("success")), "messages": messages, "has_sms": has_sms, "raw": sms_data.get("raw")}


async def _sync_rental_protection_snapshot(order_id, order: dict | None) -> dict[str, Any]:
    order = order or {}
    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        return {"success": False, "reason": "provider_order_missing"}

    try:
        info = await get_rental_info_from_provider(provider, provider_order_id)
    except Exception as exc:
        return {"success": False, "reason": "provider_info_failed", "raw": str(exc)}

    refund_deadline_at = _coerce_utc_datetime(info.get("refund_refundable_until"))
    end_date = _coerce_utc_datetime(info.get("end_date"))
    provider_can_refund = info.get("refund_can_refund")
    patch: dict[str, Any] = {"rental_last_policy_sync_at": _utc_now()}
    if end_date:
        patch["rental_end_date"] = end_date
    if refund_deadline_at and provider_can_refund is not False:
        patch["rental_refund_deadline_at"] = refund_deadline_at
        patch["rental_safe_cutoff_at"] = datetime.fromtimestamp(
            refund_deadline_at.timestamp() - max(30, int(_rental_protection_policy(provider).get("safe_cutoff_sec") or 60)),
            tz=UTC,
        )
    protection_policy = dict(order.get("rental_protection_policy") or {})
    if provider_can_refund is not None:
        protection_policy["provider_can_refund"] = bool(provider_can_refund)
        patch["rental_provider_can_refund"] = bool(provider_can_refund)
    if refund_deadline_at:
        protection_policy["provider_refund_deadline_at"] = refund_deadline_at
    if protection_policy:
        patch["rental_protection_policy"] = protection_policy
    if len(patch) > 1:
        with suppress(Exception):
            await update_order_details(order_id, patch)
    return {
        "success": bool(info.get("success")),
        "refund_deadline_at": refund_deadline_at,
        "provider_can_refund": provider_can_refund,
        "end_date": end_date,
        "raw": info.get("raw"),
    }


async def _provider_close_rental(order: dict) -> dict[str, Any]:
    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        return {"success": False, "reason": "provider_order_missing"}

    policy = _rental_protection_policy(provider)
    close_method = str(policy.get("close_method") or "finish").strip().lower()
    last_raw: Any = None
    for attempt in range(1, 4):
        try:
            if close_method == "cancel":
                prov = PROVIDERS.get(provider)
                if not prov or not hasattr(prov, "cancel"):
                    return {"success": False, "reason": "provider_cancel_not_supported"}
                close_res = await asyncio.wait_for(prov.cancel(provider_order_id), timeout=12.0)
            else:
                close_res = await asyncio.wait_for(
                    finish_rental_from_provider(provider, provider_order_id),
                    timeout=12.0,
                )
        except Exception as exc:
            close_res = {"success": False, "raw": str(exc)}
        last_raw = (close_res or {}).get("raw")
        if bool((close_res or {}).get("success")):
            return {"success": True, "raw": last_raw}
        if attempt < 3:
            await asyncio.sleep(float(attempt))
    return {"success": False, "reason": "provider_close_failed", "raw": last_raw}


async def _cancel_and_refund_rental_order(
    *,
    order_id,
    order: dict,
    actor_user_id: int,
    reason: str,
    require_no_sms: bool = False,
) -> dict:
    if not order_id or not order:
        return {"success": False, "reason": "order_not_found"}
    status = str(order.get("status") or "").lower()
    if status in {"cancelled", "failed", "refunded", "expired"}:
        return {"success": False, "reason": "already_closed"}
    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        return {"success": False, "reason": "provider_order_missing"}
    now = _utc_now()
    await _log_number_event_from_order(
        order,
        "cancel_requested",
        payload={"reason": str(reason or "cancelled")},
        number_mode="rental",
    )
    with suppress(Exception):
        await update_order_details(
            order_id,
            {
                "rental_last_close_attempt_at": now,
                "rental_last_close_reason": str(reason or "cancelled"),
            },
        )
    if require_no_sms:
        sms_snapshot = await _sync_rental_sms_snapshot(order_id, order)
        if sms_snapshot.get("has_sms"):
            return {
                "success": False,
                "reason": "sms_received",
                "messages": sms_snapshot.get("messages") or [],
            }

    close_res = await _provider_close_rental(order)
    if not close_res.get("success"):
        await _log_number_event_from_order(
            order,
            "provider_close_failed",
            payload={"raw": close_res.get("raw"), "reason": str(close_res.get("reason") or "provider_close_failed")},
            number_mode="rental",
        )
        with suppress(Exception):
            await update_order_details(
                order_id,
                {
                    "rental_last_close_error_at": _utc_now(),
                    "rental_last_close_error": str(close_res.get("reason") or "provider_close_failed"),
                    "rental_last_close_raw": close_res.get("raw"),
                },
            )
        return {
            "success": False,
            "reason": str(close_res.get("reason") or "provider_close_failed"),
            "raw": close_res.get("raw"),
        }

    sale_price, cost_price = extract_order_amounts(order)
    ok, msg = await FinancialManager.refund_core_purchase(
        int(actor_user_id),
        order_id,
        sale_price,
        cost_price,
        reseller_id=int(order.get("reseller_id") or actor_user_id),
    )
    if not ok:
        await _log_number_event_from_order(
            order,
            "refund_failed",
            payload={"raw": msg, "reason": str(reason or "cancelled")},
            number_mode="rental",
        )
        with suppress(Exception):
            await update_order_details(
                order_id,
                {
                    "rental_last_close_error_at": _utc_now(),
                    "rental_last_close_error": "financial_refund_failed",
                    "rental_last_close_raw": msg,
                },
            )
        return {"success": False, "reason": "financial_refund_failed", "raw": msg}

    await update_order_status(order_id, "cancelled")
    await update_order_details(
        order_id,
        {
            "rental_cancelled_at": now,
            "rental_refunded_at": now,
            "rental_cancel_reason": str(reason or "cancelled"),
            "rental_last_close_error_at": None,
            "rental_last_close_error": None,
            "rental_last_close_raw": close_res.get("raw"),
        },
    )
    await _log_rental_event(
        order_id=order_id,
        user_id=int(order.get("user_id") or 0),
        provider=provider,
        service_id=str(order.get("service_id") or ""),
        event="cancelled_refunded",
        payload={"reason": str(reason or "cancelled")},
    )
    await _log_number_event_from_order(
        order,
        "refund_success",
        payload={"reason": str(reason or "cancelled")},
        status_after="cancelled",
        number_mode="rental",
    )
    return {"success": True, "reason": "ok"}


async def _rental_refund_guard(
    *,
    order_id,
    actor_user_id: int,
) -> None:
    order = await get_order(order_id)
    if not order:
        return
    provider = str(order.get("provider") or "").strip().lower()
    policy = _rental_protection_policy(provider)
    deadline_sec = policy.get("refund_deadline_sec")
    poll_sec = max(20, int(policy.get("watch_poll_sec") or 30))
    fallback_sync_window_sec = max(300, int(policy.get("fallback_sync_window_sec") or RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC))

    if provider in {"textverified", "smspool"}:
        with suppress(Exception):
            await _sync_rental_protection_snapshot(order_id, order)
            order = await get_order(order_id) or order

    start_dt = _to_utc_datetime(order.get("rental_started_at")) or _to_utc_datetime(order.get("created_at"))
    if not start_dt:
        return
    deadline_ts = start_dt.timestamp() + int(deadline_sec) if deadline_sec else None
    cutoff_ts = None
    if deadline_ts:
        cutoff_ts = deadline_ts - max(30, int(policy.get("safe_cutoff_sec") or 60))
    sync_until_ts = deadline_ts or (start_dt.timestamp() + fallback_sync_window_sec)

    if cutoff_ts:
        wait_sec = max(0, int(cutoff_ts - _utc_now().timestamp()))
        if wait_sec > 0:
            await asyncio.sleep(wait_sec)

    while _utc_now().timestamp() <= sync_until_ts:
        latest = await get_order(order_id)
        if not latest:
            return
        if str(latest.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
            return
        if not _rental_no_sms_yet(latest):
            return

        sms_snapshot = await _sync_rental_sms_snapshot(order_id, latest)
        if sms_snapshot.get("has_sms"):
            return

        now_ts = _utc_now().timestamp()
        if cutoff_ts and now_ts >= cutoff_ts:
            await _log_number_event_from_order(
                latest,
                "deadline_reached",
                payload={"source": "rental_guard"},
                number_mode="rental",
            )
            result = await _cancel_and_refund_rental_order(
                order_id=order_id,
                order=latest,
                actor_user_id=int(actor_user_id),
                reason=f"{provider}_guard_no_sms_timeout",
                require_no_sms=True,
            )
            if result.get("success"):
                await _log_number_event_from_order(
                    latest,
                    "auto_protection_triggered",
                    payload={"source": "rental_guard"},
                    status_after="cancelled",
                    number_mode="rental",
                )
                await _log_rental_event(
                    order_id=order_id,
                    user_id=int(latest.get("user_id") or 0),
                    provider=provider,
                    service_id=str(latest.get("service_id") or ""),
                    event="auto_cancel_refund_guard_success",
                    payload={},
                )
                return
            if result.get("reason") == "sms_received":
                return
            await asyncio.sleep(10)
            continue

        if not deadline_ts:
            await asyncio.sleep(poll_sec)
            continue

        next_wait = min(poll_sec, max(5, int(cutoff_ts - now_ts))) if cutoff_ts else poll_sec
        await asyncio.sleep(max(5, next_wait))


async def run_rental_protection_sweep(
    *,
    limit: int = 200,
    alert_threshold_sec: int | None = None,
) -> dict[str, Any]:
    threshold_sec = max(
        60,
        int(
            alert_threshold_sec
            or getattr(settings, "numbers_rental_owner_alert_window_sec", RENTAL_OWNER_ALERT_WINDOW_SEC)
            or RENTAL_OWNER_ALERT_WINDOW_SEC
        ),
    )
    orders = await list_open_rental_orders_without_sms(limit=int(limit))
    stats = {
        "checked": 0,
        "synced_sms": 0,
        "auto_cancelled": 0,
        "close_failures": 0,
        "alerts": [],
    }
    now_dt = _utc_now()
    for order in orders:
        stats["checked"] += 1
        order_id = order.get("_id")
        if not order_id or not _rental_no_sms_yet(order):
            continue

        sms_snapshot = await _sync_rental_sms_snapshot(order_id, order)
        if sms_snapshot.get("has_sms"):
            stats["synced_sms"] += 1
            continue

        latest = await get_order(order_id)
        if not latest or not _rental_no_sms_yet(latest):
            continue

        provider_code = str(latest.get("provider") or "").strip().lower()
        if provider_code in {"textverified", "smspool"}:
            await _sync_rental_protection_snapshot(order_id, latest)
            latest = await get_order(order_id) or latest

        cutoff_at = _rental_safe_cutoff_at(latest)
        deadline_at = _rental_deadline_at(latest)
        provider_code = str(latest.get("provider") or "").strip().lower()
        provider_label = provider_public_id(provider_code)

        if cutoff_at and now_dt >= cutoff_at:
            await _log_number_event_from_order(
                latest,
                "deadline_reached",
                payload={"source": "rental_global_sweep"},
                number_mode="rental",
            )
            result = await _cancel_and_refund_rental_order(
                order_id=order_id,
                order=latest,
                actor_user_id=int(latest.get("user_id") or 0),
                reason=f"{provider_code}_global_guard_no_sms_timeout",
                require_no_sms=True,
            )
            if result.get("success"):
                stats["auto_cancelled"] += 1
                await _log_number_event_from_order(
                    latest,
                    "auto_protection_triggered",
                    payload={"source": "rental_global_sweep"},
                    status_after="cancelled",
                    number_mode="rental",
                )
                await _log_rental_event(
                    order_id=order_id,
                    user_id=int(latest.get("user_id") or 0),
                    provider=provider_code,
                    service_id=str(latest.get("service_id") or ""),
                    event="auto_cancel_refund_global_guard_success",
                    payload={},
                )
                continue
            if result.get("reason") == "sms_received":
                continue
            stats["close_failures"] += 1
            close_fail_alert_sent_at = _to_utc_datetime(latest.get("rental_close_failure_alert_sent_at"))
            if close_fail_alert_sent_at is None:
                alert_text = _rental_close_failed_alert_text(
                    order_id=order_id,
                    provider_label=provider_label,
                    user_id=latest.get("user_id"),
                    reason=str(result.get("reason") or "provider_close_failed"),
                )
                stats["alerts"].append({"kind": "close_failed", "order_id": str(order_id), "text": alert_text})
                with suppress(Exception):
                    await update_order_details(order_id, {"rental_close_failure_alert_sent_at": now_dt})
            continue

        if deadline_at:
            seconds_left = _seconds_left_until(deadline_at)
            alert_sent_at = _to_utc_datetime(latest.get("rental_cutoff_alert_sent_at"))
            if 0 < seconds_left <= threshold_sec and alert_sent_at is None:
                cutoff_txt = deadline_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                alert_text = _rental_near_cutoff_alert_text(
                    order_id=order_id,
                    provider_label=provider_label,
                    user_id=latest.get("user_id"),
                    deadline=cutoff_txt,
                    seconds_left=seconds_left,
                )
                stats["alerts"].append({"kind": "near_cutoff", "order_id": str(order_id), "text": alert_text})
                with suppress(Exception):
                    await update_order_details(order_id, {"rental_cutoff_alert_sent_at": now_dt})

    return stats


async def run_temp_wait_recovery_sweep(*, bot, limit: int = 200) -> dict[str, Any]:
    return await _run_temp_wait_recovery_sweep_impl(
        bot=bot,
        limit=int(limit),
        utc_now=_utc_now,
        list_open_temp_orders_for_recovery=list_open_temp_orders_for_recovery,
        order_bot_id=_order_bot_id,
        get_order=get_order,
        get_user=get_user,
        cancel_and_refund_temp_order=_cancel_and_refund_temp_order,
        safe_edit_message=_safe_edit_message,
        temp_post_refund_kb=_temp_post_refund_kb,
        translations_t=t,
        fetch_provider_sms=_fetch_provider_sms,
        extract_new_sms_code=_extract_new_sms_code,
        safe_code_text=_safe_code_text,
        seconds_between=_seconds_between,
        update_order_details=update_order_details,
        log_temp_event=_log_temp_event,
        temp_code_received_text=_temp_code_received_text,
        temp_code_received_kb=temp_code_received_kb,
        order_temp_timeout_sec=_order_temp_timeout_sec,
        send_temp_timeout_state=_send_temp_timeout_state,
        sync_temp_wait_controls=_sync_temp_wait_controls,
    )


async def run_unprovisioned_number_order_recovery_sweep(
    *,
    limit: int = 100,
    grace_sec: int = 120,
) -> dict[str, Any]:
    return await _run_unprovisioned_number_order_recovery_sweep_impl(
        limit=int(limit),
        grace_sec=int(grace_sec),
        utc_now=_utc_now,
        list_paid_number_orders_missing_provider=list_paid_number_orders_missing_provider,
        to_utc_datetime=_to_utc_datetime,
        extract_order_amounts=extract_order_amounts,
        financial_manager=FinancialManager,
        update_order_status=update_order_status,
        update_order_details=update_order_details,
        log_number_event_from_order=_log_number_event_from_order,
    )


async def _fetch_provider_sms(provider_code: str, provider_order_id: str) -> dict:
    return await _fetch_provider_sms_impl(PROVIDERS, provider_code, provider_order_id)


async def _provider_resend(provider_code: str, provider_order_id: str) -> dict:
    return await _provider_resend_impl(PROVIDERS, provider_code, provider_order_id)


async def _send_temp_timeout_state(bot, order: dict, lang: str):
    await _send_temp_timeout_state_impl(
        bot=bot,
        order=order,
        lang=lang,
        utc_now=_utc_now,
        log_number_event_from_order=_log_number_event_from_order,
        cancel_and_refund_temp_order=_cancel_and_refund_temp_order,
        update_order_details=update_order_details,
        safe_edit_message=_safe_edit_message,
        temp_post_refund_kb=_temp_post_refund_kb,
        translations_t=t,
        log_temp_event=_log_temp_event,
        order_temp_timeout_sec=_order_temp_timeout_sec,
        get_order=get_order,
        sync_temp_wait_controls=_sync_temp_wait_controls,
        retry_temp_refund_until_success=_retry_temp_refund_until_success,
    )


async def _start_temp_waiter(
    *,
    bot,
    order: dict,
    lang: str,
    is_second_code: bool = False,
):
    await _start_temp_waiter_impl(
        bot=bot,
        order=order,
        lang=lang,
        is_second_code=bool(is_second_code),
        poll_interval_for_provider=_poll_interval_for_provider,
        utc_now=_utc_now,
        update_order_details=update_order_details,
        log_temp_event=_log_temp_event,
        order_temp_timeout_sec=_order_temp_timeout_sec,
        get_order=get_order,
        fetch_provider_sms=_fetch_provider_sms,
        extract_new_sms_code=_extract_new_sms_code,
        seconds_between=_seconds_between,
        maybe_send_purchase_charge_confirmed_notice=_maybe_send_purchase_charge_confirmed_notice,
        safe_edit_message=_safe_edit_message,
        temp_code_received_text=_temp_code_received_text,
        temp_code_received_kb=temp_code_received_kb,
        send_temp_timeout_state_cb=_send_temp_timeout_state,
        sync_temp_wait_controls=_sync_temp_wait_controls,
    )


async def _queue_temp_waiter(bot, order: dict, lang: str, is_second_code: bool = False):
    await _queue_temp_waiter_impl(
        bot=bot,
        order=order,
        lang=lang,
        is_second_code=bool(is_second_code),
        start_temp_waiter_cb=_start_temp_waiter,
        logger_obj=logger,
    )


def _voice_recording_uri_from_calls(calls: Any) -> str:
    if not isinstance(calls, list):
        return ""
    for call in calls:
        if not isinstance(call, dict):
            continue
        recording_uri = str(call.get("recordingUri") or call.get("recordingUrl") or "").strip()
        if recording_uri:
            return recording_uri
    return ""


async def _mark_voice_call_received_and_notify(
    *,
    bot,
    order_id,
    order: dict,
    calls: Any,
    recording_uri: str,
    lang: str,
    chat_id: int,
    message_id: int,
    source: str,
) -> bool:
    now = _utc_now()
    await update_order_details(
        order_id,
        {
            "temp_wait_state": "call_received",
            "voice_call_received_at": now,
            "voice_recording_uri": recording_uri,
            "voice_calls": calls[:5] if isinstance(calls, list) else [],
        },
    )
    await _log_temp_event(order, "voice_call_received", {"has_recording": True, "source": source})
    updated = await get_order(order_id) or order
    recording_sent = await _send_voice_recording_file(
        bot=bot,
        chat_id=chat_id,
        provider_code=str(order.get("provider") or ""),
        recording_uri=recording_uri,
        lang=lang,
    )
    await update_order_details(order_id, {"voice_recording_sent_to_user": bool(recording_sent)})
    updated = await get_order(order_id) or updated
    await _best_effort_safe_edit_message(
        bot,
        chat_id=chat_id,
        message_id=message_id,
        text=_voice_received_text(lang, updated, recording_sent=recording_sent),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="flow:main:back")]]
        ),
        parse_mode="HTML",
    )
    return True


async def _start_voice_waiter(*, bot, order: dict, lang: str) -> None:
    order_id = order.get("_id")
    provider_code = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    chat_id = int(order.get("temp_wait_chat_id") or 0)
    msg_id = int(order.get("temp_wait_message_id") or 0)
    if not order_id or not provider_code or not provider_order_id or not chat_id or not msg_id:
        return

    interval = _poll_interval_for_provider(provider_code)
    started_at = _utc_now()
    await update_order_details(
        order_id,
        {
            "temp_wait_state": "waiting_for_call",
            "temp_wait_started_at": started_at,
            "temp_wait_interval_sec": interval,
        },
    )
    await _log_temp_event(order, "voice_wait_started", {"interval_sec": interval})
    deadline = started_at.timestamp() + _order_temp_timeout_sec(order)
    while _utc_now().timestamp() < deadline:
        current = await get_order(order_id)
        if not current:
            return
        if str(current.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
            return
        calls_data = await get_calls_from_provider(provider_code, provider_order_id, to_number=str(current.get("provider_number") or ""))
        calls = calls_data.get("calls") or []
        recording_uri = _voice_recording_uri_from_calls(calls)
        if recording_uri:
            await _mark_voice_call_received_and_notify(
                bot=bot,
                order_id=order_id,
                order=current,
                calls=calls,
                recording_uri=recording_uri,
                lang=lang,
                chat_id=chat_id,
                message_id=msg_id,
                source="voice_waiter",
            )
            return
        await asyncio.sleep(interval)

    refreshed = await get_order(order_id)
    if refreshed:
        await _send_temp_timeout_state(bot, refreshed, lang)


async def _queue_voice_waiter(bot, order: dict, lang: str) -> None:
    task = asyncio.create_task(_start_voice_waiter(bot=bot, order=order, lang=lang))

    def _done(t: asyncio.Task) -> None:
        try:
            _ = t.exception()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("voice waiter task failed unexpectedly")

    task.add_done_callback(_done)


async def _show_my_numbers(target: types.Message | types.CallbackQuery, user_id: int, lang: str) -> None:
    temp_voice_orders = await list_user_open_temp_and_voice_orders(user_id, limit=20)
    rental_orders = await list_user_rental_orders(user_id, limit=20)
    orders = [order for order in [*temp_voice_orders, *rental_orders] if _is_manageable_my_number(order)]
    if not orders:
        text = t(lang, "my_numbers_empty")
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "rental_add_number"), callback_data="flow:rental:add")],
                [InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:main:back")],
            ]
        )
        if isinstance(target, types.CallbackQuery):
            await target.message.edit_text(text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)
        return

    rows: list[list[InlineKeyboardButton]] = []
    for order in orders:
        oid = str(order.get("_id"))
        if oid:
            rows.append([InlineKeyboardButton(text=_my_number_short_label(order, lang), callback_data=f"num:my:view:{oid}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:main:back")])
    text = t(lang, "my_numbers_title")
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.message(lambda msg: bool(msg.text) and ((msg.text or "").strip() in {t("en", "btn_my_numbers"), t("ar", "btn_my_numbers")}))
async def my_numbers_menu(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    await _show_my_numbers(message, message.from_user.id, lang)


@router.callback_query(lambda c: c.data == "flow:rental:my")
async def rental_my_numbers(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await _show_my_numbers(callback, callback.from_user.id, lang)


@router.callback_query(lambda c: c.data and (c.data.startswith("num:my:view:") or c.data.startswith("rent:my:view:")))
async def my_number_view(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 3)[3]
    _oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)
    await callback.message.edit_text(
        _my_number_detail_text(order, lang),
        reply_markup=_my_number_manage_kb(order, raw_id, lang),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("voice:check:"))
async def voice_check_now(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order or str(order.get("number_mode") or "").strip().lower() != "voice":
        return await _safe_callback_answer(callback, t(lang, "order_not_found"), show_alert=True)
    if str(order.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
        return await _safe_callback_answer(callback, t(lang, "order_not_found"), show_alert=True)

    cooldown_left = _temp_refresh_cooldown_left(order)
    if cooldown_left > 0:
        return await _safe_callback_answer(callback, t(lang, "temp_refresh_wait").format(seconds=cooldown_left), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await _safe_callback_answer(callback, t(lang, "order_not_found"), show_alert=True)

    recording_uri = str(order.get("voice_recording_uri") or "").strip()
    calls = order.get("voice_calls") or []
    if not recording_uri:
        try:
            calls_data = await get_calls_from_provider(provider, provider_order_id, to_number=str(order.get("provider_number") or ""))
        except Exception as exc:
            logger.warning("Manual voice call check failed for order %s: %s", order_oid, exc)
            return await _safe_callback_answer(callback, provider_generic_error(lang), show_alert=True)
        calls = calls_data.get("calls") or []
        recording_uri = _voice_recording_uri_from_calls(calls)

    if recording_uri:
        await _mark_voice_call_received_and_notify(
            bot=callback.message.bot,
            order_id=order_oid,
            order=order,
            calls=calls,
            recording_uri=recording_uri,
            lang=lang,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            source="manual_voice_check",
        )
        return await _safe_callback_answer_or_message(callback, t(lang, "ok_plain"))

    now = _utc_now()
    await update_order_details(order_oid, {"temp_last_refresh_at": now})
    await _log_temp_event(order, "manual_voice_check_no_call", {"cooldown_sec": TEMP_REFRESH_COOLDOWN_SEC})
    refreshed = await get_order(order_oid) or order
    await _best_effort_safe_edit_message(
        callback.message.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=_my_number_detail_text(refreshed, lang),
        reply_markup=_my_number_manage_kb(refreshed, str(order_oid), lang),
    )
    return await _safe_callback_answer(
        callback,
        _numbers_text(lang, "No call found yet.", "ما في مكالمة جديدة بعد."),
        show_alert=True,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("buy_provider:"))
async def provider_selected(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")

    provider_code = callback.data.split(":", 1)[1]
    if str(provider_code or "").strip().lower() in _HIDDEN_TEMP_PROVIDER_CODES:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    data = await state.get_data()
    all_prices = data.get("available_prices", {})
    provider_info = all_prices.get(provider_code)
    if not provider_info:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    if not bool(provider_info.get("available_for_buy", True)):
        msg = _numbers_provider_block_reason_text(lang, provider_info.get("provider_reason"))
        return await _safe_callback_answer(msg, show_alert=True)
    if not str(provider_info.get("api_service_name") or "").strip():
        return await _safe_callback_answer(t(lang, "no_prices_available"), show_alert=True)
    try:
        provider_price = float(provider_info.get("price") or 0)
    except Exception:
        provider_price = 0.0
    if provider_price <= 0:
        return await _safe_callback_answer(t(lang, "no_prices_available"), show_alert=True)

    await state.update_data(
        selected_provider=provider_code,
        final_price=provider_price,
        base_price=float(provider_info.get("base_price") or provider_price),
        api_service=provider_info["api_service_name"],
        selected_provider_country=provider_info.get("provider_country") or data.get("country"),
        lang=lang,
    )
    state_label = t(lang, "state_any") if str(data.get("state", "none")).lower() == "none" else str(data.get("state", "none"))
    is_voice = str(data.get("num_type") or "").strip().lower() == "voice"
    if is_voice:
        text = "\n".join(
            [
                t(lang, "confirm_purchase"),
                "",
                f"{t(lang, 'service_label')}: {data.get('service')}",
                f"{t(lang, 'country_label')}: {_country_display_name(data.get('country'))}",
                f"{t(lang, 'price_label')}: {format_usd(float(provider_info['price']))}",
                "",
                _numbers_text(
                    lang,
                    "After confirmation, the bot will show a US voice-capable number.",
                    "بعد التأكيد سيعرض البوت رقم أمريكي قابل لاستقبال مكالمة التفعيل.",
                ),
                _numbers_text(
                    lang,
                    "Send the verification call to that number. The bot will check for the call recording.",
                    "اطلب مكالمة التفعيل على الرقم. البوت سيراقب وصول تسجيل المكالمة.",
                ),
                _numbers_text(
                    lang,
                    "There is no SMS resend or multi-code flow for call numbers. If no call arrives, try another number or cancel.",
                    "لا يوجد إعادة إرسال SMS أو Multi-Code لرقم الاتصال. إذا لم تصل المكالمة جرّب رقم آخر أو ألغِ الطلب.",
                ),
                "",
                t(lang, "confirm_purchase_question"),
            ]
        )
    else:
        reuse_policy_text = "\n" + _temp_reuse_policy_text(
            lang,
            _provider_default_reuse_warranty_sec(provider_code),
        )
        text = (
            f"{t(lang, 'confirm_purchase')}\n\n"
            f"{t(lang, 'provider_label')}: {provider_public_id(provider_code)}\n"
            f"{t(lang, 'service_label')}: {data.get('service')}\n"
            f"{t(lang, 'country_label')}: {_country_display_name(data.get('country'))}\n"
            f"{t(lang, 'state_label')}: {state_label}\n"
            f"{t(lang, 'price_label')}: {format_usd(float(provider_info['price']))}"
            f"{reuse_policy_text}\n\n"
            f"{t(lang, 'confirm_purchase_question')}"
        )
    await callback.message.edit_text(text, reply_markup=confirm_buy_kb(lang))
    await state.set_state(NumberFlow.confirm_buy)


@router.callback_query(lambda c: c.data == "buy_provider_show_all")
async def provider_show_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    prices = data.get("available_prices") or {}
    if not prices:
        return await _safe_callback_answer(t(lang, "no_prices_available"), show_alert=True)
    usd_to_syp_rate = float(data.get("usd_to_syp_rate") or 0)
    state_code = str(data.get("state") or "")
    state_label = t(lang, "state_any") if state_code.lower() in {"", "none"} else state_code
    context = (
        f"{t(lang, 'choose_provider_prompt')}\n\n"
        f"{t(lang, 'service_label')}: {data.get('service')}\n"
        f"{t(lang, 'country_label')}: {_country_display_name(data.get('country'))}"
    )
    if str(data.get("country") or "") == "1":
        context += f"\n{t(lang, 'state_label')}: {state_label}"
    await callback.message.edit_text(
        context,
        reply_markup=provider_choice_kb(prices, lang=lang, usd_to_syp=usd_to_syp_rate, show_all=True),
    )
    await _safe_callback_answer()


@router.callback_query(lambda c: c.data and c.data.startswith("buy_provider_info:"))
async def provider_info_noop(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    provider_code = str((callback.data or "").split(":", 1)[1] if ":" in str(callback.data or "") else "").strip().lower()
    info = None
    try:
        data = await state.get_data()
        info = (data.get("available_prices") or {}).get(provider_code)
    except Exception:
        info = None
    if info is None:
        await _safe_callback_answer()
        return
    await _safe_callback_answer(_provider_info_alert_text(lang, provider_code, info), show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("renthead:"))
async def rental_provider_header_noop(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    provider_code = str((callback.data or "").split(":", 1)[1] if ":" in str(callback.data or "") else "").strip().lower()
    data = await state.get_data()
    provider_options = data.get("rental_provider_options") or {}
    provider_rows = data.get("rental_provider_rows") or []
    options = provider_options.get(provider_code) or []
    summary = next((row for row in provider_rows if str(row.get("provider") or "").strip().lower() == provider_code), None)
    if not options and not summary:
        await _safe_callback_answer()
        return
    await _safe_callback_answer(
        _rental_provider_info_alert_text(lang, provider_code, options, summary=summary),
        show_alert=True,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("rentna:"))
async def rental_provider_duration_unavailable(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    msg = t(lang, "numbers_rental_duration_unavailable")
    await _safe_callback_answer(msg, show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("rentpick:"))
async def rental_option_selected_from_provider_grid(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()

    parts = str(callback.data or "").split(":")
    if len(parts) != 3:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    provider_code = parts[1].strip().lower()
    try:
        duration_hours = int(parts[2].strip())
    except Exception:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)

    provider_options = data.get("rental_provider_options") or {}
    option = _pick_rental_option_by_duration(provider_options, provider_code, duration_hours)
    if not option:
        return await _safe_callback_answer(t(lang, "no_rental_options"), show_alert=True)

    if provider_code == "textverified":
        matched_rows = [
            dict(row)
            for row in (provider_options.get(provider_code) or [])
            if int(row.get("duration") or 0) == int(duration_hours)
        ]
        if not matched_rows:
            return await _safe_callback_answer(t(lang, "no_rental_options"), show_alert=True)
        duration_key = str(matched_rows[0].get("tv_duration_key") or "").strip()
        nonrenew_price = None
        renew_price = None
        for row in matched_rows:
            try:
                price = float(row.get("price") or 0)
            except Exception:
                price = 0.0
            if price <= 0:
                continue
            if bool(row.get("tv_is_renewable")):
                renew_price = price if renew_price is None else min(renew_price, price)
            else:
                nonrenew_price = price if nonrenew_price is None else min(nonrenew_price, price)
        if nonrenew_price is None and renew_price is None:
            return await _safe_callback_answer(t(lang, "no_rental_options"), show_alert=True)
        await state.update_data(
            selected_rental_provider=provider_code,
            rental_options=provider_options.get(provider_code) or [],
            selected_rental_option=None,
            tv_selected_duration=duration_key,
            tv_selected_option_base=None,
            awaiting_tv_state=False,
        )
        usd_to_syp_rate = float(data.get("usd_to_syp_rate") or 0)
        await callback.message.edit_text(
            t(lang, "tv_choose_renew_mode"),
            reply_markup=tv_renewable_kb(
                nonrenew_price=nonrenew_price,
                renew_price=renew_price,
                lang=lang,
                usd_to_syp=usd_to_syp_rate,
            ),
        )
        await state.set_state(NumberFlow.rental_tv_renew)
        return

    await state.update_data(
        selected_rental_provider=provider_code,
        rental_options=provider_options.get(provider_code) or [],
        selected_rental_option=option,
    )

    await callback.message.edit_text(_rental_confirm_text(lang, data, option), reply_markup=rental_confirm_kb(lang))
    await state.set_state(NumberFlow.rental_confirm)


@router.callback_query(lambda c: c.data and c.data.startswith("rentopt:"))
async def rental_option_selected(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    options = data.get("rental_options") or []

    try:
        idx = int(callback.data.split(":", 1)[1])
    except Exception:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)

    if idx < 0 or idx >= len(options):
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)

    option = options[idx]
    await state.update_data(selected_rental_option=option)
    await callback.message.edit_text(_rental_confirm_text(lang, data, option), reply_markup=rental_confirm_kb(lang))
    await state.set_state(NumberFlow.rental_confirm)


@router.callback_query(lambda c: c.data == "rent:noop")
async def rental_noop(callback: types.CallbackQuery):
    await _safe_callback_answer()


@router.callback_query(lambda c: c.data == "rent:cancel")
async def rental_cancel(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await _return_to_main_menu_from_buy(callback, state, lang)
    await _safe_callback_answer(callback)


@router.callback_query(lambda c: c.data == "rent:confirm")
async def rent_confirm_warning(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    selected = data.get("selected_rental_option") or {}
    provider_code = selected.get("provider")
    if not provider_code:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    await callback.message.edit_text(
        _rental_refund_warning_text(lang, provider_code=provider_code, selected_option=selected, data=data),
        reply_markup=rental_warning_kb(lang),
    )
    await _safe_callback_answer()


@router.callback_query(lambda c: c.data == "rent:confirm:back")
async def rent_confirm_warning_back(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    selected = data.get("selected_rental_option") or {}
    if not selected:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    await callback.message.edit_text(
        _rental_confirm_text(lang, data, selected),
        reply_markup=rental_confirm_kb(lang),
    )
    await _safe_callback_answer()


@router.callback_query(lambda c: c.data == "rent:confirm:final")
async def rent_confirm_process(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    user_id = callback.from_user.id
    data = await state.get_data()
    service_name = data.get("service")
    selected = data.get("selected_rental_option") or {}

    provider_code = selected.get("provider")
    api_service = selected.get("api_service_name")
    country = str(selected.get("country") or data.get("country") or "")
    country_name = _country_display_name(country, country_name=selected.get("country_name"))
    try:
        duration = int(selected.get("duration") or 0)
    except Exception:
        duration = 0
    final_price = float(selected.get("price") or 0)
    try:
        cost_price = float(selected.get("base_price", final_price) or final_price)
    except Exception:
        cost_price = final_price
    is_renewable = bool(selected.get("tv_is_renewable"))
    billing_cycle_label = str(selected.get("rental_billing_cycle_label") or "")
    if is_renewable and not billing_cycle_label:
        billing_cycle_label = t(lang, "tv_billing_cycle_auto_new")

    if not provider_code or not api_service or not service_name or not country or duration <= 0 or final_price <= 0:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    if bool(data.get("rent_confirm_inflight")):
        return await _safe_callback_answer(t(lang, "processing_order"), show_alert=False)
    await state.update_data(rent_confirm_inflight=True)
    state_cleared = False
    inflight_locked = True

    bot_id = (await callback.message.bot.get_me()).id
    reseller_id = await _resolve_user_reseller(user_id, bot_id)

    order = await create_order(
        user_id=user_id,
        reseller_id=reseller_id,
        service_id=f"{service_name}:rental",
        selling_price=final_price,
        base_price=cost_price,
    )
    order_id = order["_id"]
    order.update(
        {
            "number_mode": "rental",
            "provisioning_provider": str(provider_code),
            "provisioning_country": str(country),
            "provisioning_state_code": str(selected.get("state_code") or "none"),
        }
    )
    await update_order_details(
        order_id,
        {
            "number_mode": "rental",
            "telegram_bot_id": int(bot_id),
            "provisioning_state": "awaiting_charge",
            "provisioning_provider": str(provider_code),
            "provisioning_service": str(api_service),
            "provisioning_country": str(country),
            "provisioning_state_code": str(selected.get("state_code") or "none"),
            "provisioning_duration_hours": int(duration),
            "provisioning_created_at": _utc_now(),
        },
    )
    await _log_number_event_from_order(order, "order_created", payload={"duration_hours": int(duration)}, number_mode="rental")

    ok, message = await FinancialManager.process_core_purchase(
        user_id=user_id,
        order_id=order_id,
        sale_price=final_price,
        cost_price=cost_price,
        reseller_id=reseller_id,
    )
    if not ok:
        await update_order_status(order_id, "failed")
        await _log_number_event_from_order(order, "wallet_charge_failed", payload={"message": str(message)}, status_after="failed", number_mode="rental")
        await state.update_data(rent_confirm_inflight=False)
        inflight_locked = False
        return await _safe_callback_answer(finance_error_public_text(lang, str(message)), show_alert=True)

    await _best_effort_edit_text(callback.message, t(lang, "processing_order"))
    await _log_number_event_from_order(order, "wallet_charged", status_after="paid", number_mode="rental")

    try:
        await update_order_details(
            order_id,
            {
                "provisioning_state": "charged_pending_provider",
                "provisioning_charged_at": _utc_now(),
            },
        )
        await _log_number_event_from_order(
            {**order, "provider": provider_code, "status": "paid"},
            "provider_rent_started",
            payload={"api_service": str(api_service), "duration_hours": int(duration)},
            status_after="paid",
            number_mode="rental",
        )
        option_meta = {
            key: selected.get(key)
            for key in (
                "rental_id",
                "duration_days",
                "country_name",
                "tv_with_state",
                "state_code",
                "tv_duration_key",
                "tv_is_renewable",
            )
            if selected.get(key) not in (None, "")
        }
        rent_res = await rent_number_from_provider(
            provider_code=provider_code,
            api_service_name=str(api_service),
            country=country,
            duration=duration,
            option_meta=option_meta,
        )
        if not rent_res or not rent_res.get("success"):
            refund_ok, _refund_msg = await FinancialManager.refund_core_purchase(
                user_id,
                order_id,
                final_price,
                cost_price,
                reseller_id=reseller_id,
            )
            await update_order_status(order_id, "refunded" if refund_ok else "failed")
            await update_order_details(
                order_id,
                {
                    "provisioning_state": "provider_failed_refunded" if refund_ok else "provider_failed_refund_error",
                    "provisioning_failure_at": _utc_now(),
                },
            )
            await _log_number_event_from_order(
                {**order, "provider": provider_code, "status": "paid"},
                "provider_rent_failed",
                payload={"raw": rent_res.get("raw") if rent_res else "provider_no_response"},
                status_after="refunded" if refund_ok else "failed",
                number_mode="rental",
            )
            await _log_number_event_from_order(
                {**order, "provider": provider_code, "status": "paid"},
                "refund_success" if refund_ok else "refund_failed",
                payload={"source": "provider_rent_failed"},
                status_after="refunded" if refund_ok else "failed",
                number_mode="rental",
            )
            if refund_ok:
                try:
                    current_balance = await get_user_wallet_balance(user_id, reseller_id)
                    await callback.message.answer(
                        _purchase_refunded_notice_text(
                            lang,
                            amount=float(final_price),
                            balance=float(current_balance),
                        )
                    )
                except Exception:
                    pass
            err = rent_res.get("raw", "provider_error") if rent_res else "provider_no_response"
            raise RuntimeError(_provider_error_text(err))

        provider_order_id = str(rent_res.get("order_id"))
        number = str(rent_res.get("number"))
        protection_policy = _rental_protection_policy(provider_code)
        rental_started_at = _utc_now()
        rental_deadline_at = None
        rental_safe_cutoff_at = None
        provider_refund_deadline_at = _coerce_utc_datetime(rent_res.get("refund_refundable_until"))
        provider_can_refund = rent_res.get("refund_can_refund")
        if provider_refund_deadline_at and provider_can_refund is not False:
            rental_deadline_at = provider_refund_deadline_at
            rental_safe_cutoff_at = datetime.fromtimestamp(
                rental_deadline_at.timestamp() - max(30, int(protection_policy.get("safe_cutoff_sec") or 60)),
                tz=UTC,
            )
        elif protection_policy.get("refund_deadline_sec"):
            rental_deadline_at = datetime.fromtimestamp(
                rental_started_at.timestamp() + int(protection_policy["refund_deadline_sec"]),
                tz=UTC,
            )
            rental_safe_cutoff_at = datetime.fromtimestamp(
                rental_deadline_at.timestamp() - max(30, int(protection_policy.get("safe_cutoff_sec") or 60)),
                tz=UTC,
            )
        await update_order_details(
            order_id,
            {
                "provider_order_id": provider_order_id,
                "provider": provider_code,
                "provider_number": number,
                "number_mode": "rental",
                "rental_started_at": rental_started_at,
                "rental_duration_hours": duration,
                "rental_duration_label": _duration_text(selected, lang),
                "rental_country": country,
                "rental_country_name": country_name,
                "rental_cost": rent_res.get("price"),
                "rental_end_date": rent_res.get("end_date"),
                "rental_is_renewable": bool(is_renewable),
                "rental_billing_cycle_label": billing_cycle_label if is_renewable else "-",
                "rental_billing_cycle_id": rent_res.get("billing_cycle_id"),
                "rental_state_code": str(selected.get("state_code") or "none"),
                "rental_refund_deadline_at": rental_deadline_at,
                "rental_safe_cutoff_at": rental_safe_cutoff_at,
                "telegram_bot_id": int(bot_id),
                "provisioning_state": "provisioned",
                "provisioned_at": _utc_now(),
                "rental_protection_policy": {
                    "provider": provider_code,
                    "close_method": protection_policy.get("close_method"),
                    "refund_deadline_sec": protection_policy.get("refund_deadline_sec"),
                    "safe_cutoff_sec": protection_policy.get("safe_cutoff_sec"),
                    "provider_can_refund": provider_can_refund,
                    "provider_refund_deadline_at": provider_refund_deadline_at,
                },
            },
        )
        await update_order_status(order_id, "success")
        await _log_number_event_from_order(
            {
                **order,
                "_id": order_id,
                "provider": provider_code,
                "provider_order_id": provider_order_id,
                "provider_number": number,
                "rental_country": country,
                "rental_state_code": str(selected.get("state_code") or "none"),
                "status": "paid",
            },
            "provider_rent_success",
            payload={"duration_hours": int(duration)},
            status_after="success",
            number_mode="rental",
        )
        await _log_rental_event(
            order_id=order_id,
            user_id=user_id,
            provider=provider_code,
            service_id=f"{service_name}:rental",
            event="purchase_success",
            payload={
                "duration_hours": int(duration),
                "provider_order_id": provider_order_id,
            },
        )

        duration_text = _duration_text(selected, lang)
        asyncio.create_task(
            _rental_refund_guard(
                order_id=order_id,
                actor_user_id=int(user_id),
            )
        )
        try:
            await _best_effort_edit_text(
                callback.message,
                t(lang, "rental_purchase_complete").format(
                    number=_format_number_for_copy_html(number, country),
                    order_id=provider_order_id,
                    provider=provider_public_id(provider_code),
                    duration=duration_text,
                ),
                reply_markup=_rental_result_kb(str(order_id), lang, can_renew=is_renewable),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("Rental completion edit failed after provider success: %s", exc)
        state_cleared = True
        inflight_locked = False
        await state.clear()
    except Exception as exc:
        err_text = _provider_error_text(exc)
        if _is_expected_provider_failure(exc):
            logger.warning("Provider rental failed for user %s: %s", user_id, err_text)
        else:
            logger.exception("Provider rental failed for user %s: %s", user_id, err_text)
        await _show_purchase_failed_then_main_menu(callback.message, state, lang)
        state_cleared = True
        inflight_locked = False
    finally:
        if inflight_locked and not state_cleared:
            await state.update_data(rent_confirm_inflight=False)


@router.callback_query(lambda c: c.data and c.data.startswith("rent:sms:"))
async def rent_fetch_sms(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]

    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)

    try:
        sms_data = await get_rental_sms_from_provider(provider, provider_order_id)
    except Exception:
        sms_data = {"success": False, "messages": []}

    messages = sms_data.get("messages") or []
    if not messages:
        return await _safe_callback_answer(t(lang, "no_sms_yet"), show_alert=True)

    now = _utc_now()
    try:
        await update_order_details(
            order_oid,
            {
                "rental_sms_received_at": now,
                "rental_sms_count": len(messages),
            },
        )
    except Exception:
        pass
    refreshed_order = await get_order(order_oid) or order
    await _maybe_send_purchase_charge_confirmed_notice(
        bot=callback.message.bot,
        chat_id=callback.message.chat.id,
        order=refreshed_order,
        lang=lang,
    )

    await _log_rental_event(
        order_id=order_oid,
        user_id=int(callback.from_user.id),
        provider=provider,
        service_id=str(order.get("service_id") or ""),
        event="code_received",
        payload={"messages_count": len(messages)},
    )

    lines = "\n".join([f"- {m}" for m in messages[:8]])
    await callback.message.answer(t(lang, "rental_sms_list").format(messages=lines))
    await _safe_callback_answer(t(lang, "updated_plain"))


@router.callback_query(lambda c: c.data and c.data.startswith("rent:finish:"))
async def rent_finish(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]

    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)

    # Hero rental safety: if no SMS arrived and we are still inside the provider's
    # cancellation window, perform cancel+refund instead of finish.
    if provider == "herosms" and _rental_no_sms_yet(order) and _is_within_hero_rental_cancel_window(order):
        cancel_refund = await _cancel_and_refund_rental_order(
            order_id=order_oid,
            order=order,
            actor_user_id=int(callback.from_user.id),
            reason="hero_rental_no_sms_within_window",
            require_no_sms=True,
        )
        if cancel_refund.get("success"):
            return await _safe_callback_answer(t(lang, "rental_cancelled_refunded"), show_alert=True)
        return await _safe_callback_answer(t(lang, "rental_finish_failed"), show_alert=True)

    try:
        finish_res = await finish_rental_from_provider(provider, provider_order_id)
        ok = bool(finish_res.get("success"))
    except Exception:
        ok = False

    if ok:
        await update_order_details(
            order_oid,
            {"rental_finished_at": datetime.now(UTC)},
        )
        await _log_number_event_from_order(order, "rental_finished", status_after=str(order.get("status") or "success"), number_mode="rental")
        return await _safe_callback_answer(t(lang, "rental_finished"), show_alert=True)

    await _log_number_event_from_order(order, "rental_finish_failed", number_mode="rental")
    return await _safe_callback_answer(t(lang, "rental_finish_failed"), show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("rent:renew:"))
async def rent_renew(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    if not bool(order.get("rental_is_renewable")):
        return await _safe_callback_answer(t(lang, "rental_action_not_supported"), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)

    try:
        res = await renew_rental_from_provider(provider, provider_order_id)
        if bool(res.get("success")):
            await update_order_details(order_oid, {"rental_last_renew_at": datetime.now(UTC)})
            await _log_number_event_from_order(order, "rental_renewed", payload={"raw": res.get("raw")}, number_mode="rental")
            return await _safe_callback_answer(t(lang, "rental_renewed"), show_alert=True)
    except Exception:
        pass
    await _log_number_event_from_order(order, "rental_renew_failed", number_mode="rental")
    return await _safe_callback_answer(t(lang, "rental_renew_failed"), show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("rent:wake:"))
async def rent_wake(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)

    try:
        res = await wake_rental_from_provider(provider, provider_order_id)
        if bool(res.get("success")):
            await update_order_details(order_oid, {"rental_last_wake_at": datetime.now(UTC)})
            await _log_number_event_from_order(order, "rental_wake_ok", payload={"raw": res.get("raw")}, number_mode="rental")
            return await _safe_callback_answer(t(lang, "rental_wake_ok"), show_alert=True)
    except Exception:
        pass
    await _log_number_event_from_order(order, "rental_wake_failed", number_mode="rental")
    return await _safe_callback_answer(t(lang, "rental_wake_failed"), show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("rent:notes:"))
async def rent_notes_tags(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    _order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)

    try:
        res = await notes_tags_from_provider(provider, provider_order_id)
    except Exception:
        res = {"success": False}
    if not res.get("success"):
        return await _safe_callback_answer(t(lang, "rental_action_not_supported"), show_alert=True)

    notes = str(res.get("notes") or "-")
    tags = res.get("tags") or []
    if isinstance(tags, list) and tags:
        tags_text = ", ".join([str(x) for x in tags[:20]])
    else:
        tags_text = "-"
    await callback.message.answer(
        t(lang, "rental_notes_tags_text").format(notes=notes, tags=tags_text)
    )
    return await _safe_callback_answer(t(lang, "ok_plain"))


def _parse_rental_guard_callback(data: str) -> tuple[str, str, str] | None:
    parts = str(data or "").split(":")
    if len(parts) != 4 or parts[0] != "rentguard":
        return None
    action = parts[1].strip().lower()
    target = parts[2].strip().lower()
    order_id = parts[3].strip()
    if action not in {"keep", "cancel"} or not order_id:
        return None
    return action, target, order_id


@router.callback_query(lambda c: c.data and c.data.startswith("rentguard:keep:"))
async def rental_guard_keep(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    parsed = _parse_rental_guard_callback(str(callback.data or ""))
    if not parsed or not callback.message:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    _action, target, _order_scope = parsed
    await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
    await _safe_callback_answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rentguard:cancel:"))
async def rental_guard_cancel(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    parsed = _parse_rental_guard_callback(str(callback.data or ""))
    if not parsed or not callback.message:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    _action, target, raw_scope = parsed
    if raw_scope == "all":
        orders = await _user_open_rentals_without_sms(callback.from_user.id)
        if not orders:
            await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
            return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)
        result = await _cancel_and_refund_rental_orders(
            orders=orders,
            actor_user_id=int(callback.from_user.id),
            reason=f"exit_guard_user_cancel_{target}",
        )
        if result.get("success_count"):
            notice = _rental_cancelled_notice(lang, int(result.get("success_count") or 0))
            try:
                await callback.message.edit_text(notice)
            except Exception:
                await callback.message.answer(notice)
            await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
            return await _safe_callback_answer()
        if result.get("sms_received_count"):
            await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
            return await _safe_callback_answer(
                t(lang, "rental_guard_sms_received_many_notice"),
                show_alert=True,
            )
        await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
        return await _safe_callback_answer(
            t(lang, "rental_guard_cancel_many_failed_notice"),
            show_alert=True,
        )

    order_oid, order = await _load_user_order(raw_scope, callback.from_user.id)
    if not order_oid or not order:
        await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)

    result = await _cancel_and_refund_rental_order(
        order_id=order_oid,
        order=order,
        actor_user_id=int(callback.from_user.id),
        reason=f"exit_guard_user_cancel_{target}",
        require_no_sms=True,
    )
    if result.get("success"):
        notice = t(lang, "rental_cancelled_refunded_one_notice")
        try:
            await callback.message.edit_text(notice)
        except Exception:
            await callback.message.answer(notice)
        await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
        return await _safe_callback_answer()

    if result.get("reason") == "sms_received":
        await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
        return await _safe_callback_answer(
            t(lang, "rental_guard_sms_received_one_notice"),
            show_alert=True,
        )

    return await _safe_callback_answer(
        t(lang, "rental_guard_cancel_one_failed_notice"),
        show_alert=True,
    )


@router.callback_query(lambda c: c.data == "buy:confirm")
async def confirm_buy_process(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    user_id = callback.from_user.id
    data = await state.get_data()
    provider_code = data.get("selected_provider")
    api_service = data.get("api_service")
    country = data.get("country")
    provider_country = data.get("selected_provider_country")
    state_code = data.get("state")
    service_name = data.get("service")
    final_price = float(data.get("final_price", 0))
    cost_price = float(data.get("base_price", final_price))
    number_mode = "voice" if str(data.get("num_type") or "").strip().lower() == "voice" else "temp"

    if not provider_code or not api_service or not service_name or final_price <= 0:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    if str(provider_code or "").strip().lower() in _HIDDEN_TEMP_PROVIDER_CODES:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    if bool(data.get("buy_confirm_inflight")):
        return await _safe_callback_answer(t(lang, "processing_order"), show_alert=False)
    await state.update_data(buy_confirm_inflight=True)
    state_cleared = False
    inflight_locked = True

    trust_gate = await _evaluate_temp_trust_gate(
        user_id=user_id,
        service_id=str(service_name),
        provider_code=str(provider_code),
    )
    if not bool(trust_gate.get("allowed")):
        await state.update_data(buy_confirm_inflight=False)
        inflight_locked = False
        return await _safe_callback_answer(
            _trust_alert_text(
                lang,
                mode=str(trust_gate.get("mode") or "purchase"),
                wait_sec=int(trust_gate.get("wait_sec") or 0),
            ),
            show_alert=True,
        )

    bot_id = (await callback.message.bot.get_me()).id
    reseller_id = await _resolve_user_reseller(user_id, bot_id)

    order = await create_order(
        user_id=user_id,
        reseller_id=reseller_id,
        service_id=service_name,
        selling_price=final_price,
        base_price=cost_price,
    )
    order_id = order["_id"]
    order.update(
        {
            "number_mode": number_mode,
            "provisioning_provider": str(provider_code),
            "provisioning_country": None if country == "none" else country,
            "provisioning_state_code": None if state_code == "none" else state_code,
        }
    )
    await update_order_details(
        order_id,
        {
            "number_mode": number_mode,
            "telegram_bot_id": int(bot_id),
            "provisioning_state": "awaiting_charge",
            "provisioning_provider": str(provider_code),
            "provisioning_service": str(api_service),
            "provisioning_country": None if country == "none" else country,
            "provisioning_state_code": None if state_code == "none" else state_code,
            "provisioning_created_at": _utc_now(),
        },
    )
    await _log_number_event_from_order(order, "order_created", number_mode=number_mode)

    ok, message = await FinancialManager.process_core_purchase(
        user_id=user_id,
        order_id=order_id,
        sale_price=final_price,
        cost_price=cost_price,
        reseller_id=reseller_id,
    )
    if not ok:
        await update_order_status(order_id, "failed")
        await _log_number_event_from_order(order, "wallet_charge_failed", payload={"message": str(message)}, status_after="failed", number_mode=number_mode)
        await state.update_data(buy_confirm_inflight=False)
        inflight_locked = False
        return await _safe_callback_answer(finance_error_public_text(lang, str(message)), show_alert=True)

    await _best_effort_edit_text(callback.message, t(lang, "processing_order"))
    await _log_number_event_from_order(order, "wallet_charged", status_after="paid", number_mode=number_mode)

    try:
        await update_order_details(
            order_id,
            {
                "provisioning_state": "charged_pending_provider",
                "provisioning_charged_at": _utc_now(),
            },
        )
        purchase_options = {
            "reuse_mode": True,
            "_audit_requested_service": str(order.get("temp_service_key") or order.get("service_id") or ""),
        }
        if number_mode == "voice":
            purchase_options["capability"] = "voice"
        await _log_number_event_from_order(
            {**order, "provider": provider_code, "status": "paid"},
            "provider_buy_started",
            payload={"api_service": str(api_service)},
            status_after="paid",
            number_mode=number_mode,
        )
        req_country = None if provider_country == "none" else provider_country
        req_state = None if state_code == "none" else state_code

        buy_res = await buy_number_from_provider(
            provider_code=provider_code,
            api_service_name=api_service,
            country=req_country,
            state=req_state,
            dry_run=False,
            purchase_options=purchase_options,
        )
        if not buy_res or not buy_res.get("success"):
            refund_ok, _refund_msg = await FinancialManager.refund_core_purchase(
                user_id,
                order_id,
                final_price,
                cost_price,
                reseller_id=reseller_id,
            )
            await update_order_status(order_id, "refunded" if refund_ok else "failed")
            await update_order_details(
                order_id,
                {
                    "provisioning_state": "provider_failed_refunded" if refund_ok else "provider_failed_refund_error",
                    "provisioning_failure_at": _utc_now(),
                },
            )
            await _log_number_event_from_order(
                {**order, "provider": provider_code, "status": "paid"},
                "provider_buy_failed",
                payload={"raw": buy_res.get("raw") if buy_res else "provider_no_response"},
                status_after="refunded" if refund_ok else "failed",
                number_mode=number_mode,
            )
            await _log_number_event_from_order(
                {**order, "provider": provider_code, "status": "paid"},
                "refund_success" if refund_ok else "refund_failed",
                payload={"source": "provider_buy_failed"},
                status_after="refunded" if refund_ok else "failed",
                number_mode=number_mode,
            )
            if refund_ok:
                try:
                    current_balance = await get_user_wallet_balance(user_id, reseller_id)
                    await callback.message.answer(
                        _purchase_refunded_notice_text(
                            lang,
                            amount=float(final_price),
                            balance=float(current_balance),
                        )
                    )
                except Exception:
                    pass
            err = buy_res.get("raw", "provider_error") if buy_res else "provider_no_response"
            if buy_res and isinstance(buy_res, dict) and isinstance(buy_res.get("normalized_error"), dict):
                normalized = buy_res.get("normalized_error") or {}
                err = normalized.get("message") or err
            raise RuntimeError(_provider_error_text(err))

        provider_order_id = buy_res.get("order_id")
        number = buy_res.get("number")
        provider_pool = str(buy_res.get("pool") or "").strip() or None
        interval_sec = _poll_interval_for_provider(str(provider_code))
        provider_timeout_sec = _extract_provider_wait_timeout_sec(buy_res)
        if provider_timeout_sec:
            provider_timeout_sec = min(TEMP_WAIT_TIMEOUT_SEC, int(provider_timeout_sec))
        now = _utc_now()
        reuse_until = None
        reuse_warranty_sec = _resolve_reuse_warranty_sec(provider_code, buy_res)
        reuse_until = datetime.fromtimestamp(now.timestamp() + int(reuse_warranty_sec), tz=UTC)

        await update_order_details(
            order_id,
            {
                "provider_order_id": provider_order_id,
                "provider": provider_code,
                "provider_number": number,
                "provider_pool": provider_pool,
                "number_mode": number_mode,
                "voice_enabled": number_mode == "voice",
                "temp_api_service": str(api_service),
                "temp_country": None if country == "none" else country,
                "temp_state": None if state_code == "none" else state_code,
                "temp_service_key": str(service_name),
                "temp_reuse_warranty_until": reuse_until,
                "temp_reuse_warranty_sec": reuse_warranty_sec,
                "temp_wait_chat_id": callback.message.chat.id,
                "temp_wait_message_id": callback.message.message_id,
                "temp_wait_bot_id": int(bot_id),
                "temp_wait_interval_sec": interval_sec,
                "temp_wait_timeout_sec": provider_timeout_sec if provider_timeout_sec else TEMP_WAIT_TIMEOUT_SEC,
                "temp_last_refresh_at": None,
                "temp_replace_enabled": False,
                "temp_codes": [],
                "temp_codes_count": 0,
                "temp_wait_state": "waiting_for_call" if number_mode == "voice" else "waiting",
                "temp_wait_started_at": now,
                "provisioning_state": "provisioned",
                "provisioned_at": now,
            },
        )
        await update_order_status(order_id, "success")
        await _log_number_event_from_order(
            {
                **order,
                "_id": order_id,
                "provider": provider_code,
                "provider_order_id": provider_order_id,
                "provider_number": number,
                "temp_country": None if country == "none" else country,
                "temp_state": None if state_code == "none" else state_code,
                "status": "paid",
            },
            "provider_buy_success",
            payload={"provider_pool": provider_pool},
            status_after="success",
            number_mode=number_mode,
        )

        await _log_temp_event(
            {
                "_id": order_id,
                "user_id": user_id,
                "provider": provider_code,
                "service_id": service_name,
            },
            "purchase_success",
            {
                "resend_enabled": True,
                "sale_price": final_price,
                "base_price": cost_price,
                "provider_order_id": str(provider_order_id),
                "provider_pool": provider_pool,
            },
        )

        # Reload order snapshot and start auto-wait flow.
        fresh_order = await get_order(order_id)
        if fresh_order and number_mode == "voice":
            await _queue_voice_waiter(bot=callback.message.bot, order=fresh_order, lang=lang)
        elif fresh_order:
            await _queue_temp_waiter(bot=callback.message.bot, order=fresh_order, lang=lang, is_second_code=False)
        await _best_effort_safe_edit_message(
            callback.message.bot,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=(
                _voice_waiting_text(
                    lang=lang,
                    provider_code=str(provider_code),
                    number=str(number),
                    interval_sec=int(interval_sec),
                    service_name=str(service_name or ""),
                )
                if number_mode == "voice"
                else _temp_waiting_text(
                    lang=lang,
                    provider_code=str(provider_code),
                    number=str(number),
                    country_code=str(country),
                    interval_sec=int(interval_sec),
                    elapsed_sec=0,
                    reuse_warranty_sec=reuse_warranty_sec,
                    service_name=str(service_name or ""),
                )
            ),
            reply_markup=None,
            parse_mode="HTML",
        )
        state_cleared = True
        inflight_locked = False
        await state.clear()
    except Exception as exc:
        err_text = _provider_error_text(exc)
        if _is_expected_provider_failure(exc):
            logger.warning("Provider buy failed for user %s: %s", user_id, err_text)
        else:
            logger.exception("Provider buy failed for user %s: %s", user_id, err_text)
        await _show_purchase_failed_then_main_menu(callback.message, state, lang)
        state_cleared = True
        inflight_locked = False
    finally:
        if inflight_locked and not state_cleared:
            await state.update_data(buy_confirm_inflight=False)


@router.callback_query(lambda c: c.data and c.data.startswith("temp:refresh:"))
async def temp_refresh_now(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await _safe_callback_answer(callback, t(lang, "order_not_found"), show_alert=True)
    if str(order.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)

    elapsed = _temp_elapsed_sec(order)
    if elapsed < TEMP_REFRESH_COOLDOWN_SEC:
        return await _safe_callback_answer(
            t(lang, "temp_refresh_wait").format(seconds=max(1, TEMP_REFRESH_COOLDOWN_SEC - elapsed)),
            show_alert=True,
        )
    cooldown_left = _temp_refresh_cooldown_left(order)
    if cooldown_left > 0:
        return await _safe_callback_answer(t(lang, "temp_refresh_wait").format(seconds=cooldown_left), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)

    sms_data = await _fetch_provider_sms(provider, provider_order_id)
    codes = set(str(x) for x in (order.get("temp_codes") or []) if x not in (None, ""))
    code = _extract_new_sms_code(sms_data.get("messages") or [], codes)
    if not code:
        now = _utc_now()
        await update_order_details(order_oid, {"temp_last_refresh_at": now})
        refreshed = await get_order(order_oid)
        if refreshed:
            await _sync_temp_wait_controls(callback.message.bot, refreshed, lang)
        await _log_temp_event(order, "manual_refresh_no_sms", {"cooldown_sec": TEMP_REFRESH_COOLDOWN_SEC})
        return await _safe_callback_answer_or_message(callback, t(lang, "temp_no_new_sms"), show_alert=True)

    now = _utc_now()
    code = _safe_code_text(code)
    updated_codes = list(codes)
    updated_codes.append(code)
    patch = {
        "temp_last_sms_at": now,
        "temp_last_code": code,
        "temp_codes": updated_codes,
        "temp_codes_count": len(updated_codes),
    }
    if not order.get("temp_first_sms_at"):
        patch["temp_first_sms_at"] = now
        seconds_to_first_sms = _seconds_between(now, order.get("created_at"))
        if seconds_to_first_sms is not None:
            patch["temp_seconds_to_first_sms"] = seconds_to_first_sms
    await update_order_details(
        order_oid,
        patch,
    )
    await _log_temp_event(order, "refresh_code_received", {"code_len": len(code)})
    refreshed_order = await get_order(order_oid) or order
    await _maybe_send_purchase_charge_confirmed_notice(
        bot=callback.message.bot,
        chat_id=callback.message.chat.id,
        order=refreshed_order,
        lang=lang,
        code=code,
    )
    await _safe_edit_message(
        callback.message.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=_temp_code_received_text(lang, code, refreshed_order),
        reply_markup=temp_code_received_kb(str(order_oid), lang=lang),
        parse_mode="HTML",
    )
    return await _safe_callback_answer_or_message(callback, t(lang, "ok_plain"))


@router.callback_query(lambda c: c.data and c.data.startswith("temp:cancel:"))
async def temp_cancel_and_refund(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)
    if _temp_elapsed_sec(order) < TEMP_CANCEL_AFTER_SEC:
        left = max(1, TEMP_CANCEL_AFTER_SEC - _temp_elapsed_sec(order))
        return await _safe_callback_answer(t(lang, "temp_cancel_wait").format(seconds=left), show_alert=True)

    result = await _cancel_and_refund_temp_order(
        order_id=order_oid,
        order=order,
        actor_user_id=callback.from_user.id,
        reason="user_after_timeout",
        require_no_sms=True,
    )
    if not result.get("success"):
        await update_order_details(order_oid, {"temp_replace_enabled": True})
        refreshed = await get_order(order_oid)
        if refreshed:
            await _sync_temp_wait_controls(callback.message.bot, refreshed, lang)
        if bool(result.get("retryable")):
            asyncio.create_task(
                _retry_temp_refund_until_success(
                    bot=callback.message.bot,
                    order_id=order_oid,
                    actor_user_id=int(callback.from_user.id),
                    lang=lang,
                    source_reason="user_cancel_refund",
                )
            )
            return await _safe_callback_answer(t(lang, "temp_cancel_retry_pending"), show_alert=True)
        return await _safe_callback_answer(t(lang, "temp_cancel_failed"), show_alert=True)

    await _safe_edit_message(
        callback.message.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=t(lang, "temp_cancelled_refunded"),
        reply_markup=_temp_post_refund_kb(str(order_oid), lang=lang, allow_replace=True),
    )
    return await _safe_callback_answer(t(lang, "ok_plain"))


async def _request_replacement_temp_number(
    *,
    callback: types.CallbackQuery,
    order_oid: ObjectId,
    order: dict,
    lang: str,
    provider_code: str,
    api_service: str,
    service_name: str,
    country: Any,
    state_code: Any,
    final_price: float,
    cost_price: float,
    source_reason: str,
) -> None:
    if not provider_code or not api_service:
        return await _safe_callback_answer(t(lang, "temp_replace_unavailable"), show_alert=True)

    if str(order.get("status") or "").lower() not in {"cancelled", "failed", "refunded", "expired"}:
        result = await _cancel_and_refund_temp_order(
            order_id=order_oid,
            order=order,
            actor_user_id=callback.from_user.id,
            reason=source_reason,
            require_no_sms=True,
        )
        if not result.get("success"):
            return await _safe_callback_answer(t(lang, "temp_cancel_failed"), show_alert=True)

    trust_gate = await _evaluate_temp_trust_gate(
        user_id=int(callback.from_user.id),
        service_id=service_name,
        provider_code=provider_code,
    )
    if not bool(trust_gate.get("allowed")):
        return await _safe_callback_answer(
            _trust_alert_text(
                lang,
                mode=str(trust_gate.get("mode") or "purchase"),
                wait_sec=int(trust_gate.get("wait_sec") or 0),
            ),
            show_alert=True,
        )

    bot_id = (await callback.message.bot.get_me()).id
    reseller_id = await _resolve_user_reseller(callback.from_user.id, bot_id)
    new_order = await create_order(
        user_id=callback.from_user.id,
        reseller_id=reseller_id,
        service_id=service_name,
        selling_price=final_price,
        base_price=cost_price,
    )
    new_order_id = new_order["_id"]
    await update_order_details(
        new_order_id,
        {
            "number_mode": "temp",
            "telegram_bot_id": int(bot_id),
            "provisioning_state": "awaiting_charge",
            "provisioning_provider": str(provider_code),
            "provisioning_service": str(api_service),
            "provisioning_country": country,
            "provisioning_state_code": state_code,
            "provisioning_created_at": _utc_now(),
            "temp_retry_source_order_id": str(order_oid),
            "temp_retry_reason": source_reason,
        },
    )
    ok, msg = await FinancialManager.process_core_purchase(
        user_id=callback.from_user.id,
        order_id=new_order_id,
        sale_price=final_price,
        cost_price=cost_price,
        reseller_id=reseller_id,
    )
    if not ok:
        await update_order_status(new_order_id, "failed")
        return await _safe_callback_answer(finance_error_public_text(lang, str(msg)), show_alert=True)

    await update_order_details(
        new_order_id,
        {
            "provisioning_state": "charged_pending_provider",
            "provisioning_charged_at": _utc_now(),
        },
    )
    purchase_options = {
        "reuse_mode": True,
        "_audit_requested_service": str(order.get("temp_service_key") or order.get("service_id") or ""),
        "retry_reason": source_reason,
    }
    buy_res = await buy_number_from_provider(
        provider_code=provider_code,
        api_service_name=api_service,
        country=country,
        state=state_code,
        dry_run=False,
        purchase_options=purchase_options,
    )
    if not buy_res or not buy_res.get("success"):
        refund_ok, _refund_msg = await FinancialManager.refund_core_purchase(
            callback.from_user.id,
            new_order_id,
            final_price,
            cost_price,
            reseller_id=reseller_id,
        )
        await update_order_details(
            new_order_id,
            {
                "provisioning_state": "provider_failed_refunded" if refund_ok else "provider_failed_refund_error",
                "provisioning_failure_at": _utc_now(),
            },
        )
        await update_order_status(new_order_id, "refunded" if refund_ok else "failed")
        return await _safe_callback_answer(t(lang, "temp_replace_failed"), show_alert=True)

    interval_sec = _poll_interval_for_provider(provider_code)
    provider_timeout_sec = _extract_provider_wait_timeout_sec(buy_res)
    if provider_timeout_sec:
        provider_timeout_sec = min(TEMP_WAIT_TIMEOUT_SEC, int(provider_timeout_sec))
    now = _utc_now()
    reuse_warranty_sec = _resolve_reuse_warranty_sec(provider_code, buy_res)
    reuse_until = datetime.fromtimestamp(now.timestamp() + int(reuse_warranty_sec), tz=UTC)

    await update_order_details(
        new_order_id,
        {
            "provider_order_id": str(buy_res.get("order_id") or ""),
            "provider": provider_code,
            "provider_number": str(buy_res.get("number") or ""),
            "provider_pool": str(buy_res.get("pool") or "").strip() or None,
            "number_mode": "temp",
            "temp_api_service": api_service,
            "temp_country": country,
            "temp_state": state_code,
            "temp_service_key": service_name,
            "temp_reuse_warranty_until": reuse_until,
            "temp_reuse_warranty_sec": reuse_warranty_sec,
            "temp_wait_chat_id": callback.message.chat.id,
            "temp_wait_message_id": callback.message.message_id,
            "temp_wait_bot_id": int(bot_id),
            "temp_wait_interval_sec": interval_sec,
            "temp_wait_timeout_sec": provider_timeout_sec if provider_timeout_sec else TEMP_WAIT_TIMEOUT_SEC,
            "temp_last_refresh_at": None,
            "temp_replace_enabled": False,
            "temp_codes": [],
            "temp_codes_count": 0,
            "provisioning_state": "provisioned",
            "provisioned_at": _utc_now(),
        },
    )
    await update_order_status(new_order_id, "success")
    await _safe_edit_message(
        callback.message.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=_temp_waiting_text(
            lang=lang,
            provider_code=provider_code,
            number=str(buy_res.get("number") or ""),
            country_code=str(country),
            interval_sec=interval_sec,
            elapsed_sec=0,
            reuse_warranty_sec=reuse_warranty_sec,
            service_name=str(service_name or ""),
        ),
        reply_markup=None,
        parse_mode="HTML",
    )
    fresh = await get_order(new_order_id)
    if fresh:
        await _queue_temp_waiter(bot=callback.message.bot, order=fresh, lang=lang, is_second_code=False)
    return await _safe_callback_answer(t(lang, "temp_replace_success"), show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("temp:replace:"))
async def temp_replace_number(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)
    if _temp_order_has_received_code(order):
        return await _safe_callback_answer(t(lang, "temp_second_code_failed"), show_alert=True)

    replacement = _shared_temp_replacement_fields(order)
    provider_code = str(replacement.get("provider") or "")
    api_service = str(replacement.get("api_service") or "")
    service_name = str(replacement.get("service") or "")
    country = replacement.get("raw_country")
    state_code = replacement.get("raw_state")
    final_price, cost_price = extract_order_amounts(order)

    return await _request_replacement_temp_number(
        callback=callback,
        order_oid=order_oid,
        order=order,
        lang=lang,
        provider_code=provider_code,
        api_service=api_service,
        service_name=service_name,
        country=country,
        state_code=state_code,
        final_price=final_price,
        cost_price=cost_price,
        source_reason="replace_request",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("temp:alt:"))
async def temp_try_alternate_provider(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)
    if _temp_order_has_received_code(order):
        return await _safe_callback_answer(t(lang, "temp_second_code_failed"), show_alert=True)

    replacement = _shared_temp_replacement_fields(order)
    service_name = str(replacement.get("service") or "")
    country = replacement.get("raw_country")
    state_code = replacement.get("raw_state")
    current_provider = str(replacement.get("provider") or "")
    if not service_name:
        return await _safe_callback_answer(t(lang, "temp_replace_unavailable"), show_alert=True)

    prices = await get_all_prices(service_name, country, state_code)
    picked = _pick_retry_provider(prices, exclude_provider=current_provider)
    if not picked:
        return await _safe_callback_answer(
            _numbers_text(lang, "No alternate provider is available for this choice.", "لا يوجد مزود بديل متاح لهذا الخيار."),
            show_alert=True,
        )
    provider_code, provider_info = picked
    try:
        final_price = float(provider_info.get("price") or 0)
    except Exception:
        final_price = 0.0
    try:
        cost_price = float(provider_info.get("base_price") or final_price)
    except Exception:
        cost_price = final_price
    api_service = str(provider_info.get("api_service_name") or "").strip()
    if final_price <= 0 or not api_service:
        return await _safe_callback_answer(t(lang, "temp_replace_unavailable"), show_alert=True)

    return await _request_replacement_temp_number(
        callback=callback,
        order_oid=order_oid,
        order=order,
        lang=lang,
        provider_code=provider_code,
        api_service=api_service,
        service_name=service_name,
        country=country,
        state_code=state_code,
        final_price=final_price,
        cost_price=cost_price,
        source_reason="alternate_provider_request",
    )


def _second_code_log_payload(order: dict, *, now: datetime, extra: dict | None = None) -> dict:
    payload = {
        "provider": str(order.get("provider") or ""),
        "provider_order_id": str(order.get("provider_order_id") or ""),
        "seconds_since_purchase": _seconds_between(now, order.get("created_at")),
        "seconds_since_first_code": _seconds_between(now, order.get("temp_first_sms_at")),
        "seconds_since_last_sms": _seconds_between(now, order.get("temp_last_sms_at")),
        "seconds_since_previous_second_code": _seconds_between(now, order.get("temp_second_code_last_at")),
        "resend_retention_expires_at": (
            _temp_my_numbers_expires_at(order).isoformat() if _temp_my_numbers_expires_at(order) else None
        ),
        "resend_guarantee_seconds": _order_reuse_warranty_sec(order),
        "codes_count_before": int(order.get("temp_codes_count") or len(order.get("temp_codes") or []) or 0),
    }
    if extra:
        payload.update(extra)
    return payload


@router.callback_query(lambda c: c.data and c.data.startswith("temp:second:"))
async def temp_second_code(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)

    bot_id = (await callback.message.bot.get_me()).id
    reseller_id = await _resolve_user_reseller(callback.from_user.id, bot_id)
    result = await _shared_request_second_code_for_order(
        order_id=order_oid,
        order=order,
        user_id=int(callback.from_user.id),
        reseller_id=int(reseller_id),
        providers=PROVIDERS,
        provider_resend_fn=lambda _providers, provider, provider_order_id: _provider_resend(provider, provider_order_id),
        financial_manager=FinancialManager,
        create_order_fn=create_order,
        update_order_details_fn=update_order_details,
        update_order_status_fn=update_order_status,
        get_order_fn=get_order,
        log_temp_event_fn=_log_temp_event,
        temp_resend_available_fn=_temp_resend_available,
        second_code_price_fn=lambda item: (
            round(max(0.0, extract_order_amounts(item)[0]) / 2.0, 4),
            round(max(0.0, extract_order_amounts(item)[1]) / 2.0, 4),
        ),
        second_code_log_payload_fn=_second_code_log_payload,
        source="telegram",
        telegram_bot_id=int(bot_id),
        refresh_order_fn=None,
    )
    if not result.get("ok"):
        if str(result.get("code") or "") == "finance_error":
            return await _safe_callback_answer_or_message(
                callback,
                finance_error_public_text(lang, str(result.get("finance_message") or "")),
                show_alert=True,
            )
        if str(result.get("code") or "") == "order_not_found":
            return await _safe_callback_answer(t(lang, "order_not_found"), show_alert=True)
        return await _safe_callback_answer_or_message(callback, t(lang, "temp_second_code_failed"), show_alert=True)

    refreshed = result.get("order") if isinstance(result.get("order"), dict) else await get_order(order_oid)
    if refreshed:
        await _queue_temp_waiter(bot=callback.message.bot, order=refreshed, lang=lang, is_second_code=True)
    provider = str(result.get("provider") or order.get("provider") or "")
    new_provider_number = str(result.get("new_provider_number") or order.get("provider_number") or "-")
    await _best_effort_safe_edit_message(
        callback.message.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=_temp_waiting_text(
            lang=lang,
            provider_code=provider,
            number=new_provider_number,
            country_code=str(order.get("temp_country") or ""),
            interval_sec=_poll_interval_for_provider(provider),
            elapsed_sec=0,
            reuse_warranty_sec=_order_reuse_warranty_sec(order),
            service_name=str(order.get("temp_service_key") or order.get("service_id") or ""),
        ),
        reply_markup=None,
        parse_mode="HTML",
    )
    return await _safe_callback_answer_or_message(
        callback,
        t(lang, "temp_second_code_done").format(amount=float(result.get("extra_sale") or 0.0)),
        show_alert=True,
    )

@router.callback_query(lambda c: c.data == "buy:cancel")
async def cancel_buy(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    user_id = callback.from_user.id
    res = await reservations_repo.get_reservation_by_message(
        callback.message.chat.id,
        callback.message.message_id,
    )
    if not res or res.get("status") != "reserved":
        await _return_to_main_menu_from_buy(callback, state, lang)
        await _safe_callback_answer(callback)
        return
    if int(res.get("user_id") or 0) != int(user_id):
        await _safe_callback_answer(callback, t(lang, "order_not_found"), show_alert=True)
        return

    order_id = res.get("order_id")
    order = await get_order(order_id)
    if not order:
        await _safe_callback_answer(callback, t(lang, "order_not_found"), show_alert=True)
        return
    order_user_id = int(order.get("user_id") or 0)
    if order_user_id != int(user_id):
        await _safe_callback_answer(callback, t(lang, "order_not_found"), show_alert=True)
        return

    sale_price, cost_price = extract_order_amounts(order)
    provider = order.get("provider")
    provider_order_id = order.get("provider_order_id")

    if provider and provider_order_id:
        prov = PROVIDERS.get(provider)
        if prov and hasattr(prov, "cancel"):
            try:
                await prov.cancel(provider_order_id)
            except Exception:
                pass

    refund_ok, refund_msg = await FinancialManager.refund_core_purchase(
        order_user_id,
        order_id,
        sale_price,
        cost_price,
        reseller_id=int(order.get("reseller_id") or order_user_id),
    )
    if not refund_ok:
        await callback.message.edit_text(
            t(lang, "numbers_refund_failed_notice").format(error=str(refund_msg))
        )
        await _safe_callback_answer(callback, t(lang, "numbers_refund_failed_short"), show_alert=True)
        return
    await reservations_repo.release_reservation(order_id)
    await update_order_status(order_id, "cancelled")
    await callback.message.edit_text(t(lang, "order_cancelled_refunded"))
    await state.set_state(NumberFlow.service)


@router.callback_query(lambda c: c.data and (c.data.startswith("buy:resend:") or c.data.startswith("num_resend_")))
async def resend_code(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")

    if callback.data.startswith("buy:resend:"):
        raw_id = callback.data.split(":", 2)[2]
    else:
        raw_id = callback.data.replace("num_resend_", "")
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await _safe_callback_answer(callback, t(lang, "order_not_found"), show_alert=True)
    if str(order.get("number_mode") or "").lower() == "temp":
        return await _safe_callback_answer(callback, t(lang, "temp_second_code"), show_alert=True)
    provider = order.get("provider")
    provider_order_id = order.get("provider_order_id")
    if not provider or not provider_order_id:
        return await _safe_callback_answer(callback, t(lang, "cannot_resend"), show_alert=True)

    prov = PROVIDERS.get(provider)
    if not prov or not hasattr(prov, "resend"):
        return await _safe_callback_answer(callback, t(lang, "service_no_resend"), show_alert=True)

    try:
        ok = await prov.resend(provider_order_id)
        if ok:
            return await _safe_callback_answer(callback, t(lang, "resend_requested"), show_alert=True)
    except Exception:
        pass
    return await _safe_callback_answer(callback, t(lang, "resend_failed"), show_alert=True)




