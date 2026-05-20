from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import web
from bson import ObjectId

from config import settings
from database import number_events_repo, temp_number_stats_repo
from database.financial_ledger import get_user_wallet_balance
from database.orders_repo import (
    create_order,
    extract_order_amounts,
    get_order,
    list_user_open_temp_orders,
    update_order_details,
    update_order_status,
)
from database.user_repo import create_user, get_user
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.data.states_us import STATES_LIST
from services.numbers.handlers.event_logging import (
    _log_number_event_from_order as _log_number_event_from_order_impl,
    _log_temp_event as _log_temp_event_impl,
)
from services.numbers.handlers.temp_order_utils import (
    TEMP_CANCEL_AFTER_SEC,
    TEMP_WAIT_TIMEOUT_SEC,
    _extract_new_sms_code,
    _extract_provider_wait_timeout_sec,
    _format_wait_time_short,
    _is_retryable_provider_cancel,
    _is_temp_order_active_for_trust_gate,
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
from services.numbers.handlers.temp_provider_io import fetch_provider_sms
from services.numbers.manager import PROVIDERS, buy_number_from_provider, get_all_prices, get_all_rental_prices, get_all_voice_prices
from services.numbers.service_map import (
    get_service_aliases,
    get_service_display_name,
    list_service_keys,
    resolve_canonical_service_key,
)
from utils.core_service_guard import finance_error_public_text
from utils.financial_manager import FinancialManager
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
_BOOTSTRAP_CACHE: dict[str, Any] = {"data": None}
_PRICE_TIMEOUT_SEC = 18.0
_MAX_PRICE_ROWS = 16
_QUOTE_TTL_SEC = 300
_HIDDEN_TEMP_PROVIDER_CODES = {"smsman", "smsman_s6"}
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

    open_orders = await list_user_open_temp_orders(int(user_id), limit=5)
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


def _country_rows() -> list[dict[str, str]]:
    rows = [{"code": "none", "iso": "", "name": "Any country"}]
    for item in COUNTRIES_LIST:
        code = str(item.get("code") or "").strip()
        iso = str(item.get("iso") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        if code and name and "_V" not in iso:
            rows.append({"code": code, "iso": iso, "name": name})
    return rows


def _state_rows() -> list[dict[str, str]]:
    rows = [{"code": "none", "name": "No state"}]
    for item in STATES_LIST:
        code = str(item.get("code") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        if code and name:
            rows.append({"code": code, "name": name})
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
        "defaults": {"mode": "temp", "service": "telegram", "country": "1", "state": "none"},
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


def _public_reason(value: Any) -> str:
    reason = str(value or "").strip().lower()
    if reason == "provider_balance_low":
        return "Provider balance is low"
    if reason == "provider_balance_unknown":
        return "Provider balance is being checked"
    if reason in {"service_not_supported", "second_lane_unavailable", "rental_not_supported"}:
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


async def _resolve_temp_offer_from_quote(token: str) -> dict[str, Any]:
    quote = _verify_quote_token(token)
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


def _order_public_status(order: dict[str, Any]) -> str:
    status = str(order.get("status") or "").strip().lower()
    wait_state = str(order.get("temp_wait_state") or "").strip().lower()
    if status in {"cancelled", "refunded"} or wait_state in {"refunded", "auto_refunded"}:
        return "refunded"
    if status in {"failed", "expired"}:
        return status
    if _temp_order_has_received_code(order):
        return "code_received"
    if wait_state == "refund_pending":
        return "refund_pending"
    return "waiting"


def _order_payload(order: dict[str, Any]) -> dict[str, Any]:
    sale_price, cost_price = extract_order_amounts(order)
    elapsed = _temp_elapsed_sec(order)
    timeout_sec = _order_temp_timeout_sec(order)
    cancel_left = max(0, TEMP_CANCEL_AFTER_SEC - elapsed)
    codes = [str(code) for code in (order.get("temp_codes") or []) if str(code or "").strip()]
    return {
        "id": str(order.get("_id") or ""),
        "status": str(order.get("status") or ""),
        "public_status": _order_public_status(order),
        "wait_state": str(order.get("temp_wait_state") or ""),
        "provider": provider_display_name(order.get("provider")),
        "provider_id": provider_public_id(order.get("provider")),
        "service": str(order.get("temp_service_key") or order.get("service_id") or ""),
        "service_label": _service_label(str(order.get("temp_service_key") or order.get("service_id") or "")),
        "country": str(order.get("temp_country") or ""),
        "state": str(order.get("temp_state") or "none"),
        "number": str(order.get("provider_number") or ""),
        "code": str(order.get("temp_last_code") or (codes[-1] if codes else "")),
        "codes": codes,
        "price": float(sale_price),
        "price_label": _money(sale_price),
        "base_price_label": _money(cost_price),
        "elapsed_sec": int(elapsed),
        "timeout_sec": int(timeout_sec),
        "seconds_left": max(0, int(timeout_sec) - int(elapsed)),
        "can_cancel": cancel_left <= 0 and not _temp_order_has_received_code(order) and _order_public_status(order) == "waiting",
        "cancel_wait_sec": int(cancel_left),
    }


async def _cancel_and_refund_temp_order(
    *,
    order_id: Any,
    order: dict[str, Any],
    actor_user_id: int,
    reason: str,
    require_no_sms: bool = True,
) -> dict[str, Any]:
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
        payload={"reason": str(reason or "cancelled"), "source": "numbers_miniapp"},
        number_mode="temp",
    )

    cancel_res: dict[str, Any] = {"success": False, "raw": "cancel_not_attempted"}
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
            "source": "numbers_miniapp",
        },
    )
    await _log_number_event_from_order(
        order,
        "refund_success",
        payload={"reason": str(reason or "cancelled"), "source": "numbers_miniapp"},
        status_after="cancelled",
        number_mode="temp",
    )
    return {"success": True, "reason": "ok"}


