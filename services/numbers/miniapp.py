from __future__ import annotations

import asyncio


import hashlib

import hmac

import json

import logging

import re

from datetime import UTC, datetime, timedelta

from pathlib import Path

from typing import Any

from urllib.parse import parse_qsl

from aiohttp import web

from bson import ObjectId

from config import settings

from database import number_events_repo, temp_number_stats_repo

from database.financial_ledger import get_user_wallet_balance, list_user_wallet_entries
from database.mongo import db
from database.orders_repo import (

    create_order,

    extract_order_amounts,

    get_order,

    list_user_open_temp_and_voice_orders,

    list_user_number_orders_for_miniapp,

    update_order_details,

    update_order_status,

)

from database.user_repo import create_user, get_user, update_user_language

from services.numbers.data.countries import COUNTRIES_LIST

from services.numbers.data.states_us import STATES_LIST

from services.numbers.api_payloads import (
    QuoteTokenError as ApiQuoteTokenError,
    normalize_rental_quote_rows as _api_normalize_rental_quote_rows,
    normalize_temp_quote_rows as _api_normalize_temp_quote_rows,
    normalize_voice_quote_rows as _api_normalize_voice_quote_rows,
    verify_quote_token as _api_verify_quote_token,
)
from services.numbers.country_suggestions_service import (
    _CHEAP_COUNTRY_CACHE,
    country_suggestions_for_service as _shared_country_suggestions_for_service,
)
from services.numbers.customer_flows import (
    MAX_RECHARGE_PROOF_BYTES,
    SUPPORT_CATEGORIES as _SHARED_SUPPORT_CATEGORIES,
    currency_label as _shared_currency_label,
    numbers_source_bot_id as _shared_numbers_source_bot_id,
    recent_recharge_requests_payload as _shared_recent_recharge_requests_payload,
    recharge_methods_payload as _shared_recharge_methods_payload,
    recharge_per_credit as _shared_recharge_per_credit,
    recharge_request_payload as _shared_recharge_request_payload,
    recharge_status_label as _shared_recharge_status_label,
    render_recharge_instructions as _shared_render_recharge_instructions,
    submit_recharge_request as _shared_submit_recharge_request,
    submit_support_ticket as _shared_submit_support_ticket,
    support_bridge_token as _shared_support_bridge_token,
    support_categories_payload as _shared_support_categories_payload,
    support_category_label as _shared_support_category_label,
)

from services.numbers.order_refresh_service import refresh_number_order as _api_refresh_number_order
from services.numbers.order_recording_service import (
    download_voice_order_recording as _api_download_voice_order_recording,
    voice_recording_uri_from_calls as _api_voice_recording_uri_from_calls,
)
from services.numbers.order_resend_service import request_number_order_resend as _api_request_number_order_resend
from services.numbers.order_service import (
    NumbersOrderError as ApiNumbersOrderError,
    create_number_order_from_quote as _api_create_number_order_from_quote,
    enable_alternate_provider_suggestion as _api_enable_alternate_provider_suggestion,
    public_order_payload as _api_public_order_payload,
    request_replacement_order as _api_request_replacement_order,
)
from services.numbers.order_rental_service import (
    finish_rental_order as _api_finish_rental_order,
    rental_notes_state as _api_rental_notes_state,
    rental_sms_state as _api_rental_sms_state,
    renew_rental_order as _api_renew_rental_order,
    wake_rental_order as _api_wake_rental_order,
)
from services.numbers import order_rental_protection_service as rental_protection_service

from services.numbers.provider_delivery import provider_sms_polling_enabled

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

    _format_wait_time_short,

    _is_retryable_provider_cancel,

    _is_temp_order_active_for_trust_gate,

    _order_reuse_warranty_sec,

    _order_temp_timeout_sec,

    _safe_code_text,

    _seconds_between,

    _seconds_left_until,

    _temp_elapsed_sec,

    _temp_order_has_received_code,

    _utc_now,

)

from services.numbers.shared.rental_policy import _rental_no_sms_yet, _rental_protection_policy

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
from services.numbers.manager import (

    PROVIDERS,

    TEMP_NOT_LISTED_SERVICE_KEY,

    finish_rental_from_provider,

    get_all_prices,

    get_all_rental_prices,

    get_all_voice_prices,

    get_rental_sms_from_provider,

    is_temp_not_listed_service,

    temp_not_listed_provider_codes,

)

from services.numbers.service_map import (

    get_service_aliases,

    get_service_display_name,

    list_service_keys,

    resolve_canonical_service_key,

)

from utils.core_service_guard import finance_error_public_text

from utils.financial_manager import FinancialManager

from utils.bot_menu_context import numbers_bot_url

from utils.provider_alias import provider_code_from_public_id, provider_display_name, provider_public_id

from utils.services_keyboard import DEFAULT_TOP_SERVICES, load_top_services

logger = logging.getLogger("numbers_miniapp")

_ROOT = Path(__file__).resolve().parents[2]

_STATIC = _ROOT / "webapp" / "numbers"

_STATIC_V2 = _ROOT / "webapp" / "numbers_v2"

_NO_STORE_HEADERS = {

    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",

    "Pragma": "no-cache",

    "Expires": "0",

}

_BOOTSTRAP_CACHE: dict[str, Any] = {"data": None}

_PRICE_TIMEOUT_SEC = 34.0
_PRICE_SOFT_TIMEOUT_SEC = 6.0
_TEMP_PRICE_SCREEN_PROVIDER_CODES = (
    "smspool",
    "telabot",
    "textverified",
    "herosms",
    "pvadeals",
    "vaksms",
    "nonvoip",
    "smsready",
    "pvapins",
)

_TEMP_NOT_LISTED_PRICE_PROVIDER_CODES = temp_not_listed_provider_codes()

_MAX_PRICE_ROWS = 16

_HIDDEN_TEMP_PROVIDER_CODES = {"nonvoip_s6"}


_SUPPORT_CATEGORIES = _SHARED_SUPPORT_CATEGORIES

_TEMP_MY_NUMBERS_RETENTION_DAYS = 5

_VOICE_GENERIC_SERVICE = "servicenotlistedvoice"

_TEXTVERIFIED_RENTAL_STATE_SURCHARGE = 2.0

_MINIAPP_SURFACE_TABS = (
    ("buy", "tabBuy", "buy", False),
    ("orders", "tabOrders", "orders", True),
    ("recharge", "tabRecharge", "recharge", True),
    ("account", "tabAccount", "account", True),
    ("support", "tabSupport", "support", True),
)


def _miniapp_surface_tabs() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "label_key": label_key,
            "icon": icon,
            "enabled": True,
            "requires_auth": requires_auth,
        }
        for key, label_key, icon, requires_auth in _MINIAPP_SURFACE_TABS
    ]


def _miniapp_surface_action(
    key: str,
    endpoint: str,
    *,
    method: str = "GET",
    enabled: bool = True,
    requires_auth: bool = True,
    label_key: str = "",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "enabled": bool(enabled),
        "label_key": label_key or key,
        "endpoint": endpoint,
        "method": method.upper(),
        "requires_auth": bool(requires_auth),
        "reason": reason if enabled else (reason or "disabled"),
    }


