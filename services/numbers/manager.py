import asyncio
import copy
import logging
import time
from typing import Any

from rapidfuzz import process, fuzz

from config import settings
from database.numbers_config_repo import get_numbers_markup_percent
from database import temp_number_stats_repo
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.data import smspool_services, telabot_services, textverified_services
from services.numbers.providers.herosms_provider import HeroSMSProvider
from services.numbers.providers.error_normalizer import normalize_provider_error
from services.numbers.providers.smsman_provider import SMSManProvider
from services.numbers.providers.smspool_provider import SMSPoolProvider
from services.numbers.providers.telabot_provider import TelabotProvider
from services.numbers.providers.textverified_provider import TextVerifiedProvider
from services.numbers.service_families import normalize_service_key
from services.numbers.service_map import SERVICE_MAP
from utils.beta_mode import beta_mode_enabled, beta_numbers_markup_percent

logger = logging.getLogger("numbers_manager")

PROVIDERS: dict[str, Any] = {
    "smspool": SMSPoolProvider(),
    "telabot": TelabotProvider(),
    "textverified": TextVerifiedProvider(),
    "herosms": HeroSMSProvider(),
    "smsman": SMSManProvider(),
}

RENTAL_PROVIDER_CODES: tuple[str, ...] = ("smspool", "herosms", "textverified")
RENTAL_UNLIMITED_SERVICE_KEY = "rental_unlimited"
# backward compatibility alias
SMSPOOL_OPEN_RENTAL_SERVICE_KEY = RENTAL_UNLIMITED_SERVICE_KEY
UNLIMITED_RENTAL_ALLOWED_ISO: frozenset[str] = frozenset({"US", "CA", "GB"})

PROVIDER_CAPABILITIES: dict[str, dict[str, Any]] = {
    "herosms": {
        "supports_temp": True,
        "supports_rental": True,
        "supports_unlimited_rental": False,
        "supports_state_temp": False,
        "supports_state_rental": False,
    },
    "textverified": {
        "supports_temp": True,
        "supports_rental": True,
        "supports_unlimited_rental": True,
        "supports_state_temp": True,
        "supports_state_rental": True,
    },
    "smspool": {
        "supports_temp": True,
        "supports_rental": False,
        "supports_unlimited_rental": True,
        "supports_state_temp": True,
        "supports_state_rental": False,
    },
    "telabot": {
        "supports_temp": True,
        "supports_rental": False,
        "supports_unlimited_rental": False,
        "supports_state_temp": True,
        "supports_state_rental": False,
    },
    "smsman": {
        "supports_temp": True,
        "supports_rental": False,
        "supports_unlimited_rental": False,
        "supports_state_temp": False,
        "supports_state_rental": False,
    },
}

_PRICE_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_RENTAL_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_MARKUP_CACHE: dict[str, Any] = {"value": None, "ts": 0.0}
_PROVIDER_BALANCE_CACHE: dict[str, dict[str, Any]] = {}
_COUNTRY_ISO_BY_CODE = {
    str(item.get("code") or "").strip(): str(item.get("iso") or "").strip().upper()
    for item in COUNTRIES_LIST
    if str(item.get("code") or "").strip()
}


def _cache_ttl_sec(kind: str) -> int:
    if kind == "rental":
        return max(0, int(getattr(settings, "numbers_rental_cache_ttl_sec", 90) or 0))
    return max(0, int(getattr(settings, "numbers_price_cache_ttl_sec", 60) or 0))


def _cache_stale_sec(kind: str) -> int:
    if kind == "rental":
        return max(0, int(getattr(settings, "numbers_rental_cache_stale_fallback_sec", 900) or 0))
    return max(0, int(getattr(settings, "numbers_price_cache_stale_fallback_sec", 600) or 0))


def _cache_enabled() -> bool:
    return bool(getattr(settings, "numbers_price_cache_enabled", True))


def _provider_timeout_sec(kind: str, provider_code: str | None = None) -> float:
    if kind == "rental":
        base = float(getattr(settings, "numbers_rental_provider_timeout_sec", 10.0) or 10.0)
        # Keep rental UI responsive: cap long waits unless explicitly overridden very low.
        base = min(base, 7.0)
        # TextVerified rental pricing can block UI when API slows down; keep tighter timeout.
        if str(provider_code or "").strip().lower() == "textverified":
            tv_override = getattr(settings, "numbers_textverified_rental_timeout_sec", None)
            if tv_override not in (None, ""):
                try:
                    return max(3.0, float(tv_override))
                except Exception:
                    pass
            return max(3.0, min(base, 5.0))
        return max(3.0, base)
    base = float(getattr(settings, "numbers_provider_timeout_sec", 12.0) or 12.0)
    return max(3.0, base)


