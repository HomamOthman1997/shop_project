from __future__ import annotations

from typing import Any, Awaitable, Callable

from database.orders_repo import list_api_temp_orders_for_auto_refund, update_order_details
from services.numbers.order_cancel_service import cancel_number_order
from services.numbers.order_service import public_order_payload
from services.numbers.provider_readiness import provider_readiness
from services.numbers.shared.events import _log_temp_event
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

    provider_code = str(order.get("provider") or order.get("provisioning_provider") or "").strip().lower()
    readiness = provider_readiness(provider_code)
    if not readiness.auto_refund_enabled:
        await _mark_support_review(order, f"auto_refund_disabled_{readiness.status}")
        return {
            "ok": True,
            "refunded": False,
            "support_review_required": True,
            "reason": f"auto_refund_disabled_{readiness.status}",
            "order": public_order_payload(order),
        }

    try:
        result = await cancel_number_order(
            order,
            actor_user_id=user_id,
            reason="numbers_api_timeout_auto_refund",
            source="numbers_api_auto_refund",
            allow_provider_terminal_refund=True,
            allow_empty_provider_refund=True,
            sleep_fn=sleep_fn,
        )
    except Exception as exc:
        reason = getattr(exc, "code", "auto_refund_failed")
        retryable = _auto_refund_exception_retryable(exc, str(reason))
        marked_order = order
        if retryable:
            marked_order = await _mark_refund_pending(order, str(reason))
        else:
            marked_order = await _mark_support_review(order, str(reason))
        return {
            "ok": True,
            "refunded": False,
            "support_review_required": not retryable,
            "reason": str(reason),
            "order": public_order_payload(marked_order),
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


async def _mark_support_review(order: dict[str, Any], reason: str) -> dict[str, Any]:
    order_id = order.get("_id") if isinstance(order, dict) else None
    if not order_id:
        return order
    now = _utc_now()
    patch = {
        "temp_wait_timeout_at": (order or {}).get("temp_wait_timeout_at") or now,
        "temp_wait_state": "refund_pending",
        "temp_replace_enabled": True,
        "temp_refund_support_review_required": True,
        "temp_refund_support_review_status": "open",
        "temp_refund_support_review_reason": str(reason or "auto_refund_failed"),
        "temp_refund_support_review_at": now,
    }
    await update_order_details(order_id, patch)
    return {**order, **patch}


def _auto_refund_exception_retryable(exc: Exception, reason: str) -> bool:
    status = int(getattr(exc, "status", 0) or 0)
    if status >= 500:
        return True
    return temp_refund_result_retryable({"success": False, "reason": reason, "retryable": status >= 500})


async def _mark_refund_pending(order: dict[str, Any], reason: str) -> dict[str, Any]:
    order_id = order.get("_id") if isinstance(order, dict) else None
    if not order_id:
        return order
    now = _utc_now()
    attempts = int((order or {}).get("temp_refund_retry_attempts") or 0) + 1
    patch = {
        "temp_wait_timeout_at": (order or {}).get("temp_wait_timeout_at") or now,
        "temp_wait_state": "refund_pending",
        "temp_replace_enabled": True,
        "temp_refund_retry_attempts": attempts,
        "temp_refund_retry_last_at": now,
        "temp_refund_retry_reason": str(reason or "provider_cancel_failed"),
    }
    await update_order_details(order_id, patch)
    await _log_temp_event(
        order,
        "refund_pending",
        {
            "source": "numbers_api_auto_refund",
            "attempts": attempts,
            "reason": str(reason or ""),
        },
    )
    return {**order, **patch}