def _miniapp_surface_actions() -> dict[str, dict[str, Any]]:
    return {
        "bootstrap": _miniapp_surface_action(
            "bootstrap",
            "/mini/numbers/api/bootstrap",
            requires_auth=False,
            label_key="loading",
        ),
        "account": _miniapp_surface_action(
            "account",
            "/mini/numbers/api/account",
            label_key="account",
        ),
        "change_language": _miniapp_surface_action(
            "change_language",
            "/mini/numbers/api/account/language",
            method="POST",
            label_key="language",
        ),
        "account_activity_export": _miniapp_surface_action(
            "account_activity_export",
            "/mini/numbers/api/account/activity.csv",
            label_key="downloadActivity",
        ),
        "account_activity": _miniapp_surface_action(
            "account_activity",
            "/mini/numbers/api/account/activity",
            label_key="walletActivity",
        ),
        "orders": _miniapp_surface_action(
            "orders",
            "/mini/numbers/api/orders",
            label_key="tabOrders",
        ),
        "prices": _miniapp_surface_action(
            "prices",
            "/mini/numbers/api/prices",
            requires_auth=False,
            label_key="check",
        ),
        "country_suggestions": _miniapp_surface_action(
            "country_suggestions",
            "/mini/numbers/api/country-suggestions",
            requires_auth=False,
            label_key="country",
        ),
        "purchase": _miniapp_surface_action(
            "purchase",
            "/mini/numbers/api/purchase",
            method="POST",
            label_key="buy",
        ),
        "recharge": _miniapp_surface_action(
            "recharge",
            "/mini/numbers/api/recharge",
            label_key="recharge",
        ),
        "submit_recharge": _miniapp_surface_action(
            "submit_recharge",
            "/mini/numbers/api/recharge/submit",
            method="POST",
            label_key="submitRecharge",
        ),
        "support": _miniapp_surface_action(
            "support",
            "/mini/numbers/api/support",
            label_key="support",
        ),
        "submit_support_ticket": _miniapp_surface_action(
            "submit_support_ticket",
            "/mini/numbers/api/support/ticket",
            method="POST",
            label_key="sendSupport",
        ),
    }


def _miniapp_surface_payload() -> dict[str, Any]:
    return {
        "primary_surface": "miniapp",
        "telegram_order_flow_enabled": bool(getattr(settings, "numbers_telegram_order_flow_enabled", False)),
        "provider_sms_polling_enabled": provider_sms_polling_enabled(),
        "manual_customer_refund_enabled": False,
        "tabs": _miniapp_surface_tabs(),
        "actions": _miniapp_surface_actions(),
        "features": {
            "buy": True,
            "orders": True,
            "recharge": True,
            "account": True,
            "support": True,
            "telegram_reply_keyboard_order_flow": False,
            "server_managed_refunds": True,
            "webhook_first_delivery": not provider_sms_polling_enabled(),
        },
    }

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

async def _json_body(request: web.Request) -> dict[str, Any]:

    try:

        body = await request.json()

    except Exception:

        body = {}

    return body if isinstance(body, dict) else {}

def _miniapp_idempotency_key(

    request: web.Request,

    body: dict[str, Any],

    *,

    action: str,

    user_id: int,

    order_id: Any,

) -> str:

    supplied = str(request.headers.get("Idempotency-Key") or body.get("idempotency_key") or "").strip()

    if supplied:

        return supplied

    return f"miniapp:{action}:{int(user_id)}:{str(order_id)}"

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

def _auth_profile(auth: dict[str, Any], user_doc: dict[str, Any] | None = None) -> dict[str, str]:

    tg_user = auth.get("user") if isinstance(auth.get("user"), dict) else {}

    username = str((user_doc or {}).get("username") or tg_user.get("username") or "").strip()

    first_name = str(tg_user.get("first_name") or "").strip()

    last_name = str(tg_user.get("last_name") or "").strip()

    full_name = " ".join(part for part in (first_name, last_name) if part).strip()

    if not full_name:

        full_name = str((user_doc or {}).get("full_name") or "").strip()

    return {"username": username, "full_name": full_name}

def _ledger_reason_label(reason: Any, category: Any, lang: str, order: dict[str, Any] | None = None) -> str:

    reason_text = str(reason or "").strip().lower()

    category_text = str(category or "").strip().lower()

    retry_reason = str((order or {}).get("temp_retry_reason") or "").strip().lower()

    if category_text == "core_purchase" or reason_text.startswith("purchase_core_"):

        if retry_reason == "replace_request":

            return _text(lang, "Replacement purchase", "شراء رقم بديل")

        if retry_reason == "alternate_provider_request":

            return _text(lang, "Alternate provider purchase", "شراء من مزود بديل")

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

def _ledger_subject_text_is_identifier(value: str) -> bool:

    text = str(value or "").strip()

    compact = text.replace("-", "").replace("_", "")

    return bool(len(compact) >= 16 and all(ch in "0123456789abcdefABCDEF" for ch in compact))

def _ledger_activity_subject_from_entry(entry: dict[str, Any], lang: str) -> str:

    reason = str(entry.get("reason") or "").strip().lower()
    category = str(entry.get("category") or "").strip().lower()
    if category == "recharge_credit" or reason == "recharge_request_accepted":
        return _text(lang, "Recharge request", "طلب شحن")

    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}

    bot_username = str(metadata.get("bot_username") or metadata.get("bot") or metadata.get("source_bot") or "").strip()

    if bot_username:

        clean = bot_username if bot_username.startswith("@") else f"@{bot_username}"

        return clean[:80]

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

        if text and not _ledger_subject_text_is_identifier(text):

            return text[:80]

    service_key = str(metadata.get("service") or metadata.get("service_id") or metadata.get("service_ref_id") or "").strip()

    if service_key:

        return _service_label(service_key.replace(":rental", "").replace(":second_code", ""))

    source = str(metadata.get("source") or metadata.get("service_type") or metadata.get("flow") or "").strip()

    if source:

        return source.replace("_", " ").title()[:80]

    order_id = str(entry.get("order_id") or "").strip()

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

        order = (orders or {}).get(order_id)

        label = _ledger_reason_label(entry.get("reason"), entry.get("category"), lang, order)

        subject = _order_activity_subject(order) or _ledger_activity_subject_from_entry(entry, lang)

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

def _currency_label(amount: Any, currency: Any) -> str:
    return _shared_currency_label(amount, currency)

async def _recharge_per_credit(method: dict[str, Any]) -> float:
    return await _shared_recharge_per_credit(method)

def _render_recharge_instructions(method: dict[str, Any], *, rate: float) -> str:
    return _shared_render_recharge_instructions(method, rate=rate)

async def _recharge_method_payload(method: dict[str, Any], lang: str) -> dict[str, Any]:

    currency = str(method.get("currency") or "USD").strip().upper() or "USD"

    rate = await _recharge_per_credit(method)

    rate_label = _text(

        lang,

        f"1 credit = {_currency_label(rate, currency)}",

        f"1 كريدت = {_currency_label(rate, currency)}",

    )

    return {

        "code": str(method.get("code") or method.get("title") or "").strip(),

        "title": str(method.get("title") or method.get("code") or "").strip(),

        "currency": currency,

        "target": str(method.get("target") or "").strip(),

        "support": str(method.get("support") or "@support").strip(),

        "per_credit": float(rate),

        "rate_label": rate_label,

        "instructions": _render_recharge_instructions(method, rate=rate),

    }

async def _recharge_methods_payload(lang: str) -> list[dict[str, Any]]:
    return await _shared_recharge_methods_payload(lang, text_fn=_text)

def _recharge_status_label(status: Any, lang: str) -> str:

    key = str(status or "pending").strip().lower()

    labels = {

        "pending": ("Pending review", "بانتظار المراجعة"),

        "processing": ("Processing", "قيد المعالجة"),

        "need_more_proof": ("Needs another proof", "\u064a\u062d\u062a\u0627\u062c \u0625\u062b\u0628\u0627\u062a \u0625\u0636\u0627\u0641\u064a"),

        "accepted": ("Accepted", "تم القبول"),

        "rejected": ("Rejected", "مرفوض"),

    }

    en, ar = labels.get(key, (key.replace("_", " ").title(), key.replace("_", " ")))

    return _text(lang, en, ar)

