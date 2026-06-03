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
async def test_buy_number_prefers_explicit_provider_country(monkeypatch):
    provider = HeroSMSProvider()
    calls = []

    async def fake_request(action, **params):
        calls.append((action, params))
        if action == "getNumberV2":
            assert str(params.get("country")) == "129"
            return 200, "ACCESS_NUMBER:123456:306999999999"
        raise AssertionError(f"unexpected request {action}")

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.buy_number("wa", country="129", provider_country="129")
    assert res["success"] is True
    assert calls == [("getNumberV2", {"service": "wa", "country": "129"})]


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
async def test_rent_number_can_use_provider_country_id(monkeypatch):
    provider = HeroSMSProvider()
    calls = []

    async def fake_request(action, **params):
        calls.append((action, params))
        if action == "getRentNumber":
            return 200, {"id": "rent-1", "phoneNumber": "+123", "cost": 0.5}
        raise AssertionError(f"unexpected request {action}")

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.rent_number("go", country="none", duration=24, provider_country="6")
    assert res["success"] is True
    assert calls == [("getRentNumber", {"service": "go", "country": "6", "duration": 24, "currency": 840})]


@pytest.mark.asyncio
async def test_rental_prices_parse(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        if action == "getCountries":
            return 200, [
                {"id": 1, "eng": "Ukraine"},
                {"id": 187, "eng": "USA", "visible": 1},
            ]
        if action == "getRentServicesAndCountries":
            return 404, {"title": "BAD_ACTION", "details": "Method Not Found"}
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
    assert res["options"][0]["provider_country_iso"] == "US"
    assert res["options"][0]["provider_country_name"] == "United States"


@pytest.mark.asyncio
async def test_rental_prices_include_duration_probe_options(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        if action == "getCountries":
            return 200, [
                {"id": 187, "eng": "USA", "visible": 1},
            ]
        if action == "serviceCountRent":
            assert str(params.get("country")) == "187"
            return 200, {"187": {"24": {"price": 0.96, "count": 1}}}
        if action == "getRentServicesAndCountries" and "duration" not in params:
            return 400, {
                "title": "BAD_DURATION",
                "details": "Invalid rental period.",
                "info": {"available_durations": [12, 24]},
            }
        if action == "getRentServicesAndCountries" and int(params.get("duration")) == 12:
            return 200, {"services": {"go": {"price": 0.55, "quantity": 4}}}
        raise AssertionError(f"unexpected request {action} {params}")

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.get_rental_prices("go", country="1")
    assert res["success"] is True
    assert [row["duration"] for row in res["options"]] == [12, 24]
    assert [row["duration_label"] for row in res["options"]] == ["12h", "1d"]


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
    assert res["provider_country"] == "187"
    assert res["provider_country_iso"] == "US"


@pytest.mark.asyncio
async def test_get_price_uses_requested_country_service_price_only(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        if action == "getCountries":
            return 200, [
                {"id": 108, "eng": "Iceland", "visible": 1},
                {"id": 129, "eng": "Greece", "visible": 1},
            ]
        if action == "getPrices":
            assert str(params.get("country")) == "108"
            return 200, {
                "108": {"tg": {"cost": 0.34, "count": 5}},
                "129": {"tg": {"cost": 0.25, "count": 5}},
            }
        return 200, {}

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.get_price("tg", country="Iceland")
    assert res["success"] is True
    assert res["price"] == 0.34
    assert res["provider_country"] == "108"
    assert res["provider_country_iso"] == "IS"


@pytest.mark.asyncio
async def test_buy_number_rejects_unresolved_non_numeric_country(monkeypatch):
    provider = HeroSMSProvider()

    async def fake_request(action, **params):
        if action == "getCountries":
            return 200, []
        if action == "getPrices":
            return 200, {}
        raise AssertionError("buy should not send a non-numeric HeroSMS country")

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.buy_number("go", country="Unknown Country")
    assert res["success"] is False
    assert res["raw"]["title"] == "BAD_COUNTRY"


@pytest.mark.asyncio
async def test_buy_number_preserves_country_no_numbers(monkeypatch):
    provider = HeroSMSProvider()
    calls: list[tuple[str, dict]] = []

    async def fake_request(action, **params):
        calls.append((action, params))
        if action == "getCountries":
            return 200, [
                {"id": 187, "eng": "USA", "visible": 1},
            ]
        if action in {"getNumberV2", "getNumber"}:
            assert str(params.get("country")) == "187"
            return 200, "NO_NUMBERS"
        return 200, {}

    monkeypatch.setattr(provider, "_request", fake_request)
    res = await provider.buy_number("gp", country="US")
    assert res["success"] is False
    assert res["raw"] == "NO_NUMBERS"
    assert not any(action == "getNumberV2" and "country" not in params for action, params in calls)


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
