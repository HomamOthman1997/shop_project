from __future__ import annotations

import asyncio
from typing import Any

from config import settings
from services.proxies.providers.fourg_proxy_provider import FourGProxyProvider
from services.proxies.providers.nine_proxy_provider import NineProxyProvider
from services.proxies.risk_engine import verify_proxy_endpoint
from utils.beta_mode import beta_mode_enabled, beta_proxy_markup_percent

PROXY_PROVIDERS = {
    "9proxy": NineProxyProvider(),
    "4g": FourGProxyProvider(),
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _norm_text(value: Any, fallback: str = "Any") -> str:
    text = str(value or "").strip()
    return text or fallback


def _clamp_success_rate(value: Any) -> float:
    rate = _as_float(value, 100.0)
    if rate < 0:
        return 0.0
    if rate > 100:
        return 100.0
    return rate


def _proxy_markup_pct() -> float:
    if beta_mode_enabled():
        return beta_proxy_markup_percent(10.0)
    pct = _as_float(getattr(settings, "proxy_service_markup_percent", 0.0), 0.0)
    # Proxy markup is an operational pricing lever and should remain independent.
    # If explicitly set, apply it even when global profit policy is off.
    if pct > 0:
        return pct
    if not bool(getattr(settings, "profit_policy_enabled", True)):
        return 0.0
    if pct < 0:
        return 0.0
    return pct


def _hide_unpriced_offers() -> bool:
    return bool(getattr(settings, "proxy_hide_unpriced_offers", True))


def _price_with_markup(base_price: float, markup_pct: float) -> float:
    if base_price <= 0:
        return 0.0
    if markup_pct <= 0:
        return round(base_price, 4)
    return round(base_price * (1.0 + markup_pct / 100.0), 4)


def _infer_billing_type(title: str, raw: dict[str, Any]) -> str:
    raw_type = str(raw.get("product_type") or raw.get("billing_type") or "").lower()
    title_l = title.lower()
    if "traffic" in raw_type or "gb" in raw_type or "traffic" in title_l or "consumable" in title_l:
        return "bandwidth"
    return "fixed"


def _normalize_offer(provider_code: str, row: dict[str, Any], markup_pct: float) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None

    offer_id = str(row.get("offer_id") or row.get("id") or "").strip()
    if not offer_id:
        return None

    title = str(row.get("title") or row.get("name") or f"Offer {offer_id}").strip() or f"Offer {offer_id}"
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}

    base_price = _as_float(row.get("base_price") if row.get("base_price") is not None else row.get("price"), 0.0)
    sale_price = _price_with_markup(base_price, markup_pct)
    if _hide_unpriced_offers() and sale_price <= 0:
        return None

    normalized = {
        "provider": provider_code,
        "offer_id": offer_id,
        "title": title,
        "country": _norm_text(row.get("country"), "Any"),
        "state": _norm_text(row.get("state"), "Any"),
        "city": _norm_text(row.get("city"), "Any"),
        "period": _norm_text(row.get("period"), "-"),
        "base_price": round(base_price, 4),
        "price": sale_price,
        "success_rate": _clamp_success_rate(row.get("success_rate", 100)),
        "billing_type": _infer_billing_type(title, raw),
        "raw": raw,
    }
    return normalized


async def _fetch_provider_offers(provider_code: str, provider_obj: Any) -> list[dict[str, Any]]:
    try:
        rows = await asyncio.wait_for(provider_obj.list_offers(), timeout=20.0)
    except Exception:
        rows = []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def proxy_change_check_price() -> float:
    value = _as_float(getattr(settings, "proxy_change_check_price", 0.015), 0.015)
    if value < 0:
        return 0.0
    return round(value, 4)


def proxy_change_only_cooldown_minutes() -> int:
    try:
        minutes = int(getattr(settings, "proxy_change_only_cooldown_minutes", 15) or 15)
    except Exception:
        minutes = 15
    return max(1, minutes)


