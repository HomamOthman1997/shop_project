from __future__ import annotations

import asyncio
import secrets
from typing import Any

from config import settings
from database.proxy_telemetry_repo import record_proxy_event
from services.proxies.providers.fourg_proxy_provider import FourGProxyProvider
from services.proxies.risk_engine import verify_proxy_endpoint

PROXY_PROVIDERS = {
    "4g": FourGProxyProvider(),
    # Keep 9Proxy suspended until upstream auth/permission issues are resolved.
}


async def _record_proxy_event_safe(**kwargs: Any) -> None:
    try:
        await record_proxy_event(**kwargs)
    except Exception:
        return


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


def _proxy_event_reason(raw: Any, fallback: str = "") -> str:
    if isinstance(raw, dict):
        for key in ("title", "message", "error", "details", "reason"):
            value = str(raw.get(key) or "").strip()
            if value:
                return value[:120]
    text = str(raw or fallback or "").strip()
    return text[:120]


def _offer_event_extra(offer: dict[str, Any]) -> dict[str, Any]:
    raw = offer.get("raw") if isinstance(offer.get("raw"), dict) else {}
    return {
        "offer_id": str(offer.get("offer_id") or "").strip(),
        "title": str(offer.get("title") or "").strip(),
        "country": str(offer.get("country") or "").strip(),
        "state": str(offer.get("state") or "").strip(),
        "city": str(offer.get("city") or "").strip(),
        "carrier": str(offer.get("carrier") or "").strip(),
        "period": str(offer.get("period") or "").strip(),
        "billing_type": str(offer.get("billing_type") or "").strip(),
        "price": _as_float(offer.get("price"), 0.0),
        "base_price": _as_float(offer.get("base_price"), 0.0),
        "protocol": str(offer.get("protocol") or raw.get("protocol") or "").strip(),
        "duration_value": str(offer.get("duration_value") or raw.get("duration_value") or "").strip(),
    }


def _proxy_markup_pct() -> float:
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
        "carrier": _norm_text(row.get("carrier"), provider_code.upper()),
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
        await _record_proxy_event_safe(
            event_type="catalog_fetch",
            provider=provider_code,
            success=True,
            extra={"rows": len(rows) if isinstance(rows, list) else 0},
        )
    except Exception:
        await _record_proxy_event_safe(
            event_type="catalog_fetch",
            provider=provider_code,
            success=False,
            reason="provider_list_offers_failed",
        )
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
        normalized_count = 0
        for row in rows:
            normalized = _normalize_offer(provider_code, row, markup_pct)
            if not normalized:
                continue
            normalized_count += 1
            key = (
                str(normalized.get("provider") or ""),
                str(normalized.get("offer_id") or ""),
                str(normalized.get("country") or ""),
                str(normalized.get("state") or ""),
                str(normalized.get("city") or ""),
                str(normalized.get("carrier") or ""),
                str(normalized.get("period") or ""),
            )
            if key not in dedup:
                dedup[key] = normalized
        await _record_proxy_event_safe(
            event_type="catalog_normalized",
            provider=provider_code,
            success=True,
            reason="catalog_ready",
            extra={"normalized_rows": normalized_count},
        )

    offers = list(dedup.values())
    offers.sort(
        key=lambda x: (
            str(x.get("country") or "Any"),
            str(x.get("state") or "Any"),
            str(x.get("city") or "Any"),
            str(x.get("carrier") or ""),
            float(x.get("price") or 0.0),
        )
    )
    return offers


async def rent_proxy_offer(offer: dict[str, Any]) -> dict[str, Any]:
    provider_code = str(offer.get("provider") or "").lower()
    provider = PROXY_PROVIDERS.get(provider_code)
    if not provider:
        await _record_proxy_event_safe(
            event_type="rent_offer",
            provider=provider_code or "unknown",
            success=False,
            reason="unknown_provider",
        )
        return {"success": False, "raw": {"title": "UNKNOWN_PROVIDER"}}
    result = await provider.rent_offer(offer)
    raw = result.get("raw")
    await _record_proxy_event_safe(
        event_type="rent_offer",
        provider=provider_code,
        success=bool(result.get("success")),
        reason=_proxy_event_reason(raw, str(result.get("message") or "")),
        extra={
            **_offer_event_extra(offer),
            "order_id": str(result.get("order_id") or "").strip(),
            "endpoint": str(result.get("endpoint") or "").strip(),
            "username": str(result.get("username") or "").strip(),
        },
    )
    return result