def _country_iso_value(country_value: str | None) -> str:
    raw = str(country_value or "").strip()
    if not raw:
        return ""
    if len(raw) == 2 and raw.isalpha():
        return raw.upper()
    return _COUNTRY_ISO_BY_CODE.get(raw, raw.upper())


def get_provider_capabilities(provider_code: str | None) -> dict[str, Any]:
    code = str(provider_code or "").strip().lower()
    return dict(PROVIDER_CAPABILITIES.get(code) or {})


def provider_supports_temp(provider_code: str | None) -> bool:
    return bool(get_provider_capabilities(provider_code).get("supports_temp"))


def provider_supports_rental(provider_code: str | None) -> bool:
    return bool(get_provider_capabilities(provider_code).get("supports_rental"))


def provider_supports_unlimited_rental(provider_code: str | None) -> bool:
    return bool(get_provider_capabilities(provider_code).get("supports_unlimited_rental"))


def provider_allows_temp(provider_code: str | None, *, state_selected: bool = False) -> bool:
    caps = get_provider_capabilities(provider_code)
    if not caps.get("supports_temp"):
        return False
    if state_selected and not caps.get("supports_state_temp", False):
        return False
    return True


def provider_allows_rental(
    provider_code: str | None,
    *,
    service_key: str | None,
    country_iso: str | None = None,
    state_selected: bool = False,
) -> bool:
    caps = get_provider_capabilities(provider_code)
    if _is_unlimited_rental_service(str(service_key or "")):
        if _country_iso_value(country_iso) not in UNLIMITED_RENTAL_ALLOWED_ISO:
            return False
        return bool(caps.get("supports_unlimited_rental"))
    if state_selected and not caps.get("supports_state_rental", False):
        return False
    return bool(caps.get("supports_rental"))


async def _effective_numbers_markup_percent() -> float:
    if beta_mode_enabled():
        return beta_numbers_markup_percent(10.0)
    if not bool(getattr(settings, "profit_policy_enabled", True)):
        return 0.0
    now = time.time()
    try:
        ttl = max(5, int(getattr(settings, "numbers_markup_cache_ttl_sec", 60) or 60))
    except Exception:
        ttl = 60
    cached_val = _MARKUP_CACHE.get("value")
    cached_ts = float(_MARKUP_CACHE.get("ts") or 0.0)
    if cached_val is not None and (now - cached_ts) <= float(ttl):
        try:
            value = float(cached_val)
            return max(0.0, value)
        except Exception:
            pass
    default_markup = float(getattr(settings, "numbers_service_markup_percent", 25.0) or 25.0)
    try:
        value = await get_numbers_markup_percent(default_markup)
    except Exception:
        value = default_markup
    value = max(0.0, float(value))
    _MARKUP_CACHE["value"] = value
    _MARKUP_CACHE["ts"] = now
    return value


def _success_rate_enabled() -> bool:
    return bool(getattr(settings, "numbers_success_rate_enabled", True))


def _success_rate_lookback_days() -> int:
    return max(1, int(getattr(settings, "numbers_success_rate_lookback_days", 14) or 14))


def _success_rate_min_attempts() -> int:
    return max(1, int(getattr(settings, "numbers_success_rate_min_attempts", 3) or 3))


def _success_rate_default() -> float:
    try:
        value = float(getattr(settings, "numbers_success_rate_default_percent", 100.0) or 100.0)
    except Exception:
        value = 100.0
    return max(0.0, min(100.0, value))


