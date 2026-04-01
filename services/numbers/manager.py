import asyncio
import json
import logging
import time
from typing import Any

from config import settings
from database import temp_number_stats_repo
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.data import smspool_services, telabot_services, textverified_services
from services.numbers.providers.herosms_provider import HeroSMSProvider
from services.numbers.providers.error_normalizer import normalize_provider_error
from services.numbers.providers.smsman_provider import SMSManProvider
from services.numbers.providers.smspool_provider import SMSPoolProvider
from services.numbers.providers.telabot_provider import TelabotProvider
from services.numbers.providers.textverified_provider import TextVerifiedProvider
from services.numbers.providers.pvadeals_provider import PVADealsProvider
from services.numbers.providers.alisms_provider import AliSMSProvider
from services.numbers.service_families import (
    normalize_service_key,
)
from services.numbers.service_map import (
    SERVICE_MAP,
    get_service_aliases,
    get_service_display_name,
    get_service_provider_map,
    resolve_canonical_service_key,
)

logger = logging.getLogger("numbers_manager")

_SMSMAN_PROVIDER = SMSManProvider()

PROVIDERS: dict[str, Any] = {
    "smspool": SMSPoolProvider(),
    "telabot": TelabotProvider(),
    "textverified": TextVerifiedProvider(),
    "herosms": HeroSMSProvider(),
    "smsman": _SMSMAN_PROVIDER,
    "pvadeals": PVADealsProvider(),
    "alisms": AliSMSProvider(),
    # Virtual second lane for the same backend provider (second-best offer).
    "smsman_s6": _SMSMAN_PROVIDER,
}

RENTAL_PROVIDER_CODES: tuple[str, ...] = ("smspool", "herosms", "textverified", "pvadeals")
RENTAL_UNLIMITED_SERVICE_KEY = "rental_unlimited"
# backward compatibility alias
SMSPOOL_OPEN_RENTAL_SERVICE_KEY = RENTAL_UNLIMITED_SERVICE_KEY
UNLIMITED_RENTAL_ALLOWED_ISO: frozenset[str] = frozenset({"US", "CA", "GB"})
UNLIMITED_RENTAL_PROVIDER_SERVICE_NAMES: dict[str, str] = {
    "smspool": RENTAL_UNLIMITED_SERVICE_KEY,
    "textverified": "allservices",
    "pvadeals": "Website not in the list (Unknown)",
}

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
    "pvadeals": {
        "supports_temp": True,
        "supports_rental": True,
        "supports_unlimited_rental": True,
        "supports_state_temp": False,
        "supports_state_rental": False,
    },
    "alisms": {
        "supports_temp": True,
        "supports_rental": False,
        "supports_unlimited_rental": False,
        "supports_state_temp": False,
        "supports_state_rental": False,
    },
    "smsman_s6": {
        "supports_temp": True,
        "supports_rental": False,
        "supports_unlimited_rental": False,
        "supports_state_temp": False,
        "supports_state_rental": False,
    },
}

_PROVIDER_BALANCE_CACHE: dict[str, dict[str, Any]] = {}
_SERVICE_RESOLUTION_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_PROVIDER_SERVICE_LIST_CACHE: dict[str, dict[str, Any]] = {}
_COUNTRY_ISO_BY_CODE = {
    str(item.get("code") or "").strip(): str(item.get("iso") or "").strip().upper()
    for item in COUNTRIES_LIST
    if str(item.get("code") or "").strip()
}
_COUNTRY_NAME_TO_ISO = {
    str(item.get("name") or "").strip().lower(): str(item.get("iso") or "").strip().upper()
    for item in COUNTRIES_LIST
    if str(item.get("name") or "").strip()
}


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


def _price_screen_provider_timeout_sec(provider_code: str | None = None) -> float:
    explicit = getattr(settings, "numbers_price_screen_provider_timeout_sec", None)
    if explicit not in (None, ""):
        try:
            return max(1.0, float(explicit))
        except Exception:
            pass
    return max(1.0, min(_provider_timeout_sec("temp", provider_code), 5.5))


def _service_resolution_timeout_sec(provider_code: str | None = None) -> float:
    explicit = getattr(settings, "numbers_service_resolution_timeout_sec", None)
    if explicit not in (None, ""):
        try:
            return max(0.5, float(explicit))
        except Exception:
            pass
    code = str(provider_code or "").strip().lower()
    if code == "textverified":
        return 2.5
    return 2.0


def _provider_service_catalog_cache_ttl_sec() -> int:
    try:
        return max(0, int(getattr(settings, "numbers_provider_service_catalog_cache_ttl_sec", 900) or 900))
    except Exception:
        return 900


