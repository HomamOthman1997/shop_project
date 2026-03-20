import asyncio
import html
import logging
import re
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bson import ObjectId

from config import settings
from database import reservations_repo
from database import temp_number_stats_repo
from database import number_events_repo
from database.bots_repo import get_reseller_id_for_bot
from database.orders_repo import (
    create_order,
    extract_order_amounts,
    get_order,
    list_open_rental_orders_without_sms,
    list_open_temp_orders_for_recovery,
    list_paid_number_orders_missing_provider,
    list_user_open_temp_orders,
    list_user_open_rental_orders_without_sms,
    list_user_rental_orders,
    update_order_details,
    update_order_status,
)
from database.user_repo import get_user, get_user_reseller_for_bot, set_user_reseller_for_bot
from database.financial_ledger import get_user_wallet_balance
from keyboards.main_menu_kb import main_menu
from keyboards.reseller_main_menu import reseller_main_menu
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.keyboards.core_numbers_kb import (
    confirm_buy_kb,
    temp_code_received_kb,
    temp_wait_timeout_kb,
    rental_confirm_kb,
    rental_home_kb,
    rental_providers_kb,
    rental_warning_kb,
    service_kb,
    tv_renewable_kb,
)
from services.numbers.manager import (
    PROVIDERS,
    buy_number_from_provider,
    finish_rental_from_provider,
    get_rental_info_from_provider,
    get_rental_sms_from_provider,
    notes_tags_from_provider,
    rent_number_from_provider,
    renew_rental_from_provider,
    wake_rental_from_provider,
)
from services.numbers.states.core_numbers_states import NumberFlow
from utils.financial_manager import FinancialManager
from utils.permissions import is_reseller
from utils.provider_alias import provider_generic_error, provider_public_id
from utils.translations import t

logger = logging.getLogger("numbers_buy")
router = Router()

TEMP_WAIT_TIMEOUT_SEC = 300
TEMP_PROVIDER_SAFETY_BUFFER_SEC = 60
TEMP_CANCEL_AFTER_SEC = 180
TEMP_REFRESH_COOLDOWN_SEC = 60
TEMP_REFUND_RETRY_INTERVAL_SEC = 45
TEMP_REFUND_RETRY_WINDOW_SEC = 900
HERO_RENTAL_CANCEL_WINDOW_SEC = 1200
RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC = 1800
RENTAL_OWNER_ALERT_WINDOW_SEC = 180
TEMP_REUSE_WARRANTY_FALLBACK_SEC = 900
TEMP_REUSE_WARRANTY_SEC_BY_PROVIDER = {}
TEMP_POLL_INTERVALS = {
    "smsman": 6,
    "smspool": 8,
    "textverified": 8,
    "herosms": 7,
    "telabot": 10,
}

_COUNTRY_NAME_BY_CODE = {
    str(item.get("code") or "").strip(): str(item.get("name") or "").strip()
    for item in COUNTRIES_LIST
    if str(item.get("code") or "").strip()
}

_TEMP_WARRANTY_SECONDS_KEYS = (
    "reuse_warranty_sec",
    "warranty_sec",
    "expires_in",
    "expiresin",
    "expires_in_seconds",
    "expiresinseconds",
    "expiration_seconds",
    "ttl",
    "ttl_sec",
    "time_to_live",
    "valid_for_sec",
    "validforsec",
)
_TEMP_WARRANTY_EPOCH_KEYS = (
    "expires_at",
    "expiresat",
    "expiration_at",
    "expirationat",
    "valid_until",
    "validuntil",
    "expire_at",
    "expireat",
)
_TEMP_WARRANTY_TEXT_KEYS = (
    "reuse_warranty",
    "warranty",
    "valid_for",
    "expires_in_human",
)


def _main_reseller_bot_link() -> str | None:
    username = str(settings.main_reseller_bot_username or "").strip().lstrip("@")
    if not username:
        return None
    return f"https://t.me/{username}"


def _rental_provider_period_title(lang: str) -> str:
    if str(lang or "").lower().startswith("ar"):
        return "اختر المزود ومدة الرقم"
    return "Choose rental provider and period"


def _rental_server_warning_lines(lang: str) -> list[str]:
    if str(lang or "").lower().startswith("ar"):
        return [
            "تنبيه مهم:",
            "- Server 1 لا يدعم تحديد الولاية.",
            "- Server 2 يدعم تحديد الولاية، واختيار ولاية يضيف +2$.",
        ]
    return [
        "Important notice:",
        "- Server 1 does not support state targeting.",
        "- Server 2 supports state targeting; selecting a state adds +2$.",
    ]


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
    code = str(provider_code or "").strip().lower()
    if code == "herosms":
        return "protected"
    return "uncertain"


def _rental_refund_warning_text(
    lang: str,
    *,
    provider_code: str | None,
    selected_option: dict | None = None,
) -> str:
    provider_label = provider_public_id(provider_code)
    kind = _rental_refund_warning_kind(provider_code, selected_option)
    is_ar = str(lang or "").lower().startswith("ar")
    if is_ar:
        heading_map = {
            "protected": "تحذير قبل الشراء:",
            "uncertain": "تنبيه قبل الشراء:",
            "non_refundable": "تحذير مهم:",
        }
        body_map = {
            "protected": (
                "هذا الرقم يمكن طلب استرجاعه فقط إذا لم يصل أي كود، "
                "وإذا ظل المزود يسمح بالإلغاء قبل انتهاء مهلة الحماية."
            ),
            "uncertain": (
                "إمكانية الاسترجاع غير مضمونة بعد الشراء، وتعتمد على سياسة المزود "
                "وحالة الرقم بعد تنفيذ الطلب."
            ),
            "non_refundable": (
                "هذا الرقم غير قابل للاسترجاع بعد الشراء. أكمل فقط إذا كنت متأكدًا من المتابعة."
            ),
        }
        footer = "هل تريد المتابعة بالشراء؟"
    else:
        heading_map = {
            "protected": "Refund notice:",
            "uncertain": "Important notice:",
            "non_refundable": "Non-refundable warning:",
        }
        body_map = {
            "protected": (
                "Refund is only possible if no SMS arrives and the provider still allows cancellation "
                "before the protection cutoff."
            ),
            "uncertain": (
                "Refund is not guaranteed after purchase and depends on provider policy and the number state "
                "after the order is created."
            ),
            "non_refundable": (
                "This rental is not refundable after purchase. Continue only if you are sure you want to proceed."
            ),
        }
        footer = "Do you want to continue with the purchase?"
    return "\n".join(
        [
            heading_map[kind],
            f"Provider: {provider_label}",
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
            f"{t(lang, 'rental_duration_label')}: {duration_text}",
            f"{t(lang, 'rental_renewable_label')}: {_bool_text(renewable, lang)}",
            f"{t(lang, 'rental_billing_cycle_label')}: {billing_cycle}",
            f"{t(lang, 'price_label')}: {float(selected_option.get('price', 0)):.2f}$",
            "",
            *_rental_server_warning_lines(lang),
            "",
            t(lang, "confirm_purchase_question"),
        ]
    )
    return "\n".join(lines)


def _purchase_refunded_notice_text(lang: str, *, amount: float, balance: float) -> str:
    if str(lang or "").lower().startswith("ar"):
        return (
            f"لم يتم تثبيت أي خصم عليك، وتمت إعادة {float(amount):.2f}$ إلى رصيدك المتاح.\n"
            f"الرصيد الحالي: {float(balance):.2f}$"
        )
    return (
        f"No final charge was kept. {float(amount):.2f}$ was returned to your available balance.\n"
        f"Current balance: {float(balance):.2f}$"
    )


def _purchase_charge_confirmed_notice_text(lang: str, *, amount: float, balance: float) -> str:
    if str(lang or "").lower().startswith("ar"):
        return (
            f"تم تثبيت الخصم بعد وصول الكود: {float(amount):.2f}$\n"
            f"الرصيد الحالي: {float(balance):.2f}$"
        )
    return (
        f"Charge confirmed after code arrival: {float(amount):.2f}$\n"
        f"Current balance: {float(balance):.2f}$"
    )


def _country_display_name(country_value: Any, *, country_name: str | None = None) -> str:
    direct_name = str(country_name or "").strip()
    if direct_name:
        return direct_name
    raw = str(country_value or "").strip()
    if not raw:
        return "-"
    code = "".join(ch for ch in raw if ch.isdigit())
    if code and code in _COUNTRY_NAME_BY_CODE:
        return _COUNTRY_NAME_BY_CODE[code]
    return raw


def _order_bot_id(order: dict | None) -> int | None:
    order = order or {}
    raw = order.get("telegram_bot_id")
    try:
        if raw is None:
            return None
        return int(raw)
    except Exception:
        return None


def _split_number_for_copy(raw_number: str | None, country_code: str | None) -> tuple[str | None, str]:
    raw = str(raw_number or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit()) or raw
    cc = "".join(ch for ch in str(country_code or "").strip() if ch.isdigit())
    if cc and 1 <= len(cc) <= 4 and isinstance(digits, str) and digits:
        if digits.startswith(cc) and len(digits) > len(cc):
            local_digits = digits[len(cc):]
        else:
            local_digits = digits
        if local_digits:
            return cc, local_digits
    return None, raw if raw else str(digits)


def _format_number_for_copy_html(raw_number: str | None, country_code: str | None) -> str:
    cc, local = _split_number_for_copy(raw_number, country_code)
    if cc:
        return f"+{cc} <code>{html.escape(local)}</code>"
    return f"<code>{html.escape(local)}</code>"


