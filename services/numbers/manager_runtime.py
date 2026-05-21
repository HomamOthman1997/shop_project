import asyncio
import json
import logging
import time
from typing import Any

from services.numbers.manager_helpers import _extract_balance_value

logger = logging.getLogger("numbers_manager")


def _provider_timeout_sec(settings_obj: Any, kind: str, provider_code: str | None = None) -> float:
    if kind == "rental":
        base = float(getattr(settings_obj, "numbers_rental_provider_timeout_sec", 10.0) or 10.0)
        base = min(base, 7.0)
        if str(provider_code or "").strip().lower() == "textverified":
            tv_override = getattr(settings_obj, "numbers_textverified_rental_timeout_sec", None)
            if tv_override not in (None, ""):
                try:
                    return max(3.0, float(tv_override))
                except (TypeError, ValueError):
                    pass
            return max(3.0, min(base, 5.0))
        return max(3.0, base)
    base = float(getattr(settings_obj, "numbers_provider_timeout_sec", 12.0) or 12.0)
    return max(3.0, base)


def _price_screen_provider_timeout_sec(settings_obj: Any, provider_code: str | None = None) -> float:
    explicit = getattr(settings_obj, "numbers_price_screen_provider_timeout_sec", None)
    if explicit not in (None, ""):
        try:
            return max(1.0, float(explicit))
        except (TypeError, ValueError):
            pass
    code = str(provider_code or "").strip().lower()
    if code == "smspool":
        return 16.0
    if code == "herosms":
        return 8.0
    if code == "textverified":
        return 7.0
    return max(1.0, min(_provider_timeout_sec(settings_obj, "temp", provider_code), 5.5))


def _service_resolution_timeout_sec(settings_obj: Any, provider_code: str | None = None) -> float:
    explicit = getattr(settings_obj, "numbers_service_resolution_timeout_sec", None)
    if explicit not in (None, ""):
        try:
            return max(0.5, float(explicit))
        except (TypeError, ValueError):
            pass
    code = str(provider_code or "").strip().lower()
    if code == "textverified":
        return 2.5
    return 2.0


def _provider_service_catalog_cache_ttl_sec(settings_obj: Any) -> int:
    try:
        return max(0, int(getattr(settings_obj, "numbers_provider_service_catalog_cache_ttl_sec", 900) or 900))
    except (TypeError, ValueError):
        return 900


def _price_screen_balance_timeout_sec(settings_obj: Any) -> float:
    try:
        value = float(getattr(settings_obj, "numbers_price_screen_balance_timeout_sec", 2.0) or 2.0)
    except (TypeError, ValueError):
        value = 2.0
    return max(0.5, value)


def _simulated_provider_balances(settings_obj: Any) -> dict[str, float]:
    raw = str(getattr(settings_obj, "numbers_provider_balance_simulation", "") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        logger.warning("invalid numbers_provider_balance_simulation json")
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in data.items():
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        out[str(key or "").strip().lower()] = amount
    return out


async def _provider_balance(provider_obj: Any, *, settings_obj: Any, providers: dict[str, Any], balance_cache: dict[str, dict[str, Any]]) -> float | None:
    return await _provider_balance_with_timeout(
        provider_obj,
        settings_obj=settings_obj,
        providers=providers,
        balance_cache=balance_cache,
    )


async def _provider_balance_with_timeout(
    provider_obj: Any,
    *,
    settings_obj: Any,
    providers: dict[str, Any],
    balance_cache: dict[str, dict[str, Any]],
    timeout_sec: float | None = None,
) -> float | None:
    provider_name = str(getattr(provider_obj, "__class__", type("X", (), {})).__name__ or "").lower()
    simulated_balances = _simulated_provider_balances(settings_obj)
    if provider_name:
        simulated = simulated_balances.get(provider_name)
        if simulated is not None:
            return float(simulated)
    for provider_code, candidate in providers.items():
        if candidate is provider_obj:
            simulated = simulated_balances.get(str(provider_code or "").strip().lower())
            if simulated is not None:
                return float(simulated)
    ttl = max(0, int(getattr(settings_obj, "numbers_provider_balance_cache_ttl_sec", 90) or 0))
    now_ts = time.time()
    cached_entry: dict[str, Any] | None = None
    if provider_name and ttl > 0:
        cached = balance_cache.get(provider_name)
        if isinstance(cached, dict):
            cached_entry = cached
            ts = float(cached.get("ts") or 0.0)
            if (now_ts - ts) <= float(ttl):
                return _extract_balance_value(cached.get("value"))
    if not hasattr(provider_obj, "get_balance"):
        return None
    if timeout_sec in (None, ""):
        timeout_value = 8.0
    else:
        try:
            timeout_value = max(0.5, float(timeout_sec))
        except (TypeError, ValueError):
            timeout_value = 8.0
    try:
        raw_balance = await asyncio.wait_for(provider_obj.get_balance(), timeout=timeout_value)
    except Exception:
        return _extract_balance_value((cached_entry or {}).get("value"))
    if provider_name and ttl > 0:
        balance_cache[provider_name] = {"ts": now_ts, "value": raw_balance}
    parsed_balance = _extract_balance_value(raw_balance)
    if parsed_balance is None:
        return _extract_balance_value((cached_entry or {}).get("value"))
    return parsed_balance