async def _provider_list_services_cached(provider_code: str, provider_obj: Any) -> Any:
    if not hasattr(provider_obj, "list_services"):
        return []
    provider_code = str(provider_code or "").strip().lower()
    ttl = _provider_service_catalog_cache_ttl_sec()
    now_ts = time.time()
    cached_entry = _PROVIDER_SERVICE_LIST_CACHE.get(provider_code) if ttl > 0 else None
    if isinstance(cached_entry, dict):
        cached_ts = float(cached_entry.get("ts") or 0.0)
        if (now_ts - cached_ts) <= float(ttl):
            return cached_entry.get("value")
    try:
        live = await asyncio.wait_for(
            provider_obj.list_services(),
            timeout=_service_resolution_timeout_sec(provider_code),
        )
    except Exception:
        if isinstance(cached_entry, dict):
            return cached_entry.get("value")
        return []
    if ttl > 0:
        _PROVIDER_SERVICE_LIST_CACHE[provider_code] = {"ts": now_ts, "value": live}
    return live


async def _provider_resolve_service_code_with_timeout(provider_code: str, provider_obj: Any, candidate: str) -> str | None:
    if not hasattr(provider_obj, "resolve_service_code"):
        return None
    try:
        result = await asyncio.wait_for(
            provider_obj.resolve_service_code(candidate),
            timeout=_service_resolution_timeout_sec(provider_code),
        )
    except Exception:
        return None
    if result in (None, ""):
        return None
    return str(result)


def _country_iso_value(country_value: str | None) -> str:
    raw = str(country_value or "").strip()
    if not raw:
        return ""
    normalized = raw.lower().replace(" ", "")
    if normalized in {"us", "usa", "unitedstates", "unitedstatesofamerica"}:
        return "US"
    if normalized in {"gb", "uk", "unitedkingdom", "greatbritain"}:
        return "GB"
    if len(raw) == 2 and raw.isalpha():
        return raw.upper()
    if raw in _COUNTRY_ISO_BY_CODE:
        return _COUNTRY_ISO_BY_CODE.get(raw, "").upper()
    by_name = _COUNTRY_NAME_TO_ISO.get(raw.lower())
    if by_name:
        return by_name
    return raw.upper()


def _price_match(value: Any, expected: float | None) -> bool:
    try:
        actual = float(value)
        target = float(expected)
    except Exception:
        return False
    return abs(actual - target) <= 1e-9


def _extract_provider_location(
    provider_code: str,
    *,
    api_service_name: str | None,
    price_data: dict[str, Any],
) -> tuple[str, str]:
    code = str(provider_code or "").strip().lower()
    state_code = str(price_data.get("provider_state") or price_data.get("provider_state_code") or "").strip().upper()
    country_iso = _country_iso_value(
        str(
            price_data.get("provider_country_iso")
            or price_data.get("provider_country")
            or ""
        ).strip()
    )
    if state_code or country_iso:
        return state_code, country_iso

    raw = price_data.get("raw")
    base_price = _to_float(price_data.get("base_price") or price_data.get("price"))
    api_name = str(api_service_name or price_data.get("api_service_name") or "").strip()

    if code == "pvadeals" and isinstance(raw, dict):
        return "", _country_iso_value(str(raw.get("country") or "").strip())

    if code == "smspool" and isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            if str(row.get("service") or "").strip() != api_name:
                continue
            if not _price_match(row.get("price"), base_price):
                continue
            iso = _country_iso_value(
                str(
                    row.get("short_name")
                    or row.get("country")
                    or row.get("country_name")
                    or row.get("name")
                    or row.get("tag")
                    or ""
                ).strip()
            )
            if iso:
                return "", iso

    if code == "alisms" and isinstance(raw, dict):
        service_block = next((value for value in raw.values() if isinstance(value, dict)), None)
        if isinstance(service_block, dict) and service_block:
            country_id = next(iter(service_block.keys()), "")
            iso = _country_iso_value(str(country_id or "").strip())
            if iso:
                return "", iso

    if code in {"textverified", "telabot"}:
        return "", "US"

    return "", ""


def _price_screen_balance_timeout_sec() -> float:
    try:
        value = float(getattr(settings, "numbers_price_screen_balance_timeout_sec", 2.0) or 2.0)
    except Exception:
        value = 2.0
    return max(0.5, value)


def _simulated_provider_balances() -> dict[str, float]:
    raw = str(getattr(settings, "numbers_provider_balance_simulation", "") or "").strip()
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
        except Exception:
            continue
        out[str(key or "").strip().lower()] = amount
    return out


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
    # Single source of truth for numbers pricing markup.
    # Numbers prices are controlled only by NUMBERS_SERVICE_MARKUP_PERCENT.
    try:
        value = float(getattr(settings, "numbers_service_markup_percent", 0.0) or 0.0)
    except Exception:
        value = 0.0
    return max(0.0, float(value))


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