async def get_proxy_catalog() -> list[dict[str, Any]]:
    tasks = [
        _fetch_provider_offers(code, provider)
        for code, provider in PROXY_PROVIDERS.items()
    ]
    responses = await asyncio.gather(*tasks)

    markup_pct = _proxy_markup_pct()
    dedup: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}

    for idx, provider_code in enumerate(PROXY_PROVIDERS.keys()):
        rows = responses[idx] if idx < len(responses) else []
        for row in rows:
            normalized = _normalize_offer(provider_code, row, markup_pct)
            if not normalized:
                continue
            key = (
                str(normalized.get("provider") or ""),
                str(normalized.get("offer_id") or ""),
                str(normalized.get("country") or ""),
                str(normalized.get("state") or ""),
                str(normalized.get("city") or ""),
                str(normalized.get("period") or ""),
            )
            if key not in dedup:
                dedup[key] = normalized

    offers = list(dedup.values())
    offers.sort(
        key=lambda x: (
            str(x.get("country") or "Any"),
            str(x.get("state") or "Any"),
            str(x.get("city") or "Any"),
            str(x.get("provider") or ""),
            float(x.get("price") or 0.0),
        )
    )
    return offers


async def rent_proxy_offer(offer: dict[str, Any]) -> dict[str, Any]:
    provider_code = str(offer.get("provider") or "").lower()
    provider = PROXY_PROVIDERS.get(provider_code)
    if not provider:
        return {"success": False, "raw": {"title": "UNKNOWN_PROVIDER"}}
    return await provider.rent_offer(offer)


async def verify_proxy_offer_delivery(endpoint: str) -> dict[str, Any]:
    gate_enabled = bool(getattr(settings, "proxy_quality_gate_enabled", True))
    fail_closed = bool(getattr(settings, "proxy_quality_fail_closed", False))

    if not gate_enabled:
        return {
            "allowed": True,
            "decision": "pass",
            "reason": "quality_gate_disabled",
            "engines": {"gate": {"decision": "pass", "reason": "disabled"}},
        }

    result = await verify_proxy_endpoint(endpoint)
    decision = str(result.get("decision") or "gray").lower()

    if decision == "pass":
        return {**result, "allowed": True}
    if decision == "fail":
        return {**result, "allowed": False}
    # gray
    if fail_closed:
        return {**result, "allowed": False, "decision": "gray_fail"}
    return {**result, "allowed": True, "decision": "gray_pass"}


async def refresh_proxy_order(
    order_data: dict[str, Any],
    *,
    with_check: bool = False,
    max_attempts: int = 1,
) -> dict[str, Any]:
    provider_code = str(order_data.get("provider") or "").lower()
    provider = PROXY_PROVIDERS.get(provider_code)
    if not provider:
        return {"success": False, "raw": {"title": "UNKNOWN_PROVIDER"}}

    attempts = max(1, int(max_attempts))
    last_raw: Any = None

    for idx in range(1, attempts + 1):
        refreshed = await provider.refresh_proxy(order_data, with_check=with_check)
        if not refreshed.get("success"):
            last_raw = refreshed.get("raw")
            continue

        if with_check:
            endpoint = str(refreshed.get("endpoint") or "")
            quality = await verify_proxy_offer_delivery(endpoint)
            if not quality.get("allowed"):
                last_raw = {"title": "QUALITY_FAIL", "quality": quality}
                if idx < attempts:
                    continue
                return {
                    "success": False,
                    "raw": last_raw,
                    "quality": quality,
                    "attempts": idx,
                    "billable": False,
                }
            return {
                "success": True,
                **refreshed,
                "quality": quality,
                "attempts": idx,
                "billable": True,
            }

        return {
            "success": True,
            **refreshed,
            "attempts": idx,
            "billable": False,
        }

    return {"success": False, "raw": last_raw or {"title": "REFRESH_FAILED"}, "attempts": attempts}
