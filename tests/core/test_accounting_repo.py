import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.getcwd())

import pytest

import database.accounting_repo as accounting


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, _length=None):
        return self._rows


class _Orders:
    def __init__(self, rows):
        self._rows = rows
        self.pipelines = []

    def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
        return _Cursor(self._rows)


class _Db:
    def __init__(self, rows):
        self.orders = _Orders(rows)


@pytest.mark.asyncio
async def test_profit_and_loss_totals_and_breakdown(monkeypatch):
    rows = [
        {"_id": "core_digital_products", "revenue": 100.0, "cost": 70.0, "orders": 5},
        {"_id": "numbers", "revenue": 50.0, "cost": 40.0, "orders": 3},
    ]
    monkeypatch.setattr(accounting, "db", _Db(rows))

    result = await accounting.profit_and_loss(
        start=datetime(2026, 6, 1, tzinfo=UTC), end=datetime(2026, 7, 1, tzinfo=UTC)
    )

    assert result["revenue"] == 150.0
    assert result["cost"] == 110.0
    assert result["profit"] == 40.0
    assert result["orders"] == 8
    # sorted by revenue desc
    assert [row["service"] for row in result["by_service"]] == ["core_digital_products", "numbers"]
    assert result["by_service"][0]["profit"] == 30.0


@pytest.mark.asyncio
async def test_monthly_trend_fills_missing_months(monkeypatch):
    rows = [
        {"_id": {"y": 2026, "m": 7}, "revenue": 200.0, "cost": 150.0, "orders": 10},
    ]
    monkeypatch.setattr(accounting, "db", _Db(rows))

    trend = await accounting.monthly_profit_trend(months=3, now=datetime(2026, 7, 15, tzinfo=UTC))

    assert [row["month"] for row in trend] == ["2026-05", "2026-06", "2026-07"]
    # only July has data; the empty months are zero-filled
    july = next(row for row in trend if row["month"] == "2026-07")
    assert july["profit"] == 50.0
    assert trend[0]["revenue"] == 0.0


class _MultiDb:
    """Fake db exposing separate collections for orders and wallets."""
    def __init__(self, orders_rows, wallets_rows):
        self.orders = _Orders(orders_rows)
        self.wallets = _Orders(wallets_rows)


@pytest.mark.asyncio
async def test_profit_by_provider_sorted_by_profit(monkeypatch):
    rows = [
        {"_id": "g2bulk", "revenue": 300.0, "cost": 250.0, "orders": 20},
        {"_id": "manual_catalog", "revenue": 200.0, "cost": 120.0, "orders": 8},
    ]
    monkeypatch.setattr(accounting, "db", _Db(rows))

    result = await accounting.profit_by_provider(
        start=datetime(2026, 6, 1, tzinfo=UTC), end=datetime(2026, 7, 1, tzinfo=UTC)
    )

    # sorted by profit desc: manual_catalog (80) before g2bulk (50)
    assert [row["provider"] for row in result] == ["manual_catalog", "g2bulk"]
    assert result[0]["profit"] == 80.0


@pytest.mark.asyncio
async def test_capital_summary_totals_wallet_float(monkeypatch):
    wallets = [
        {"_id": "user_main", "balance": 500.0, "wallets": 40},
        {"_id": "reseller_main", "balance": 300.0, "wallets": 5},
        {"_id": "reseller_earnings", "balance": 120.0, "wallets": 5},
    ]
    monkeypatch.setattr(accounting, "db", _MultiDb([], wallets))

    result = await accounting.capital_summary()

    assert result["total_float"] == 920.0
    assert result["by_type"][0]["wallet_type"] == "user_main"
