import json
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.providers.alisms_provider import AliSMSProvider


class DummyResponse:
    def __init__(self, status=200, json_data=None, text=""):
        self.status = status
        self._json_data = json_data
        self._text = text

    async def text(self):
        if self._text:
            return self._text
        if self._json_data is not None:
            return json.dumps(self._json_data)
        return ""

    async def json(self, content_type=None):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummySession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        key = (url, tuple(sorted((params or {}).items())))
        response = self.routes[key]
        return response


@pytest.fixture(autouse=True)
def _alisms_settings(monkeypatch):
    monkeypatch.setattr(settings, "alisms_key", "test-key")
    monkeypatch.setattr(settings, "alisms_base_url", "https://api.alisms.org/stubs/handler_api.php")


@pytest.fixture
def countries_payload():
    return {
        "187": {"id": 187, "code": "us", "eng": "USA"},
        "16": {"id": 16, "code": "ke", "eng": "Kenya"},
    }


@pytest.fixture
def services_payload():
    return {
        "status": "success",
        "services": [
            {"code": "go", "name": "Google"},
            {"code": "tg", "name": "Telegram"},
            {"code": "payp", "name": "PayPal"},
        ],
    }


@pytest.mark.asyncio
async def test_alisms_get_price_uses_country_and_service(monkeypatch, countries_payload, services_payload):
    routes = {
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getServicesList"), ("api_key", "test-key")),
        ): DummyResponse(status=200, json_data=services_payload),
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getCountries"), ("api_key", "test-key")),
        ): DummyResponse(status=200, json_data=countries_payload),
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getPrices"), ("api_key", "test-key"), ("country", "187"), ("service", "go")),
        ): DummyResponse(status=200, json_data={"go": {"187": {"221": 0.124, "223": 0.1}}}),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = AliSMSProvider()

    result = await provider.get_price("google", country="1")
    assert result["success"] is True
    assert result["price"] == 0.1
    assert result["api_service_name"] == "go"


@pytest.mark.asyncio
async def test_alisms_get_price_falls_back_to_country_available_candidate(monkeypatch, countries_payload):
    routes = {
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getServicesList"), ("api_key", "test-key")),
        ): DummyResponse(
            status=200,
            json_data={
                "status": "success",
                "services": [
                    {"code": "hzo", "name": "gmail"},
                    {"code": "go", "name": "Google"},
                    {"code": "jewa", "name": "GOOGLE_GMAIL"},
                ],
            },
        ),
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getCountries"), ("api_key", "test-key")),
        ): DummyResponse(status=200, json_data=countries_payload),
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getPrices"), ("api_key", "test-key"), ("country", "187")),
        ): DummyResponse(
            status=200,
            json_data={
                "go": {"187": {"223": 0.1}},
                "jewa": {"187": {"75": 0.17}},
            },
        ),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = AliSMSProvider()

    result = await provider.get_price("gmail", country="1")
    assert result["success"] is True
    assert result["price"] == 0.1
    assert result["api_service_name"] == "go"


@pytest.mark.asyncio
async def test_alisms_get_price_any_country_selects_best_country(monkeypatch, services_payload):
    routes = {
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getServicesList"), ("api_key", "test-key")),
        ): DummyResponse(status=200, json_data=services_payload),
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getPrices"), ("api_key", "test-key")),
        ): DummyResponse(
            status=200,
            json_data={
                "tg": {
                    "187": {"221": 0.50},
                    "16": {"221": 0.20},
                }
            },
        ),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = AliSMSProvider()

    result = await provider.get_price("telegram", country=None)
    assert result["success"] is True
    assert result["price"] == 0.2
    assert result["api_service_name"] == "tg"
    assert result["provider_country"] == "16"


@pytest.mark.asyncio
async def test_alisms_buy_number_parses_access_number(monkeypatch, countries_payload, services_payload):
    routes = {
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getServicesList"), ("api_key", "test-key")),
        ): DummyResponse(status=200, json_data=services_payload),
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getCountries"), ("api_key", "test-key")),
        ): DummyResponse(status=200, json_data=countries_payload),
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getNumberV2"), ("api_key", "test-key"), ("country", "187"), ("service", "tg")),
        ): DummyResponse(status=200, text="ACCESS_NUMBER:12345:15551234567"),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = AliSMSProvider()

    result = await provider.buy_number("telegram", country="1")
    assert result["success"] is True
    assert result["order_id"] == "12345"
    assert result["number"] == "15551234567"


@pytest.mark.asyncio
async def test_alisms_get_sms_and_cancel(monkeypatch):
    routes = {
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getStatus"), ("api_key", "test-key"), ("id", "12345")),
        ): DummyResponse(status=200, text="STATUS_OK:987654"),
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "setStatus"), ("api_key", "test-key"), ("id", "12345"), ("status", 8)),
        ): DummyResponse(status=200, text="ACCESS_CANCEL"),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = AliSMSProvider()

    sms = await provider.get_sms("12345")
    cancel = await provider.cancel("12345")
    assert sms["success"] is True
    assert sms["messages"] == ["987654"]
    assert cancel["success"] is True


@pytest.mark.asyncio
async def test_alisms_get_balance(monkeypatch):
    routes = {
        (
            "https://api.alisms.org/stubs/handler_api.php",
            (("action", "getBalance"), ("api_key", "test-key")),
        ): DummyResponse(status=200, text="ACCESS_BALANCE:12.500"),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = AliSMSProvider()

    balance = await provider.get_balance()
    assert balance == 12.5
