import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.numbers.providers.textverified_provider import TextVerifiedProvider
from services.numbers.data import tv_area_codes


class _DummyResp:
    def __init__(self, status, json_data=None, headers=None):
        self.status = status
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return str(self._json)

    async def json(self):
        return self._json


@pytest.fixture(autouse=True)
def _reset_textverified_caches():
    TextVerifiedProvider._services_cache_by_capability = {}
    TextVerifiedProvider._auth_lock = None
    TextVerifiedProvider._token_cache = {"token": None, "expires_at": 0.0, "fingerprint": None}
    TextVerifiedProvider._price_cache = {}


@pytest.mark.asyncio
async def test_buy_number_google_fallbacks_to_gmail(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)

    class DummySession:
        def __init__(self):
            self.calls = []

        def post(self, url, headers=None, json=None):
            self.calls.append(("post", url, dict(json or {})))
            service = str((json or {}).get("serviceName") or "")
            if url.endswith("/pub/v2/verifications") and service == "google":
                return _DummyResp(400, {"errorCode": "Unavailable", "errorDescription": "Out of stock or unavailable."})
            if url.endswith("/pub/v2/verifications") and service == "gmail":
                return _DummyResp(201, {"href": "https://www.textverified.com/api/pub/v2/verifications/v_1", "method": "GET"})
            return _DummyResp(400, {"errorCode": "Unavailable"})

        def request(self, method, href, headers=None):
            self.calls.append(("request", href, {}))
            return _DummyResp(200, {"id": "v_1", "number": "+15551234567"})

    sess = DummySession()

    async def fake_get_session():
        return sess

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    TextVerifiedProvider._services_cache_by_capability = {"sms": {"google", "gmail"}}

    res = await provider.buy_number("google", reuse_mode=True)
    assert res["success"] is True
    assert res["order_id"] == "v_1"
    assert res["api_service_name"] == "gmail"
    assert res["requested_reuse_mode"] is True

    create_calls = [c for c in sess.calls if c[0] == "post" and c[1].endswith("/pub/v2/verifications")]
    assert create_calls[0][2]["serviceName"] == "google"
    assert create_calls[1][2]["serviceName"] == "gmail"


@pytest.mark.asyncio
async def test_buy_voice_number_uses_voice_capability(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)

    class DummySession:
        def __init__(self):
            self.calls = []

        def post(self, url, headers=None, json=None):
            payload = dict(json or {})
            self.calls.append(("post", url, payload))
            if url.endswith("/pub/v2/verifications"):
                return _DummyResp(201, {"href": "https://www.textverified.com/api/pub/v2/verifications/v_voice", "method": "GET"})
            return _DummyResp(400, {"errorCode": "Unavailable"})

        def request(self, method, href, headers=None):
            self.calls.append(("request", href, {}))
            return _DummyResp(200, {"id": "v_voice", "number": "+15551234567"})

    sess = DummySession()

    async def fake_get_session():
        return sess

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    TextVerifiedProvider._services_cache_by_capability = {"voice": {"gmail"}}

    res = await provider.buy_number("gmail", capability="voice")

    assert res["success"] is True
    create_call = next(c for c in sess.calls if c[0] == "post")
    assert create_call[2]["capability"] == "voice"


@pytest.mark.asyncio
async def test_get_calls_returns_recording_uri(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)

    class DummySession:
        def get(self, url, headers=None, params=None):
            assert url.endswith("/pub/v2/calls")
            assert params["reservationId"] == "v_voice"
            return _DummyResp(
                200,
                {
                    "data": [
                        {
                            "id": "call_1",
                            "to": "+15551234567",
                            "recordingUri": "https://recording.example/call_1.mp3",
                        }
                    ]
                },
            )

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)

    res = await provider.get_calls("v_voice", to_number="+15551234567")

    assert res["success"] is True
    assert res["calls"][0]["recordingUri"] == "https://recording.example/call_1.mp3"


@pytest.mark.asyncio
async def test_download_recording_accepts_relative_textverified_uri(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)

    class RecordingResp:
        status = 200
        headers = {"Content-Type": "audio/mpeg"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return ""

        async def read(self):
            return b"mp3-bytes"

    class DummySession:
        def __init__(self):
            self.calls = []

        def get(self, url, headers=None):
            self.calls.append((url, dict(headers or {})))
            return RecordingResp()

    sess = DummySession()

    async def fake_get_session():
        return sess

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)

    res = await provider.download_recording("/api/pub/v2/calls/call_1/recording")

    assert res["success"] is True
    assert res["content"] == b"mp3-bytes"
    assert res["content_type"] == "audio/mpeg"
    assert sess.calls[0][0] == "https://www.textverified.com/api/pub/v2/calls/call_1/recording"


@pytest.mark.asyncio
async def test_buy_number_fallback_from_area_code_to_any(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)

    class DummySession:
        def __init__(self):
            self.calls = []

        def post(self, url, headers=None, json=None):
            payload = dict(json or {})
            self.calls.append(("post", url, payload))
            has_area = bool(payload.get("areaCodeSelectOption"))
            if url.endswith("/pub/v2/verifications") and has_area:
                return _DummyResp(400, {"errorCode": "Unavailable", "errorDescription": "Out of stock or unavailable."})
            if url.endswith("/pub/v2/verifications"):
                return _DummyResp(201, {"href": "https://www.textverified.com/api/pub/v2/verifications/v_2", "method": "GET"})
            return _DummyResp(400, {"errorCode": "Unavailable"})

        def request(self, method, href, headers=None):
            self.calls.append(("request", href, {}))
            return _DummyResp(200, {"id": "v_2", "number": "+15550000000"})

    sess = DummySession()

    async def fake_get_session():
        return sess

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    monkeypatch.setattr(tv_area_codes, "DATA", {"NY": ["212"]}, raising=False)
    TextVerifiedProvider._services_cache_by_capability = {"sms": {"gmail"}}

    res = await provider.buy_number("gmail", state="NY")
    assert res["success"] is True
    assert res["order_id"] == "v_2"

    create_calls = [c for c in sess.calls if c[0] == "post" and c[1].endswith("/pub/v2/verifications")]
    assert len(create_calls) >= 2
    assert "areaCodeSelectOption" in create_calls[0][2]
    assert "areaCodeSelectOption" not in create_calls[1][2]


