from datetime import UTC, datetime

import pytest

from services.numbers import order_service
from services.numbers import api_payloads
from services.numbers.api_payloads import make_quote_token, rental_option_match_key


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
            "provider_order_id": "provider-rental-1",
            "rental_duration_label": "24h",
            "rental_end_date": "2026-05-26T12:00:00Z",
            "rental_is_renewable": True,
            "rental_notes": "Keep alive",
            "rental_tags": ["vip", "login"],
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
    assert payload["duration_label"] == "24h"
    assert payload["end_date"] == "2026-05-26T12:00:00Z"
    assert payload["notes"] == "Keep alive"
    assert payload["tags"] == ["vip", "login"]
    assert payload["can_finish"] is True
    assert payload["can_renew"] is True
    assert payload["can_wake"] is True
    assert payload["can_notes"] is True


def test_public_order_payload_exposes_voice_recording_state():
    payload = order_service.public_order_payload(
        {
            "_id": "voice-1",
            "number_mode": "voice",
            "status": "success",
            "temp_wait_state": "waiting_for_recording",
            "temp_service_key": "telegram",
            "temp_country": "1",
            "provider": "textverified",
            "provider_number": "+15551234567",
            "selling_price": 0.5,
            "voice_calls_count": 1,
            "voice_recording_uri": "/api/pub/v2/calls/call-1/recording",
        }
    )

    assert payload["mode"] == "voice"
    assert payload["public_status"] == "call_received"
    assert payload["calls_count"] == 1
    assert payload["recording_available"] is True
    assert payload["recording_url"] == "/api/v1/numbers/orders/voice-1/recording"
    assert payload["can_refresh"] is False


def test_public_order_payload_exposes_safe_replacement_state():
    payload = order_service.public_order_payload(
        {
            "_id": "temp-refunded",
            "number_mode": "temp",
            "status": "cancelled",
            "temp_wait_state": "refunded",
            "temp_service_key": "telegram",
            "temp_country": "1",
            "provider": "textverified",
            "provider_number": "+15551234567",
            "selling_price": 0.44,
            "temp_codes": [],
            "temp_alternate_enabled": True,
            "temp_alternate_provider": "herosms",
            "temp_alternate_price": 0.66,
        }
    )

    assert payload["can_replace"] is True
    assert payload["can_alternate_provider"] is True
    assert payload["alternate_provider"] == "Alpha"
    assert payload["alternate_provider_id"] == "S1"
    assert payload["alternate_provider_price_label"] == "$0.66"
    assert "textverified" not in payload["alternate_provider"]


def test_public_order_payload_uses_customer_safe_refund_reason():
    refunded = order_service.public_order_payload(
        {
            "_id": "temp-refunded",
            "number_mode": "temp",
            "status": "cancelled",
            "temp_wait_state": "refunded",
            "temp_refund_reason": "provider_cancel_failed",
            "temp_refund_source": "provider",
            "temp_provider_terminal_reason": "provider_missing_or_expired",
            "provider": "textverified",
            "provider_number": "+15551234567",
            "selling_price": 0.44,
            "base_price": 0.4,
        }
    )
    pending = order_service.public_order_payload(
        {
            "_id": "temp-pending",
            "number_mode": "temp",
            "status": "success",
            "temp_wait_state": "refund_pending",
            "temp_refund_reason": "provider_empty_response",
            "provider": "textverified",
            "provider_number": "+15551234567",
            "selling_price": 0.44,
            "base_price": 0.4,
        }
    )

    assert refunded["refund"]["reason"] == "automatic_refund"
    assert "provider" not in refunded["refund"]["reason"]
    assert pending["refund"]["reason"] == "refund_pending"
    assert "provider" not in pending["refund"]["reason"]
    assert "base_price" not in refunded


