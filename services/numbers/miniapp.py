from __future__ import annotations

import asyncio

import base64

import hashlib

import hmac

import json

import logging

import re

import time

from datetime import UTC, datetime, timedelta

from pathlib import Path

from typing import Any

from urllib.parse import parse_qsl

from aiogram import Bot

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from aiohttp import web

from bson import ObjectId

from config import settings

from database import number_events_repo, temp_number_stats_repo

from database.financial_ledger import get_user_wallet_balance, list_user_wallet_entries

from database.orders_repo import (

    create_order,

    extract_order_amounts,

    get_order,

    list_user_open_temp_and_voice_orders,

    list_user_rental_orders,

    list_user_recent_temp_and_voice_orders,

    update_order_details,

    update_order_status,

)

from database.support_tickets_repo import create_support_ticket, has_open_support_ticket, set_ticket_delivery

from database.support_topics_repo import get_support_target

from database.user_repo import create_user, get_user, update_user_language

from services.numbers.data.countries import COUNTRIES_LIST

from services.numbers.data.states_us import STATES_LIST

from services.numbers.shared.events import (

    _log_number_event_from_order as _log_number_event_from_order_impl,

    _log_rental_event as _log_rental_event_impl,

    _log_temp_event as _log_temp_event_impl,

)

from services.numbers.shared.temp_order import (

    TEMP_CANCEL_AFTER_SEC,

    TEMP_WAIT_TIMEOUT_SEC,

    _coerce_utc_datetime,

    _extract_new_sms_code,

    _extract_provider_wait_timeout_sec,

    _format_wait_time_short,

    _is_retryable_provider_cancel,

    _is_temp_order_active_for_trust_gate,

    _order_reuse_warranty_sec,

    _order_temp_timeout_sec,

    _poll_interval_for_provider,

    _provider_default_reuse_warranty_sec,

    _safe_code_text,

    _seconds_between,

    _seconds_left_until,

    _temp_elapsed_sec,

    _temp_order_has_received_code,

    _utc_now,

)

from services.numbers.shared.rental_policy import _rental_deadline_at, _rental_no_sms_yet, _rental_protection_policy

from services.numbers.shared.provider_io import fetch_provider_sms, provider_resend

from services.numbers.shared.temp_refund import (

    cancel_and_refund_temp_order as _shared_cancel_and_refund_temp_order,

    finalize_temp_local_refund as _shared_finalize_temp_local_refund,

    order_provider_code as _shared_order_provider_code,

    order_provider_order_id as _shared_order_provider_order_id,

    provider_failure_should_retry as _shared_provider_failure_should_retry,

    provider_raw_is_empty as _shared_provider_raw_is_empty,

    provider_status_text as _shared_provider_status_text,

    provider_terminal_refund_reason as _shared_provider_terminal_refund_reason,

    temp_refund_result_retryable as _shared_temp_refund_result_retryable,

)

from services.numbers.shared.temp_second_code import request_second_code_for_order as _shared_request_second_code_for_order
from services.numbers.shared.temp_replacement import pick_retry_provider as _shared_pick_retry_provider

from services.numbers.manager import (

    PROVIDERS,

    buy_number_from_provider,

    finish_rental_from_provider,

    get_all_prices,

    get_all_rental_prices,

    get_all_voice_prices,

    get_calls_from_provider,

    get_recording_from_provider,

    get_rental_sms_from_provider,

    notes_tags_from_provider,

    rent_number_from_provider,

    renew_rental_from_provider,

    wake_rental_from_provider,

)

from services.numbers.service_map import (

    get_service_aliases,

    get_service_display_name,

    list_service_keys,

    resolve_canonical_service_key,

)

from utils.core_service_guard import finance_error_public_text

from utils.financial_manager import FinancialManager

from utils.bot_menu_context import extract_bot_id_from_token, numbers_bot_url

from utils.provider_alias import provider_display_name, provider_public_id

from utils.services_keyboard import DEFAULT_TOP_SERVICES, load_top_services

logger = logging.getLogger("numbers_miniapp")

_ROOT = Path(__file__).resolve().parents[2]

_STATIC = _ROOT / "webapp" / "numbers"

_NO_STORE_HEADERS = {

    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",

    "Pragma": "no-cache",

    "Expires": "0",

}

_CHEAP_COUNTRY_CACHE_TTL_SEC = 300

_CHEAP_COUNTRY_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}

_CHEAP_COUNTRY_ISOS = (

    "US",

    "GB",

    "DE",

    "CA",

    "FR",

    "NL",

    "PL",

    "RO",

    "CZ",

    "ES",

    "IT",

    "BE",

    "AT",

    "CH",

    "IE",

    "PT",

    "FI",

    "NO",

    "SE",

    "DK",

)

_BOOTSTRAP_CACHE: dict[str, Any] = {"data": None}

_PRICE_TIMEOUT_SEC = 34.0
_PRICE_SOFT_TIMEOUT_SEC = 6.0
_TEMP_PRICE_SCREEN_PROVIDER_CODES = ("smspool", "telabot", "textverified", "herosms", "pvadeals", "vaksms")

_MAX_PRICE_ROWS = 16

_QUOTE_TTL_SEC = 300

_HIDDEN_TEMP_PROVIDER_CODES = {"smsman", "smsman_s6"}

_SUPPORT_CATEGORIES = ("numbers", "user_balance")

_TEMP_MY_NUMBERS_RETENTION_DAYS = 5

_VOICE_GENERIC_SERVICE = "servicenotlistedvoice"

_TEXTVERIFIED_RENTAL_STATE_SURCHARGE = 2.0

_EXTRA_SERVICE_SEARCH_ALIASES: dict[str, tuple[str, ...]] = {

    "attapoll": ("اتابول", "اتا بول", "أتابول", "أتا بول"),

}

def _init_tokens() -> list[str]:

    tokens: list[str] = []

    for key in ("bot_numbers_token", "bot_main_token"):

        token = str(getattr(settings, key, "") or "").strip()

        if token and token not in tokens:

            tokens.append(token)

    return tokens

def _verify_init_data(init_data: str) -> dict[str, Any]:

    raw = str(init_data or "").strip()

    if not raw:

        raise web.HTTPUnauthorized(text="missing initData")

    pairs = dict(parse_qsl(raw, keep_blank_values=True))

    received_hash = str(pairs.pop("hash", "") or "")

    if not received_hash:

        raise web.HTTPUnauthorized(text="missing hash")

    check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))

    for token in _init_tokens():

        secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()

        calculated = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if hmac.compare_digest(calculated, received_hash):

            user = json.loads(pairs.get("user") or "{}")

            return {"user_id": int(user.get("id") or 0), "user": user}

    raise web.HTTPUnauthorized(text="bad initData")

def _optional_auth(request: web.Request) -> dict[str, Any] | None:

    init_data = str(request.headers.get("X-Telegram-Init-Data", "") or "").strip()

    if not init_data:

        return None

    return _verify_init_data(init_data)

def _require_auth(request: web.Request) -> dict[str, Any]:

    init_data = str(request.headers.get("X-Telegram-Init-Data", "") or "").strip()

    auth = _verify_init_data(init_data)

    if int(auth.get("user_id") or 0) <= 0:

        raise web.HTTPUnauthorized(text="invalid user")

    return auth

async def _load_or_create_user(auth: dict[str, Any]) -> dict[str, Any]:

    user_id = int(auth.get("user_id") or 0)

    user_doc = await get_user(user_id)

    if user_doc:

        return user_doc

    tg_user = auth.get("user") if isinstance(auth.get("user"), dict) else {}

    username = str(tg_user.get("username") or tg_user.get("first_name") or "").strip()

    try:

        return await create_user(user_id, username, reseller_id=None)

    except Exception:

        user_doc = await get_user(user_id)

        if user_doc:

            return user_doc

        raise

def _lang_from_user(user_doc: dict[str, Any] | None, auth: dict[str, Any] | None = None) -> str:

    lang = str((user_doc or {}).get("language") or "").strip()

    if lang:

        return "ar" if lang.lower().startswith("ar") else "en"

    tg_user = (auth or {}).get("user") if isinstance((auth or {}).get("user"), dict) else {}

    language_code = str(tg_user.get("language_code") or "").strip().lower()

    return "ar" if language_code.startswith("ar") else "en"

def _text(lang: str, en: str, ar: str) -> str:

    return ar if str(lang or "").lower().startswith("ar") else en

def _json_error(message: str, *, status: int = 400, code: str = "bad_request", **extra: Any) -> web.Response:

    payload = {"ok": False, "code": code, "message": message}

    payload.update(extra)

    return web.json_response(payload, status=status, headers=dict(_NO_STORE_HEADERS))

def _format_joined_date(value: Any) -> str:

    if isinstance(value, datetime):

        if value.tzinfo is None:

            value = value.replace(tzinfo=UTC)

        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")

    return "-"

def _language_label(language: str) -> str:

    return "Arabic" if str(language or "").strip().lower().startswith("ar") else "English"

def _support_category_label(lang: str, category: str) -> str:

    key = str(category or "").strip().lower()

    labels = {

        "numbers": ("Numbers orders", "طلبات الأرقام"),

        "user_balance": ("Balance and payments", "الرصيد والدفع"),

    }

    en, ar = labels.get(key, (key.replace("_", " ").title(), key.replace("_", " ")))

    return _text(lang, en, ar)

def _support_categories_payload(lang: str) -> list[dict[str, str]]:

    return [{"key": key, "label": _support_category_label(lang, key)} for key in _SUPPORT_CATEGORIES]

def _support_bridge_token() -> str:

    return str(getattr(settings, "bot_admin_token", "") or "").strip()

def _numbers_source_bot_id() -> int:

    return int(extract_bot_id_from_token(getattr(settings, "bot_numbers_token", "")) or 0)

def _auth_profile(auth: dict[str, Any], user_doc: dict[str, Any] | None = None) -> dict[str, str]:

    tg_user = auth.get("user") if isinstance(auth.get("user"), dict) else {}

    username = str((user_doc or {}).get("username") or tg_user.get("username") or "").strip()

    first_name = str(tg_user.get("first_name") or "").strip()

    last_name = str(tg_user.get("last_name") or "").strip()

    full_name = " ".join(part for part in (first_name, last_name) if part).strip()

    if not full_name:

        full_name = str((user_doc or {}).get("full_name") or "").strip()

    return {"username": username, "full_name": full_name}

def _support_ticket_header_text(

    *,

    lang: str,

    ticket_no: int,

    category: str,

    user_id: int,

    username: str,

    full_name: str,

) -> str:

    username_display = f"@{username}" if username else "-"

    full_name_display = full_name or "-"

    category_label = _support_category_label(lang, category)

    if str(lang or "").lower().startswith("ar"):

        return (

            f"تذكرة دعم #{int(ticket_no or 0)}\n"

            f"القسم: {category_label}\n"

            f"المصدر: Numbers Mini App\n"

            f"User ID: {int(user_id)}\n"

            f"Username: {username_display}\n"

            f"Name: {full_name_display}"

        )

    return (

        f"Support ticket #{int(ticket_no or 0)}\n"

        f"Category: {category_label}\n"

        f"Source: Numbers Mini App\n"

        f"User ID: {int(user_id)}\n"

        f"Username: {username_display}\n"

        f"Name: {full_name_display}"

    )

def _support_ticket_action_markup(ticket_id: str) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(text="Reply", callback_data=f"support:reply_ticket:{ticket_id}"),

                InlineKeyboardButton(text="Solved", callback_data=f"support:solve_ticket:{ticket_id}"),

            ]

        ]

    )

def _ledger_reason_label(reason: Any, category: Any, lang: str) -> str:

    reason_text = str(reason or "").strip().lower()

    category_text = str(category or "").strip().lower()

    if category_text == "core_purchase" or reason_text.startswith("purchase_core_"):

        return _text(lang, "Numbers purchase", "شراء أرقام")

    if category_text == "core_refund" or reason_text.startswith("refund_core_"):

        return _text(lang, "Numbers refund", "استرجاع أرقام")

    if category_text == "recharge_credit" or reason_text == "recharge_request_accepted":

        return _text(lang, "Balance recharge", "شحن رصيد")

    if category_text in {"manual_credit", "manual_adjustment"}:

        return _text(lang, "Balance adjustment", "تعديل رصيد")

    return _text(lang, "Wallet activity", "حركة رصيد")

def _order_activity_subject(order: dict[str, Any] | None) -> str:

    if not order:

        return ""

    service = str(order.get("temp_service_key") or order.get("service_id") or order.get("service_ref_id") or "")

    service = service.replace(":rental", "").replace(":second_code", "").strip()

    label = _service_label(service) if service else ""

    number = str(order.get("provider_number") or "").strip()

    mode = str(order.get("number_mode") or "").strip().lower()

    if mode == "rental" and label:

        label = f"{label} rental"

    elif mode == "voice" and label:

        label = f"{label} call"

    if label and number:

        return f"{label} · {number}"

    return label or number

def _ledger_activity_subject_from_entry(entry: dict[str, Any], lang: str) -> str:

    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}

    candidates = [

        metadata.get("service_label"),

        metadata.get("service_name"),

        metadata.get("product_name"),

        metadata.get("item_name"),

        metadata.get("description"),

        metadata.get("label"),

        metadata.get("note"),

    ]

    for value in candidates:

        text = str(value or "").strip()

        if text:

            return text[:80]

    service_key = str(metadata.get("service") or metadata.get("service_id") or metadata.get("service_ref_id") or "").strip()

    if service_key:

        return _service_label(service_key.replace(":rental", "").replace(":second_code", ""))

    bot_username = str(metadata.get("bot_username") or metadata.get("bot") or metadata.get("source_bot") or "").strip()

    if bot_username:

        clean = bot_username if bot_username.startswith("@") else f"@{bot_username}"

        return clean[:80]

    source = str(metadata.get("source") or metadata.get("service_type") or metadata.get("flow") or "").strip()

    if source:

        return source.replace("_", " ").title()[:80]

    order_id = str(entry.get("order_id") or "").strip()

    reason = str(entry.get("reason") or "").strip().lower()

    if order_id and reason == "recharge_request_accepted":

        return _text(lang, "Recharge request", "طلب شحن")

    if order_id and "bot_subscription" in reason:

        return _text(lang, "Bot subscription", "اشتراك بوت")

    return ""

def _ledger_order_id_candidates(value: Any) -> list[Any]:

    raw = str(value or "").strip()

    if not raw:

        return []

    values: list[Any] = [value]

    try:

        oid = ObjectId(raw)

    except Exception:

        oid = None

    if oid is not None and oid not in values:

        values.append(oid)

    return values

