import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from config import settings
from services.numbers.providers.smsready_provider import SMSReadyProvider


@pytest.fixture(autouse=True)
def _smsready_settings(monkeypatch):
    monkeypatch.setattr(settings, "smsready_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "smsready_base_url", "https://api.sms-ready.com/api", raising=False)


@pytest.mark.asyncio
async def test_smsready_temp_price_and_purchase(monkeypatch):
    provider = SMSReadyProvider()
    calls = []

    async def fake_request(method, endpoint, **params):
        calls.append((method, endpoint, params))
        if endpoint == "get-services-for-one-time-numbers/":
            return 200, {"status": "ok", "message": [{"service_name": "PayPal"}]}
        if endpoint == "get-countries-for-one-time-numbers/":
            return 200, {"status": "ok", "message": ["United States", "Mexico"]}
        if endpoint == "get-price-one-time-number/":
            return 200, {"status": "ok", "message": {"price": "0.525"}}
        if endpoint == "order-one-time-number/":
            return 200, {
                "status": "ok",
                "message": {
                    "order_id": 50,
                    "phone_number": "18583056127",
                    "country": "United States",
                    "service": "PayPal",
                    "expires_in": 900,
                    "cost": "0.525",
                },
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(provider, "_request", fake_request)

    price = await provider.get_price("paypal", country="US")
    assert price["success"] is True
    assert price["price"] == 0.525
    assert price["api_service_name"] == "PayPal"
    assert price["provider_country"] == "United States"

    order = await provider.buy_number("paypal", country="1")
    assert order["success"] is True
    assert order["order_id"] == "50"
    assert order["number"] == "18583056127"

    price_call = [call for call in calls if call[1] == "get-price-one-time-number/"][0]
    assert price_call[2] == {"service": "PayPal", "country": "United States"}
    order_call = [call for call in calls if call[1] == "order-one-time-number/"][0]
    assert order_call[0] == "POST"


@pytest.mark.asyncio
async def test_smsready_rental_prices_and_order(monkeypatch):
    provider = SMSReadyProvider()
    calls = []

    async def fake_request(method, endpoint, **params):
        calls.append((method, endpoint, params))
        if endpoint == "get-services-ltr/":
            return 200, {"status": "ok", "message": {"PayPal": {"durations": [3, 30, "per day"]}}}
        if endpoint == "get-countries-for-long-term/":
            return 200, {"status": "ok", "message": ["United States"]}
        if endpoint == "get-order-info-ltr/":
            return 200, {"status": "ok", "message": {"per day": 0.55, "3": 1.5, "30": 12.0}}
        if endpoint == "order-ltr/":
            return 200, {
                "status": "ok",
                "message": {
                    "order_id": 123,
                    "phone_number": "18583056127",
                    "expires_at": "2026-06-30 23:59:59",
                    "cost": "1.50",
                },
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(provider, "_request", fake_request)

    prices = await provider.get_rental_prices("paypal", country="US")
    assert prices["success"] is True
    assert [row["duration_label"] for row in prices["options"]] == ["per day", "3d", "30d"]
    assert prices["options"][0]["provider_duration"] == "per day"

    order = await provider.rent_number(
        "paypal",
        country="US",
        duration=24,
        duration_days=1,
        provider_duration="per day",
    )
    assert order["success"] is True
    assert order["order_id"] == "123"
    assert order["number"] == "18583056127"

    rent_call = [call for call in calls if call[1] == "order-ltr/"][0]
    assert rent_call[0] == "POST"
    assert rent_call[2]["duration"] == "per day"


@pytest.mark.asyncio
async def test_smsready_cancel_and_resend(monkeypatch):
    provider = SMSReadyProvider()

    async def fake_request(method, endpoint, **params):
        if endpoint == "refund-one-time-order/":
            return 200, {"status": "ok", "message": "Order has been canceled and money has been refunded."}
        if endpoint == "resend-one-time-order/":
            return 200, {"status": "ok", "message": {"order_id": 51, "phone_number": "18583056127"}}
        raise AssertionError(endpoint)

    monkeypatch.setattr(provider, "_request", fake_request)

    assert (await provider.cancel("50"))["success"] is True
    resend = await provider.resend("50")
    assert resend["success"] is True
    assert resend["order_id"] == "51"
    assert resend["number"] == "18583056127"
