import os
import sys

import pytest
from pymongo import ReturnDocument

sys.path.insert(0, os.getcwd())

import database.recharge_repo as recharge_repo


class _FakeRechargeRequests:
    def __init__(self, doc: dict):
        self.doc = doc

    async def find_one_and_update(self, query, update, return_document=None):
        status_filter = query.get("status")
        if isinstance(status_filter, dict):
            allowed = status_filter.get("$in", [])
            if self.doc.get("status") not in allowed:
                return None
        elif status_filter is not None and self.doc.get("status") != status_filter:
            return None
        before = dict(self.doc)
        for key, value in update.get("$set", {}).items():
            self.doc[key] = value
        if return_document == ReturnDocument.AFTER:
            return dict(self.doc)
        return before

    async def find_one(self, query):
        return dict(self.doc) if query.get("_id") == self.doc.get("_id") else None

    async def update_one(self, query, update):
        status_filter = query.get("status")
        if status_filter is not None and self.doc.get("status") != status_filter:
            return None
        for key, value in update.get("$set", {}).items():
            self.doc[key] = value
        return None


class _FakeDb:
    def __init__(self, doc: dict):
        self.recharge_requests = _FakeRechargeRequests(doc)


@pytest.mark.asyncio
async def test_update_recharge_request_preserves_manual_approved_amount_during_recovery(monkeypatch):
    request_id = "req-1"
    stored = {
        "_id": request_id,
        "status": "pending",
        "user_id": 50,
        "reseller_id": 77,
        "wallet_type": "user",
        "amount": 10.0,
        "approved_amount": None,
    }
    fake_db = _FakeDb(stored)
    seen = {"calls": 0}

    async def fake_credit_user_wallet(**kwargs):
        raise RuntimeError("simulated credit timeout")

    async def fake_ledger_applied_for_request(_request_id, _req):
        seen["calls"] += 1
        return seen["calls"] >= 2

    monkeypatch.setattr(recharge_repo, "db", fake_db)
    monkeypatch.setattr(recharge_repo, "credit_user_wallet", fake_credit_user_wallet)
    monkeypatch.setattr(recharge_repo, "_ledger_applied_for_request", fake_ledger_applied_for_request)

    updated = await recharge_repo.update_recharge_request(
        request_id,
        "accepted",
        reviewed_by=77,
        approved_amount=7.5,
        expected_reseller_id=77,
    )

    assert updated is not None
    assert updated["status"] == "accepted"
    assert updated["approved_amount"] == 7.5


@pytest.mark.asyncio
async def test_update_recharge_request_logs_rejected_path(monkeypatch, caplog):
    request_id = "req-2"
    stored = {
        "_id": request_id,
        "status": "pending",
        "user_id": 51,
        "reseller_id": 88,
        "wallet_type": "user",
        "amount": 5.0,
        "approved_amount": None,
    }
    fake_db = _FakeDb(stored)

    monkeypatch.setattr(recharge_repo, "db", fake_db)

    with caplog.at_level("INFO", logger="recharge_repo"):
        updated = await recharge_repo.update_recharge_request(
            request_id,
            "rejected",
            reviewed_by=88,
            expected_reseller_id=88,
        )

    assert updated is not None
    assert updated["status"] == "rejected"
    assert "recharge_event=request_decided" in caplog.text