async def _refresh_temp_order(order: dict[str, Any]) -> dict[str, Any]:
    if not order or not order.get("_id"):
        return order
    if str(order.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
        return order

    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        return order

    current = await get_order(order["_id"]) or order
    if str(current.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
        return current
    if _temp_order_has_received_code(current):
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
    if _temp_elapsed_sec(current) < _order_temp_timeout_sec(current):
        return current

    result = await _cancel_and_refund_temp_order(
        order_id=current["_id"],
        order=current,
        actor_user_id=int(current.get("user_id") or 0),
        reason="miniapp_timeout_auto_refund",
        require_no_sms=True,
    )
    if result.get("success"):
        return await get_order(current["_id"]) or current

    await update_order_details(
        current["_id"],
        {
            "temp_wait_timeout_at": now,
            "temp_wait_state": "refund_pending",
            "temp_refund_retry_last_at": now,
            "temp_refund_retry_reason": str(result.get("reason") or "provider_cancel_failed"),
        },
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
    return await get_order(current["_id"]) or current


async def _purchase_temp_offer(
    *,
    user_id: int,
    reseller_id: int,
    lang: str,
    offer: dict[str, Any],
) -> dict[str, Any]:
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
            "number_mode": "temp",
            "source": "numbers_miniapp",
            "telegram_bot_id": None,
            "provisioning_state": "awaiting_charge",
            "provisioning_provider": provider_code,
            "provisioning_service": api_service,
            "provisioning_country": None if country == "none" else country,
            "provisioning_state_code": None if state == "none" else state,
            "provisioning_created_at": _utc_now(),
        },
    )
    order.update(
        {
            "number_mode": "temp",
            "provisioning_provider": provider_code,
            "provisioning_country": None if country == "none" else country,
            "provisioning_state_code": None if state == "none" else state,
        }
    )
    await _log_number_event_from_order(order, "order_created", payload={"source": "numbers_miniapp"}, number_mode="temp")

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
            number_mode="temp",
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
        await _log_number_event_from_order(order, "wallet_charged", status_after="paid", number_mode="temp")
        provider_country = str(info.get("provider_country") or country or "").strip()
        req_country = None if provider_country == "none" else provider_country
        req_state = None if state == "none" else state
        buy_res = await buy_number_from_provider(
            provider_code=provider_code,
            api_service_name=api_service,
            country=req_country,
            state=req_state,
            dry_run=False,
            purchase_options={
                "reuse_mode": True,
                "_audit_requested_service": service,
                "source": "numbers_miniapp",
            },
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
                number_mode="temp",
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
                "number_mode": "temp",
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
                "temp_wait_state": "waiting",
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
            number_mode="temp",
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


def _normalize_provider_rows(
    data: dict[str, Any],
    mode: str,
    *,
    service: str | None = None,
    country: str | None = None,
    state: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, info in sorted((data or {}).items(), key=lambda item: _provider_sort_key(str(item[0]))):
        if not isinstance(info, dict):
            continue
        code = str(code or "").strip().lower()
        if mode == "temp" and code in _HIDDEN_TEMP_PROVIDER_CODES:
            continue
        available = bool(info.get("available_for_buy", True))
        options = []
        if mode == "rental":
            for option in (info.get("options") or [])[:8]:
                if not isinstance(option, dict):
                    continue
                options.append(
                    {
                        "duration": str(option.get("duration") or option.get("label") or option.get("hours") or "").strip(),
                        "price": float(option.get("price") or 0.0),
                        "price_label": _money(option.get("price")),
                    }
                )
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
        rows.append(
            {
                "provider": provider_display_name(code),
                "provider_id": provider_public_id(code),
                "price": float(info.get("price") or 0.0),
                "price_label": _money(info.get("price")),
                "base_price_label": _money(info.get("base_price")),
                "success_rate": _success_rate(info.get("success_rate"), info.get("success_attempts")),
                "available": available,
                "reason": "" if available else _public_reason(info.get("provider_reason")),
                "quote_token": quote_token,
                "options": options,
            }
        )
    rows.sort(key=lambda row: (not row["available"], float(row.get("price") or 9999), str(row.get("provider_id") or "")))
    return rows[:_MAX_PRICE_ROWS]


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


async def prices(request: web.Request) -> web.Response:
    _optional_auth(request)
    mode = str(request.query.get("mode") or "temp").strip().lower()
    service = resolve_canonical_service_key(str(request.query.get("service") or "telegram"))
    country = str(request.query.get("country") or "none").strip() or "none"
    state = str(request.query.get("state") or "none").strip() or "none"
    if not service:
        raise web.HTTPBadRequest(text="invalid service")
    if mode not in {"temp", "rental", "voice"}:
        raise web.HTTPBadRequest(text="invalid mode")
    if country != "1":
        state = "none"

    try:
        if mode == "rental":
            raw = await asyncio.wait_for(
                get_all_rental_prices(service, country, with_success_rates=False),
                timeout=_PRICE_TIMEOUT_SEC,
            )
        elif mode == "voice":
            raw = await asyncio.wait_for(get_all_voice_prices(service, country, state), timeout=_PRICE_TIMEOUT_SEC)
        else:
            raw = await asyncio.wait_for(
                get_all_prices(service, country, state, with_success_rates=False),
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
    return web.json_response(
        {
            "ok": True,
            "mode": mode,
            "service": {"key": service, "label": _service_label(service)},
            "country": country,
            "state": state,
            "providers": rows,
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def active_orders(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    user_doc = await _load_or_create_user(auth)
    lang = _lang_from_user(user_doc, auth)
    _ = lang
    orders = await list_user_open_temp_orders(int(auth["user_id"]), limit=10)
    rows: list[dict[str, Any]] = []
    for order in orders or []:
        try:
            refreshed = await _refresh_temp_order(order)
        except Exception:
            logger.exception("numbers miniapp order refresh failed: order=%s", order.get("_id"))
            refreshed = order
        rows.append(_order_payload(refreshed))
    return web.json_response({"ok": True, "orders": rows}, headers=dict(_NO_STORE_HEADERS))


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

    result = await _purchase_temp_offer(
        user_id=int(auth["user_id"]),
        reseller_id=int(auth["user_id"]),
        lang=lang,
        offer=offer,
    )
    if not result.get("ok"):
        status = 402 if str(result.get("code")) == "INSUFFICIENT_USER_BALANCE" else 409
        return _json_error(str(result.get("message") or ""), status=status, code=str(result.get("code") or "purchase_failed"))

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
        refreshed = await _refresh_temp_order(order)
    except Exception:
        logger.exception("numbers miniapp manual refresh failed: order=%s", raw_id)
        refreshed = order
    return web.json_response({"ok": True, "order": _order_payload(refreshed)}, headers=dict(_NO_STORE_HEADERS))


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
    )
    if not result.get("success"):
        refreshed = await get_order(order_id) or order
        return _json_error(
            _text(lang, "Could not cancel this order right now.", "تعذر إلغاء الطلب حاليا."),
            status=409,
            code=str(result.get("reason") or "cancel_failed"),
            order=_order_payload(refreshed),
        )
    refreshed = await get_order(order_id) or order
    return web.json_response(
        {
            "ok": True,
            "message": _text(lang, "Order cancelled and refunded.", "تم إلغاء الطلب وإرجاع الرصيد."),
            "order": _order_payload(refreshed),
        },
        headers=dict(_NO_STORE_HEADERS),
    )


def register_numbers_routes(app: web.Application) -> None:
    app.router.add_get("/mini/numbers", index)
    app.router.add_get("/mini/numbers/static/{name}", static_file)
    app.router.add_get("/mini/numbers/api/bootstrap", bootstrap)
    app.router.add_get("/mini/numbers/api/prices", prices)
    app.router.add_get("/mini/numbers/api/orders", active_orders)
    app.router.add_post("/mini/numbers/api/purchase", purchase_temp)
    app.router.add_post("/mini/numbers/api/orders/{order_id}/refresh", refresh_order)
    app.router.add_post("/mini/numbers/api/orders/{order_id}/cancel", cancel_order)
