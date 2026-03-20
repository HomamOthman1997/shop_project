import os
import sys
from datetime import UTC, datetime

import pytest

sys.path.insert(0, os.getcwd())

import database.financial_ledger as financial_ledger


class _FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def limit(self, limit):
        self.docs = self.docs[:limit]
        return self

    async def to_list(self, length=None):
        if length is None:
            return list(self.docs)
        return list(self.docs[:length])


class _FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query=None, projection=None):
        query = query or {}
        filtered = []
        for doc in self.docs:
            if _matches(doc, query):
                if projection:
                    row = {}
                    include_id = projection.get("_id", 1) != 0
                    if include_id and "_id" in doc:
                        row["_id"] = doc["_id"]
                    for key, enabled in projection.items():
                        if key == "_id" or not enabled:
                            continue
                        if key in doc:
                            row[key] = doc[key]
                    filtered.append(row)
                else:
                    filtered.append(dict(doc))
        return _FakeCursor(filtered)


class _FakeDb:
    def __init__(self):
        now = datetime.now(UTC)
        self.wallets = _FakeCollection(
            [
                {"owner_type": "user", "owner_id": 1, "wallet_type": "user", "reseller_id": 77, "balance": -2.5},
            ]
        )
        self.orders = _FakeCollection(
            [
                {"_id": "o1", "user_id": 1, "reseller_id": 77, "status": "paid", "service_type": "core", "created_at": now},
            ]
        )
        self.ledger_entries = _FakeCollection([])
        self.recharge_requests = _FakeCollection(
            [
                {"_id": "r1", "user_id": 1, "reseller_id": 77, "wallet_type": "user", "status": "accepted", "amount": 4.0, "approved_amount": None, "reviewed_at": now},
            ]
        )
        self.settlements = _FakeCollection(
            [
                {"reseller_id": 77, "cycle_key": "2026-03", "net_due": 12.0, "payment_status": "overdue", "services_locked": True, "payment_due_at": now},
            ]
        )


def _matches(doc, query):
    for key, value in query.items():
        if key == "$or":
            if not any(_matches(doc, part) for part in value):
                return False
            continue
        if isinstance(value, dict):
            for op, op_value in value.items():
                actual = doc.get(key)
                if op == "$gte" and not (actual >= op_value):
                    return False
                if op == "$lte" and not (actual <= op_value):
                    return False
                if op == "$lt" and not (actual < op_value):
                    return False
                if op == "$in" and not (actual in op_value):
                    return False
        else:
            if doc.get(key) != value:
                return False
    return True


@pytest.mark.asyncio
async def test_scan_financial_anomalies_reports_expected_categories(monkeypatch):
    monkeypatch.setattr(financial_ledger, "db", _FakeDb())

    report = await financial_ledger.scan_financial_anomalies(days=30, max_rows=10)

    assert report["negative_wallets_count"] == 1
    assert report["orders_missing_ledger_count"] == 1
    assert report["accepted_recharges_without_ledger_count"] == 1
    assert report["locked_overdue_settlements_count"] == 1
