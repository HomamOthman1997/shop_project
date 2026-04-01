import pytest

from services.numbers.providers.herosms_provider import HeroSMSProvider


@pytest.mark.asyncio
async def test_resolve_service_code(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        assert action == "getServicesList"
        return 200, {
            "status": "success",
            "services": [
                {"code": "tg", "name": "Telegram"},
                {"code": "wa", "name": "WhatsApp"},
            ],
        }

    monkeypatch.setattr(provider, "_request", fake_request)
    code = await provider.resolve_service_code("Telegram")
    assert code == "tg"


@pytest.mark.asyncio
async def test_resolve_service_code_tokenized_name(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        assert action == "getServicesList"
        return 200, {
            "status": "success",
            "services": [
                {"code": "go", "name": "Google,youtube,Gmail"},
                {"code": "mb", "name": "Yahoo Mail"},
            ],
        }

    monkeypatch.setattr(provider, "_request", fake_request)
    code = await provider.resolve_service_code("gmail")
    assert code == "go"


@pytest.mark.asyncio
async def test_resolve_service_code_does_not_fuzzy_match_different_service(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        assert action == "getServicesList"
        return 200, {
            "status": "success",
            "services": [
                {"code": "wr", "name": "Walmart"},
                {"code": "tg", "name": "Telegram"},
            ],
        }

    monkeypatch.setattr(provider, "_request", fake_request)
    code = await provider.resolve_service_code("walmartmoneycard")
    assert code is None


@pytest.mark.asyncio
async def test_buy_number_parses_access_number(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        if action == "getCountries":
            return 200, [
                {"id": 1, "eng": "Ukraine"},
                {"id": 187, "eng": "USA", "visible": 1},
            ]
        if action == "getNumberV2":
            assert str(params.get("country")) == "187"
            return 200, "ACCESS_NUMBER:123456:7999999999"
        return 200, {}

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.buy_number("tg", country="1")
    assert res["success"] is True
    assert res["order_id"] == "123456"
    assert res["number"] == "7999999999"


@pytest.mark.asyncio
async def test_get_balance_parses_access_balance(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        assert action == "getBalance"
        return 200, "ACCESS_BALANCE:12.5"

    monkeypatch.setattr(provider, "_request", fake_request)
    bal = await provider.get_balance()
    assert bal == 12.5


@pytest.mark.asyncio
async def test_rental_prices_parse(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        if action == "getCountries":
            return 200, [
                {"id": 1, "eng": "Ukraine"},
                {"id": 187, "eng": "USA", "visible": 1},
            ]
        assert action == "serviceCountRent"
        assert str(params.get("country")) == "187"
        return 200, {
            "187": {
                "2": {"price": 0.18, "count": 100},
                "12": {"price": 0.45, "count": 50},
            }
        }

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.get_rental_prices("tg", country="1")
    assert res["success"] is True
    assert len(res["options"]) == 2
    assert res["options"][0]["duration"] == 2


@pytest.mark.asyncio
async def test_get_price_maps_common_country_code(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        if action == "getCountries":
            return 200, [
                {"id": 1, "eng": "Ukraine"},
                {"id": 187, "eng": "USA", "visible": 1},
            ]
        if action == "getPrices":
            assert str(params.get("country")) == "187"
            return 200, {"187": {"go": {"cost": 0.6, "count": 12}}}
        return 200, {}

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.get_price("go", country="1")
    assert res["success"] is True
    assert res["price"] == 0.6


@pytest.mark.asyncio
async def test_rental_sms_parse(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        assert action == "getAllSms"
        return 200, {
            "data": [
                {"code": "1234", "text": "code 1234"},
                {"text": "hello"},
            ]
        }

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.get_rental_sms("abc")
    assert res["success"] is True
    assert res["messages"] == ["1234", "hello"]