def _cache_read(
    cache: dict[tuple[Any, ...], dict[str, Any]],
    key: tuple[Any, ...],
    *,
    ttl_sec: int,
    stale_sec: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    entry = cache.get(key)
    if not isinstance(entry, dict):
        return None, None
    ts = float(entry.get("ts") or 0.0)
    value = entry.get("value")
    if not isinstance(value, dict):
        return None, None
    age = max(0.0, time.time() - ts)
    fresh = copy.deepcopy(value) if age <= float(ttl_sec) else None
    stale = copy.deepcopy(value) if age <= float(stale_sec) else None
    return fresh, stale


def _cache_write(cache: dict[tuple[Any, ...], dict[str, Any]], key: tuple[Any, ...], value: dict[str, Any]) -> None:
    cache[key] = {"ts": time.time(), "value": copy.deepcopy(value)}


async def _apply_dynamic_success_rates(results: dict[str, Any], service_id: str) -> None:
    if not results or not _success_rate_enabled():
        return
    providers = [str(code or "").strip().lower() for code in results.keys() if str(code or "").strip()]
    if not providers:
        return
    try:
        stats = await temp_number_stats_repo.get_provider_success_rates(
            service_id=str(service_id or "").strip(),
            providers=providers,
            lookback_days=_success_rate_lookback_days(),
            min_attempts=_success_rate_min_attempts(),
            default_rate=_success_rate_default(),
        )
    except Exception:
        logger.exception("failed to compute provider success rates: service=%s", service_id)
        return

    default_rate = _success_rate_default()
    for provider_code, info in results.items():
        if not isinstance(info, dict):
            continue
        provider = str(provider_code or "").strip().lower()
        row = stats.get(provider) or {}
        try:
            rate_value = float(row.get("success_rate", default_rate))
        except Exception:
            rate_value = default_rate
        info["success_rate"] = max(0.0, min(100.0, rate_value))
        info["success_attempts"] = int(row.get("attempts") or 0)
        info["success_sample_sufficient"] = bool(row.get("sample_sufficient"))


def _normalize_key(value: str) -> str:
    return normalize_service_key(value)


def _is_unlimited_rental_service(service_key: str) -> bool:
    return _normalize_key(service_key) == _normalize_key(RENTAL_UNLIMITED_SERVICE_KEY)


def _fuzzy_match(target: str, candidates: list[str], threshold: float = 80) -> str | None:
    if not candidates:
        return None
    match = process.extractOne(
        str(target or ""),
        candidates,
        scorer=fuzz.ratio,
    )
    if match and float(match[1]) >= float(threshold):
        return str(match[0])
    return None


def _service_display_name(service_key: str) -> str | None:
    entry = SERVICE_MAP.get(_normalize_key(service_key))
    if not entry:
        return None
    name = entry.get("display_name")
    return str(name) if name else None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _extract_balance_value(raw_balance: Any) -> float | None:
    if raw_balance is None:
        return None
    if isinstance(raw_balance, (int, float, str)):
        return _to_float(raw_balance)
    if isinstance(raw_balance, dict):
        for key in ("balance", "currentBalance", "available", "amount", "value"):
            if key in raw_balance:
                parsed = _to_float(raw_balance.get(key))
                if parsed is not None:
                    return parsed
        # Telabot balance payload: {"status":"ok","message":"0.14"}
        if "message" in raw_balance:
            parsed = _to_float(raw_balance.get("message"))
            if parsed is not None:
                return parsed
    return None


async def _provider_balance(provider_obj: Any) -> float | None:
    provider_name = str(getattr(provider_obj, "__class__", type("X", (), {})).__name__ or "").lower()
    ttl = max(0, int(getattr(settings, "numbers_provider_balance_cache_ttl_sec", 90) or 0))
    now_ts = time.time()
    if provider_name and ttl > 0:
        cached = _PROVIDER_BALANCE_CACHE.get(provider_name)
        if isinstance(cached, dict):
            ts = float(cached.get("ts") or 0.0)
            if (now_ts - ts) <= float(ttl):
                return _extract_balance_value(cached.get("value"))
    if not hasattr(provider_obj, "get_balance"):
        return None
    try:
        raw_balance = await asyncio.wait_for(provider_obj.get_balance(), timeout=8.0)
    except Exception:
        return None
    if provider_name and ttl > 0:
        _PROVIDER_BALANCE_CACHE[provider_name] = {"ts": now_ts, "value": raw_balance}
    return _extract_balance_value(raw_balance)


async def get_provider_service_name_dynamic(service_key: str, provider_code: str):
    """Resolve the provider-side service identifier for a generic service key."""
    raw = service_key or ""
    norm_target = _normalize_key(raw)

    try:
        if provider_code == "smspool":
            # Prefer runtime provider catalog first (tests and live refreshes patch this list).
            names = [item.get("name", "") for item in smspool_services.DATA if item.get("name")]
            for item in smspool_services.DATA:
                name = item.get("name", "")
                if _normalize_key(name) == norm_target:
                    return str(item.get("ID"))
            fuzzy = _fuzzy_match(raw, names)
            if fuzzy:
                for item in smspool_services.DATA:
                    if item.get("name") == fuzzy:
                        return str(item.get("ID"))
            mapped = SERVICE_MAP.get(norm_target, {}).get("providers", {}).get("smspool")
            if mapped not in (None, ""):
                return str(mapped)
            return None

        if provider_code == "telabot":
            data = telabot_services.DATA
            if isinstance(data, dict) and "message" in data:
                names = [it.get("name", "") for it in data.get("message", []) if it.get("name")]
            elif isinstance(data, dict):
                names = list(data.keys())
            else:
                names = []

            for n in names:
                if _normalize_key(n) == norm_target:
                    return n
            return _fuzzy_match(raw, names)

        if provider_code == "textverified":
            names = [it.get("serviceName", "") for it in textverified_services.DATA if it.get("serviceName")]
            for n in names:
                if _normalize_key(n) == norm_target:
                    return n
            fuzzy = _fuzzy_match(raw, names)
            if fuzzy:
                return fuzzy

            prov = PROVIDERS.get("textverified")
            if prov and hasattr(prov, "list_services"):
                try:
                    live = await prov.list_services()
                    if isinstance(live, list):
                        live_names = [it.get("serviceName", "") for it in live if it.get("serviceName")]
                        for n in live_names:
                            if _normalize_key(n) == norm_target:
                                return n
                        return _fuzzy_match(raw, live_names)
                except Exception:
                    pass
            return None

        if provider_code == "herosms":
            mapped = SERVICE_MAP.get(norm_target, {}).get("providers", {}).get("herosms")
            if mapped:
                return str(mapped)

            prov = PROVIDERS.get("herosms")
            if not prov:
                return None

            candidates = [raw]
            display_name = _service_display_name(raw)
            if display_name and display_name not in candidates:
                candidates.append(display_name)

            for candidate in candidates:
                try:
                    if hasattr(prov, "resolve_service_code"):
                        code = await prov.resolve_service_code(candidate)
                        if code:
                            return str(code)
                except Exception:
                    continue

            return None

        if provider_code == "smsman":
            mapped = SERVICE_MAP.get(norm_target, {}).get("providers", {}).get("smsman")
            if mapped:
                return str(mapped)

            prov = PROVIDERS.get("smsman")
            if not prov:
                return None

            candidates = [raw]
            display_name = _service_display_name(raw)
            if display_name and display_name not in candidates:
                candidates.append(display_name)

            for candidate in candidates:
                try:
                    if hasattr(prov, "resolve_service_code"):
                        code = await prov.resolve_service_code(candidate)
                        if code:
                            return str(code)
                except Exception:
                    continue

            return None
    except Exception as e:
        logger.warning("Error reading provider data for %s: %s", provider_code, e)

    return None


async def get_all_prices(service_key: str, country: str | None, state: str | None):
    """Fetch temporary-number prices from all configured providers."""
    results = {}
    markup_pct = await _effective_numbers_markup_percent()
    show_all_for_testing = bool(getattr(settings, "numbers_show_all_providers_for_testing", False))
    state_selected = bool(state and str(state).strip().lower() != "none")
    async def fetch_single_provider(code, provider_obj):
        try:
            if not provider_allows_temp(code, state_selected=state_selected):
                return (code, None)

            api_service_name = await get_provider_service_name_dynamic(service_key, code)
            if not api_service_name:
                if show_all_for_testing:
                    return (
                        code,
                        {
                            "success": False,
                            "price": 0.0,
                            "base_price": 0.0,
                            "api_service_name": "",
                            "success_rate": 100.0,
                            "testing_visible": True,
                            "available_for_buy": False,
                            "provider_reason": "service_not_supported",
                        },
                    )
                return (code, None)

            c_code = str(country) if country and country != "none" else None
            s_code = str(state) if state and state != "none" else None

            price_data = await asyncio.wait_for(
                provider_obj.get_price(api_service_name, c_code, s_code),
                timeout=_provider_timeout_sec("temp", code),
            )

            if price_data and price_data.get("success"):
                try:
                    base_price = float(price_data.get("price") or 0.0)
                except Exception:
                    base_price = 0.0
                if base_price <= 0:
                    if show_all_for_testing:
                        return (
                            code,
                            {
                                "success": False,
                                "price": 0.0,
                                "base_price": 0.0,
                                "api_service_name": api_service_name,
                                "success_rate": 100.0,
                                "testing_visible": True,
                                "available_for_buy": False,
                                "provider_reason": "invalid_price",
                            },
                        )
                    return (code, None)

                provider_balance = await _provider_balance(provider_obj)
                if provider_balance is None:
                    # Safety-first: if provider balance cannot be verified, hide it in production
                    # to avoid showing providers that may fail at purchase time.
                    if not show_all_for_testing:
                        return (code, None)
                    price_data["testing_visible"] = True
                    price_data["provider_reason"] = "provider_balance_unknown"
                if provider_balance is not None and provider_balance + 1e-9 < base_price:
                    # Hide provider when its account cannot currently buy this service.
                    if not show_all_for_testing:
                        return (code, None)

                sale_price = base_price
                if base_price > 0 and markup_pct > 0:
                    sale_price = round(base_price * (1.0 + markup_pct / 100.0), 4)
                price_data["base_price"] = base_price
                price_data["price"] = sale_price
                price_data["api_service_name"] = api_service_name
                price_data["available_for_buy"] = True
                if provider_balance is not None:
                    price_data["provider_balance"] = float(provider_balance)
                    if provider_balance + 1e-9 < base_price:
                        price_data["testing_visible"] = True
                        price_data["provider_reason"] = "provider_balance_low"
                return (code, price_data)
            if show_all_for_testing:
                normalized = normalize_provider_error(price_data.get("raw") if isinstance(price_data, dict) else price_data)
                return (
                    code,
                    {
                        "success": False,
                        "price": 0.0,
                        "base_price": 0.0,
                        "api_service_name": api_service_name,
                        "success_rate": 100.0,
                        "testing_visible": True,
                        "available_for_buy": False,
                        "provider_reason": normalized.get("code", "price_unavailable"),
                        "provider_reason_message": normalized.get("message", ""),
                    },
                )
        except Exception as e:
            logger.warning("Provider %s price fetch failed: %s", code, e)
            if show_all_for_testing:
                normalized = normalize_provider_error(str(e))
                return (
                    code,
                    {
                        "success": False,
                        "price": 0.0,
                        "base_price": 0.0,
                        "api_service_name": "",
                        "success_rate": 100.0,
                        "testing_visible": True,
                        "available_for_buy": False,
                        "provider_reason": normalized.get("code", "price_fetch_failed"),
                        "provider_reason_message": normalized.get("message", ""),
                    },
                )
        return (code, None)

    tasks = [fetch_single_provider(code, p) for code, p in PROVIDERS.items()]
    responses = await asyncio.gather(*tasks)

    for code, data in responses:
        if data:
            results[code] = data
    if results:
        await _apply_dynamic_success_rates(results, str(service_key or ""))
    return results


async def get_all_rental_prices(service_key: str, country: str | None):
    """Fetch rental options from providers that support rental APIs."""
    results = {}
    is_unlimited = _is_unlimited_rental_service(service_key)
    show_all_for_testing = bool(getattr(settings, "numbers_show_all_providers_for_testing", False))
    async def fetch_single_provider(code: str, provider_obj):
        if code not in RENTAL_PROVIDER_CODES:
            return (code, None)
        if not hasattr(provider_obj, "get_rental_prices"):
            if show_all_for_testing:
                return (
                    code,
                    {
                        "success": False,
                        "options": [],
                        "api_service_name": "",
                        "available_for_buy": False,
                        "testing_visible": True,
                        "provider_reason": "rental_not_supported",
                    },
                )
            return (code, None)
        try:
            if not provider_allows_rental(
                code,
                service_key=service_key,
                country_iso=str(country or "").strip().upper(),
            ):
                return (code, None)
            if is_unlimited:
                if code == "smspool":
                    api_service_name = RENTAL_UNLIMITED_SERVICE_KEY
                elif code == "textverified":
                    # TextVerified "All Services" rental SKU (unlimited-style line).
                    api_service_name = "allservices"
                else:
                    return (code, None)
            else:
                api_service_name = await get_provider_service_name_dynamic(service_key, code)
                if not api_service_name:
                    if show_all_for_testing:
                        return (
                            code,
                            {
                                "success": False,
                                "options": [],
                                "api_service_name": "",
                                "available_for_buy": False,
                                "testing_visible": True,
                                "provider_reason": "service_not_supported",
                            },
                        )
                    return (code, None)
            c_code = str(country) if country and country != "none" else None
            rent_data = await asyncio.wait_for(
                provider_obj.get_rental_prices(api_service_name, country=c_code),
                timeout=_provider_timeout_sec("rental", code),
            )
            if not rent_data or not rent_data.get("success") or not rent_data.get("options"):
                if show_all_for_testing:
                    return (
                        code,
                        {
                            "success": False,
                            "options": [],
                            "api_service_name": api_service_name,
                            "available_for_buy": False,
                            "testing_visible": True,
                            "provider_reason": "provider_no_options",
                            "raw": rent_data,
                        },
                    )
                return (code, None)
            if rent_data and rent_data.get("success") and rent_data.get("options"):
                options = [row for row in (rent_data.get("options") or []) if isinstance(row, dict)]
                min_provider_price = None
                for row in options:
                    try:
                        raw_price = float(row.get("price") or 0.0)
                    except Exception:
                        raw_price = 0.0
                    if raw_price <= 0:
                        continue
                    if min_provider_price is None or raw_price < min_provider_price:
                        min_provider_price = raw_price

                provider_balance = await _provider_balance(provider_obj)
                if provider_balance is None and not show_all_for_testing:
                    return (code, None)
                if (
                    provider_balance is not None
                    and min_provider_price is not None
                    and provider_balance + 1e-9 < float(min_provider_price)
                    and not show_all_for_testing
                ):
                    return (code, None)

                markup_pct = await _effective_numbers_markup_percent()
                if markup_pct > 0:
                    enriched_options = []
                    for option in (rent_data.get("options") or []):
                        if not isinstance(option, dict):
                            enriched_options.append(option)
                            continue
                        row = dict(option)
                        try:
                            base_price = float(row.get("price") or 0.0)
                        except Exception:
                            base_price = 0.0
                        row["base_price"] = base_price
                        row["price"] = round(base_price * (1.0 + markup_pct / 100.0), 4) if base_price > 0 else base_price
                        enriched_options.append(row)
                    rent_data["options"] = enriched_options
                rent_data["api_service_name"] = api_service_name
                rent_data["available_for_buy"] = True
                if provider_balance is not None:
                    rent_data["provider_balance"] = float(provider_balance)
                    if min_provider_price is not None and provider_balance + 1e-9 < float(min_provider_price):
                        rent_data["available_for_buy"] = False
                        rent_data["provider_reason"] = "provider_balance_low"
                elif show_all_for_testing:
                    rent_data["available_for_buy"] = False
                    rent_data["provider_reason"] = "provider_balance_unknown"
                    rent_data["testing_visible"] = True
                return (code, rent_data)
        except asyncio.TimeoutError:
            logger.warning("Provider %s rental price fetch timed out", code)
            if show_all_for_testing:
                return (
                    code,
                    {
                        "success": False,
                        "options": [],
                        "api_service_name": "",
                        "available_for_buy": False,
                        "testing_visible": True,
                        "provider_reason": "provider_timeout",
                    },
                )
        except Exception as e:
            logger.warning("Provider %s rental price fetch failed: %s (%r)", code, type(e).__name__, e)
            if show_all_for_testing:
                return (
                    code,
                    {
                        "success": False,
                        "options": [],
                        "api_service_name": "",
                        "available_for_buy": False,
                        "testing_visible": True,
                        "provider_reason": "provider_error",
                        "raw": str(e),
                    },
                )
        return (code, None)

    tasks = [fetch_single_provider(code, PROVIDERS[code]) for code in RENTAL_PROVIDER_CODES if code in PROVIDERS]
    responses = await asyncio.gather(*tasks)
    for code, data in responses:
        if data:
            results[code] = data
    if results:
        await _apply_dynamic_success_rates(results, f"{str(service_key or '')}:rental")
    return results


async def buy_number_from_provider(
    provider_code: str,
    api_service_name: str,
    country: str | None,
    state: str | None,
    dry_run: bool = False,
    purchase_options: dict[str, Any] | None = None,
):
    provider = PROVIDERS.get(provider_code)
    if not provider:
        raise ValueError(f"Invalid provider code: {provider_code}")

    if dry_run:
        try:
            price_data = await asyncio.wait_for(provider.get_price(api_service_name, country, state), timeout=10.0)
            if not price_data or not price_data.get("success"):
                raise ValueError("Failed to fetch price from provider.")
            return price_data.get("price")
        except asyncio.TimeoutError:
            raise ValueError("Provider price request timed out.")

    opts = purchase_options if isinstance(purchase_options, dict) else {}
    try:
        result = await provider.buy_number(api_service_name, country, state, **opts)
        if isinstance(result, dict) and not bool(result.get("success")):
            raw = result.get("raw")
            result.setdefault("normalized_error", normalize_provider_error(raw))
        return result
    except TypeError:
        # Backward compatibility for providers that do not accept extra kwargs.
        result = await provider.buy_number(api_service_name, country, state)
        if isinstance(result, dict) and not bool(result.get("success")):
            raw = result.get("raw")
            result.setdefault("normalized_error", normalize_provider_error(raw))
        return result


async def rent_number_from_provider(
    provider_code: str,
    api_service_name: str,
    country: str,
    duration: int,
    option_meta: dict[str, Any] | None = None,
):
    provider = PROVIDERS.get(provider_code)
    if not provider:
        raise ValueError(f"Invalid provider code: {provider_code}")
    if not hasattr(provider, "rent_number"):
        raise ValueError(f"Provider does not support rental: {provider_code}")
    provider_kwargs: dict[str, Any] = {}
    if isinstance(option_meta, dict):
        for key in (
            "rental_id",
            "duration_days",
            "country_name",
            "tv_with_state",
            "state_code",
            "tv_duration_key",
            "tv_is_renewable",
        ):
            value = option_meta.get(key)
            if value not in (None, ""):
                provider_kwargs[key] = value
    return await provider.rent_number(
        api_service_name,
        country=country,
        duration=int(duration),
        **provider_kwargs,
    )


async def get_rental_sms_from_provider(provider_code: str, activation_id: str):
    provider = PROVIDERS.get(provider_code)
    if not provider:
        raise ValueError(f"Invalid provider code: {provider_code}")

    if hasattr(provider, "get_rental_sms"):
        return await provider.get_rental_sms(activation_id)
    return await provider.get_sms(activation_id)


async def get_rental_info_from_provider(provider_code: str, activation_id: str):
    provider = PROVIDERS.get(provider_code)
    if not provider:
        raise ValueError(f"Invalid provider code: {provider_code}")
    if hasattr(provider, "get_rental_info"):
        return await provider.get_rental_info(activation_id)
    return {"success": False, "raw": "rental_info_not_supported"}


async def finish_rental_from_provider(provider_code: str, activation_id: str):
    provider = PROVIDERS.get(provider_code)
    if not provider:
        raise ValueError(f"Invalid provider code: {provider_code}")
    if hasattr(provider, "finish_rental"):
        return await provider.finish_rental(activation_id)
    if hasattr(provider, "cancel"):
        return await provider.cancel(activation_id)
    return {"success": False, "raw": "finish_not_supported"}


async def renew_rental_from_provider(provider_code: str, activation_id: str):
    provider = PROVIDERS.get(provider_code)
    if not provider:
        raise ValueError(f"Invalid provider code: {provider_code}")
    if hasattr(provider, "renew_rental"):
        return await provider.renew_rental(activation_id)
    return {"success": False, "raw": "renew_not_supported"}


async def wake_rental_from_provider(provider_code: str, activation_id: str):
    provider = PROVIDERS.get(provider_code)
    if not provider:
        raise ValueError(f"Invalid provider code: {provider_code}")
    if hasattr(provider, "wake_rental"):
        return await provider.wake_rental(activation_id)
    return {"success": False, "raw": "wake_not_supported"}


async def notes_tags_from_provider(provider_code: str, activation_id: str):
    provider = PROVIDERS.get(provider_code)
    if not provider:
        raise ValueError(f"Invalid provider code: {provider_code}")
    if hasattr(provider, "get_rental_notes_tags"):
        return await provider.get_rental_notes_tags(activation_id)
    return {"success": False, "raw": "notes_not_supported"}