async def _ledger_activity_orders(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:

    orders: dict[str, dict[str, Any]] = {}

    for entry in entries or []:

        raw_id = str(entry.get("order_id") or "").strip()

        if not raw_id or raw_id in orders:

            continue

        for candidate in _ledger_order_id_candidates(raw_id):

            try:

                order = await get_order(candidate)

            except Exception:

                order = None

            if order:

                orders[raw_id] = order

                break

    return orders

def _ledger_activity_payload(

    entries: list[dict[str, Any]],

    lang: str,

    orders: dict[str, dict[str, Any]] | None = None,

) -> list[dict[str, Any]]:

    rows: list[dict[str, Any]] = []

    for entry in entries or []:

        try:

            amount = float(entry.get("amount") or 0.0)

        except Exception:

            amount = 0.0

        sign = "+" if amount > 0 else "-" if amount < 0 else ""

        order_id = str(entry.get("order_id") or "")

        label = _ledger_reason_label(entry.get("reason"), entry.get("category"), lang)

        subject = _order_activity_subject((orders or {}).get(order_id)) or _ledger_activity_subject_from_entry(entry, lang)

        if subject:

            label = f"{label} · {subject}"

        rows.append(

            {

                "id": str(entry.get("_id") or ""),

                "label": label,

                "subject": subject,

                "amount": amount,

                "amount_label": f"{sign}{_money(abs(amount))}" if amount else _money(0),

                "balance_label": _money(entry.get("balance_after")),

                "created_at": _compact_datetime(entry.get("created_at")),

                "direction": str(entry.get("direction") or ""),

                "order_id": order_id,

            }

        )

    return rows

async def _account_payload(user_doc: dict[str, Any], auth: dict[str, Any]) -> dict[str, Any]:

    user_id = int(auth["user_id"])

    lang = _lang_from_user(user_doc, auth)

    profile = _auth_profile(auth, user_doc)

    balance = await get_user_wallet_balance(user_id, user_id)

    language = str(user_doc.get("language") or lang or "en").strip().lower()

    try:

        entries = await list_user_wallet_entries(user_id, user_id, limit=8)

        activity = _ledger_activity_payload(entries, lang, await _ledger_activity_orders(entries))

    except Exception:

        logger.exception("numbers miniapp account activity failed user=%s", user_id)

        activity = []

    return {

        "ok": True,

        "user": {

            "id": user_id,

            "username": profile["username"],

            "full_name": profile["full_name"],

            "language": "ar" if language.startswith("ar") else "en",

            "language_label": _language_label(language),

            "joined_at": _format_joined_date(user_doc.get("created_at")),

        },

        "balance": float(balance),

        "balance_label": _money(balance),

        "links": {

            "numbers_bot": numbers_bot_url("numbers"),

            "recharge": numbers_bot_url("balance"),

        },

        "recent_activity": activity,

        "support_categories": _support_categories_payload(lang),

    }

async def _submit_support_ticket(

    *,

    auth: dict[str, Any],

    user_doc: dict[str, Any],

    lang: str,

    category: str,

    message: str,

) -> dict[str, Any]:

    category = str(category or "").strip().lower()

    if category not in _SUPPORT_CATEGORIES:

        return {"ok": False, "code": "invalid_category", "message": _text(lang, "Choose a valid support category.", "اختر قسم دعم صحيح.")}

    message = " ".join(str(message or "").strip().split())

    if len(message) < 3:

        return {"ok": False, "code": "empty_message", "message": _text(lang, "Write a short message for support.", "اكتب رسالة قصيرة للدعم.")}

    if len(message) > 3500:

        message = message[:3500]

    source_bot_id = _numbers_source_bot_id()

    bridge_token = _support_bridge_token()

    target = await get_support_target(category)

    if source_bot_id <= 0 or not bridge_token or not target or not target.get("chat_id"):

        return {"ok": False, "code": "support_not_configured", "message": _text(lang, "Support is not configured yet.", "الدعم غير مضبوط حالياً.")}

    user_id = int(auth["user_id"])

    if await has_open_support_ticket(scope="platform", owner_id=None, user_id=user_id, category=category):

        return {"ok": False, "code": "open_ticket_exists", "message": _text(lang, "You already have an open support ticket in this category.", "عندك تذكرة دعم مفتوحة بهذا القسم.")}

    profile = _auth_profile(auth, user_doc)

    ticket = await create_support_ticket(

        scope="platform",

        owner_id=None,

        source_bot_id=source_bot_id,

        chat_id=user_id,

        user_id=user_id,

        username=profile["username"],

        full_name=profile["full_name"],

        category=category,

        payload_count=1,

    )

    kwargs: dict[str, Any] = {"chat_id": int(target["chat_id"])}

    if target.get("message_thread_id") is not None:

        kwargs["message_thread_id"] = int(target["message_thread_id"])

    ticket_id = str(ticket["_id"])

    bridge_bot = Bot(token=bridge_token)

    try:

        header = await bridge_bot.send_message(

            text=_support_ticket_header_text(

                lang=lang,

                ticket_no=int(ticket.get("ticket_no") or 0),

                category=category,

                user_id=user_id,

                username=profile["username"],

                full_name=profile["full_name"],

            ),

            reply_markup=_support_ticket_action_markup(ticket_id),

            **kwargs,

        )

        await bridge_bot.send_message(text=message, **kwargs)

        await set_ticket_delivery(

            ticket_id,

            target_chat_id=int(target["chat_id"]),

            target_thread_id=int(target["message_thread_id"]) if target.get("message_thread_id") is not None else None,

            header_message_id=int(header.message_id),

        )

    finally:

        await bridge_bot.session.close()

    return {

        "ok": True,

        "ticket_id": ticket_id,

        "ticket_no": int(ticket.get("ticket_no") or 0),

        "message": _text(lang, "Support ticket sent.", "تم إرسال تذكرة الدعم."),

    }

def _quote_secret() -> bytes:

    tokens = _init_tokens()

    seed = tokens[0] if tokens else "numbers-miniapp-local"

    return hashlib.sha256(f"numbers-miniapp:{seed}".encode("utf-8")).digest()

def _b64_encode(raw: bytes) -> str:

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

def _b64_decode(value: str) -> bytes:

    padded = str(value or "") + ("=" * (-len(str(value or "")) % 4))

    return base64.urlsafe_b64decode(padded.encode("ascii"))

def _make_quote_token(payload: dict[str, Any]) -> str:

    clean_payload = dict(payload or {})

    clean_payload["exp"] = int(time.time()) + _QUOTE_TTL_SEC

    body = _b64_encode(json.dumps(clean_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    sig = hmac.new(_quote_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()

    return f"{body}.{sig}"

def _verify_quote_token(token: str) -> dict[str, Any]:

    raw = str(token or "").strip()

    if "." not in raw:

        raise web.HTTPBadRequest(text="invalid quote")

    body, sig = raw.rsplit(".", 1)

    expected = hmac.new(_quote_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, sig):

        raise web.HTTPBadRequest(text="bad quote")

    try:

        payload = json.loads(_b64_decode(body).decode("utf-8"))

    except Exception as exc:

        raise web.HTTPBadRequest(text="bad quote payload") from exc

    if int(payload.get("exp") or 0) < int(time.time()):

        raise web.HTTPBadRequest(text="quote expired")

    return payload

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

async def _log_temp_event(order: dict, event: str, payload: dict | None = None) -> None:

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

) -> None:

    await _log_rental_event_impl(

        order_id=order_id,

        user_id=user_id,

        provider=provider,

        service_id=service_id,

        event=event,

        payload=payload,

        log_number_event_from_order_cb=_log_number_event_from_order,

    )

def _trust_message(lang: str, *, mode: str, wait_sec: int) -> str:

    if mode == "active_order":

        return _text(

            lang,

            "You already have an active number order. Wait for its code or cancel it first.",

            "عندك طلب رقم شغال حاليا. انتظر الكود أو ألغ الطلب بالأول.",

        )

    wait_text = _format_wait_time_short(wait_sec)

    return _text(

        lang,

        f"Please wait {wait_text} before trying this provider again.",

        f"انتظر {wait_text} قبل تجربة هذا المزود مرة ثانية.",

    )

async def _evaluate_temp_trust_gate(*, user_id: int, service_id: str, provider_code: str) -> dict[str, Any]:

    if not bool(getattr(settings, "numbers_trust_enabled", True)):

        return {"allowed": True}

    service = str(service_id or "").strip()

    provider = str(provider_code or "").strip().lower()

    if not service or not provider:

        return {"allowed": True}

    open_orders = await list_user_open_temp_and_voice_orders(int(user_id), limit=5)

    if any(_is_temp_order_active_for_trust_gate(item) for item in (open_orders or [])):

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

def _clean_label(value: Any) -> str:

    text = re.sub(r"\s*\([^)]*\)\s*", " ", str(value or "")).strip()

    text = re.sub(r"\s{2,}", " ", text)

    return text

def _service_label(service_key: str) -> str:

    label = get_service_display_name(service_key)

    if label:

        return _clean_label(label)

    return _clean_label(str(service_key or "").replace("_", " ")).title()

def _compact_datetime(value: Any) -> str:

    dt = _coerce_utc_datetime(value)

    if not dt:

        return ""

    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")

def _country_name(code: Any, *, fallback: Any = "") -> str:

    raw = str(code or "").strip()

    if not raw or raw == "none":

        return ""

    for item in COUNTRIES_LIST:

        if str(item.get("code") or "").strip() == raw:

            return str(item.get("name") or raw)

    return str(fallback or raw)

def _state_name(code: Any) -> str:

    raw = str(code or "").strip().upper()

    if not raw or raw == "NONE":

        return ""

    for item in STATES_LIST:

        if str(item.get("code") or "").strip().upper() == raw:

            return str(item.get("name") or raw)

    return raw

def _detail_row(key: str, value: Any) -> dict[str, str] | None:

    text = str(value or "").strip()

    if not text or text == "-":

        return None

    return {"key": key, "value": text}

def _order_provider_code(order: dict[str, Any] | None) -> str:

    return _shared_order_provider_code(order)

def _order_provider_order_id(order: dict[str, Any] | None) -> str:

    return _shared_order_provider_order_id(order)

_PROVIDER_TERMINAL_REFUND_MARKERS = (

    "status_cancel",

    "access_cancel",

    "already refunded",

    "already_refunded",

    "refunded",

    "already cancelled",

    "already canceled",

    "already_cancelled",

    "already_canceled",

    "cancelled",

    "canceled",

)

_PROVIDER_TERMINAL_MISSING_MARKERS = (

    "no_activation",

    "no activation",

    "activation not found",

    "request not found",

    "order not found",

    "not_found",

    "not found",

    "does not exist",

    "doesn't exist",

    "not exist",

    "invalid activation",

    "invalid order",

    "invalid id",

    "expired",

    "deleted",

    "removed",

)

_PROVIDER_ACTIVE_WAIT_MARKERS = (

    "status_wait",

    "wait_sms",

    "waiting",

    "awaiting",

    "pending",

    "reserved",

    "no sms",

    "no_sms",

)

_PROVIDER_BLOCKING_FAILURE_MARKERS = (

    "auth_failed",

    "missing_api_key",

    "api key",

    "bad_key",

    "bad key",

    "unauthorized",

    "forbidden",

    "rate limit",

    "429",

    "timeout",

    "timed out",

    "request_error",

    "request failed",

    "connection",

    "network",

    "temporarily",

    "try again later",

    "server error",

    "internal server error",

)

def _provider_raw_is_empty(raw: Any) -> bool:

    return _shared_provider_raw_is_empty(raw)

def _provider_status_text(raw: Any) -> str:

    return _shared_provider_status_text(raw)

def _provider_terminal_refund_reason(

    raw: Any,

    *,

    allow_missing: bool = False,

    allow_empty: bool = False,

) -> str:

    return _shared_provider_terminal_refund_reason(raw, allow_missing=allow_missing, allow_empty=allow_empty)

def _provider_failure_should_retry(raw: Any) -> bool:

    return _shared_provider_failure_should_retry(raw)

def _order_detail_rows(order: dict[str, Any], *, mode: str, public_status: str) -> list[dict[str, str]]:

    rows: list[dict[str, str]] = []

    provider_code = _order_provider_code(order)

    provider = provider_display_name(provider_code) if provider_code else ""

    for item in (

        _detail_row("provider", provider),

        _detail_row("created", _compact_datetime(order.get("created_at"))),

    ):

        if item:

            rows.append(item)

    if mode == "rental":

        country = _country_name(order.get("rental_country"), fallback=order.get("rental_country_name"))

        state = _state_name(order.get("rental_state_code"))

        extras = (

            _detail_row("country", country),

            _detail_row("state", state),

            _detail_row("duration", order.get("rental_duration_label")),

            _detail_row("ends", _compact_datetime(order.get("rental_end_date")) or str(order.get("rental_end_date") or "")),

        )

    else:

        country = _country_name(order.get("temp_country") or order.get("provisioning_country"))

        state = _state_name(order.get("temp_state") or order.get("provisioning_state_code"))

        if mode == "voice":

            calls_count = int(order.get("voice_calls_count") or len(order.get("voice_calls") or []) or 0)

            extras = (

                _detail_row("country", country),

                _detail_row("calls", calls_count if calls_count > 0 else ""),

                _detail_row("retry", order.get("temp_refund_retry_attempts") if public_status == "refund_pending" else ""),

            )

        else:

            second_codes = int(order.get("temp_second_code_count") or 0)

            extras = (

                _detail_row("country", country),

                _detail_row("state", state),

                _detail_row("reuseUntil", _compact_datetime(order.get("temp_reuse_warranty_until"))),

                _detail_row("secondCodes", second_codes if second_codes > 0 else ""),

                _detail_row("retry", order.get("temp_refund_retry_attempts") if public_status == "refund_pending" else ""),

            )

    for item in extras:

        if item:

            rows.append(item)

    return rows[:7]

def _event_public_label(event: str, lang: str) -> str:

    key = str(event or "").strip().lower()

    labels = {

        "cancel_requested": ("Checking provider refund", "جاري فحص الاسترجاع من المزود"),

        "provider_already_closed": ("Provider already closed the order", "المزود أغلق الطلب مسبقاً"),

        "provider_cancel_failed": ("Provider refund is retrying", "استرجاع المزود قيد إعادة المحاولة"),

        "refund_failed": ("Wallet refund is retrying", "استرجاع الرصيد قيد إعادة المحاولة"),

        "refund_pending": ("Refund is pending", "الاسترجاع قيد المعالجة"),

        "cancelled_refunded": ("Refund completed", "تم إرجاع الرصيد"),

        "refund_success": ("Wallet refunded", "تم إرجاع الرصيد للمحفظة"),

        "code_received": ("Code received", "وصل الكود"),

        "refresh_code_received": ("Code received after refresh", "وصل الكود بعد التحديث"),

        "manual_refresh_no_sms": ("No new SMS yet", "لا توجد رسالة جديدة بعد"),

        "voice_call_received": ("Call received", "وصلت المكالمة"),

        "manual_voice_check_no_call": ("No call yet", "لا توجد مكالمة بعد"),

        "second_code_attempted": ("Second code requested", "تم طلب كود ثاني"),

        "second_code_requested": ("Second code activated", "تم تفعيل الكود الثاني"),

        "rental_finished": ("Rental finished", "تم إنهاء الإيجار"),

        "rental_renewed": ("Rental renewed", "تم تجديد الإيجار"),

        "rental_wake_ok": ("Rental wake requested", "تم طلب تنشيط الإيجار"),

    }

    en, ar = labels.get(key, (key.replace("_", " ").strip().title(), key.replace("_", " ")))

    return _text(lang, en, ar)

def _event_payload(event: dict[str, Any], lang: str) -> dict[str, str]:

    return {

        "event": str(event.get("event") or ""),

        "label": _event_public_label(str(event.get("event") or ""), lang),

        "time": _compact_datetime(event.get("created_at")),

    }

async def _recent_order_events_payload(order_id: Any, lang: str, *, limit: int = 5) -> list[dict[str, str]]:

    try:

        rows = await number_events_repo.list_number_order_events_for_order(order_id, limit=limit)

    except Exception:

        logger.exception("numbers miniapp order events load failed: order=%s", order_id)

        return []

    return [_event_payload(row, lang) for row in rows[-limit:]]

async def _order_payload_with_events(order: dict[str, Any], lang: str) -> dict[str, Any]:

    payload = _order_payload(order)

    payload["events"] = await _recent_order_events_payload(order.get("_id"), lang)

    return payload

async def _attach_order_events(payload: dict[str, Any], lang: str) -> dict[str, Any]:

    order_payload = payload.get("order")

    if not isinstance(order_payload, dict):

        return payload

    order_id = order_payload.get("id")

    if not order_id:

        return payload

    payload["order"] = {

        **order_payload,

        "events": await _recent_order_events_payload(order_id, lang),

    }

    return payload

def _clean_aliases(values: Any) -> list[str]:

    seen: set[str] = set()

    aliases: list[str] = []

    for value in values or []:

        text = str(value or "").strip()

        key = text.lower()

        if not text or key in seen:

            continue

        seen.add(key)

        aliases.append(text)

    return aliases

def _country_rows() -> list[dict[str, Any]]:

    rows: list[dict[str, Any]] = [{"code": "none", "iso": "", "name": "Any country", "aliases": ["any", "all"]}]

    for item in COUNTRIES_LIST:

        code = str(item.get("code") or "").strip()

        iso = str(item.get("iso") or "").strip().upper()

        name = str(item.get("name") or "").strip()

        if code and name and "_V" not in iso:

            aliases = _clean_aliases([code, iso, name, *(item.get("aliases") or [])])

            rows.append({"code": code, "iso": iso, "name": name, "aliases": aliases})

    return rows

def _country_code_by_iso() -> dict[str, str]:

    out: dict[str, str] = {}

    for item in _country_rows():

        code = str(item.get("code") or "").strip()

        iso = str(item.get("iso") or "").strip().upper()

        if code and iso:

            out.setdefault(iso, code)

    return out

def _cheap_country_candidate_codes() -> list[str]:

    by_iso = _country_code_by_iso()

    out: list[str] = []

    seen: set[str] = set()

    for iso in _CHEAP_COUNTRY_ISOS:

        code = by_iso.get(str(iso or "").upper())

        if not code or code in seen:

            continue

        seen.add(code)

        out.append(code)

    return out

def _best_available_country_price(prices: Any) -> float | None:

    best: float | None = None

    def visit(value: Any) -> None:

        nonlocal best

        if isinstance(value, dict):

            if "price" in value:

                try:

                    price = float(value.get("price") or 0.0)

                except Exception:

                    price = 0.0

                if price > 0 and (best is None or price < best):

                    best = price

            for nested in value.values():

                if isinstance(nested, (dict, list, tuple)):

                    visit(nested)

        elif isinstance(value, (list, tuple)):

            for nested in value:

                visit(nested)

    visit(prices)

    return best

async def _country_suggestions_for_service(mode: str, service: str, limit: int = 10) -> list[dict[str, Any]]:

    service = resolve_canonical_service_key(str(service or ""))

    mode = str(mode or "temp").strip().lower()

    if not service or mode == "voice":

        return []

    cache_key = f"{mode}:{service}:{int(limit or 10)}"

    now_ts = time.time()

    cached = _CHEAP_COUNTRY_CACHE.get(cache_key)

    if cached and (now_ts - cached[0]) <= _CHEAP_COUNTRY_CACHE_TTL_SEC:

        return list(cached[1])[:limit]

    candidates = _cheap_country_candidate_codes()

    sem = asyncio.Semaphore(min(6, len(candidates) or 1))

    async def fetch_country(country_code: str) -> dict[str, Any] | None:

        async with sem:

            try:

                if mode == "rental":

                    prices = await asyncio.wait_for(

                        get_all_rental_prices(service, country_code, with_success_rates=False),

                        timeout=4.5,

                    )

                else:

                    prices = await asyncio.wait_for(

                        get_all_prices(service, country_code, "none", ignore_balance=True, with_success_rates=False),

                        timeout=4.5,

                    )

            except Exception:

                return None

            price = _best_available_country_price(prices)

            if price is None:

                return None

            return {

                "code": country_code,

                "name": _country_name(country_code),

                "price": float(price),

                "price_label": _money(price),

            }

    rows = [row for row in await asyncio.gather(*(fetch_country(code) for code in candidates)) if row]

    priority = {code: index for index, code in enumerate(candidates)}

    rows.sort(key=lambda row: (priority.get(str(row.get("code") or ""), 999), float(row.get("price") or 0.0)))

    selected = rows[:limit]

    _CHEAP_COUNTRY_CACHE[cache_key] = (now_ts, selected)

    return list(selected)

def _state_rows() -> list[dict[str, Any]]:

    rows: list[dict[str, Any]] = [{"code": "none", "name": "Any state", "aliases": ["any", "all"]}]

    for item in STATES_LIST:

        code = str(item.get("code") or "").strip().upper()

        name = str(item.get("name") or "").strip()

        if code and name:

            aliases = _clean_aliases([code, name, *(item.get("aliases") or [])])

            rows.append({"code": code, "name": name, "aliases": aliases})

    return rows

def _service_rows() -> list[dict[str, Any]]:

    top_raw = list(load_top_services() or []) + list(DEFAULT_TOP_SERVICES)

    top: list[str] = []

    seen: set[str] = set()

    for item in top_raw:

        key = resolve_canonical_service_key(str(item or ""))

        if key and key not in seen:

            seen.add(key)

            top.append(key)

    services: list[dict[str, Any]] = []

    emitted: set[str] = set()

    def push(key: str, *, is_top: bool) -> None:

        canonical = resolve_canonical_service_key(str(key or ""))

        if not canonical or canonical in emitted:

            return

        emitted.add(canonical)

        aliases = list(get_service_aliases(canonical))

        aliases.extend(_EXTRA_SERVICE_SEARCH_ALIASES.get(canonical, ()))

        services.append(

            {

                "key": canonical,

                "label": _service_label(canonical),

                "aliases": aliases,

                "top": is_top,

            }

        )

    for key in top:

        push(key, is_top=True)

    for key in list_service_keys():

        push(key, is_top=False)

    return services

def _bootstrap_payload() -> dict[str, Any]:

    cached = _BOOTSTRAP_CACHE.get("data")

    if isinstance(cached, dict):

        return cached

    payload = {

        "modes": [

            {"key": "temp", "label": "Temporary SMS"},

            {"key": "rental", "label": "Rental numbers"},

            {"key": "voice", "label": "US call number"},

        ],

        "countries": _country_rows(),

        "states_us": _state_rows(),

        "services": _service_rows(),

        "defaults": {"mode": "temp", "service": "", "country": "none", "state": "none"},

        "links": {

            "numbers_bot": numbers_bot_url("numbers"),

            "recharge": numbers_bot_url("balance"),

        },

    }

    _BOOTSTRAP_CACHE["data"] = payload

    return payload

def _money(value: Any) -> str:

    try:

        amount = float(value or 0.0)

    except Exception:

        amount = 0.0

    if amount <= 0:

        return "-"

    text = f"{amount:.4f}".rstrip("0").rstrip(".")

    return f"${text}"

def _success_rate(value: Any, attempts: Any = None) -> str:

    try:

        attempt_count = int(attempts or 0)

    except Exception:

        attempt_count = 0

    if attempt_count < max(1, int(getattr(settings, "numbers_success_rate_display_min_attempts", 5) or 5)):

        return "-"

    try:

        rate = max(0.0, min(100.0, float(value if value is not None else 100.0)))

    except Exception:

        rate = 100.0

    return f"{int(rate)}%" if rate.is_integer() else f"{rate:.1f}%"

def _success_attempt_count(info: dict[str, Any]) -> int:

    try:

        attempts = int(info.get("success_attempts") or 0)

    except Exception:

        attempts = 0

    try:

        context_attempts = int(info.get("context_success_attempts") or 0)

    except Exception:

        context_attempts = 0

    return max(attempts, context_attempts)

def _public_reason(value: Any) -> str:

    reason = str(value or "").strip().lower()

    if reason == "provider_balance_low":

        return "Provider balance is low"

    if reason == "provider_balance_unknown":

        return "Provider balance is being checked"

    if reason in {"service_not_supported", "second_lane_unavailable", "rental_not_supported", "voice_unavailable"}:

        return "Not available for this selection"

    if reason == "provider_timeout":

        return "Provider timed out"

    if reason:

        return "Temporarily unavailable"

    return ""

def _provider_sort_key(code: str) -> tuple[int, str, str]:

    public = provider_public_id(code)

    rank = 999

    if public.startswith("S") and public[1:].isdigit():

        rank = int(public[1:])

    return (rank, public, code)

def _provider_price_float(info: dict[str, Any]) -> float:

    try:

        return float(info.get("price") or 0.0)

    except Exception:

        return 0.0

def _miniapp_provider_buyable(mode: str, provider_code: str, info: dict[str, Any]) -> bool:

    code = str(provider_code or "").strip().lower()

    if not code or code in _HIDDEN_TEMP_PROVIDER_CODES or not isinstance(info, dict):

        return False

    if not bool(info.get("available_for_buy", True)):

        return False

    if mode == "rental":

        for option in info.get("options") or []:

            if not isinstance(option, dict):

                continue

            try:

                if float(option.get("price") or 0.0) > 0:

                    return True

            except Exception:

                continue

        return False

    if mode == "voice" and (code != "textverified" or not bool(info.get("voice_capable", True))):

        return False

    return bool(str(info.get("api_service_name") or "").strip()) and _provider_price_float(info) > 0

def _miniapp_recommended_provider_code(data: dict[str, Any], mode: str) -> str:

    buyable: list[tuple[str, dict[str, Any], float]] = []

    for provider_code, info in (data or {}).items():

        code = str(provider_code or "").strip().lower()

        if not isinstance(info, dict) or not _miniapp_provider_buyable(mode, code, info):

            continue

        if bool(info.get("recommendation_blocked")):

            continue

        if mode == "rental":

            prices = []

            for option in info.get("options") or []:

                if not isinstance(option, dict):

                    continue

                try:

                    price = float(option.get("price") or 0.0)

                except Exception:

                    price = 0.0

                if price > 0:

                    prices.append(price)

            price = min(prices) if prices else 0.0

        else:

            price = _provider_price_float(info)

        if price > 0:

            buyable.append((code, info, price))

    if not buyable:

        return ""

    cheapest = min(price for _code, _info, price in buyable)

    min_attempts = max(1, int(getattr(settings, "numbers_success_rate_display_min_attempts", 5) or 5))

    candidates: list[tuple[tuple[float, float, int, str, str], str]] = []

    for code, info, price in buyable:

        try:

            rate = float(

                info.get("recommended_success_rate")

                if info.get("recommended_success_rate") is not None

                else info.get("success_rate", 100)

            )

        except Exception:

            rate = 100.0

        rate = max(0.0, min(100.0, rate))

        try:

            attempts = int(info.get("success_attempts") or 0)

        except Exception:

            attempts = 0

        try:

            context_attempts = int(info.get("context_success_attempts") or 0)

        except Exception:

            context_attempts = 0

        if attempts < min_attempts and context_attempts < min_attempts:

            rate = min(rate, 90.0)

        public_rank, public_id, _ = _provider_sort_key(code)

        price_ratio = price / cheapest if cheapest > 0 else 1.0

        price_penalty = min(22.0, max(0.0, price_ratio - 1.0) * 12.0)

        sample_bonus = min(4.0, (attempts + (context_attempts * 2)) * 0.25)

        score = rate - price_penalty + sample_bonus

        candidates.append(((-score, price, public_rank, public_id, code), code))

    candidates.sort(key=lambda item: item[0])

    return candidates[0][1] if candidates else ""

def _voice_unavailable_prices(reason: str = "voice_unavailable") -> dict[str, dict[str, Any]]:

    return {

        "textverified": {

            "price": 0.0,

            "base_price": 0.0,

            "api_service_name": _VOICE_GENERIC_SERVICE,

            "available_for_buy": False,

            "provider_reason": reason,

            "voice_capable": True,

            "success_attempts": 0,

            "success_rate": None,

        }

    }

async def _get_miniapp_voice_prices(

    service: str,

    country: str = "1",

    state: str = "none",

    *,

    ignore_balance: bool = False,

) -> dict[str, Any]:

    raw = await get_all_voice_prices(service, country, state, ignore_balance=ignore_balance)

    if raw and any(_miniapp_provider_buyable("voice", str(code), info) for code, info in raw.items() if isinstance(info, dict)):

        return raw

    fallback_service = _VOICE_GENERIC_SERVICE

    if resolve_canonical_service_key(service) != fallback_service:

        fallback = await get_all_voice_prices(fallback_service, "1", state, ignore_balance=ignore_balance)

        if fallback:

            out: dict[str, Any] = {}

            for code, info in fallback.items():

                if not isinstance(info, dict):

                    continue

                patched = dict(info)

                patched["api_service_name"] = str(patched.get("api_service_name") or fallback_service)

                patched["voice_fallback_service"] = True

                patched["voice_requested_service"] = str(service or "")

                out[code] = patched

            if out:

                return out

    return _voice_unavailable_prices()

def _can_quote_temp_offer(

    *,

    mode: str,

    service: str | None,

    country: str | None,

    state: str | None,

    provider_code: str,

    info: dict[str, Any],

) -> bool:

    if mode != "temp":

        return False

    if provider_code in _HIDDEN_TEMP_PROVIDER_CODES:

        return False

    if not service:

        return False

    if not bool(info.get("available_for_buy", True)):

        return False

    if not str(info.get("api_service_name") or "").strip():

        return False

    try:

        return float(info.get("price") or 0.0) > 0

    except Exception:

        return False

def _can_quote_voice_offer(

    *,

    mode: str,

    service: str | None,

    provider_code: str,

    info: dict[str, Any],

) -> bool:

    if mode != "voice":

        return False

    if provider_code != "textverified":

        return False

    if not service:

        return False

    if not bool(info.get("available_for_buy", True)):

        return False

    if not bool(info.get("voice_capable", True)):

        return False

    if not str(info.get("api_service_name") or "").strip():

        return False

    try:

        return float(info.get("price") or 0.0) > 0

    except Exception:

        return False

def _rental_option_match_key(option: dict[str, Any]) -> tuple[str, str, str, str, str, str]:

    return (

        str(option.get("duration") or "").strip(),

        str(option.get("rental_id") or "").strip(),

        str(option.get("tv_duration_key") or "").strip(),

        "1" if bool(option.get("tv_is_renewable")) else "0",

        str(option.get("state_code") or "none").strip().lower(),

        str(option.get("duration_label") or "").strip().lower(),

    )

def _can_quote_rental_option(

    *,

    mode: str,

    service: str | None,

    country: str | None,

    provider_code: str,

    provider_info: dict[str, Any],

    option: dict[str, Any],

) -> bool:

    if mode != "rental":

        return False

    if not service or not country or not provider_code:

        return False

    if not bool(provider_info.get("available_for_buy", True)):

        return False

    if not str(provider_info.get("api_service_name") or "").strip():

        return False

    try:

        duration = int(option.get("duration") or 0)

        price = float(option.get("price") or 0.0)

    except Exception:

        return False

    return duration > 0 and price > 0

def _rental_duration_label(option: dict[str, Any]) -> str:

    label = str(option.get("duration_label") or "").strip()

    if label:

        return label

    try:

        hours = int(option.get("duration") or 0)

    except Exception:

        hours = 0

    if hours <= 0:

        return "-"

    if hours % 24 == 0:

        days = hours // 24

        return f"{days}d"

    return f"{hours}h"

def _rental_state_code_for_quote(state: str | None) -> str:

    raw = str(state or "none").strip().upper()

    if raw and raw != "NONE" and len(raw) == 2:

        return raw

    return "none"

def _miniapp_rental_option_candidates(

    provider_code: str,

    provider_info: dict[str, Any],

    *,

    state: str | None = None,

) -> list[dict[str, Any]]:

    provider_code = str(provider_code or "").strip().lower()

    api_service = str((provider_info or {}).get("api_service_name") or "").strip()

    state_code = _rental_state_code_for_quote(state)

    use_textverified_state = provider_code == "textverified" and state_code != "none"

    rows: list[dict[str, Any]] = []

    for raw_option in (provider_info or {}).get("options") or []:

        if not isinstance(raw_option, dict):

            continue

        option = dict(raw_option)

        option.setdefault("provider", provider_code)

        option.setdefault("api_service_name", api_service)

        if provider_code == "textverified":

            option["tv_with_state"] = bool(use_textverified_state)

            option["state_code"] = state_code if use_textverified_state else "none"

            if use_textverified_state:

                try:

                    option["price"] = round(float(option.get("price") or 0.0) + _TEXTVERIFIED_RENTAL_STATE_SURCHARGE, 4)

                except Exception:

                    option["price"] = _TEXTVERIFIED_RENTAL_STATE_SURCHARGE

                if option.get("base_price") not in (None, ""):

                    try:

                        option["base_price"] = round(float(option.get("base_price") or 0.0) + _TEXTVERIFIED_RENTAL_STATE_SURCHARGE, 4)

                    except Exception:

                        option["base_price"] = option["price"]

                option["state_surcharge"] = _TEXTVERIFIED_RENTAL_STATE_SURCHARGE

        else:

            option.setdefault("state_code", "none")

        rows.append(option)

    return rows

async def _resolve_rental_offer_from_quote(token: str) -> dict[str, Any]:

    quote = _verify_quote_token(token)

    if str(quote.get("mode") or "").strip().lower() != "rental":

        raise web.HTTPBadRequest(text="invalid quote")

    service = resolve_canonical_service_key(str(quote.get("service") or ""))

    provider_code = str(quote.get("provider") or "").strip().lower()

    country = str(quote.get("country") or "none").strip() or "none"

    match_key = tuple(str(part) for part in (quote.get("option_key") or []))

    if not service or not provider_code or not country or len(match_key) != 6:

        raise web.HTTPBadRequest(text="invalid quote")

    state = _rental_state_code_for_quote(str(quote.get("state") or match_key[4] or "none"))

    prices = await asyncio.wait_for(

        get_all_rental_prices(service, country, with_success_rates=False),

        timeout=_PRICE_TIMEOUT_SEC,

    )

    provider_info = prices.get(provider_code)

    if not isinstance(provider_info, dict):

        raise web.HTTPBadRequest(text="provider unavailable")

    api_service = str(provider_info.get("api_service_name") or "").strip()

    if not api_service:

        raise web.HTTPBadRequest(text="provider unavailable")

    for option in _miniapp_rental_option_candidates(provider_code, provider_info, state=state):

        if _rental_option_match_key(option) != match_key:

            continue

        if not _can_quote_rental_option(

            mode="rental",

            service=service,

            country=country,

            provider_code=provider_code,

            provider_info=provider_info,

            option=option,

        ):

            raise web.HTTPBadRequest(text="provider unavailable")

        return {

            "service": service,

            "country": country,

            "provider_code": provider_code,

            "provider_info": provider_info,

            "option": option,

        }

    raise web.HTTPBadRequest(text="option unavailable")

async def _resolve_temp_offer_from_quote(token: str) -> dict[str, Any]:

    quote = _verify_quote_token(token)

    if str(quote.get("mode") or "temp").strip().lower() != "temp":

        raise web.HTTPBadRequest(text="invalid quote")

    service = resolve_canonical_service_key(str(quote.get("service") or ""))

    provider_code = str(quote.get("provider") or "").strip().lower()

    country = str(quote.get("country") or "none").strip() or "none"

    state = str(quote.get("state") or "none").strip() or "none"

    if country != "1":

        state = "none"

    if not service or not provider_code:

        raise web.HTTPBadRequest(text="invalid quote")

    if provider_code in _HIDDEN_TEMP_PROVIDER_CODES:

        raise web.HTTPBadRequest(text="provider unavailable")

    prices = await asyncio.wait_for(

        get_all_prices(service, country, state, with_success_rates=False),

        timeout=_PRICE_TIMEOUT_SEC,

    )

    info = prices.get(provider_code)

    if not isinstance(info, dict):

        raise web.HTTPBadRequest(text="provider unavailable")

    if not _can_quote_temp_offer(

        mode="temp",

        service=service,

        country=country,

        state=state,

        provider_code=provider_code,

        info=info,

    ):

        raise web.HTTPBadRequest(text="provider unavailable")

    return {

        "service": service,

        "country": country,

        "state": state,

        "provider_code": provider_code,

        "info": info,

    }

async def _resolve_voice_offer_from_quote(token: str) -> dict[str, Any]:

    quote = _verify_quote_token(token)

    if str(quote.get("mode") or "").strip().lower() != "voice":

        raise web.HTTPBadRequest(text="invalid quote")

    service = resolve_canonical_service_key(str(quote.get("service") or ""))

    provider_code = str(quote.get("provider") or "").strip().lower()

    if not service or not provider_code:

        raise web.HTTPBadRequest(text="invalid quote")

    country = "1"

    state = str(quote.get("state") or "none").strip() or "none"

    prices = await asyncio.wait_for(

        _get_miniapp_voice_prices(service, country, state, ignore_balance=True),

        timeout=_PRICE_TIMEOUT_SEC,

    )

    info = prices.get(provider_code)

    if not isinstance(info, dict):

        raise web.HTTPBadRequest(text="provider unavailable")

    if not _can_quote_voice_offer(

        mode="voice",

        service=service,

        provider_code=provider_code,

        info=info,

    ):

        raise web.HTTPBadRequest(text="provider unavailable")

    return {

        "service": service,

        "country": country,

        "state": state,

        "provider_code": provider_code,

        "info": info,

    }

def _order_public_status(order: dict[str, Any]) -> str:

    mode = str(order.get("number_mode") or "").strip().lower()

    status = str(order.get("status") or "").strip().lower()

    if mode == "rental":

        if status in {"cancelled", "refunded"} or order.get("rental_refunded_at"):

            return "refunded"

        if status in {"failed", "expired"}:

            return status

        if order.get("rental_finished_at"):

            return "finished"

        if int(order.get("rental_sms_count") or 0) > 0 or order.get("rental_sms_received_at"):

            return "code_received"

        return "waiting"

    wait_state = str(order.get("temp_wait_state") or "").strip().lower()

    if mode == "voice":

        if status in {"cancelled", "refunded"} or wait_state in {"refunded", "auto_refunded"}:

            return "refunded"

        if status in {"failed", "expired"}:

            return status

        if order.get("voice_recording_uri") or wait_state == "call_received":

            return "call_received"

        if wait_state == "refund_pending":

            return "refund_pending"

        return "waiting"

    if status in {"cancelled", "refunded"} or wait_state in {"refunded", "auto_refunded"}:

        return "refunded"

    if status in {"failed", "expired"}:

        return status

    if _temp_second_code_waiting(order):

        return "waiting"

    if _temp_order_has_received_code(order):

        return "code_received"

    if wait_state == "refund_pending":

        return "refund_pending"

    return "waiting"

def _temp_my_numbers_expires_at(order: dict[str, Any]) -> datetime | None:

    created_at = _coerce_utc_datetime((order or {}).get("created_at"))

    if not created_at:

        return None

    return created_at + timedelta(days=_TEMP_MY_NUMBERS_RETENTION_DAYS)

def _temp_my_numbers_active(order: dict[str, Any]) -> bool:

    if str((order or {}).get("number_mode") or "").strip().lower() != "temp":

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

    return True if not expires_at else _seconds_left_until(expires_at) > 0

def _temp_resend_available(order: dict[str, Any]) -> bool:

    return _temp_my_numbers_active(order)

def _temp_second_code_waiting(order: dict[str, Any]) -> bool:

    if str((order or {}).get("number_mode") or "").strip().lower() != "temp":

        return False

    if str((order or {}).get("temp_wait_state") or "").strip().lower() != "waiting":

        return False

    second_requested_at = _coerce_utc_datetime((order or {}).get("temp_second_code_last_at"))

    if not second_requested_at:

        return False

    last_sms_at = _coerce_utc_datetime((order or {}).get("temp_last_sms_at"))

    return not last_sms_at or second_requested_at > last_sms_at

def _temp_like_replace_available(order: dict[str, Any]) -> bool:

    mode = str((order or {}).get("number_mode") or "").strip().lower()

    if mode not in {"temp", "voice"}:

        return False

    status = str((order or {}).get("status") or "").strip().lower()

    wait_state = str((order or {}).get("temp_wait_state") or "").strip().lower()

    closed = status in {"cancelled", "refunded", "failed", "expired"} or wait_state in {"refunded", "auto_refunded"}

    if not closed:

        return False

    if mode == "voice":

        return not bool((order or {}).get("voice_recording_uri") or wait_state == "call_received")

    return not _temp_order_has_received_code(order)

def _rental_cancel_available(order: dict[str, Any]) -> bool:

    if str((order or {}).get("number_mode") or "").strip().lower() != "rental":

        return False

    if _order_public_status(order) != "waiting":

        return False

    if not _rental_no_sms_yet(order):

        return False

    if str((order or {}).get("status") or "").strip().lower() in {"cancelled", "failed", "refunded", "expired"}:

        return False

    deadline_at = _rental_deadline_at(order)

    return True if not deadline_at else _seconds_left_until(deadline_at) > 0

def _second_code_price(order: dict[str, Any]) -> tuple[float, float]:

    sale_price, cost_price = extract_order_amounts(order)

    return round(max(0.0, float(sale_price)) / 2.0, 4), round(max(0.0, float(cost_price)) / 2.0, 4)

def _order_payload(order: dict[str, Any]) -> dict[str, Any]:

    sale_price, cost_price = extract_order_amounts(order)

    mode = str(order.get("number_mode") or "temp").strip().lower() or "temp"

    provider_code = _order_provider_code(order)

    if mode == "rental":

        messages = [str(item) for item in (order.get("rental_sms_messages") or []) if str(item or "").strip()]

        rental_tags = [str(item) for item in (order.get("rental_tags") or []) if str(item or "").strip()]

        public_status = _order_public_status(order)

        return {

            "id": str(order.get("_id") or ""),

            "mode": "rental",

            "status": str(order.get("status") or ""),

            "public_status": public_status,

            "provider": provider_display_name(provider_code),

            "provider_id": provider_public_id(provider_code),

            "service": str(order.get("service_id") or "").replace(":rental", ""),

            "service_label": _service_label(str(order.get("service_id") or "").replace(":rental", "")),

            "country": str(order.get("rental_country") or ""),

            "state": str(order.get("rental_state_code") or "none"),

            "number": str(order.get("provider_number") or ""),

            "code": messages[-1] if messages else "",

            "codes": messages,

            "messages": messages,

            "sms_count": len(messages),

            "notes": str(order.get("rental_notes") or ""),

            "tags": rental_tags,

            "details": _order_detail_rows(order, mode="rental", public_status=public_status),

            "price": float(sale_price),

            "price_label": _money(sale_price),

            "base_price_label": _money(cost_price),

            "duration_label": str(order.get("rental_duration_label") or ""),

            "end_date": str(order.get("rental_end_date") or ""),

            "can_refresh": public_status in {"waiting", "code_received"},

            "can_sms": public_status in {"waiting", "code_received"},

            "can_finish": public_status in {"waiting", "code_received"},

            "can_renew": bool(order.get("rental_is_renewable")) and public_status in {"waiting", "code_received"},

            "can_wake": public_status in {"waiting", "code_received"},

            "can_notes": public_status in {"waiting", "code_received"},

            "can_cancel": _rental_cancel_available(order),

            "seconds_left": 0,

            "cancel_wait_sec": 0,

        }

    elapsed = _temp_elapsed_sec(order)

    timeout_sec = _order_temp_timeout_sec(order)

    cancel_left = max(0, TEMP_CANCEL_AFTER_SEC - elapsed)

    codes = [str(code) for code in (order.get("temp_codes") or []) if str(code or "").strip()]

    if mode == "voice":

        public_status = _order_public_status(order)

        recording_uri = str(order.get("voice_recording_uri") or "").strip()

        calls = [item for item in (order.get("voice_calls") or []) if isinstance(item, dict)]

        order_id = str(order.get("_id") or "")

        return {

            "id": order_id,

            "mode": "voice",

            "status": str(order.get("status") or ""),

            "public_status": public_status,

            "wait_state": str(order.get("temp_wait_state") or ""),

            "provider": provider_display_name(provider_code),

            "provider_id": provider_public_id(provider_code),

            "service": str(order.get("temp_service_key") or order.get("service_id") or ""),

            "service_label": _service_label(str(order.get("temp_service_key") or order.get("service_id") or "")),

            "country": str(order.get("temp_country") or "1"),

            "state": str(order.get("temp_state") or "none"),

            "number": str(order.get("provider_number") or ""),

            "code": "",

            "codes": [],

            "calls_count": int(order.get("voice_calls_count") or len(calls) or 0),

            "recording_available": bool(recording_uri),

            "recording_url": f"/mini/numbers/api/orders/{order_id}/recording" if recording_uri and order_id else "",

            "details": _order_detail_rows(order, mode="voice", public_status=public_status),

            "price": float(sale_price),

            "price_label": _money(sale_price),

            "base_price_label": _money(cost_price),

            "elapsed_sec": int(elapsed),

            "timeout_sec": int(timeout_sec),

            "seconds_left": max(0, int(timeout_sec) - int(elapsed)),

            "can_refresh": public_status in {"waiting", "refund_pending"},

            "can_cancel": cancel_left <= 0 and public_status == "waiting",

            "can_replace": _temp_like_replace_available(order),

            "cancel_wait_sec": int(cancel_left),

        }

    public_status = _order_public_status(order)

    display_code = str(order.get("temp_last_code") or (codes[-1] if codes else "")) if public_status == "code_received" else ""

    second_sale, _second_cost = _second_code_price(order)

    can_second_code = bool(public_status == "code_received" and _temp_resend_available(order) and second_sale > 0)

    replace_available = _temp_like_replace_available(order)

    alternate_provider_code = str(order.get("temp_alternate_provider") or "").strip().lower()

    current_provider_code = provider_code

    alternate_provider_enabled = bool(order.get("temp_alternate_enabled")) and bool(alternate_provider_code)

    alternate_provider_available = bool(

        replace_available and alternate_provider_enabled and alternate_provider_code != current_provider_code

    )

    return {

        "id": str(order.get("_id") or ""),

        "mode": "temp",

        "status": str(order.get("status") or ""),

        "public_status": public_status,

        "wait_state": str(order.get("temp_wait_state") or ""),

        "provider": provider_display_name(provider_code),

        "provider_id": provider_public_id(provider_code),

        "service": str(order.get("temp_service_key") or order.get("service_id") or ""),

        "service_label": _service_label(str(order.get("temp_service_key") or order.get("service_id") or "")),

        "country": str(order.get("temp_country") or ""),

        "state": str(order.get("temp_state") or "none"),

        "number": str(order.get("provider_number") or ""),

        "code": display_code,

        "codes": codes,

        "details": _order_detail_rows(order, mode="temp", public_status=public_status),

        "price": float(sale_price),

        "price_label": _money(sale_price),

        "base_price_label": _money(cost_price),

        "can_second_code": can_second_code,

        "second_code_price": float(second_sale),

        "second_code_price_label": _money(second_sale),

        "second_code_count": int(order.get("temp_second_code_count") or 0),

        "can_replace": replace_available,

        "can_alternate_provider": alternate_provider_available,

        "alternate_provider": provider_display_name(alternate_provider_code) if alternate_provider_available else "",

        "alternate_provider_id": provider_public_id(alternate_provider_code) if alternate_provider_available else "",

        "alternate_provider_price_label": _money(order.get("temp_alternate_price")) if alternate_provider_available else "",

        "elapsed_sec": int(elapsed),

        "timeout_sec": int(timeout_sec),

        "seconds_left": max(0, int(timeout_sec) - int(elapsed)),

        "can_refresh": public_status in {"waiting", "code_received", "refund_pending"},

        "can_cancel": cancel_left <= 0 and not _temp_order_has_received_code(order) and public_status == "waiting",

        "cancel_wait_sec": int(cancel_left),

    }

async def _finalize_temp_local_refund(

    *,

    order_id: Any,

    order: dict[str, Any],

    actor_user_id: int,

    reason: str,

    provider_raw: Any = None,

    provider_terminal_reason: str = "",

) -> dict[str, Any]:

    return await _shared_finalize_temp_local_refund(

        order_id=order_id,

        order=order,

        actor_user_id=actor_user_id,

        reason=reason,

        financial_manager=FinancialManager,

        update_order_status_fn=update_order_status,

        update_order_details_fn=update_order_details,

        log_temp_event_fn=_log_temp_event,

        log_number_event_from_order_fn=_log_number_event_from_order,

        provider_raw=provider_raw,

        provider_terminal_reason=provider_terminal_reason,

        source="numbers_miniapp",

        status_after="cancelled",

        extra_patch={"temp_replace_enabled": True},

    )

async def _cancel_and_refund_temp_order(

    *,

    order_id: Any,

    order: dict[str, Any],

    actor_user_id: int,

    reason: str,

    require_no_sms: bool = True,

    allow_provider_terminal_refund: bool = False,

    allow_empty_provider_refund: bool = False,

) -> dict[str, Any]:

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

        allow_provider_terminal_refund=allow_provider_terminal_refund,

        allow_empty_provider_refund=allow_empty_provider_refund,

        source="numbers_miniapp",

        final_status="cancelled",

        extra_refund_patch={"temp_replace_enabled": True},

        sleep_fn=asyncio.sleep,

    )

def _temp_refund_result_retryable(result: dict[str, Any]) -> bool:

    return _shared_temp_refund_result_retryable(result)

async def _mark_temp_refund_pending(

    *,

    order_id: Any,

    order: dict[str, Any],

    result: dict[str, Any],

    source: str,

) -> dict[str, Any]:

    now = _utc_now()

    attempts = int((order or {}).get("temp_refund_retry_attempts") or 0) + 1

    await update_order_details(

        order_id,

        {

            "temp_wait_timeout_at": (order or {}).get("temp_wait_timeout_at") or now,

            "temp_wait_state": "refund_pending",

            "temp_replace_enabled": True,

            "temp_refund_retry_attempts": attempts,

            "temp_refund_retry_last_at": now,

            "temp_refund_retry_reason": str((result or {}).get("reason") or "provider_cancel_failed"),

        },

    )

    await _log_temp_event(

        order,

        "refund_pending",

        {

            "source": source,

            "attempts": attempts,

            "reason": str((result or {}).get("reason") or ""),

            "raw": (result or {}).get("raw"),

        },

    )

    return await get_order(order_id) or order

async def _retry_pending_temp_refund(order: dict[str, Any], *, source: str) -> dict[str, Any]:

    if not order or not order.get("_id"):

        return order

    provider = _order_provider_code(order)

    provider_order_id = _order_provider_order_id(order)

    if provider and provider_order_id:

        sms_data = await fetch_provider_sms(PROVIDERS, provider, provider_order_id)

        seen_codes = set(str(code) for code in (order.get("temp_codes") or []) if str(code or "").strip())

        code = _extract_new_sms_code((sms_data or {}).get("messages") or [], seen_codes)

        if code:

            return await get_order(order["_id"]) or order

        terminal_reason = _provider_terminal_refund_reason(

            (sms_data or {}).get("raw"),

            allow_missing=True,

            allow_empty=True,

        )

        if terminal_reason:

            result = await _finalize_temp_local_refund(

                order_id=order["_id"],

                order=order,

                actor_user_id=int(order.get("user_id") or 0),

                reason=f"{source}_{terminal_reason}",

                provider_raw=(sms_data or {}).get("raw"),

                provider_terminal_reason=terminal_reason,

            )

            if result.get("success"):

                return await get_order(order["_id"]) or order

            if _temp_refund_result_retryable(result):

                return await _mark_temp_refund_pending(

                    order_id=order["_id"],

                    order=order,

                    result=result,

                    source=source,

                )

            return await get_order(order["_id"]) or order

    result = await _cancel_and_refund_temp_order(

        order_id=order["_id"],

        order=order,

        actor_user_id=int(order.get("user_id") or 0),

        reason=source,

        require_no_sms=True,

        allow_provider_terminal_refund=True,

        allow_empty_provider_refund=True,

    )

    if result.get("success"):

        return await get_order(order["_id"]) or order

    if _temp_refund_result_retryable(result):

        return await _mark_temp_refund_pending(

            order_id=order["_id"],

            order=order,

            result=result,

            source=source,

        )

    return await get_order(order["_id"]) or order

async def _refresh_temp_order(order: dict[str, Any]) -> dict[str, Any]:

    if not order or not order.get("_id"):

        return order

    if str(order.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:

        return order

    provider = _order_provider_code(order)

    provider_order_id = _order_provider_order_id(order)

    if not provider or not provider_order_id:

        return order

    current = await get_order(order["_id"]) or order

    if str(current.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:

        return current

    if str(current.get("temp_wait_state") or "").strip().lower() == "refund_pending":

        return await _retry_pending_temp_refund(current, source="miniapp_refund_retry")

    if _temp_order_has_received_code(current) and not _temp_second_code_waiting(current):

        return current

    sms_data = await fetch_provider_sms(PROVIDERS, provider, provider_order_id)

    seen_codes = set(str(code) for code in (current.get("temp_codes") or []) if str(code or "").strip())

    code = _extract_new_sms_code(sms_data.get("messages") or [], seen_codes)

    if code:

        now = _utc_now()

        clean_code = _safe_code_text(code)

        updated_codes = list(seen_codes)

        updated_codes.append(clean_code)

        patch = {

            "temp_wait_state": "code_received",

            "temp_last_sms_at": now,

            "temp_last_code": clean_code,

            "temp_codes": updated_codes,

            "temp_codes_count": len(updated_codes),

        }

        if not current.get("temp_first_sms_at"):

            patch["temp_first_sms_at"] = now

            seconds_to_first_sms = _seconds_between(now, current.get("created_at"))

            if seconds_to_first_sms is not None:

                patch["temp_seconds_to_first_sms"] = seconds_to_first_sms

        await update_order_details(current["_id"], patch)

        await _log_temp_event(

            current,

            "code_received",

            {

                "code_len": len(clean_code),

                "seconds_since_purchase": _seconds_between(now, current.get("created_at")),

                "source": "numbers_miniapp_poll",

            },

        )

        return await get_order(current["_id"]) or {**current, **patch}

    now = _utc_now()

    await update_order_details(current["_id"], {"temp_last_refresh_at": now})

    current = await get_order(current["_id"]) or current

    timeout_reached = _temp_elapsed_sec(current) >= _order_temp_timeout_sec(current)

    terminal_reason = _provider_terminal_refund_reason(

        (sms_data or {}).get("raw"),

        allow_missing=timeout_reached,

        allow_empty=timeout_reached,

    )

    if terminal_reason:

        if terminal_reason == "provider_already_refunded":

            result = await _finalize_temp_local_refund(

                order_id=current["_id"],

                order=current,

                actor_user_id=int(current.get("user_id") or 0),

                reason=f"miniapp_provider_{terminal_reason}",

                provider_raw=(sms_data or {}).get("raw"),

                provider_terminal_reason=terminal_reason,

            )

        else:

            result = await _cancel_and_refund_temp_order(

                order_id=current["_id"],

                order=current,

                actor_user_id=int(current.get("user_id") or 0),

                reason=f"miniapp_provider_{terminal_reason}",

                require_no_sms=True,

                allow_provider_terminal_refund=True,

                allow_empty_provider_refund=True,

            )

        if result.get("success"):

            return await get_order(current["_id"]) or current

        current = await _mark_temp_refund_pending(

            order_id=current["_id"],

            order=current,

            result=result,

            source="numbers_miniapp_provider_terminal",

        )

        return current

    if not timeout_reached:

        return current

    result = await _cancel_and_refund_temp_order(

        order_id=current["_id"],

        order=current,

        actor_user_id=int(current.get("user_id") or 0),

        reason="miniapp_timeout_auto_refund",

        require_no_sms=True,

        allow_provider_terminal_refund=True,

        allow_empty_provider_refund=True,

    )

    if result.get("success"):

        return await get_order(current["_id"]) or current

    current = await _mark_temp_refund_pending(

        order_id=current["_id"],

        order=current,

        result=result,

        source="numbers_miniapp_timeout",

    )

    await _log_temp_event(

        current,

        "wait_timeout",

        {

            "timeout_sec": _order_temp_timeout_sec(current),

            "auto_refund_failed": True,

            "auto_refund_reason": str(result.get("reason") or ""),

            "source": "numbers_miniapp",

        },

    )

    return current

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

async def _refresh_voice_order(order: dict[str, Any]) -> dict[str, Any]:

    if not order or not order.get("_id"):

        return order

    if str(order.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:

        return order

    provider = _order_provider_code(order)

    provider_order_id = _order_provider_order_id(order)

    if not provider or not provider_order_id:

        return order

    current = await get_order(order["_id"]) or order

    if str(current.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:

        return current

    if str(current.get("temp_wait_state") or "").strip().lower() == "refund_pending":

        return await _retry_pending_temp_refund(current, source="miniapp_voice_refund_retry")

    if str(current.get("voice_recording_uri") or "").strip():

        return current

    now = _utc_now()

    try:

        calls_data = await get_calls_from_provider(

            provider,

            provider_order_id,

            to_number=str(current.get("provider_number") or ""),

        )

    except Exception as exc:

        await update_order_details(

            current["_id"],

            {

                "temp_last_refresh_at": now,

                "voice_last_check_failed_at": now,

                "voice_last_check_error": str(exc),

            },

        )

        return await get_order(current["_id"]) or current

    calls = [dict(item) for item in (calls_data.get("calls") or []) if isinstance(item, dict)]

    recording_uri = _voice_recording_uri_from_calls(calls)

    patch: dict[str, Any] = {

        "temp_last_refresh_at": now,

        "voice_last_check_at": now,

        "voice_calls": calls[:5],

        "voice_calls_count": len(calls),

    }

    if recording_uri:

        patch.update(

            {

                "temp_wait_state": "call_received",

                "voice_call_received_at": now,

                "voice_recording_uri": recording_uri,

            }

        )

        await update_order_details(current["_id"], patch)

        await _log_temp_event(

            current,

            "voice_call_received",

            {"has_recording": True, "source": "numbers_miniapp_poll"},

        )

        return await get_order(current["_id"]) or {**current, **patch}

    await update_order_details(current["_id"], patch)

    current = await get_order(current["_id"]) or {**current, **patch}

    timeout_reached = _temp_elapsed_sec(current) >= _order_temp_timeout_sec(current)

    terminal_reason = _provider_terminal_refund_reason(

        (calls_data or {}).get("raw"),

        allow_missing=timeout_reached,

        allow_empty=timeout_reached,

    )

    if terminal_reason:

        if terminal_reason == "provider_already_refunded":

            result = await _finalize_temp_local_refund(

                order_id=current["_id"],

                order=current,

                actor_user_id=int(current.get("user_id") or 0),

                reason=f"miniapp_voice_provider_{terminal_reason}",

                provider_raw=(calls_data or {}).get("raw"),

                provider_terminal_reason=terminal_reason,

            )

        else:

            result = await _cancel_and_refund_temp_order(

                order_id=current["_id"],

                order=current,

                actor_user_id=int(current.get("user_id") or 0),

                reason=f"miniapp_voice_provider_{terminal_reason}",

                require_no_sms=True,

                allow_provider_terminal_refund=True,

                allow_empty_provider_refund=True,

            )

        if result.get("success"):

            return await get_order(current["_id"]) or current

        current = await _mark_temp_refund_pending(

            order_id=current["_id"],

            order=current,

            result=result,

            source="numbers_miniapp_voice_provider_terminal",

        )

        return current

    if not timeout_reached:

        return current

    result = await _cancel_and_refund_temp_order(

        order_id=current["_id"],

        order=current,

        actor_user_id=int(current.get("user_id") or 0),

        reason="miniapp_voice_timeout_auto_refund",

        require_no_sms=True,

        allow_provider_terminal_refund=True,

        allow_empty_provider_refund=True,

    )

    if result.get("success"):

        return await get_order(current["_id"]) or current

    current = await _mark_temp_refund_pending(

        order_id=current["_id"],

        order=current,

        result=result,

        source="numbers_miniapp_voice_timeout",

    )

    await _log_temp_event(

        current,

        "voice_wait_timeout",

        {

            "timeout_sec": _order_temp_timeout_sec(current),

            "auto_refund_failed": True,

            "auto_refund_reason": str(result.get("reason") or ""),

            "source": "numbers_miniapp",

        },

    )

    return current

def _second_code_log_payload(order: dict[str, Any], *, now: datetime, extra: dict[str, Any] | None = None) -> dict[str, Any]:

    payload: dict[str, Any] = {

        "provider": _order_provider_code(order),

        "provider_order_id": _order_provider_order_id(order),

        "seconds_since_purchase": _seconds_between(now, order.get("created_at")),

        "seconds_since_first_code": _seconds_between(now, order.get("temp_first_sms_at")),

        "seconds_since_last_sms": _seconds_between(now, order.get("temp_last_sms_at")),

        "seconds_since_previous_second_code": _seconds_between(now, order.get("temp_second_code_last_at")),

        "resend_retention_expires_at": (

            _temp_my_numbers_expires_at(order).isoformat() if _temp_my_numbers_expires_at(order) else None

        ),

        "resend_guarantee_seconds": _order_reuse_warranty_sec(order),

        "codes_count_before": int(order.get("temp_codes_count") or len(order.get("temp_codes") or []) or 0),

        "source": "numbers_miniapp",

    }

    if extra:

        payload.update(extra)

    return payload

async def _request_second_code_for_order(

    *,

    order_id: Any,

    order: dict[str, Any],

    user_id: int,

    reseller_id: int,

    lang: str,

) -> dict[str, Any]:

    result = await _shared_request_second_code_for_order(

        order_id=order_id,

        order=order,

        user_id=user_id,

        reseller_id=reseller_id,

        providers=PROVIDERS,

        provider_resend_fn=provider_resend,

        financial_manager=FinancialManager,

        create_order_fn=create_order,

        update_order_details_fn=update_order_details,

        update_order_status_fn=update_order_status,

        get_order_fn=get_order,

        log_temp_event_fn=_log_temp_event,

        temp_resend_available_fn=_temp_resend_available,

        second_code_price_fn=_second_code_price,

        second_code_log_payload_fn=_second_code_log_payload,

        source="numbers_miniapp",

        telegram_bot_id=None,

        refresh_order_fn=_refresh_temp_order,

    )

    if result.get("ok"):

        extra_sale = float(result.get("extra_sale") or 0.0)

        return {

            "ok": True,

            "message": _text(lang, f"Second code requested. Charged {_money(extra_sale)}.", f"تم طلب كود ثاني. تم خصم {_money(extra_sale)}."),

            "order": _order_payload(result.get("order") or order),

            "second_order_id": str(result.get("second_order_id") or ""),

        }

    code = str(result.get("code") or "")

    if code == "invalid_mode":

        message = _text(lang, "This action is only for temporary numbers.", "هذا الإجراء خاص بالأرقام المؤقتة فقط.")

    elif code == "order_not_found":

        message = _text(lang, "Order not found.", "الطلب غير موجود.")

    elif code == "finance_error":

        message = finance_error_public_text(lang, str(result.get("finance_message") or ""))

        code = str(result.get("finance_message") or code)

    elif code == "second_code_provider_failed":

        message = _text(lang, "Provider could not request a second code right now.", "المزود لم يستطع طلب كود ثاني حالياً.")

    else:

        message = _text(lang, "Second code is not available for this order.", "الكود الثاني غير متاح لهذا الطلب.")

    return {"ok": False, "code": code, "message": message}

def _pick_alternate_temp_provider(

    prices: dict[str, Any],

    *,

    current_provider: str,

    service: str,

    country: str,

    state: str,

) -> tuple[str, dict[str, Any]] | None:
    quoteable = {
        str(code or "").strip().lower(): info
        for code, info in (prices or {}).items()
        if isinstance(info, dict)
        and _can_quote_temp_offer(
            mode="temp",
            service=service,
            country=country,
            state=state,
            provider_code=str(code or "").strip().lower(),
            info=info,
        )
    }
    return _shared_pick_retry_provider(
        quoteable,
        exclude_provider=current_provider,
        hidden_provider_codes=_HIDDEN_TEMP_PROVIDER_CODES,
    )

async def _enable_alternate_provider_suggestion(

    *,

    order_id: Any,

    order: dict[str, Any],

    lang: str,

) -> dict[str, Any] | None:

    if str((order or {}).get("number_mode") or "").strip().lower() != "temp":

        return None

    if not _temp_like_replace_available(order):

        return None

    service = str(order.get("temp_service_key") or order.get("service_id") or "").strip()

    current_provider = _order_provider_code(order)

    country = str(order.get("temp_country") or order.get("provisioning_country") or "none").strip() or "none"

    state = str(order.get("temp_state") or order.get("provisioning_state_code") or "none").strip() or "none"

    if country != "1":

        state = "none"

    if not service:

        return None

    try:

        prices = await asyncio.wait_for(get_all_prices(service, country, state, with_success_rates=False), timeout=_PRICE_TIMEOUT_SEC)

    except Exception:

        return None

    picked = _pick_alternate_temp_provider(

        prices,

        current_provider=current_provider,

        service=service,

        country=country,

        state=state,

    )

    if not picked:

        return None

    provider_code, info = picked

    try:

        suggested_price = float(info.get("price") or 0.0)

    except Exception:

        suggested_price = 0.0

    await update_order_details(

        order_id,

        {

            "temp_alternate_enabled": True,

            "temp_alternate_provider": provider_code,

            "temp_alternate_api_service": str(info.get("api_service_name") or ""),

            "temp_alternate_price": suggested_price,

            "temp_alternate_base_price": float(info.get("base_price") or suggested_price),

            "temp_alternate_suggested_at": _utc_now(),

        },

    )

    await _log_temp_event(

        order,

        "alternate_provider_suggested",

        {

            "source": "numbers_miniapp",

            "provider": provider_code,

            "price": suggested_price,

            "message_language": lang,

        },

    )

    return {"provider": provider_code, "info": info, "price": suggested_price}

async def _request_replacement_number(

    *,

    order_id: Any,

    order: dict[str, Any],

    user_id: int,

    reseller_id: int,

    lang: str,

    alternate_provider: bool = False,

) -> dict[str, Any]:

    mode = str((order or {}).get("number_mode") or "").strip().lower()

    if mode not in {"temp", "voice"}:

        return {"ok": False, "code": "invalid_mode", "message": _text(lang, "This action is only for temporary numbers.", "هذا الإجراء خاص بالأرقام المؤقتة فقط.")}

    if not _temp_like_replace_available(order):

        return {"ok": False, "code": "replace_unavailable", "message": _text(lang, "A replacement is not available for this order.", "استبدال الرقم غير متاح لهذا الطلب.")}

    service = str(order.get("temp_service_key") or order.get("service_id") or "").strip()

    current_provider = _order_provider_code(order)

    provider_code = current_provider

    if alternate_provider and mode == "temp":

        if not bool(order.get("temp_alternate_enabled")):

            return {"ok": False, "code": "alternate_unavailable", "message": _text(lang, "No alternate provider is available for this order.", "لا يوجد مزود بديل متاح لهذا الطلب.")}

        suggested_provider = str(order.get("temp_alternate_provider") or "").strip().lower()

        if not suggested_provider or suggested_provider == current_provider:

            return {"ok": False, "code": "alternate_unavailable", "message": _text(lang, "No alternate provider is available for this order.", "لا يوجد مزود بديل متاح لهذا الطلب.")}

        provider_code = suggested_provider

    country = str(order.get("temp_country") or order.get("provisioning_country") or "none").strip() or "none"

    state = str(order.get("temp_state") or order.get("provisioning_state_code") or "none").strip() or "none"

    if mode == "voice":

        if alternate_provider:

            return {"ok": False, "code": "alternate_unavailable", "message": _text(lang, "No alternate provider is available for this order.", "لا يوجد مزود بديل متاح لهذا الطلب.")}

        country = "1"

        state = "none"

    elif country != "1":

        state = "none"

    if not service or (not provider_code and not alternate_provider):

        return {"ok": False, "code": "replace_unavailable", "message": _text(lang, "A replacement is not available for this order.", "استبدال الرقم غير متاح لهذا الطلب.")}

    if provider_code in _HIDDEN_TEMP_PROVIDER_CODES and not alternate_provider:

        return {"ok": False, "code": "replace_unavailable", "message": _text(lang, "A replacement is not available for this order.", "استبدال الرقم غير متاح لهذا الطلب.")}

    try:

        if mode == "voice":

            prices = await asyncio.wait_for(

                _get_miniapp_voice_prices(service, "1", state, ignore_balance=True),

                timeout=_PRICE_TIMEOUT_SEC,

            )

        else:

            prices = await asyncio.wait_for(get_all_prices(service, country, state, with_success_rates=False), timeout=_PRICE_TIMEOUT_SEC)

    except asyncio.TimeoutError:

        return {"ok": False, "code": "provider_timeout", "message": _text(lang, "Provider checks took too long. Try again.", "فحص المزودين أخذ وقت طويل. جرّب مرة ثانية.")}

    if alternate_provider:

        info = prices.get(provider_code) if provider_code and provider_code != current_provider else None

        if not isinstance(info, dict) or not _can_quote_temp_offer(

            mode="temp",

            service=service,

            country=country,

            state=state,

            provider_code=provider_code,

            info=info,

        ):

            return {"ok": False, "code": "alternate_unavailable", "message": _text(lang, "No alternate provider is available for this order.", "لا يوجد مزود بديل متاح لهذا الطلب.")}

    else:

        info = prices.get(provider_code)

    if not isinstance(info, dict):

        return {"ok": False, "code": "provider_unavailable", "message": _text(lang, "This provider is not available right now.", "هذا المزود غير متاح حالياً.")}

    if mode == "voice":

        can_buy = _can_quote_voice_offer(mode="voice", service=service, provider_code=provider_code, info=info)

    else:

        can_buy = _can_quote_temp_offer(

            mode="temp",

            service=service,

            country=country,

            state=state,

            provider_code=provider_code,

            info=info,

        )

    if not can_buy:

        return {"ok": False, "code": "provider_unavailable", "message": _text(lang, "This provider is not available right now.", "هذا المزود غير متاح حالياً.")}

    result = await _purchase_temp_offer(

        user_id=int(user_id),

        reseller_id=int(reseller_id),

        lang=lang,

        offer={

            "service": service,

            "country": country,

            "state": state,

            "provider_code": provider_code,

            "info": info,

        },

        number_mode=mode,

        source_order_id=str(order_id),

        source_reason="alternate_provider_request" if alternate_provider else "replace_request",

    )

    if result.get("ok"):

        await _log_temp_event(

            order,

            "replacement_requested",

            {

                "source": "numbers_miniapp",

                "replacement_order_id": str((result.get("order") or {}).get("id") or ""),

                "provider": provider_code,

                "alternate_provider": bool(alternate_provider),

            },

        )

    return result

async def _sync_rental_sms_snapshot(order_id: Any, order: dict[str, Any]) -> dict[str, Any]:

    provider = str(order.get("provider") or "").strip().lower()

    provider_order_id = str(order.get("provider_order_id") or "").strip()

    if not provider or not provider_order_id:

        return {"success": False, "has_sms": False, "messages": [], "raw": "provider_order_missing"}

    try:

        sms_data = await get_rental_sms_from_provider(provider, provider_order_id)

    except Exception as exc:

        return {"success": False, "has_sms": False, "messages": [], "raw": str(exc)}

    messages = [str(item) for item in (sms_data.get("messages") or []) if str(item or "").strip()]

    if messages:

        await update_order_details(

            order_id,

            {

                "rental_sms_received_at": _utc_now(),

                "rental_sms_count": len(messages),

                "rental_sms_messages": messages[:20],

            },

        )

        await _log_rental_event(

            order_id=order_id,

            user_id=int(order.get("user_id") or 0),

            provider=provider,

            service_id=str(order.get("service_id") or ""),

            event="code_received",

            payload={"messages_count": len(messages), "source": "numbers_miniapp"},

        )

    return {"success": bool(sms_data.get("success")), "has_sms": bool(messages), "messages": messages, "raw": sms_data.get("raw")}

async def _refresh_rental_order(order: dict[str, Any]) -> dict[str, Any]:

    if not order or not order.get("_id"):

        return order

    if str(order.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:

        return order

    await _sync_rental_sms_snapshot(order["_id"], order)

    return await get_order(order["_id"]) or order

async def _sync_rental_notes_tags_snapshot(order_id: Any, order: dict[str, Any]) -> dict[str, Any]:

    provider = str(order.get("provider") or "").strip().lower()

    provider_order_id = str(order.get("provider_order_id") or "").strip()

    if not provider or not provider_order_id:

        return {"success": False, "notes": "", "tags": [], "raw": "provider_order_missing"}

    try:

        data = await notes_tags_from_provider(provider, provider_order_id)

    except Exception as exc:

        return {"success": False, "notes": "", "tags": [], "raw": str(exc)}

    if not bool(data.get("success")):

        return {"success": False, "notes": "", "tags": [], "raw": data.get("raw")}

    notes = str(data.get("notes") or "")

    tags = [str(item) for item in (data.get("tags") or []) if str(item or "").strip()]

    await update_order_details(

        order_id,

        {

            "rental_notes": notes,

            "rental_tags": tags[:20],

            "rental_notes_tags_fetched_at": _utc_now(),

        },

    )

    await _log_number_event_from_order(

        order,

        "rental_notes_tags_fetched",

        payload={"source": "numbers_miniapp", "tags_count": len(tags), "has_notes": bool(notes)},

        number_mode="rental",

    )

    return {"success": True, "notes": notes, "tags": tags[:20], "raw": data.get("raw")}

async def _provider_close_rental(order: dict[str, Any]) -> dict[str, Any]:

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

                close_res = await asyncio.wait_for(finish_rental_from_provider(provider, provider_order_id), timeout=12.0)

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

    order_id: Any,

    order: dict[str, Any],

    actor_user_id: int,

    reason: str,

    require_no_sms: bool = False,

) -> dict[str, Any]:

    if not order_id or not order:

        return {"success": False, "reason": "order_not_found"}

    status = str(order.get("status") or "").lower()

    if status in {"cancelled", "failed", "refunded", "expired"}:

        return {"success": False, "reason": "already_closed"}

    provider = str(order.get("provider") or "").strip().lower()

    provider_order_id = str(order.get("provider_order_id") or "").strip()

    if not provider or not provider_order_id:

        return {"success": False, "reason": "provider_order_missing"}

    if require_no_sms:

        sms_snapshot = await _sync_rental_sms_snapshot(order_id, order)

        if sms_snapshot.get("has_sms"):

            return {"success": False, "reason": "sms_received", "messages": sms_snapshot.get("messages") or []}

    now = _utc_now()

    await update_order_details(

        order_id,

        {

            "rental_last_close_attempt_at": now,

            "rental_last_close_reason": str(reason or "cancelled"),

        },

    )

    await _log_number_event_from_order(

        order,

        "cancel_requested",

        payload={"reason": str(reason or "cancelled"), "source": "numbers_miniapp"},

        number_mode="rental",

    )

    close_res = await _provider_close_rental(order)

    if not close_res.get("success"):

        await update_order_details(

            order_id,

            {

                "rental_last_close_error_at": _utc_now(),

                "rental_last_close_error": str(close_res.get("reason") or "provider_close_failed"),

                "rental_last_close_raw": close_res.get("raw"),

            },

        )

        return {"success": False, "reason": str(close_res.get("reason") or "provider_close_failed"), "raw": close_res.get("raw")}

    sale_price, cost_price = extract_order_amounts(order)

    ok, msg = await FinancialManager.refund_core_purchase(

        int(actor_user_id),

        order_id,

        sale_price,

        cost_price,

        reseller_id=int(order.get("reseller_id") or actor_user_id),

    )

    if not ok:

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

        payload={"reason": str(reason or "cancelled"), "source": "numbers_miniapp"},

    )

    await _log_number_event_from_order(

        order,

        "refund_success",

        payload={"reason": str(reason or "cancelled"), "source": "numbers_miniapp"},

        status_after="cancelled",

        number_mode="rental",

    )

    return {"success": True, "reason": "ok"}

async def _miniapp_rental_refund_guard(*, order_id: Any, actor_user_id: int) -> None:

    order = await get_order(order_id)

    if not order:

        return

    provider = str(order.get("provider") or "").strip().lower()

    policy = _rental_protection_policy(provider)

    start_dt = _coerce_utc_datetime(order.get("rental_started_at")) or _coerce_utc_datetime(order.get("created_at"))

    if not start_dt:

        return

    cutoff_dt = _coerce_utc_datetime(order.get("rental_safe_cutoff_at"))

    if cutoff_dt:

        cutoff_ts = cutoff_dt.timestamp()

    else:

        deadline_sec = policy.get("refund_deadline_sec")

        if not deadline_sec:

            return

        cutoff_ts = start_dt.timestamp() + int(deadline_sec) - max(30, int(policy.get("safe_cutoff_sec") or 60))

    wait_sec = max(0, int(cutoff_ts - _utc_now().timestamp()))

    if wait_sec > 0:

        await asyncio.sleep(wait_sec)

    latest = await get_order(order_id)

    if not latest or not _rental_no_sms_yet(latest):

        return

    if str(latest.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:

        return

    sms_snapshot = await _sync_rental_sms_snapshot(order_id, latest)

    if sms_snapshot.get("has_sms"):

        return

    result = await _cancel_and_refund_rental_order(

        order_id=order_id,

        order=latest,

        actor_user_id=int(actor_user_id),

        reason=f"{provider}_miniapp_guard_no_sms_timeout",

        require_no_sms=True,

    )

    if result.get("success"):

        await _log_number_event_from_order(

            latest,

            "auto_protection_triggered",

            payload={"source": "numbers_miniapp_rental_guard"},

            status_after="cancelled",

            number_mode="rental",

        )

async def _purchase_temp_offer(

    *,

    user_id: int,

    reseller_id: int,

    lang: str,

    offer: dict[str, Any],

    number_mode: str = "temp",

    source_order_id: str | None = None,

    source_reason: str | None = None,

) -> dict[str, Any]:

    number_mode = "voice" if str(number_mode or "").strip().lower() == "voice" else "temp"

    service = str(offer.get("service") or "").strip()

    country = str(offer.get("country") or "none").strip() or "none"

    state = str(offer.get("state") or "none").strip() or "none"

    provider_code = str(offer.get("provider_code") or "").strip().lower()

    info = offer.get("info") if isinstance(offer.get("info"), dict) else {}

    api_service = str(info.get("api_service_name") or "").strip()

    final_price = float(info.get("price") or 0.0)

    cost_price = float(info.get("base_price") or final_price)

    if not service or not provider_code or not api_service or final_price <= 0:

        return {"ok": False, "code": "invalid_offer", "message": _text(lang, "This offer is no longer available.", "هذا العرض لم يعد متاحا.")}

    trust_gate = await _evaluate_temp_trust_gate(

        user_id=int(user_id),

        service_id=service,

        provider_code=provider_code,

    )

    if not bool(trust_gate.get("allowed")):

        return {

            "ok": False,

            "code": "trust_blocked",

            "message": _trust_message(

                lang,

                mode=str(trust_gate.get("mode") or "purchase"),

                wait_sec=int(trust_gate.get("wait_sec") or 0),

            ),

        }

    order = await create_order(

        user_id=user_id,

        reseller_id=reseller_id,

        service_id=service,

        selling_price=final_price,

        base_price=cost_price,

    )

    order_id = order["_id"]

    await update_order_details(

        order_id,

        {

            "number_mode": number_mode,

            "source": "numbers_miniapp",

            "telegram_bot_id": None,

            "provisioning_state": "awaiting_charge",

            "provisioning_provider": provider_code,

            "provisioning_service": api_service,

            "provisioning_country": None if country == "none" else country,

            "provisioning_state_code": None if state == "none" else state,

            "provisioning_created_at": _utc_now(),

            "temp_retry_source_order_id": str(source_order_id or "") or None,

            "temp_retry_reason": str(source_reason or "") or None,

        },

    )

    order.update(

        {

            "number_mode": number_mode,

            "provisioning_provider": provider_code,

            "provisioning_country": None if country == "none" else country,

            "provisioning_state_code": None if state == "none" else state,

        }

    )

    await _log_number_event_from_order(

        order,

        "order_created",

        payload={"source": "numbers_miniapp", "source_order_id": source_order_id, "source_reason": source_reason},

        number_mode=number_mode,

    )

    ok, message = await FinancialManager.process_core_purchase(

        user_id=user_id,

        order_id=order_id,

        sale_price=final_price,

        cost_price=cost_price,

        reseller_id=reseller_id,

    )

    if not ok:

        await update_order_status(order_id, "failed")

        await _log_number_event_from_order(

            order,

            "wallet_charge_failed",

            payload={"message": str(message), "source": "numbers_miniapp"},

            status_after="failed",

            number_mode=number_mode,

        )

        return {"ok": False, "code": str(message), "message": finance_error_public_text(lang, str(message))}

    try:

        await update_order_details(

            order_id,

            {

                "provisioning_state": "charged_pending_provider",

                "provisioning_charged_at": _utc_now(),

            },

        )

        await _log_number_event_from_order(order, "wallet_charged", status_after="paid", number_mode=number_mode)

        provider_country = str(info.get("provider_country") or country or "").strip()

        req_country = None if provider_country == "none" else provider_country

        req_state = None if state == "none" else state

        purchase_options = {

            "reuse_mode": True,

            "_audit_requested_service": service,

            "source": "numbers_miniapp",

        }

        if source_reason:

            purchase_options["retry_reason"] = str(source_reason)

        if number_mode == "voice":

            purchase_options["capability"] = "voice"

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

                payload={"raw": buy_res.get("raw") if isinstance(buy_res, dict) else "provider_no_response", "source": "numbers_miniapp"},

                status_after="refunded" if refund_ok else "failed",

                number_mode=number_mode,

            )

            return {

                "ok": False,

                "code": "provider_failed",

                "message": _text(lang, "Provider could not reserve the number. Your balance was refunded.", "المزود لم يستطع حجز الرقم. تم إرجاع الرصيد."),

            }

        provider_order_id = str(buy_res.get("order_id") or "").strip()

        number = str(buy_res.get("number") or "").strip()

        provider_pool = str(buy_res.get("pool") or "").strip() or None

        interval_sec = _poll_interval_for_provider(provider_code)

        provider_timeout_sec = _extract_provider_wait_timeout_sec(buy_res)

        if provider_timeout_sec:

            provider_timeout_sec = min(TEMP_WAIT_TIMEOUT_SEC, int(provider_timeout_sec))

        now = datetime.now(UTC)

        reuse_warranty_sec = _provider_default_reuse_warranty_sec(provider_code)

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

                "temp_api_service": api_service,

                "temp_country": None if country == "none" else country,

                "temp_state": None if state == "none" else state,

                "temp_service_key": service,

                "temp_reuse_warranty_until": reuse_until,

                "temp_reuse_warranty_sec": reuse_warranty_sec,

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

                "temp_state": None if state == "none" else state,

                "status": "paid",

            },

            "provider_buy_success",

            payload={"provider_pool": provider_pool, "source": "numbers_miniapp"},

            status_after="success",

            number_mode=number_mode,

        )

        await _log_temp_event(

            {

                "_id": order_id,

                "user_id": user_id,

                "provider": provider_code,

                "service_id": service,

                "temp_country": None if country == "none" else country,

                "temp_state": None if state == "none" else state,

                "temp_api_service": api_service,

            },

            "purchase_success",

            {

                "sale_price": final_price,

                "base_price": cost_price,

                "provider_order_id": provider_order_id,

                "provider_pool": provider_pool,

                "source": "numbers_miniapp",

            },

        )

        fresh_order = await get_order(order_id) or order

        return {"ok": True, "order": _order_payload(fresh_order)}

    except Exception:

        logger.exception("numbers miniapp purchase failed after charge for order=%s", order_id)

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

        return {

            "ok": False,

            "code": "provider_failed",

            "message": _text(lang, "Provider could not reserve the number. Your balance was refunded.", "المزود لم يستطع حجز الرقم. تم إرجاع الرصيد."),

        }

async def _purchase_rental_offer(

    *,

    user_id: int,

    reseller_id: int,

    lang: str,

    offer: dict[str, Any],

) -> dict[str, Any]:

    service = str(offer.get("service") or "").strip()

    country = str(offer.get("country") or "none").strip() or "none"

    provider_code = str(offer.get("provider_code") or "").strip().lower()

    provider_info = offer.get("provider_info") if isinstance(offer.get("provider_info"), dict) else {}

    selected = offer.get("option") if isinstance(offer.get("option"), dict) else {}

    api_service = str(selected.get("api_service_name") or provider_info.get("api_service_name") or "").strip()

    try:

        duration = int(selected.get("duration") or 0)

    except Exception:

        duration = 0

    try:

        final_price = float(selected.get("price") or 0.0)

    except Exception:

        final_price = 0.0

    try:

        cost_price = float(selected.get("base_price", final_price) or final_price)

    except Exception:

        cost_price = final_price

    if not service or not provider_code or not api_service or not country or duration <= 0 or final_price <= 0:

        return {"ok": False, "code": "invalid_offer", "message": _text(lang, "This offer is no longer available.", "هذا العرض لم يعد متاحا.")}

    order = await create_order(

        user_id=user_id,

        reseller_id=reseller_id,

        service_id=f"{service}:rental",

        selling_price=final_price,

        base_price=cost_price,

    )

    order_id = order["_id"]

    state_code = str(selected.get("state_code") or "none")

    await update_order_details(

        order_id,

        {

            "number_mode": "rental",

            "source": "numbers_miniapp",

            "telegram_bot_id": None,

            "provisioning_state": "awaiting_charge",

            "provisioning_provider": provider_code,

            "provisioning_service": api_service,

            "provisioning_country": country,

            "provisioning_state_code": state_code,

            "provisioning_duration_hours": int(duration),

            "provisioning_created_at": _utc_now(),

        },

    )

    order.update(

        {

            "number_mode": "rental",

            "provisioning_provider": provider_code,

            "provisioning_country": country,

            "provisioning_state_code": state_code,

        }

    )

    await _log_number_event_from_order(

        order,

        "order_created",

        payload={"duration_hours": int(duration), "source": "numbers_miniapp"},

        number_mode="rental",

    )

    ok, message = await FinancialManager.process_core_purchase(

        user_id=user_id,

        order_id=order_id,

        sale_price=final_price,

        cost_price=cost_price,

        reseller_id=reseller_id,

    )

    if not ok:

        await update_order_status(order_id, "failed")

        await _log_number_event_from_order(

            order,

            "wallet_charge_failed",

            payload={"message": str(message), "source": "numbers_miniapp"},

            status_after="failed",

            number_mode="rental",

        )

        return {"ok": False, "code": str(message), "message": finance_error_public_text(lang, str(message))}

    try:

        await update_order_details(

            order_id,

            {

                "provisioning_state": "charged_pending_provider",

                "provisioning_charged_at": _utc_now(),

            },

        )

        await _log_number_event_from_order(order, "wallet_charged", status_after="paid", number_mode="rental")

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

            api_service_name=api_service,

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

                payload={"raw": rent_res.get("raw") if isinstance(rent_res, dict) else "provider_no_response", "source": "numbers_miniapp"},

                status_after="refunded" if refund_ok else "failed",

                number_mode="rental",

            )

            return {

                "ok": False,

                "code": "provider_failed",

                "message": _text(lang, "Provider could not reserve the rental. Your balance was refunded.", "المزود لم يستطع حجز الإيجار. تم إرجاع الرصيد."),

            }

        provider_order_id = str(rent_res.get("order_id") or "").strip()

        number = str(rent_res.get("number") or "").strip()

        is_renewable = bool(selected.get("tv_is_renewable"))

        billing_cycle_label = str(selected.get("rental_billing_cycle_label") or "")

        if is_renewable and not billing_cycle_label:

            billing_cycle_label = "Auto renew"

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

                "rental_duration_label": _rental_duration_label(selected),

                "rental_country": country,

                "rental_country_name": str(selected.get("country_name") or ""),

                "rental_cost": rent_res.get("price"),

                "rental_end_date": rent_res.get("end_date"),

                "rental_is_renewable": is_renewable,

                "rental_billing_cycle_label": billing_cycle_label if is_renewable else "-",

                "rental_billing_cycle_id": rent_res.get("billing_cycle_id"),

                "rental_state_code": state_code,

                "rental_refund_deadline_at": rental_deadline_at,

                "rental_safe_cutoff_at": rental_safe_cutoff_at,

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

                "rental_state_code": state_code,

                "status": "paid",

            },

            "provider_rent_success",

            payload={"duration_hours": int(duration), "source": "numbers_miniapp"},

            status_after="success",

            number_mode="rental",

        )

        await _log_rental_event(

            order_id=order_id,

            user_id=user_id,

            provider=provider_code,

            service_id=f"{service}:rental",

            event="purchase_success",

            payload={"duration_hours": int(duration), "provider_order_id": provider_order_id, "source": "numbers_miniapp"},

        )

        asyncio.create_task(_miniapp_rental_refund_guard(order_id=order_id, actor_user_id=int(user_id)))

        fresh_order = await get_order(order_id) or order

        return {"ok": True, "order": _order_payload(fresh_order)}

    except Exception:

        logger.exception("numbers miniapp rental purchase failed after charge for order=%s", order_id)

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

        return {

            "ok": False,

            "code": "provider_failed",

            "message": _text(lang, "Provider could not reserve the rental. Your balance was refunded.", "المزود لم يستطع حجز الإيجار. تم إرجاع الرصيد."),

        }

