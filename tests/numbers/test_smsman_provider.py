import pytest

from config import settings
from services.numbers.providers.smsman_provider import SMSManProvider


@pytest.mark.asyncio
async def test_resolve_service_code_by_name(monkeypatch):
    provider = SMSManProvider()

    async def fake_services(force_refresh=False):
        return [
            {"id": 1, "name": "Telegram", "code": "tg"},
            {"id": 2, "name": "WhatsApp", "code": "wa"},
        ]

    monkeypatch.setattr(provider, "list_services", fake_services)
    code = await provider.resolve_service_code("telegram")
    assert code == "1"


@pytest.mark.asyncio
async def test_get_price_parses_nested_payload(monkeypatch):
    provider = SMSManProvider()
    monkeypatch.setattr(settings, "smsman_price_currency", "USD")

    async def fake_resolve_country(country):
        assert country == "1"
        return "187"

    async def fake_request(endpoint, **params):
        assert endpoint == "get-prices"
        assert str(params.get("country_id")) == "187"
        return 200, {
            "187": {
                "1": {"cost": "0.6", "count": 12},
                "2": {"cost": "1.1", "count": 5},
            }
        }

    monkeypatch.setattr(provider, "_resolve_country", fake_resolve_country)
    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.get_price("1", country="1")
    assert res["success"] is True
    assert res["price"] == 0.6
    assert res["count"] == 12


@pytest.mark.asyncio
async def test_buy_number_success(monkeypatch):
    provider = SMSManProvider()

    async def fake_resolve_country(country):
        return "187"

    async def fake_request(endpoint, **params):
        if endpoint == "limits":
            return 200, [{"application_id": "1", "country_id": "187", "numbers": "15"}]
        assert endpoint == "get-number"
        assert str(params.get("country_id")) == "187"
        assert int(params.get("application_id")) == 1
        return 200, {"request_id": 99, "number": "79002415539"}

    monkeypatch.setattr(provider, "_resolve_country", fake_resolve_country)
    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.buy_number("1", country="1")
    assert res["success"] is True
    assert res["order_id"] == "99"
    assert res["number"] == "79002415539"


@pytest.mark.asyncio
async def test_buy_number_blocked_by_limits(monkeypatch):
    provider = SMSManProvider()

    async def fake_resolve_country(country):
        return "187"

    async def fake_request(endpoint, **params):
        if endpoint == "limits":
            return 200, [{"application_id": "1", "country_id": "187", "numbers": "0"}]
        raise AssertionError("get-number should not be called when limits says 0")

    monkeypatch.setattr(provider, "_resolve_country", fake_resolve_country)
    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.buy_number("1", country="1")
    assert res["success"] is False
    assert isinstance(res.get("raw"), dict)
    assert res["raw"].get("error_code") == "NO_NUMBERS"


@pytest.mark.asyncio
async def test_get_sms_wait_and_code(monkeypatch):
    provider = SMSManProvider()

    calls = {"n": 0}

    async def fake_request(endpoint, **params):
        assert endpoint == "get-sms"
        calls["n"] += 1
        if calls["n"] == 1:
            return 200, {"request_id": 1, "error_code": "wait_sms", "error_msg": "Still waiting..."}
        return 200, {"request_id": 1, "sms_code": "1243"}

    monkeypatch.setattr(provider, "_request", fake_request)

    first = await provider.get_sms("1")
    assert first["success"] is True
    assert first["messages"] == []

    second = await provider.get_sms("1")
    assert second["success"] is True
    assert second["messages"] == ["1243"]


@pytest.mark.asyncio
async def test_cancel_fallback_to_close(monkeypatch):
    provider = SMSManProvider()

    calls: list[str] = []

    async def fake_request(endpoint, **params):
        assert endpoint == "set-status"
        calls.append(str(params.get("status")))
        if params.get("status") == "reject":
            return 200, {"success": False, "error_code": "cannot_reject"}
        return 200, {"request_id": 10, "success": True}

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.cancel("10")
    assert res["success"] is True
    assert calls == ["reject", "close"]


@pytest.mark.asyncio
async def test_get_balance_parses_float(monkeypatch):
    provider = SMSManProvider()

    async def fake_request(endpoint, **params):
        assert endpoint == "get-balance"
        return 200, {"balance": "799.70"}

    monkeypatch.setattr(provider, "_request", fake_request)
    bal = await provider.get_balance()
    assert bal == 799.70
