from datetime import UTC, datetime

import pytest

from services.numbers import order_refresh_service


@pytest.mark.asyncio
async def test_refresh_number_order_stores_new_temp_code(monkeypatch):
    calls = {"details": [], "events": []}
    order = {
        "_id": "order-1",
        "status": "success",
        "number_mode": "temp",
        "provider": "textverified",
        "provider_order_id": "provider-1",
        "created_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        "temp_codes": [],
    }

    async def fake_get_order(order_id):
        if calls["details"]:
            patch = calls["details"][-1][1]
            return {**order, **patch}
        return order

    async def fake_fetch_provider_sms(providers, provider_code, provider_order_id):
        calls["fetch"] = (provider_code, provider_order_id)
        return {"success": True, "messages": ["123456"], "raw": {}}

    async def fake_update_order_details(order_id, patch):
        calls["details"].append((order_id, patch))

    async def fake_log_temp_event(order_arg, event, payload):
        calls["events"].append((event, payload))

    monkeypatch.setattr(order_refresh_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_refresh_service, "fetch_provider_sms", fake_fetch_provider_sms)
    monkeypatch.setattr(order_refresh_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_refresh_service, "_log_temp_event", fake_log_temp_event)
    monkeypatch.setattr(order_refresh_service, "_utc_now", lambda: datetime(2026, 5, 25, 12, 1, tzinfo=UTC))

    result = await order_refresh_service.refresh_number_order(order)

    assert calls["fetch"] == ("textverified", "provider-1")
    assert calls["details"][0][0] == "order-1"
    assert calls["details"][0][1]["temp_wait_state"] == "code_received"
    assert calls["details"][0][1]["temp_last_code"] == "123456"
    assert calls["events"][0][0] == "code_received"
    assert result["order"]["code"] == "123456"
    assert result["order"]["codes"] == ["123456"]
    assert "base_price" not in result["order"]


@pytest.mark.asyncio
async def test_refresh_number_order_marks_no_sms_refresh(monkeypatch):
    calls = {}
    order = {
        "_id": "order-1",
        "status": "success",
        "number_mode": "temp",
        "provider": "textverified",
        "provider_order_id": "provider-1",
    }

    async def fake_get_order(order_id):
        return order

    async def fake_fetch_provider_sms(providers, provider_code, provider_order_id):
        return {"success": True, "messages": [], "raw": {}}

    async def fake_update_order_details(order_id, patch):
        calls["patch"] = patch

    monkeypatch.setattr(order_refresh_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_refresh_service, "fetch_provider_sms", fake_fetch_provider_sms)
    monkeypatch.setattr(order_refresh_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_refresh_service, "_utc_now", lambda: datetime(2026, 5, 25, 12, 1, tzinfo=UTC))

    result = await order_refresh_service.refresh_number_order(order)

    assert "temp_last_refresh_at" in calls["patch"]
    assert result["message"] == "No SMS yet."


@pytest.mark.asyncio
async def test_refresh_number_order_rejects_unsupported_modes():
    with pytest.raises(order_refresh_service.NumbersOrderError) as exc:
        await order_refresh_service.refresh_number_order({"_id": "order-1", "number_mode": "rental"})

    assert exc.value.code == "unsupported_order_mode"