def _recharge_request_payload(req: dict[str, Any], lang: str) -> dict[str, Any]:
    return _shared_recharge_request_payload(
        req,
        lang,
        money_fn=_money,
        compact_datetime_fn=_compact_datetime,
        text_fn=_text,
    )

async def _recent_recharge_requests_payload(user_id: int, lang: str, *, limit: int = 6) -> list[dict[str, Any]]:
    return await _shared_recent_recharge_requests_payload(
        user_id,
        lang,
        limit=limit,
        money_fn=_money,
        compact_datetime_fn=_compact_datetime,
        text_fn=_text,
    )

async def _recharge_payload(user_id: int, lang: str) -> dict[str, Any]:

    methods: list[dict[str, Any]]

    try:

        methods = await _recharge_methods_payload(lang)

    except Exception:

        logger.exception("numbers miniapp recharge methods failed user=%s", user_id)

        methods = []

    try:

        requests = await _recent_recharge_requests_payload(user_id, lang)

    except Exception:

        logger.exception("numbers miniapp recharge requests failed user=%s", user_id)

        requests = []

    return {

        "methods": methods,

        "requests": requests,

        "bot_url": numbers_bot_url("balance"),

        "max_proof_bytes": 6 * 1024 * 1024,

    }

async def _account_payload(user_doc: dict[str, Any], auth: dict[str, Any]) -> dict[str, Any]:

    user_id = int(auth["user_id"])

    lang = _lang_from_user(user_doc, auth)

    profile = _auth_profile(auth, user_doc)

    balance = await get_user_wallet_balance(user_id, user_id)

    language = str(user_doc.get("language") or lang or "en").strip().lower()

    try:

        entries = await list_user_wallet_entries(user_id, user_id, limit=4)

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

        "recharge": await _recharge_payload(user_id, lang),

        "support_categories": _support_categories_payload(lang),
        "actions": {
            key: value
            for key, value in _miniapp_surface_actions().items()
            if key in {"change_language", "account_activity", "account_activity_export", "recharge", "support", "orders"}
        },

    }

def _quote_provider_code(quote: dict[str, Any], *, allowed_codes: Any = None) -> str:
    provider_code = str((quote or {}).get("provider") or "").strip().lower()
    if provider_code:
        return provider_code
    return provider_code_from_public_id(
        (quote or {}).get("provider_id"),
        allowed_codes=allowed_codes or PROVIDERS.keys(),
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

            "You already have an active number order. Wait for its code or timeout refund result.",

            "\u0639\u0646\u062f\u0643 \u0637\u0644\u0628 \u0631\u0642\u0645 \u0634\u063a\u0627\u0644 \u062d\u0627\u0644\u064a\u0627. \u0627\u0646\u062a\u0638\u0631 \u0627\u0644\u0643\u0648\u062f \u0623\u0648 \u0646\u062a\u064a\u062c\u0629 \u0627\u0644\u0627\u0633\u062a\u0631\u062c\u0627\u0639 \u0628\u0639\u062f \u0627\u0646\u062a\u0647\u0627\u0621 \u0627\u0644\u0645\u0647\u0644\u0629.",

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

    direct = str(fallback or "").strip()

    if direct:

        upper_direct = direct.upper()

        for item in COUNTRIES_LIST:

            if str(item.get("iso") or "").strip().upper() == upper_direct:

                return str(item.get("name") or direct)

        return direct

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

def _country_name_from_number(number: Any) -> str:

    digits = "".join(ch for ch in str(number or "") if ch.isdigit())

    if digits.startswith("30"):

        return "Greece"

    return ""

def _detail_row(key: str, value: Any) -> dict[str, str] | None:

    text = str(value or "").strip()

    if not text or text == "-":

        return None

    labels = {
        "provider": "Provider",
        "created": "Created",
        "country": "Country",
        "state": "State",
        "duration": "Duration",
        "ends": "Ends",
        "calls": "Calls",
        "retry": "Retry",
        "reuseUntil": "Reuse until",
        "secondCodes": "Second codes",
    }

    return {"key": key, "label": labels.get(key, key), "value": text}

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

        country = _country_name(
            order.get("temp_country") or order.get("provisioning_country"),
            fallback=order.get("temp_country_name") or order.get("temp_country_iso"),
        )

        if not (order.get("temp_country_name") or order.get("temp_country_iso")):

            country = _country_name_from_number(order.get("provider_number")) or country

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

                _detail_row("secondCodes", second_codes if second_codes > 0 else ""),

                _detail_row("retry", order.get("temp_refund_retry_attempts") if public_status == "refund_pending" else ""),

            )

    for item in extras:

        if item:

            rows.append(item)

    return rows[:7]

def _temp_active_estimate(order: dict[str, Any]) -> dict[str, Any]:

    provider = _order_provider_code(order)

    service = str(order.get("temp_service_key") or order.get("service_id") or "").strip().lower()

    long_pool_service = provider == "smspool" and any(marker in service for marker in ("forex", "fx", "forx"))

    window_sec = 4 * 24 * 3600 if long_pool_service else 20 * 60

    starts_at = (

        _coerce_utc_datetime(order.get("created_at"))

        or _coerce_utc_datetime(order.get("temp_wait_started_at"))

        or _utc_now()

    )

    until = starts_at + timedelta(seconds=window_sec)

    seconds_left = _seconds_left_until(until)

    return {

        "active_estimate_until": until.isoformat(),

        "active_seconds_left": int(seconds_left),

        "active_estimate_label": _format_wait_time_short(seconds_left),

        "active_estimate_unreliable": bool(long_pool_service),

    }

def _event_public_label(event: str, lang: str) -> str:

    key = str(event or "").strip().lower()

    labels = {

        "order_created": ("Order received", "تم استلام الطلب"),

        "wallet_charged": ("", ""),

        "provider_buy_started": ("", ""),

        "provider_buy_success": ("", ""),

        "purchase_success": ("Number secured", "تم تأمين الرقم"),

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

        "voice_call_seen": ("Call detected, waiting for recording", "تم رصد المكالمة، بانتظار التسجيل"),

        "voice_call_received": ("Call received", "وصلت المكالمة"),

        "manual_voice_check_no_call": ("No call yet", "لا توجد مكالمة بعد"),

        "second_code_attempted": ("Second code requested", "تم طلب كود ثاني"),

        "second_code_requested": ("Second code activated", "تم تفعيل الكود الثاني"),

        "rental_finished": ("Rental finished", "تم إنهاء الإيجار"),

        "rental_renewed": ("Rental renewed", "تم تجديد الإيجار"),

        "rental_wake_ok": ("Rental wake requested", "تم طلب تنشيط الإيجار"),

    }

    if key not in labels:
        return ""

    en, ar = labels[key]

    return _text(lang, en, ar)

def _event_payload(event: dict[str, Any], lang: str) -> dict[str, str] | None:

    label = _event_public_label(str(event.get("event") or ""), lang)
    if not label:
        return None

    return {

        "event": str(event.get("event") or ""),

        "label": label,

        "time": _compact_datetime(event.get("created_at")),

    }

async def _recent_order_events_payload(order_id: Any, lang: str, *, limit: int = 5) -> list[dict[str, str]]:

    try:

        rows = await number_events_repo.list_number_order_events_for_order(order_id, limit=max(20, int(limit or 5) * 4))

    except Exception:

        logger.exception("numbers miniapp order events load failed: order=%s", order_id)

        return []

    payloads = [_event_payload(row, lang) for row in rows]
    return [item for item in payloads if item][-max(1, int(limit or 5)):]

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

