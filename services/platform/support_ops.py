from __future__ import annotations

from typing import Any

from database.bots_repo import get_reseller_id_for_bot
from database.financial_ledger import credit_user_wallet
from database.support_tickets_repo import (
    begin_support_ticket_bug_reward,
    mark_support_ticket_bug_reward_failed,
    mark_support_ticket_bug_reward_paid,
)
from database.user_repo import get_user_reseller_for_bot, set_user_reseller_for_bot
from services.platform.telegram_delivery import send_ticket_message
from utils.bot_menu_context import is_digital_products_bot, is_main_bot, is_numbers_bot


async def resolve_ticket_wallet_scope(ticket: dict[str, Any]) -> int | None:
    user_id = int((ticket or {}).get("user_id") or 0)
    source_bot_id = int((ticket or {}).get("source_bot_id") or 0)
    if user_id <= 0 or source_bot_id <= 0:
        return None
    if await is_main_bot(source_bot_id) or await is_digital_products_bot(source_bot_id) or await is_numbers_bot(source_bot_id):
        return user_id
    reseller_id = await get_user_reseller_for_bot(user_id, source_bot_id)
    if reseller_id:
        return int(reseller_id)
    inferred = await get_reseller_id_for_bot(source_bot_id)
    if inferred:
        await set_user_reseller_for_bot(user_id, source_bot_id, int(inferred))
        return int(inferred)
    return None


async def pay_ticket_bug_reward(
    ticket: dict[str, Any],
    *,
    actor_id: int,
    amount: float = 1.0,
) -> tuple[bool, str, dict[str, Any] | None]:
    ticket_id = str((ticket or {}).get("_id") or "").strip()
    if not ticket_id:
        return False, "ticket_id_missing", None
    if str((((ticket or {}).get("bug_reward") or {}).get("status")) or "").lower() == "paid":
        return False, "already_paid", ticket

    claimed = await begin_support_ticket_bug_reward(ticket_id, actor_id=actor_id, amount=amount)
    if not claimed:
        return False, "already_processing", ticket
    wallet_scope_id = await resolve_ticket_wallet_scope(ticket)
    if not wallet_scope_id:
        await mark_support_ticket_bug_reward_failed(ticket_id, actor_id=actor_id, error="wallet_scope_missing")
        return False, "wallet_scope_missing", claimed
    try:
        ledger = await credit_user_wallet(
            int(ticket.get("user_id") or 0),
            int(wallet_scope_id),
            float(amount),
            "support_bug_reward",
            actor_id=int(actor_id),
            order_id=ticket_id,
        )
    except Exception as exc:
        await mark_support_ticket_bug_reward_failed(ticket_id, actor_id=actor_id, error=str(exc))
        return False, "credit_failed", claimed
    await mark_support_ticket_bug_reward_paid(
        ticket_id,
        actor_id=actor_id,
        amount=float(amount),
        wallet_scope_id=int(wallet_scope_id),
        ledger_id=(ledger or {}).get("_id"),
    )
    await send_ticket_message(ticket, f"A {float(amount):.2f} USD reward was added to your balance for your confirmed bug report.")
    return True, "paid", {
        "amount": float(amount),
        "wallet_scope_id": int(wallet_scope_id),
        "ledger_id": str((ledger or {}).get("_id") or ""),
    }
