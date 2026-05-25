from __future__ import annotations

from typing import Any, Awaitable, Callable

from database.orders_repo import list_api_temp_orders_for_auto_refund, update_order_details
from services.numbers.order_cancel_service import cancel_number_order
from services.numbers.order_service import public_order_payload
from services.numbers.shared.temp_order import _order_temp_timeout_sec, _temp_elapsed_sec, _temp_order_has_received_code, _utc_now
from services.numbers.shared.temp_refund import temp_refund_result_retryable


_CLOSED_STATUSES = {"cancelled", "failed", "refunded", "expired"}


async def auto_refund_temp_order_if_due(
    order: dict[str, Any],
    *,
    sleep_fn: Callable[[float], Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(order, dict) or not order.get("_id"):
        return {"ok": False, "refunded": False, "reason": "order_not_found"}

    if str(order.get("number_mode") or "temp").strip().lower() != "temp":
        return {"ok": True, "refunded": False, "reason": "unsupported_mode", "order": public_order_payload(order)}

    if str(order.get("status") or "").strip().lower() in _CLOSED_STATUSES:
        return {"ok": True, "refunded": False, "reason": "already_closed", "order": public_order_payload(order)}

    if _temp_order_has_received_code(order):
        return {"ok": True, "refunded": False, "reason": "code_received", "order": public_order_payload(order)}

    elapsed = _temp_elapsed_sec(order)
    timeout_sec = _order_temp_timeout_sec(order)
    if elapsed < timeout_sec:
        return {
            "ok": True,
            "refunded": False,
            "reason": "not_due",
            "seconds_left": max(0, int(timeout_sec) - int(elapsed)),
            "order": public_order_payload(order),
        }

    user_id = int(order.get("user_id") or 0)
    if user_id <= 0:
        return {"ok": False, "refunded": False, "reason": "missing_user_id", "order": public_order_payload(order)}

    try:
        result = await cancel_number_order(order, actor_user_id=user_id, sleep_fn=sleep_fn)
    except Exception as exc:
        reason = getattr(exc, "code", "auto_refund_failed")
        return {
            "ok": True,
            "refunded": False,
            "support_review_required": not temp_refund_result_retryable({"success": False, "reason": reason}),
            "reason": str(reason),
            "order": public_order_payload(order),
        }
    return {"ok": True, "refunded": True, "reason": "timeout_no_code", "order": result.get("order") or public_order_payload(order)}


async def run_numbers_api_auto_refund_sweep(
    *,
    limit: int = 200,
    sleep_fn: Callable[[float], Awaitable[Any]] | None = None,
) -> dict[str, int]:
    stats = {"checked": 0, "refunded": 0, "skipped": 0, "support_review": 0, "errors": 0}
    orders = await list_api_temp_orders_for_auto_refund(limit=int(limit))
    for order in orders:
        stats["checked"] += 1
        try:
            result = await auto_refund_temp_order_if_due(order, sleep_fn=sleep_fn)
        except Exception:
            stats["errors"] += 1
            await _mark_support_review(order, "auto_refund_exception")
            continue
        if result.get("refunded"):
            stats["refunded"] += 1
        elif result.get("support_review_required"):
            stats["support_review"] += 1
            await _mark_support_review(order, str(result.get("reason") or "auto_refund_failed"))
        else:
            stats["skipped"] += 1
    return stats


async def _mark_support_review(order: dict[str, Any], reason: str) -> None:
    order_id = order.get("_id") if isinstance(order, dict) else None
    if not order_id:
        return
    await update_order_details(
        order_id,
        {
            "temp_refund_support_review_required": True,
            "temp_refund_support_review_reason": str(reason or "auto_refund_failed"),
            "temp_refund_support_review_at": _utc_now(),
        },
    )
