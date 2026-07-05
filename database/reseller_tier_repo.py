"""Persistence for the monthly reseller-tier review: read a website reseller's
own monthly purchase volume and list/update reseller accounts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from database.mongo import db
from services.digital_products.reseller_pricing import TIERS

_PAID_STATUSES = ["paid", "success", "done", "completed"]


def previous_month_range(now: datetime) -> tuple[datetime, datetime]:
    """[start, end) of the calendar month just BEFORE `now` (the completed month)."""
    first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_last = first_this - timedelta(days=1)
    start = prev_last.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, first_this


async def sum_account_month_spend(customer_id: int, *, start: datetime, end: datetime) -> float:
    """Total USD the account PAID for its own orders in [start, end) — a reseller's
    tier is driven by their monthly spend on Phantom (retail_amount = what they paid,
    which for a reseller is the wholesale price)."""
    orders = getattr(db, "orders", None)
    if orders is None or not hasattr(orders, "aggregate"):
        return 0.0
    cursor = orders.aggregate(
        [
            {
                "$match": {
                    "user_id": int(customer_id),
                    "status": {"$in": _PAID_STATUSES},
                    "created_at": {"$gte": start, "$lt": end},
                }
            },
            {"$project": {"amount": {"$ifNull": ["$retail_amount", {"$ifNull": ["$selling_price", 0]}]}}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]
    )
    rows = await cursor.to_list(length=1)
    return float((rows[0] if rows else {}).get("total") or 0.0)


async def list_reseller_accounts() -> list[dict]:
    return await db.website_accounts.find({"reseller_tier": {"$in": list(TIERS)}}).to_list(None)


async def set_account_tier_state(customer_id: int, tier: str, miss_streak: int, *, now: datetime) -> None:
    await db.website_accounts.update_one(
        {"customer_id": int(customer_id)},
        {
            "$set": {
                "reseller_tier": str(tier),
                "reseller_miss_streak": int(miss_streak),
                "reseller_tier_reviewed_at": now,
                "updated_at": now,
            }
        },
    )