def _normalize_provider_rows(

    data: dict[str, Any],

    mode: str,

    *,

    service: str | None = None,

    country: str | None = None,

    state: str | None = None,

) -> list[dict[str, Any]]:

    rows: list[dict[str, Any]] = []

    recommended_code = _miniapp_recommended_provider_code(data, mode)

    for code, info in sorted((data or {}).items(), key=lambda item: _provider_sort_key(str(item[0]))):

        if not isinstance(info, dict):

            continue

        code = str(code or "").strip().lower()

        if mode == "temp" and code in _HIDDEN_TEMP_PROVIDER_CODES:

            continue

        available = bool(info.get("available_for_buy", True))

        options = []

        if mode == "rental":

            for normalized_option in _miniapp_rental_option_candidates(code, info, state=state):

                option_quote = ""

                if _can_quote_rental_option(

                    mode=mode,

                    service=service,

                    country=country,

                    provider_code=code,

                    provider_info=info,

                    option=normalized_option,

                ):

                    option_quote = _make_quote_token(

                        {

                            "mode": "rental",

                            "service": str(service or ""),

                            "country": str(country or "none"),

                            "state": str(normalized_option.get("state_code") or state or "none"),

                            "provider": code,

                            "option_key": list(_rental_option_match_key(normalized_option)),

                        }

                    )

                if not option_quote:

                    continue

                option_state = str(normalized_option.get("state_code") or "none").strip()

                option_payload = {

                    "duration": str(normalized_option.get("duration") or normalized_option.get("label") or normalized_option.get("hours") or "").strip(),

                    "duration_label": _rental_duration_label(normalized_option),

                    "price": float(normalized_option.get("price") or 0.0),

                    "price_label": _money(normalized_option.get("price")),

                    "quote_token": option_quote,

                    "state_code": option_state if option_state else "none",

                }

                if "tv_is_renewable" in normalized_option:

                    option_payload["renewable"] = bool(normalized_option.get("tv_is_renewable"))

                if "tv_with_state" in normalized_option:

                    option_payload["with_state"] = bool(normalized_option.get("tv_with_state"))

                options.append(option_payload)

        quote_token = ""

        if _can_quote_temp_offer(

            mode=mode,

            service=service,

            country=country,

            state=state,

            provider_code=code,

            info=info,

        ):

            quote_token = _make_quote_token(

                {

                    "mode": "temp",

                    "service": str(service or ""),

                    "country": str(country or "none"),

                    "state": str(state or "none"),

                    "provider": code,

                }

            )

        elif _can_quote_voice_offer(

            mode=mode,

            service=service,

            provider_code=code,

            info=info,

        ):

            quote_token = _make_quote_token(

                {

                    "mode": "voice",

                    "service": str(service or ""),

                    "country": "1",

                    "state": str(state or "none"),

                    "provider": code,

                }

            )

        if mode == "rental":

            options.sort(key=lambda option: float(option.get("price") or 9999))

        if mode == "rental" and not options:

            continue

        if mode in {"temp", "voice"} and (not available or not quote_token):

            continue

        if mode == "rental":

            available = bool(options)

        success_value = info.get("recommended_success_rate") if info.get("recommended_success_rate") is not None else info.get("success_rate", 100)

        success_attempts = _success_attempt_count(info)

        provider_state_code = str(info.get("provider_state_code") or "").strip().upper()

        provider_country_iso = str(info.get("provider_country_iso") or "").strip().upper()

        rows.append(

            {

                "provider": provider_display_name(code),

                "provider_id": provider_public_id(code),

                "location_tag": provider_state_code or provider_country_iso,

                "price": float(options[0]["price"] if mode == "rental" and options else info.get("price") or 0.0),

                "price_label": _money(options[0]["price"] if mode == "rental" and options else info.get("price")),

                "success_rate": _success_rate(success_value, success_attempts),

                "success_attempts": int(success_attempts),

                "available": available,

                "quote_token": quote_token,

                "options": options,

                "recommended": code == recommended_code,

                "voice_fallback": bool(info.get("voice_fallback_service")),

            }

        )

    rows.sort(key=lambda row: (not row.get("recommended"), float(row.get("price") or 9999), str(row.get("provider_id") or "")))

    return rows[:_MAX_PRICE_ROWS]

