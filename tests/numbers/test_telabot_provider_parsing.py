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

