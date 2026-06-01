from __future__ import annotations

import json
from typing import Any

from config import settings
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


def _configured_floors() -> dict[str, dict[str, float]]:
    floors = {service: dict(values) for service, values in _FLOORS_BY_SERVICE.items()}
    raw = str(getattr(settings, "numbers_temp_price_floors_json", "") or "").strip()
    if not raw:
        return floors
    try:
        data = json.loads(raw)
    except Exception:
        return floors
    if not isinstance(data, dict):
        return floors
    for service_key, service_floors in data.items():
        service = _policy_service_key(service_key)
        if not service or not isinstance(service_floors, dict):
            continue
        target = floors.setdefault(service, {})
        for country_key, value in service_floors.items():
            country = str(country_key or "").strip().upper()
            if not country:
                continue
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price > 0:
                target[country] = price
    return floors


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
    return round(cost, 4)
