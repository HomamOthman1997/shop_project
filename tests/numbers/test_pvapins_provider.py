import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from config import settings
from services.numbers.providers.pvapins_provider import PVAPinsProvider


@pytest.fixture(autouse=True)
def _pvapins_settings(monkeypatch):
    monkeypatch.setattr(settings, "pvapins_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "pvapins_base_url", "https://api.pvapins.com/user/api", raising=False)


@pytest.mark.asyncio
async def test_pvapins_price_uses_country_app_catalog(monkeypatch):
    provider = PVAPinsProvider()
    calls = []

    async def fake_request(endpoint, *, auth=True, **params):
        calls.append((endpoint, auth, params))
        if endpoint == "load_countries.php":
            return 200, [{"id": 58, "full_name": "USA"}]
        if endpoint == "load_apps.php":
            return 200, [{"id": 2551, "app_name": "Gmail40", "deduct": "0.84"}]
        raise AssertionError(endpoint)

    monkeypatch.setattr(provider, "_request", fake_request)

    price = await provider.get_price("gmail", country="US")
    assert price["success"] is True
    assert price["price"] == 0.84
    assert price["api_service_name"] == "Gmail40"
    assert price["provider_country"] == "USA"

    app_call = [call for call in calls if call[0] == "load_apps.php"][0]
    assert app_call[1] is False
    assert app_call[2] == {"country_id": "58"}


@pytest.mark.asyncio
async def test_pvapins_purchase_sms_cancel_and_reuse(monkeypatch):
    provider = PVAPinsProvider()
    calls = []

    async def fake_request(endpoint, *, auth=True, **params):
        calls.append((endpoint, auth, params))
        if endpoint == "load_countries.php":
            return 200, [{"id": 58, "full_name": "USA"}]
        if endpoint == "get_number.php":
            if params.get("number"):
                return 200, {"data": "12817437990", "code": 100}
            return 200, {"data": "12817437990", "code": 100}
        if endpoint == "get_sms.php":
            return 200, [{"message": "Your code is 123456", "timestamp": "22/05/2026 08:15 pm"}]
        if endpoint == "get_reject_number.php":
            return 200, "Number Rejected."
        raise AssertionError(endpoint)

    monkeypatch.setattr(provider, "_request", fake_request)

    order = await provider.buy_number("Gmail40", country="USA")
    assert order["success"] is True
    assert order["number"] == "12817437990"
    assert str(order["order_id"]).startswith("pvapins:")

    sms = await provider.get_sms(order["order_id"])
    assert sms["success"] is True
    assert sms["messages"] == ["Your code is 123456"]

    cancel = await provider.cancel(order["order_id"])
    assert cancel["success"] is True

    resend = await provider.resend(order["order_id"])
    assert resend["success"] is True
    assert resend["number"] == "12817437990"

    get_number_call = [call for call in calls if call[0] == "get_number.php"][0]
    assert get_number_call[2] == {"app": "Gmail40", "country": "USA"}
    sms_call = [call for call in calls if call[0] == "get_sms.php"][0]
    assert sms_call[2] == {"number": "12817437990", "country": "USA", "app": "Gmail40"}


@pytest.mark.asyncio
async def test_pvapins_rental_flow(monkeypatch):
    provider = PVAPinsProvider()
    calls = []

    async def fake_request(endpoint, *, auth=True, **params):
        calls.append((endpoint, auth, params))
        if endpoint == "load_countries.php":
            return 200, [{"id": 58, "full_name": "USA"}]
        if endpoint == "load_apps.php":
            return 200, [{"id": 2333, "app_name": "Rent GPay GPlay GVoice", "deduct": "10.00"}]
        if endpoint == "get_number.php" and params.get("is_rent") == 1:
            return 200, {"data": "12817437990", "code": 100}
        if endpoint == "load_rent_code.php":
            return 200, [{"from": "22000", "message": "Use code 418494 only in Google Voice app"}]
        if endpoint == "reject_rent.php":
            return 200, {"data": "Rejected", "code": 100}
        if endpoint == "rent_renew_number.php":
            return 200, {"data": "Status Updated", "code": 100}
        raise AssertionError(endpoint)

    monkeypatch.setattr(provider, "_request", fake_request)

    prices = await provider.get_rental_prices("GPay GPlay", country="US")
    assert prices["success"] is True
    assert prices["options"][0]["duration_days"] == 3
    assert prices["options"][0]["provider_app"] == "Rent GPay GPlay GVoice"

    order = await provider.rent_number("Rent GPay GPlay GVoice", country="US")
    assert order["success"] is True
    assert order["number"] == "12817437990"

    sms = await provider.get_rental_sms(order["order_id"])
    assert sms["messages"] == ["Use code 418494 only in Google Voice app"]
    assert (await provider.finish_rental(order["order_id"]))["success"] is True
    assert (await provider.renew_rental(order["order_id"]))["success"] is True

    rent_country_call = [call for call in calls if call[0] == "load_countries.php"][0]
    assert rent_country_call[2] == {"is_rent": 1}
    rent_call = [call for call in calls if call[0] == "get_number.php" and call[2].get("is_rent") == 1][0]
    assert rent_call[2] == {"app": "Rent GPay GPlay GVoice", "country": "USA", "is_rent": 1}


@pytest.mark.asyncio
async def test_pvapins_rental_reject_error_is_not_success(monkeypatch):
    provider = PVAPinsProvider()
    activation_id = provider._pack_activation(number="12817437990", country="USA", app="Rent GPay")

    async def fake_request(endpoint, *, auth=True, **params):
        assert endpoint == "reject_rent.php"
        return 200, {"data": "Cant Rejected", "code": 200}

    monkeypatch.setattr(provider, "_request", fake_request)

    result = await provider.finish_rental(activation_id)
    assert result["success"] is False