def _format_number_for_copy_text(raw_number: str | None, country_code: str | None) -> str:
    cc, local = _split_number_for_copy(raw_number, country_code)
    if cc:
        return f"+{cc} {local}"
    return local


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
    kb.inline_keyboard.append([InlineKeyboardButton(text=t(lang, "rental_my_numbers"), callback_data="flow:rental:my")])
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
    if str(lang or "").lower().startswith("ar"):
        if count > 1:
            return (
                f"لديك {count} أرقام رينتال نشطة ولم يتم رصد أي SMS لها بعد.\n\n"
                f"آخر مزود: {provider_label}\n"
                "هل تريد الاحتفاظ بها أم إلغاءها واسترجاع الرصيد؟"
            )
        return (
            "لديك رقم رينتال نشط ولم يتم رصد أي SMS له بعد.\n\n"
            f"المزود: {provider_label}\n"
            "هل تريد الاحتفاظ به أم إلغاءه واسترجاع الرصيد؟"
        )
    if count > 1:
        return (
            f"You still have {count} active rental numbers and no SMS has been detected yet.\n\n"
            f"Latest provider: {provider_label}\n"
            "Do you want to keep the numbers or cancel them and refund the balance?"
        )
    return (
        "You still have an active rental number and no SMS has been detected yet.\n\n"
        f"Provider: {provider_label}\n"
        "Do you want to keep the number or cancel it and refund the balance?"
    )