async def _miniapp_order_result(payload: dict[str, Any], lang: str) -> dict[str, Any]:

    order_payload = payload.get("order") if isinstance(payload, dict) else None

    order_id = str((order_payload or {}).get("id") or "").strip() if isinstance(order_payload, dict) else ""

    if order_id:

        try:

            fresh_order = await get_order(order_id)

        except Exception:

            fresh_order = None

        if isinstance(fresh_order, dict):

            payload["order"] = await _order_payload_with_events(fresh_order, lang)

            return payload

    return await _attach_order_events(payload, lang)

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

async def _country_suggestions_for_service(mode: str, service: str, limit: int = 10) -> list[dict[str, Any]]:
    return await _shared_country_suggestions_for_service(
        mode,
        service,
        limit,
        get_temp_prices_fn=get_all_prices,
        get_rental_prices_fn=get_all_rental_prices,
    )

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
        "client": _miniapp_surface_payload(),

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

def _temp_my_numbers_expires_at(order: dict[str, Any]) -> datetime | None:

    created_at = _coerce_utc_datetime((order or {}).get("created_at"))

    if not created_at:

        return None

    return created_at + timedelta(days=_TEMP_MY_NUMBERS_RETENTION_DAYS)

def _temp_my_numbers_active(order: dict[str, Any]) -> bool:

    if str((order or {}).get("number_mode") or "temp").strip().lower() != "temp":

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

def _second_code_price(order: dict[str, Any]) -> tuple[float, float]:

    sale_price, cost_price = extract_order_amounts(order)

    return round(max(0.0, float(sale_price)) / 2.0, 4), round(max(0.0, float(cost_price)) / 2.0, 4)