def test_public_order_payload_includes_customer_state_without_provider_names():
    payload = order_service.public_order_payload(
        {
            "_id": "temp-waiting",
            "number_mode": "temp",
            "status": "success",
            "temp_wait_state": "waiting",
            "temp_service_key": "telegram",
            "temp_country": "1",
            "provider": "textverified",
            "provider_sms_delivery": "webhook",
            "provider_number": "+15551234567",
            "provider_order_id": "provider-1",
            "selling_price": 0.44,
        }
    )

    state = payload["customer_state"]
    assert state["key"] == "awaiting_provider_webhook"
    assert state["tone"] == "waiting"
    assert state["message_key"] == "waitForWebhook"
    assert state["awaiting_webhook"] is True
    assert state["auto_refund_managed"] is True
    assert state["manual_refund_available"] is False
    assert state["show_provider_identity"] is False
    assert state["provider_reference"] == payload["provider_id"]
    assert "textverified" not in str(state).lower()


def test_public_order_payload_customer_state_marks_support_review_refund():
    payload = order_service.public_order_payload(
        {
            "_id": "temp-review",
            "number_mode": "temp",
            "status": "success",
            "temp_wait_state": "refund_pending",
            "temp_refund_support_review_status": "open",
            "temp_service_key": "telegram",
            "temp_country": "1",
            "provider": "nonvoip",
            "provider_sms_delivery": "webhook",
            "provider_number": "+15551234567",
            "provider_order_id": "provider-1",
            "selling_price": 0.44,
        }
    )

    state = payload["customer_state"]
    assert payload["public_status"] == "refund_pending"
    assert state["key"] == "support_review_pending"
    assert state["tone"] == "pending-refund"
    assert state["message_key"] == "supportReviewQueued"
    assert state["support_review_open"] is True
    assert state["manual_refund_available"] is False
    assert "nonvoip" not in str(state).lower()


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

    async def fake_charge_order_or_raise(**kwargs):
        calls["charge"] = {
            "sale_price": kwargs["final_price"],
            "cost_price": kwargs["cost_price"],
            "user_id": kwargs["user_id"],
            "order_id": kwargs["order_id"],
            "reseller_id": kwargs["reseller_id"],
        }

    async def fake_buy_number_from_provider(**kwargs):
        calls["buy"] = kwargs
        return {"success": True, "order_id": "provider-1", "number": "+15551234567", "pool": "A"}

    async def fake_provision_charged_temp_order(**kwargs):
        buy_res = await fake_buy_number_from_provider(
            provider_code=kwargs["provider_code"],
            api_service_name=kwargs["api_service"],
            country=kwargs["country"],
            state=kwargs["state"],
            dry_run=False,
            purchase_options={**(kwargs.get("purchase_options") or {}), "source": kwargs["source"]},
        )
        await fake_update_order_details(
            kwargs["order_id"],
            {
                "provider_order_id": buy_res["order_id"],
                "provider": kwargs["provider_code"],
                "provider_sms_delivery": "webhook",
                "provider_number": buy_res["number"],
                "provider_pool": buy_res["pool"],
                "source": kwargs["source"],
            },
        )
        await fake_update_order_status(kwargs["order_id"], "success")
        await fake_log_temp_event(
            {"_id": kwargs["order_id"]},
            "purchase_success",
            {"provider_order_id": buy_res["order_id"], "provider_pool": buy_res["pool"], "source": kwargs["source"]},
        )
        return {"provider_order_id": buy_res["order_id"], "number": buy_res["number"]}

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
    monkeypatch.setattr(order_service, "charge_order_or_raise", fake_charge_order_or_raise)
    monkeypatch.setattr(order_service, "provision_charged_temp_order", fake_provision_charged_temp_order)
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
async def test_resolve_temp_offer_uses_provider_country_from_quote(monkeypatch):
    calls = {}
    quote = make_quote_token(
        {
            "mode": "temp",
            "service": "whatsapp",
            "country": "none",
            "state": "none",
            "provider": "herosms",
            "provider_country": "102",
            "provider_country_iso": "GR",
        }
    )

    async def fake_get_all_prices(service, country, state, **kwargs):
        calls["prices"] = (service, country, state, kwargs)
        return {
            "herosms": {
                "price": 0.25,
                "base_price": 0.25,
                "api_service_name": "wa",
                "provider_country": "102",
                "provider_country_iso": "GR",
                "available_for_buy": True,
            }
        }

    monkeypatch.setattr(order_service, "get_all_prices", fake_get_all_prices)

    offer = await order_service._resolve_temp_offer_from_quote(quote)

    assert calls["prices"][0:3] == ("whatsapp", "102", "none")
    assert offer["country"] == "none"
    assert offer["info"]["provider_country"] == "102"


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

    async def fake_charge_order_or_raise(**kwargs):
        return None

    async def fake_buy_number_from_provider(**kwargs):
        return {"success": True, "order_id": "50", "number": "+15551234567"}

    async def fake_provision_charged_temp_order(**kwargs):
        await fake_buy_number_from_provider(
            provider_code=kwargs["provider_code"],
            api_service_name=kwargs["api_service"],
            country=kwargs["country"],
            state=kwargs["state"],
            dry_run=False,
            purchase_options={**(kwargs.get("purchase_options") or {}), "source": kwargs["source"]},
        )
        await fake_update_order_details(kwargs["order_id"], {"provider_sms_delivery": "webhook"})
        await fake_update_order_status(kwargs["order_id"], "success")
        await fake_noop()
        return {"provider_order_id": "50", "number": "+15551234567"}

    async def fake_get_order(order_id):
        return {"_id": order_id, "status": "success", "number_mode": "temp", "provider_sms_delivery": "webhook"}

    async def fake_noop(*args, **kwargs):
        calls.setdefault("noop", 0)
        calls["noop"] += 1

    monkeypatch.setattr(order_service, "get_all_prices", fake_get_all_prices)
    monkeypatch.setattr(order_service, "create_order", fake_create_order)
    monkeypatch.setattr(order_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_service, "update_order_status", fake_update_order_status)
    monkeypatch.setattr(order_service, "charge_order_or_raise", fake_charge_order_or_raise)
    monkeypatch.setattr(order_service, "provision_charged_temp_order", fake_provision_charged_temp_order)
    monkeypatch.setattr(order_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_service, "provider_purchase_enabled", lambda provider, mode="temp": True)
    monkeypatch.setattr(api_payloads, "provider_purchase_enabled", lambda provider, mode="temp": True)
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


