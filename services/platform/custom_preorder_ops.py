from __future__ import annotations

from typing import Any

from database.custom_services_repo import (
    get_next_pending_preorder,
    get_preorder_request,
    mark_preorder_fulfilling,
    mark_preorder_fulfilled,
    mark_preorder_refunding,
    mark_preorder_rejected,
    reset_preorder_to_pending,
)
from database.orders_repo import update_order_details, update_order_status
from services.platform.telegram_delivery import send_source_bot_message
from utils.financial_manager import FinancialManager


def available_preorder_actions(preorder: dict[str, Any]) -> list[str]:
    status = str((preorder or {}).get("status") or "").strip().lower()
    if status == "pending":
        return ["fulfill", "reject"]
    if status == "fulfilling":
        return ["release", "fulfill", "reject"]
    return []


async def fulfill_preorder_from_owner(
    preorder_id: str,
    *,
    actor_id: int,
    delivery_text: str,
) -> tuple[bool, str, dict[str, Any] | None]:
    preorder = await get_preorder_request(preorder_id)
    if not preorder:
        return False, "not_found", None
    status = str(preorder.get("status") or "")
    if status == "fulfilled":
        return False, "already_fulfilled", preorder
    if status not in {"pending", "fulfilling"}:
        return False, "not_fulfillable", preorder

    text = str(delivery_text or "").strip()
    if len(text) < 2 or len(text) > 3500:
        return False, "invalid_delivery_text", preorder

    if status == "pending":
        next_pending = await get_next_pending_preorder(preorder.get("endpoint_id"))
        if next_pending and str(next_pending.get("_id")) != str(preorder.get("_id")):
            return False, "fifo_violation", preorder
        claimed = await mark_preorder_fulfilling(preorder["_id"], actor_id=actor_id)
        if not claimed:
            return False, "claim_conflict", preorder
        preorder = claimed

    delivered = await send_source_bot_message(
        source_bot_id=int(preorder.get("source_bot_id") or 0),
        user_id=int(preorder.get("buyer_user_id") or 0),
        text=text,
    )
    if not delivered:
        return False, "delivery_failed", preorder

    fulfilled = await mark_preorder_fulfilled(preorder["_id"], actor_id=actor_id)
    if not fulfilled:
        return False, "status_conflict", preorder
    order_id = preorder.get("order_id")
    if order_id:
        await update_order_details(
            order_id,
            {
                "status": "success",
                "custom_preorder_fulfilled_manually": True,
                "custom_preorder_fulfilled_by": int(actor_id),
                "custom_preorder_delivery_text": text,
            },
        )
        await update_order_status(order_id, "success")
    return True, "fulfilled", fulfilled


async def release_preorder_from_owner(
    preorder_id: str,
    *,
    actor_id: int,
) -> tuple[bool, str, dict[str, Any] | None]:
    preorder = await get_preorder_request(preorder_id)
    if not preorder:
        return False, "not_found", None
    if str(preorder.get("status") or "") != "fulfilling":
        return False, "not_fulfilling", preorder
    row = await reset_preorder_to_pending(preorder["_id"])
    return (True, "released", row) if row else (False, "status_conflict", preorder)


async def reject_preorder_from_owner(
    preorder_id: str,
    *,
    actor_id: int,
    reason: str,
) -> tuple[bool, str, dict[str, Any] | None]:
    preorder = await get_preorder_request(preorder_id)
    if not preorder:
        return False, "not_found", None
    status = str(preorder.get("status") or "")
    if status in {"fulfilled", "rejected"}:
        return False, f"already_{status}", preorder

    order_id = preorder.get("order_id")
    buyer_user_id = int(preorder.get("buyer_user_id") or 0)
    wallet_scope_id = int(preorder.get("wallet_scope_id") or preorder.get("catalog_owner_id") or 0)
    if not order_id or buyer_user_id <= 0 or wallet_scope_id <= 0:
        return False, "incomplete_refund_data", preorder

    refunding = await mark_preorder_refunding(preorder["_id"], actor_id=actor_id)
    if not refunding:
        return False, "status_conflict", preorder
    ok, refund_reason = await FinancialManager.refund_custom_purchase(
        buyer_user_id,
        str(order_id),
        float(preorder.get("total_price") or 0.0),
        reseller_id=wallet_scope_id,
    )
    if not ok:
        await reset_preorder_to_pending(preorder["_id"])
        return False, f"refund_failed:{refund_reason}", preorder

    clean_reason = str(reason or "").strip() or "owner_rejected"
    rejected = await mark_preorder_rejected(preorder["_id"], actor_id=actor_id, reason=clean_reason)
    if not rejected:
        return False, "refund_applied_status_conflict", preorder
    await update_order_details(
        order_id,
        {
            "status": "refunded",
            "custom_preorder_rejected": True,
            "custom_preorder_rejected_by": int(actor_id),
            "custom_preorder_reject_reason": clean_reason,
        },
    )
    await update_order_status(order_id, "refunded")
    await send_source_bot_message(
        source_bot_id=int(preorder.get("source_bot_id") or 0),
        user_id=buyer_user_id,
        text=f"Your preorder was rejected and {float(preorder.get('total_price') or 0.0):.2f} USD was refunded.\nReason: {clean_reason}",
    )
    return True, "rejected", rejected
