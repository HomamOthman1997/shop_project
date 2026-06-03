import pytest

from config import settings
from services.numbers.providers.nonvoip_provider import NonVoipProvider


@pytest.mark.asyncio
async def test_resolve_service_code_by_name(monkeypatch):
    provider = NonVoipProvider()

    async def fake_services(force_refresh=False):
        return [
            {"id": 1, "name": "Telegram", "code": "tg"},
            {"id": 2, "name": "WhatsApp", "code": "wa"},
        ]

    monkeypatch.setattr(provider, "list_services", fake_services)
    code = await provider.resolve_service_code("telegram")
    assert code == "1"


@pytest.mark.asyncio
async def test_resolve_service_code_does_not_fuzzy_match_unknown(monkeypatch):
    provider = NonVoipProvider()

    async def fake_services(force_refresh=False):
        return [
            {"id": 1, "name": "Telegram", "code": "tg"},
            {"id": 2, "name": "WhatsApp", "code": "wa"},
        ]

    monkeypatch.setattr(provider, "list_services", fake_services)
    code = await provider.resolve_service_code("gmail")
    assert code is None


@pytest.mark.asyncio
async def test_get_price_parses_nested_payload(monkeypatch):
    provider = NonVoipProvider()
    monkeypatch.setattr(settings, "nonvoip_price_currency", "USD")

    async def fake_services(force_refresh=False):
        return [
            {"id": "1", "name": "Apple 4", "price": 0.6, "provider_country_iso": "US", "raw": {"service_id": 1}},
            {"id": "2", "name": "Apple 4 UK", "price": 1.1, "provider_country_iso": "GB", "raw": {"service_id": 2}},
        ]

    monkeypatch.setattr(provider, "list_services", fake_services)
    res = await provider.get_price("1", country="1")
    assert res["success"] is True
    assert res["price"] == 0.6
    assert res["provider_country_iso"] == "US"


@pytest.mark.asyncio
async def test_get_price_filters_numeric_service_by_country(monkeypatch):
    provider = NonVoipProvider()

    async def fake_services(force_refresh=False):
        return [
            {"id": "1425", "name": "Five Surveys 4 UK", "price": 0.15, "provider_country_iso": "GB"},
            {"id": "1465", "name": "Five Surveys 4 Germany", "price": 0.15, "provider_country_iso": "DE"},
        ]

    monkeypatch.setattr(provider, "list_services", fake_services)
    assert (await provider.get_price("1425", country="US"))["success"] is False
    gb = await provider.get_price("1425", country="GB")
    assert gb["success"] is True
    assert gb["provider_country_iso"] == "GB"


@pytest.mark.asyncio
async def test_buy_number_success(monkeypatch):
    provider = NonVoipProvider()

    async def fake_services(force_refresh=False):
        return [{"id": "1", "name": "Apple 4", "price": 0.6, "provider_country_iso": "US"}]

    async def fake_request(endpoint, **params):
        assert endpoint == "order_number"
        assert str(params.get("service_id")) == "1"
        return 200, {"order_id": 99, "number": "79002415539"}

    monkeypatch.setattr(provider, "list_services", fake_services)
    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.buy_number("1", country="1")
    assert res["success"] is True
    assert res["order_id"] == "99"
    assert res["number"] == "79002415539"


@pytest.mark.asyncio
async def test_buy_number_blocks_country_mismatch(monkeypatch):
    provider = NonVoipProvider()

    async def fake_services(force_refresh=False):
        return [{"id": "1425", "name": "Five Surveys 4 UK", "price": 0.15, "provider_country_iso": "GB"}]

    async def fake_request(endpoint, **params):
        raise AssertionError("order_number should not be called for mismatched country")

    monkeypatch.setattr(provider, "list_services", fake_services)
    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.buy_number("1425", country="US")
    assert res["success"] is False
    assert isinstance(res.get("raw"), dict)
    assert res["raw"].get("error_code") == "COUNTRY_MISMATCH"


@pytest.mark.asyncio
async def test_get_sms_wait_and_code(monkeypatch):
    provider = NonVoipProvider()

    calls = {"n": 0}

    async def fake_request(endpoint, **params):
        assert endpoint == "get_messages"
        calls["n"] += 1
        if calls["n"] == 1:
            return 200, {"order_id": 1, "text": "", "code": "", "received_at": None}
        return 200, {"order_id": 1, "text": "Your code is 1243", "code": "1243"}

    monkeypatch.setattr(provider, "_request", fake_request)

    first = await provider.get_sms("1")
    assert first["success"] is False
    assert first["messages"] == []

    second = await provider.get_sms("1")
    assert second["success"] is True
    assert second["messages"] == ["1243"]


@pytest.mark.asyncio
async def test_cancel_uses_documented_refund_number(monkeypatch):
    provider = NonVoipProvider()

    async def fake_request(endpoint, **params):
        assert endpoint == "refund_number"
        assert str(params.get("id")) == "10"
        return 200, {"code": "200", "message": "success"}

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.cancel("10")
    assert res["success"] is True


@pytest.mark.asyncio
async def test_resend_uses_documented_reuse_number(monkeypatch):
    provider = NonVoipProvider()

    async def fake_request(endpoint, **params):
        assert endpoint == "reuse_number"
        assert str(params.get("order_id")) == "10"
        return 200, {"order_id": 11, "number": "15551234567"}

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.resend("10")
    assert res["success"] is True
    assert res["order_id"] == "11"
    assert res["number"] == "15551234567"


@pytest.mark.asyncio
async def test_get_balance_is_unsupported_by_supplied_docs(monkeypatch):
    provider = NonVoipProvider()

    async def fake_request(endpoint, **params):
        raise AssertionError("non-VoIP docs do not include a balance endpoint")

    monkeypatch.setattr(provider, "_request", fake_request)
    bal = await provider.get_balance()
    assert bal is None