@pytest.mark.asyncio
async def test_create_voice_order_from_quote_success(monkeypatch):
    calls = {"details": [], "statuses": [], "events": [], "temp_events": []}
    quote = make_quote_token({"mode": "voice", "service": "telegram", "country": "1", "state": "CA", "provider": "textverified"})

    async def fake_idempotency_get(*args, **kwargs):
        calls["idempotency_get"] = (args, kwargs)
        return None

    async def fake_idempotency_save(*args, **kwargs):
        calls["idempotency_save"] = (args, kwargs)

    async def fake_get_all_voice_prices(service, country, state, ignore_balance=False):
        calls["prices"] = (service, country, state, ignore_balance)
        return {
            "textverified": {
                "price": 0.66,
                "base_price": 0.5,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "voice_capable": True,
            }
        }

    async def fake_create_order(**kwargs):
        calls["create_order"] = kwargs
        return {"_id": "voice-order-1", **kwargs}

    async def fake_update_order_details(order_id, details):
        calls["details"].append((order_id, details))

    async def fake_update_order_status(order_id, status):
        calls["statuses"].append((order_id, status))

    async def fake_process_core_purchase(**kwargs):
        calls["charge"] = kwargs
        return True, "ok"

    async def fake_charge_order_or_raise(**kwargs):
        calls["charge"] = {
            "sale_price": kwargs["final_price"],
            "cost_price": kwargs["cost_price"],
            "user_id": kwargs["user_id"],
            "order_id": kwargs["order_id"],
            "reseller_id": kwargs["reseller_id"],
        }

    async def fake_buy_number_from_provider(**kwargs):
        calls["buy"] = kwargs
        return {"success": True, "order_id": "provider-voice-1", "number": "+15551234567", "pool": "voice"}

    async def fake_provision_charged_temp_order(**kwargs):
        buy_res = await fake_buy_number_from_provider(
            provider_code=kwargs["provider_code"],
            api_service_name=kwargs["api_service"],
            country=kwargs["country"],
            state=kwargs["state"],
            dry_run=False,
            purchase_options={**(kwargs.get("purchase_options") or {}), "source": kwargs["source"]},
        )
        await fake_update_order_details(
            kwargs["order_id"],
            {
                "provider_order_id": buy_res["order_id"],
                "provider": kwargs["provider_code"],
                "provider_sms_delivery": "webhook",
                "provider_number": buy_res["number"],
                "provider_pool": buy_res["pool"],
                "number_mode": kwargs["number_mode"],
                "temp_wait_state": "waiting_for_call",
            },
        )
        await fake_update_order_status(kwargs["order_id"], "success")
        await fake_log_temp_event(
            {"_id": kwargs["order_id"]},
            "purchase_success",
            {"provider_order_id": buy_res["order_id"], "provider_pool": buy_res["pool"], "source": kwargs["source"]},
        )
        return {"provider_order_id": buy_res["order_id"], "number": buy_res["number"]}

    async def fake_get_order(order_id):
        return {
            "_id": order_id,
            "status": "success",
            "number_mode": "voice",
            "temp_service_key": "telegram",
            "temp_country": "1",
            "temp_state": "CA",
            "provider": "textverified",
            "provider_sms_delivery": "webhook",
            "provider_order_id": "provider-voice-1",
            "provider_number": "+15551234567",
            "selling_price": 0.66,
            "base_price": 0.5,
            "temp_wait_state": "waiting_for_call",
        }

    async def fake_log_number_event(order, event, **kwargs):
        calls["events"].append((event, kwargs))

    async def fake_log_temp_event(order, event, payload):
        calls["temp_events"].append((event, payload))

    async def fake_enqueue_event_for_user(**kwargs):
        calls["webhook"] = kwargs

    monkeypatch.setattr(order_service, "_idempotency_get_for_operation", fake_idempotency_get)
    monkeypatch.setattr(order_service, "_idempotency_save_for_operation", fake_idempotency_save)
    monkeypatch.setattr(order_service, "get_all_voice_prices", fake_get_all_voice_prices)
    monkeypatch.setattr(order_service, "create_order", fake_create_order)
    monkeypatch.setattr(order_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_service, "update_order_status", fake_update_order_status)
    monkeypatch.setattr(order_service, "charge_order_or_raise", fake_charge_order_or_raise)
    monkeypatch.setattr(order_service, "provision_charged_temp_order", fake_provision_charged_temp_order)
    monkeypatch.setattr(order_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_service, "_log_number_event_from_order", fake_log_number_event)
    monkeypatch.setattr(order_service, "_log_temp_event", fake_log_temp_event)
    monkeypatch.setattr(order_service, "enqueue_event_for_user", fake_enqueue_event_for_user)
    monkeypatch.setattr(order_service, "_utc_now", lambda: datetime(2026, 5, 25, 12, 0, tzinfo=UTC))

    result = await order_service.create_voice_order_from_quote(
        user_id=123,
        reseller_id=456,
        quote_token=quote,
        idempotency_key="voice-1",
        lang="en",
    )

    assert result["ok"] is True
    assert result["order"]["id"] == "voice-order-1"
    assert result["order"]["mode"] == "voice"
    assert result["order"]["provider"] == "Bravo"
    assert "base_price" not in result["order"]
    assert calls["idempotency_get"] == ((123, "voice-1"), {"operation": "create_voice_order"})
    assert calls["prices"] == ("telegram", "1", "CA", True)
    assert calls["create_order"]["service_id"] == "telegram"
    assert calls["charge"]["sale_price"] == 0.66
    assert calls["charge"]["cost_price"] == 0.5
    assert calls["buy"]["provider_code"] == "textverified"
    assert calls["buy"]["purchase_options"]["capability"] == "voice"
    assert calls["buy"]["purchase_options"]["source"] == "numbers_api"
    assert calls["statuses"] == [("voice-order-1", "success")]
    assert any(details.get("provider_sms_delivery") == "webhook" for _, details in calls["details"])
    assert any(details.get("temp_wait_state") == "waiting_for_call" for _, details in calls["details"])
    assert any(event == "purchase_success" for event, _ in calls["temp_events"])
    assert calls["webhook"]["event_type"] == "numbers.order.created"


