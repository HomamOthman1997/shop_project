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

    async def fake_cancel_number_order(order, *, actor_user_id, sleep_fn=None):
        calls["cancel"] = (order, actor_user_id, sleep_fn)
        return {"ok": True, "order": {"id": order["_id"], "status": "cancelled"}}

    async def fake_sleep(_seconds):
        pass

    monkeypatch.setattr(order_auto_refund_service, "cancel_number_order", fake_cancel_number_order)

    result = await order_auto_refund_service.auto_refund_temp_order_if_due(due_order(), sleep_fn=fake_sleep)

    assert calls["cancel"][1] == 123
    assert calls["cancel"][2] is fake_sleep
    assert result == {"ok": True, "refunded": True, "reason": "timeout_no_code", "order": {"id": "order-1", "status": "cancelled"}}


@pytest.mark.asyncio
async def test_auto_refund_marks_support_review_on_provider_failure(monkeypatch):
    async def fake_cancel_number_order(order, *, actor_user_id, sleep_fn=None):
        raise NumbersOrderError("provider_cancel_failed", "Could not cancel this order right now.", status=503)

    monkeypatch.setattr(order_auto_refund_service, "cancel_number_order", fake_cancel_number_order)

    result = await order_auto_refund_service.auto_refund_temp_order_if_due(due_order())

    assert result["refunded"] is False
    assert result["reason"] == "provider_cancel_failed"
    assert result["support_review_required"] is True