def _service_name_variants(value: str) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    variants = {_normalize_key(raw)}
    for part in raw.replace("|", "/").split("/"):
        part_norm = _normalize_key(part)
        if part_norm:
            variants.add(part_norm)
    return {item for item in variants if item}


def _service_candidate_keys(value: str) -> set[str]:
    canonical = resolve_canonical_service_key(value)
    if not canonical:
        return set()
    keys = {canonical}
    keys.update(get_service_aliases(canonical))
    base = _normalize_key(value)
    if base:
        keys.add(base)
    return {item for item in keys if item}


def _service_matches_name(service_key: str, provider_name: str) -> bool:
    target_keys = set()
    for item in _service_candidate_keys(service_key):
        target_keys.update(_service_name_variants(item))
    name_keys = _service_name_variants(provider_name)
    if not target_keys or not name_keys:
        return False
    return bool(target_keys & name_keys)


def _service_display_name(service_key: str) -> str | None:
    return get_service_display_name(service_key)


def _service_resolution_snapshot(service_key: str, provider_code: str) -> dict[str, Any]:
    canonical = resolve_canonical_service_key(service_key)
    provider_code_norm = str(provider_code or "").strip().lower()
    provider_map = get_service_provider_map(canonical or service_key)
    return {
        "requested_service": str(service_key or ""),
        "canonical_service": canonical,
        "display_name": get_service_display_name(canonical or service_key) or str(service_key or ""),
        "provider_code": provider_code_norm,
        "provider_mapped_value": provider_map.get(provider_code_norm),
        "provider_candidates": sorted(_service_candidate_keys(service_key)),
        "resolved_provider_service": None,
        "provider_reason": "",
    }


def _log_provider_resolution_failure(resolution: dict[str, Any]) -> None:
    logger.info(
        "provider service unresolved provider=%s requested=%s canonical=%s reason=%s candidates=%s",
        resolution.get("provider_code", ""),
        resolution.get("requested_service", ""),
        resolution.get("canonical_service", ""),
        resolution.get("provider_reason", ""),
        ",".join(str(item) for item in (resolution.get("provider_candidates") or [])),
    )


def _log_provider_resolution_event(
    resolution: dict[str, Any],
    *,
    phase: str,
    country: str | None = None,
    state: str | None = None,
) -> None:
    requested = str(resolution.get("requested_service") or "").strip()
    canonical = str(resolution.get("canonical_service") or "").strip()
    resolved = str(resolution.get("resolved_provider_service") or "").strip()
    reason = str(resolution.get("provider_reason") or "").strip()
    provider = str(resolution.get("provider_code") or "").strip().lower()
    display_name = str(resolution.get("display_name") or "").strip()
    candidates = ",".join(str(item) for item in (resolution.get("provider_candidates") or []))
    is_mismatch = bool(resolved) and normalize_service_key(requested) != normalize_service_key(resolved)
    if not is_mismatch and reason not in {"resolved_static_mapping", "resolved_provider_lookup"}:
        return
    logger.info(
        "provider resolution %s provider=%s requested=%s canonical=%s resolved=%s display=%s reason=%s country=%s state=%s candidates=%s mismatch=%s",
        phase,
        provider,
        requested,
        canonical,
        resolved,
        display_name,
        reason,
        str(country or ""),
        str(state or ""),
        candidates,
        is_mismatch,
    )


def _log_provider_attempt_event(
    *,
    phase: str,
    provider_code: str,
    requested_service: str | None,
    api_service_name: str | None,
    country: str | None,
    state: str | None,
    success: bool,
    reason: str | None = None,
    raw: Any = None,
) -> None:
    normalized = normalize_provider_error(raw) if not bool(success) else {"code": "", "message": ""}
    logger.info(
        "provider attempt %s provider=%s requested=%s api_service=%s country=%s state=%s success=%s reason=%s normalized_code=%s normalized_message=%s",
        phase,
        str(provider_code or "").strip().lower(),
        str(requested_service or "").strip(),
        str(api_service_name or "").strip(),
        str(country or ""),
        str(state or ""),
        bool(success),
        str(reason or "").strip(),
        str(normalized.get("code") or ""),
        str(normalized.get("message") or ""),
    )


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
    return await _provider_balance_with_timeout(provider_obj)