@pytest.mark.asyncio
async def test_buy_number_reuse_tries_state_area_codes_then_unavailable(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)
    monkeypatch.setattr(tv_area_codes, "DATA", {"NY": ["212", "315", "718"]}, raising=False)
    TextVerifiedProvider._services_cache_by_capability = {"sms": {"gmail"}}

    class DummySession:
        def __init__(self):
            self.calls = []

        def post(self, url, headers=None, json=None):
            payload = dict(json or {})
            self.calls.append(("post", url, payload))
            if url.endswith("/pub/v2/verifications"):
                return _DummyResp(400, {"errorCode": "Unavailable", "errorDescription": "Out of stock or unavailable."})
            return _DummyResp(400, {"errorCode": "Unavailable"})

        def request(self, method, href, headers=None):
            self.calls.append(("request", href, {}))
            return _DummyResp(400, {"errorCode": "Unavailable"})

    sess = DummySession()

    async def fake_get_session():
        return sess

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)

    res = await provider.buy_number("gmail", state="NY", reuse_mode=True)
    assert res["success"] is False
    raw = res.get("raw") or {}
    assert raw.get("errorCode") == "UNAVAILABLE_IN_STATE"
    assert raw.get("stateCode") == "NY"
    assert raw.get("attemptedAreaCodes") == ["212", "315", "718"]

    create_calls = [c for c in sess.calls if c[0] == "post" and c[1].endswith("/pub/v2/verifications")]
    assert len(create_calls) == 3
    assert create_calls[0][2].get("areaCodeSelectOption") == ["212"]
    assert create_calls[1][2].get("areaCodeSelectOption") == ["315"]
    assert create_calls[2][2].get("areaCodeSelectOption") == ["718"]


@pytest.mark.asyncio
async def test_auth_reuses_cached_token(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    monkeypatch.setattr("config.settings.tv_user", "user", raising=False)
    monkeypatch.setattr("config.settings.tv_key", "key", raising=False)

    class DummySession:
        def __init__(self):
            self.calls = 0

        def post(self, url, headers=None, json=None):
            self.calls += 1
            return _DummyResp(200, {"token": "cached-token", "expiresIn": 120})

    sess = DummySession()

    async def fake_get_session():
        return sess

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)

    provider = TextVerifiedProvider()
    first = await provider._auth()
    second = await provider._auth()
    assert first == "cached-token"
    assert second == "cached-token"
    assert sess.calls == 1


@pytest.mark.asyncio
async def test_get_price_retries_rate_limit_then_succeeds(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    async def fake_sleep(_cls, _seconds):
        return None

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)
    monkeypatch.setattr(TextVerifiedProvider, "_sleep", classmethod(fake_sleep))
    TextVerifiedProvider._services_cache_by_capability = {"sms": {"netspend"}}

    class DummySession:
        def __init__(self):
            self.calls = 0

        def post(self, url, headers=None, json=None):
            self.calls += 1
            if self.calls == 1:
                return _DummyResp(429, {"errorCode": "TooManyRequests", "message": "Too many requests"}, {"Retry-After": "0"})
            return _DummyResp(200, {"price": 0.75, "serviceName": "netspend"})

    sess = DummySession()

    async def fake_get_session():
        return sess

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    res = await provider.get_price("netspend", country="US")
    assert res["success"] is True
    assert res["price"] == 0.75
    assert sess.calls == 2


@pytest.mark.asyncio
async def test_get_price_uses_short_cache(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)
    TextVerifiedProvider._services_cache_by_capability = {"sms": {"netspend"}}

    class DummySession:
        def __init__(self):
            self.calls = 0

        def post(self, url, headers=None, json=None):
            self.calls += 1
            return _DummyResp(200, {"price": 0.33, "serviceName": "netspend"})

    sess = DummySession()

    async def fake_get_session():
        return sess

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)

    first = await provider.get_price("netspend", country="US", state="NY")
    second = await provider.get_price("netspend", country="US", state="NY")
    assert first["success"] is True
    assert second["success"] is True
    assert sess.calls == 1


@pytest.mark.asyncio
async def test_cancel_accepts_accepted_status(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)

    class DummySession:
        def post(self, url, headers=None):
            return _DummyResp(202, {"message": "Cancellation accepted"})

    sess = DummySession()

    async def fake_get_session():
        return sess

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)

    res = await provider.cancel("v_123")
    assert res["success"] is True


@pytest.mark.asyncio
async def test_cancel_accepts_canceled_message(monkeypatch):
    from services.numbers.core.session_manager import SessionManager

    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)

    class DummySession:
        def post(self, url, headers=None):
            return _DummyResp(400, {"message": "Already canceled"})

    sess = DummySession()

    async def fake_get_session():
        return sess

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)

    res = await provider.cancel("v_123")
    assert res["success"] is True