@pytest.mark.asyncio
async def test_create_rental_order_from_quote_success(monkeypatch):
    calls = {"details": [], "statuses": [], "events": []}
    option = {
        "duration": 24,
        "duration_label": "1d",
        "price": 4.0,
        "base_price": 3.0,
        "tv_duration_key": "oneDay",
        "tv_is_renewable": False,
        "state_code": "NY",
    }
    quote = make_quote_token(
        {
            "mode": "rental",
            "service": "telegram",
            "country": "1",
            "state": "NY",
            "provider": "textverified",
            "option_key": list(rental_option_match_key(option)),
        }
    )

    async def fake_idempotency_get(*args, **kwargs):
        calls["idempotency_get"] = (args, kwargs)
        return None

    async def fake_idempotency_save(*args, **kwargs):
        calls["idempotency_save"] = (args, kwargs)

    async def fake_get_all_rental_prices(service, country, with_success_rates=False):
        calls["prices"] = (service, country, with_success_rates)
        return {
            "textverified": {
                "api_service_name": "telegram",
                "available_for_buy": True,
                "options": [option],
            }
        }

    async def fake_create_order(**kwargs):
        calls["create_order"] = kwargs
        return {"_id": "rental-order-1", **kwargs}

    async def fake_update_order_details(order_id, details):
        calls["details"].append((order_id, details))

    async def fake_update_order_status(order_id, status):
        calls["statuses"].append((order_id, status))

    async def fake_process_core_purchase(**kwargs):
        calls["charge"] = kwargs
        return True, "ok"

    async def fake_charge_order_or_raise(**kwargs):
        calls["charge"] = {
            "sale_price": kwargs["final_price"],
            "cost_price": kwargs["cost_price"],
            "user_id": kwargs["user_id"],
            "order_id": kwargs["order_id"],
            "reseller_id": kwargs["reseller_id"],
        }

    async def fake_rent_number_from_provider(**kwargs):
        calls["rent"] = kwargs
        return {
            "success": True,
            "order_id": "provider-rental-1",
            "number": "+15551234567",
            "end_date": "2026-05-26T12:00:00Z",
            "price": 3.0,
        }

    async def fake_provision_charged_rental_order(**kwargs):
        rent_res = await fake_rent_number_from_provider(
            provider_code=kwargs["provider_code"],
            api_service_name=kwargs["api_service"],
            country=kwargs["country"],
            duration=kwargs["duration"],
            option_meta=kwargs.get("option_meta") or {},
        )
        await fake_update_order_details(
            kwargs["order_id"],
            {
                "provider_order_id": rent_res["order_id"],
                "provider": kwargs["provider_code"],
                "provider_sms_delivery": "webhook",
                "provider_number": rent_res["number"],
                "rental_state_code": (kwargs.get("option_meta") or {}).get("state_code"),
                "source": kwargs["source"],
            },
        )
        await fake_update_order_status(kwargs["order_id"], "success")
        return {"provider_order_id": rent_res["order_id"], "number": rent_res["number"], "rental_safe_cutoff_at": None}

    async def fake_get_order(order_id):
        return {
            "_id": order_id,
            "status": "success",
            "number_mode": "rental",
            "service_id": "telegram:rental",
            "provider": "textverified",
            "provider_order_id": "provider-rental-1",
            "provider_number": "+15551234567",
            "rental_country": "1",
            "rental_state_code": "NY",
            "rental_duration_label": "1d",
            "selling_price": 6.0,
            "base_price": 5.0,
        }

    async def fake_log_number_event(order, event, **kwargs):
        calls["events"].append((event, kwargs))

    async def fake_enqueue_event_for_user(**kwargs):
        calls["webhook"] = kwargs

    monkeypatch.setattr(order_service, "_idempotency_get_for_operation", fake_idempotency_get)
    monkeypatch.setattr(order_service, "_idempotency_save_for_operation", fake_idempotency_save)
    monkeypatch.setattr(order_service, "get_all_rental_prices", fake_get_all_rental_prices)
    monkeypatch.setattr(order_service, "create_order", fake_create_order)
    monkeypatch.setattr(order_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_service, "update_order_status", fake_update_order_status)
    monkeypatch.setattr(order_service, "charge_order_or_raise", fake_charge_order_or_raise)
    monkeypatch.setattr(order_service, "provision_charged_rental_order", fake_provision_charged_rental_order)
    monkeypatch.setattr(order_service, "get_order", fake_get_order)
    monkeypatch.setattr(order_service, "_log_number_event_from_order", fake_log_number_event)
    monkeypatch.setattr(order_service, "enqueue_event_for_user", fake_enqueue_event_for_user)
    monkeypatch.setattr(order_service, "_utc_now", lambda: datetime(2026, 5, 25, 12, 0, tzinfo=UTC))

    result = await order_service.create_rental_order_from_quote(
        user_id=123,
        reseller_id=456,
        quote_token=quote,
        idempotency_key="rent-1",
        lang="en",
    )

    assert result["ok"] is True
    assert result["order"]["id"] == "rental-order-1"
    assert result["order"]["provider"] == "Bravo"
    assert "base_price" not in result["order"]
    assert calls["idempotency_get"] == ((123, "rent-1"), {"operation": "create_rental_order"})
    assert calls["prices"] == ("telegram", "1", False)
    assert calls["create_order"]["service_id"] == "telegram:rental"
    assert calls["charge"]["sale_price"] == 6.0
    assert calls["charge"]["cost_price"] == 5.0
    assert calls["rent"]["provider_code"] == "textverified"
    assert calls["rent"]["duration"] == 24
    assert calls["rent"]["option_meta"]["state_code"] == "NY"
    assert calls["statuses"] == [("rental-order-1", "success")]
    assert any(details.get("source") == "numbers_api" for _, details in calls["details"])
    assert any(details.get("provider_sms_delivery") == "webhook" for _, details in calls["details"])
    assert calls["webhook"]["event_type"] == "numbers.order.created"


