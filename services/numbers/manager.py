import asyncio
import inspect
import logging
import time
from typing import Any

from config import settings
from database import temp_number_stats_repo
from services.numbers.data import smspool_services, telabot_services, textverified_services
from services.numbers.manager_helpers import (
    _country_iso_value,
    _extract_balance_value,
    _extract_provider_location,
    _normalize_key,
    _price_match,
    _service_candidate_keys,
    _service_display_name,
    _service_matches_name,
    _service_name_variants,
    _to_float,
)
from services.numbers.manager_runtime import (
    _price_screen_balance_timeout_sec as _runtime_price_screen_balance_timeout_sec,
    _price_screen_provider_timeout_sec as _runtime_price_screen_provider_timeout_sec,
    _provider_balance as _runtime_provider_balance,
    _provider_balance_with_timeout as _runtime_provider_balance_with_timeout,
    _provider_service_catalog_cache_ttl_sec as _runtime_provider_service_catalog_cache_ttl_sec,
    _provider_timeout_sec as _runtime_provider_timeout_sec,
    _service_resolution_timeout_sec as _runtime_service_resolution_timeout_sec,
    _simulated_provider_balances as _runtime_simulated_provider_balances,
)
from services.numbers.manager_resolution import (
    _log_provider_attempt_event,
    _log_provider_resolution_event,
    _log_provider_resolution_failure,
    _service_resolution_snapshot,
)
from services.numbers.pricing_policy import temp_sale_price
from services.numbers.provider_readiness import provider_quote_enabled, readiness_block_payload
from services.numbers.virtual_policy import apply_virtual_offer_policy
from services.numbers.providers.herosms_provider import HeroSMSProvider
from services.numbers.providers.nonvoip_provider import NonVoipProvider
from services.numbers.providers.smspool_provider import SMSPoolProvider
from services.numbers.providers.telabot_provider import TelabotProvider
from services.numbers.providers.textverified_provider import TextVerifiedProvider
from services.numbers.providers.pvadeals_provider import PVADealsProvider
from services.numbers.providers.pvapins_provider import PVAPinsProvider
from services.numbers.providers.smsready_provider import SMSReadyProvider
from services.numbers.providers.vaksms_provider import VAKSMSProvider
from services.numbers.providers.error_normalizer import normalize_provider_error
from services.numbers.service_map import (
    SERVICE_MAP,
    get_service_provider_map,
    resolve_canonical_service_key,
)

logger = logging.getLogger("numbers_manager")

_NONVOIP_PROVIDER = NonVoipProvider()

PROVIDERS: dict[str, Any] = {
    "smspool": SMSPoolProvider(),
    "telabot": TelabotProvider(),
    "textverified": TextVerifiedProvider(),
    "herosms": HeroSMSProvider(),
    "nonvoip": _NONVOIP_PROVIDER,
    "pvadeals": PVADealsProvider(),
    "smsready": SMSReadyProvider(),
    "pvapins": PVAPinsProvider(),
    "vaksms": VAKSMSProvider(),
    # Virtual second lane for the same backend provider (second-best offer).
    "nonvoip_s6": _NONVOIP_PROVIDER,
}


def _provider_buy_kwargs(provider: Any, opts: dict[str, Any]) -> dict[str, Any]:
    """Return only purchase options accepted by this provider's buy method."""
    return _provider_method_kwargs(provider.buy_number, opts)


