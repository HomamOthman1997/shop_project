from typing import Any

from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.service_families import normalize_service_key
from services.numbers.service_map import (
    get_service_aliases,
    get_service_display_name,
    resolve_canonical_service_key,
)

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
    except (TypeError, ValueError):
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

    if code == "vaksms" and isinstance(raw, dict):
        iso = _country_iso_value(str(price_data.get("provider_country_iso") or price_data.get("provider_country") or "").strip())
        if iso:
            return "", iso

    if code in {"textverified", "telabot"}:
        return "", "US"

    return "", ""


def _normalize_key(value: str) -> str:
    return normalize_service_key(value)


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


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
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
        if "message" in raw_balance:
            parsed = _to_float(raw_balance.get("message"))
            if parsed is not None:
                return parsed
    return None