@pytest.mark.asyncio
async def test_create_number_order_from_quote_routes_rental(monkeypatch):
    quote = make_quote_token(
        {
            "mode": "rental",
            "service": "telegram",
            "country": "1",
            "state": "none",
            "provider": "textverified",
            "option_key": ["24", "", "oneDay", "0", "none", "1d"],
        }
    )
    calls = {}

    async def fake_create_rental_order_from_quote(**kwargs):
        calls.update(kwargs)
        return {"ok": True, "order": {"id": "rental-order-1"}}

    monkeypatch.setattr(order_service, "create_rental_order_from_quote", fake_create_rental_order_from_quote)

    result = await order_service.create_number_order_from_quote(
        user_id=123,
        reseller_id=456,
        quote_token=quote,
        idempotency_key="rent-1",
        lang="en",
    )

    assert result == {"ok": True, "order": {"id": "rental-order-1"}}
    assert calls == {
        "user_id": 123,
        "reseller_id": 456,
        "quote_token": quote,
        "idempotency_key": "rent-1",
        "lang": "en",
    }


@pytest.mark.asyncio
async def test_create_number_order_from_quote_routes_voice(monkeypatch):
    quote = make_quote_token(
        {
            "mode": "voice",
            "service": "telegram",
            "country": "1",
            "state": "CA",
            "provider": "textverified",
        }
    )
    calls = {}

    async def fake_create_voice_order_from_quote(**kwargs):
        calls.update(kwargs)
        return {"ok": True, "order": {"id": "voice-order-1"}}

    monkeypatch.setattr(order_service, "create_voice_order_from_quote", fake_create_voice_order_from_quote)

    result = await order_service.create_number_order_from_quote(
        user_id=123,
        reseller_id=456,
        quote_token=quote,
        idempotency_key="voice-1",
        lang="en",
    )

    assert result == {"ok": True, "order": {"id": "voice-order-1"}}
    assert calls == {
        "user_id": 123,
        "reseller_id": 456,
        "quote_token": quote,
        "idempotency_key": "voice-1",
        "lang": "en",
    }