async def reserve_available_4g_username(prefix: str = "PH", *, attempts: int = 30) -> str:
    provider = PROXY_PROVIDERS.get("4g")
    if not provider or not hasattr(provider, "check_username_available"):
        return ""
    tried: set[str] = set()
    for _ in range(max(1, attempts)):
        candidate = f"{prefix}{secrets.randbelow(10000):04d}"
        if candidate in tried:
            continue
        tried.add(candidate)
        try:
            available = await provider.check_username_available(candidate)
        except Exception:
            continue
        if available:
            return candidate
    return ""


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
        await _record_proxy_event_safe(event_type="quality_check", provider="quality_gate", success=True, reason="pass")
        return {**result, "allowed": True}
    if decision == "fail":
        await _record_proxy_event_safe(
            event_type="quality_check",
            provider="quality_gate",
            success=False,
            reason=str(result.get("reason") or "fail")[:120],
        )
        return {**result, "allowed": False}
    # gray
    if fail_closed:
        await _record_proxy_event_safe(event_type="quality_check", provider="quality_gate", success=False, reason="gray_fail_closed")
        return {**result, "allowed": False, "decision": "gray_fail"}
    await _record_proxy_event_safe(event_type="quality_check", provider="quality_gate", success=True, reason="gray_pass")
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
        await _record_proxy_event_safe(event_type="refresh_proxy", provider=provider_code or "unknown", success=False, reason="unknown_provider")
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
                await _record_proxy_event_safe(
                    event_type="refresh_proxy",
                    provider=provider_code,
                    success=False,
                    reason=str(quality.get("reason") or "quality_fail")[:120],
                    extra={
                        "attempts": idx,
                        "with_check": True,
                        "order_id": str(order_data.get("_id") or "").strip(),
                        "provider_order_id": str(order_data.get("provider_order_id") or order_data.get("proxy_provider_order_id") or "").strip(),
                    },
                )
                return {
                    "success": False,
                    "raw": last_raw,
                    "quality": quality,
                    "attempts": idx,
                    "billable": False,
                }
            result = {
                "success": True,
                **refreshed,
                "quality": quality,
                "attempts": idx,
                "billable": True,
            }
            await _record_proxy_event_safe(
                event_type="refresh_proxy",
                provider=provider_code,
                success=True,
                reason="quality_ok",
                extra={
                    "attempts": idx,
                    "with_check": True,
                    "order_id": str(order_data.get("_id") or "").strip(),
                    "provider_order_id": str(order_data.get("provider_order_id") or order_data.get("proxy_provider_order_id") or "").strip(),
                    "endpoint": str(refreshed.get("endpoint") or "").strip(),
                },
            )
            return result

        result = {
            "success": True,
            **refreshed,
            "attempts": idx,
            "billable": False,
        }
        await _record_proxy_event_safe(
            event_type="refresh_proxy",
            provider=provider_code,
            success=True,
            reason="refreshed",
            extra={
                "attempts": idx,
                "with_check": False,
                "order_id": str(order_data.get("_id") or "").strip(),
                "provider_order_id": str(order_data.get("provider_order_id") or order_data.get("proxy_provider_order_id") or "").strip(),
                "endpoint": str(refreshed.get("endpoint") or "").strip(),
            },
        )
        return result

    result = {"success": False, "raw": last_raw or {"title": "REFRESH_FAILED"}, "attempts": attempts}
    await _record_proxy_event_safe(
        event_type="refresh_proxy",
        provider=provider_code,
        success=bool(result.get("success")),
        reason=_proxy_event_reason(result.get("raw"), "refresh_failed"),
        extra={
            "attempts": attempts,
            "with_check": bool(with_check),
            "order_id": str(order_data.get("_id") or "").strip(),
            "provider_order_id": str(order_data.get("provider_order_id") or order_data.get("proxy_provider_order_id") or "").strip(),
        },
    )
    return result


async def reconfigure_proxy_order(
    order_data: dict[str, Any],
    offer: dict[str, Any],
    *,
    with_check: bool = True,
) -> dict[str, Any]:
    provider_code = str(order_data.get("provider") or offer.get("provider") or "").lower()
    provider = PROXY_PROVIDERS.get(provider_code)
    if not provider:
        await _record_proxy_event_safe(event_type="reconfigure_proxy", provider=provider_code or "unknown", success=False, reason="unknown_provider")
        return {"success": False, "raw": {"title": "UNKNOWN_PROVIDER"}}

    result = await provider.reconfigure_proxy(order_data, offer)
    raw = result.get("raw")
    if not result.get("success"):
        await _record_proxy_event_safe(
            event_type="reconfigure_proxy",
            provider=provider_code,
            success=False,
            reason=_proxy_event_reason(raw, str(result.get("message") or "")),
            extra={
                "order_id": str(order_data.get("_id") or "").strip(),
                "provider_order_id": str(order_data.get("provider_order_id") or order_data.get("proxy_provider_order_id") or "").strip(),
                **_offer_event_extra(offer),
            },
        )
        return result

    if with_check:
        endpoint = str(result.get("endpoint") or order_data.get("proxy_endpoint") or "").strip()
        quality = await verify_proxy_offer_delivery(endpoint)
        if not quality.get("allowed"):
            await _record_proxy_event_safe(
                event_type="reconfigure_proxy",
                provider=provider_code,
                success=False,
                reason=str(quality.get("reason") or "quality_fail")[:120],
                extra={
                    "order_id": str(order_data.get("_id") or "").strip(),
                    "provider_order_id": str(order_data.get("provider_order_id") or order_data.get("proxy_provider_order_id") or "").strip(),
                    **_offer_event_extra(offer),
                },
            )
            return {
                "success": False,
                **result,
                "quality": quality,
            }
        result = {**result, "quality": quality}

    await _record_proxy_event_safe(
        event_type="reconfigure_proxy",
        provider=provider_code,
        success=True,
        reason="reconfigured",
        extra={
            "order_id": str(order_data.get("_id") or "").strip(),
            "provider_order_id": str(order_data.get("provider_order_id") or order_data.get("proxy_provider_order_id") or "").strip(),
            "endpoint": str(result.get("endpoint") or "").strip(),
            **_offer_event_extra(offer),
        },
    )
    return result
