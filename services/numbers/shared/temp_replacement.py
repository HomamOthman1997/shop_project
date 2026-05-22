from __future__ import annotations

from typing import Any


def temp_replacement_fields(order: dict[str, Any] | None) -> dict[str, Any]:
    order = order or {}
    service = str(order.get("temp_service_key") or order.get("service_id") or "").strip()
    provider = str(order.get("provider") or order.get("provisioning_provider") or "").strip().lower()
    api_service = str(order.get("temp_api_service") or order.get("provisioning_service") or "").strip()
    raw_country = order.get("temp_country")
    if raw_country in (None, ""):
        raw_country = order.get("provisioning_country")
    raw_state = order.get("temp_state")
    if raw_state in (None, ""):
        raw_state = order.get("provisioning_state_code")
    country = str(raw_country or "none").strip() or "none"
    state = str(raw_state or "none").strip() or "none"
    if country != "1":
        state = "none"
    return {
        "service": service,
        "provider": provider,
        "api_service": api_service,
        "raw_country": raw_country,
        "raw_state": raw_state,
        "country": country,
        "state": state,
    }


def provider_retry_score(info: dict[str, Any], cheapest: float) -> float:
    try:
        price = float(info.get("price") or 0)
    except Exception:
        price = 0.0
    try:
        rate = float(
            info.get("recommended_success_rate")
            if info.get("recommended_success_rate") is not None
            else info.get("success_rate", 100)
        )
    except Exception:
        rate = 100.0
    rate = max(0.0, min(100.0, rate))
    attempts = int(info.get("success_attempts") or 0)
    context_attempts = int(info.get("context_success_attempts") or 0)
    if attempts < 3 and context_attempts < 3:
        rate = min(rate, 90.0)
    price_ratio = price / cheapest if cheapest > 0 else 1.0
    price_penalty = min(22.0, max(0.0, price_ratio - 1.0) * 12.0)
    sample_bonus = min(4.0, (attempts + (context_attempts * 2)) * 0.25)
    return rate - price_penalty + sample_bonus


def pick_retry_provider(
    prices: dict[str, Any],
    *,
    exclude_provider: str | None = None,
    hidden_provider_codes: set[str] | frozenset[str] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    excluded = str(exclude_provider or "").strip().lower()
    hidden = set(hidden_provider_codes or set())
    candidates: list[tuple[float, float, str, dict[str, Any]]] = []
    buyable: list[tuple[str, dict[str, Any], float]] = []
    for provider_code, info in (prices or {}).items():
        code = str(provider_code or "").strip().lower()
        if not code or code == excluded or code in hidden or not isinstance(info, dict):
            continue
        try:
            price = float(info.get("price") or 0)
        except Exception:
            price = 0.0
        if not bool(info.get("available_for_buy", True)) or not str(info.get("api_service_name") or "").strip() or price <= 0:
            continue
        buyable.append((code, info, price))
    if not buyable:
        return None
    cheapest = min(price for _code, _info, price in buyable)
    for code, info, price in buyable:
        candidates.append((-provider_retry_score(info, cheapest), price, code, info))
    candidates.sort(key=lambda row: (row[0], row[1], row[2]))
    return candidates[0][2], candidates[0][3]
