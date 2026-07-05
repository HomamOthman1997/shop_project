"""Monthly reseller-tier review: for each website reseller, look at the completed
calendar month's spend and promote / hold (protection) / demote (one level) their
tier per the agreed rules. Idempotent — safe to run more than once for a month."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from database.reseller_pricing_config_repo import get_pricing_config
from database.reseller_tier_repo import (
    list_reseller_accounts,
    previous_month_range,
    set_account_tier_state,
    sum_account_month_spend,
)
from services.digital_products.reseller_pricing import review_tier

logger = logging.getLogger("reseller_tier_review")


async def run_reseller_tier_review(*, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    start, end = previous_month_range(now)
    cfg = await get_pricing_config()
    accounts = await list_reseller_accounts()
    changes: list[dict] = []
    reviewed = 0
    for account in accounts:
        customer_id = int(account.get("customer_id") or 0)
        if customer_id <= 0:
            continue
        reviewed += 1
        current_tier = str(account.get("reseller_tier") or "").strip().lower()
        streak = int(account.get("reseller_miss_streak") or 0)
        spend = await sum_account_month_spend(customer_id, start=start, end=end)
        new_tier, new_streak, changed = review_tier(current_tier, spend, streak, cfg)
        if new_tier != current_tier or new_streak != streak:
            await set_account_tier_state(customer_id, new_tier, new_streak, now=now)
        if changed:
            changes.append({
                "customer_id": customer_id,
                "from": current_tier,
                "to": new_tier,
                "spend": round(spend, 2),
            })
    summary = {
        "reviewed": reviewed,
        "changed": len(changes),
        "changes": changes,
        "month": start.strftime("%Y-%m"),
    }
    logger.info("reseller tier review: %s", summary)
    return summary