async def _return_to_main_menu_from_buy(callback: types.CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.clear()
    if not callback.message:
        return
    bot_id = (await callback.bot.get_me()).id
    try:
        await callback.message.delete()
    except Exception:
        pass

    if await is_reseller(callback.from_user.id, bot_id=bot_id):
        await callback.message.answer(t(lang, "main_menu"), reply_markup=reseller_main_menu(lang))
    else:
        await callback.message.answer(t(lang, "main_menu"), reply_markup=main_menu(lang))


async def _show_main_menu_message(message: types.Message, user_id: int, lang: str) -> None:
    bot_id = (await message.bot.get_me()).id
    if await is_reseller(user_id, bot_id=bot_id):
        await message.answer(t(lang, "main_menu"), reply_markup=reseller_main_menu(lang))
    else:
        await message.answer(t(lang, "main_menu"), reply_markup=main_menu(lang))


async def _return_after_rental_exit_message(
    message: types.Message,
    state: FSMContext,
    *,
    target: str,
    lang: str,
) -> None:
    await state.clear()
    await _show_main_menu_message(message, int(message.from_user.id), lang)


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
            notice = (
                f"{result.get('success_count')} rental number(s) were cancelled automatically and refunded."
                if not str(lang).lower().startswith("ar")
                else f"?? ????? {result.get('success_count')} ?? ????? ???????? ??????? ?????? ??????."
            )
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
        await callback.answer()
        if result.get("success_count"):
            notice = (
                f"{result.get('success_count')} rental number(s) were cancelled automatically and refunded."
                if not str(lang).lower().startswith("ar")
                else f"?? ????? {result.get('success_count')} ?? ????? ???????? ??????? ?????? ??????."
            )
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
    await callback.answer()
    return True


def _bool_text(value: bool, lang: str) -> str:
    return t(lang, "yes") if bool(value) else t(lang, "no")


def _as_float(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _as_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_utc_datetime(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _coerce_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _to_utc_datetime(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    return _to_utc_datetime(parsed)


def _seconds_between(later: datetime | None, earlier: datetime | None) -> int | None:
    later_dt = _to_utc_datetime(later)
    earlier_dt = _to_utc_datetime(earlier)
    if not later_dt or not earlier_dt:
        return None
    return int((later_dt - earlier_dt).total_seconds())


def _seconds_left_until(value: datetime | None) -> int:
    target = _to_utc_datetime(value)
    if not target:
        return 0
    return max(0, int((target - _utc_now()).total_seconds()))


def _format_wait_time_short(seconds: int) -> str:
    sec = max(0, int(seconds or 0))
    minutes = (sec + 59) // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m" if mins else f"{hours}h"


def _trust_alert_text(lang: str, *, mode: str, wait_sec: int) -> str:
    wait_txt = _format_wait_time_short(wait_sec)
    if mode == "active_order":
        if str(lang or "en").lower().startswith("ar"):
            return (
                "???? ??? ??? ???? ??? ??? ???? ?????? ???????.\n"
                "???? ?????? ?????? ???? ??? ????? ???? ?????."
            )
        return (
            "You already have an active temp-number request.\n"
            "Open Numbers and finish or cancel it before requesting another number."
        )
    if str(lang or "en").lower().startswith("ar"):
        return (
            "???? ????? ???? ??? ??? ??????? ???? ???? ??????/??????? ???? ??? ??????.\n"
            f"???? ???????? {wait_txt} ?? ????? ????????."
        )
    return (
        "Too many recent no-code attempts for this service/server.\n"
        f"Please wait {wait_txt} and try again."
    )


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
        if str(item.get("temp_wait_state") or "").lower() in {"waiting", "code_received", "refund_pending"}
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


def _provider_default_reuse_warranty_sec(provider_code: str | None) -> int:
    code = str(provider_code or "").strip().lower()
    return int(TEMP_REUSE_WARRANTY_SEC_BY_PROVIDER.get(code, TEMP_REUSE_WARRANTY_FALLBACK_SEC))


def _normalize_warranty_sec(value: int | float | None) -> int | None:
    if value is None:
        return None
    sec = _as_int(value, 0)
    if sec <= 0:
        return None
    # Keep temp warranty bounded to a sane range for UI and storage.
    sec = max(60, min(sec, 7 * 24 * 3600))
    return sec


def _seconds_until_timestamp(raw_value, now_ts: float) -> int | None:
    if raw_value in (None, ""):
        return None
    ts_value: float | None = None
    if isinstance(raw_value, (int, float)):
        ts_value = float(raw_value)
    elif isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return None
        if re.fullmatch(r"-?\d+(\.\d+)?", text):
            try:
                ts_value = float(text)
            except Exception:
                ts_value = None
        else:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                ts_value = parsed.timestamp()
            except Exception:
                ts_value = None
    if ts_value is None:
        return None
    # Support millisecond timestamps.
    if ts_value > 10_000_000_000:
        ts_value = ts_value / 1000.0
    delta = int(ts_value - now_ts)
    if delta <= 0:
        return None
    return delta


def _seconds_from_text(raw_value) -> int | None:
    text = str(raw_value or "").strip().lower()
    if not text:
        return None
    patterns = (
        (r"(\d+)\s*(?:seconds?|secs?|s)\b", 1),
        (r"(\d+)\s*(?:minutes?|mins?|m)\b", 60),
        (r"(\d+)\s*(?:hours?|hrs?|h)\b", 3600),
        (r"(\d+)\s*(?:days?|d)\b", 24 * 3600),
    )
    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            value = int(match.group(1))
        except Exception:
            continue
        if value > 0:
            return value * multiplier
    return None


def _extract_explicit_reuse_warranty_sec(payload) -> int | None:
    if payload in (None, ""):
        return None
    now_ts = _utc_now().timestamp()
    queue = [payload]
    seen: set[int] = set()

    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            current_id = id(current)
            if current_id in seen:
                continue
            seen.add(current_id)
            for key, value in current.items():
                key_norm = str(key or "").strip().lower()
                if key_norm in _TEMP_WARRANTY_SECONDS_KEYS:
                    sec = _normalize_warranty_sec(_as_int(value, 0))
                    if sec:
                        return sec
                if key_norm in _TEMP_WARRANTY_EPOCH_KEYS:
                    sec = _normalize_warranty_sec(_seconds_until_timestamp(value, now_ts))
                    if sec:
                        return sec
                if key_norm in _TEMP_WARRANTY_TEXT_KEYS:
                    sec = _normalize_warranty_sec(_seconds_from_text(value))
                    if sec:
                        return sec
                if isinstance(value, (dict, list)):
                    queue.append(value)
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    queue.append(item)

    return None


def _resolve_reuse_warranty_sec(provider_code: str | None, buy_response: dict | None = None) -> int:
    # Unified policy: fixed 15-minute reuse warranty for all providers.
    # Keep provider payload warranty hints ignored to avoid inconsistent UX.
    return _provider_default_reuse_warranty_sec(provider_code)


def _warranty_minutes_text_value(warranty_sec: int | None) -> int:
    sec = _normalize_warranty_sec(warranty_sec)
    if not sec:
        sec = TEMP_REUSE_WARRANTY_FALLBACK_SEC
    return max(1, (int(sec) + 59) // 60)


def _order_reuse_warranty_sec(order: dict | None) -> int:
    order = order or {}
    sec = _normalize_warranty_sec(_as_int(order.get("temp_reuse_warranty_sec"), 0))
    if sec:
        return sec

    created_at = _to_utc_datetime(order.get("created_at"))
    warranty_until = _to_utc_datetime(order.get("temp_reuse_warranty_until"))
    if created_at and warranty_until:
        derived = _normalize_warranty_sec(int((warranty_until - created_at).total_seconds()))
        if derived:
            return derived

    fallback = _provider_default_reuse_warranty_sec(order.get("provider"))
    return int(_normalize_warranty_sec(fallback) or TEMP_REUSE_WARRANTY_FALLBACK_SEC)


def _temp_reuse_policy_text(lang: str, warranty_sec: int | None) -> str:
    minutes = _warranty_minutes_text_value(warranty_sec)
    line_1 = t(lang, "temp_reuse_warranty_line").format(minutes=minutes)
    line_2 = t(lang, "temp_reuse_resend_note")
    line_3 = t(lang, "temp_reuse_cost_note")
    return f"{line_1}\n{line_2}\n{line_3}"


def _temp_waiting_text(
    *,
    lang: str,
    provider_code: str,
    number: str,
    country_code: str | None,
    interval_sec: int,
    elapsed_sec: int = 0,
    reuse_warranty_sec: int | None = None,
) -> str:
    provider_public = provider_public_id(provider_code)
    provider_label = provider_public
    if provider_public.upper().startswith("S") and provider_public[1:].isdigit():
        provider_label = f"Server{provider_public[1:]}"

    raw_number = str(number or "").strip()
    digits = "".join(ch for ch in raw_number if ch.isdigit()) or raw_number
    cc = "".join(ch for ch in str(country_code or "").strip() if ch.isdigit())
    if cc and 1 <= len(cc) <= 4 and isinstance(digits, str) and digits:
        if digits.startswith(cc) and len(digits) > len(cc):
            local_digits = digits[len(cc):]
        else:
            local_digits = digits
        pretty_number = f"+{cc} {local_digits}".strip()
    else:
        pretty_number = raw_number if raw_number else str(digits)

    # UX: show a calm synthetic progress counter and freeze it once cancel becomes available.
    shown_elapsed = min(max(0, int(elapsed_sec or 0)), TEMP_CANCEL_AFTER_SEC)
    refresh_count = max(0, int(shown_elapsed // 30))
    number_mono = _format_number_for_copy_html(pretty_number, country_code)
    text = t(lang, "temp_waiting_code").format(
        provider=provider_label,
        number=number_mono,
        refreshes=refresh_count,
    )
    return f"{text}\n{_temp_reuse_policy_text(lang, reuse_warranty_sec)}"


def _temp_code_received_text(lang: str, code: str, order: dict | None = None) -> str:
    order = order or {}
    number_value = _format_number_for_copy_html(
        str(order.get("provider_number") or "").strip(),
        str(order.get("temp_country") or "").strip(),
    )
    service_value = str(order.get("temp_service_key") or order.get("service_id") or "-")
    code_value = _safe_code_text(code)
    text = t(lang, "temp_code_received_block").format(
        number=number_value,
        service=html.escape(service_value),
        code=f"<code>{html.escape(code_value)}</code>",
    )
    return f"{text}\n{_temp_reuse_policy_text(lang, _order_reuse_warranty_sec(order))}"


def _poll_interval_for_provider(provider_code: str) -> int:
    return int(TEMP_POLL_INTERVALS.get(str(provider_code or "").lower(), 8))


def _parse_provider_dt(raw_value) -> datetime | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    candidates = (
        text,
        text.replace("Z", "+00:00"),
        text.replace(" ", "T"),
        text.replace(" ", "T").replace("Z", "+00:00"),
    )
    for item in candidates:
        try:
            dt = datetime.fromisoformat(item)
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except Exception:
            continue
    return None


def _extract_provider_wait_timeout_sec(buy_res: dict | None) -> int | None:
    if not isinstance(buy_res, dict):
        return None
    raw = buy_res.get("raw")
    if not isinstance(raw, dict):
        return None
    started = _parse_provider_dt(raw.get("activationTime"))
    ended = _parse_provider_dt(raw.get("activationEndTime"))
    if not started or not ended:
        return None
    duration = int((ended - started).total_seconds())
    if duration <= 0:
        return None
    safe_duration = max(60, duration - TEMP_PROVIDER_SAFETY_BUFFER_SEC)
    return safe_duration


def _order_temp_timeout_sec(order: dict | None) -> int:
    if not isinstance(order, dict):
        return TEMP_WAIT_TIMEOUT_SEC
    try:
        sec = int(order.get("temp_wait_timeout_sec") or 0)
    except Exception:
        sec = 0
    return sec if sec > 0 else TEMP_WAIT_TIMEOUT_SEC


def _temp_elapsed_sec(order: dict, now: datetime | None = None) -> int:
    now_dt = _to_utc_datetime(now) or _utc_now()
    started_at = _to_utc_datetime(order.get("temp_wait_started_at") or order.get("created_at")) or now_dt
    return max(0, int((now_dt - started_at).total_seconds()))


def _temp_refresh_cooldown_left(order: dict, now: datetime | None = None) -> int:
    now_dt = _to_utc_datetime(now) or _utc_now()
    last_refresh = _to_utc_datetime(order.get("temp_last_refresh_at"))
    if not last_refresh:
        return 0
    delta = int((now_dt - last_refresh).total_seconds())
    return max(0, TEMP_REFRESH_COOLDOWN_SEC - delta)


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
    rows.append([InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="flow:main:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _sync_temp_wait_controls(bot, order: dict, lang: str):
    chat_id = int(order.get("temp_wait_chat_id") or 0)
    msg_id = int(order.get("temp_wait_message_id") or 0)
    if not chat_id or not msg_id:
        return
    elapsed = _temp_elapsed_sec(order)
    timeout_sec = _order_temp_timeout_sec(order)
    text = t(lang, "temp_no_code_timeout") if elapsed >= timeout_sec else _temp_waiting_text(
        lang=lang,
        provider_code=str(order.get("provider") or ""),
        number=str(order.get("provider_number") or ""),
        country_code=str(order.get("temp_country") or ""),
        interval_sec=_poll_interval_for_provider(str(order.get("provider") or "")),
        elapsed_sec=elapsed,
        reuse_warranty_sec=_order_reuse_warranty_sec(order),
    )
    await _safe_edit_message(
        bot,
        chat_id=chat_id,
        message_id=msg_id,
        text=text,
        reply_markup=_build_temp_action_keyboard(order, lang),
        parse_mode="HTML",
    )


def _safe_code_text(value: str) -> str:
    return str(value or "").strip().replace("\n", " ")[:200]


def _clean_provider_error_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _provider_error_text(raw) -> str:
    if isinstance(raw, dict):
        for key in ("errorDescription", "message", "error", "detail"):
            cleaned = _clean_provider_error_text(raw.get(key))
            if cleaned:
                return cleaned
        pools = raw.get("pools")
        if isinstance(pools, dict):
            parts: list[str] = []
            for pool_name, pool_info in pools.items():
                if isinstance(pool_info, dict):
                    msg = _clean_provider_error_text(pool_info.get("message"))
                    if msg:
                        parts.append(f"{pool_name}: {msg}")
            if parts:
                return " | ".join(parts)
        return _clean_provider_error_text(str(raw)) or "provider_error"
    cleaned = _clean_provider_error_text(raw)
    return cleaned or "provider_error"


_EXPECTED_PROVIDER_FAILURE_MARKERS = (
    "out of stock",
    "unavailable",
    "insufficient balance",
    "balance_error",
    "no numbers",
    "not enough balance",
    "service not available",
    "no free phones",
    "temporarily unavailable",
)


def _is_expected_provider_failure(raw) -> bool:
    text = _provider_error_text(raw).lower()
    if not text:
        return False
    return any(marker in text for marker in _EXPECTED_PROVIDER_FAILURE_MARKERS)


def _extract_new_sms_code(messages: list, seen_codes: set[str]) -> str | None:
    for raw in messages or []:
        code = _safe_code_text(str(raw))
        if not code:
            continue
        if code in seen_codes:
            continue
        return code
    return None


def _temp_order_has_received_code(order: dict | None) -> bool:
    order = order or {}
    if _as_int(order.get("temp_codes_count"), 0) > 0:
        return True
    if order.get("temp_first_sms_at"):
        return True
    if str(order.get("temp_last_code") or "").strip():
        return True
    codes = order.get("temp_codes") or []
    if isinstance(codes, list):
        for code in codes:
            if str(code or "").strip():
                return True
    return False


def _is_retryable_provider_cancel(raw: Any) -> bool:
    text = _provider_error_text(raw).lower()
    if not text:
        return False
    return (
        "early_cancel_denied" in text
        or "early cancel denied" in text
        or "try again later" in text
        or "wait" in text
    )


async def _cancel_and_refund_temp_order(
    *,
    order_id,
    order: dict,
    actor_user_id: int,
    reason: str,
    require_no_sms: bool = True,
) -> dict:
    if not order_id or not order:
        return {"success": False, "reason": "order_not_found"}

    status = str(order.get("status") or "").lower()
    if status in {"cancelled", "failed", "refunded", "expired"}:
        return {"success": False, "reason": "already_closed"}
    if order.get("temp_refunded_at") or order.get("temp_cancelled_at"):
        return {"success": False, "reason": "already_closed"}

    if require_no_sms and _temp_order_has_received_code(order):
        return {"success": False, "reason": "sms_received"}

    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        return {"success": False, "reason": "provider_order_missing"}

    prov = PROVIDERS.get(provider)
    if not prov or not hasattr(prov, "cancel"):
        return {"success": False, "reason": "provider_cancel_not_supported"}

    await _log_number_event_from_order(
        order,
        "cancel_requested",
        payload={"reason": str(reason or "cancelled")},
        number_mode="temp",
    )

    cancel_res: dict = {"success": False, "raw": "cancel_not_attempted"}
    for attempt in range(1, 5):
        try:
            cancel_res = await asyncio.wait_for(prov.cancel(provider_order_id), timeout=12.0)
        except Exception as exc:
            cancel_res = {"success": False, "raw": str(exc)}
        if bool((cancel_res or {}).get("success")):
            break
        if attempt < 3:
            await asyncio.sleep(float(min(6, attempt * 2)))

    if not bool((cancel_res or {}).get("success")):
        await _log_number_event_from_order(
            order,
            "provider_cancel_failed",
            payload={"raw": (cancel_res or {}).get("raw"), "reason": str(reason or "cancelled")},
            number_mode="temp",
        )
        return {
            "success": False,
            "reason": "provider_cancel_failed",
            "raw": (cancel_res or {}).get("raw"),
            "retryable": bool((cancel_res or {}).get("retryable")) or _is_retryable_provider_cancel((cancel_res or {}).get("raw")),
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
            number_mode="temp",
        )
        return {"success": False, "reason": "financial_refund_failed", "raw": msg}

    now = _utc_now()
    await update_order_status(order_id, "cancelled")
    await update_order_details(
        order_id,
        {
            "temp_cancelled_at": now,
            "temp_refunded_at": now,
            "temp_cancel_reason": str(reason or "cancelled"),
            "temp_wait_state": "refunded",
        },
    )
    await _log_temp_event(
        order,
        "cancelled_refunded",
        {
            "sale_price": sale_price,
            "cost_price": cost_price,
            "reason": str(reason or "cancelled"),
        },
    )
    await _log_number_event_from_order(
        order,
        "refund_success",
        payload={"reason": str(reason or "cancelled")},
        status_after="cancelled",
        number_mode="temp",
    )
    return {"success": True, "reason": "ok"}


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


async def _best_effort_edit_text(
    message: types.Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception as exc:
        logger.warning("Best-effort edit_text failed: %s", exc)


def _order_short_label(order: dict) -> str:
    number = _format_number_for_copy_text(
        str(order.get("provider_number") or "?"),
        str(order.get("rental_country") or order.get("temp_country") or ""),
    )
    service = str(order.get("service_id") or "").replace(":rental", "")
    provider = provider_public_id(order.get("provider"))
    label = f"{number} | {service} | {provider}"
    if len(label) > 60:
        label = label[:57] + "..."
    return label


def _rental_detail_text(order: dict, lang: str) -> str:
    service = str(order.get("service_id") or "").replace(":rental", "")
    country = _country_display_name(
        order.get("rental_country"),
        country_name=order.get("rental_country_name"),
    )
    duration = str(order.get("rental_duration_label") or "-")
    renewable = bool(order.get("rental_is_renewable"))
    billing_cycle = str(order.get("rental_billing_cycle_label") or "-")
    if not renewable:
        billing_cycle = "-"
    lines = [
        f"{t(lang, 'service_label')}: {service}",
        f"{t(lang, 'country_label')}: {country}",
        f"{t(lang, 'rental_duration_label')}: {duration}",
        f"{t(lang, 'rental_renewable_label')}: {_bool_text(renewable, lang)}",
        f"{t(lang, 'rental_billing_cycle_label')}: {billing_cycle}",
        f"{t(lang, 'price_label')}: {_as_float(order.get('selling_price') or order.get('retail_amount') or 0):.2f}$",
        f"{t(lang, 'provider_label')}: {provider_public_id(order.get('provider'))}",
        f"{t(lang, 'rental_number_label')}: {_format_number_for_copy_text(order.get('provider_number') or '-', order.get('rental_country') or '')}",
    ]
    return "\n".join(lines)


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
    reseller_id = await get_user_reseller_for_bot(user_id, bot_id)
    if reseller_id:
        return reseller_id
    inferred = await get_reseller_id_for_bot(bot_id)
    if inferred:
        await set_user_reseller_for_bot(user_id, bot_id, inferred)
        return inferred
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
    order = order or {}
    sale_price, cost_price = extract_order_amounts(order)
    return {
        "order_id": order.get("_id"),
        "user_id": int(order.get("user_id") or 0),
        "reseller_id": int(order.get("reseller_id") or 0) or None,
        "provider": str(order.get("provider") or order.get("provisioning_provider") or ""),
        "service_id": str(order.get("service_id") or ""),
        "number_mode": str(number_mode or order.get("number_mode") or "").strip().lower(),
        "status_before": str(order.get("status") or ""),
        "sale_price": sale_price,
        "cost_price": cost_price,
        "provider_order_id": str(order.get("provider_order_id") or ""),
        "provider_number": str(order.get("provider_number") or ""),
        "country": str(order.get("temp_country") or order.get("rental_country") or order.get("provisioning_country") or ""),
        "state": str(order.get("temp_state") or order.get("rental_state_code") or order.get("provisioning_state_code") or ""),
    }


async def _log_number_event_from_order(
    order: dict | None,
    event: str,
    *,
    payload: dict | None = None,
    status_after: str | None = None,
    number_mode: str | None = None,
) -> None:
    try:
        ctx = _number_event_context_from_order(order, number_mode=number_mode)
        await number_events_repo.log_number_order_event(
            order_id=ctx["order_id"],
            user_id=ctx["user_id"],
            reseller_id=ctx["reseller_id"],
            provider=ctx["provider"],
            service_id=ctx["service_id"],
            number_mode=ctx["number_mode"],
            event=event,
            status_before=ctx["status_before"],
            status_after=status_after,
            sale_price=ctx["sale_price"],
            cost_price=ctx["cost_price"],
            provider_order_id=ctx["provider_order_id"],
            provider_number=ctx["provider_number"],
            country=ctx["country"],
            state=ctx["state"],
            payload=payload or {},
        )
    except Exception:
        logger.exception("number event log failed: event=%s order=%s", event, (order or {}).get("_id"))


async def _log_temp_event(order: dict, event: str, payload: dict | None = None):
    try:
        await temp_number_stats_repo.log_temp_number_event(
            order.get("_id"),
            user_id=int(order.get("user_id") or 0),
            provider=str(order.get("provider") or ""),
            service_id=str(order.get("service_id") or ""),
            event=event,
            payload=payload or {},
        )
    except Exception:
        logger.exception("temp event log failed: event=%s order=%s", event, order.get("_id"))
    await _log_number_event_from_order(order, event, payload=payload, number_mode="temp")


async def _log_rental_event(
    *,
    order_id: Any,
    user_id: int,
    provider: str,
    service_id: str,
    event: str,
    payload: dict | None = None,
):
    await _log_number_event_from_order(
        {
            "_id": order_id,
            "user_id": int(user_id or 0),
            "reseller_id": None,
            "provider": provider,
            "service_id": service_id,
            "number_mode": "rental",
        },
        event,
        payload=payload,
        number_mode="rental",
    )


async def _maybe_send_purchase_charge_confirmed_notice(
    *,
    bot,
    chat_id: int,
    order: dict,
    lang: str,
) -> None:
    order = order or {}
    if order.get("purchase_debit_notice_sent_at"):
        return
    try:
        user_id = int(order.get("user_id") or 0)
        reseller_id = int(order.get("reseller_id") or user_id)
        sale_price, _cost_price = extract_order_amounts(order)
        current_balance = await get_user_wallet_balance(user_id, reseller_id)
        await bot.send_message(
            chat_id=chat_id,
            text=_purchase_charge_confirmed_notice_text(
                lang,
                amount=float(sale_price),
                balance=float(current_balance),
            ),
        )
        await update_order_details(order.get("_id"), {"purchase_debit_notice_sent_at": _utc_now()})
    except Exception:
        logger.exception("failed to send deferred purchase debit notice for order=%s", order.get("_id"))


def _rental_no_sms_yet(order: dict | None) -> bool:
    order = order or {}
    if order.get("rental_sms_received_at"):
        return False
    count = _as_int(order.get("rental_sms_count"), 0)
    if count > 0:
        return False
    return True


def _is_within_hero_rental_cancel_window(order: dict | None) -> bool:
    order = order or {}
    start_dt = _to_utc_datetime(order.get("rental_started_at")) or _to_utc_datetime(order.get("created_at"))
    if not start_dt:
        return False
    now = _utc_now()
    return (now - start_dt).total_seconds() <= float(getattr(settings, "numbers_hero_rental_cancel_window_sec", HERO_RENTAL_CANCEL_WINDOW_SEC) or HERO_RENTAL_CANCEL_WINDOW_SEC)


def _rental_protection_policy(provider_code: str | None) -> dict[str, Any]:
    code = str(provider_code or "").strip().lower()
    poll_sec = max(20, int(getattr(settings, "numbers_rental_watch_poll_sec", 30) or 30))
    fallback_sync_window = max(
        300,
        int(
            getattr(
                settings,
                "numbers_rental_guard_fallback_sync_window_sec",
                RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC,
            )
            or RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC
        ),
    )
    policy = {
        "provider": code,
        "close_method": "finish",
        "refund_deadline_sec": None,
        "safe_cutoff_sec": max(30, int(getattr(settings, "numbers_rental_safe_cutoff_sec", 60) or 60)),
        "watch_poll_sec": poll_sec,
        "fallback_sync_window_sec": fallback_sync_window,
    }
    if code == "herosms":
        policy["close_method"] = "cancel"
        policy["refund_deadline_sec"] = max(
            60,
            int(getattr(settings, "numbers_hero_rental_cancel_window_sec", HERO_RENTAL_CANCEL_WINDOW_SEC) or HERO_RENTAL_CANCEL_WINDOW_SEC),
        )
    elif code == "smspool":
        deadline = getattr(settings, "numbers_smspool_rental_refund_window_sec", None)
        if deadline not in (None, ""):
            try:
                policy["refund_deadline_sec"] = max(60, int(deadline))
            except Exception:
                policy["refund_deadline_sec"] = None
    elif code == "textverified":
        deadline = getattr(settings, "numbers_textverified_rental_refund_window_sec", None)
        if deadline not in (None, ""):
            try:
                policy["refund_deadline_sec"] = max(60, int(deadline))
            except Exception:
                policy["refund_deadline_sec"] = None
    return policy


def _rental_deadline_at(order: dict | None) -> datetime | None:
    order = order or {}
    explicit = _to_utc_datetime(order.get("rental_refund_deadline_at"))
    if explicit:
        return explicit
    start_dt = _to_utc_datetime(order.get("rental_started_at")) or _to_utc_datetime(order.get("created_at"))
    if not start_dt:
        return None
    deadline_sec = _rental_protection_policy(order.get("provider")).get("refund_deadline_sec")
    if not deadline_sec:
        return None
    return datetime.fromtimestamp(start_dt.timestamp() + int(deadline_sec), tz=UTC)


def _rental_safe_cutoff_at(order: dict | None) -> datetime | None:
    order = order or {}
    explicit = _to_utc_datetime(order.get("rental_safe_cutoff_at"))
    if explicit:
        return explicit
    deadline_at = _rental_deadline_at(order)
    if not deadline_at:
        return None
    safe_cutoff_sec = int(_rental_protection_policy(order.get("provider")).get("safe_cutoff_sec") or 60)
    return datetime.fromtimestamp(deadline_at.timestamp() - max(30, safe_cutoff_sec), tz=UTC)


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
                alert_text = (
                    "Rental protection auto-cancel failed.\n\n"
                    f"Order: {order_id}\n"
                    f"Provider: {provider_label}\n"
                    f"User: {latest.get('user_id')}\n"
                    f"Reason: {result.get('reason') or 'provider_close_failed'}"
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
                alert_text = (
                    "Rental protection warning.\n\n"
                    f"Order: {order_id}\n"
                    f"Provider: {provider_label}\n"
                    f"User: {latest.get('user_id')}\n"
                    f"Deadline: {cutoff_txt}\n"
                    f"Seconds left: {seconds_left}\n"
                    "If no SMS arrives, the system will auto-cancel this rental before the deadline."
                )
                stats["alerts"].append({"kind": "near_cutoff", "order_id": str(order_id), "text": alert_text})
                with suppress(Exception):
                    await update_order_details(order_id, {"rental_cutoff_alert_sent_at": now_dt})

    return stats


async def run_temp_wait_recovery_sweep(*, bot, limit: int = 200) -> dict[str, Any]:
    stats = {
        "checked": 0,
        "synced": 0,
        "code_received": 0,
        "timed_out": 0,
        "refund_retries": 0,
    }
    if bot is None:
        return stats

    try:
        bot_id = int(getattr(bot, "_cached_bot_id", 0) or 0)
        if bot_id <= 0:
            me = await bot.get_me()
            bot_id = int(me.id)
            setattr(bot, "_cached_bot_id", bot_id)
    except Exception:
        bot_id = 0

    orders = await list_open_temp_orders_for_recovery(limit=int(limit))
    now_dt = _utc_now()
    for order in orders:
        stats["checked"] += 1
        order_id = order.get("_id")
        if not order_id:
            continue
        order_bot_id = _order_bot_id(order)
        if bot_id and order_bot_id and order_bot_id != bot_id:
            continue

        latest = await get_order(order_id)
        if not latest:
            continue
        if str(latest.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
            continue

        user = await get_user(int(latest.get("user_id") or 0))
        lang = (user or {}).get("language", "en")
        wait_state = str(latest.get("temp_wait_state") or "").strip().lower()

        if wait_state == "refund_pending":
            result = await _cancel_and_refund_temp_order(
                order_id=order_id,
                order=latest,
                actor_user_id=int(latest.get("user_id") or 0),
                reason="global_temp_recovery_retry",
                require_no_sms=True,
            )
            if result.get("success"):
                stats["refund_retries"] += 1
                with suppress(Exception):
                    await _safe_edit_message(
                        bot,
                        chat_id=int(latest.get("temp_wait_chat_id") or 0),
                        message_id=int(latest.get("temp_wait_message_id") or 0),
                        text=t(lang, "temp_timeout_refunded_retry"),
                        reply_markup=_temp_post_refund_kb(str(order_id), lang=lang, allow_replace=True),
                    )
            continue

        if wait_state == "code_received":
            continue

        provider = str(latest.get("provider") or "").strip()
        provider_order_id = str(latest.get("provider_order_id") or "").strip()
        if not provider or not provider_order_id:
            continue

        seen_codes = set(str(x) for x in (latest.get("temp_codes") or []) if x not in (None, ""))
        sms_data = await _fetch_provider_sms(provider, provider_order_id)
        code = _extract_new_sms_code((sms_data or {}).get("messages") or [], seen_codes)
        if code:
            code = _safe_code_text(code)
            code_now = _utc_now()
            updated_codes = list(seen_codes)
            updated_codes.append(code)
            patch = {
                "temp_wait_state": "code_received",
                "temp_last_sms_at": code_now,
                "temp_last_code": code,
                "temp_codes": updated_codes,
                "temp_codes_count": len(updated_codes),
            }
            if not latest.get("temp_first_sms_at"):
                patch["temp_first_sms_at"] = code_now
                seconds_to_first_sms = _seconds_between(code_now, latest.get("created_at"))
                if seconds_to_first_sms is not None:
                    patch["temp_seconds_to_first_sms"] = seconds_to_first_sms
            await update_order_details(order_id, patch)
            await _log_temp_event(
                latest,
                "code_received_recovery",
                {"code_len": len(code)},
            )
            with suppress(Exception):
                await _safe_edit_message(
                    bot,
                    chat_id=int(latest.get("temp_wait_chat_id") or 0),
                    message_id=int(latest.get("temp_wait_message_id") or 0),
                    text=_temp_code_received_text(lang, code, latest),
                    reply_markup=temp_code_received_kb(str(order_id), lang=lang),
                    parse_mode="HTML",
                )
            stats["code_received"] += 1
            continue

        started_at = _to_utc_datetime(latest.get("temp_wait_started_at")) or _to_utc_datetime(latest.get("created_at")) or now_dt
        timeout_sec = _order_temp_timeout_sec(latest)
        if now_dt.timestamp() >= (started_at.timestamp() + timeout_sec):
            await _send_temp_timeout_state(bot, latest, lang)
            stats["timed_out"] += 1
            continue

        await _sync_temp_wait_controls(bot, latest, lang)
        stats["synced"] += 1

    return stats


async def run_unprovisioned_number_order_recovery_sweep(
    *,
    limit: int = 100,
    grace_sec: int = 120,
) -> dict[str, Any]:
    stats = {"checked": 0, "refunded": 0, "refund_failures": 0, "skipped_recent": 0}
    now_dt = _utc_now()
    orders = await list_paid_number_orders_missing_provider(limit=int(limit))
    for order in orders:
        stats["checked"] += 1
        order_id = order.get("_id")
        if not order_id:
            continue
        charged_at = _to_utc_datetime(order.get("provisioning_charged_at")) or _to_utc_datetime(order.get("created_at"))
        if not charged_at or (now_dt - charged_at).total_seconds() < int(grace_sec):
            stats["skipped_recent"] += 1
            continue

        sale_price, cost_price = extract_order_amounts(order)
        refund_ok, refund_msg = await FinancialManager.refund_core_purchase(
            int(order.get("user_id") or 0),
            order_id,
            sale_price,
            cost_price,
            reseller_id=int(order.get("reseller_id") or order.get("user_id") or 0),
        )
        if refund_ok:
            await update_order_status(order_id, "refunded")
            await update_order_details(
                order_id,
                {
                    "provisioning_state": "recovered_refunded_unprovisioned",
                    "provisioning_recovered_at": now_dt,
                    "provisioning_recovery_reason": "missing_provider_order_id",
                },
            )
            await _log_number_event_from_order(
                order,
                "refund_success",
                payload={"source": "unprovisioned_recovery"},
                status_after="refunded",
                number_mode=str(order.get("number_mode") or ""),
            )
            stats["refunded"] += 1
            continue

        await update_order_details(
            order_id,
            {
                "provisioning_state": "recovery_refund_failed",
                "provisioning_recovery_last_at": now_dt,
                "provisioning_recovery_last_error": str(refund_msg or "unknown_error"),
            },
        )
        await _log_number_event_from_order(
            order,
            "refund_failed",
            payload={"source": "unprovisioned_recovery", "raw": str(refund_msg or "unknown_error")},
            status_after=str(order.get("status") or "paid"),
            number_mode=str(order.get("number_mode") or ""),
        )
        stats["refund_failures"] += 1
    return stats


async def _fetch_provider_sms(provider_code: str, provider_order_id: str) -> dict:
    prov = PROVIDERS.get(str(provider_code or "").lower())
    if not prov:
        return {"success": False, "messages": [], "raw": "provider_not_found"}
    if not hasattr(prov, "get_sms"):
        return {"success": False, "messages": [], "raw": "get_sms_not_supported"}
    try:
        return await prov.get_sms(provider_order_id)
    except Exception as exc:
        return {"success": False, "messages": [], "raw": str(exc)}


async def _provider_resend(provider_code: str, provider_order_id: str) -> dict:
    prov = PROVIDERS.get(str(provider_code or "").lower())
    if not prov:
        return {"success": False}
    # SMSPool numbers can continue receiving messages without explicit resend trigger.
    if str(provider_code or "").lower() == "smspool":
        return {"success": True, "order_id": provider_order_id}
    if hasattr(prov, "resend"):
        try:
            res = await prov.resend(provider_order_id)
            if isinstance(res, dict):
                ok = bool(res.get("success"))
                if not ok:
                    return {"success": False}
                out = {"success": True, "order_id": str(res.get("order_id") or provider_order_id)}
                number = str(res.get("number") or "").strip()
                if number:
                    out["number"] = number
                return out
            if bool(res):
                return {"success": True, "order_id": provider_order_id}
            return {"success": False}
        except Exception:
            return {"success": False}
    return {"success": False}


async def _send_temp_timeout_state(bot, order: dict, lang: str):
    now = _utc_now()
    await _log_number_event_from_order(
        order,
        "deadline_reached",
        payload={"source": "temp_wait_timeout"},
        number_mode="temp",
    )
    # New behavior: auto-cancel + auto-refund after timeout (no SMS received).
    result = await _cancel_and_refund_temp_order(
        order_id=order["_id"],
        order=order,
        actor_user_id=int(order.get("user_id") or 0),
        reason="timeout_auto_refund",
        require_no_sms=True,
    )
    if result.get("success"):
        await update_order_details(
            order["_id"],
            {
                "temp_wait_timeout_at": now,
                "temp_wait_state": "auto_refunded",
                "temp_replace_enabled": True,
            },
        )
        await _safe_edit_message(
            bot,
            chat_id=int(order.get("temp_wait_chat_id") or 0),
            message_id=int(order.get("temp_wait_message_id") or 0),
            text=t(lang, "temp_timeout_refunded_retry"),
            reply_markup=_temp_post_refund_kb(str(order["_id"]), lang=lang, allow_replace=True),
        )
        await _log_number_event_from_order(
            order,
            "auto_protection_triggered",
            payload={"source": "temp_wait_timeout"},
            status_after="cancelled",
            number_mode="temp",
        )
        await _log_temp_event(order, "wait_timeout_auto_refunded", {"timeout_sec": _order_temp_timeout_sec(order)})
        return

    # Fallback: keep previous timeout state if auto-refund fails for any reason.
    await update_order_details(
        order["_id"],
        {
            "temp_wait_timeout_at": now,
            "temp_wait_state": "refund_pending",
            "temp_replace_enabled": True,
            "temp_refund_retry_last_at": now,
            "temp_refund_retry_reason": str(result.get("reason") or "provider_cancel_failed"),
        },
    )
    refreshed = await get_order(order["_id"])
    if refreshed:
        await _sync_temp_wait_controls(bot, refreshed, lang)
    await _log_temp_event(
        order,
        "wait_timeout",
        {
            "timeout_sec": _order_temp_timeout_sec(order),
            "auto_refund_failed": True,
            "auto_refund_reason": str(result.get("reason") or ""),
        },
    )
    # Keep retrying provider cancel+refund in the background to avoid balance leakage.
    asyncio.create_task(
        _retry_temp_refund_until_success(
            bot=bot,
            order_id=order["_id"],
            actor_user_id=int(order.get("user_id") or 0),
            lang=lang,
            source_reason="timeout_auto_refund",
        )
    )


async def _start_temp_waiter(
    *,
    bot,
    order: dict,
    lang: str,
    is_second_code: bool = False,
):
    order_id = order.get("_id")
    if not order_id:
        return
    provider_code = str(order.get("provider") or "").lower()
    provider_order_id = str(order.get("provider_order_id") or "")
    chat_id = int(order.get("temp_wait_chat_id") or 0)
    msg_id = int(order.get("temp_wait_message_id") or 0)
    if not provider_code or not provider_order_id or not chat_id or not msg_id:
        return

    interval = _poll_interval_for_provider(provider_code)
    started_at = _utc_now()
    await update_order_details(
        order_id,
        {
            "temp_wait_state": "waiting",
            "temp_wait_started_at": started_at,
            "temp_wait_interval_sec": interval,
        },
    )
    await _log_temp_event(order, "wait_started", {"interval_sec": interval, "second_code": bool(is_second_code)})

    deadline = started_at.timestamp() + _order_temp_timeout_sec(order)
    while _utc_now().timestamp() < deadline:
        current = await get_order(order_id)
        if not current:
            return
        if str(current.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
            return
        if str(current.get("provider_order_id") or "") != provider_order_id:
            # A newer replacement order session was started for this logical flow.
            return

        seen_codes = set(str(x) for x in (current.get("temp_codes") or []) if x not in (None, ""))
        sms_data = await _fetch_provider_sms(provider_code, provider_order_id)
        messages = sms_data.get("messages") or []
        code = _extract_new_sms_code(messages, seen_codes)
        if code:
            now = _utc_now()
            codes = list(seen_codes)
            codes.append(code)
            patch = {
                "temp_wait_state": "code_received",
                "temp_last_sms_at": now,
                "temp_last_code": code,
                "temp_codes": codes,
                "temp_codes_count": len(codes),
            }
            if not current.get("temp_first_sms_at"):
                patch["temp_first_sms_at"] = now
                seconds_to_first_sms = _seconds_between(now, current.get("created_at"))
                if seconds_to_first_sms is not None:
                    patch["temp_seconds_to_first_sms"] = seconds_to_first_sms
            await update_order_details(order_id, patch)
            seconds_since_purchase = _seconds_between(now, current.get("created_at"))
            await _log_temp_event(
                current,
                "code_received",
                {
                    "code_len": len(code),
                    "seconds_since_purchase": seconds_since_purchase,
                    "second_code": bool(is_second_code),
                },
            )
            updated_order = await get_order(order_id) or current
            await _maybe_send_purchase_charge_confirmed_notice(
                bot=bot,
                chat_id=chat_id,
                order=updated_order,
                lang=lang,
            )
            await _safe_edit_message(
                bot,
                chat_id=chat_id,
                message_id=msg_id,
                text=_temp_code_received_text(lang, code, updated_order),
                reply_markup=temp_code_received_kb(str(order_id), lang=lang),
                parse_mode="HTML",
            )
            return

        await _sync_temp_wait_controls(bot, current, lang)
        await asyncio.sleep(interval)

    refreshed = await get_order(order_id)
    if refreshed:
        await _send_temp_timeout_state(bot, refreshed, lang)


async def _queue_temp_waiter(bot, order: dict, lang: str, is_second_code: bool = False):
    task = asyncio.create_task(_start_temp_waiter(bot=bot, order=order, lang=lang, is_second_code=is_second_code))
    def _done(t: asyncio.Task) -> None:
        try:
            _ = t.exception()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("temp waiter task failed unexpectedly")
    task.add_done_callback(_done)


@router.callback_query(lambda c: c.data == "flow:rental:my")
async def rental_my_numbers(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    orders = await list_user_rental_orders(callback.from_user.id, limit=20)
    if not orders:
        await callback.message.edit_text(
            t(lang, "rental_my_numbers_empty"),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=t(lang, "rental_add_number"), callback_data="flow:rental:add")],
                    [InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:rental:menu")],
                ]
            ),
        )
        return

    rows = []
    for order in orders:
        oid = str(order.get("_id"))
        if not oid:
            continue
        rows.append([InlineKeyboardButton(text=_order_short_label(order), callback_data=f"rent:my:view:{oid}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:rental:menu")])
    await callback.message.edit_text(
        t(lang, "rental_my_numbers_title"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("rent:my:view:"))
async def rental_my_view(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 3)[3]
    _oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)
    can_renew = bool(order.get("rental_is_renewable"))
    await callback.message.edit_text(
        _rental_detail_text(order, lang),
        reply_markup=_rental_manage_kb(order_id=raw_id, lang=lang, can_renew=can_renew, back_callback="flow:rental:my"),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("buy_provider:"))
async def provider_selected(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")

    provider_code = callback.data.split(":", 1)[1]
    data = await state.get_data()
    all_prices = data.get("available_prices", {})
    provider_info = all_prices.get(provider_code)
    if not provider_info:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    if not bool(provider_info.get("available_for_buy", True)):
        msg = (
            "??? ?????? ???? ???????? ??? ????? ??? ???? ?????? ????? ???? ??????/??????."
            if str(lang).lower().startswith("ar")
            else "This provider is shown for testing only and has no available pricing for this service/country."
        )
        return await callback.answer(msg, show_alert=True)
    if not str(provider_info.get("api_service_name") or "").strip():
        return await callback.answer(t(lang, "no_prices_available"), show_alert=True)
    try:
        provider_price = float(provider_info.get("price") or 0)
    except Exception:
        provider_price = 0.0
    if provider_price <= 0:
        return await callback.answer(t(lang, "no_prices_available"), show_alert=True)

    await state.update_data(
        selected_provider=provider_code,
        final_price=provider_price,
        base_price=float(provider_info.get("base_price") or provider_price),
        api_service=provider_info["api_service_name"],
        lang=lang,
    )
    reuse_policy_text = "\n" + _temp_reuse_policy_text(
        lang,
        _provider_default_reuse_warranty_sec(provider_code),
    )
    text = (
        f"{t(lang, 'provider_label')}: {provider_public_id(provider_code)}\n"
        f"{t(lang, 'service_label')}: {data.get('service')}\n"
        f"{t(lang, 'country_label')}: {data.get('country')}\n"
        f"{t(lang, 'state_label')}: {data.get('state', 'none')}\n"
        f"{t(lang, 'price_label')}: {float(provider_info['price']):.2f}$"
        f"{reuse_policy_text}\n\n"
        f"{t(lang, 'confirm_purchase_question')}"
    )
    await callback.message.edit_text(text, reply_markup=confirm_buy_kb(lang))
    await state.set_state(NumberFlow.confirm_buy)


@router.callback_query(lambda c: c.data and c.data.startswith("renthead:"))
async def rental_provider_header_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rentna:"))
async def rental_provider_duration_unavailable(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    msg = (
        "??? ????? ??? ????? ????? ??? ??? ???????."
        if str(lang).lower().startswith("ar")
        else "This duration is currently unavailable on this server."
    )
    await callback.answer(msg, show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("rentpick:"))
async def rental_option_selected_from_provider_grid(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()

    parts = str(callback.data or "").split(":")
    if len(parts) != 3:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    provider_code = parts[1].strip().lower()
    try:
        duration_hours = int(parts[2].strip())
    except Exception:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    provider_options = data.get("rental_provider_options") or {}
    option = _pick_rental_option_by_duration(provider_options, provider_code, duration_hours)
    if not option:
        return await callback.answer(t(lang, "no_rental_options"), show_alert=True)

    if provider_code == "textverified":
        matched_rows = [
            dict(row)
            for row in (provider_options.get(provider_code) or [])
            if int(row.get("duration") or 0) == int(duration_hours)
        ]
        if not matched_rows:
            return await callback.answer(t(lang, "no_rental_options"), show_alert=True)
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
            return await callback.answer(t(lang, "no_rental_options"), show_alert=True)
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
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    if idx < 0 or idx >= len(options):
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    option = options[idx]
    await state.update_data(selected_rental_option=option)
    await callback.message.edit_text(_rental_confirm_text(lang, data, option), reply_markup=rental_confirm_kb(lang))
    await state.set_state(NumberFlow.rental_confirm)


@router.callback_query(lambda c: c.data == "rent:noop")
async def rental_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(lambda c: c.data == "rent:cancel")
async def rental_cancel(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await _return_to_main_menu_from_buy(callback, state, lang)
    await callback.answer()


@router.callback_query(lambda c: c.data == "rent:confirm")
async def rent_confirm_warning(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    selected = data.get("selected_rental_option") or {}
    provider_code = selected.get("provider")
    if not provider_code:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    await callback.message.edit_text(
        _rental_refund_warning_text(lang, provider_code=provider_code, selected_option=selected),
        reply_markup=rental_warning_kb(lang),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "rent:confirm:back")
async def rent_confirm_warning_back(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    selected = data.get("selected_rental_option") or {}
    if not selected:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    await callback.message.edit_text(
        _rental_confirm_text(lang, data, selected),
        reply_markup=rental_confirm_kb(lang),
    )
    await callback.answer()


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
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    if bool(data.get("rent_confirm_inflight")):
        return await callback.answer(t(lang, "processing_order"), show_alert=False)
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
        if str(message) == "INSUFFICIENT_RESELLER_MAIN":
            bot_link = _main_reseller_bot_link()
            if bot_link:
                await callback.message.answer(
                    t(lang, "core_redirect_to_main_reseller").format(bot_link=bot_link)
                )
                return await callback.answer("Redirected", show_alert=True)
        return await callback.answer(str(message), show_alert=True)

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
        await callback.message.edit_text(
            t(lang, "rental_purchase_complete").format(
                number=_format_number_for_copy_html(number, country),
                order_id=provider_order_id,
                provider=provider_public_id(provider_code),
                duration=duration_text,
            ),
            reply_markup=_rental_result_kb(str(order_id), lang, can_renew=is_renewable),
            parse_mode="HTML",
        )
        asyncio.create_task(
            _rental_refund_guard(
                order_id=order_id,
                actor_user_id=int(user_id),
            )
        )
        state_cleared = True
        inflight_locked = False
        await state.clear()
    except Exception as exc:
        err_text = _provider_error_text(exc)
        if _is_expected_provider_failure(exc):
            logger.warning("Provider rental failed for user %s: %s", user_id, err_text)
        else:
            logger.exception("Provider rental failed for user %s: %s", user_id, err_text)
        await _best_effort_edit_text(
            callback.message,
            t(lang, "purchase_failed").format(error=provider_generic_error(lang)),
        )
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
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

    try:
        sms_data = await get_rental_sms_from_provider(provider, provider_order_id)
    except Exception:
        sms_data = {"success": False, "messages": []}

    messages = sms_data.get("messages") or []
    if not messages:
        return await callback.answer(t(lang, "no_sms_yet"), show_alert=True)

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
    await callback.answer("Updated")


@router.callback_query(lambda c: c.data and c.data.startswith("rent:finish:"))
async def rent_finish(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]

    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

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
            return await callback.answer(t(lang, "rental_cancelled_refunded"), show_alert=True)
        return await callback.answer(t(lang, "rental_finish_failed"), show_alert=True)

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
        return await callback.answer(t(lang, "rental_finished"), show_alert=True)

    await _log_number_event_from_order(order, "rental_finish_failed", number_mode="rental")
    return await callback.answer(t(lang, "rental_finish_failed"), show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("rent:renew:"))
async def rent_renew(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    if not bool(order.get("rental_is_renewable")):
        return await callback.answer(t(lang, "rental_action_not_supported"), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

    try:
        res = await renew_rental_from_provider(provider, provider_order_id)
        if bool(res.get("success")):
            await update_order_details(order_oid, {"rental_last_renew_at": datetime.now(UTC)})
            await _log_number_event_from_order(order, "rental_renewed", payload={"raw": res.get("raw")}, number_mode="rental")
            return await callback.answer(t(lang, "rental_renewed"), show_alert=True)
    except Exception:
        pass
    await _log_number_event_from_order(order, "rental_renew_failed", number_mode="rental")
    return await callback.answer(t(lang, "rental_renew_failed"), show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("rent:wake:"))
async def rent_wake(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

    try:
        res = await wake_rental_from_provider(provider, provider_order_id)
        if bool(res.get("success")):
            await update_order_details(order_oid, {"rental_last_wake_at": datetime.now(UTC)})
            await _log_number_event_from_order(order, "rental_wake_ok", payload={"raw": res.get("raw")}, number_mode="rental")
            return await callback.answer(t(lang, "rental_wake_ok"), show_alert=True)
    except Exception:
        pass
    await _log_number_event_from_order(order, "rental_wake_failed", number_mode="rental")
    return await callback.answer(t(lang, "rental_wake_failed"), show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("rent:notes:"))
async def rent_notes_tags(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    _order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

    try:
        res = await notes_tags_from_provider(provider, provider_order_id)
    except Exception:
        res = {"success": False}
    if not res.get("success"):
        return await callback.answer(t(lang, "rental_action_not_supported"), show_alert=True)

    notes = str(res.get("notes") or "-")
    tags = res.get("tags") or []
    if isinstance(tags, list) and tags:
        tags_text = ", ".join([str(x) for x in tags[:20]])
    else:
        tags_text = "-"
    await callback.message.answer(
        t(lang, "rental_notes_tags_text").format(notes=notes, tags=tags_text)
    )
    return await callback.answer("OK")


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
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    _action, target, _order_scope = parsed
    await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rentguard:cancel:"))
async def rental_guard_cancel(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    parsed = _parse_rental_guard_callback(str(callback.data or ""))
    if not parsed or not callback.message:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    _action, target, raw_scope = parsed
    if raw_scope == "all":
        orders = await _user_open_rentals_without_sms(callback.from_user.id)
        if not orders:
            await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
            return await callback.answer(t(lang, "order_not_found"), show_alert=True)
        result = await _cancel_and_refund_rental_orders(
            orders=orders,
            actor_user_id=int(callback.from_user.id),
            reason=f"exit_guard_user_cancel_{target}",
        )
        if result.get("success_count"):
            notice = (
                f"{result.get('success_count')} rental number(s) were cancelled and refunded."
                if not str(lang).lower().startswith("ar")
                else f"?? ????? {result.get('success_count')} ?? ????? ???????? ?????? ??????."
            )
            try:
                await callback.message.edit_text(notice)
            except Exception:
                await callback.message.answer(notice)
            await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
            return await callback.answer()
        if result.get("sms_received_count"):
            await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
            return await callback.answer(
                "SMS already arrived for at least one rental, so active numbers were kept."
                if not str(lang).lower().startswith("ar")
                else "???? ????? ?????? ????? ??? ????? ?? ????? ????????? ???? ?? ???????? ???????? ??????.",
                show_alert=True,
            )
        await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
        return await callback.answer(
            "Could not cancel the active rental numbers right now."
            if not str(lang).lower().startswith("ar")
            else "???? ????? ????? ???????? ?????? ?????.",
            show_alert=True,
        )

    order_oid, order = await _load_user_order(raw_scope, callback.from_user.id)
    if not order_oid or not order:
        await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

    result = await _cancel_and_refund_rental_order(
        order_id=order_oid,
        order=order,
        actor_user_id=int(callback.from_user.id),
        reason=f"exit_guard_user_cancel_{target}",
        require_no_sms=True,
    )
    if result.get("success"):
        notice = (
            "The rental number was cancelled and your balance was refunded."
            if not str(lang).lower().startswith("ar")
            else "?? ????? ??? ???????? ?????? ??????."
        )
        try:
            await callback.message.edit_text(notice)
        except Exception:
            await callback.message.answer(notice)
        await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
        return await callback.answer()

    if result.get("reason") == "sms_received":
        await _return_after_rental_exit_callback(callback, state, target=target, lang=lang)
        return await callback.answer(
            "SMS already arrived, so the number was kept active."
            if not str(lang).lower().startswith("ar")
            else "???? ????? ??????? ???? ?? ???????? ??????.",
            show_alert=True,
        )

    return await callback.answer(
        "Could not cancel this rental right now."
        if not str(lang).lower().startswith("ar")
        else "???? ????? ??? ???????? ?????.",
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
    state_code = data.get("state")
    service_name = data.get("service")
    final_price = float(data.get("final_price", 0))
    cost_price = float(data.get("base_price", final_price))

    if not provider_code or not api_service or not service_name or final_price <= 0:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    if bool(data.get("buy_confirm_inflight")):
        return await callback.answer(t(lang, "processing_order"), show_alert=False)
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
        return await callback.answer(
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
            "number_mode": "temp",
            "provisioning_provider": str(provider_code),
            "provisioning_country": None if country == "none" else country,
            "provisioning_state_code": None if state_code == "none" else state_code,
        }
    )
    await update_order_details(
        order_id,
        {
            "number_mode": "temp",
            "telegram_bot_id": int(bot_id),
            "provisioning_state": "awaiting_charge",
            "provisioning_provider": str(provider_code),
            "provisioning_service": str(api_service),
            "provisioning_country": None if country == "none" else country,
            "provisioning_state_code": None if state_code == "none" else state_code,
            "provisioning_created_at": _utc_now(),
        },
    )
    await _log_number_event_from_order(order, "order_created", number_mode="temp")

    ok, message = await FinancialManager.process_core_purchase(
        user_id=user_id,
        order_id=order_id,
        sale_price=final_price,
        cost_price=cost_price,
        reseller_id=reseller_id,
    )
    if not ok:
        await update_order_status(order_id, "failed")
        await _log_number_event_from_order(order, "wallet_charge_failed", payload={"message": str(message)}, status_after="failed", number_mode="temp")
        await state.update_data(buy_confirm_inflight=False)
        inflight_locked = False
        if str(message) == "INSUFFICIENT_RESELLER_MAIN":
            bot_link = _main_reseller_bot_link()
            if bot_link:
                await callback.message.answer(
                    t(lang, "core_redirect_to_main_reseller").format(bot_link=bot_link)
                )
                return await callback.answer("Redirected", show_alert=True)
        return await callback.answer(str(message), show_alert=True)

    await _best_effort_edit_text(callback.message, t(lang, "processing_order"))
    await _log_number_event_from_order(order, "wallet_charged", status_after="paid", number_mode="temp")

    try:
        await update_order_details(
            order_id,
            {
                "provisioning_state": "charged_pending_provider",
                "provisioning_charged_at": _utc_now(),
            },
        )
        purchase_options = {"reuse_mode": True}
        await _log_number_event_from_order(
            {**order, "provider": provider_code, "status": "paid"},
            "provider_buy_started",
            payload={"api_service": str(api_service)},
            status_after="paid",
            number_mode="temp",
        )
        req_country = None if country == "none" else country
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
                number_mode="temp",
            )
            await _log_number_event_from_order(
                {**order, "provider": provider_code, "status": "paid"},
                "refund_success" if refund_ok else "refund_failed",
                payload={"source": "provider_buy_failed"},
                status_after="refunded" if refund_ok else "failed",
                number_mode="temp",
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
                "number_mode": "temp",
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
                "provisioning_state": "provisioned",
                "provisioned_at": _utc_now(),
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
            number_mode="temp",
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

        await _safe_edit_message(
            callback.message.bot,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=_temp_waiting_text(
                lang=lang,
                provider_code=str(provider_code),
                number=str(number),
                country_code=str(country),
                interval_sec=int(interval_sec),
                elapsed_sec=0,
                reuse_warranty_sec=reuse_warranty_sec,
            ),
            reply_markup=None,
            parse_mode="HTML",
        )

        # Reload order snapshot and start auto-wait flow.
        fresh_order = await get_order(order_id)
        if fresh_order:
            await _queue_temp_waiter(bot=callback.message.bot, order=fresh_order, lang=lang, is_second_code=False)
        state_cleared = True
        inflight_locked = False
        await state.clear()
    except Exception as exc:
        err_text = _provider_error_text(exc)
        if _is_expected_provider_failure(exc):
            logger.warning("Provider buy failed for user %s: %s", user_id, err_text)
        else:
            logger.exception("Provider buy failed for user %s: %s", user_id, err_text)
        await _best_effort_edit_text(
            callback.message,
            t(lang, "purchase_failed").format(error=provider_generic_error(lang)),
        )
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
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)
    if str(order.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

    elapsed = _temp_elapsed_sec(order)
    if elapsed < TEMP_REFRESH_COOLDOWN_SEC:
        return await callback.answer(
            t(lang, "temp_refresh_wait").format(seconds=max(1, TEMP_REFRESH_COOLDOWN_SEC - elapsed)),
            show_alert=True,
        )
    cooldown_left = _temp_refresh_cooldown_left(order)
    if cooldown_left > 0:
        return await callback.answer(t(lang, "temp_refresh_wait").format(seconds=cooldown_left), show_alert=True)

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

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
        return await callback.answer(t(lang, "temp_no_new_sms"), show_alert=True)

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
    )
    await _safe_edit_message(
        callback.message.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=_temp_code_received_text(lang, code, refreshed_order),
        reply_markup=temp_code_received_kb(str(order_oid), lang=lang),
        parse_mode="HTML",
    )
    return await callback.answer("OK")


@router.callback_query(lambda c: c.data and c.data.startswith("temp:cancel:"))
async def temp_cancel_and_refund(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)
    if _temp_elapsed_sec(order) < TEMP_CANCEL_AFTER_SEC:
        left = max(1, TEMP_CANCEL_AFTER_SEC - _temp_elapsed_sec(order))
        return await callback.answer(t(lang, "temp_cancel_wait").format(seconds=left), show_alert=True)

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
            return await callback.answer(t(lang, "temp_cancel_retry_pending"), show_alert=True)
        return await callback.answer(t(lang, "temp_cancel_failed"), show_alert=True)

    await _safe_edit_message(
        callback.message.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=t(lang, "temp_cancelled_refunded"),
        reply_markup=_temp_post_refund_kb(str(order_oid), lang=lang, allow_replace=True),
    )
    return await callback.answer("OK")


@router.callback_query(lambda c: c.data and c.data.startswith("temp:replace:"))
async def temp_replace_number(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)
    if _temp_order_has_received_code(order):
        return await callback.answer(t(lang, "temp_second_code_failed"), show_alert=True)

    provider_code = str(order.get("provider") or "").strip().lower()
    api_service = str(order.get("temp_api_service") or "").strip()
    service_name = str(order.get("temp_service_key") or str(order.get("service_id") or "")).strip()
    country = order.get("temp_country")
    state_code = order.get("temp_state")
    final_price, cost_price = extract_order_amounts(order)

    if not provider_code or not api_service:
        return await callback.answer(t(lang, "temp_replace_unavailable"), show_alert=True)

    trust_gate = await _evaluate_temp_trust_gate(
        user_id=int(callback.from_user.id),
        service_id=service_name,
        provider_code=provider_code,
    )
    if not bool(trust_gate.get("allowed")):
        return await callback.answer(
            _trust_alert_text(
                lang,
                mode=str(trust_gate.get("mode") or "purchase"),
                wait_sec=int(trust_gate.get("wait_sec") or 0),
            ),
            show_alert=True,
        )

    # Best-effort cancel+refund on original order if still open.
    if str(order.get("status") or "").lower() not in {"cancelled", "failed", "refunded", "expired"}:
        result = await _cancel_and_refund_temp_order(
            order_id=order_oid,
            order=order,
            actor_user_id=callback.from_user.id,
            reason="replace_request",
            require_no_sms=True,
        )
        if not result.get("success"):
            return await callback.answer(t(lang, "temp_cancel_failed"), show_alert=True)

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
        return await callback.answer(str(msg), show_alert=True)

    await update_order_details(
        new_order_id,
        {
            "provisioning_state": "charged_pending_provider",
            "provisioning_charged_at": _utc_now(),
        },
    )
    purchase_options = {"reuse_mode": True}
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
        return await callback.answer(t(lang, "temp_replace_failed"), show_alert=True)

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
        ),
        reply_markup=None,
        parse_mode="HTML",
    )
    fresh = await get_order(new_order_id)
    if fresh:
        await _queue_temp_waiter(bot=callback.message.bot, order=fresh, lang=lang, is_second_code=False)
    return await callback.answer(t(lang, "temp_replace_success"), show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("temp:second:"))
async def temp_second_code(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    raw_id = callback.data.split(":", 2)[2]
    order_oid, order = await _load_user_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

    now = _utc_now()

    provider = str(order.get("provider") or "")
    provider_order_id = str(order.get("provider_order_id") or "")
    if not provider or not provider_order_id:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

    resend_result = await _provider_resend(provider, provider_order_id)
    if not bool((resend_result or {}).get("success")):
        return await callback.answer(t(lang, "temp_second_code_failed"), show_alert=True)
    new_provider_order_id = str((resend_result or {}).get("order_id") or provider_order_id).strip() or provider_order_id
    new_provider_number = str((resend_result or {}).get("number") or order.get("provider_number") or "").strip()

    sale_price, cost_price = extract_order_amounts(order)
    extra_sale = round(max(0.0, sale_price) / 2.0, 4)
    extra_cost = round(max(0.0, cost_price) / 2.0, 4)
    if extra_sale <= 0:
        return await callback.answer(t(lang, "temp_second_code_failed"), show_alert=True)

    bot_id = (await callback.message.bot.get_me()).id
    reseller_id = await _resolve_user_reseller(callback.from_user.id, bot_id)
    second_order = await create_order(
        user_id=callback.from_user.id,
        reseller_id=reseller_id,
        service_id=f"{str(order.get('service_id') or 'temp')}:second_code",
        selling_price=extra_sale,
        base_price=extra_cost,
    )
    await update_order_details(
        second_order["_id"],
        {
            "number_mode": "temp",
            "telegram_bot_id": int(bot_id),
            "provisioning_state": "awaiting_charge",
            "provisioning_provider": str(order.get("provider") or ""),
            "provisioning_service": str(order.get("temp_api_service") or order.get("service_id") or ""),
            "provisioning_country": order.get("temp_country"),
            "provisioning_state_code": order.get("temp_state"),
            "provisioning_created_at": _utc_now(),
        },
    )
    ok, msg = await FinancialManager.process_core_purchase(
        user_id=callback.from_user.id,
        order_id=second_order["_id"],
        sale_price=extra_sale,
        cost_price=extra_cost,
        reseller_id=reseller_id,
    )
    if not ok:
        await update_order_status(second_order["_id"], "failed")
        return await callback.answer(str(msg), show_alert=True)

    await update_order_status(second_order["_id"], "success")
    await update_order_details(
        second_order["_id"],
        {
            "provisioning_state": "provisioned",
            "provisioning_charged_at": _utc_now(),
            "provisioned_at": _utc_now(),
        },
    )
    await update_order_details(
        order_oid,
        {
            "temp_second_code_last_at": now,
            "temp_second_code_count": int(order.get("temp_second_code_count") or 0) + 1,
            "provider_order_id": new_provider_order_id,
            "provider_number": new_provider_number or str(order.get("provider_number") or ""),
        },
    )
    await _log_temp_event(order, "second_code_requested", {"extra_sale": extra_sale, "extra_cost": extra_cost})

    await _safe_edit_message(
        callback.message.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=_temp_waiting_text(
            lang=lang,
            provider_code=provider,
            number=new_provider_number or str(order.get("provider_number") or "-"),
            country_code=str(order.get("temp_country") or ""),
            interval_sec=_poll_interval_for_provider(provider),
            elapsed_sec=0,
            reuse_warranty_sec=_order_reuse_warranty_sec(order),
        ),
        reply_markup=None,
        parse_mode="HTML",
    )
    refreshed = await get_order(order_oid)
    if refreshed:
        await _queue_temp_waiter(bot=callback.message.bot, order=refreshed, lang=lang, is_second_code=True)
    return await callback.answer(t(lang, "temp_second_code_done").format(amount=float(extra_sale)), show_alert=True)


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
        return await callback.answer()

    order_id = res.get("order_id")
    order = await get_order(order_id)
    if not order:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)

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

    await FinancialManager.refund_core_purchase(user_id, order_id, sale_price, cost_price, reseller_id=int(order.get("reseller_id") or user_id))
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
    try:
        order_oid = ObjectId(raw_id)
    except Exception:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    order = await get_order(order_oid)
    if not order:
        return await callback.answer(t(lang, "order_not_found"), show_alert=True)
    if str(order.get("number_mode") or "").lower() == "temp":
        return await callback.answer(t(lang, "temp_second_code"), show_alert=True)
    provider = order.get("provider")
    provider_order_id = order.get("provider_order_id")
    if not provider or not provider_order_id:
        return await callback.answer(t(lang, "cannot_resend"), show_alert=True)

    prov = PROVIDERS.get(provider)
    if not prov or not hasattr(prov, "resend"):
        return await callback.answer(t(lang, "service_no_resend"), show_alert=True)

    try:
        ok = await prov.resend(provider_order_id)
        if ok:
            return await callback.answer(t(lang, "resend_requested"), show_alert=True)
    except Exception:
        pass
    return await callback.answer(t(lang, "resend_failed"), show_alert=True)