async def _provider_balance_with_timeout(provider_obj: Any, *, timeout_sec: float | None = None) -> float | None:
    provider_name = str(getattr(provider_obj, "__class__", type("X", (), {})).__name__ or "").lower()
    simulated_balances = _simulated_provider_balances()
    if provider_name:
        simulated = simulated_balances.get(provider_name)
        if simulated is not None:
            return float(simulated)
    for provider_code, candidate in PROVIDERS.items():
        if candidate is provider_obj:
            simulated = simulated_balances.get(str(provider_code or "").strip().lower())
            if simulated is not None:
                return float(simulated)
    ttl = max(0, int(getattr(settings, "numbers_provider_balance_cache_ttl_sec", 90) or 0))
    now_ts = time.time()
    cached_entry: dict[str, Any] | None = None
    if provider_name and ttl > 0:
        cached = _PROVIDER_BALANCE_CACHE.get(provider_name)
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
        except Exception:
            timeout_value = 8.0
    try:
        raw_balance = await asyncio.wait_for(provider_obj.get_balance(), timeout=timeout_value)
    except Exception:
        return _extract_balance_value((cached_entry or {}).get("value"))
    if provider_name and ttl > 0:
        _PROVIDER_BALANCE_CACHE[provider_name] = {"ts": now_ts, "value": raw_balance}
    parsed_balance = _extract_balance_value(raw_balance)
    if parsed_balance is None:
        return _extract_balance_value((cached_entry or {}).get("value"))
    return parsed_balance


async def get_provider_service_resolution_dynamic(service_key: str, provider_code: str) -> dict[str, Any]:
    """Resolve provider-side service id/name and return diagnostics for failures."""
    raw = str(service_key or "")
    norm_target = _normalize_key(raw)
    provider_code = str(provider_code or "").strip().lower()
    cache_ttl = max(0, int(getattr(settings, "numbers_service_resolution_cache_ttl_sec", 1800) or 1800))
    cache_key = (provider_code, norm_target or raw.lower())
    now_ts = time.time()
    if cache_ttl > 0:
        cached = _SERVICE_RESOLUTION_CACHE.get(cache_key)
        if isinstance(cached, dict):
            cached_ts = float(cached.get("_ts") or 0.0)
            if (now_ts - cached_ts) <= float(cache_ttl):
                return {k: v for k, v in cached.items() if k != "_ts"}
    resolution = _service_resolution_snapshot(raw, provider_code)

    def _cache_and_return(value: dict[str, Any]) -> dict[str, Any]:
        if cache_ttl > 0:
            _SERVICE_RESOLUTION_CACHE[cache_key] = {**value, "_ts": now_ts}
        return value

    try:
        if provider_code == "smspool":
            names = [item.get("name", "") for item in smspool_services.DATA if item.get("name")]
            for item in smspool_services.DATA:
                name = item.get("name", "")
                if _service_matches_name(raw, str(name)):
                    resolution["resolved_provider_service"] = str(item.get("ID"))
                    resolution["resolved_provider_label"] = str(name)
                    resolution["provider_reason"] = "resolved_catalog_match"
                    return _cache_and_return(resolution)
            mapped = get_service_provider_map(norm_target).get("smspool")
            if mapped not in (None, ""):
                resolution["resolved_provider_service"] = str(mapped)
                resolution["provider_reason"] = "resolved_static_mapping"
                return _cache_and_return(resolution)
            resolution["provider_reason"] = "service_not_supported"
            return _cache_and_return(resolution)

        if provider_code == "telabot":
            data = telabot_services.DATA
            if isinstance(data, dict) and "message" in data:
                names = [it.get("name", "") for it in data.get("message", []) if it.get("name")]
            elif isinstance(data, dict):
                names = list(data.keys())
            else:
                names = []
            for name in names:
                if _service_matches_name(raw, str(name)):
                    resolution["resolved_provider_service"] = str(name)
                    resolution["provider_reason"] = "resolved_catalog_match"
                    return _cache_and_return(resolution)
            resolution["provider_reason"] = "service_not_supported"
            return _cache_and_return(resolution)

        if provider_code == "textverified":
            names = [it.get("serviceName", "") for it in textverified_services.DATA if it.get("serviceName")]
            for name in names:
                if _service_matches_name(raw, str(name)):
                    resolution["resolved_provider_service"] = str(name)
                    resolution["provider_reason"] = "resolved_catalog_match"
                    return _cache_and_return(resolution)

            prov = PROVIDERS.get("textverified")
            if prov and hasattr(prov, "list_services"):
                try:
                    live = await _provider_list_services_cached("textverified", prov)
                    if isinstance(live, list):
                        live_names = [it.get("serviceName", "") for it in live if it.get("serviceName")]
                        for name in live_names:
                            if _service_matches_name(raw, str(name)):
                                resolution["resolved_provider_service"] = str(name)
                                resolution["provider_reason"] = "resolved_live_catalog_match"
                                return _cache_and_return(resolution)
                except Exception:
                    pass
            resolution["provider_reason"] = "service_not_supported"
            return _cache_and_return(resolution)

        if provider_code == "pvadeals":
            prov = PROVIDERS.get("pvadeals")
            if not prov or not hasattr(prov, "list_services"):
                resolution["provider_reason"] = "provider_missing"
                return _cache_and_return(resolution)

            candidates = [raw]
            candidates.extend(sorted(_service_candidate_keys(raw)))
            display_name = _service_display_name(raw)
            if display_name and display_name not in candidates:
                candidates.append(display_name)
            resolution["provider_candidates"] = [str(item) for item in candidates if str(item).strip()]

            for candidate in candidates:
                code = await _provider_resolve_service_code_with_timeout("pvadeals", prov, str(candidate))
                if code:
                    resolution["resolved_provider_service"] = str(code)
                    resolution["resolved_provider_candidate"] = str(candidate)
                    resolution["provider_reason"] = "resolved_provider_lookup"
                    return _cache_and_return(resolution)

            live = await _provider_list_services_cached("pvadeals", prov)
            if isinstance(live, list):
                strict_targets = _service_name_variants(raw)
                strict_targets.update(_service_name_variants(display_name or ""))
                for item in live:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    if strict_targets and (strict_targets & _service_name_variants(name)):
                        resolution["resolved_provider_service"] = name
                        resolution["provider_reason"] = "resolved_live_catalog_match"
                        return _cache_and_return(resolution)
            resolution["provider_reason"] = "service_not_supported"
            return _cache_and_return(resolution)

        if provider_code in {"herosms", "smsman", "alisms"}:
            mapped = get_service_provider_map(norm_target).get(provider_code)
            if mapped:
                resolution["resolved_provider_service"] = str(mapped)
                resolution["provider_reason"] = "resolved_static_mapping"
                return _cache_and_return(resolution)

            prov = PROVIDERS.get(provider_code)
            if not prov:
                resolution["provider_reason"] = "provider_missing"
                return _cache_and_return(resolution)

            candidates = [raw]
            candidates.extend(sorted(_service_candidate_keys(raw)))
            display_name = _service_display_name(raw)
            if display_name and display_name not in candidates:
                candidates.append(display_name)
            resolution["provider_candidates"] = [str(item) for item in candidates if str(item).strip()]

            for candidate in candidates:
                code = await _provider_resolve_service_code_with_timeout(provider_code, prov, str(candidate))
                if code:
                    resolution["resolved_provider_service"] = str(code)
                    resolution["resolved_provider_candidate"] = str(candidate)
                    resolution["provider_reason"] = "resolved_provider_lookup"
                    return _cache_and_return(resolution)

            resolution["provider_reason"] = "service_not_supported"
            return _cache_and_return(resolution)
    except Exception as e:
        logger.warning("Error reading provider data for %s: %s", provider_code, e)
        resolution["provider_reason"] = "provider_resolution_error"
        resolution["provider_reason_message"] = str(e)
        return _cache_and_return(resolution)

    resolution["provider_reason"] = "provider_not_supported"
    return _cache_and_return(resolution)


