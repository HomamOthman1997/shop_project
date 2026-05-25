from datetime import UTC, datetime

import pytest

from services.numbers import order_service
from services.numbers.api_payloads import make_quote_token


def test_public_order_payload_exposes_rental_sms_state():
    payload = order_service.public_order_payload(
        {
            "_id": "rental-1",
            "number_mode": "rental",
            "status": "success",
            "service_id": "paypal:rental",
            "rental_country": "usa",
            "rental_state_code": "CA",
            "provider": "pvadeals",
            "provider_number": "+15551234567",
            "selling_price": 5.0,
            "rental_sms_received_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
            "rental_last_code": "112233",
            "rental_codes": ["112233"],
            "rental_sms_messages": ["Your code is 112233"],
        }
    )

    assert payload["mode"] == "rental"
    assert payload["public_status"] == "code_received"
    assert payload["service"] == "paypal"
    assert payload["country"] == "usa"
    assert payload["state"] == "CA"
    assert payload["code"] == "112233"
    assert payload["codes"] == ["112233"]
    assert payload["messages"] == ["Your code is 112233"]


@pytest.mark.asyncio
async def test_create_temp_order_from_quote_success(monkeypatch):
    calls = {"details": [], "statuses": [], "events": [], "temp_events": []}
    quote = make_quote_token({"mode": "temp", "service": "telegram", "country": "1", "state": "CA", "provider": "textverified"})

    async def fake_idempotency_get(user_id, key):
        calls["idempotency_get"] = (user_id, key)
        return None

    async def fake_idempotency_save(user_id, key, response):
        calls["idempotency_save"] = (user_id, key, response)

    async def fake_get_all_prices(service, country, state, **kwargs):
        calls["prices"] = (service, country, state, kwargs)
        return {
            "textverified": {
                "price": 0.44,
                "base_price": 0.4,
                "api_service_name": "telegram",
                "available_for_buy": True,
            }
        }

    async def fake_create_order(**kwargs):
        calls["create_order"] = kwargs
        return {"_id": "order-1", **kwargs}

    async def fake_update_order_details(order_id, details):
        calls["details"].append((order_id, details))

    async def fake_update_order_status(order_id, status):
        calls["statuses"].append((order_id, status))

    async def fake_process_core_purchase(**kwargs):
        calls["charge"] = kwargs
        return True, "ok"

    async def fake_buy_number_from_provider(**kwargs):
        calls["buy"] = kwargs
        return {"success": True, "order_id": "provider-1", "number": "+15551234567", "pool": "A"}

    async def fake_get_order(order_id):
        return {
            "_id": order_id,
            "status": "success",
            "number_mode": "temp",
            "temp_service_key": "telegram",
            "temp_country": "1",
            "temp_state": "CA",
            "provider_number": "+15551234567",
            "selling_price": 0.44,
            "base_price": 0.4,
            "temp_wait_state": "waiting",
        }

    async def fake_log_number_event(order, event, **kwargs):
        calls["events"].append((event, kwargs))

    async def fake_log_temp_event(order, event, payload):
        calls["temp_events"].append((event, payload))

    async def fake_enqueue_event_for_user(**kwargs):
        calls["webhook"] = kwargs

    monkeypatch.setattr(order_service, "_idempotency_get", fake_idempotency_get)
    monkeypatch.setattr(order_service, "_idempotency_save", fake_idempotency_save)
    monkeypatch.setattr(order_service, "get_all_prices", fake_get_all_prices)
    monkeypatch.setattr(order_service, "create_order", fake_create_order)
    monkeypatch.setattr(order_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_service, "update_order_status", fake_update_order_status)
    monkeypatch.setattr(order_service.FinancialManager, "process_core_purchase", fake_process_core_purchase)
    monkeypatch.setattr(order_service, "buy_number_from_provider", fake_buy_number_from_provider)
    monkeypatch.setattr(order_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_service, "_log_number_event_from_order", fake_log_number_event)
    monkeypatch.setattr(order_service, "_log_temp_event", fake_log_temp_event)
    monkeypatch.setattr(order_service, "enqueue_event_for_user", fake_enqueue_event_for_user)
    monkeypatch.setattr(order_service, "_utc_now", lambda: datetime(2026, 5, 25, 12, 0, tzinfo=UTC))

    result = await order_service.create_temp_order_from_quote(
        user_id=123,
        reseller_id=123,
        quote_token=quote,
        idempotency_key="idem-1",
        lang="en",
    )

    assert result["ok"] is True
    assert result["order"]["id"] == "order-1"
    assert "base_price" not in result["order"]
    assert calls["prices"][0:3] == ("telegram", "1", "CA")
    assert calls["charge"]["sale_price"] == 0.44
    assert calls["buy"]["provider_code"] == "textverified"
    assert calls["buy"]["api_service_name"] == "telegram"
    assert calls["statuses"] == [("order-1", "success")]
    assert calls["idempotency_save"][0:2] == (123, "idem-1")
    assert any(details.get("source") == "numbers_api" for _, details in calls["details"])
    assert any(details.get("provider_sms_delivery") == "webhook" for _, details in calls["details"])
    assert any(event == "purchase_success" for event, _ in calls["temp_events"])
    assert calls["webhook"]["event_type"] == "numbers.order.created"


