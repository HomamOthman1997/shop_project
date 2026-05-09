from __future__ import annotations

from typing import Any

from services.numbers.manager_helpers import _country_iso_value
from services.numbers.service_families import normalize_service_key

_POLICY_SERVICES = {"whatsapp", "telegram"}
_MIN_MARKUP_PERCENT = 25.0

_FLOORS_BY_SERVICE: dict[str, dict[str, float]] = {
    "whatsapp": {
        "*": 1.00,
        "US": 1.50,
    },
    "telegram": {
        "*": 0.75,
        "US": 0.90,
    },
}


def _policy_service_key(service_key: Any) -> str:
    key = normalize_service_key(str(service_key or ""))
    return key if key in _POLICY_SERVICES else ""


def temp_sale_price(
    *,
    service_key: Any,
    base_price: float,
    markup_percent: float,
    requested_country: Any = None,
    provider_country_iso: Any = None,
    provider_country: Any = None,
) -> float:
    try:
        cost = float(base_price or 0.0)
    except Exception:
        cost = 0.0
    if cost <= 0:
        return 0.0

    service = _policy_service_key(service_key)
    effective_markup = float(markup_percent or 0.0)
    if service:
        effective_markup = max(effective_markup, _MIN_MARKUP_PERCENT)

    sale_price = cost * (1.0 + max(0.0, effective_markup) / 100.0)
    floors = _FLOORS_BY_SERVICE.get(service) or {}
    if floors:
        iso = _country_iso_value(str(provider_country_iso or provider_country or requested_country or "").strip())
        floor = floors.get(iso) or floors.get("*") or 0.0
        sale_price = max(sale_price, floor)
    return round(sale_price, 4)
