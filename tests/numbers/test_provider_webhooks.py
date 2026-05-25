from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services.numbers import provider_webhooks


def test_register_provider_webhook_routes_adds_smsready_endpoint():
    app = web.Application()

    provider_webhooks.register_provider_webhook_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("POST", "/api/v1/provider-webhooks/smsready") in routes
    assert ("POST", "/api/v1/provider-webhooks/pvadeals") in routes
    assert ("POST", "/api/v1/provider-webhooks/{provider}") in routes


@pytest.mark.asyncio
async def test_smsready_webhook_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr(provider_webhooks, "_configured_provider_webhook_token", lambda: "secret")
    request = make_mocked_request("POST", "/api/v1/provider-webhooks/smsready?token=wrong")

    response = await provider_webhooks.smsready_webhook(request)
    payload = json.loads(response.text)

    assert response.status == 401
    assert payload["code"] == "unauthorized_provider_webhook"


@pytest.mark.asyncio
async def test_smsready_webhook_applies_new_sms(monkeypatch):
    calls = {}
    monkeypatch.setattr(provider_webhooks, "_configured_provider_webhook_token", lambda: "secret")

    async def fake_apply_provider_temp_sms_webhook(**kwargs):
        calls["apply"] = kwargs
        return {"ok": True, "reason": "code_received", "order": {"id": "order-1"}}

    monkeypatch.setattr(provider_webhooks, "apply_provider_temp_sms_webhook", fake_apply_provider_temp_sms_webhook)
    request = make_mocked_request(
        "POST",
        "/api/v1/provider-webhooks/smsready?token=secret",
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps(
        {
            "event": "new_sms",
            "message": {
                "order_id": 50,
                "number": "18583056127",
                "code": "245646",
                "full_sms": "Here is your code: 245646",
            },
        }
    ).encode("utf-8")

    response = await provider_webhooks.smsready_webhook(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["ok"] is True
    assert calls["apply"]["provider_code"] == "smsready"
    assert calls["apply"]["provider_order_id"] == "50"
    assert calls["apply"]["code"] == "245646"
    assert calls["apply"]["full_sms"] == "Here is your code: 245646"


@pytest.mark.asyncio
async def test_pvadeals_webhook_applies_sms_received(monkeypatch):
    calls = {}
    monkeypatch.setattr(provider_webhooks, "_configured_provider_webhook_token", lambda: "secret")

    async def fake_apply_provider_temp_sms_webhook(**kwargs):
        calls["apply"] = kwargs
        return {"ok": True, "reason": "code_received", "order": {"id": "order-1"}}

    monkeypatch.setattr(provider_webhooks, "apply_provider_temp_sms_webhook", fake_apply_provider_temp_sms_webhook)
    request = make_mocked_request(
        "POST",
        "/api/v1/provider-webhooks/pvadeals?token=secret",
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps(
        {
            "event": "sms_received",
            "timestamp": "2026-01-28T22:57:35.001Z",
            "requestId": "697a90d25ef1873ef44f48bc",
            "serviceId": "697139f7fe5460ddc2f27214",
            "number": "+13130001234",
            "message": "Your Airbnb verification code is 2200.",
        }
    ).encode("utf-8")

    response = await provider_webhooks.pvadeals_webhook(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["ok"] is True
    assert calls["apply"]["provider_code"] == "pvadeals"
    assert calls["apply"]["provider_order_id"] == "697a90d25ef1873ef44f48bc"
    assert calls["apply"]["code"] == ""
    assert calls["apply"]["full_sms"] == "Your Airbnb verification code is 2200."


@pytest.mark.asyncio
async def test_generic_provider_webhook_normalizes_common_sms_payload(monkeypatch):
    calls = {}
    monkeypatch.setattr(provider_webhooks, "_configured_provider_webhook_token", lambda: "secret")

    async def fake_apply_provider_temp_sms_webhook(**kwargs):
        calls["apply"] = kwargs
        return {"ok": True, "reason": "code_received", "order": {"id": "order-1"}}

    monkeypatch.setattr(provider_webhooks, "apply_provider_temp_sms_webhook", fake_apply_provider_temp_sms_webhook)
    request = make_mocked_request(
        "POST",
        "/api/v1/provider-webhooks/herosms?token=secret",
        match_info={"provider": "herosms"},
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps(
        {
            "event": "smsIncoming",
            "activationId": "hero-activation-1",
            "message": {"text": "Your code is 991122", "code": "991122"},
        }
    ).encode("utf-8")

    response = await provider_webhooks.generic_provider_webhook(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["ok"] is True
    assert calls["apply"]["provider_code"] == "herosms"
    assert calls["apply"]["provider_order_id"] == "hero-activation-1"
    assert calls["apply"]["code"] == "991122"
    assert calls["apply"]["full_sms"] == "Your code is 991122"