@pytest.mark.asyncio
async def test_request_replacement_order_uses_current_provider(monkeypatch):
    order = {
        "_id": "temp-order-id",
        "number_mode": "temp",
        "status": "cancelled",
        "temp_wait_state": "refunded",
        "provider": "textverified",
        "temp_service_key": "gmail",
        "temp_country": "1",
        "temp_state": "none",
        "temp_codes": [],
    }
    calls = {"temp_events": []}

    async def fake_get_all_prices(service, country, state, **kwargs):
        calls["prices"] = (service, country, state, kwargs)
        return {
            "textverified": {
                "price": 0.44,
                "base_price": 0.4,
                "api_service_name": "gmail",
                "available_for_buy": True,
            }
        }

    async def fake_create_temp_order_from_quote(**kwargs):
        calls["create_temp"] = kwargs
        return {"ok": True, "order": {"id": "replacement-order"}}

    async def fake_log_temp_event(order_arg, event, payload):
        calls["temp_events"].append((event, payload))

    monkeypatch.setattr(order_service, "get_all_prices", fake_get_all_prices)
    monkeypatch.setattr(order_service, "create_temp_order_from_quote", fake_create_temp_order_from_quote)
    monkeypatch.setattr(order_service, "_log_temp_event", fake_log_temp_event)

    result = await order_service.request_replacement_order(
        order=order,
        user_id=123,
        reseller_id=456,
        idempotency_key="replace-1",
        lang="en",
    )

    quote = make_quote_token({"mode": "temp", "service": "dummy", "country": "none", "provider": "textverified"})
    assert result == {"ok": True, "order": {"id": "replacement-order"}}
    assert calls["prices"][0:3] == ("gmail", "1", "none")
    assert calls["create_temp"]["source_order_id"] == "temp-order-id"
    assert calls["create_temp"]["source_reason"] == "replace_request"
    assert calls["create_temp"]["idempotency_operation"] == "replace_temp_order"
    assert calls["create_temp"]["idempotency_key"] == "replace-1"
    resolved = order_service.verify_quote_token(calls["create_temp"]["quote_token"])
    assert resolved["provider_id"] == order_service.verify_quote_token(quote)["provider_id"]
    assert "provider" not in resolved
    assert calls["temp_events"][-1][0] == "replacement_requested"