def _miniapp_order_action(
    *,
    enabled: bool,
    label_key: str,
    endpoint: str = "",
    method: str = "POST",
    reason: str = "",
    confirm_label_key: str = "",
    busy_label_key: str = "working",
    success_label_key: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:

    return {

        "enabled": bool(enabled),

        "label_key": str(label_key or ""),

        "endpoint": str(endpoint or ""),

        "method": str(method or "POST").upper(),

        "reason": str(reason or ""),

        "confirm_label_key": str(confirm_label_key or ""),

        "busy_label_key": str(busy_label_key or ""),

        "success_label_key": str(success_label_key or ""),

        "idempotency_key": str(idempotency_key or ""),

    }


def _miniapp_order_actions(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:

    order_id = str((payload or {}).get("id") or "").strip()

    base = f"/mini/numbers/api/orders/{order_id}" if order_id else ""

    mode = str((payload or {}).get("mode") or "temp").strip().lower() or "temp"

    refresh_label = "checkCall" if mode == "voice" else "refresh"
    test_active_endpoint = f"{base}/wake" if mode == "rental" else f"{base}/test-active"
    has_temp_code = bool(payload.get("code") or payload.get("codes"))
    if mode == "rental":
        test_active_enabled = bool(payload.get("can_wake"))
        test_active_method = "POST"
    elif mode == "temp":
        test_active_enabled = bool(has_temp_code)
        test_active_method = "CLIENT"
        test_active_endpoint = ""
    else:
        test_active_enabled = bool(payload.get("can_refresh", False))
        test_active_method = "POST"

    actions: dict[str, dict[str, Any]] = {

        "copy_number": _miniapp_order_action(enabled=bool(payload.get("number")), label_key="copyNumber", endpoint="", method="CLIENT"),

        "copy_code": _miniapp_order_action(enabled=bool(payload.get("code")), label_key="copyCode", endpoint="", method="CLIENT"),

        "refresh": _miniapp_order_action(enabled=bool(payload.get("can_refresh", False)), label_key=refresh_label, endpoint=f"{base}/refresh" if base else "", busy_label_key="checkingOrder"),

        "test_active": _miniapp_order_action(enabled=test_active_enabled, label_key="testActive", endpoint=test_active_endpoint if base else "", method=test_active_method, busy_label_key="checkingOrder", idempotency_key=f"miniapp-test-active-{order_id}" if order_id and test_active_method != "CLIENT" else ""),

        "second_code": _miniapp_order_action(enabled=bool(payload.get("can_second_code") or payload.get("can_resend")), label_key="secondCode", endpoint=f"{base}/second-code" if base else "", confirm_label_key="confirmSecondCode", success_label_key="secondCodeRequested"),

        "replace": _miniapp_order_action(enabled=bool(payload.get("can_replace")), label_key="tryAnother", endpoint=f"{base}/replace" if base else "", confirm_label_key="confirmTryAnother", success_label_key="replacementRequested", idempotency_key=f"miniapp-replace-{order_id}" if order_id else ""),

        "alternate_provider": _miniapp_order_action(enabled=bool(payload.get("can_alternate_provider")), label_key="alternateProvider", endpoint=f"{base}/alternate" if base else "", confirm_label_key="confirmAlternateProvider", success_label_key="replacementRequested", idempotency_key=f"miniapp-alternate-{order_id}" if order_id else ""),

        "cancel": _miniapp_order_action(enabled=bool(payload.get("can_cancel")), label_key="cancelOrder", endpoint=f"{base}/cancel" if base else "", confirm_label_key="confirmCancelOrder", busy_label_key="cancellingOrder", success_label_key="orderCancelled", idempotency_key=f"miniapp-cancel-{order_id}" if order_id else ""),

        "preview_recording": _miniapp_order_action(enabled=bool(mode == "voice" and payload.get("recording_url")), label_key="playRecording", endpoint=str(payload.get("recording_url") or ""), method="GET"),

        "download_recording": _miniapp_order_action(enabled=bool(mode == "voice" and payload.get("recording_url")), label_key="downloadRecording", endpoint=str(payload.get("recording_url") or ""), method="GET"),

        "rental_sms": _miniapp_order_action(enabled=bool(mode == "rental" and payload.get("can_sms")), label_key="rentalSms", endpoint=f"{base}/sms" if base else "", idempotency_key=f"miniapp-rental-sms-{order_id}" if order_id else ""),

        "rental_renew": _miniapp_order_action(enabled=bool(mode == "rental" and payload.get("can_renew")), label_key="renew", endpoint=f"{base}/renew" if base else "", confirm_label_key="renew", idempotency_key=f"miniapp-rental-renew-{order_id}" if order_id else ""),

        "rental_wake": _miniapp_order_action(enabled=bool(mode == "rental" and payload.get("can_wake")), label_key="wake", endpoint=f"{base}/wake" if base else "", idempotency_key=f"miniapp-rental-wake-{order_id}" if order_id else ""),

        "rental_notes": _miniapp_order_action(enabled=bool(mode == "rental" and payload.get("can_notes")), label_key="notesTags", endpoint=f"{base}/notes" if base else "", idempotency_key=f"miniapp-rental-notes-{order_id}" if order_id else ""),

        "rental_finish": _miniapp_order_action(enabled=bool(mode == "rental" and payload.get("can_finish")), label_key="finish", endpoint=f"{base}/finish" if base else "", confirm_label_key="finish"),

        "report_issue": {
            **_miniapp_order_action(enabled=bool(order_id), label_key="reportIssue", endpoint="", method="CLIENT"),
        },

    }

    if not base:

        for action in actions.values():

            if action["method"] != "CLIENT":

                action["enabled"] = False

                action["reason"] = "missing_order_id"

    return actions


def _order_payload(order: dict[str, Any]) -> dict[str, Any]:

    payload = dict(_api_public_order_payload(order))

    mode = str(payload.get("mode") or (order or {}).get("number_mode") or "temp").strip().lower() or "temp"

    public_status = str(payload.get("public_status") or "waiting")

    service_key = str(payload.get("service") or "")

    sale_price, _cost_price = extract_order_amounts(order)

    payload["service_label"] = _service_label(service_key)

    payload["price"] = float(sale_price)

    payload["price_label"] = _money(sale_price)

    payload["details"] = _order_detail_rows(order, mode=mode, public_status=public_status)

    payload["can_cancel"] = bool(payload.get("can_cancel"))

    payload["cancel_wait_sec"] = 0

    if mode == "rental":

        if (order or {}).get("rental_finished_at") and str((order or {}).get("status") or "").strip().lower() not in {"cancelled", "failed", "refunded", "expired"}:

            payload["public_status"] = "finished"

            public_status = "finished"

        payload["sms_count"] = len(payload.get("messages") or [])

        payload["can_refresh"] = public_status in {"waiting", "code_received"}

        payload["can_sms"] = public_status in {"waiting", "code_received"}

        payload["can_cancel"] = False

        payload["cancel_wait_sec"] = 0

        payload["actions"] = _miniapp_order_actions(payload)

        return payload

    if mode == "voice":

        order_id = str((order or {}).get("_id") or payload.get("id") or "")

        if payload.get("recording_available") and order_id:

            payload["recording_url"] = f"/mini/numbers/api/orders/{order_id}/recording"

        payload["can_refresh"] = public_status in {"waiting", "waiting_for_recording", "refund_pending"}

        payload["can_cancel"] = False

        payload["cancel_wait_sec"] = 0

        payload["actions"] = _miniapp_order_actions(payload)

        return payload

    if public_status != "code_received":

        payload["code"] = ""
    else:

        payload.update(_temp_active_estimate(order))

    second_sale, _second_cost = _second_code_price(order)

    can_second_code = bool(public_status == "code_received" and payload.get("can_resend") and second_sale > 0)

    payload["can_second_code"] = can_second_code

    payload["can_resend"] = can_second_code

    payload["second_code_price"] = float(second_sale)

    payload["second_code_price_label"] = _money(second_sale)

    payload["can_refresh"] = public_status in {"waiting", "code_received", "refund_pending"}

    payload["can_cancel"] = bool(public_status == "waiting" and not payload.get("code") and payload.get("number") and payload.get("can_cancel"))

    payload["cancel_wait_sec"] = 0

    payload["actions"] = _miniapp_order_actions(payload)

    return payload

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

    try:

        await _api_refresh_number_order(current)

    except ApiNumbersOrderError:

        return current

    return await get_order(current["_id"]) or current

def _voice_recording_uri_from_calls(calls: Any) -> str:

    return _api_voice_recording_uri_from_calls(calls)

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

async def _sync_rental_sms_snapshot(order_id: Any, order: dict[str, Any]) -> dict[str, Any]:
    return await rental_protection_service.sync_rental_sms_snapshot(
        order_id,
        order,
        provider_sms_polling_enabled_fn=provider_sms_polling_enabled,
        get_rental_sms_from_provider_fn=get_rental_sms_from_provider,
        update_order_details_fn=update_order_details,
        log_rental_event_fn=_log_rental_event,
        utc_now_fn=_utc_now,
        sms_detected_event="code_received",
        event_source="numbers_miniapp",
        logger_obj=logger,
    )

async def _refresh_rental_order(order: dict[str, Any]) -> dict[str, Any]:
    return await rental_protection_service.refresh_rental_order(
        order,
        get_order_fn=get_order,
        sync_rental_sms_snapshot_fn=_sync_rental_sms_snapshot,
    )

async def _provider_close_rental(order: dict[str, Any]) -> dict[str, Any]:
    return await rental_protection_service.provider_close_rental(
        order,
        providers=PROVIDERS,
        finish_rental_from_provider_fn=finish_rental_from_provider,
        policy_fn=_rental_protection_policy,
        sleep_fn=asyncio.sleep,
    )

async def _cancel_and_refund_rental_order(

    *,

    order_id: Any,

    order: dict[str, Any],

    actor_user_id: int,

    reason: str,

    require_no_sms: bool = False,

) -> dict[str, Any]:
    return await rental_protection_service.cancel_and_refund_rental_order(
        order_id=order_id,
        order=order,
        actor_user_id=actor_user_id,
        reason=reason,
        require_no_sms=require_no_sms,
        sync_rental_sms_snapshot_fn=_sync_rental_sms_snapshot,
        provider_close_rental_fn=_provider_close_rental,
        update_order_details_fn=update_order_details,
        update_order_status_fn=update_order_status,
        log_number_event_from_order_fn=_log_number_event_from_order,
        log_rental_event_fn=_log_rental_event,
        financial_manager_cls=FinancialManager,
        extract_order_amounts_fn=extract_order_amounts,
        utc_now_fn=_utc_now,
        event_source="numbers_miniapp",
    )

async def _miniapp_rental_refund_guard(*, order_id: Any, actor_user_id: int) -> None:
    await rental_protection_service.rental_refund_guard(
        order_id=order_id,
        actor_user_id=actor_user_id,
        get_order_fn=get_order,
        sync_rental_sms_snapshot_fn=_sync_rental_sms_snapshot,
        cancel_and_refund_rental_order_fn=_cancel_and_refund_rental_order,
        log_number_event_from_order_fn=_log_number_event_from_order,
        log_rental_event_fn=_log_rental_event,
        policy_fn=_rental_protection_policy,
        no_sms_yet_fn=_rental_no_sms_yet,
        utc_now_fn=_utc_now,
        sleep_fn=asyncio.sleep,
        deadline_event_source="numbers_miniapp_rental_guard",
        auto_event_source="numbers_miniapp_rental_guard",
        cancel_reason_suffix="miniapp_guard_no_sms_timeout",
    )

def _normalize_provider_rows(

    data: dict[str, Any],

    mode: str,

    *,

    service: str | None = None,

    country: str | None = None,

    state: str | None = None,

) -> list[dict[str, Any]]:

    if mode == "temp":

        return _attach_miniapp_purchase_actions(_api_normalize_temp_quote_rows(

            data,

            service=str(service or ""),

            country=str(country or "none"),

            state=str(state or "none"),

        ))

    if mode == "rental":

        return _attach_miniapp_purchase_actions(_api_normalize_rental_quote_rows(

            data,

            service=str(service or ""),

            country=str(country or "none"),

            state=str(state or "none"),

        ))

    if mode == "voice":

        return _attach_miniapp_purchase_actions(_api_normalize_voice_quote_rows(

            data,

            service=str(service or ""),

            country=str(country or "1"),

            state=str(state or "none"),

        ))

    return []


def _miniapp_purchase_action(quote_token: Any) -> dict[str, Any]:

    token = str(quote_token or "").strip()

    return {

        "enabled": bool(token),

        "label_key": "buy",

        "endpoint": "/mini/numbers/api/purchase",

        "method": "POST",

        "body": {"quote_token": token} if token else {},

        "reason": "" if token else "missing_quote_token",

    }


def _attach_miniapp_purchase_actions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:

    patched_rows: list[dict[str, Any]] = []

    for row in rows or []:

        if not isinstance(row, dict):

            continue

        patched = dict(row)

        if patched.get("quote_token"):

            patched["purchase_action"] = _miniapp_purchase_action(patched.get("quote_token"))

        if isinstance(patched.get("options"), list):

            options: list[dict[str, Any]] = []

            for option in patched.get("options") or []:

                if not isinstance(option, dict):

                    continue

                option_payload = dict(option)

                option_payload["purchase_action"] = _miniapp_purchase_action(option_payload.get("quote_token"))

                options.append(option_payload)

            patched["options"] = options

        patched_rows.append(patched)

    return patched_rows

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

async def index_v2(_request: web.Request) -> web.Response:

    return web.FileResponse(_STATIC_V2 / "index.html", headers=dict(_NO_STORE_HEADERS))

async def static_file(request: web.Request) -> web.Response:

    name = str(request.match_info.get("name") or "")

    if "/" in name or "\\" in name or not name:

        raise web.HTTPNotFound()

    path = _STATIC / name

    if not path.exists() or not path.is_file():

        raise web.HTTPNotFound()

    return web.FileResponse(path, headers=dict(_NO_STORE_HEADERS))

async def static_file_v2(request: web.Request) -> web.Response:

    name = str(request.match_info.get("name") or "")

    if "/" in name or "\\" in name or not name:

        raise web.HTTPNotFound()

    path = _STATIC_V2 / name

    if not path.exists() or not path.is_file():

        raise web.HTTPNotFound()

    return web.FileResponse(path, headers=dict(_NO_STORE_HEADERS))

async def bootstrap(request: web.Request) -> web.Response:

    auth = _optional_auth(request)
    payload = dict(_bootstrap_payload())
    user_doc = None
    if auth and int(auth.get("user_id") or 0) > 0:
        try:
            user_doc = await get_user(int(auth["user_id"]))
        except Exception:
            logger.exception("numbers miniapp bootstrap user lookup failed user=%s", auth.get("user_id"))
    lang = _lang_from_user(user_doc, auth)
    payload["language"] = lang
    payload["direction"] = "rtl" if lang == "ar" else "ltr"

    return web.json_response(payload, headers=dict(_NO_STORE_HEADERS))

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

async def account_activity(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    try:

        entries = await list_user_wallet_entries(int(auth["user_id"]), int(auth["user_id"]), limit=500)

        rows = _ledger_activity_payload(entries, lang, await _ledger_activity_orders(entries))

    except Exception:

        logger.exception("numbers miniapp account activity failed user=%s", auth.get("user_id"))

        rows = []

    return web.json_response({"ok": True, "activity": rows}, headers=dict(_NO_STORE_HEADERS))

async def account_activity_csv(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    try:

        entries = await list_user_wallet_entries(int(auth["user_id"]), int(auth["user_id"]), limit=500)

        rows = _ledger_activity_payload(entries, lang, await _ledger_activity_orders(entries))

    except Exception:

        logger.exception("numbers miniapp account activity export failed user=%s", auth.get("user_id"))

        rows = []

    lines = ["date,label,amount,balance,direction,order_id"]

    for row in rows:

        values = [
            row.get("created_at") or "",
            row.get("label") or "",
            row.get("amount_label") or "",
            row.get("balance_label") or "",
            row.get("direction") or "",
            row.get("order_id") or "",
        ]

        escaped = [f'"{str(value).replace(chr(34), chr(34) + chr(34))}"' for value in values]

        lines.append(",".join(escaped))

    return web.Response(
        text="\n".join(lines) + "\n",
        content_type="text/csv",
        headers={
            **_NO_STORE_HEADERS,
            "Content-Disposition": 'attachment; filename="phantom-numbers-wallet-activity.csv"',
        },
    )

async def recharge_info(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

    return web.json_response(

        {

            "ok": True,

            "balance": float(balance),

            "balance_label": _money(balance),

            "recharge": await _recharge_payload(int(auth["user_id"]), lang),
            "actions": {
                key: value
                for key, value in _miniapp_surface_actions().items()
                if key in {"submit_recharge", "recharge", "account"}
            },

        },

        headers=dict(_NO_STORE_HEADERS),

    )

async def recharge_submit(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    try:

        fields, proof_bytes, proof_filename, proof_content_type = await _parse_recharge_submit_form(request)

    except web.HTTPRequestEntityTooLarge:

        return _json_error(

            _text(lang, "Proof file is too large.", "ملف إثبات الدفع كبير جداً."),

            status=413,

            code="proof_too_large",

        )

    except Exception:

        return _json_error(

            _text(lang, "Could not read the recharge form.", "تعذر قراءة نموذج الشحن."),

            status=400,

            code="invalid_form",

        )

    result = await _shared_submit_recharge_request(

        auth=auth,

        user_doc=user_doc,

        lang=lang,

        fields=fields,

        proof_bytes=proof_bytes,

        proof_filename=proof_filename,

        proof_content_type=proof_content_type,

        source="numbers_miniapp",

        source_label="Numbers Mini App",

        text_fn=_text,

        money_fn=_money,

        compact_datetime_fn=_compact_datetime,

    )

    if not result.get("ok"):

        return _json_error(

            str(result.get("message") or _text(lang, "Recharge request failed.", "تعذر إرسال طلب الشحن.")),

            status=400,

            code=str(result.get("code") or "recharge_failed"),

        )

    balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

    result["balance"] = float(balance)

    result["balance_label"] = _money(balance)

    result["recharge"] = await _recharge_payload(int(auth["user_id"]), lang)
    result["actions"] = {
        key: value
        for key, value in _miniapp_surface_actions().items()
        if key in {"submit_recharge", "recharge", "account"}
    }

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))

async def support_info(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    return web.json_response(

        {

            "ok": True,

            "categories": _support_categories_payload(lang),

            "bot_url": numbers_bot_url("numbers"),
            "actions": {
                key: value
                for key, value in _miniapp_surface_actions().items()
                if key in {"submit_support_ticket", "support", "orders"}
            },

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

    result = await _shared_submit_support_ticket(

        auth=auth,

        user_doc=user_doc,

        lang=lang,

        category=str((body or {}).get("category") or ""),

        message=str((body or {}).get("message") or ""),

        source_label="Numbers Mini App",

        text_fn=_text,

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

    temp_provider_codes = (
        _TEMP_NOT_LISTED_PRICE_PROVIDER_CODES
        if is_temp_not_listed_service(service)
        else _TEMP_PRICE_SCREEN_PROVIDER_CODES
    )

    if mode == "rental":

        raw = await get_all_rental_prices(service, country, with_success_rates=True, ignore_balance=True)

    elif mode == "voice":

        raw = await _get_miniapp_voice_prices(service, country, state, ignore_balance=True)

    else:

        raw = await get_all_prices(
            service,
            country,
            state,
            ignore_balance=True,
            with_success_rates=False,
            provider_codes=temp_provider_codes,
            soft_timeout_sec=None,
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

    number_orders = await list_user_number_orders_for_miniapp(int(auth["user_id"]), limit=120)

    rows: list[dict[str, Any]] = []

    for order in number_orders or []:
        if _is_second_code_charge_order(order):
            continue

        try:

            mode = str(order.get("number_mode") or "").strip().lower()

            status = str(order.get("status") or "").strip().lower()

            wait_state = str(order.get("temp_wait_state") or "").strip().lower()

            can_refresh_temp = (
                mode == "temp"
                and status in {"success", "pending", "paid"}
                and wait_state == "waiting"
                and _temp_my_numbers_active(order)
                and int(_temp_elapsed_sec(order)) <= 30 * 60
            )

            if mode != "temp" or not can_refresh_temp:

                refreshed = order

            else:

                refreshed = await _refresh_temp_order(order)

        except Exception:

            logger.exception("numbers miniapp order refresh failed: order=%s", order.get("_id"))

            refreshed = order

        rows.append(await _order_payload_with_events(refreshed, lang))

    payload: dict[str, Any] = {"ok": True, "orders": rows, "orders_limit": 120, "orders_count": len(rows)}

    try:

        balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

        payload["balance"] = float(balance)

        payload["balance_label"] = _money(balance)

    except Exception:

        pass

    return web.json_response(payload, headers=dict(_NO_STORE_HEADERS))


def _is_second_code_charge_order(order: dict[str, Any] | None) -> bool:
    order = order or {}
    mode = str(order.get("number_mode") or "").strip().lower()
    service_id = str(order.get("service_id") or order.get("service_ref_id") or "").strip().lower()
    return bool(
        mode == "second_code_charge"
        or service_id.endswith(":second_code")
        or str(order.get("temp_second_code_source_order_id") or "").strip()
    )

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
        quote_payload = _api_verify_quote_token(token)
        quote_mode = str(quote_payload.get("mode") or "temp").strip().lower()
        if quote_mode not in {"temp", "rental", "voice"}:
            raise web.HTTPBadRequest(text="invalid_quote_mode")

    except web.HTTPException as exc:

        return _json_error(

            _text(lang, "This offer is no longer available.", "هذا العرض لم يعد متاحا."),

            status=400,

            code=str(exc.text or "invalid_quote"),

        )
    except ApiQuoteTokenError:
        return _json_error(
            _text(lang, "This offer is no longer available.", "\u0647\u0630\u0627 \u0627\u0644\u0639\u0631\u0636 \u0644\u0645 \u064a\u0639\u062f \u0645\u062a\u0627\u062d\u0627."),
            status=400,
            code="invalid_quote",
        )

    if quote_mode == "temp":

        trust_gate = await _evaluate_temp_trust_gate(

            user_id=int(auth["user_id"]),

            service_id=str(quote_payload.get("service") or ""),

            provider_code=_quote_provider_code(quote_payload, allowed_codes=_TEMP_PRICE_SCREEN_PROVIDER_CODES),

        )

        if not bool(trust_gate.get("allowed")):

            result = {

                "ok": False,

                "code": "trust_blocked",

                "message": _trust_message(

                    lang,

                    mode=str(trust_gate.get("mode") or "purchase"),

                    wait_sec=int(trust_gate.get("wait_sec") or 0),

                ),

            }

        else:

            result = None

    else:

        result = None

    if result is None:

        try:

            api_result = await _api_create_number_order_from_quote(

                user_id=int(auth["user_id"]),

                reseller_id=int(auth["user_id"]),

                quote_token=token,

                idempotency_key=str(request.headers.get("Idempotency-Key") or (body or {}).get("idempotency_key") or ""),

                lang=lang,

            )

            result = await _miniapp_order_result(dict(api_result or {"ok": True}), lang)

        except ApiNumbersOrderError as exc:

            result = {"ok": False, "code": exc.code, "message": exc.message}

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

    api_result: dict[str, Any] = {}

    try:

        api_result = await _api_refresh_number_order(order)
        refreshed = await get_order(order_id) or order

    except ApiNumbersOrderError as exc:

        refreshed = await get_order(order_id) or order
        return _json_error(exc.message, status=exc.status, code=exc.code, order=await _order_payload_with_events(refreshed, lang))

    except Exception:

        logger.exception("numbers miniapp manual refresh failed: order=%s", raw_id)

        refreshed = order

    payload: dict[str, Any] = {
        "ok": True,
        "order": await _order_payload_with_events(refreshed, lang),
        "message": str((api_result or {}).get("message") or ""),
    }

    try:

        balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

        payload["balance"] = float(balance)

        payload["balance_label"] = _money(balance)

    except Exception:

        pass

    return web.json_response(payload, headers=dict(_NO_STORE_HEADERS))

async def test_active_order(request: web.Request) -> web.Response:

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

    api_result: dict[str, Any] = {}

    try:

        api_result = await _api_refresh_number_order(order, allow_auto_refund=False)
        refreshed = await get_order(order_id) or order

    except ApiNumbersOrderError as exc:

        refreshed = await get_order(order_id) or order
        return _json_error(exc.message, status=exc.status, code=exc.code, order=await _order_payload_with_events(refreshed, lang))

    except Exception:

        logger.exception("numbers miniapp test-active failed: order=%s", raw_id)

        refreshed = order

    payload: dict[str, Any] = {
        "ok": True,
        "order": await _order_payload_with_events(refreshed, lang),
        "message": str((api_result or {}).get("message") or ""),
    }

    try:

        balance = await get_user_wallet_balance(int(auth["user_id"]), int(auth["user_id"]))

        payload["balance"] = float(balance)

        payload["balance_label"] = _money(balance)

    except Exception:

        pass

    return web.json_response(payload, headers=dict(_NO_STORE_HEADERS))


async def cancel_order(request: web.Request) -> web.Response:

    auth = _require_auth(request)

    user_doc = await _load_or_create_user(auth)

    lang = _lang_from_user(user_doc, auth)

    raw_id = str(request.match_info.get("order_id") or "").strip()

    try:

        order_id = ObjectId(raw_id)

    except Exception:

        return _json_error(_text(lang, "Order not found.", "Ø§Ù„Ø·Ù„Ø¨ ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "Ø§Ù„Ø·Ù„Ø¨ ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯."), status=404, code="order_not_found")

    status = str(order.get("status") or "").strip().lower()

    wait_state = str(order.get("temp_wait_state") or "").strip().lower()

    if status in {"cancelled", "refunded"} or wait_state in {"refunded", "auto_refunded"} or order.get("temp_refunded_at"):

        return web.json_response(

            {

                "ok": True,

                "order": await _order_payload_with_events(order, lang),

                "message": _text(lang, "Order is already refunded.", "Ø§Ù„Ø·Ù„Ø¨ Ù…Ø³ØªØ±Ø¬Ø¹ Ù…Ø³Ø¨Ù‚Ø§."),

            },

            headers=dict(_NO_STORE_HEADERS),

        )

    result = await _cancel_and_refund_temp_order(

        order_id=order_id,

        order=order,

        actor_user_id=int(auth["user_id"]),

        reason="miniapp_user_cancel",

        require_no_sms=True,

        allow_provider_terminal_refund=True,

        allow_empty_provider_refund=True,

    )

    refreshed = await get_order(order_id) or order

    if not result.get("success"):

        status = 503 if _temp_refund_result_retryable(result) else 409

        return _json_error(

            _text(lang, "Could not cancel this order right now. Please try again.", "ØªØ¹Ø°Ø± Ø¥Ù„ØºØ§Ø¡ Ø§Ù„Ø·Ù„Ø¨ Ø­Ø§Ù„ÙŠØ§. Ø­Ø§ÙˆÙ„ Ù…Ø±Ø© Ø£Ø®Ø±Ù‰."),

            status=status,

            code=str(result.get("reason") or "cancel_failed"),

            order=await _order_payload_with_events(refreshed, lang),

        )

    payload: dict[str, Any] = {

        "ok": True,

        "order": await _order_payload_with_events(refreshed, lang),

        "message": _text(lang, "Order cancelled and your balance was refunded.", "ØªÙ… Ø¥Ù„ØºØ§Ø¡ Ø§Ù„Ø·Ù„Ø¨ ÙˆØ¥Ø±Ø¬Ø§Ø¹ Ø§Ù„Ø±ØµÙŠØ¯."),

    }

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

        return _json_error(_text(lang, "Order not found.", "????? ??? ?????."), status=404, code="order_not_found")

    order = await get_order(order_id)

    if not order or int(order.get("user_id") or 0) != int(auth["user_id"]):

        return _json_error(_text(lang, "Order not found.", "????? ??? ?????."), status=404, code="order_not_found")

    refreshed = await get_order(order_id) or order

    try:

        data = await _api_download_voice_order_recording(refreshed)

    except ApiNumbersOrderError as exc:

        messages = {

            "invalid_mode": _text(lang, "This action is only for call numbers.", "??? ??????? ??? ?????? ??????? ???."),

            "recording_not_ready": _text(lang, "No call recording is available yet.", "?? ???? ????? ?????? ?????."),

            "recording_download_failed": _text(lang, "Could not download the recording right now.", "???? ????? ??????? ?????."),

        }

        return _json_error(messages.get(exc.code, exc.message), status=exc.status, code=exc.code)

    headers = {

        **_NO_STORE_HEADERS,

        "Content-Disposition": f'attachment; filename="{data["filename"]}"',

    }

    return web.Response(body=data["content"], content_type=data["content_type"], headers=headers)

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

    try:

        api_result = await _api_request_number_order_resend(

            order,

            user_id=int(auth["user_id"]),

            reseller_id=int(auth["user_id"]),

        )

    except ApiNumbersOrderError as exc:

        refreshed = await get_order(order_id) or order

        return _json_error(

            exc.message,

            status=exc.status,

            code=exc.code or "second_code_failed",

            order=await _order_payload_with_events(refreshed, lang),

        )

    refreshed = await get_order(order_id) or order

    result = {

        "ok": True,

        "message": _text(lang, "Resend requested. Waiting for the next code.", "تم طلب إعادة الإرسال. بانتظار الكود الجديد."),

        "order": await _order_payload_with_events(refreshed, lang),

        "second_order_id": str(api_result.get("second_order_id") or ""),

    }

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

    body = await _json_body(request)

    try:

        result = await _api_request_replacement_order(

            order=order,

            user_id=int(auth["user_id"]),

            reseller_id=int(auth["user_id"]),

            idempotency_key=_miniapp_idempotency_key(

                request,

                body,

                action="replace",

                user_id=int(auth["user_id"]),

                order_id=order_id,

            ),

            lang=lang,

            alternate_provider=False,

        )

    except ApiNumbersOrderError as exc:

        failure_code = str(exc.code or "")

        if failure_code in {"provider_unavailable", "provider_failed", "provider_timeout", "invalid_offer", "offer_unavailable"}:

            suggestion = await _api_enable_alternate_provider_suggestion(order_id=str(order_id), order=order, lang=lang)

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

        refreshed = await get_order(order_id) or order

        return _json_error(

            exc.message,

            status=int(getattr(exc, "status", 409) or 409),

            code=failure_code or "replace_failed",

            order=await _order_payload_with_events(refreshed, lang),

        )

    result = await _miniapp_order_result(result, lang)

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

    body = await _json_body(request)

    try:

        result = await _api_request_replacement_order(

            order=order,

            user_id=int(auth["user_id"]),

            reseller_id=int(auth["user_id"]),

            idempotency_key=_miniapp_idempotency_key(

                request,

                body,

                action="alternate",

                user_id=int(auth["user_id"]),

                order_id=order_id,

            ),

            lang=lang,

            alternate_provider=True,

        )

    except ApiNumbersOrderError as exc:

        refreshed = await get_order(order_id) or order

        return _json_error(

            exc.message,

            status=int(getattr(exc, "status", 409) or 409),

            code=str(exc.code or "alternate_failed"),

            order=await _order_payload_with_events(refreshed, lang),

        )

    result = await _miniapp_order_result(result, lang)

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

    try:

        result = await _api_rental_sms_state(order, source="numbers_miniapp")

    except ApiNumbersOrderError as exc:

        refreshed = await get_order(order_id) or order

        return _json_error(exc.message, status=exc.status, code=exc.code, order=await _order_payload_with_events(refreshed, lang))

    result = await _miniapp_order_result(dict(result), lang)

    result["message"] = (

        _text(lang, "Rental SMS loaded.", "\u062a\u0645 \u062a\u062d\u0645\u064a\u0644 \u0631\u0633\u0627\u0626\u0644 SMS.")

        if result.get("messages")

        else _text(lang, "Waiting for provider webhook.", "\u0628\u0627\u0646\u062a\u0638\u0627\u0631 \u0648\u064a\u0628 \u0647\u0648\u0643 \u0627\u0644\u0645\u0632\u0648\u062f.")

    )

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))

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

    try:

        result = await _api_finish_rental_order(order, source="numbers_miniapp")

    except ApiNumbersOrderError as exc:

        refreshed = await get_order(order_id) or order

        return _json_error(exc.message, status=exc.status, code=exc.code, order=await _order_payload_with_events(refreshed, lang))

    result = await _miniapp_order_result(dict(result), lang)

    result["message"] = _text(lang, "Rental finished.", "\u062a\u0645 \u0625\u0646\u0647\u0627\u0621 \u0627\u0644\u0625\u064a\u062c\u0627\u0631.")

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))


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

    body = await _json_body(request)

    try:

        result = await _api_renew_rental_order(

            order=order,

            user_id=int(auth["user_id"]),

            idempotency_key=_miniapp_idempotency_key(

                request,

                body,

                action="renew",

                user_id=int(auth["user_id"]),

                order_id=order_id,

            ),
            source="numbers_miniapp",

        )

    except ApiNumbersOrderError as exc:

        refreshed = await get_order(order_id) or order

        return _json_error(exc.message, status=exc.status, code=exc.code, order=await _order_payload_with_events(refreshed, lang))

    result = await _miniapp_order_result(dict(result), lang)

    result["message"] = _text(lang, "Rental renewed.", "\u062a\u0645 \u062a\u062c\u062f\u064a\u062f \u0627\u0644\u0625\u064a\u062c\u0627\u0631.")

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))


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

    try:

        result = await _api_wake_rental_order(order, source="numbers_miniapp")

    except ApiNumbersOrderError as exc:

        refreshed = await get_order(order_id) or order

        return _json_error(exc.message, status=exc.status, code=exc.code, order=await _order_payload_with_events(refreshed, lang))

    result = await _miniapp_order_result(dict(result), lang)

    result["message"] = _text(lang, "Rental wake requested.", "\u062a\u0645 \u0637\u0644\u0628 \u062a\u0646\u0634\u064a\u0637 \u0627\u0644\u0625\u064a\u062c\u0627\u0631.")

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))


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

    try:

        result = await _api_rental_notes_state(order, source="numbers_miniapp")

    except ApiNumbersOrderError as exc:

        refreshed = await get_order(order_id) or order

        return _json_error(exc.message, status=exc.status, code=exc.code, order=await _order_payload_with_events(refreshed, lang))

    result = await _miniapp_order_result(dict(result), lang)

    result["message"] = _text(lang, "Notes and tags loaded.", "\u062a\u0645 \u062a\u062d\u0645\u064a\u0644 \u0627\u0644\u0645\u0644\u0627\u062d\u0638\u0627\u062a \u0648\u0627\u0644\u062a\u0627\u063a\u0627\u062a.")

    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))


def register_numbers_routes(app: web.Application) -> None:

    app.router.add_get("/mini/numbers", index)

    app.router.add_get("/mini/numbers/static/{name}", static_file)

    app.router.add_get("/mini/numbers-v2", index_v2)

    app.router.add_get("/mini/numbers-v2/static/{name}", static_file_v2)

    app.router.add_get("/mini/numbers/api/bootstrap", bootstrap)

    app.router.add_get("/mini/numbers/api/country-suggestions", country_suggestions)

    app.router.add_get("/mini/numbers/api/account", account)

    app.router.add_post("/mini/numbers/api/account/language", account_language)

    app.router.add_get("/mini/numbers/api/account/activity", account_activity)

    app.router.add_get("/mini/numbers/api/account/activity.csv", account_activity_csv)

    app.router.add_get("/mini/numbers/api/recharge", recharge_info)

    app.router.add_post("/mini/numbers/api/recharge/submit", recharge_submit)

    app.router.add_get("/mini/numbers/api/support", support_info)

    app.router.add_post("/mini/numbers/api/support/ticket", support_ticket)

    app.router.add_get("/mini/numbers/api/prices", prices)

    app.router.add_get("/mini/numbers/api/orders", active_orders)

    app.router.add_post("/mini/numbers/api/purchase", purchase_temp)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/refresh", refresh_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/test-active", test_active_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/cancel", cancel_order)

    app.router.add_get("/mini/numbers/api/orders/{order_id}/recording", download_recording)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/second-code", request_second_code)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/replace", replace_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/alternate", alternate_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/sms", rental_sms_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/finish", finish_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/renew", renew_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/wake", wake_order)

    app.router.add_post("/mini/numbers/api/orders/{order_id}/notes", notes_order)