def _provider_debug_rows(data: dict[str, Any], mode: str) -> list[dict[str, Any]]:

    rows: list[dict[str, Any]] = []

    for code, info in sorted((data or {}).items(), key=lambda item: _provider_sort_key(str(item[0]))):

        provider_code = str(code or "").strip().lower()

        if not isinstance(info, dict):

            rows.append(

                {

                    "provider": provider_code,

                    "provider_id": provider_public_id(provider_code),

                    "visible": False,

                    "reason": "invalid_provider_payload",

                }

            )

            continue

        buyable = _miniapp_provider_buyable(mode, provider_code, info)

        hidden = provider_code in _HIDDEN_TEMP_PROVIDER_CODES

        options = info.get("options") if isinstance(info.get("options"), list) else []

        reason = str(info.get("provider_reason") or info.get("reason") or "").strip()

        if hidden:

            reason = "hidden_provider"

        elif not bool(info.get("available_for_buy", True)):

            reason = reason or "not_available_for_buy"

        elif not buyable:

            reason = reason or "not_buyable"

        rows.append(

            {

                "provider": provider_display_name(provider_code),

                "provider_code": provider_code,

                "provider_id": provider_public_id(provider_code),

                "visible": bool(not hidden and buyable),

                "available_for_buy": bool(info.get("available_for_buy", True)),

                "buyable": bool(buyable),

                "reason": reason or "visible",

                "public_reason": _public_reason(reason),

                "price": _provider_price_float(info),

                "options": len(options),

                "api_service": bool(str(info.get("api_service_name") or "").strip()),

                "voice_capable": bool(info.get("voice_capable", True)),

                "success_attempts": _success_attempt_count(info),

                "success_rate": _success_rate(

                    info.get("recommended_success_rate") if info.get("recommended_success_rate") is not None else info.get("success_rate"),

                    _success_attempt_count(info),

                ),

            }

        )

    return rows