@pytest.mark.asyncio
async def test_create_temp_order_marks_smsready_as_webhook_delivery(monkeypatch):
    calls = {"details": [], "statuses": [], "events": [], "temp_events": []}
    quote = make_quote_token({"mode": "temp", "service": "telegram", "country": "1", "state": "none", "provider": "smsready"})

    async def fake_get_all_prices(service, country, state, **kwargs):
        return {
            "smsready": {
                "price": 0.44,
                "base_price": 0.4,
                "api_service_name": "telegram",
                "available_for_buy": True,
            }
        }

    async def fake_create_order(**kwargs):
        return {"_id": "order-1", **kwargs}

    async def fake_update_order_details(order_id, details):
        calls["details"].append((order_id, details))

    async def fake_update_order_status(order_id, status):
        calls["statuses"].append((order_id, status))

    async def fake_process_core_purchase(**kwargs):
        return True, "ok"

    async def fake_buy_number_from_provider(**kwargs):
        return {"success": True, "order_id": "50", "number": "+15551234567"}

    async def fake_get_order(order_id):
        return {"_id": order_id, "status": "success", "number_mode": "temp", "provider_sms_delivery": "webhook"}

    async def fake_noop(*args, **kwargs):
        calls.setdefault("noop", 0)
        calls["noop"] += 1

    monkeypatch.setattr(order_service, "get_all_prices", fake_get_all_prices)
    monkeypatch.setattr(order_service, "create_order", fake_create_order)
    monkeypatch.setattr(order_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_service, "update_order_status", fake_update_order_status)
    monkeypatch.setattr(order_service.FinancialManager, "process_core_purchase", fake_process_core_purchase)
    monkeypatch.setattr(order_service, "buy_number_from_provider", fake_buy_number_from_provider)
    monkeypatch.setattr(order_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_service, "_log_number_event_from_order", fake_noop)
    monkeypatch.setattr(order_service, "_log_temp_event", fake_noop)
    monkeypatch.setattr(order_service, "enqueue_event_for_user", fake_noop)

    await order_service.create_temp_order_from_quote(user_id=123, reseller_id=123, quote_token=quote)

    assert any(details.get("provider_sms_delivery") == "webhook" for _, details in calls["details"])


@pytest.mark.asyncio
async def test_create_temp_order_from_quote_replays_idempotency(monkeypatch):
    async def fake_idempotency_get(user_id, key):
        return {"ok": True, "order": {"id": "existing"}}

    monkeypatch.setattr(order_service, "_idempotency_get", fake_idempotency_get)

    result = await order_service.create_temp_order_from_quote(
        user_id=123,
        reseller_id=123,
        quote_token="not-used",
        idempotency_key="idem-1",
    )

    assert result == {"ok": True, "order": {"id": "existing"}, "idempotent_replay": True}
