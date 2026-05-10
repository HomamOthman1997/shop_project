import json
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.providers.vaksms_provider import VAKSMSProvider


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

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout, "headers": headers})
        key = (url, tuple(sorted((params or {}).items())))
        response = self.routes[key]
        return response


@pytest.fixture(autouse=True)
def _vaksms_settings(monkeypatch):
    monkeypatch.setattr(settings, "vaksms_key", "test-key")
    monkeypatch.setattr(settings, "vaksms_base_url", "https://vak-sms.com/api")
    monkeypatch.setattr(settings, "vaksms_docs_url", "https://vak-sms.com/api/vak/", raising=False)
    monkeypatch.setattr(settings, "vaksms_site_base_url", "https://vak-sms.com/backend", raising=False)


@pytest.fixture
def countries_payload():
    return [
        {"countryName": "United States", "countryCode": "us", "operatorList": ["any", "tmobile"]},
        {"countryName": "Kenya", "countryCode": "ke", "operatorList": ["any"]},
    ]


@pytest.fixture
def docs_html():
    return """
    <div id="serviceCodeList1">
      <tbody>
        <tr><td>Google</td><td>gl</td></tr>
        <tr><td>Telegram</td><td>tg</td></tr>
        <tr><td>WhatsApp</td><td>wa</td></tr>
      </tbody>
    </div>
    """


@pytest.mark.asyncio
async def test_vaksms_get_price_uses_country_and_service(monkeypatch, countries_payload, docs_html):
    routes = {
        ("https://vak-sms.com/api/vak/", ()): DummyResponse(status=200, text=docs_html),
        ("https://vak-sms.com/api/getCountryList/", ()): DummyResponse(status=200, json_data=countries_payload),
        (
            "https://vak-sms.com/api/getCountNumber/",
            (("apiKey", "test-key"), ("country", "us"), ("price", 1), ("service", "gl")),
        ): DummyResponse(status=200, json_data={"gl": 12, "price": 0.25}),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = VAKSMSProvider()

    result = await provider.get_price("google", country="1")
    assert result["success"] is True
    assert result["price"] == 0.25
    assert result["api_service_name"] == "gl"
    assert result["provider_country"] == "us"


@pytest.mark.asyncio
async def test_vaksms_get_price_uses_site_stock_price_when_api_count_is_zero(monkeypatch, countries_payload, docs_html):
    routes = {
        ("https://vak-sms.com/api/vak/", ()): DummyResponse(status=200, text=docs_html),
        ("https://vak-sms.com/api/getCountryList/", ()): DummyResponse(status=200, json_data=countries_payload),
        (
            "https://vak-sms.com/api/getCountNumber/",
            (("apiKey", "test-key"), ("country", "us"), ("price", 1), ("service", "wa")),
        ): DummyResponse(status=200, json_data={"wa": 0, "price": 0.88}),
        (
            "https://vak-sms.com/backend/country/stats",
            (("serviceId", "wa"),),
        ): DummyResponse(
            status=200,
            json_data=[
                {
                    "id": "us",
                    "name": "United States",
                    "count": 922,
                    "minPrice": 4.6,
                    "apiPrice": 0.88,
                    "available": [{"count": 922, "price": 4.6}],
                }
            ],
        ),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = VAKSMSProvider()

    result = await provider.get_price("whatsapp", country="1")
    assert result["success"] is True
    assert result["price"] == 4.6
    assert result["api_service_name"] == "wa"
    assert result["provider_country"] == "us"
    assert result["site_stock_pricing"] is True
    assert result["raw"]["api"] == {"wa": 0, "price": 0.88}
    assert result["raw"]["site"]["count"] == 922


@pytest.mark.asyncio
async def test_vaksms_get_price_picks_site_country_for_any_country(monkeypatch, countries_payload, docs_html):
    routes = {
        ("https://vak-sms.com/api/vak/", ()): DummyResponse(status=200, text=docs_html),
        ("https://vak-sms.com/backend/country/stats", (("serviceId", "wa"),)): DummyResponse(
            status=200,
            json_data=[
                {"id": "us", "name": "United States", "count": 922, "apiPrice": 0.88, "minPrice": 4.6},
                {"id": "id", "name": "Indonesia", "count": 28180, "apiPrice": 0.004, "minPrice": 0.004},
            ],
        ),
        (
            "https://vak-sms.com/api/getCountNumber/",
            (("apiKey", "test-key"), ("country", "us"), ("price", 1), ("service", "wa")),
        ): DummyResponse(status=200, json_data={"wa": 922, "price": 0.88}),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = VAKSMSProvider()

    result = await provider.get_price("whatsapp", country="none")
    assert result["success"] is True
    assert result["price"] == 0.88
    assert result["api_service_name"] == "wa"
    assert result["provider_country"] == "us"
    assert result["provider_country_iso"] == "US"
    assert "recommendation_blocked" not in result


@pytest.mark.asyncio
async def test_vaksms_buy_number_parses_json(monkeypatch, countries_payload, docs_html):
    routes = {
        ("https://vak-sms.com/api/vak/", ()): DummyResponse(status=200, text=docs_html),
        ("https://vak-sms.com/api/getCountryList/", ()): DummyResponse(status=200, json_data=countries_payload),
        (
            "https://vak-sms.com/api/getNumber/",
            (("apiKey", "test-key"), ("country", "us"), ("service", "tg")),
        ): DummyResponse(status=200, json_data={"tel": 15551234567, "idNum": "abc123"}),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = VAKSMSProvider()

    result = await provider.buy_number("telegram", country="1")
    assert result["success"] is True
    assert result["order_id"] == "abc123"
    assert result["number"] == "15551234567"


@pytest.mark.asyncio
async def test_vaksms_get_sms_cancel_and_resend(monkeypatch):
    routes = {
        (
            "https://vak-sms.com/api/getSmsCode/",
            (("apiKey", "test-key"), ("idNum", "abc123")),
        ): DummyResponse(status=200, json_data={"smsCode": "987654"}),
        (
            "https://vak-sms.com/api/setStatus/",
            (("apiKey", "test-key"), ("idNum", "abc123"), ("status", "end")),
        ): DummyResponse(status=200, json_data={"status": "update"}),
        (
            "https://vak-sms.com/api/setStatus/",
            (("apiKey", "test-key"), ("idNum", "abc123"), ("status", "send")),
        ): DummyResponse(status=200, json_data={"status": "ready"}),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = VAKSMSProvider()

    sms = await provider.get_sms("abc123")
    cancel = await provider.cancel("abc123")
    resend = await provider.resend("abc123")
    assert sms["success"] is True
    assert sms["messages"] == ["987654"]
    assert cancel["success"] is True
    assert resend is True


@pytest.mark.asyncio
async def test_vaksms_get_balance(monkeypatch):
    routes = {
        (
            "https://vak-sms.com/api/getBalance/",
            (("apiKey", "test-key"),),
        ): DummyResponse(status=200, json_data={"balance": 12.5}),
    }
    session = DummySession(routes)

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = VAKSMSProvider()

    balance = await provider.get_balance()
    assert balance == 12.5
