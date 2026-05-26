import pytest

from services.numbers.order_service import NumbersOrderError
from services.numbers.order_voice_service import voice_call_recording_state


@pytest.mark.asyncio
async def test_voice_call_recording_state_fetches_calls_and_extracts_recording():
    calls = {}

    async def fake_fetch(provider, provider_order_id, to_number):
        calls["args"] = (provider, provider_order_id, to_number)
        return {
            "calls": [
                {
                    "id": "call-1",
                    "recording": {"downloadUrl": "https://example.test/call.mp3"},
                }
            ]
        }

    result = await voice_call_recording_state(
        {
            "number_mode": "voice",
            "provider": "textverified",
            "provider_order_id": "reservation-1",
            "provider_number": "15551234567",
        },
        fetch_calls=fake_fetch,
    )

    assert calls["args"] == ("textverified", "reservation-1", "15551234567")
    assert result["recording_uri"] == "https://example.test/call.mp3"
    assert result["calls"][0]["id"] == "call-1"


@pytest.mark.asyncio
async def test_voice_call_recording_state_rejects_non_voice_orders():
    async def fake_fetch(provider, provider_order_id, to_number):
        raise AssertionError("fetch should not run")

    with pytest.raises(NumbersOrderError) as exc:
        await voice_call_recording_state({"number_mode": "temp"}, fetch_calls=fake_fetch)

    assert exc.value.code == "invalid_mode"
