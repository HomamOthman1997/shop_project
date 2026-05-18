from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from config import settings
from database.cardex_repo import (
    accept_card,
    create_card_submission,
    create_pricing_rule,
    create_trader,
    create_trader_batch,
    create_withdrawal,
    deactivate_pricing_rule,
    ensure_cardex_wallet,
    get_or_create_cardex_user,
    get_missing_pricing,
    list_active_pricing_rules,
    list_audit_logs,
    list_cards_for_review,
    list_cards_for_daily_export,
    list_cards_for_user,
    list_missing_pricing,
    list_open_withdrawals,
    list_top_card_brands,
    list_traders,
    list_withdrawals_for_user,
    post_trader_payment,
    queue_missing_pricing,
    reject_card,
    search_card_brands,
    find_active_pricing_rule,
    trader_statement,
    update_withdrawal_status,
)


def parse_decimal(text: str) -> Decimal:
    try:
        value = Decimal(str(text).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("invalid decimal value")
    if value <= 0:
        raise ValueError("value must be positive")
    return value


async def ensure_user_from_telegram(tg_user) -> dict[str, Any]:
    full_name = f"{getattr(tg_user, 'first_name', '')} {getattr(tg_user, 'last_name', '')}".strip() or None
    return await get_or_create_cardex_user(
        telegram_user_id=int(getattr(tg_user, "id", 0) or 0),
        telegram_username=getattr(tg_user, "username", None),
        full_name=full_name,
        owner_telegram_user_id=int(getattr(settings, "owner_id", 0) or 0),
    )


async def get_wallet_snapshot(user_id: str) -> dict[str, Any]:
    return await ensure_cardex_wallet(user_id)


async def quote_card_submission(
    *,
    brand: str,
    denomination: Decimal,
    currency: str,
    region: str | None,
) -> dict[str, Any]:
    rule = await find_active_pricing_rule(brand, denomination, currency, region)
    if rule is None:
        return {"configured": False, "rule": None}

    face = Decimal(str(denomination))
    customer_rate = Decimal(str(rule.get("customer_buy_rate_percent") or 0))
    trader_rate = Decimal(str(rule.get("trader_rate_percent") or 0))
    return {
        "configured": True,
        "rule": rule,
        "customer_buy_rate_percent": float(customer_rate),
        "trader_rate_percent": float(trader_rate),
        "customer_value_usd": float(face * customer_rate / Decimal("100")),
        "trader_value_usd": float(face * trader_rate / Decimal("100")),
        "public_note": str(rule.get("public_note") or "").strip() or None,
    }


async def submit_card(
    *,
    actor_user_id: str,
    brand: str,
    denomination: Decimal,
    currency: str,
    region: str | None,
    code: str,
    pin: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    rule = await find_active_pricing_rule(brand, denomination, currency, region)
    if rule is None:
        queued = await queue_missing_pricing(
            actor_user_id=actor_user_id,
            brand=brand,
            denomination=denomination,
            currency=currency,
            region=region,
        )
        return None, queued
    card = await create_card_submission(
        seller_user_id=actor_user_id,
        brand=brand,
        denomination=denomination,
        currency=currency,
        region=region,
        code=code,
        pin=pin,
        pricing_rule=rule,
    )
    return card, None


__all__ = [
    "accept_card",
    "create_pricing_rule",
    "create_trader",
    "create_trader_batch",
    "create_withdrawal",
    "deactivate_pricing_rule",
    "ensure_user_from_telegram",
    "get_missing_pricing",
    "get_wallet_snapshot",
    "list_active_pricing_rules",
    "list_audit_logs",
    "list_cards_for_review",
    "list_cards_for_daily_export",
    "list_cards_for_user",
    "list_missing_pricing",
    "list_open_withdrawals",
    "list_top_card_brands",
    "list_traders",
    "list_withdrawals_for_user",
    "parse_decimal",
    "post_trader_payment",
    "quote_card_submission",
    "reject_card",
    "search_card_brands",
    "submit_card",
    "trader_statement",
    "update_withdrawal_status",
]