async def get_provider_service_name_dynamic(service_key: str, provider_code: str):
    """Resolve the provider-side service identifier for a generic service key."""
    resolution = await get_provider_service_resolution_dynamic(service_key, provider_code)
    resolved = resolution.get("resolved_provider_service")
    if resolved in (None, ""):
        return None
    return str(resolved)


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
            resolution = _service_resolution_snapshot(service_key, code)
            balance_task = asyncio.create_task(
                _provider_balance_with_timeout(
                    provider_obj,
                    timeout_sec=_price_screen_balance_timeout_sec(),
                )
            )

            # NonVoIP lane split: expose two virtual lanes (S5 cheapest + S6 second cheapest).
            if code == "smsman":
                query = _service_display_name(service_key) or str(service_key or "")
                c_code = str(country) if country and country != "none" else None
                s_code = str(state) if state and state != "none" else None
                variants = []
                if hasattr(provider_obj, "get_price_variants"):
                    variants = await asyncio.wait_for(
                        provider_obj.get_price_variants(query, c_code, s_code, limit=2),
                        timeout=_price_screen_provider_timeout_sec(code),
                    )
                if not variants and hasattr(provider_obj, "get_price"):
                    api_service_name = await get_provider_service_name_dynamic(service_key, code)
                    if not api_service_name and show_all_for_testing:
                        resolution = await get_provider_service_resolution_dynamic(service_key, code)
                    if api_service_name:
                        resolution["resolved_provider_service"] = str(api_service_name)
                        resolution["provider_reason"] = str(resolution.get("provider_reason") or "resolved_provider_lookup")
                        _log_provider_resolution_event(resolution, phase="pricing", country=c_code, state=s_code)
                        single = await asyncio.wait_for(
                            provider_obj.get_price(api_service_name, c_code, s_code),
                            timeout=_price_screen_provider_timeout_sec(code),
                        )
                        if isinstance(single, dict) and bool(single.get("success")):
                            variants = [dict(single)]
                            variants[0]["api_service_name"] = str(single.get("api_service_name") or api_service_name)
                if not variants:
                    provider_balance = await balance_task
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
                                "provider_reason": resolution.get("provider_reason", "service_not_supported"),
                                "provider_reason_message": resolution.get("provider_reason_message", ""),
                                "requested_service": resolution.get("requested_service", str(service_key or "")),
                                "canonical_service": resolution.get("canonical_service", ""),
                                "provider_candidates": list(resolution.get("provider_candidates") or []),
                            },
                        )
                    return (code, None)
                provider_balance = await balance_task
                lanes: list[dict[str, Any]] = []
                for variant in variants[:2]:
                    try:
                        base_price = float(variant.get("price") or 0.0)
                    except Exception:
                        base_price = 0.0
                    if base_price <= 0:
                        continue
                    api_service_name = str(variant.get("api_service_name") or "").strip()
                    if not api_service_name:
                        continue

                    lane = dict(variant)
                    lane["base_price"] = base_price
                    lane["price"] = round(base_price * (1.0 + markup_pct / 100.0), 4) if markup_pct > 0 else base_price
                    lane["api_service_name"] = api_service_name
                    lane["available_for_buy"] = True
                    if provider_balance is not None:
                        lane["provider_balance"] = float(provider_balance)
                        if provider_balance + 1e-9 < base_price:
                            lane["available_for_buy"] = False
                            lane["testing_visible"] = True
                            lane["provider_reason"] = "provider_balance_low"
                    elif not show_all_for_testing:
                        # Production safety: hide when balance cannot be verified.
                        continue
                    else:
                        lane["testing_visible"] = True
                        lane["provider_reason"] = "provider_balance_unknown"
                    lanes.append(lane)

                if not lanes:
                    return (code, None)
                lanes.sort(key=lambda row: float(row.get("base_price") or 0.0))
                primary = dict(lanes[0])
                if len(lanes) > 1:
                    primary["__second_lane"] = dict(lanes[1])
                return (code, primary)

            resolution = await get_provider_service_resolution_dynamic(service_key, code)
            api_service_name = str(service_key or "") if code == "alisms" else str(resolution.get("resolved_provider_service") or "")
            if not api_service_name:
                if not balance_task.done():
                    balance_task.cancel()
                if show_all_for_testing:
                    _log_provider_resolution_failure(resolution)
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
                            "provider_reason": resolution.get("provider_reason", "service_not_supported"),
                            "provider_reason_message": resolution.get("provider_reason_message", ""),
                            "requested_service": resolution.get("requested_service", str(service_key or "")),
                            "canonical_service": resolution.get("canonical_service", ""),
                            "provider_candidates": list(resolution.get("provider_candidates") or []),
                        },
                    )
                return (code, None)
            resolution["resolved_provider_service"] = str(api_service_name)
            _log_provider_resolution_event(resolution, phase="pricing", country=country, state=state)

            c_code = str(country) if country and country != "none" else None
            s_code = str(state) if state and state != "none" else None

            price_result, balance_result = await asyncio.gather(
                asyncio.wait_for(
                    provider_obj.get_price(api_service_name, c_code, s_code),
                    timeout=_price_screen_provider_timeout_sec(code),
                ),
                balance_task,
                return_exceptions=True,
            )
            if isinstance(price_result, Exception):
                raise price_result
            price_data = price_result
            provider_balance = None if isinstance(balance_result, Exception) else balance_result

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
                                "requested_service": resolution.get("requested_service", str(service_key or "")),
                                "canonical_service": resolution.get("canonical_service", ""),
                                "provider_candidates": list(resolution.get("provider_candidates") or []),
                            },
                        )
                    return (code, None)

                if provider_balance is None:
                    price_data["testing_visible"] = True
                    price_data["provider_reason"] = "provider_balance_unknown"
                if provider_balance is not None and provider_balance + 1e-9 < base_price:
                    # Hide provider when its account cannot currently buy this service.
                    if not show_all_for_testing:
                        return (code, None)
                    price_data["available_for_buy"] = False
                    price_data["testing_visible"] = True
                    price_data["provider_reason"] = "provider_balance_low"

                sale_price = base_price
                if base_price > 0 and markup_pct > 0:
                    sale_price = round(base_price * (1.0 + markup_pct / 100.0), 4)
                resolved_api_service_name = str(price_data.get("api_service_name") or api_service_name)
                price_data["base_price"] = base_price
                price_data["price"] = sale_price
                price_data["api_service_name"] = resolved_api_service_name
                price_data["available_for_buy"] = bool(price_data.get("available_for_buy", True))
                if not c_code:
                    provider_state_code, provider_country_iso = _extract_provider_location(
                        code,
                        api_service_name=resolved_api_service_name,
                        price_data=price_data,
                    )
                    if provider_state_code:
                        price_data["provider_state_code"] = provider_state_code
                    if provider_country_iso:
                        price_data["provider_country_iso"] = provider_country_iso
                _log_provider_attempt_event(
                    phase="pricing",
                    provider_code=code,
                    requested_service=str(service_key or ""),
                    api_service_name=resolved_api_service_name,
                    country=c_code,
                    state=s_code,
                    success=True,
                    reason=str(resolution.get("provider_reason") or ""),
                    raw=price_data.get("raw"),
                )
                if provider_balance is not None:
                    price_data["provider_balance"] = float(provider_balance)
                    if provider_balance + 1e-9 < base_price:
                        price_data["available_for_buy"] = False
                        price_data["testing_visible"] = True
                        price_data["provider_reason"] = "provider_balance_low"
                return (code, price_data)
            if show_all_for_testing:
                normalized = normalize_provider_error(price_data.get("raw") if isinstance(price_data, dict) else price_data)
                _log_provider_attempt_event(
                    phase="pricing",
                    provider_code=code,
                    requested_service=str(service_key or ""),
                    api_service_name=api_service_name,
                    country=c_code,
                    state=s_code,
                    success=False,
                    reason=str(resolution.get("provider_reason") or normalized.get("code") or "price_unavailable"),
                    raw=price_data.get("raw") if isinstance(price_data, dict) else price_data,
                )
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
                        "requested_service": resolution.get("requested_service", str(service_key or "")),
                        "canonical_service": resolution.get("canonical_service", ""),
                        "provider_candidates": list(resolution.get("provider_candidates") or []),
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
                        "requested_service": str(service_key or ""),
                        "canonical_service": resolve_canonical_service_key(service_key),
                        "provider_candidates": sorted(_service_candidate_keys(service_key)),
                    },
                )
        return (code, None)

    tasks = [
        fetch_single_provider(code, p)
        for code, p in PROVIDERS.items()
        if code != "smsman_s6"
    ]
    responses = await asyncio.gather(*tasks)

    for code, data in responses:
        if data:
            results[code] = data
            second_lane = data.pop("__second_lane", None) if isinstance(data, dict) else None
            if code == "smsman" and isinstance(second_lane, dict):
                results["smsman_s6"] = second_lane
            elif code == "smsman" and show_all_for_testing and "smsman_s6" not in results:
                results["smsman_s6"] = {
                    "success": False,
                    "price": 0.0,
                    "base_price": 0.0,
                    "api_service_name": "",
                    "success_rate": 100.0,
                    "testing_visible": True,
                    "available_for_buy": False,
                    "provider_reason": "second_lane_unavailable",
                    "requested_service": str(service_key or ""),
                    "canonical_service": str(resolve_canonical_service_key(str(service_key or "")) or ""),
                }
    if results:
        await _apply_dynamic_success_rates(results, str(service_key or ""))
    return results


