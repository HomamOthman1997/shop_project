from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import web

from config import settings
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.data.states_us import STATES_LIST
from services.numbers.manager import get_all_prices, get_all_rental_prices, get_all_voice_prices
from services.numbers.service_map import get_service_display_name, list_service_keys, resolve_canonical_service_key
from utils.provider_alias import provider_display_name, provider_public_id
from utils.services_keyboard import DEFAULT_TOP_SERVICES, load_top_services

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
        services.append({"key": canonical, "label": _service_label(canonical), "top": is_top})

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


def _normalize_provider_rows(data: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, info in sorted((data or {}).items(), key=lambda item: _provider_sort_key(str(item[0]))):
        if not isinstance(info, dict):
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

    rows = _normalize_provider_rows(raw, mode)
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


def register_numbers_routes(app: web.Application) -> None:
    app.router.add_get("/mini/numbers", index)
    app.router.add_get("/mini/numbers/static/{name}", static_file)
    app.router.add_get("/mini/numbers/api/bootstrap", bootstrap)
    app.router.add_get("/mini/numbers/api/prices", prices)
