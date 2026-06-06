import pytest

from services.numbers.providers.telabot_provider import TelabotProvider


@pytest.mark.asyncio
async def test_buy_number_handles_string_error_message(monkeypatch):
    provider = TelabotProvider()

    async def fake_get(params):
        return {"status": "error", "message": "Invalid service name"}

    monkeypatch.setattr(provider, "_get", fake_get)
    res = await provider.buy_number("bad-service")
    assert res["success"] is False
    assert isinstance(res.get("raw"), dict)
    assert res["raw"].get("status") == "error"


@pytest.mark.asyncio
async def test_get_sms_does_not_treat_error_message_as_sms(monkeypatch):
    provider = TelabotProvider()

    async def fake_get(params):
        return {"status": "error", "message": "Invalid request"}

    monkeypatch.setattr(provider, "_get", fake_get)

    result = await provider.get_sms("bad-order")

    assert result["success"] is False
    assert result["messages"] == []


@pytest.mark.asyncio
async def test_get_sms_extracts_pin_from_message_rows(monkeypatch):
    provider = TelabotProvider()

    async def fake_get(params):
        return {"status": "ok", "message": [{"pin": "445566", "reply": "Your code is 445566"}]}

    monkeypatch.setattr(provider, "_get", fake_get)

    result = await provider.get_sms("order-1")

    assert result["success"] is True
    assert result["messages"] == ["445566"]