@pytest.mark.asyncio
async def test_request_replacement_order_picks_alternate_provider(monkeypatch):
    order = {
        "_id": "temp-order-id",
        "number_mode": "temp",
        "status": "cancelled",
        "temp_wait_state": "refunded",
        "provider": "textverified",
        "temp_service_key": "gmail",
        "temp_country": "1",
        "temp_state": "none",
        "temp_codes": [],
    }
    calls = {"details": [], "temp_events": []}

    async def fake_get_all_prices(service, country, state, **kwargs):
        calls.setdefault("prices", []).append((service, country, state, kwargs))
        return {
            "textverified": {
                "price": 0.44,
                "base_price": 0.4,
                "api_service_name": "gmail",
                "available_for_buy": True,
            },
            "herosms": {
                "price": 0.66,
                "base_price": 0.6,
                "api_service_name": "gmail",
                "available_for_buy": True,
                "success_attempts": 6,
                "success_rate": 99,
            },
        }

    async def fake_update_order_details(order_id, patch):
        calls["details"].append((order_id, patch))

    async def fake_create_temp_order_from_quote(**kwargs):
        calls["create_temp"] = kwargs
        return {"ok": True, "order": {"id": "alternate-order"}}

    async def fake_log_temp_event(order_arg, event, payload):
        calls["temp_events"].append((event, payload))

    monkeypatch.setattr(order_service, "get_all_prices", fake_get_all_prices)
    monkeypatch.setattr(order_service, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(order_service, "create_temp_order_from_quote", fake_create_temp_order_from_quote)
    monkeypatch.setattr(order_service, "_log_temp_event", fake_log_temp_event)

    result = await order_service.request_replacement_order(
        order=order,
        user_id=123,
        reseller_id=456,
        idempotency_key="alternate-1",
        alternate_provider=True,
        lang="en",
    )

    assert result == {"ok": True, "order": {"id": "alternate-order"}}
    assert calls["details"][0][1]["temp_alternate_provider"] == "herosms"
    resolved = order_service.verify_quote_token(calls["create_temp"]["quote_token"])
    assert resolved["provider_id"] == "S1"
    assert calls["create_temp"]["source_reason"] == "alternate_provider_request"
    assert calls["create_temp"]["idempotency_operation"] == "alternate_provider_order"
    assert any(event == "alternate_provider_suggested" for event, _ in calls["temp_events"])
    assert calls["temp_events"][-1][1]["alternate_provider"] is True


@pytest.mark.asyncio
async def test_request_replacement_order_passes_client_source_to_temp_creation(monkeypatch):
    order = {
        "_id": "temp-order-id",
        "number_mode": "temp",
        "status": "cancelled",
        "temp_wait_state": "refunded",
        "provider": "textverified",
        "temp_service_key": "gmail",
        "temp_country": "1",
        "temp_state": "none",
        "temp_codes": [],
    }
    calls = {"temp_events": []}

    async def fake_get_all_prices(service, country, state, **kwargs):
        return {
            "textverified": {
                "price": 0.44,
                "base_price": 0.4,
                "api_service_name": "gmail",
                "available_for_buy": True,
            }
        }

    async def fake_create_temp_order_from_quote(**kwargs):
        calls["create_temp"] = kwargs
        return {"ok": True, "order": {"id": "telegram-replacement-order"}}

    async def fake_log_temp_event(order_arg, event, payload):
        calls["temp_events"].append((event, payload))

    monkeypatch.setattr(order_service, "get_all_prices", fake_get_all_prices)
    monkeypatch.setattr(order_service, "create_temp_order_from_quote", fake_create_temp_order_from_quote)
    monkeypatch.setattr(order_service, "_log_temp_event", fake_log_temp_event)

    result = await order_service.request_replacement_order(
        order=order,
        user_id=123,
        reseller_id=456,
        idempotency_key="telegram:replace:123:temp-order-id",
        lang="en",
        source="numbers_telegram",
        telegram_bot_id=987,
        telegram_wait={"chat_id": 111, "message_id": 222, "bot_id": 987},
    )

    assert result == {"ok": True, "order": {"id": "telegram-replacement-order"}}
    assert calls["create_temp"]["source"] == "numbers_telegram"
    assert calls["create_temp"]["telegram_bot_id"] == 987
    assert calls["create_temp"]["telegram_wait"] == {"chat_id": 111, "message_id": 222, "bot_id": 987}
    assert calls["temp_events"][-1][1]["source"] == "numbers_telegram"
