from datetime import UTC, datetime

import pytest

from services.numbers import order_rental_service
from services.numbers.order_service import NumbersOrderError


@pytest.mark.asyncio
async def test_rental_sms_state_returns_stored_messages_without_provider_poll(monkeypatch):
    calls = {"details": []}
    order = {
        "_id": "rental-1",
        "number_mode": "rental",
        "status": "success",
        "provider": "textverified",
        "provider_order_id": "provider-1",
        "service_id": "telegram:rental",
        "rental_sms_messages": ["Your code is 123456"],
        "rental_last_code": "123456",
        "selling_price": 3.0,
    }

    async def fake_update_order_details(order_id, patch):
        calls["details"].append((order_id, patch))

    async def fake_get_order(order_id):
        return {**order, **calls["details"][-1][1]}

    async def fail_provider_poll(*args, **kwargs):
        raise AssertionError("rental API SMS state must not poll providers")

    monkeypatch.setattr(order_rental_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_rental_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_rental_service, "finish_rental_from_provider", fail_provider_poll)

    result = await order_rental_service.rental_sms_state(order)

    assert result["ok"] is True
    assert result["messages"] == ["Your code is 123456"]
    assert result["order"]["code"] == "123456"
    assert calls["details"][0][0] == "rental-1"
    assert calls["details"][0][1]["api_last_rental_sms_check_mode"] == "provider_webhook"


@pytest.mark.asyncio
async def test_finish_rental_order_calls_provider_and_updates_public_state(monkeypatch):
    calls = {"details": [], "events": []}
    order = {
        "_id": "rental-1",
        "number_mode": "rental",
        "status": "success",
        "provider": "textverified",
        "provider_order_id": "provider-1",
        "service_id": "telegram:rental",
    }

    async def fake_finish(provider, provider_order_id):
        calls["finish"] = (provider, provider_order_id)
        return {"success": True, "raw": {"done": True}}

    async def fake_update_order_details(order_id, patch):
        calls["details"].append((order_id, patch))

    async def fake_get_order(order_id):
        return {**order, **calls["details"][-1][1]}

    async def fake_log(order_arg, event, **kwargs):
        calls["events"].append((event, kwargs))

    monkeypatch.setattr(order_rental_service, "finish_rental_from_provider", fake_finish)
    monkeypatch.setattr(order_rental_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_rental_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_rental_service, "_log_number_event_from_order", fake_log)

    result = await order_rental_service.finish_rental_order(order)

    assert result["ok"] is True
    assert result["order"]["can_finish"] is False
    assert calls["finish"] == ("textverified", "provider-1")
    assert "rental_finished_at" in calls["details"][0][1]
    assert calls["events"][0][0] == "rental_finished"


@pytest.mark.asyncio
async def test_renew_rental_order_requires_idempotency_key(monkeypatch):
    with pytest.raises(NumbersOrderError) as exc:
        await order_rental_service.renew_rental_order(
            order={"_id": "rental-1", "number_mode": "rental"},
            user_id=123,
            idempotency_key="",
        )

    assert exc.value.code == "missing_idempotency_key"
    assert exc.value.status == 400


@pytest.mark.asyncio
async def test_renew_rental_order_replays_idempotency(monkeypatch):
    async def fake_idempotency_get(**kwargs):
        return {"ok": True, "order": {"id": "rental-1"}}

    async def fail_renew(*args, **kwargs):
        raise AssertionError("cached renewal must not call provider")

    monkeypatch.setattr(order_rental_service, "_idempotency_get", fake_idempotency_get)
    monkeypatch.setattr(order_rental_service, "renew_rental_from_provider", fail_renew)

    result = await order_rental_service.renew_rental_order(
        order={"_id": "rental-1", "number_mode": "rental", "rental_is_renewable": True},
        user_id=123,
        idempotency_key="renew-1",
    )

    assert result == {"ok": True, "order": {"id": "rental-1"}, "idempotent_replay": True}


@pytest.mark.asyncio
async def test_rental_notes_state_hides_provider_raw(monkeypatch):
    calls = {"details": [], "events": []}
    order = {
        "_id": "rental-1",
        "number_mode": "rental",
        "status": "success",
        "provider": "textverified",
        "provider_order_id": "provider-1",
        "service_id": "telegram:rental",
        "created_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
    }

    async def fake_notes(provider, provider_order_id):
        calls["notes_provider"] = (provider, provider_order_id)
        return {"success": True, "notes": "Keep alive", "tags": ["vip"], "raw": {"provider": "secret"}}

    async def fake_update_order_details(order_id, patch):
        calls["details"].append((order_id, patch))

    async def fake_get_order(order_id):
        return {**order, **calls["details"][-1][1]}

    async def fake_log(order_arg, event, **kwargs):
        calls["events"].append((event, kwargs))

    monkeypatch.setattr(order_rental_service, "notes_tags_from_provider", fake_notes)
    monkeypatch.setattr(order_rental_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_rental_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_rental_service, "_log_number_event_from_order", fake_log)

    result = await order_rental_service.rental_notes_state(order)

    assert result["ok"] is True
    assert result["notes"] == "Keep alive"
    assert result["tags"] == ["vip"]
    assert "raw" not in result
    assert result["order"]["notes"] == "Keep alive"
    assert calls["notes_provider"] == ("textverified", "provider-1")
