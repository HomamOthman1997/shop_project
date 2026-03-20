import json

import pytest

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.providers.smspool_provider import SMSPoolProvider


class DummyResp:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload)

    async def json(self, content_type=None):
        if isinstance(self._payload, str):
            return json.loads(self._payload)
        return self._payload


@pytest.mark.asyncio
async def test_get_rental_prices_parses_retrieve_all(monkeypatch):
    monkeypatch.setattr(settings, "smspool_key", "key")

    payload = {
        "success": 1,
        "data": [
            {
                "ID": 11,
                "name": "United States",
                "tag": "United States [Provider 1]",
                "pool": 17,
                "pricing": {"1": 6, "7": 12},
            }
        ],
    }

    class DummySession:
        def get(self, url, params=None):
            assert url.endswith("/rental/retrieve_all")
            assert params.get("type") == 1
            return DummyResp(200, payload)

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = SMSPoolProvider()
    result = await provider.get_rental_prices("ignored", country="1")
    assert result["success"] is True
    assert result["options"][0]["rental_id"] == "11"
    assert result["options"][0]["duration"] == 24
    assert result["options"][0]["duration_days"] == 1


@pytest.mark.asyncio
async def test_rent_number_uses_purchase_rental(monkeypatch):
    monkeypatch.setattr(settings, "smspool_key", "key")
    captured = {}

    class DummySession:
        def post(self, url, data=None):
            assert url.endswith("/purchase/rental")
            captured["data"] = dict(data or {})
            return DummyResp(
                200,
                {
                    "success": 1,
                    "rental_code": "rent_001",
                    "number": "+15555550123",
                    "price": 6,
                },
            )

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = SMSPoolProvider()
    result = await provider.rent_number(
        "ignored",
        country="1",
        duration=24,
        rental_id="11",
        duration_days=1,
    )
    assert result["success"] is True
    assert result["order_id"] == "rent_001"
    assert captured["data"]["id"] == "11"
    assert int(captured["data"]["days"]) == 1


@pytest.mark.asyncio
async def test_get_rental_sms_parses_messages(monkeypatch):
    monkeypatch.setattr(settings, "smspool_key", "key")

    class DummySession:
        def get(self, url, params=None):
            assert url.endswith("/rental/retrieve_messages")
            return DummyResp(200, {"success": 1, "data": [{"message": "1234"}]})

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = SMSPoolProvider()
    result = await provider.get_rental_sms("rent_001")
    assert result["success"] is True
    assert result["messages"] == ["1234"]


@pytest.mark.asyncio
async def test_finish_rental_idempotent_already_message(monkeypatch):
    monkeypatch.setattr(settings, "smspool_key", "key")

    class DummySession:
        def post(self, url, data=None):
            # New endpoint first
            assert url.endswith("/rental/refund")
            return DummyResp(200, {"success": 0, "message": "Already refunded"})

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = SMSPoolProvider()
    result = await provider.finish_rental("rent_001")
    assert result["success"] is True