def _provider_method_kwargs(method: Any, opts: dict[str, Any]) -> dict[str, Any]:
    """Return only keyword options accepted by a provider method."""
    clean_opts = {k: v for k, v in opts.items() if not str(k).startswith("_audit_")}
    if not clean_opts:
        return {}

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return clean_opts

    params = signature.parameters
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
        return clean_opts

    accepted = {
        name
        for name, param in params.items()
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {key: value for key, value in clean_opts.items() if key in accepted}


RENTAL_PROVIDER_CODES: tuple[str, ...] = ("smspool", "herosms", "textverified", "pvadeals", "smsready", "pvapins")
RENTAL_UNLIMITED_SERVICE_KEY = "rental_unlimited"
TEMP_NOT_LISTED_SERVICE_KEY = "not_listed_generic"
# backward compatibility alias
SMSPOOL_OPEN_RENTAL_SERVICE_KEY = RENTAL_UNLIMITED_SERVICE_KEY
UNLIMITED_RENTAL_ALLOWED_ISO: frozenset[str] = frozenset({"US", "CA", "GB"})
UNLIMITED_RENTAL_PROVIDER_SERVICE_NAMES: dict[str, str] = {
    "smspool": RENTAL_UNLIMITED_SERVICE_KEY,
    "textverified": "allservices",
    "pvadeals": PVADealsProvider.ALL_SERVICES_SERVICE_ID,
}
TEMP_NOT_LISTED_PROVIDER_SERVICE_NAMES: dict[str, str] = {
    "smspool": "817",
    "textverified": "servicenotlisted",
    "telabot": "Unknown",
    "herosms": "ot",
    "pvadeals": "Website not in the list (Unknown)",
    "pvapins": "Anyother",
}


def is_temp_not_listed_service(service_key: str | None) -> bool:
    return _normalize_key(service_key) == resolve_canonical_service_key(TEMP_NOT_LISTED_SERVICE_KEY)


def temp_not_listed_provider_codes() -> tuple[str, ...]:
    return tuple(TEMP_NOT_LISTED_PROVIDER_SERVICE_NAMES)


def temp_not_listed_provider_service_name(provider_code: str | None) -> str:
    code = str(provider_code or "").strip().lower()
    return str(TEMP_NOT_LISTED_PROVIDER_SERVICE_NAMES.get(code) or "").strip()

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
        "temp_allowed_country_iso": {"US"},
        "rental_allowed_country_iso": {"US"},
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
        "temp_allowed_country_iso": {"US"},
    },
    "nonvoip": {
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
        "temp_allowed_country_iso": {"US"},
        "rental_allowed_country_iso": {"US"},
    },
    "smsready": {
        "supports_temp": True,
        "supports_rental": True,
        "supports_unlimited_rental": False,
        "supports_state_temp": False,
        "supports_state_rental": False,
    },
    "pvapins": {
        "supports_temp": True,
        "supports_rental": True,
        "supports_unlimited_rental": False,
        "supports_state_temp": False,
        "supports_state_rental": False,
    },
    "vaksms": {
        "supports_temp": True,
        "supports_rental": False,
        "supports_unlimited_rental": False,
        "supports_state_temp": False,
        "supports_state_rental": False,
    },
    "nonvoip_s6": {
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


def _provider_timeout_sec(kind: str, provider_code: str | None = None) -> float:
    return _runtime_provider_timeout_sec(settings, kind, provider_code)


def _price_screen_provider_timeout_sec(provider_code: str | None = None) -> float:
    return _runtime_price_screen_provider_timeout_sec(settings, provider_code)


def _service_resolution_timeout_sec(provider_code: str | None = None) -> float:
    return _runtime_service_resolution_timeout_sec(settings, provider_code)


def _provider_service_catalog_cache_ttl_sec() -> int:
    return _runtime_provider_service_catalog_cache_ttl_sec(settings)


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


async def _provider_resolve_first_service_code(
    provider_code: str,
    provider_obj: Any,
    candidates: list[str],
) -> tuple[str | None, str | None]:
    clean_candidates = []
    seen = set()
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        clean_candidates.append(text)
    if not clean_candidates or not hasattr(provider_obj, "resolve_service_code"):
        return None, None

    first_candidate = clean_candidates[0]
    first_code = await _provider_resolve_service_code_with_timeout(provider_code, provider_obj, first_candidate)
    if first_code:
        return first_code, first_candidate

    remaining_candidates = clean_candidates[1:]
    if not remaining_candidates:
        return None, None

    if hasattr(provider_obj, "list_services"):
        try:
            await _provider_list_services_cached(provider_code, provider_obj)
        except Exception:
            pass

    async def _resolve(candidate: str) -> tuple[str, str | None]:
        return candidate, await _provider_resolve_service_code_with_timeout(provider_code, provider_obj, candidate)

    tasks = [asyncio.create_task(_resolve(candidate)) for candidate in remaining_candidates]
    try:
        for task in asyncio.as_completed(tasks):
            candidate, code = await task
            if code:
                for pending in tasks:
                    if pending is not task and not pending.done():
                        pending.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                return code, candidate
    finally:
        for pending in tasks:
            if not pending.done():
                pending.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return None, None


def _price_screen_balance_timeout_sec() -> float:
    return _runtime_price_screen_balance_timeout_sec(settings)


def _simulated_provider_balances() -> dict[str, float]:
    return _runtime_simulated_provider_balances(settings)


def get_provider_capabilities(provider_code: str | None) -> dict[str, Any]:
    code = str(provider_code or "").strip().lower()
    return dict(PROVIDER_CAPABILITIES.get(code) or {})


def provider_supports_temp(provider_code: str | None) -> bool:
    return bool(get_provider_capabilities(provider_code).get("supports_temp"))


def provider_supports_rental(provider_code: str | None) -> bool:
    return bool(get_provider_capabilities(provider_code).get("supports_rental"))


def provider_supports_unlimited_rental(provider_code: str | None) -> bool:
    return bool(get_provider_capabilities(provider_code).get("supports_unlimited_rental"))


def provider_allows_temp(
    provider_code: str | None,
    *,
    country_iso: str | None = None,
    state_selected: bool = False,
) -> bool:
    caps = get_provider_capabilities(provider_code)
    if not caps.get("supports_temp"):
        return False
    allowed_iso = {str(item or "").strip().upper() for item in (caps.get("temp_allowed_country_iso") or []) if str(item or "").strip()}
    requested_iso = _country_iso_value(country_iso)
    if allowed_iso and requested_iso and requested_iso not in allowed_iso:
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
    allowed_iso = {str(item or "").strip().upper() for item in (caps.get("rental_allowed_country_iso") or []) if str(item or "").strip()}
    requested_iso = _country_iso_value(country_iso)
    if allowed_iso and requested_iso and requested_iso not in allowed_iso:
        return False
    if state_selected and not caps.get("supports_state_rental", False):
        return False
    return bool(caps.get("supports_rental"))


async def _effective_numbers_markup_percent() -> float:
    # Numbers are currently run at provider cost while provider integrations are
    # being validated. Keep this as the single hard stop so stale production env
    # markup values cannot affect quote screens or purchases.
    return 0.0


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


def _success_rate_query_timeout_sec() -> float:
    try:
        value = float(getattr(settings, "numbers_success_rate_query_timeout_sec", 2.0) or 2.0)
    except Exception:
        value = 2.0
    return max(0.1, value)


def _blend_success_rate(general: dict[str, Any], contextual: dict[str, Any], default_rate: float) -> float:
    general_rate = float(general.get("success_rate", default_rate))
    context_rate = float(contextual.get("success_rate", default_rate))
    general_attempts = int(general.get("attempts") or 0)
    context_attempts = int(contextual.get("attempts") or 0)
    min_attempts = _success_rate_min_attempts()
    if context_attempts >= min_attempts:
        return context_rate
    if context_attempts > 0:
        context_weight = min(0.7, 0.35 + (0.35 * context_attempts / float(min_attempts)))
        return (context_rate * context_weight) + (general_rate * (1.0 - context_weight))
    if general_attempts > 0:
        return general_rate
    return default_rate


async def _apply_dynamic_success_rates(
    results: dict[str, Any],
    service_id: str,
    *,
    country: str | None = None,
    state: str | None = None,
) -> None:
    if not results or not _success_rate_enabled():
        return
    providers = [str(code or "").strip().lower() for code in results.keys() if str(code or "").strip()]
    if not providers:
        return
    try:
        timeout_sec = _success_rate_query_timeout_sec()
        stats = await asyncio.wait_for(
            temp_number_stats_repo.get_provider_success_rates(
                service_id=str(service_id or "").strip(),
                providers=providers,
                lookback_days=_success_rate_lookback_days(),
                min_attempts=_success_rate_min_attempts(),
                default_rate=_success_rate_default(),
            ),
            timeout=timeout_sec,
        )
        context_stats: dict[str, Any] = {}
        country_value = str(country or "").strip()
        state_value = str(state or "").strip() or "none"
        if country_value:
            context_stats = await asyncio.wait_for(
                temp_number_stats_repo.get_provider_success_rates(
                    service_id=str(service_id or "").strip(),
                    providers=providers,
                    country=country_value,
                    state=state_value,
                    lookback_days=_success_rate_lookback_days(),
                    min_attempts=_success_rate_min_attempts(),
                    default_rate=_success_rate_default(),
                ),
                timeout=timeout_sec,
            )
    except TimeoutError:
        logger.warning("provider success rates timed out: service=%s", service_id)
        return
    except Exception:
        logger.exception("failed to compute provider success rates: service=%s", service_id)
        return

    default_rate = _success_rate_default()
    for provider_code, info in results.items():
        if not isinstance(info, dict):
            continue
        provider = str(provider_code or "").strip().lower()
        row = stats.get(provider) or {}
        context_row = context_stats.get(provider) or {}
        try:
            rate_value = float(row.get("success_rate", default_rate))
        except Exception:
            rate_value = default_rate
        try:
            context_rate_value = float(context_row.get("success_rate", default_rate))
        except Exception:
            context_rate_value = default_rate
        info["success_rate"] = max(0.0, min(100.0, rate_value))
        info["success_attempts"] = int(row.get("attempts") or 0)
        info["success_sample_sufficient"] = bool(row.get("sample_sufficient"))
        info["context_success_rate"] = max(0.0, min(100.0, context_rate_value))
        info["context_success_attempts"] = int(context_row.get("attempts") or 0)
        info["context_success_sample_sufficient"] = bool(context_row.get("sample_sufficient"))
        info["recommended_success_rate"] = max(
            0.0,
            min(100.0, _blend_success_rate(row, context_row, default_rate)),
        )


def _is_unlimited_rental_service(service_key: str) -> bool:
    return _normalize_key(service_key) == resolve_canonical_service_key(RENTAL_UNLIMITED_SERVICE_KEY)


async def _provider_balance(provider_obj: Any) -> float | None:
    return await _runtime_provider_balance(
        provider_obj,
        settings_obj=settings,
        providers=PROVIDERS,
        balance_cache=_PROVIDER_BALANCE_CACHE,
    )


async def _provider_balance_with_timeout(provider_obj: Any, *, timeout_sec: float | None = None) -> float | None:
    return await _runtime_provider_balance_with_timeout(
        provider_obj,
        settings_obj=settings,
        providers=PROVIDERS,
        balance_cache=_PROVIDER_BALANCE_CACHE,
        timeout_sec=timeout_sec,
    )


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

            code, candidate = await _provider_resolve_first_service_code("pvadeals", prov, resolution["provider_candidates"])
            if code:
                resolution["resolved_provider_service"] = str(code)
                resolution["resolved_provider_candidate"] = str(candidate or "")
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

        if provider_code in {"herosms", "nonvoip", "vaksms", "smsready", "pvapins"}:
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

            code, candidate = await _provider_resolve_first_service_code(provider_code, prov, resolution["provider_candidates"])
            if code:
                resolution["resolved_provider_service"] = str(code)
                resolution["resolved_provider_candidate"] = str(candidate or "")
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


async def get_all_prices(
    service_key: str,
    country: str | None,
    state: str | None,
    *,
    ignore_balance: bool = False,
    with_success_rates: bool = True,
    soft_timeout_sec: float | None = None,
    provider_codes: set[str] | list[str] | tuple[str, ...] | None = None,
):
    """Fetch temporary-number prices from all configured providers."""
    results = {}
    markup_pct = await _effective_numbers_markup_percent()
    show_all_for_testing = bool(getattr(settings, "numbers_show_all_providers_for_testing", False))
    state_selected = bool(state and str(state).strip().lower() != "none")
    requested_country_iso = _country_iso_value(str(country or "").strip()) if country and str(country).strip().lower() != "none" else ""
    async def fetch_single_provider(code, provider_obj):
        try:
            if not provider_quote_enabled(code, mode="temp"):
                return (code, readiness_block_payload(code, mode="temp") if show_all_for_testing else None)
            if not provider_allows_temp(code, country_iso=requested_country_iso, state_selected=state_selected):
                return (code, None)
            resolution = _service_resolution_snapshot(service_key, code)
            balance_task = (
                asyncio.create_task(
                    _provider_balance_with_timeout(
                        provider_obj,
                        timeout_sec=_price_screen_balance_timeout_sec(),
                    )
                )
                if not ignore_balance
                else None
            )

            # NonVoIP lane split: expose two virtual lanes (S7 cheapest + S8 second cheapest).
            if code == "nonvoip":
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
                    provider_balance = await balance_task if balance_task is not None else None
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
                provider_balance = await balance_task if balance_task is not None else None
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
                    lane["price"] = temp_sale_price(
                        service_key=service_key,
                        base_price=base_price,
                        markup_percent=markup_pct,
                        requested_country=c_code,
                        provider_country_iso=lane.get("provider_country_iso"),
                        provider_country=lane.get("provider_country"),
                    )
                    apply_virtual_offer_policy(lane, service_key=service_key)
                    lane["api_service_name"] = api_service_name
                    lane["available_for_buy"] = True
                    if provider_balance is not None:
                        lane["provider_balance"] = float(provider_balance)
                        if provider_balance + 1e-9 < base_price and not ignore_balance:
                            lane["available_for_buy"] = False
                            lane["testing_visible"] = True
                            lane["provider_reason"] = "provider_balance_low"
                    elif not show_all_for_testing and not ignore_balance:
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

            if is_temp_not_listed_service(service_key):
                api_service_name = temp_not_listed_provider_service_name(code)
                resolution["resolved_provider_service"] = api_service_name
                resolution["provider_reason"] = "resolved_not_listed_fallback" if api_service_name else "service_not_supported"
            else:
                resolution = await get_provider_service_resolution_dynamic(service_key, code)
                api_service_name = str(resolution.get("resolved_provider_service") or "")
            if not api_service_name:
                if balance_task is not None and not balance_task.done():
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

            if balance_task is not None:
                price_result, balance_result = await asyncio.gather(
                    asyncio.wait_for(
                        provider_obj.get_price(api_service_name, c_code, s_code),
                        timeout=_price_screen_provider_timeout_sec(code),
                    ),
                    balance_task,
                    return_exceptions=True,
                )
            else:
                price_result = await asyncio.wait_for(
                    provider_obj.get_price(api_service_name, c_code, s_code),
                    timeout=_price_screen_provider_timeout_sec(code),
                )
                balance_result = None
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
                    if not show_all_for_testing and not ignore_balance:
                        return (code, None)
                    if not ignore_balance:
                        price_data["available_for_buy"] = False
                        price_data["testing_visible"] = True
                        price_data["provider_reason"] = "provider_balance_low"

                resolved_api_service_name = str(price_data.get("api_service_name") or api_service_name)
                price_data["base_price"] = base_price
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
                price_data["price"] = temp_sale_price(
                    service_key=service_key,
                    base_price=base_price,
                    markup_percent=markup_pct,
                    requested_country=c_code,
                    provider_country_iso=price_data.get("provider_country_iso"),
                    provider_country=price_data.get("provider_country"),
                )
                apply_virtual_offer_policy(price_data, service_key=service_key)
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
                    if provider_balance + 1e-9 < base_price and not ignore_balance:
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

    allowed_provider_codes = {str(code or "").strip().lower() for code in (provider_codes or []) if str(code or "").strip()}
    tasks = [
        asyncio.create_task(fetch_single_provider(code, p))
        for code, p in PROVIDERS.items()
        if code != "nonvoip_s6" and (not allowed_provider_codes or str(code).strip().lower() in allowed_provider_codes)
    ]
    if soft_timeout_sec and soft_timeout_sec > 0:
        done, pending = await asyncio.wait(tasks, timeout=float(soft_timeout_sec))
        responses = [task.result() for task in done if not task.cancelled() and task.exception() is None]
        has_visible_data = any(data for _code, data in responses)
        if pending and has_visible_data:
            for task in pending:
                task.cancel()
            await asyncio.wait(pending, timeout=0.1)
        elif pending:
            responses.extend(await asyncio.gather(*pending))
    else:
        responses = await asyncio.gather(*tasks)

    for code, data in responses:
        if data:
            results[code] = data
            second_lane = data.pop("__second_lane", None) if isinstance(data, dict) else None
            if code == "nonvoip" and isinstance(second_lane, dict):
                results["nonvoip_s6"] = second_lane
            elif code == "nonvoip" and show_all_for_testing and "nonvoip_s6" not in results:
                results["nonvoip_s6"] = {
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
    if results and with_success_rates:
        await _apply_dynamic_success_rates(results, str(service_key or ""), country=country, state=state or "none")
    return results


async def get_all_rental_prices(
    service_key: str,
    country: str | None,
    *,
    with_success_rates: bool = True,
    ignore_balance: bool = False,
):
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
        and code != "nonvoip_s6"
    )
    async def fetch_single_provider(code: str, provider_obj):
        if code not in rental_provider_codes:
            return (code, None)
        if not provider_quote_enabled(code, mode="rental"):
            return (code, readiness_block_payload(code, mode="rental") if show_all_for_testing else None)
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
                if provider_balance is None and not show_all_for_testing and not ignore_balance:
                    return (code, None)

                markup_pct = await _effective_numbers_markup_percent()
                enriched_options = []
                for option in (rent_data.get("options") or []):
                    if not isinstance(option, dict):
                        enriched_options.append(option)
                        continue
                    row = dict(option)
                    try:
                        base_price = float(row.get("base_price", row.get("price")) or 0.0)
                    except Exception:
                        base_price = 0.0
                    row["base_price"] = base_price
                    if markup_pct > 0:
                        row["price"] = round(base_price * (1.0 + markup_pct / 100.0), 4) if base_price > 0 else base_price
                    else:
                        row["price"] = base_price
                    enriched_options.append(row)
                rent_data["options"] = enriched_options
                insufficient_balance = False
                if provider_balance is not None and not ignore_balance:
                    affordable_options: list[dict[str, Any]] = []
                    for option in (rent_data.get("options") or []):
                        if not isinstance(option, dict):
                            continue
                        try:
                            option_price = float(option.get("base_price") or option.get("price") or 0.0)
                        except Exception:
                            option_price = 0.0
                        if option_price > 0 and provider_balance + 1e-9 >= option_price:
                            affordable_options.append(option)
                    if not affordable_options:
                        insufficient_balance = True
                        rent_data["available_for_buy"] = False
                        rent_data["provider_reason"] = "provider_balance_low"
                        rent_data["testing_visible"] = True
                    else:
                        rent_data["options"] = affordable_options
                rent_data["api_service_name"] = api_service_name
                rent_data["available_for_buy"] = bool(rent_data.get("options")) and not insufficient_balance
                if provider_balance is not None:
                    rent_data["provider_balance"] = float(provider_balance)
                    if not rent_data.get("options") or insufficient_balance:
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
    if results and with_success_rates:
        await _apply_dynamic_success_rates(results, f"{str(service_key or '')}:rental", country=country)
    return results


async def get_all_voice_prices(service_key: str, country: str | None, state: str | None, *, ignore_balance: bool = False):
    """Fetch incoming-call verification prices. Currently TextVerified only."""
    provider_code = "textverified"
    provider_obj = PROVIDERS.get(provider_code)
    if not provider_obj or not hasattr(provider_obj, "get_voice_price"):
        return {}
    markup_pct = await _effective_numbers_markup_percent()
    c_code = str(country) if country and country != "none" else None
    s_code = str(state) if state and state != "none" else None
    try:
        if ignore_balance:
            price_result = await asyncio.wait_for(
                provider_obj.get_voice_price(str(service_key or ""), c_code, s_code),
                timeout=_price_screen_provider_timeout_sec(provider_code),
            )
            balance_result = None
        else:
            price_result, balance_result = await asyncio.gather(
                asyncio.wait_for(
                    provider_obj.get_voice_price(str(service_key or ""), c_code, s_code),
                    timeout=_price_screen_provider_timeout_sec(provider_code),
                ),
                _provider_balance_with_timeout(
                    provider_obj,
                    timeout_sec=_price_screen_balance_timeout_sec(),
                ),
                return_exceptions=True,
            )
        if isinstance(price_result, Exception):
            raise price_result
        if not isinstance(price_result, dict) or not bool(price_result.get("success")):
            return {}
        try:
            base_price = float(price_result.get("price") or 0.0)
        except Exception:
            base_price = 0.0
        if base_price <= 0:
            return {}
        provider_balance = None if isinstance(balance_result, Exception) else balance_result
        if provider_balance is not None and provider_balance + 1e-9 < base_price and not ignore_balance:
            return {}
        sale_price = round(base_price * (1.0 + markup_pct / 100.0), 4) if markup_pct > 0 else base_price
        info = dict(price_result)
        info.update(
            {
                "base_price": base_price,
                "price": sale_price,
                "api_service_name": str(price_result.get("api_service_name") or service_key or ""),
                "available_for_buy": True,
                "voice_capable": True,
                "success_rate": 100.0,
                "success_attempts": 0,
            }
        )
        if provider_balance is not None:
            info["provider_balance"] = float(provider_balance)
        return {provider_code: info}
    except Exception as exc:
        logger.warning("Provider %s voice price fetch failed: %s", provider_code, exc)
        return {}


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
    provider_opts = _provider_buy_kwargs(provider, opts)
    result = await provider.buy_number(api_service_name, country, state, **provider_opts)
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


async def get_calls_from_provider(provider_code: str, provider_order_id: str, to_number: str | None = None) -> dict[str, Any]:
    provider = PROVIDERS.get(provider_code)
    if not provider or not hasattr(provider, "get_calls"):
        return {"success": False, "calls": [], "raw": "provider_does_not_support_calls"}
    return await provider.get_calls(provider_order_id, to_number=to_number)


async def get_recording_from_provider(provider_code: str, recording_uri: str) -> dict[str, Any]:
    provider = PROVIDERS.get(provider_code)
    if not provider or not hasattr(provider, "download_recording"):
        return {"success": False, "raw": "provider_does_not_support_recording_download"}
    return await provider.download_recording(recording_uri)


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
            "provider_country",
            "tv_with_state",
            "state_code",
            "tv_duration_key",
            "tv_is_renewable",
            "provider_duration",
            "provider_app",
        ):
            value = option_meta.get(key)
            if value not in (None, ""):
                provider_kwargs[key] = value
    provider_kwargs = _provider_method_kwargs(provider.rent_number, provider_kwargs)
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

