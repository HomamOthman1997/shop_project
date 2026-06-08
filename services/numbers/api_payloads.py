from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from config import settings
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.data.states_us import STATES_LIST
from services.numbers.provider_quality import provider_quality, provider_recommendation_bonus, provider_service_blacklisted
from services.numbers.provider_readiness import provider_purchase_enabled
from services.numbers.service_map import (
    get_service_aliases,
    get_service_display_name,
    list_service_keys,
    resolve_canonical_service_key,
)
from utils.bot_menu_context import numbers_bot_url
from utils.provider_alias import provider_display_name, provider_public_id
from utils.services_keyboard import DEFAULT_TOP_SERVICES, load_top_services

_BOOTSTRAP_CACHE: dict[str, Any] = {"data": None}
QUOTE_TTL_SEC = 1800
TEMP_QUOTE_PROVIDER_CODES = (
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
RENTAL_QUOTE_PROVIDER_CODES = (
    "smspool",
    "herosms",
    "textverified",
    "pvadeals",
    "smsready",
    "pvapins",
)
VOICE_QUOTE_PROVIDER_CODES = ("textverified",)
TRUSTED_SUCCESS_RATE_PERCENT = 90.0
TRUSTED_SUCCESS_RATE_TIERS = {"excellent", "trusted"}
PROVIDER_SUCCESS_RATE_OVERRIDES = {
    "herosms": 70.0,
}
VOICE_GENERIC_SERVICE = "servicenotlistedvoice"
HIDDEN_TEMP_PROVIDER_CODES = {"nonvoip_s6"}
MAX_QUOTE_PROVIDER_ROWS = 16
TEXTVERIFIED_RENTAL_STATE_SURCHARGE = 2.0
RENTAL_OUTLIER_PRICE_MULTIPLIER = 4.0


def clear_numbers_api_payload_cache() -> None:
    _BOOTSTRAP_CACHE["data"] = None


def _clean_aliases(values: list[Any] | tuple[Any, ...]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        aliases.append(text)
    return aliases


def country_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [{"code": "none", "iso": "", "name": "Any country", "aliases": ["any", "all"]}]
    for item in COUNTRIES_LIST:
        code = str(item.get("code") or "").strip()
        iso = str(item.get("iso") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        if code and name and "_V" not in iso:
            aliases = _clean_aliases([code, iso, name, *(item.get("aliases") or [])])
            rows.append({"code": code, "iso": iso, "name": name, "aliases": aliases})
    return rows


def state_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [{"code": "none", "name": "Any state", "aliases": ["any", "all"]}]
    for item in STATES_LIST:
        code = str(item.get("code") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        if code and name:
            aliases = _clean_aliases([code, name, *(item.get("aliases") or [])])
            rows.append({"code": code, "name": name, "aliases": aliases})
    return rows


def service_rows() -> list[dict[str, Any]]:
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
        services.append(
            {
                "key": canonical,
                "label": get_service_display_name(canonical),
                "aliases": list(get_service_aliases(canonical)),
                "top": is_top,
            }
        )

    for key in top:
        push(key, is_top=True)
    for key in list_service_keys():
        push(key, is_top=False)
    return services


def _api_action(
    key: str,
    endpoint: str,
    *,
    method: str = "GET",
    scope: str = "",
    enabled: bool = True,
    reason: str = "",
    requires_idempotency_key: bool = False,
) -> dict[str, Any]:
    return {
        "key": str(key or ""),
        "enabled": bool(enabled),
        "endpoint": str(endpoint or ""),
        "method": str(method or "GET").upper(),
        "scope": str(scope or ""),
        "reason": "" if enabled else str(reason or ""),
        "requires_idempotency_key": bool(requires_idempotency_key),
    }


def api_discovery_payload() -> dict[str, Any]:
    return {
        "base_path": "/api/v1/numbers",
        "quote_ttl_sec": int(QUOTE_TTL_SEC),
        "required_headers": {
            "auth": "Authorization: Bearer <api_key>",
            "idempotency": "Idempotency-Key for mutating create/resend/replace/renew calls",
        },
        "capabilities": {
            "modes": ["temp", "rental", "voice"],
            "provider_identity_public": False,
            "provider_sms_polling_enabled": bool(getattr(settings, "numbers_provider_sms_polling_enabled", False)),
            "manual_customer_refund_enabled": False,
            "recharge_submit_enabled": True,
            "support_ticket_submit_enabled": True,
            "server_managed_refunds": True,
            "customer_webhooks": True,
        },
        "actions": {
            "api_docs": _api_action("api_docs", "/api/v1/numbers/docs", scope="public"),
            "openapi": _api_action("openapi", "/api/v1/numbers/openapi.json", scope="public"),
            "bootstrap": _api_action("bootstrap", "/api/v1/numbers/catalog/bootstrap", scope="public"),
            "country_suggestions": _api_action(
                "country_suggestions",
                "/api/v1/numbers/country-suggestions",
                scope="numbers:quotes",
            ),
            "account": _api_action("account", "/api/v1/numbers/account", scope="numbers:account:read"),
            "recharge": _api_action("recharge", "/api/v1/numbers/recharge", scope="numbers:account:read"),
            "recharge_requests": _api_action("recharge_requests", "/api/v1/numbers/recharge/requests", scope="numbers:account:read"),
            "support": _api_action("support", "/api/v1/numbers/support", scope="numbers:account:read"),
            "quotes": _api_action("quotes", "/api/v1/numbers/quotes", scope="numbers:quotes"),
            "orders": _api_action("orders", "/api/v1/numbers/orders", scope="numbers:orders:read"),
            "create_order": _api_action(
                "create_order",
                "/api/v1/numbers/orders",
                method="POST",
                scope="numbers:orders:create",
                requires_idempotency_key=True,
            ),
            "order_detail": _api_action(
                "order_detail",
                "/api/v1/numbers/orders/{order_id}",
                scope="numbers:orders:read",
            ),
            "refresh_order": _api_action(
                "refresh_order",
                "/api/v1/numbers/orders/{order_id}/refresh",
                method="POST",
                scope="numbers:orders:refresh",
            ),
            "resend_order": _api_action(
                "resend_order",
                "/api/v1/numbers/orders/{order_id}/resend",
                method="POST",
                scope="numbers:orders:resend",
                requires_idempotency_key=True,
            ),
            "replace_order": _api_action(
                "replace_order",
                "/api/v1/numbers/orders/{order_id}/replace",
                method="POST",
                scope="numbers:orders:replace",
                requires_idempotency_key=True,
            ),
            "alternate_provider": _api_action(
                "alternate_provider",
                "/api/v1/numbers/orders/{order_id}/alternate",
                method="POST",
                scope="numbers:orders:replace",
                requires_idempotency_key=True,
            ),
            "cancel_order": _api_action(
                "cancel_order",
                "/api/v1/numbers/orders/{order_id}/cancel",
                method="POST",
                scope="numbers:orders:cancel",
                requires_idempotency_key=True,
            ),
            "download_recording": _api_action(
                "download_recording",
                "/api/v1/numbers/orders/{order_id}/recording",
                scope="numbers:orders:read",
            ),
            "rental_sms": _api_action(
                "rental_sms",
                "/api/v1/numbers/orders/{order_id}/rental/sms",
                method="POST",
                scope="numbers:orders:rental",
            ),
            "rental_finish": _api_action(
                "rental_finish",
                "/api/v1/numbers/orders/{order_id}/rental/finish",
                method="POST",
                scope="numbers:orders:rental",
            ),
            "rental_renew": _api_action(
                "rental_renew",
                "/api/v1/numbers/orders/{order_id}/rental/renew",
                method="POST",
                scope="numbers:orders:rental",
                requires_idempotency_key=True,
            ),
            "rental_wake": _api_action(
                "rental_wake",
                "/api/v1/numbers/orders/{order_id}/rental/wake",
                method="POST",
                scope="numbers:orders:rental",
            ),
            "rental_notes": _api_action(
                "rental_notes",
                "/api/v1/numbers/orders/{order_id}/rental/notes",
                method="POST",
                scope="numbers:orders:rental",
            ),
            "customer_webhooks": _api_action(
                "customer_webhooks",
                "/api/v1/webhooks",
                scope="webhooks:manage",
            ),
            "api_keys": _api_action(
                "api_keys",
                "/api/v1/api-keys",
                scope="api_keys:manage",
            ),
            "submit_recharge": _api_action(
                "submit_recharge",
                "/api/v1/numbers/recharge/submit",
                method="POST",
                scope="numbers:account:read",
            ),
            "submit_ticket": _api_action(
                "submit_ticket",
                "/api/v1/numbers/support/ticket",
                method="POST",
                scope="numbers:account:read",
            ),
        },
    }


def numbers_bootstrap_payload() -> dict[str, Any]:
    cached = _BOOTSTRAP_CACHE.get("data")
    if isinstance(cached, dict):
        return cached

    payload = {
        "ok": True,
        "version": "v1",
        "modes": [
            {"key": "temp", "label": "Temporary SMS"},
            {"key": "rental", "label": "Rental numbers"},
            {"key": "voice", "label": "US call number"},
        ],
        "countries": country_rows(),
        "states_us": state_rows(),
        "services": service_rows(),
        "defaults": {"mode": "temp", "service": "", "country": "none", "state": "none"},
        "client": {
            "primary_surface": "miniapp",
            "telegram_order_flow_enabled": bool(getattr(settings, "numbers_telegram_order_flow_enabled", False)),
            "provider_sms_polling_enabled": bool(getattr(settings, "numbers_provider_sms_polling_enabled", False)),
            "manual_customer_refund_enabled": False,
        },
        "api": api_discovery_payload(),
        "links": {
            "numbers_bot": numbers_bot_url("numbers"),
            "recharge": numbers_bot_url("balance"),
        },
    }
    _BOOTSTRAP_CACHE["data"] = payload
    return payload


def money_label(value: Any) -> str:
    try:
        amount = float(value or 0.0)
    except Exception:
        amount = 0.0
    if amount <= 0:
        return "-"
    text = f"{amount:.4f}".rstrip("0").rstrip(".")
    return f"${text}"


def success_attempt_count(info: dict[str, Any]) -> int:
    try:
        attempts = int(info.get("success_attempts") or 0)
    except Exception:
        attempts = 0
    try:
        context_attempts = int(info.get("context_success_attempts") or 0)
    except Exception:
        context_attempts = 0
    return max(attempts, context_attempts)


def success_rate_label(value: Any, attempts: Any = None) -> str:
    try:
        attempt_count = int(attempts or 0)
    except Exception:
        attempt_count = 0
    min_attempts = max(1, int(getattr(settings, "numbers_success_rate_display_min_attempts", 5) or 5))
    if attempt_count < min_attempts:
        return "-"
    try:
        rate = max(0.0, min(100.0, float(value if value is not None else 100.0)))
    except Exception:
        rate = 100.0
    return f"{int(rate)}%" if rate.is_integer() else f"{rate:.1f}%"


def provider_success_rate_label(provider_code: str, value: Any, attempts: Any = None) -> str:
    code = str(provider_code or "").strip().lower()
    if code in PROVIDER_SUCCESS_RATE_OVERRIDES:
        return success_rate_label(PROVIDER_SUCCESS_RATE_OVERRIDES[code], getattr(settings, "numbers_success_rate_display_min_attempts", 5))
    quality = provider_quality(provider_code)
    if quality.tier in TRUSTED_SUCCESS_RATE_TIERS:
        return success_rate_label(TRUSTED_SUCCESS_RATE_PERCENT, getattr(settings, "numbers_success_rate_display_min_attempts", 5))
    return success_rate_label(value, attempts)


def _quote_secret() -> bytes:
    token = str(getattr(settings, "bot_numbers_token", "") or getattr(settings, "bot_main_token", "") or "").strip()
    seed = token or "numbers-api-local"
    return hashlib.sha256(f"numbers-api:{seed}".encode("utf-8")).digest()


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padded = str(value or "") + ("=" * (-len(str(value or "")) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def make_quote_token(payload: dict[str, Any]) -> str:
    clean_payload = dict(payload or {})
    provider_code = str(clean_payload.pop("provider", "") or "").strip().lower()
    if provider_code and not str(clean_payload.get("provider_id") or "").strip():
        clean_payload["provider_id"] = provider_public_id(provider_code)
    clean_payload["exp"] = int(time.time()) + QUOTE_TTL_SEC
    body = _b64_encode(json.dumps(clean_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_quote_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


class QuoteTokenError(ValueError):
    pass


def verify_quote_token(token: str) -> dict[str, Any]:
    raw = str(token or "").strip()
    if "." not in raw:
        raise QuoteTokenError("invalid_quote")
    body, sig = raw.rsplit(".", 1)
    expected = hmac.new(_quote_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise QuoteTokenError("bad_quote")
    try:
        payload = json.loads(_b64_decode(body).decode("utf-8"))
    except Exception as exc:
        raise QuoteTokenError("bad_quote_payload") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise QuoteTokenError("quote_expired")
    return payload


def _provider_sort_key(code: str) -> tuple[int, str, str]:
    public = provider_public_id(code)
    rank = 999
    if public.startswith("S") and public[1:].isdigit():
        rank = int(public[1:])
    return (rank, public, code)


def _provider_buyable_for_temp(provider_code: str, info: dict[str, Any], *, service: str | None = None) -> bool:
    code = str(provider_code or "").strip().lower()
    if not code or code in HIDDEN_TEMP_PROVIDER_CODES:
        return False
    if provider_service_blacklisted(code, service):
        return False
    if not provider_purchase_enabled(code, mode="temp"):
        return False
    if not isinstance(info, dict) or not bool(info.get("available_for_buy", True)):
        return False
    if not str(info.get("api_service_name") or "").strip():
        return False
    try:
        return float(info.get("price") or 0.0) > 0
    except Exception:
        return False


def temp_provider_offer_is_buyable(provider_code: str, info: dict[str, Any]) -> bool:
    service = str((info or {}).get("requested_service") or (info or {}).get("canonical_service") or "").strip()
    return _provider_buyable_for_temp(provider_code, info, service=service)


def rental_state_code_for_quote(state: str | None) -> str:
    raw = str(state or "none").strip().upper()
    if raw and raw != "NONE" and len(raw) == 2:
        return raw
    return "none"


def rental_duration_label(option: dict[str, Any]) -> str:
    label = str((option or {}).get("duration_label") or "").strip()
    if label:
        return label
    try:
        hours = int((option or {}).get("duration") or 0)
    except Exception:
        hours = 0
    if hours <= 0:
        return "-"
    if hours % 24 == 0:
        return f"{hours // 24}d"
    return f"{hours}h"


def rental_option_match_key(option: dict[str, Any]) -> tuple[str, ...]:
    option = option or {}
    return (
        str(option.get("duration") or "").strip(),
        str(option.get("rental_id") or "").strip(),
        str(option.get("tv_duration_key") or "").strip(),
        "1" if bool(option.get("tv_is_renewable")) else "0",
        str(option.get("state_code") or "none").strip().lower(),
        str(option.get("duration_label") or "").strip().lower(),
        str(option.get("country") or option.get("provider_country") or option.get("country_code") or "").strip().lower(),
    )


def rental_option_candidates(
    provider_code: str,
    provider_info: dict[str, Any],
    *,
    state: str | None = None,
) -> list[dict[str, Any]]:
    code = str(provider_code or "").strip().lower()
    info = provider_info or {}
    api_service = str(info.get("api_service_name") or "").strip()
    state_code = rental_state_code_for_quote(state)
    use_textverified_state = code == "textverified" and state_code != "none"
    rows: list[dict[str, Any]] = []

    for raw_option in info.get("options") or []:
        if not isinstance(raw_option, dict):
            continue
        option = dict(raw_option)
        option.setdefault("provider", code)
        option.setdefault("api_service_name", api_service)
        if code == "textverified":
            option["tv_with_state"] = bool(use_textverified_state)
            option["state_code"] = state_code if use_textverified_state else "none"
            if use_textverified_state:
                try:
                    option["price"] = round(float(option.get("price") or 0.0) + TEXTVERIFIED_RENTAL_STATE_SURCHARGE, 4)
                except Exception:
                    option["price"] = TEXTVERIFIED_RENTAL_STATE_SURCHARGE
                if option.get("base_price") not in (None, ""):
                    try:
                        option["base_price"] = round(
                            float(option.get("base_price") or 0.0) + TEXTVERIFIED_RENTAL_STATE_SURCHARGE,
                            4,
                        )
                    except Exception:
                        option["base_price"] = option["price"]
                option["state_surcharge"] = TEXTVERIFIED_RENTAL_STATE_SURCHARGE
        else:
            option.setdefault("state_code", "none")
        rows.append(option)
    return rows


def rental_option_is_buyable(
    *,
    service: str | None,
    country: str | None,
    provider_code: str,
    provider_info: dict[str, Any],
    option: dict[str, Any],
) -> bool:
    if not service or not country or not provider_code:
        return False
    if provider_code not in RENTAL_QUOTE_PROVIDER_CODES:
        return False
    if not provider_purchase_enabled(provider_code, mode="rental"):
        return False
    if not isinstance(provider_info, dict) or not bool(provider_info.get("available_for_buy", True)):
        return False
    if not str(provider_info.get("api_service_name") or "").strip():
        return False
    try:
        duration = int((option or {}).get("duration") or 0)
        price = float((option or {}).get("price") or 0.0)
    except Exception:
        return False
    return duration > 0 and price > 0


def _rental_duration_min_prices(data: dict[str, Any], *, service: str, country: str, state: str) -> dict[str, float]:
    min_prices: dict[str, float] = {}
    for raw_code, info in (data or {}).items():
        code = str(raw_code or "").strip().lower()
        if code not in RENTAL_QUOTE_PROVIDER_CODES or not isinstance(info, dict):
            continue
        for option in rental_option_candidates(code, info, state=state):
            if not rental_option_is_buyable(
                service=service,
                country=country,
                provider_code=code,
                provider_info=info,
                option=option,
            ):
                continue
            duration_key = str(option.get("duration") or "").strip()
            if not duration_key:
                continue
            try:
                price = float(option.get("price") or 0.0)
            except Exception:
                continue
            if price <= 0:
                continue
            current = min_prices.get(duration_key)
            if current is None or price < current:
                min_prices[duration_key] = price
    return min_prices


def rental_option_is_price_outlier(option: dict[str, Any], duration_min_prices: dict[str, float]) -> bool:
    duration_key = str((option or {}).get("duration") or "").strip()
    if not duration_key:
        return False
    min_price = duration_min_prices.get(duration_key)
    if min_price is None or min_price <= 0:
        return False
    try:
        price = float((option or {}).get("price") or 0.0)
    except Exception:
        return False
    return price > min_price * RENTAL_OUTLIER_PRICE_MULTIPLIER


def voice_provider_offer_is_buyable(provider_code: str, info: dict[str, Any]) -> bool:
    code = str(provider_code or "").strip().lower()
    if code not in VOICE_QUOTE_PROVIDER_CODES:
        return False
    if not provider_purchase_enabled(code, mode="voice"):
        return False
    if not isinstance(info, dict) or not bool(info.get("available_for_buy", True)):
        return False
    if not bool(info.get("voice_capable", True)):
        return False
    if not str(info.get("api_service_name") or "").strip():
        return False
    try:
        return float(info.get("price") or 0.0) > 0
    except Exception:
        return False


def _recommended_temp_provider_code(data: dict[str, Any], *, service: str | None = None) -> str:
    buyable: list[tuple[str, float, float]] = []
    min_attempts = max(1, int(getattr(settings, "numbers_success_rate_display_min_attempts", 5) or 5))
    for provider_code, info in (data or {}).items():
        code = str(provider_code or "").strip().lower()
        if not isinstance(info, dict) or not _provider_buyable_for_temp(code, info, service=service):
            continue
        if bool(info.get("recommendation_blocked")):
            continue
        try:
            price = float(info.get("price") or 9999)
        except Exception:
            price = 9999.0
        attempts = success_attempt_count(info)
        success_value = info.get("recommended_success_rate") if info.get("recommended_success_rate") is not None else info.get("success_rate", 100)
        try:
            success_rate = float(success_value if attempts >= min_attempts else 100.0)
        except Exception:
            success_rate = 100.0
        adjusted_rate = max(0.0, min(100.0, success_rate + provider_recommendation_bonus(code, service)))
        buyable.append((code, price, adjusted_rate))
    if not buyable:
        return ""
    buyable.sort(key=lambda row: (-row[2], row[1], _provider_sort_key(row[0])))
    return buyable[0][0]


def normalize_temp_quote_rows(
    data: dict[str, Any],
    *,
    service: str,
    country: str,
    state: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    recommended_code = _recommended_temp_provider_code(data, service=service)

    for raw_code, info in sorted((data or {}).items(), key=lambda item: _provider_sort_key(str(item[0]))):
        code = str(raw_code or "").strip().lower()
        if not isinstance(info, dict) or not _provider_buyable_for_temp(code, info, service=service):
            continue

        attempts = success_attempt_count(info)
        success_value = info.get("recommended_success_rate") if info.get("recommended_success_rate") is not None else info.get("success_rate", 100)
        provider_state_code = str(info.get("provider_state_code") or "").strip().upper()
        provider_country_iso = str(info.get("provider_country_iso") or "").strip().upper()
        quote_token = make_quote_token(
            {
                "mode": "temp",
                "service": service,
                "country": country,
                "state": state,
                "provider": code,
                "provider_country": str(info.get("provider_country") or "").strip(),
                "provider_country_iso": provider_country_iso,
                "provider_state_code": provider_state_code,
            }
        )
        rows.append(
            {
                "provider": provider_display_name(code),
                "provider_id": provider_public_id(code),
                "location_tag": provider_state_code or provider_country_iso,
                "price": float(info.get("price") or 0.0),
                "price_label": money_label(info.get("price")),
                "success_rate": provider_success_rate_label(code, success_value, attempts),
                "success_attempts": int(attempts),
                "available": True,
                "quote_token": quote_token,
                "recommended": code == recommended_code,
            }
        )

    rows.sort(key=lambda row: (not row.get("recommended"), float(row.get("price") or 9999), str(row.get("provider_id") or "")))
    return rows[:MAX_QUOTE_PROVIDER_ROWS]


def _recommended_rental_provider_code(data: dict[str, Any], *, service: str, country: str, state: str) -> str:
    buyable: list[tuple[str, float]] = []
    for provider_code, info in (data or {}).items():
        code = str(provider_code or "").strip().lower()
        if not isinstance(info, dict):
            continue
        prices: list[float] = []
        for option in rental_option_candidates(code, info, state=state):
            if not rental_option_is_buyable(
                service=service,
                country=country,
                provider_code=code,
                provider_info=info,
                option=option,
            ):
                continue
            try:
                prices.append(float(option.get("price") or 0.0))
            except Exception:
                continue
        if prices and not bool(info.get("recommendation_blocked")):
            buyable.append((code, min(prices)))
    if not buyable:
        return ""
    buyable.sort(key=lambda row: (row[1], _provider_sort_key(row[0])))
    return buyable[0][0]


def normalize_rental_quote_rows(
    data: dict[str, Any],
    *,
    service: str,
    country: str,
    state: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    duration_min_prices = _rental_duration_min_prices(data, service=service, country=country, state=state)
    recommended_code = _recommended_rental_provider_code(data, service=service, country=country, state=state)

    for raw_code, info in sorted((data or {}).items(), key=lambda item: _provider_sort_key(str(item[0]))):
        code = str(raw_code or "").strip().lower()
        if code not in RENTAL_QUOTE_PROVIDER_CODES or not isinstance(info, dict):
            continue
        options: list[dict[str, Any]] = []
        for normalized_option in rental_option_candidates(code, info, state=state):
            if not rental_option_is_buyable(
                service=service,
                country=country,
                provider_code=code,
                provider_info=info,
                option=normalized_option,
            ):
                continue
            if rental_option_is_price_outlier(normalized_option, duration_min_prices):
                continue
            option_state = str(normalized_option.get("state_code") or "none").strip() or "none"
            quote_token = make_quote_token(
                {
                    "mode": "rental",
                    "service": str(service or ""),
                    "country": str(country or "none"),
                    "state": option_state,
                    "provider": code,
                    "option_key": list(rental_option_match_key(normalized_option)),
                }
            )
            option_payload = {
                "duration": str(normalized_option.get("duration") or normalized_option.get("label") or normalized_option.get("hours") or "").strip(),
                "duration_label": rental_duration_label(normalized_option),
                "price": float(normalized_option.get("price") or 0.0),
                "price_label": money_label(normalized_option.get("price")),
                "quote_token": quote_token,
                "state_code": option_state,
            }
            option_country_name = str(
                normalized_option.get("provider_country_name") or normalized_option.get("country_name") or normalized_option.get("country_label") or ""
            ).strip()
            option_country_iso = str(normalized_option.get("provider_country_iso") or normalized_option.get("country_iso") or "").strip().upper()
            option_country = str(normalized_option.get("country") or normalized_option.get("provider_country") or "").strip()
            if option_country_name or option_country_iso or option_country:
                option_payload["location_tag"] = option_country_name or option_country_iso or option_country
                option_payload["country_label"] = option_country_name
                option_payload["country_iso"] = option_country_iso
                option_payload["country"] = option_country
            if "tv_is_renewable" in normalized_option:
                option_payload["renewable"] = bool(normalized_option.get("tv_is_renewable"))
            if "tv_with_state" in normalized_option:
                option_payload["with_state"] = bool(normalized_option.get("tv_with_state"))
            options.append(option_payload)
        if not options:
            continue
        options.sort(key=lambda option: float(option.get("price") or 9999))
        attempts = success_attempt_count(info)
        success_value = info.get("recommended_success_rate") if info.get("recommended_success_rate") is not None else info.get("success_rate", 100)
        provider_state_code = str(info.get("provider_state_code") or "").strip().upper()
        provider_country_iso = str(info.get("provider_country_iso") or "").strip().upper()
        rows.append(
            {
                "provider": provider_display_name(code),
                "provider_id": provider_public_id(code),
                "location_tag": provider_state_code or provider_country_iso,
                "price": float(options[0]["price"]),
                "price_label": money_label(options[0]["price"]),
                "success_rate": provider_success_rate_label(code, success_value, attempts),
                "success_attempts": int(attempts),
                "available": True,
                "quote_token": "",
                "options": options,
                "recommended": code == recommended_code,
            }
        )

    rows.sort(key=lambda row: (not row.get("recommended"), float(row.get("price") or 9999), str(row.get("provider_id") or "")))
    return rows[:MAX_QUOTE_PROVIDER_ROWS]


def normalize_voice_quote_rows(
    data: dict[str, Any],
    *,
    service: str,
    country: str,
    state: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for raw_code, info in sorted((data or {}).items(), key=lambda item: _provider_sort_key(str(item[0]))):
        code = str(raw_code or "").strip().lower()
        if not voice_provider_offer_is_buyable(code, info if isinstance(info, dict) else {}):
            continue

        provider_state_code = str(info.get("provider_state_code") or state or "").strip().upper()
        provider_country_iso = str(info.get("provider_country_iso") or "US").strip().upper()
        attempts = success_attempt_count(info)
        success_value = info.get("recommended_success_rate") if info.get("recommended_success_rate") is not None else info.get("success_rate", 100)
        quote_token = make_quote_token(
            {
                "mode": "voice",
                "service": str(service or ""),
                "country": str(country or "1"),
                "state": str(state or "none"),
                "provider": code,
            }
        )
        rows.append(
            {
                "provider": provider_display_name(code),
                "provider_id": provider_public_id(code),
                "location_tag": provider_state_code or provider_country_iso,
                "price": float(info.get("price") or 0.0),
                "price_label": money_label(info.get("price")),
                "success_rate": provider_success_rate_label(code, success_value, attempts),
                "success_attempts": int(attempts),
                "available": True,
                "quote_token": quote_token,
                "recommended": True,
                "voice": True,
                "fallback": bool(info.get("voice_fallback_service")),
                "voice_fallback": bool(info.get("voice_fallback_service")),
            }
        )

    rows.sort(key=lambda row: (not row.get("recommended"), float(row.get("price") or 9999), str(row.get("provider_id") or "")))
    return rows[:MAX_QUOTE_PROVIDER_ROWS]
