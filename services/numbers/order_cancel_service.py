from __future__ import annotations

from typing import Any, Awaitable, Callable

from database.orders_repo import get_order, update_order_details, update_order_status
from services.numbers.manager import PROVIDERS
from services.numbers.order_service import NumbersOrderError, public_order_payload
from services.numbers.shared.events import _log_number_event_from_order, _log_temp_event
from services.numbers.shared.temp_refund import cancel_and_refund_temp_order, temp_refund_result_retryable
from services.platform.webhooks import enqueue_event_for_user
from utils.financial_manager import FinancialManager


async def cancel_number_order(
    order: dict[str, Any],
    *,
    actor_user_id: int,
    reason: str = "numbers_api_user_cancel",
    source: str = "numbers_api_cancel",
    allow_provider_terminal_refund: bool = False,
    allow_empty_provider_refund: bool = False,
    sleep_fn: Callable[[float], Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(order, dict) or not order.get("_id"):
        raise NumbersOrderError("order_not_found", "Order was not found.", status=404)

    mode = str(order.get("number_mode") or "temp").strip().lower()
    if mode != "temp":
        raise NumbersOrderError("unsupported_order_mode", "This order mode does not support cancel yet.", status=409)

    result = await cancel_and_refund_temp_order(
        order_id=order["_id"],
        order=order,
        actor_user_id=int(actor_user_id),
        reason=str(reason or "numbers_api_user_cancel"),
        providers=PROVIDERS,
        financial_manager=FinancialManager,
        update_order_status_fn=update_order_status,
        update_order_details_fn=update_order_details,
        log_temp_event_fn=_log_temp_event,
        log_number_event_from_order_fn=_log_number_event_from_order,
        require_no_sms=True,
        source=str(source or "numbers_api_cancel"),
        allow_provider_terminal_refund=bool(allow_provider_terminal_refund),
        allow_empty_provider_refund=bool(allow_empty_provider_refund),
        sleep_fn=sleep_fn if sleep_fn is not None else _default_sleep,
    )
    refreshed = await get_order(order["_id"]) or order
    if not result.get("success"):
        code = str(result.get("reason") or "cancel_failed")
        status = 503 if temp_refund_result_retryable(result) else 409
        raise NumbersOrderError(code, "Could not cancel this order right now.", status=status)
    payload = {"ok": True, "order": public_order_payload(refreshed)}
    await enqueue_event_for_user(
        user_id=int(refreshed.get("user_id") or order.get("user_id") or 0),
        reseller_id=int(refreshed.get("reseller_id") or order.get("reseller_id") or order.get("user_id") or 0),
        event_type="numbers.order.refunded",
        data={"order": payload["order"]},
    )
    return payload


async def _default_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
