import pytest

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.providers.smspool_provider import SMSPoolProvider


class _DummyResp:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return str(self._payload)

    async def json(self, content_type=None):
        return self._payload


@pytest.mark.asyncio
async def test_get_sms_falls_back_to_legacy_request_check(monkeypatch):
    monkeypatch.setattr(settings, "smspool_key", "key")
    called = []

    class DummySession:
        def post(self, url, data=None):
            called.append(url)
            if url.endswith("/sms/check"):
                return _DummyResp(404, {"error": "not found"})
            if url.endswith("/request/check"):
                return _DummyResp(200, {"sms": ["1234"]})
            raise AssertionError(url)

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = SMSPoolProvider()
    result = await provider.get_sms("100")
    assert result["success"] is True
    assert result["messages"] == ["1234"]
    assert called == [
        "https://api.smspool.net/sms/check",
        "https://api.smspool.net/request/check",
    ]


@pytest.mark.asyncio
async def test_cancel_prefers_new_sms_cancel(monkeypatch):
    monkeypatch.setattr(settings, "smspool_key", "key")
    called = []

    class DummySession:
        def post(self, url, data=None):
            called.append(url)
            if url.endswith("/sms/cancel"):
                return _DummyResp(200, {"success": 1})
            raise AssertionError(url)

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = SMSPoolProvider()
    result = await provider.cancel("100")
    assert result["success"] is True
    assert called == ["https://api.smspool.net/sms/cancel"]

