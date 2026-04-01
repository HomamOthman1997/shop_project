import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

import database.financial_ledger as financial_ledger
from database.financial_ledger import _classify_ledger_reason


def test_classify_ledger_reason_core_purchase():
    category, tags = _classify_ledger_reason("purchase_core_user_debit")
    assert category == "core_purchase"
    assert "core" in tags
    assert "purchase" in tags


def test_classify_ledger_reason_manual_adjust():
    category, tags = _classify_ledger_reason("balance_adjust_set")
    assert category == "manual_adjustment"
    assert "manual" in tags


@pytest.mark.asyncio
async def test_refund_core_purchase_is_idempotent_when_ledger_entry_exists(monkeypatch):
    seen = {"marked": None, "released": None}

    async def fake_acquire(_lock_key):
        return True

    async def fake_release(lock_key):
        seen["released"] = lock_key

    async def fake_run_in_transaction(coro):
        return await coro(None)

    async def fake_ledger_entry_exists(query, *, session=None):
        return query["reason"] == "refund_core_user_credit"

    async def fake_mark_order_status(order_id, status, *, session=None):
        seen["marked"] = (order_id, status)

    async def fail_apply(*args, **kwargs):
        raise AssertionError("_apply_wallet_delta should not run on idempotent refund")

    monkeypatch.setattr(financial_ledger, "acquire_session_lock", fake_acquire)
    monkeypatch.setattr(financial_ledger, "release_session_lock", fake_release)
    monkeypatch.setattr(financial_ledger, "_run_in_transaction", fake_run_in_transaction)
    monkeypatch.setattr(financial_ledger, "_ledger_entry_exists", fake_ledger_entry_exists)
    monkeypatch.setattr(financial_ledger, "mark_order_status", fake_mark_order_status)
    monkeypatch.setattr(financial_ledger, "_apply_wallet_delta", fail_apply)

    ok, code, meta = await financial_ledger.refund_core_purchase(
        user_id=1,
        order_id="ord-1",
        sale_price=5.0,
        cost_price=3.0,
        actor_id=1,
        reseller_id=77,
    )

    assert ok is True
    assert code == "ALREADY_REFUNDED"
    assert meta["idempotent"] is True
    assert seen["marked"] == ("ord-1", "refunded")
    assert seen["released"] == "user:1:reseller:77:refund:ord-1"


@pytest.mark.asyncio
async def test_refund_custom_purchase_is_idempotent_when_ledger_entry_exists(monkeypatch):
    seen = {"marked": None}

    async def fake_acquire(_lock_key):
        return True

    async def fake_release(_lock_key):
        return None

    async def fake_run_in_transaction(coro):
        return await coro(None)

    async def fake_ledger_entry_exists(query, *, session=None):
        return query["reason"] == "refund_custom_user_credit"

    async def fake_mark_order_status(order_id, status, *, session=None):
        seen["marked"] = (order_id, status)

    async def fail_apply(*args, **kwargs):
        raise AssertionError("_apply_wallet_delta should not run on idempotent refund")

    monkeypatch.setattr(financial_ledger, "acquire_session_lock", fake_acquire)
    monkeypatch.setattr(financial_ledger, "release_session_lock", fake_release)
    monkeypatch.setattr(financial_ledger, "_run_in_transaction", fake_run_in_transaction)
    monkeypatch.setattr(financial_ledger, "_ledger_entry_exists", fake_ledger_entry_exists)
    monkeypatch.setattr(financial_ledger, "mark_order_status", fake_mark_order_status)
    monkeypatch.setattr(financial_ledger, "_apply_wallet_delta", fail_apply)

    ok, code, meta = await financial_ledger.refund_custom_purchase(
        user_id=2,
        order_id="ord-2",
        price=9.5,
        actor_id=2,
        reseller_id=88,
    )

    assert ok is True
    assert code == "ALREADY_REFUNDED"
    assert meta["idempotent"] is True
    assert seen["marked"] == ("ord-2", "refunded")
