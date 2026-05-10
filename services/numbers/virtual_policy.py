from __future__ import annotations

from typing import Any

from services.numbers.service_families import normalize_service_key

_SENSITIVE_VIRTUAL_SERVICE_KEYS = {
    "whatsapp",
    "telegram",
    "gmail",
    "googlegmail",
    "google",
    "youtube",
}

_VIRTUAL_COUNTRY_CODES = {
    "USV",
    "AUV",
}

_LOCATION_KEYS = {
    "country",
    "countrycode",
    "country_code",
    "countryid",
    "country_id",
    "countryiso",
    "country_iso",
    "iso",
    "shortname",
    "short_name",
    "provider_country",
    "provider_country_iso",
    "countryname",
    "country_name",
    "name",
    "tag",
}


def _compact_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("-", "_")


def _is_virtual_location_value(value: Any) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    upper = raw.upper()
    if upper in _VIRTUAL_COUNTRY_CODES:
        return True
    normalized = raw.casefold()
    return "virtual" in normalized or normalized.endswith("(v)")


def is_virtual_offer(offer: dict[str, Any] | None) -> bool:
    if not isinstance(offer, dict):
        return False
    if bool(offer.get("virtual_number")):
        return True
    for key in ("provider_country_iso", "provider_country", "country_iso", "country", "country_name"):
        if _is_virtual_location_value(offer.get(key)):
            return True
    return _raw_has_virtual_location(offer.get("raw"))


def _raw_has_virtual_location(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            key_norm = _compact_key(key)
            if key_norm in _LOCATION_KEYS and _is_virtual_location_value(item):
                return True
            if isinstance(item, (dict, list, tuple)) and _raw_has_virtual_location(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_raw_has_virtual_location(item) for item in value)
    return False


def is_virtual_sensitive_service(service_key: Any) -> bool:
    return normalize_service_key(str(service_key or "")) in _SENSITIVE_VIRTUAL_SERVICE_KEYS


def apply_virtual_offer_policy(offer: dict[str, Any], *, service_key: Any) -> None:
    if not is_virtual_offer(offer):
        return
    offer["virtual_number"] = True
    if not is_virtual_sensitive_service(service_key):
        return
    offer["recommendation_blocked"] = True
    offer.setdefault("recommendation_reason", "virtual_low_confidence")