async def index(_request: web.Request) -> web.Response:

    return web.FileResponse(_STATIC / "index.html", headers=dict(_NO_STORE_HEADERS))

async def static_file(request: web.Request) -> web.Response:

    name = str(request.match_info.get("name") or "")

    if "/" in name or "\\" in name or not name:

        raise web.HTTPNotFound()

    path = _STATIC / name

    if not path.exists() or not path.is_file():

        raise web.HTTPNotFound()

    return web.FileResponse(path)

async def bootstrap(request: web.Request) -> web.Response:

    _optional_auth(request)

    return web.json_response(_bootstrap_payload(), headers=dict(_NO_STORE_HEADERS))

async def country_suggestions(request: web.Request) -> web.Response:

    _optional_auth(request)

    mode = str(request.query.get("mode") or "temp").strip().lower()

    service = resolve_canonical_service_key(str(request.query.get("service") or ""))

    if mode not in {"temp", "rental", "voice"}:

        raise web.HTTPBadRequest(text="invalid mode")

    if not service:

        return web.json_response({"ok": True, "mode": mode, "service": "", "countries": []}, headers=dict(_NO_STORE_HEADERS))

    rows = await _country_suggestions_for_service(mode, service)

    return web.json_response(

        {

            "ok": True,

            "mode": mode,

            "service": service,

            "countries": rows,

        },

        headers=dict(_NO_STORE_HEADERS),

    )

