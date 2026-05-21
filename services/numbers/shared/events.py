"""Shared event logging helpers for Numbers orders."""

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("numbers_buy")


def _number_event_context_from_order(
    order: dict | None,
    *,
    number_mode: str | None = None,
    extract_order_amounts: Callable[[dict], tuple[float, float]],
) -> dict[str, Any]:
    order = order or {}
    sale_price, cost_price = extract_order_amounts(order)
    return {
        "order_id": order.get("_id"),
        "user_id": int(order.get("user_id") or 0),
        "reseller_id": int(order.get("reseller_id") or 0) or None,
        "provider": str(order.get("provider") or order.get("provisioning_provider") or ""),
        "service_id": str(order.get("service_id") or ""),
        "number_mode": str(number_mode or order.get("number_mode") or "").strip().lower(),
        "status_before": str(order.get("status") or ""),
        "sale_price": sale_price,
        "cost_price": cost_price,
        "provider_order_id": str(order.get("provider_order_id") or ""),
        "provider_number": str(order.get("provider_number") or ""),
        "country": str(order.get("temp_country") or order.get("rental_country") or order.get("provisioning_country") or ""),
        "state": str(order.get("temp_state") or order.get("rental_state_code") or order.get("provisioning_state_code") or ""),
    }


async def _log_number_event_from_order(
    order: dict | None,
    event: str,
    *,
    payload: dict | None = None,
    status_after: str | None = None,
    number_mode: str | None = None,
    extract_order_amounts: Callable[[dict], tuple[float, float]],
    number_events_repo_obj: Any,
) -> None:
    try:
        ctx = _number_event_context_from_order(
            order,
            number_mode=number_mode,
            extract_order_amounts=extract_order_amounts,
        )
        await number_events_repo_obj.log_number_order_event(
            order_id=ctx["order_id"],
            user_id=ctx["user_id"],
            reseller_id=ctx["reseller_id"],
            provider=ctx["provider"],
            service_id=ctx["service_id"],
            number_mode=ctx["number_mode"],
            event=event,
            status_before=ctx["status_before"],
            status_after=status_after,
            sale_price=ctx["sale_price"],
            cost_price=ctx["cost_price"],
            provider_order_id=ctx["provider_order_id"],
            provider_number=ctx["provider_number"],
            country=ctx["country"],
            state=ctx["state"],
            payload=payload or {},
        )
    except Exception:
        logger.exception("number event log failed: event=%s order=%s", event, (order or {}).get("_id"))


async def _log_temp_event(
    order: dict,
    event: str,
    *,
    payload: dict | None = None,
    temp_number_stats_repo_obj: Any,
    log_number_event_from_order_cb: Callable[..., Awaitable[None]],
) -> None:
    order = order or {}
    enriched_payload = dict(payload or {})
    enriched_payload.setdefault(
        "country",
        str(order.get("temp_country") or order.get("provisioning_country") or "").strip(),
    )
    enriched_payload.setdefault(
        "state",
        str(order.get("temp_state") or order.get("provisioning_state_code") or "none").strip() or "none",
    )
    enriched_payload.setdefault(
        "api_service",
        str(order.get("temp_api_service") or order.get("provisioning_service") or "").strip(),
    )
    try:
        await temp_number_stats_repo_obj.log_temp_number_event(
            order.get("_id"),
            user_id=int(order.get("user_id") or 0),
            provider=str(order.get("provider") or ""),
            service_id=str(order.get("service_id") or ""),
            event=event,
            payload=enriched_payload,
        )
    except Exception:
        logger.exception("temp event log failed: event=%s order=%s", event, order.get("_id"))
    await log_number_event_from_order_cb(order, event, payload=enriched_payload, number_mode="temp")


async def _log_rental_event(
    *,
    order_id: Any,
    user_id: int,
    provider: str,
    service_id: str,
    event: str,
    payload: dict | None = None,
    log_number_event_from_order_cb: Callable[..., Awaitable[None]],
) -> None:
    await log_number_event_from_order_cb(
        {
            "_id": order_id,
            "user_id": int(user_id or 0),
            "reseller_id": None,
            "provider": provider,
            "service_id": service_id,
            "number_mode": "rental",
        },
        event,
        payload=payload,
        number_mode="rental",
    )
