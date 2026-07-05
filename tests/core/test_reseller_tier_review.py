import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.getcwd())

import pytest

from services.digital_products import reseller_tier_review as review
from services.digital_products.reseller_pricing import DEFAULT_CONFIG
from database.reseller_tier_repo import previous_month_range


def test_previous_month_range_is_the_completed_calendar_month():
    start, end = previous_month_range(datetime(2026, 7, 5, 12, 0, tzinfo=UTC))
    assert start == datetime(2026, 6, 1, tzinfo=UTC)
    assert end == datetime(2026, 7, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_run_reseller_tier_review_promotes_and_demotes(monkeypatch):
    accounts = [
        {"customer_id": 1, "reseller_tier": "bronze", "reseller_miss_streak": 0},   # sells 1200 -> gold
        {"customer_id": 2, "reseller_tier": "silver", "reseller_miss_streak": 1},   # sells 100  -> demote to bronze
        {"customer_id": 3, "reseller_tier": "gold", "reseller_miss_streak": 0},     # sells 1500 -> stays gold
    ]
    spend = {1: 1200.0, 2: 100.0, 3: 1500.0}
    saved = {}

    async def fake_cfg():
        return DEFAULT_CONFIG

    async def fake_list():
        return accounts

    async def fake_spend(customer_id, *, start, end):
        return spend[customer_id]

    async def fake_save(customer_id, tier, miss_streak, *, now):
        saved[customer_id] = (tier, miss_streak)

    monkeypatch.setattr(review, "get_pricing_config", fake_cfg)
    monkeypatch.setattr(review, "list_reseller_accounts", fake_list)
    monkeypatch.setattr(review, "sum_account_month_spend", fake_spend)
    monkeypatch.setattr(review, "set_account_tier_state", fake_save)

    summary = await review.run_reseller_tier_review(now=datetime(2026, 8, 1, tzinfo=UTC))

    assert summary["reviewed"] == 3
    assert saved[1] == ("gold", 0)      # promoted
    assert saved[2] == ("bronze", 0)    # demoted one level
    assert 3 not in saved               # gold maintained -> no write
    assert summary["changed"] == 2
    assert summary["month"] == "2026-07"