async def account(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    return web.json_response(await _account_payload(user_doc, auth), headers=dict(_NO_STORE_HEADERS))

async def account_language(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    try:

        body = await request.json()

    except Exception:

        body = {}

    language = str((body or {}).get("language") or "").strip().lower()

    if language not in {"ar", "en"}:

        return _json_error(_text(lang, "Choose Arabic or English.", "اختر العربية أو الإنكليزية."), status=400, code="invalid_language")

    await update_user_language(int(auth["user_id"]), language)

    updated = await get_user(int(auth["user_id"])) or {**user_doc, "language": language}

    return web.json_response(await _account_payload(updated, auth), headers=dict(_NO_STORE_HEADERS))

async def support_info(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    return web.json_response(

        {

            "ok": True,

            "categories": _support_categories_payload(lang),

            "bot_url": numbers_bot_url("numbers"),

        },

        headers=dict(_NO_STORE_HEADERS),

    )

async def support_ticket(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    try:

        body = await request.json()

    except Exception:

        body = {}

    result = await _submit_support_ticket(

        auth=auth,

        user_doc=user_doc,

        lang=lang,

        category=str((body or {}).get("category") or ""),

        message=str((body or {}).get("message") or ""),

    )

    if not result.get("ok"):

        status = 409 if str(result.get("code")) == "open_ticket_exists" else 400

        if str(result.get("code")) == "support_not_configured":

            status = 503

        return _json_error(str(result.get("message") or ""), status=status, code=str(result.get("code") or "support_failed"))

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))

async def prices(request: web.Request) -> web.Response:

    auth = _optional_auth(request)

    mode = str(request.query.get("mode") or "temp").strip().lower()

    service = resolve_canonical_service_key(str(request.query.get("service") or ""))

    country = str(request.query.get("country") or "none").strip() or "none"

    state = str(request.query.get("state") or "none").strip() or "none"

    if not service:

        return web.json_response(

            {"ok": False, "message": "Choose a service first.", "providers": []},

            headers=dict(_NO_STORE_HEADERS),

        )

    if mode not in {"temp", "rental", "voice"}:

        raise web.HTTPBadRequest(text="invalid mode")

    if mode == "voice":

        country = "1"

        state = state or "none"

    if country != "1":

        state = "none"

    try:

        if mode == "rental":

            raw = await asyncio.wait_for(

                get_all_rental_prices(service, country, with_success_rates=True),

                timeout=_PRICE_TIMEOUT_SEC,

            )

        elif mode == "voice":

            raw = await asyncio.wait_for(

                _get_miniapp_voice_prices(service, country, state, ignore_balance=True),

                timeout=_PRICE_TIMEOUT_SEC,

            )

        else:

            raw = await asyncio.wait_for(

                get_all_prices(
                    service,
                    country,
                    state,
                    ignore_balance=True,
                    with_success_rates=False,
                    provider_codes=_TEMP_PRICE_SCREEN_PROVIDER_CODES,
                ),

                timeout=_PRICE_TIMEOUT_SEC,

            )

    except asyncio.TimeoutError:

        return web.json_response(

            {

                "ok": False,

                "message": "Provider checks took too long. Try a narrower country or service.",

                "providers": [],

            },

            headers=dict(_NO_STORE_HEADERS),

        )

    rows = _normalize_provider_rows(raw, mode, service=service, country=country, state=state)

    payload: dict[str, Any] = {

        "ok": True,

        "mode": mode,

        "service": {"key": service, "label": _service_label(service)},

        "country": country,

        "state": state,

        "providers": rows,

    }

    debug_requested = str(request.query.get("debug") or "").strip().lower() in {"1", "true", "yes"}

    if debug_requested and auth and int(auth.get("user_id") or 0) == int(getattr(settings, "owner_id", 0) or 0):

        payload["debug"] = {

            "hidden_provider_diagnostics": _provider_debug_rows(raw, mode),

        }

    return web.json_response(payload, headers=dict(_NO_STORE_HEADERS))

async def active_orders(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    _ = lang

    temp_orders = await list_user_recent_temp_and_voice_orders(

        int(auth["user_id"]),

        limit=12,

        days=_TEMP_MY_NUMBERS_RETENTION_DAYS,

    )

    rental_orders = await list_user_rental_orders(int(auth["user_id"]), limit=10)

    rows: list[dict[str, Any]] = []

    for order in temp_orders or []:

        try:

            if str(order.get("number_mode") or "").strip().lower() == "voice":

                refreshed = await _refresh_voice_order(order)

            else:

                refreshed = await _refresh_temp_order(order)

        except Exception:

            logger.exception("numbers miniapp order refresh failed: order=%s", order.get("_id"))

            refreshed = order

        rows.append(await _order_payload_with_events(refreshed, lang))

    for order in rental_orders or []:

        if order.get("rental_finished_at"):

            continue

        if str(order.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:

            continue

        try:

            refreshed = await _refresh_rental_order(order)

        except Exception:

            logger.exception("numbers miniapp rental refresh failed: order=%s", order.get("_id"))

            refreshed = order

        rows.append(await _order_payload_with_events(refreshed, lang))

    payload: dict[str, Any] = {"ok": True, "orders": rows}

    try:

        balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

        payload["balance"] = float(balance)

        payload["balance_label"] = _money(balance)

    except Exception:

        pass

    return web.json_response(payload, headers=dict(_NO_STORE_HEADERS))

async def purchase_temp(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    try:

        body = await request.json()

    except Exception:

        body = {}

    token = str((body or {}).get("quote_token") or "").strip()

    if not token:

        return _json_error(_text(lang, "Missing quote.", "العرض غير موجود."), status=400, code="missing_quote")

    try:

        quote_payload = _verify_quote_token(token)

        quote_mode = str(quote_payload.get("mode") or "temp").strip().lower()

        if quote_mode == "rental":

            offer = await _resolve_rental_offer_from_quote(token)

        elif quote_mode == "voice":

            offer = await _resolve_voice_offer_from_quote(token)

        else:

            offer = await _resolve_temp_offer_from_quote(token)

    except asyncio.TimeoutError:

        return _json_error(

            _text(lang, "Provider checks took too long. Try again.", "فحص المزودين أخذ وقت طويل. جرّب مرة ثانية."),

            status=504,

            code="provider_timeout",

        )

    except web.HTTPException as exc:

        return _json_error(

            _text(lang, "This offer is no longer available.", "هذا العرض لم يعد متاحا."),

            status=400,

            code=str(exc.text or "invalid_quote"),

        )

    if quote_mode == "rental":

        result = await _purchase_rental_offer(

            user_id=int(auth["user_id"]),

            reseller_id=int(auth["user_id"]),

            lang=lang,

            offer=offer,

        )

    elif quote_mode == "voice":

        result = await _purchase_temp_offer(

            user_id=int(auth["user_id"]),

            reseller_id=int(auth["user_id"]),

            lang=lang,

            offer=offer,

            number_mode="voice",

        )

    else:

        result = await _purchase_temp_offer(

            user_id=int(auth["user_id"]),

            reseller_id=int(auth["user_id"]),

            lang=lang,

            offer=offer,

        )

    if not result.get("ok"):

        status = 402 if str(result.get("code")) == "INSUFFICIENT_USER_BALANCE" else 409

        return _json_error(str(result.get("message") or ""), status=status, code=str(result.get("code") or "purchase_failed"))

    result = await _attach_order_events(result, lang)

    try:

        balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

        result["balance"] = float(balance)

        result["balance_label"] = _money(balance)

    except Exception:

        pass

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))

async def refresh_order(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    try:

        number_mode = str(order.get("number_mode") or "").strip().lower()

        if number_mode == "rental":

            refreshed = await _refresh_rental_order(order)

        elif number_mode == "voice":

            refreshed = await _refresh_voice_order(order)

        else:

            refreshed = await _refresh_temp_order(order)

    except Exception:

        logger.exception("numbers miniapp manual refresh failed: order=%s", raw_id)

        refreshed = order

    payload: dict[str, Any] = {"ok": True, "order": await _order_payload_with_events(refreshed, lang)}

    try:

        balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

        payload["balance"] = float(balance)

        payload["balance_label"] = _money(balance)

    except Exception:

        pass

    return web.json_response(payload, headers=dict(_NO_STORE_HEADERS))

async def download_recording(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    if str(order.get("number_mode") or "").strip().lower() != "voice":

        return _json_error(_text(lang, "This action is only for call numbers.", "هذا الإجراء خاص بأرقام الاتصال فقط."), status=400, code="invalid_mode")

    refreshed = await _refresh_voice_order(order)

    recording_uri = str((refreshed or {}).get("voice_recording_uri") or "").strip()

    provider = _order_provider_code(refreshed or {})

    if not provider or not recording_uri:

        return _json_error(_text(lang, "No call recording is available yet.", "لا يوجد تسجيل مكالمة حاليا."), status=404, code="recording_not_ready")

    try:

        data = await get_recording_from_provider(provider, recording_uri)

    except Exception:

        logger.exception("numbers miniapp recording download failed: order=%s", raw_id)

        data = {"success": False}

    if not isinstance(data, dict) or not data.get("success") or not data.get("content"):

        return _json_error(_text(lang, "Could not download the recording right now.", "تعذر تحميل التسجيل حاليا."), status=502, code="recording_download_failed")

    content_type = str(data.get("content_type") or "application/octet-stream")

    headers = {

        **_NO_STORE_HEADERS,

        "Content-Disposition": f'attachment; filename="{_voice_recording_filename(content_type)}"',

    }

    return web.Response(body=bytes(data.get("content") or b""), content_type=content_type, headers=headers)

async def request_second_code(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    result = await _request_second_code_for_order(

        order_id=order_id,

        order=order,

        user_id=int(auth["user_id"]),

        reseller_id=int(auth["user_id"]),

        lang=lang,

    )

    if not result.get("ok"):

        status = 402 if str(result.get("code")) == "INSUFFICIENT_USER_BALANCE" else 409

        if str(result.get("code")) in {"order_not_found", "invalid_mode"}:

            status = 404 if str(result.get("code")) == "order_not_found" else 400

        refreshed = await get_order(order_id) or order

        return _json_error(

            str(result.get("message") or ""),

            status=status,

            code=str(result.get("code") or "second_code_failed"),

            order=await _order_payload_with_events(refreshed, lang),

        )

    result = await _attach_order_events(result, lang)

    try:

        balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

        result["balance"] = float(balance)

        result["balance_label"] = _money(balance)

    except Exception:

        pass

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))

async def replace_order(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    result = await _request_replacement_number(

        order_id=order_id,

        order=order,

        user_id=int(auth["user_id"]),

        reseller_id=int(auth["user_id"]),

        lang=lang,

        alternate_provider=False,

    )

    if not result.get("ok"):

        failure_code = str(result.get("code") or "")

        if failure_code in {"provider_unavailable", "provider_failed", "provider_timeout", "invalid_offer"}:

            suggestion = await _enable_alternate_provider_suggestion(order_id=order_id, order=order, lang=lang)

            if suggestion:

                refreshed = await get_order(order_id) or order

                return web.json_response(

                    {

                        "ok": True,

                        "replacement_failed": True,

                        "code": failure_code,

                        "message": _text(

                            lang,

                            "Same provider retry failed. Alternate provider is available.",

                            "فشلت محاولة نفس المزود. ظهر خيار مزود بديل.",

                        ),

                        "order": await _order_payload_with_events(refreshed, lang),

                    },

                    headers=dict(_NO_STORE_HEADERS),

                )

        status = 402 if failure_code == "INSUFFICIENT_USER_BALANCE" else 409

        if failure_code in {"order_not_found", "invalid_mode"}:

            status = 404 if failure_code == "order_not_found" else 400

        refreshed = await get_order(order_id) or order

        return _json_error(

            str(result.get("message") or ""),

            status=status,

            code=failure_code or "replace_failed",

            order=await _order_payload_with_events(refreshed, lang),

        )

    result = await _attach_order_events(result, lang)

    try:

        balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

        result["balance"] = float(balance)

        result["balance_label"] = _money(balance)

    except Exception:

        pass

    result["message"] = _text(lang, "Replacement number requested.", "تم طلب رقم بديل.")

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))

async def alternate_order(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    result = await _request_replacement_number(

        order_id=order_id,

        order=order,

        user_id=int(auth["user_id"]),

        reseller_id=int(auth["user_id"]),

        lang=lang,

        alternate_provider=True,

    )

    if not result.get("ok"):

        status = 402 if str(result.get("code")) == "INSUFFICIENT_USER_BALANCE" else 409

        if str(result.get("code")) in {"order_not_found", "invalid_mode"}:

            status = 404 if str(result.get("code")) == "order_not_found" else 400

        refreshed = await get_order(order_id) or order

        return _json_error(

            str(result.get("message") or ""),

            status=status,

            code=str(result.get("code") or "alternate_failed"),

            order=await _order_payload_with_events(refreshed, lang),

        )

    result = await _attach_order_events(result, lang)

    try:

        balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

        result["balance"] = float(balance)

        result["balance_label"] = _money(balance)

    except Exception:

        pass

    result["message"] = _text(lang, "Alternate provider number requested.", "تم طلب رقم من مزود بديل.")

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))

async def rental_sms_order(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "\u0627\u0644\u0637\u0644\u0628 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "\u0627\u0644\u0637\u0644\u0628 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f."), status=404, code="order_not_found")

    if str(order.get("number_mode") or "").strip().lower() != "rental":

        return _json_error(

            _text(lang, "This action is only for rentals.", "\u0647\u0630\u0627 \u0627\u0644\u0625\u062c\u0631\u0627\u0621 \u062e\u0627\u0635 \u0628\u0627\u0644\u0625\u064a\u062c\u0627\u0631 \u0641\u0642\u0637."),

            status=400,

            code="invalid_mode",

        )

    result = await _sync_rental_sms_snapshot(order_id, order)

    refreshed = await get_order(order_id) or order

    if not result.get("has_sms"):

        code = "no_sms_yet" if result.get("success") else "sms_check_failed"

        message = _text(lang, "No SMS yet.", "\u0644\u0627 \u064a\u0648\u062c\u062f SMS \u0628\u0639\u062f.")

        if not result.get("success"):

            message = _text(lang, "Could not check rental SMS right now.", "\u062a\u0639\u0630\u0631 \u0641\u062d\u0635 \u0631\u0633\u0627\u0626\u0644 SMS \u062d\u0627\u0644\u064a\u0627.")

        return _json_error(message, status=409, code=code, order=await _order_payload_with_events(refreshed, lang))

    return web.json_response(

        {

            "ok": True,

            "message": _text(lang, "Rental SMS loaded.", "\u062a\u0645 \u062a\u062d\u0645\u064a\u0644 \u0631\u0633\u0627\u0626\u0644 SMS."),

            "messages": result.get("messages") or [],

            "order": await _order_payload_with_events(refreshed, lang),

        },

        headers=dict(_NO_STORE_HEADERS),

    )

async def finish_order(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    if str(order.get("number_mode") or "").strip().lower() != "rental":

        return _json_error(_text(lang, "This action is only for rentals.", "هذا الإجراء خاص بالإيجار فقط."), status=400, code="invalid_mode")

    provider = str(order.get("provider") or "").strip().lower()

    provider_order_id = str(order.get("provider_order_id") or "").strip()

    if not provider or not provider_order_id:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    try:

        finish_res = await finish_rental_from_provider(provider, provider_order_id)

        ok = bool(finish_res.get("success"))

    except Exception:

        finish_res = {"success": False}

        ok = False

    if not ok:

        await _log_number_event_from_order(order, "rental_finish_failed", payload={"source": "numbers_miniapp"}, number_mode="rental")

        return _json_error(_text(lang, "Could not finish this rental right now.", "تعذر إنهاء هذا الإيجار حاليا."), status=409, code="finish_failed")

    await update_order_details(order_id, {"rental_finished_at": _utc_now(), "rental_finish_raw": finish_res.get("raw")})

    await _log_number_event_from_order(order, "rental_finished", payload={"source": "numbers_miniapp"}, status_after=str(order.get("status") or "success"), number_mode="rental")

    refreshed = await get_order(order_id) or order

    return web.json_response(

        {

            "ok": True,

            "message": _text(lang, "Rental finished.", "تم إنهاء الإيجار."),

            "order": await _order_payload_with_events(refreshed, lang),

        },

        headers=dict(_NO_STORE_HEADERS),

    )

async def renew_order(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    if str(order.get("number_mode") or "").strip().lower() != "rental":

        return _json_error(_text(lang, "This action is only for rentals.", "هذا الإجراء خاص بالإيجار فقط."), status=400, code="invalid_mode")

    if not bool(order.get("rental_is_renewable")):

        return _json_error(_text(lang, "Renew is not supported for this rental.", "التجديد غير مدعوم لهذا الإيجار."), status=409, code="renew_not_supported")

    provider = str(order.get("provider") or "").strip().lower()

    provider_order_id = str(order.get("provider_order_id") or "").strip()

    if not provider or not provider_order_id:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    try:

        renew_res = await renew_rental_from_provider(provider, provider_order_id)

        ok = bool(renew_res.get("success"))

    except Exception:

        logger.exception("numbers miniapp rental renew failed: order=%s", raw_id)

        renew_res = {"success": False}

        ok = False

    if not ok:

        await _log_number_event_from_order(order, "rental_renew_failed", payload={"source": "numbers_miniapp"}, number_mode="rental")

        refreshed = await get_order(order_id) or order

        return _json_error(_text(lang, "Could not renew this rental right now.", "تعذر تجديد هذا الإيجار حاليا."), status=409, code="renew_failed", order=await _order_payload_with_events(refreshed, lang))

    await update_order_details(order_id, {"rental_last_renew_at": _utc_now(), "rental_last_renew_raw": renew_res.get("raw")})

    await _log_number_event_from_order(order, "rental_renewed", payload={"raw": renew_res.get("raw"), "source": "numbers_miniapp"}, number_mode="rental")

    refreshed = await _refresh_rental_order(await get_order(order_id) or order)

    return web.json_response(

        {

            "ok": True,

            "message": _text(lang, "Rental renewed.", "تم تجديد الإيجار."),

            "order": await _order_payload_with_events(refreshed, lang),

        },

        headers=dict(_NO_STORE_HEADERS),

    )

async def wake_order(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    if str(order.get("number_mode") or "").strip().lower() != "rental":

        return _json_error(_text(lang, "This action is only for rentals.", "هذا الإجراء خاص بالإيجار فقط."), status=400, code="invalid_mode")

    provider = str(order.get("provider") or "").strip().lower()

    provider_order_id = str(order.get("provider_order_id") or "").strip()

    if not provider or not provider_order_id:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    try:

        wake_res = await wake_rental_from_provider(provider, provider_order_id)

        ok = bool(wake_res.get("success"))

    except Exception:

        logger.exception("numbers miniapp rental wake failed: order=%s", raw_id)

        wake_res = {"success": False}

        ok = False

    if not ok:

        await _log_number_event_from_order(order, "rental_wake_failed", payload={"source": "numbers_miniapp"}, number_mode="rental")

        refreshed = await get_order(order_id) or order

        return _json_error(_text(lang, "Could not wake this rental right now.", "تعذر تنشيط هذا الإيجار حاليا."), status=409, code="wake_failed", order=await _order_payload_with_events(refreshed, lang))

    await update_order_details(order_id, {"rental_last_wake_at": _utc_now(), "rental_last_wake_raw": wake_res.get("raw")})

    await _log_number_event_from_order(order, "rental_wake_ok", payload={"raw": wake_res.get("raw"), "source": "numbers_miniapp"}, number_mode="rental")

    refreshed = await _refresh_rental_order(await get_order(order_id) or order)

    return web.json_response(

        {

            "ok": True,

            "message": _text(lang, "Rental wake requested.", "تم طلب تنشيط الإيجار."),

            "order": await _order_payload_with_events(refreshed, lang),

        },

        headers=dict(_NO_STORE_HEADERS),

    )

async def notes_order(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    if str(order.get("number_mode") or "").strip().lower() != "rental":

        return _json_error(_text(lang, "This action is only for rentals.", "هذا الإجراء خاص بالإيجار فقط."), status=400, code="invalid_mode")

    result = await _sync_rental_notes_tags_snapshot(order_id, order)

    refreshed = await get_order(order_id) or order

    if not result.get("success"):

        return _json_error(

            _text(lang, "Notes and tags are not available for this rental.", "الملاحظات والتاغات غير متاحة لهذا الإيجار."),

            status=409,

            code="notes_not_supported",

            order=await _order_payload_with_events(refreshed, lang),

        )

    return web.json_response(

        {

            "ok": True,

            "message": _text(lang, "Notes and tags loaded.", "تم تحميل الملاحظات والتاغات."),

            "notes": str(result.get("notes") or ""),

            "tags": result.get("tags") or [],

            "order": await _order_payload_with_events(refreshed, lang),

        },

        headers=dict(_NO_STORE_HEADERS),

    )

async def cancel_order(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "الطلب غير موجود."), status=404, code="order_not_found")

    if str(order.get("number_mode") or "").strip().lower() == "rental":

        result = await _cancel_and_refund_rental_order(

            order_id=order_id,

            order=order,

            actor_user_id=int(auth["user_id"]),

            reason="miniapp_user_cancel",

            require_no_sms=True,

        )

        refreshed = await get_order(order_id) or order

        if not result.get("success"):

            return _json_error(

                _text(lang, "Could not cancel this rental right now.", "تعذر إلغاء هذا الإيجار حاليا."),

                status=409,

                code=str(result.get("reason") or "cancel_failed"),

                order=await _order_payload_with_events(refreshed, lang),

            )

        return web.json_response(

            {

                "ok": True,

                "message": _text(lang, "Rental cancelled and refunded.", "تم إلغاء الإيجار وإرجاع الرصيد."),

                "order": await _order_payload_with_events(refreshed, lang),

            },

            headers=dict(_NO_STORE_HEADERS),

        )

    if _temp_elapsed_sec(order) < TEMP_CANCEL_AFTER_SEC:

        retry_after = max(1, TEMP_CANCEL_AFTER_SEC - _temp_elapsed_sec(order))

        return _json_error(

            _text(lang, f"You can cancel after {retry_after} seconds.", f"فيني ألغي بعد {retry_after} ثانية."),

            status=409,

            code="cancel_wait",

            retry_after=retry_after,

        )

    result = await _cancel_and_refund_temp_order(

        order_id=order_id,

        order=order,

        actor_user_id=int(auth["user_id"]),

        reason="miniapp_user_cancel",

        require_no_sms=True,

        allow_provider_terminal_refund=_temp_elapsed_sec(order) >= _order_temp_timeout_sec(order),

        allow_empty_provider_refund=_temp_elapsed_sec(order) >= _order_temp_timeout_sec(order),

    )

    if not result.get("success"):

        refreshed = await get_order(order_id) or order

        if _temp_refund_result_retryable(result):

            refreshed = await _mark_temp_refund_pending(

                order_id=order_id,

                order=refreshed,

                result=result,

                source="numbers_miniapp_user_cancel",

            )

            return web.json_response(

                {

                    "ok": True,

                    "message": _text(

                        lang,

                        "Refund is pending. We will keep retrying.",

                        "الاسترجاع قيد المعالجة. رح نضل نعيد المحاولة.",

                    ),

                    "order": await _order_payload_with_events(refreshed, lang),

                },

                headers=dict(_NO_STORE_HEADERS),

            )

        return _json_error(

            _text(lang, "Could not cancel this order right now.", "تعذر إلغاء الطلب حاليا."),

            status=409,

            code=str(result.get("reason") or "cancel_failed"),

            order=await _order_payload_with_events(refreshed, lang),

        )

    refreshed = await get_order(order_id) or order

    balance_payload: dict[str, Any] = {}

    try:

        balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

        balance_payload["balance"] = float(balance)

        balance_payload["balance_label"] = _money(balance)

    except Exception:

        pass

    return web.json_response(

        {

            "ok": True,

            "message": _text(lang, "Order cancelled and refunded.", "تم إلغاء الطلب وإرجاع الرصيد."),

            "order": await _order_payload_with_events(refreshed, lang),

            **balance_payload,

        },

        headers=dict(_NO_STORE_HEADERS),

    )

def register_numbers_routes(app: web.Application) -> None:

    app.router.add_get("/mini/numbers", index)

    app.router.add_get("/mini/numbers/static/{name}", static_file)

    app.router.add_get("/mini/numbers/api/bootstrap", bootstrap)

    app.router.add_get("/mini/numbers/api/country-suggestions", country_suggestions)

    app.router.add_get("/mini/numbers/api/account", account)

    app.router.add_post("/mini/numbers/api/account/language", account_language)

    app.router.add_get("/mini/numbers/api/support", support_info)

    app.router.add_post("/mini/numbers/api/support/ticket", support_ticket)

    app.router.add_get("/mini/numbers/api/prices", prices)

    app.router.add_get("/mini/numbers/api/orders", active_orders)

    app.router.add_post("/mini/numbers/api/purchase", purchase_temp)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/refresh", refresh_order)

    app.router.add_get("/mini/numbers/api/orders/{order_id}/recording", download_recording)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/second-code", request_second_code)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/replace", replace_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/alternate", alternate_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/sms", rental_sms_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/finish", finish_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/renew", renew_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/wake", wake_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/notes", notes_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/cancel", cancel_order)
