import pytest

from services.numbers import order_cancel_service


@pytest.mark.asyncio
async def test_cancel_number_order_refunds_temp_order(monkeypatch):
    calls = {}
    order = {"_id": "order-1", "number_mode": "temp", "status": "success", "user_id": 123, "reseller_id": 456}

    async def fake_cancel_and_refund_temp_order(**kwargs):
        calls["cancel"] = kwargs
        return {"success": True, "reason": "ok"}

    async def fake_get_order(order_id):
        calls["get"] = order_id
        return {**order, "status": "cancelled", "temp_wait_state": "refunded"}

    async def fake_sleep(_seconds):
        calls["sleep"] = True

    monkeypatch.setattr(order_cancel_service, "cancel_and_refund_temp_order", fake_cancel_and_refund_temp_order)
    monkeypatch.setattr(order_cancel_service, "get_order", fake_get_order)

    result = await order_cancel_service.cancel_number_order(order, actor_user_id=123, sleep_fn=fake_sleep)

    assert calls["cancel"]["order_id"] == "order-1"
    assert calls["cancel"]["actor_user_id"] == 123
    assert calls["cancel"]["reason"] == "numbers_api_user_cancel"
    assert calls["cancel"]["source"] == "numbers_api_cancel"
    assert result["order"]["status"] == "cancelled"
    assert result["order"]["wait_state"] == "refunded"


@pytest.mark.asyncio
async def test_cancel_number_order_rejects_failed_cancel(monkeypatch):
    async def fake_cancel_and_refund_temp_order(**kwargs):
        return {"success": False, "reason": "sms_received"}

    async def fake_get_order(order_id):
        return {"_id": order_id, "number_mode": "temp", "status": "success"}

    monkeypatch.setattr(order_cancel_service, "cancel_and_refund_temp_order", fake_cancel_and_refund_temp_order)
    monkeypatch.setattr(order_cancel_service, "get_order", fake_get_order)

    with pytest.raises(order_cancel_service.NumbersOrderError) as exc:
        await order_cancel_service.cancel_number_order(
            {"_id": "order-1", "number_mode": "temp", "status": "success"},
            actor_user_id=123,
            sleep_fn=lambda _seconds: None,
        )

    assert exc.value.code == "sms_received"
    assert exc.value.status == 409


@pytest.mark.asyncio
async def test_cancel_number_order_rejects_unsupported_modes():
    with pytest.raises(order_cancel_service.NumbersOrderError) as exc:
        await order_cancel_service.cancel_number_order({"_id": "order-1", "number_mode": "rental"}, actor_user_id=123)

    assert exc.value.code == "unsupported_order_mode"
