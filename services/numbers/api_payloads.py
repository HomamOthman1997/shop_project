from __future__ import annotations

from typing import Any

from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.data.states_us import STATES_LIST
from services.numbers.service_map import (
    get_service_aliases,
    get_service_display_name,
    list_service_keys,
    resolve_canonical_service_key,
)
from utils.bot_menu_context import numbers_bot_url
from utils.services_keyboard import DEFAULT_TOP_SERVICES, load_top_services

_BOOTSTRAP_CACHE: dict[str, Any] = {"data": None}


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
