from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.numbers import provider_webhook_service


@pytest.mark.asyncio
async def test_apply_provider_temp_sms_webhook_updates_order_and_enqueues_customer_webhook(monkeypatch):
    calls = {}
    order = {
        "_id": "order-1",
        "source": "numbers_api",
        "number_mode": "temp",
        "provider": "smsready",
        "provider_order_id": "50",
        "user_id": 123,
        "reseller_id": 456,
        "status": "success",
        "created_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        "temp_codes": [],
    }

    async def fake_get_temp_order_by_provider_order(provider_code, provider_order_id):
        calls["lookup"] = (provider_code, provider_order_id)
        return order

    async def fake_update_order_details(order_id, patch):
        calls["patch"] = (order_id, patch)

    async def fake_log_temp_event(*args, **kwargs):
        calls["event"] = (args, kwargs)

    async def fake_get_order(order_id):
        calls["get"] = order_id
        return {**order, **calls["patch"][1]}

    async def fake_enqueue_event_for_user(**kwargs):
        calls["webhook"] = kwargs

    async def fake_record_provider_webhook_event(**kwargs):
        calls["provider_event"] = kwargs

    monkeypatch.setattr(provider_webhook_service, "get_temp_order_by_provider_order", fake_get_temp_order_by_provider_order)
    monkeypatch.setattr(provider_webhook_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(provider_webhook_service, "_log_temp_event", fake_log_temp_event)
    monkeypatch.setattr(provider_webhook_service, "get_order", fake_get_order)
    monkeypatch.setattr(provider_webhook_service, "enqueue_event_for_user", fake_enqueue_event_for_user)
    monkeypatch.setattr(provider_webhook_service, "record_provider_webhook_event", fake_record_provider_webhook_event)

    result = await provider_webhook_service.apply_provider_temp_sms_webhook(
        provider_code="smsready",
        provider_order_id="50",
        code="245646",
        full_sms="Here is your code: 245646",
        raw_event={"event": "new_sms"},
    )

    assert result["ok"] is True
    assert result["reason"] == "code_received"
    assert calls["lookup"] == ("smsready", "50")
    assert calls["patch"][0] == "order-1"
    assert calls["patch"][1]["temp_wait_state"] == "code_received"
    assert calls["patch"][1]["temp_last_code"] == "245646"
    assert calls["patch"][1]["temp_codes"] == ["245646"]
    assert calls["patch"][1]["temp_last_sms_text"] == "Here is your code: 245646"
    assert calls["event"][1] == {}
    assert calls["webhook"]["event_type"] == "numbers.order.sms"
    assert calls["webhook"]["data"]["order"]["code"] == "245646"
    assert calls["provider_event"]["status"] == "processed"
    assert calls["provider_event"]["reason"] == "code_received"
    assert calls["provider_event"]["order_id"] == "order-1"


@pytest.mark.asyncio
async def test_apply_provider_temp_sms_webhook_is_idempotent_for_duplicate_code(monkeypatch):
    calls = {}

    async def fake_get_temp_order_by_provider_order(provider_code, provider_order_id):
        return {
            "_id": "order-1",
            "number_mode": "temp",
            "provider": "smsready",
            "provider_order_id": "50",
            "user_id": 123,
            "reseller_id": 456,
            "status": "success",
            "temp_codes": ["245646"],
            "temp_last_code": "245646",
        }

    async def fake_update_order_details(order_id, patch):
        calls["patch"] = (order_id, patch)

    async def fake_record_provider_webhook_event(**kwargs):
        calls["provider_event"] = kwargs

    monkeypatch.setattr(provider_webhook_service, "get_temp_order_by_provider_order", fake_get_temp_order_by_provider_order)
    monkeypatch.setattr(provider_webhook_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(provider_webhook_service, "record_provider_webhook_event", fake_record_provider_webhook_event)

    result = await provider_webhook_service.apply_provider_temp_sms_webhook(
        provider_code="smsready",
        provider_order_id="50",
        code="245646",
    )

    assert result["ok"] is True
    assert result["reason"] == "duplicate_code"
    assert "patch" not in calls
    assert calls["provider_event"]["status"] == "duplicate"


@pytest.mark.asyncio
async def test_apply_provider_temp_sms_webhook_records_unmatched_payload(monkeypatch):
    calls = {}

    async def fake_get_temp_order_by_provider_order(provider_code, provider_order_id):
        return None

    async def fake_get_number_order_by_provider_order(provider_code, provider_order_id):
        return None

    async def fake_record_provider_webhook_event(**kwargs):
        calls["provider_event"] = kwargs

    monkeypatch.setattr(provider_webhook_service, "get_temp_order_by_provider_order", fake_get_temp_order_by_provider_order)
    monkeypatch.setattr(provider_webhook_service, "get_number_order_by_provider_order", fake_get_number_order_by_provider_order)
    monkeypatch.setattr(provider_webhook_service, "record_provider_webhook_event", fake_record_provider_webhook_event)

    result = await provider_webhook_service.apply_provider_temp_sms_webhook(
        provider_code="pvadeals",
        provider_order_id="missing",
        code="123456",
        raw_event={"event": "sms_received"},
    )

    assert result == {"ok": False, "reason": "order_not_found"}
    assert calls["provider_event"]["status"] == "unmatched"
    assert calls["provider_event"]["reason"] == "order_not_found"


@pytest.mark.asyncio
async def test_apply_provider_temp_sms_webhook_updates_rental_order(monkeypatch):
    calls = {}
    order = {
        "_id": "rental-1",
        "number_mode": "rental",
        "provider": "pvadeals",
        "provider_order_id": "rent-50",
        "user_id": 123,
        "reseller_id": 456,
        "service_id": "paypal:rental",
        "status": "success",
        "created_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        "rental_sms_messages": [],
        "rental_codes": [],
    }

    async def fake_get_temp_order_by_provider_order(provider_code, provider_order_id):
        return None

    async def fake_get_number_order_by_provider_order(provider_code, provider_order_id):
        calls["lookup"] = (provider_code, provider_order_id)
        return order

    async def fake_update_order_details(order_id, patch):
        calls["patch"] = (order_id, patch)

    async def fake_log_rental_event(**kwargs):
        calls["event"] = kwargs

    async def fake_get_order(order_id):
        return {**order, **calls["patch"][1]}

    async def fake_enqueue_event_for_user(**kwargs):
        calls["webhook"] = kwargs

    async def fake_record_provider_webhook_event(**kwargs):
        calls["provider_event"] = kwargs

    monkeypatch.setattr(provider_webhook_service, "get_temp_order_by_provider_order", fake_get_temp_order_by_provider_order)
    monkeypatch.setattr(provider_webhook_service, "get_number_order_by_provider_order", fake_get_number_order_by_provider_order)
    monkeypatch.setattr(provider_webhook_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(provider_webhook_service, "_log_rental_event", fake_log_rental_event)
    monkeypatch.setattr(provider_webhook_service, "get_order", fake_get_order)
    monkeypatch.setattr(provider_webhook_service, "enqueue_event_for_user", fake_enqueue_event_for_user)
    monkeypatch.setattr(provider_webhook_service, "record_provider_webhook_event", fake_record_provider_webhook_event)

    result = await provider_webhook_service.apply_provider_temp_sms_webhook(
        provider_code="pvadeals",
        provider_order_id="rent-50",
        code="778899",
        full_sms="Your code is 778899",
        raw_event={"event": "sms_received"},
    )

    assert result["ok"] is True
    assert result["reason"] == "code_received"
    assert calls["lookup"] == ("pvadeals", "rent-50")
    assert calls["patch"][0] == "rental-1"
    assert calls["patch"][1]["rental_last_code"] == "778899"
    assert calls["patch"][1]["rental_codes"] == ["778899"]
    assert calls["patch"][1]["rental_sms_messages"] == ["Your code is 778899"]
    assert calls["event"]["event"] == "code_received"
    assert calls["webhook"]["event_type"] == "numbers.order.sms"
    assert calls["webhook"]["data"]["order"]["mode"] == "rental"
    assert calls["webhook"]["data"]["order"]["code"] == "778899"
    assert calls["provider_event"]["status"] == "processed"


@pytest.mark.asyncio
async def test_replay_provider_webhook_event_reprocesses_stored_payload(monkeypatch):
    calls = {}

    async def fake_get_provider_webhook_event(event_id):
        calls["get_event"] = event_id
        return {
            "_id": "evt-1",
            "provider": "pvadeals",
            "payload": {
                "event": "sms_received",
                "requestId": "req-1",
                "message": "Your code is 2200.",
            },
        }

    async def fake_apply_provider_temp_sms_webhook(**kwargs):
        calls["apply"] = kwargs
        return {"ok": True, "reason": "code_received", "order": {"id": "order-1"}}

    async def fake_mark_provider_webhook_event_replayed(**kwargs):
        calls["mark"] = kwargs
        return {
            "_id": kwargs["event_id"],
            "provider": "pvadeals",
            "status": "unmatched",
            "replay_status": kwargs["replay_status"],
            "replay_reason": kwargs["replay_reason"],
        }

    monkeypatch.setattr(provider_webhook_service, "get_provider_webhook_event", fake_get_provider_webhook_event)
    monkeypatch.setattr(provider_webhook_service, "apply_provider_temp_sms_webhook", fake_apply_provider_temp_sms_webhook)
    monkeypatch.setattr(provider_webhook_service, "mark_provider_webhook_event_replayed", fake_mark_provider_webhook_event_replayed)

    result = await provider_webhook_service.replay_provider_webhook_event("evt-1")

    assert result["ok"] is True
    assert calls["apply"]["provider_code"] == "pvadeals"
    assert calls["apply"]["provider_order_id"] == "req-1"
    assert calls["apply"]["full_sms"] == "Your code is 2200."
    assert calls["apply"]["record_audit"] is False
    assert calls["mark"]["replay_status"] == "processed"
    assert calls["mark"]["replay_reason"] == "code_received"
    assert calls["mark"]["order_id"] == "order-1"
    assert result["event"]["replay_status"] == "processed"


@pytest.mark.asyncio
async def test_replay_provider_webhook_event_marks_unsupported_payload(monkeypatch):
    calls = {}

    async def fake_get_provider_webhook_event(event_id):
        return {"_id": event_id, "provider": "pvadeals", "payload": {"event": "number_purchased"}}

    async def fake_mark_provider_webhook_event_replayed(**kwargs):
        calls["mark"] = kwargs
        return {
            "_id": kwargs["event_id"],
            "provider": "pvadeals",
            "replay_status": kwargs["replay_status"],
            "replay_reason": kwargs["replay_reason"],
        }

    monkeypatch.setattr(provider_webhook_service, "get_provider_webhook_event", fake_get_provider_webhook_event)
    monkeypatch.setattr(provider_webhook_service, "mark_provider_webhook_event_replayed", fake_mark_provider_webhook_event_replayed)

    result = await provider_webhook_service.replay_provider_webhook_event("evt-unsupported")

    assert result["ok"] is True
    assert result["reason"] == "unsupported_event"
    assert calls["mark"]["replay_status"] == "ignored"
    assert calls["mark"]["replay_reason"] == "unsupported_event"