async def get_all_rental_prices(service_key: str, country: str | None):
    """Fetch rental options from providers that support rental APIs."""
    results = {}
    is_unlimited = _is_unlimited_rental_service(service_key)
    show_all_for_testing = bool(getattr(settings, "numbers_show_all_providers_for_testing", False))
    rental_provider_codes = tuple(
        code
        for code in PROVIDERS.keys()
        if (
            provider_supports_rental(code)
            or (is_unlimited and provider_supports_unlimited_rental(code))
        )
        and code != "smsman_s6"
    )
    async def fetch_single_provider(code: str, provider_obj):
        if code not in rental_provider_codes:
            return (code, None)
        resolution = _service_resolution_snapshot(service_key, code)
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
            balance_task = asyncio.create_task(_provider_balance(provider_obj))
            if is_unlimited:
                api_service_name = str(UNLIMITED_RENTAL_PROVIDER_SERVICE_NAMES.get(code) or "").strip()
                if not api_service_name:
                    if not balance_task.done():
                        balance_task.cancel()
                    return (code, None)
            else:
                api_service_name = await get_provider_service_name_dynamic(service_key, code)
                if not api_service_name:
                    if not balance_task.done():
                        balance_task.cancel()
                    if show_all_for_testing:
                        resolution = await get_provider_service_resolution_dynamic(service_key, code)
                        _log_provider_resolution_failure(resolution)
                    if show_all_for_testing:
                        return (
                            code,
                            {
                                "success": False,
                                "options": [],
                                "api_service_name": "",
                                "available_for_buy": False,
                                "testing_visible": True,
                                "provider_reason": resolution.get("provider_reason", "service_not_supported"),
                                "provider_reason_message": resolution.get("provider_reason_message", ""),
                                "requested_service": resolution.get("requested_service", str(service_key or "")),
                                "canonical_service": resolution.get("canonical_service", ""),
                                "provider_candidates": list(resolution.get("provider_candidates") or []),
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
                            "requested_service": resolution.get("requested_service", str(service_key or "")),
                            "canonical_service": resolution.get("canonical_service", ""),
                            "provider_candidates": list(resolution.get("provider_candidates") or []),
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

                provider_balance = await balance_task
                if provider_balance is None and not show_all_for_testing:
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
                if provider_balance is not None:
                    affordable_options: list[dict[str, Any]] = []
                    for option in (rent_data.get("options") or []):
                        if not isinstance(option, dict):
                            continue
                        try:
                            option_price = float(option.get("price") or 0.0)
                        except Exception:
                            option_price = 0.0
                        if option_price > 0 and provider_balance + 1e-9 >= option_price:
                            affordable_options.append(option)
                    if not affordable_options:
                        if not show_all_for_testing:
                            return (code, None)
                        rent_data["options"] = []
                        rent_data["available_for_buy"] = False
                        rent_data["provider_reason"] = "provider_balance_low"
                        rent_data["testing_visible"] = True
                    else:
                        rent_data["options"] = affordable_options
                rent_data["api_service_name"] = api_service_name
                rent_data["available_for_buy"] = True
                if provider_balance is not None:
                    rent_data["provider_balance"] = float(provider_balance)
                    if not rent_data.get("options"):
                        rent_data["available_for_buy"] = False
                        rent_data["provider_reason"] = "provider_balance_low"
                        if show_all_for_testing:
                            rent_data["testing_visible"] = True
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
                        "requested_service": resolution.get("requested_service", str(service_key or "")),
                        "canonical_service": resolution.get("canonical_service", ""),
                        "provider_candidates": list(resolution.get("provider_candidates") or []),
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
                        "requested_service": resolution.get("requested_service", str(service_key or "")),
                        "canonical_service": resolution.get("canonical_service", ""),
                        "provider_candidates": list(resolution.get("provider_candidates") or []),
                    },
                )
        return (code, None)

    tasks = [fetch_single_provider(code, PROVIDERS[code]) for code in rental_provider_codes if code in PROVIDERS]
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
    audit_requested_service = str(opts.get("_audit_requested_service") or "").strip()
    try:
        result = await provider.buy_number(api_service_name, country, state, **opts)
        if isinstance(result, dict) and not bool(result.get("success")):
            raw = result.get("raw")
            result.setdefault("normalized_error", normalize_provider_error(raw))
            _log_provider_attempt_event(
                phase="purchase",
                provider_code=provider_code,
                requested_service=audit_requested_service,
                api_service_name=api_service_name,
                country=country,
                state=state,
                success=False,
                reason=str((result.get("normalized_error") or {}).get("code") or ""),
                raw=raw,
            )
        else:
            _log_provider_attempt_event(
                phase="purchase",
                provider_code=provider_code,
                requested_service=audit_requested_service,
                api_service_name=api_service_name,
                country=country,
                state=state,
                success=True,
                raw=result.get("raw") if isinstance(result, dict) else result,
            )
        return result
    except TypeError:
        # Backward compatibility for providers that do not accept extra kwargs.
        legacy_opts = {k: v for k, v in opts.items() if not str(k).startswith("_audit_")}
        if legacy_opts:
            result = await provider.buy_number(api_service_name, country, state, **legacy_opts)
        else:
            result = await provider.buy_number(api_service_name, country, state)
        if isinstance(result, dict) and not bool(result.get("success")):
            raw = result.get("raw")
            result.setdefault("normalized_error", normalize_provider_error(raw))
            _log_provider_attempt_event(
                phase="purchase",
                provider_code=provider_code,
                requested_service=audit_requested_service,
                api_service_name=api_service_name,
                country=country,
                state=state,
                success=False,
                reason=str((result.get("normalized_error") or {}).get("code") or ""),
                raw=raw,
            )
        else:
            _log_provider_attempt_event(
                phase="purchase",
                provider_code=provider_code,
                requested_service=audit_requested_service,
                api_service_name=api_service_name,
                country=country,
                state=state,
                success=True,
                raw=result.get("raw") if isinstance(result, dict) else result,
            )
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

