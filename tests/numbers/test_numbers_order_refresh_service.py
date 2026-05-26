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
        "provider_sms_delivery": "polling",
        "provider_order_id": "provider-1",
        "user_id": 123,
        "reseller_id": 456,
        "created_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        "temp_wait_started_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        "temp_wait_timeout_sec": 999999,
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

    async def fake_enqueue_event_for_user(**kwargs):
        calls["webhook"] = kwargs

    monkeypatch.setattr(order_refresh_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_refresh_service, "fetch_provider_sms", fake_fetch_provider_sms)
    monkeypatch.setattr(order_refresh_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_refresh_service, "_log_temp_event", fake_log_temp_event)
    monkeypatch.setattr(order_refresh_service, "enqueue_event_for_user", fake_enqueue_event_for_user)
    monkeypatch.setattr(order_refresh_service, "provider_sms_polling_enabled", lambda provider=None: True)
    monkeypatch.setattr(order_refresh_service, "_utc_now", lambda: datetime(2026, 5, 25, 12, 1, tzinfo=UTC))

    result = await order_refresh_service.refresh_number_order(order)

    assert calls["fetch"] == ("textverified", "provider-1")
    assert calls["details"][0][0] == "order-1"
    assert calls["details"][0][1]["temp_wait_state"] == "code_received"
    assert calls["details"][0][1]["temp_last_code"] == "123456"
    assert calls["events"][0][0] == "code_received"
    assert calls["webhook"]["event_type"] == "numbers.order.sms"
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
        "provider_sms_delivery": "polling",
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
    monkeypatch.setattr(order_refresh_service, "provider_sms_polling_enabled", lambda provider=None: True)
    monkeypatch.setattr(order_refresh_service, "_utc_now", lambda: datetime(2026, 5, 25, 12, 1, tzinfo=UTC))

    result = await order_refresh_service.refresh_number_order(order)

    assert "temp_last_refresh_at" in calls["patch"]
    assert result["message"] == "No SMS yet."


@pytest.mark.asyncio
async def test_refresh_number_order_does_not_poll_webhook_provider(monkeypatch):
    calls = {}
    order = {
        "_id": "order-1",
        "status": "success",
        "number_mode": "temp",
        "provider": "smsready",
        "provider_sms_delivery": "webhook",
        "provider_order_id": "50",
    }

    async def fake_get_order(order_id):
        return order

    async def fake_fetch_provider_sms(providers, provider_code, provider_order_id):
        calls["fetch"] = (provider_code, provider_order_id)
        return {"success": True, "messages": [], "raw": {}}

    async def fake_update_order_details(order_id, patch):
        calls["patch"] = patch

    monkeypatch.setattr(order_refresh_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_refresh_service, "fetch_provider_sms", fake_fetch_provider_sms)
    monkeypatch.setattr(order_refresh_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_refresh_service, "_utc_now", lambda: datetime(2026, 5, 25, 12, 1, tzinfo=UTC))

    result = await order_refresh_service.refresh_number_order(order)

    assert "fetch" not in calls
    assert calls["patch"]["temp_last_refresh_mode"] == "provider_webhook"
    assert result["message"] == "Waiting for provider webhook."


@pytest.mark.asyncio
async def test_refresh_number_order_polls_explicit_polling_provider_when_global_polling_is_off(monkeypatch):
    calls = {}
    order = {
        "_id": "order-1",
        "status": "success",
        "number_mode": "temp",
        "provider": "smspool",
        "provider_order_id": "pool-1",
        "user_id": 123,
        "reseller_id": 456,
        "created_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        "temp_wait_started_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        "temp_wait_timeout_sec": 999999,
        "temp_codes": [],
    }

    async def fake_get_order(order_id):
        if calls.get("patch"):
            return {**order, **calls["patch"]}
        return order

    async def fake_fetch_provider_sms(providers, provider_code, provider_order_id):
        calls["fetch"] = (provider_code, provider_order_id)
        return {"success": True, "messages": ["654321"], "raw": {}}

    async def fake_update_order_details(order_id, patch):
        calls["patch"] = patch

    async def fake_log_temp_event(order_arg, event, payload):
        calls["event"] = event

    async def fake_enqueue_event_for_user(**kwargs):
        calls["webhook"] = kwargs

    monkeypatch.setattr(order_refresh_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_refresh_service, "fetch_provider_sms", fake_fetch_provider_sms)
    monkeypatch.setattr(order_refresh_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_refresh_service, "_log_temp_event", fake_log_temp_event)
    monkeypatch.setattr(order_refresh_service, "enqueue_event_for_user", fake_enqueue_event_for_user)
    monkeypatch.setattr(order_refresh_service, "_utc_now", lambda: datetime(2026, 5, 25, 12, 1, tzinfo=UTC))

    result = await order_refresh_service.refresh_number_order(order)

    assert calls["fetch"] == ("smspool", "pool-1")
    assert calls["patch"]["temp_last_code"] == "654321"
    assert calls["event"] == "code_received"
    assert calls["webhook"]["event_type"] == "numbers.order.sms"
    assert result["order"]["code"] == "654321"


@pytest.mark.asyncio
async def test_refresh_number_order_returns_rental_or_voice_state_without_provider_poll(monkeypatch):
    calls = {}
    order = {
        "_id": "rental-1",
        "status": "success",
        "number_mode": "rental",
        "provider": "pvadeals",
        "provider_order_id": "provider-rental",
        "service_id": "telegram:rental",
        "rental_country": "1",
        "rental_sms_count": 1,
        "rental_last_code": "112233",
    }

    async def fake_get_order(order_id):
        if calls.get("patch"):
            return {**order, **calls["patch"]}
        return order

    async def fake_update_order_details(order_id, patch):
        calls["patch"] = patch

    async def fake_fetch_provider_sms(*args, **kwargs):
        calls["fetch"] = True
        return {"success": True, "messages": []}

    monkeypatch.setattr(order_refresh_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_refresh_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_refresh_service, "fetch_provider_sms", fake_fetch_provider_sms)
    monkeypatch.setattr(order_refresh_service, "_utc_now", lambda: datetime(2026, 5, 25, 12, 1, tzinfo=UTC))

    result = await order_refresh_service.refresh_number_order(order)

    assert "fetch" not in calls
    assert calls["patch"]["api_last_refresh_mode"] == "provider_webhook"
    assert result["message"] == "Waiting for provider webhook."
    assert result["order"]["mode"] == "rental"
    assert result["order"]["public_status"] == "code_received"
    assert result["order"]["code"] == "112233"
