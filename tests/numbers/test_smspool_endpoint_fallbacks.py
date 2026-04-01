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


@pytest.mark.asyncio
async def test_get_price_matches_country_code_and_iso(monkeypatch):
    monkeypatch.setattr(settings, "smspool_key", "key")

    pricing_rows = [
        {
            "service": 1371,
            "service_name": "ClaudeAI / Anthropic",
            "country": 1,
            "country_name": "United States",
            "short_name": "US",
            "pool": 7,
            "price": "0.36",
        },
        {
            "service": 1371,
            "service_name": "ClaudeAI / Anthropic",
            "country": 22,
            "country_name": "United States (Virtual)",
            "short_name": "US_V",
            "pool": 7,
            "price": "0.60",
        },
    ]

    class DummySession:
        def post(self, url, data=None):
            assert url.endswith("/request/pricing")
            return _DummyResp(200, pricing_rows)

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = SMSPoolProvider()

    by_code = await provider.get_price("1371", country="1")
    by_iso = await provider.get_price("1371", country="US")

    assert by_code["success"] is True
    assert by_iso["success"] is True
    assert by_code["price"] == 0.36
    assert by_iso["price"] == 0.36


@pytest.mark.asyncio
async def test_get_price_numeric_country_code_does_not_match_by_substring(monkeypatch):
    monkeypatch.setattr(settings, "smspool_key", "key")

    pricing_rows = [
        {
            "service": 395,
            "service_name": "Google/Gmail",
            "country": 154,
            "country_name": "Azerbaijan",
            "short_name": "AZ",
            "pool": 12,
            "price": "0.07",
        },
        {
            "service": 395,
            "service_name": "Google/Gmail",
            "country": 11,
            "country_name": "Vietnam",
            "short_name": "VN",
            "pool": 7,
            "price": "0.08",
        },
        {
            "service": 395,
            "service_name": "Google/Gmail",
            "country": 1,
            "country_name": "United States",
            "short_name": "US",
            "pool": 7,
            "price": "0.72",
        },
    ]

    class DummySession:
        def post(self, url, data=None):
            assert url.endswith("/request/pricing")
            return _DummyResp(200, pricing_rows)

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = SMSPoolProvider()

    by_code = await provider.get_price("395", country="1")

    assert by_code["success"] is True
    assert by_code["price"] == 0.72
