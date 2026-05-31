import os
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

from services.game_store import recovery as mod


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    async def to_list(self, _n):
        return list(self._rows)


class _FakeOrdersCollection:
    def __init__(self, rows):
        self._rows = list(rows)

    def find(self, query=None, *_args, **_kwargs):
        query = query or {}
        rows = list(self._rows)
        # Handle the second sweep query that targets missing provider_order_id rows.
        has_missing_order_id_filter = False
        for item in list(query.get("$or") or []):
            if "provider_order_id" in item:
                has_missing_order_id_filter = True
                break
        if has_missing_order_id_filter:
            filtered = []
            for row in rows:
                pov = row.get("provider_order_id")
                if pov in (None, ""):
                    filtered.append(row)
            return _FakeCursor(filtered)
        return _FakeCursor(rows)


@pytest.mark.asyncio
async def test_game_store_recovery_marks_success(monkeypatch):
    now = datetime.now(UTC)
    rows = [
        {
            "_id": "ord1",
            "user_id": 11,
            "reseller_id": 22,
            "service_type": "core_game_store",
            "status": "paid",
            "provider_code": "g2bulk",
            "provider_order_id": "P-1",
            "created_at": now - timedelta(minutes=10),
            "retail_amount": 3.0,
            "wholesale_amount": 2.0,
        }
    ]
    monkeypatch.setattr(mod, "db", SimpleNamespace(orders=_FakeOrdersCollection(rows)))

    class _Client:
        async def get_order_status(self, _oid):
            return {"status": 200, "data": {"status": "success"}}

        async def get_order_delivery(self, _oid):
            return {"status": 200, "data": {"delivery_items": ["CODE-1"]}}

    monkeypatch.setattr(mod, "G2BulkClient", _Client)

    updated_status = []

    async def _upd_status(oid, status):
        updated_status.append((oid, status))

    monkeypatch.setattr(mod, "update_order_status", _upd_status)

    details_calls = []

    async def _upd_details(oid, data):
        details_calls.append((oid, dict(data)))

    async def _refund(**_k):
        return True, "ok"

    monkeypatch.setattr(mod, "update_order_details", _upd_details)
    monkeypatch.setattr(mod.FinancialManager, "refund_core_purchase", _refund)

    stats = await mod.run_g2bulk_pending_recovery_sweep(limit=20, pending_age_sec=60)
    assert stats["checked"] >= 1
    assert stats["marked_success"] == 1
    assert ("ord1", "success") in updated_status
    assert any(call[1].get("provider_recovery_outcome") == "success" for call in details_calls)


@pytest.mark.asyncio
async def test_game_store_recovery_refunds_on_provider_failure(monkeypatch):
    now = datetime.now(UTC)
    rows = [
        {
            "_id": "ord2",
            "user_id": 111,
            "reseller_id": 222,
            "service_type": "core_game_store",
            "status": "paid",
            "provider_code": "g2bulk",
            "provider_order_id": "P-2",
            "created_at": now - timedelta(minutes=10),
            "retail_amount": 4.0,
            "wholesale_amount": 3.0,
        }
    ]
    monkeypatch.setattr(mod, "db", SimpleNamespace(orders=_FakeOrdersCollection(rows)))

    class _Client:
        async def get_order_status(self, _oid):
            return {"status": 200, "data": {"status": "failed"}}

        async def get_order_delivery(self, _oid):
            return {"status": 200, "data": {"delivery_items": ["CODE-1"]}}

    monkeypatch.setattr(mod, "G2BulkClient", _Client)

    updated_status = []

    async def _upd_status(oid, status):
        updated_status.append((oid, status))

    async def _upd_details(*_a, **_k):
        return None

    async def _refund(**_k):
        return True, "ok"

    monkeypatch.setattr(mod, "update_order_status", _upd_status)
    monkeypatch.setattr(mod, "update_order_details", _upd_details)
    monkeypatch.setattr(mod, "extract_order_amounts", lambda _order: (4.0, 3.0))
    monkeypatch.setattr(mod.FinancialManager, "refund_core_purchase", _refund)

    stats = await mod.run_g2bulk_pending_recovery_sweep(limit=20, pending_age_sec=60)
    assert stats["checked"] >= 1
    assert stats["marked_refunded"] == 1
    assert ("ord2", "refunded") in updated_status


@pytest.mark.asyncio
async def test_game_store_recovery_keeps_pending_when_provider_is_still_processing(monkeypatch):
    now = datetime.now(UTC)
    rows = [
        {
            "_id": "ord3",
            "user_id": 1,
            "reseller_id": 2,
            "service_type": "core_game_store",
            "status": "paid",
            "provider_code": "g2bulk",
            "provider_order_id": "P-3",
            "created_at": now - timedelta(minutes=10),
        }
    ]
    monkeypatch.setattr(mod, "db", SimpleNamespace(orders=_FakeOrdersCollection(rows)))

    class _Client:
        async def get_order_status(self, _oid):
            return {"status": 200, "data": {"status": "processing"}}

        async def get_order_delivery(self, _oid):
            return {"status": 200, "data": {"delivery_items": ["CODE-1"]}}

    monkeypatch.setattr(mod, "G2BulkClient", _Client)

    updated_status = []

    async def _upd_status(oid, status):
        updated_status.append((oid, status))

    async def _upd_details(*_a, **_k):
        return None

    monkeypatch.setattr(mod, "update_order_status", _upd_status)
    monkeypatch.setattr(mod, "update_order_details", _upd_details)
    async def _refund(**_k):
        return True, "ok"

    monkeypatch.setattr(mod.FinancialManager, "refund_core_purchase", _refund)

    stats = await mod.run_g2bulk_pending_recovery_sweep(limit=20, pending_age_sec=60)
    assert stats["pending"] >= 1
    assert not updated_status


@pytest.mark.asyncio
async def test_game_store_recovery_refunds_missing_provider_order_id_after_timeout(monkeypatch):
    now = datetime.now(UTC)
    rows = [
        {
            "_id": "ord4",
            "user_id": 7,
            "reseller_id": 8,
            "service_type": "core_game_store",
            "status": "paid",
            "provider_code": "g2bulk",
            "provider_order_id": "",
            "provider_manual_review_required": True,
            "created_at": now - timedelta(minutes=25),
            "retail_amount": 5.0,
            "wholesale_amount": 4.0,
        }
    ]
    monkeypatch.setattr(mod, "db", SimpleNamespace(orders=_FakeOrdersCollection(rows)))

    class _Client:
        async def get_order_status(self, _oid):
            return {"status": 200, "data": {"status": "processing"}}

        async def get_order_delivery(self, _oid):
            return {"status": 200, "data": {"delivery_items": ["CODE-1"]}}

    monkeypatch.setattr(mod, "G2BulkClient", _Client)
    monkeypatch.setattr(mod, "extract_order_amounts", lambda _order: (5.0, 4.0))
    async def _refund(**_k):
        return True, "ok"

    monkeypatch.setattr(mod.FinancialManager, "refund_core_purchase", _refund)

    updated_status = []

    async def _upd_status(oid, status):
        updated_status.append((oid, status))

    async def _upd_details(*_a, **_k):
        return None

    monkeypatch.setattr(mod, "update_order_status", _upd_status)
    monkeypatch.setattr(mod, "update_order_details", _upd_details)

    stats = await mod.run_g2bulk_pending_recovery_sweep(limit=20, pending_age_sec=60)
    assert stats["missing_order_id_refunded"] == 1
    assert ("ord4", "refunded") in updated_status
