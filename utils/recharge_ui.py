from __future__ import annotations

from aiogram import types


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def owner_reseller_topup_review_kb(request_id) -> types.InlineKeyboardMarkup:
    rid = str(request_id)
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Accept Sent Amount", callback_data=f"owner_rchg:accept:{rid}")],
            [types.InlineKeyboardButton(text="Manual Amount", callback_data=f"owner_rchg:manual:{rid}")],
            [types.InlineKeyboardButton(text="Reject", callback_data=f"owner_rchg:reject:{rid}")],
        ]
    )


def format_owner_reseller_topup_text(req: dict, *, include_approved: bool = True) -> str:
    details = req.get("details") or {}
    paid_amount = _as_float(details.get("paid_amount"), 0.0)
    paid_currency = str(details.get("paid_currency", "USD")).upper()
    expected_credits = _as_float(details.get("credits", req.get("amount")), 0.0)
    approved_amount = _as_float(req.get("approved_amount"), 0.0)
    status = str(req.get("status") or "-")

    lines = [
        "Reseller Core Wallet Topup Request",
        "",
        f"Request ID: {req.get('_id')}",
        f"Reseller ID: {int(_as_float(req.get('reseller_id'), 0))}",
        f"Method: {req.get('method')}",
        f"Paid: {paid_amount:.2f} {paid_currency}",
        f"Expected Credits: {expected_credits:.4f}",
    ]
    if include_approved:
        lines.append(f"Approved Credits: {approved_amount:.4f}")
    lines.append(f"Status: {status}")
    return "\n".join(lines)


def user_recharge_review_kb(request_id) -> types.InlineKeyboardMarkup:
    rid = str(request_id)
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Add Sent Amount", callback_data=f"recharge_accept_{rid}")],
            [types.InlineKeyboardButton(text="Add Manual Amount", callback_data=f"recharge_manual_{rid}")],
            [types.InlineKeyboardButton(text="Need More Proof", callback_data=f"recharge_needproof_{rid}")],
            [types.InlineKeyboardButton(text="Reject", callback_data=f"recharge_reject_{rid}")],
        ]
    )
