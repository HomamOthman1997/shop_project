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
QUOTE_TTL_SEC = 300
TEMP_QUOTE_PROVIDER_CODES = (
    "smspool",
    "telabot",
    "textverified",
    "herosms",
    "pvadeals",
    "vaksms",
    "smsready",
    "pvapins",
)
HIDDEN_TEMP_PROVIDER_CODES = {"smsman", "smsman_s6"}
MAX_QUOTE_PROVIDER_ROWS = 16


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


def _provider_buyable_for_temp(provider_code: str, info: dict[str, Any]) -> bool:
    code = str(provider_code or "").strip().lower()
    if not code or code in HIDDEN_TEMP_PROVIDER_CODES:
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
    return _provider_buyable_for_temp(provider_code, info)


def _recommended_temp_provider_code(data: dict[str, Any]) -> str:
    buyable: list[tuple[str, float]] = []
    for provider_code, info in (data or {}).items():
        code = str(provider_code or "").strip().lower()
        if not isinstance(info, dict) or not _provider_buyable_for_temp(code, info):
            continue
        if bool(info.get("recommendation_blocked")):
            continue
        try:
            price = float(info.get("price") or 9999)
        except Exception:
            price = 9999.0
        buyable.append((code, price))
    if not buyable:
        return ""
    buyable.sort(key=lambda row: (row[1], _provider_sort_key(row[0])))
    return buyable[0][0]


def normalize_temp_quote_rows(
    data: dict[str, Any],
    *,
    service: str,
    country: str,
    state: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    recommended_code = _recommended_temp_provider_code(data)

    for raw_code, info in sorted((data or {}).items(), key=lambda item: _provider_sort_key(str(item[0]))):
        code = str(raw_code or "").strip().lower()
        if not isinstance(info, dict) or not _provider_buyable_for_temp(code, info):
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
            }
        )
        rows.append(
            {
                "provider": provider_display_name(code),
                "provider_id": provider_public_id(code),
                "location_tag": provider_state_code or provider_country_iso,
                "price": float(info.get("price") or 0.0),
                "price_label": money_label(info.get("price")),
                "success_rate": success_rate_label(success_value, attempts),
                "success_attempts": int(attempts),
                "available": True,
                "quote_token": quote_token,
                "recommended": code == recommended_code,
            }
        )

    rows.sort(key=lambda row: (not row.get("recommended"), float(row.get("price") or 9999), str(row.get("provider_id") or "")))
    return rows[:MAX_QUOTE_PROVIDER_ROWS]
