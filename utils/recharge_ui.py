from __future__ import annotations

from aiogram import types
from utils.translations import t


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def owner_reseller_topup_review_kb(request_id, lang: str = "en") -> types.InlineKeyboardMarkup:
    rid = str(request_id)
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=t(lang, "owner_accept_sent_amount_button"), callback_data=f"owner_rchg:accept:{rid}")],
            [types.InlineKeyboardButton(text=t(lang, "owner_manual_amount_button"), callback_data=f"owner_rchg:manual:{rid}")],
            [types.InlineKeyboardButton(text=t(lang, "owner_reject_button"), callback_data=f"owner_rchg:reject:{rid}")],
        ]
    )


def format_owner_reseller_topup_text(req: dict, *, include_approved: bool = True, lang: str = "en") -> str:
    details = req.get("details") or {}
    paid_amount = _as_float(details.get("paid_amount"), 0.0)
    paid_currency = str(details.get("paid_currency", "USD")).upper()
    expected_credits = _as_float(details.get("credits", req.get("amount")), 0.0)
    approved_amount = _as_float(req.get("approved_amount"), 0.0)
    status = str(req.get("status") or "-")

    lines = [
        t(lang, "owner_reseller_topup_request_title"),
        "",
        t(lang, "owner_request_id_line").format(request_id=req.get("_id")),
        t(lang, "owner_reseller_id_line").format(reseller_id=int(_as_float(req.get("reseller_id"), 0))),
        t(lang, "owner_method_line").format(method=req.get("method")),
        t(lang, "owner_paid_line").format(paid_amount=paid_amount, paid_currency=paid_currency),
        t(lang, "owner_expected_credits_line").format(expected_credits=expected_credits),
    ]
    if include_approved:
        lines.append(t(lang, "owner_approved_credits_line").format(approved_amount=approved_amount))
    lines.append(t(lang, "owner_status_line").format(status=status))
    return "\n".join(lines)


def user_recharge_review_kb(request_id, lang: str = "en") -> types.InlineKeyboardMarkup:
    rid = str(request_id)
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=t(lang, "reseller_add_sent_amount_button"), callback_data=f"recharge_accept_{rid}")],
            [types.InlineKeyboardButton(text=t(lang, "reseller_add_manual_amount_button"), callback_data=f"recharge_manual_{rid}")],
            [types.InlineKeyboardButton(text=t(lang, "reseller_need_more_proof_button"), callback_data=f"recharge_needproof_{rid}")],
            [types.InlineKeyboardButton(text=t(lang, "owner_reject_button"), callback_data=f"recharge_reject_{rid}")],
        ]
    )
