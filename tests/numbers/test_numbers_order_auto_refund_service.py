from datetime import UTC, datetime, timedelta

import pytest

from services.numbers import order_auto_refund_service
from services.numbers.order_service import NumbersOrderError


def due_order(**overrides):
    now = datetime.now(UTC)
    order = {
        "_id": "order-1",
        "user_id": 123,
        "status": "success",
        "number_mode": "temp",
        "provider": "textverified",
        "created_at": now - timedelta(seconds=901),
        "temp_wait_started_at": now - timedelta(seconds=901),
        "temp_wait_timeout_sec": 900,
        "temp_codes": [],
    }
    order.update(overrides)
    return order


@pytest.mark.asyncio
async def test_auto_refund_skips_before_timeout():
    order = due_order(temp_wait_started_at=datetime.now(UTC), created_at=datetime.now(UTC))

    result = await order_auto_refund_service.auto_refund_temp_order_if_due(order)

    assert result["refunded"] is False
    assert result["reason"] == "not_due"
    assert result["seconds_left"] > 0


@pytest.mark.asyncio
async def test_auto_refund_skips_if_code_received():
    result = await order_auto_refund_service.auto_refund_temp_order_if_due(due_order(temp_last_code="123456"))

    assert result["refunded"] is False
    assert result["reason"] == "code_received"


@pytest.mark.asyncio
async def test_auto_refund_delegates_to_provider_aware_cancel(monkeypatch):
    calls = {}

    async def fake_cancel_number_order(order, **kwargs):
        calls["cancel"] = (order, kwargs)
        return {"ok": True, "order": {"id": order["_id"], "status": "cancelled"}}

    async def fake_sleep(_seconds):
        pass

    monkeypatch.setattr(order_auto_refund_service, "cancel_number_order", fake_cancel_number_order)

    result = await order_auto_refund_service.auto_refund_temp_order_if_due(due_order(), sleep_fn=fake_sleep)

    assert calls["cancel"][1]["actor_user_id"] == 123
    assert calls["cancel"][1]["reason"] == "numbers_api_timeout_auto_refund"
    assert calls["cancel"][1]["source"] == "numbers_api_auto_refund"
    assert calls["cancel"][1]["allow_provider_terminal_refund"] is True
    assert calls["cancel"][1]["allow_empty_provider_refund"] is True
    assert calls["cancel"][1]["sleep_fn"] is fake_sleep
    assert result == {"ok": True, "refunded": True, "reason": "timeout_no_code", "order": {"id": "order-1", "status": "cancelled"}}


@pytest.mark.asyncio
async def test_auto_refund_marks_support_review_on_provider_failure(monkeypatch):
    async def fake_cancel_number_order(order, **kwargs):
        raise NumbersOrderError("provider_cancel_failed", "Could not cancel this order right now.", status=503)

    monkeypatch.setattr(order_auto_refund_service, "cancel_number_order", fake_cancel_number_order)

    result = await order_auto_refund_service.auto_refund_temp_order_if_due(due_order())

    assert result["refunded"] is False
    assert result["reason"] == "provider_cancel_failed"
    assert result["support_review_required"] is True


@pytest.mark.asyncio
async def test_auto_refund_sends_refund_risk_provider_to_support_review(monkeypatch):
    calls = {}

    async def fake_update_order_details(order_id, patch):
        calls["support_patch"] = (order_id, patch)

    monkeypatch.setattr(order_auto_refund_service, "update_order_details", fake_update_order_details)

    result = await order_auto_refund_service.auto_refund_temp_order_if_due(due_order(provider="nonvoip"))

    assert result["refunded"] is False
    assert result["support_review_required"] is True
    assert result["reason"] == "auto_refund_disabled_refund_risk"
    assert calls["support_patch"][0] == "order-1"


@pytest.mark.asyncio
async def test_auto_refund_sweep_marks_support_review(monkeypatch):
    calls = {}
    order = due_order()

    async def fake_list_api_temp_orders_for_auto_refund(limit):
        calls["limit"] = limit
        return [order]

    async def fake_auto_refund_temp_order_if_due(order_arg, sleep_fn=None):
        calls["order"] = order_arg
        return {"ok": True, "refunded": False, "support_review_required": True, "reason": "provider_cancel_failed"}

    async def fake_update_order_details(order_id, patch):
        calls["support_patch"] = (order_id, patch)

    monkeypatch.setattr(order_auto_refund_service, "list_api_temp_orders_for_auto_refund", fake_list_api_temp_orders_for_auto_refund)
    monkeypatch.setattr(order_auto_refund_service, "auto_refund_temp_order_if_due", fake_auto_refund_temp_order_if_due)
    monkeypatch.setattr(order_auto_refund_service, "update_order_details", fake_update_order_details)

    stats = await order_auto_refund_service.run_numbers_api_auto_refund_sweep(limit=5)

    assert stats == {"checked": 1, "refunded": 0, "skipped": 0, "support_review": 1, "errors": 0}
    assert calls["limit"] == 5
    assert calls["support_patch"][0] == "order-1"
    assert calls["support_patch"][1]["temp_refund_support_review_status"] == "open"
    assert calls["support_patch"][1]["temp_refund_support_review_reason"] == "provider_cancel_failed"
