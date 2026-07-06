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
