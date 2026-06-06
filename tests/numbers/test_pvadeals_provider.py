import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from config import settings
from services.numbers.providers.pvadeals_provider import PVADealsProvider
from services.numbers.core.session_manager import SessionManager


class DummyResponse:
    def __init__(self, status=200, json_data=None, text=""):
        self.status = status
        self._json_data = json_data
        self._text = text
        self.headers = {}

    async def text(self):
        return self._text

    async def json(self, content_type=None):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummySession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json": json,
                "params": params,
            }
        )
        key = (str(method).upper(), url)
        response = self.routes[key]
        if callable(response):
            response = response(method=method, url=url, headers=headers, json=json, params=params, timeout=timeout)
        return response


@pytest.fixture(autouse=True)
def _pvadeals_settings(monkeypatch):
    monkeypatch.setattr(settings, "pvadeals_key", "test-key")
    monkeypatch.setattr(settings, "pvadeals_base_url", "https://prod-v3.pvadeals.com/v3/api")


@pytest.fixture
def sample_catalog():
    return {
        "success": True,
        "data": {
            "services": [
                {
                    "_id": "svc_us_tg",
                    "name": "Telegram",
                    "country": "USA",
                    "STRprice": 0.2,
                    "LTR3price": 1.5,
                    "LTR7price": 2.5,
                    "LTR14price": 4.0,
                    "LTR30price": 7.0,
                },
                {
                    "_id": "svc_ca_tg",
                    "name": "Telegram",
                    "country": "Canada",
                    "STRprice": 0.3,
                    "LTR3price": 1.9,
                    "LTR7price": 2.9,
                    "LTR14price": 4.9,
                    "LTR30price": 7.9,
                },
            ]
        },
    }


@pytest.mark.asyncio
async def test_pvadeals_get_price_uses_country_filtered_catalog(monkeypatch, sample_catalog):
    session = DummySession(
        {
            ("GET", "https://prod-v3.pvadeals.com/v3/api/services/all"): DummyResponse(status=200, json_data=sample_catalog),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.get_price("Telegram", country="1")
    assert result["success"] is True
    assert result["price"] == 0.2
    assert result["api_service_name"] == "Telegram"


@pytest.mark.asyncio
async def test_pvadeals_get_price_any_country_picks_cheapest_country(monkeypatch):
    catalog = {
        "success": True,
        "data": {
            "services": [
                {"_id": "svc_us_tg", "name": "Telegram", "country": "USA", "STRprice": 1.45},
                {"_id": "svc_co_tg", "name": "Telegram", "country": "Colombia", "STRprice": 0.85},
                {"_id": "svc_az_tg", "name": "Telegram", "country": "Azerbaijan", "STRprice": 0.55},
            ]
        },
    }
    session = DummySession(
        {
            ("GET", "https://prod-v3.pvadeals.com/v3/api/services/all"): DummyResponse(status=200, json_data=catalog),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.get_price("Telegram", country=None)
    assert result["success"] is True
    assert result["price"] == 0.55
    assert result["provider_country"] == "Azerbaijan"


@pytest.mark.asyncio
async def test_pvadeals_get_price_any_country_accepts_exact_id(monkeypatch):
    catalog = {
        "success": True,
        "data": {
            "services": [
                {"_id": "svc_us_tg", "name": "Telegram", "country": "USA", "STRprice": 1.45},
            ]
        },
    }
    session = DummySession(
        {
            ("GET", "https://prod-v3.pvadeals.com/v3/api/services/all"): DummyResponse(status=200, json_data=catalog),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.get_price("svc_us_tg", country=None)
    assert result["success"] is True
    assert result["price"] == 1.45
    assert result["provider_country"] == "USA"


@pytest.mark.asyncio
async def test_pvadeals_buy_number_posts_purchase_payload(monkeypatch, sample_catalog):
    purchase_payload = {
        "success": True,
        "data": {
            "_id": "req_1",
            "number": "+13130001234",
            "serviceId": "svc_us_tg",
            "serviceName": "Telegram",
        },
    }
    session = DummySession(
        {
            ("GET", "https://prod-v3.pvadeals.com/v3/api/services/all"): DummyResponse(status=200, json_data=sample_catalog),
            ("POST", "https://prod-v3.pvadeals.com/v3/api/purchase"): DummyResponse(status=200, json_data=purchase_payload),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.buy_number("Telegram", country="US")
    assert result["success"] is True
    assert result["order_id"] == "req_1"
    assert result["number"] == "+13130001234"
    assert session.calls[-1]["json"] == {"services": [{"serviceId": "svc_us_tg"}]}


@pytest.mark.asyncio
async def test_pvadeals_get_rental_prices_extracts_supported_durations(monkeypatch, sample_catalog):
    session = DummySession(
        {
            ("GET", "https://prod-v3.pvadeals.com/v3/api/services/all"): DummyResponse(status=200, json_data=sample_catalog),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.get_rental_prices("Telegram", country="US")
    assert result["success"] is True
    assert [row["duration_days"] for row in result["options"]] == [3, 7, 14, 30]
    assert result["options"][0]["price"] == 1.5


@pytest.mark.asyncio
async def test_pvadeals_rent_number_posts_duration_days(monkeypatch, sample_catalog):
    rental_payload = {
        "success": True,
        "data": {
            "_id": "ltr_1",
            "number": "+13130001234",
            "serviceId": "svc_us_tg",
            "serviceName": "Telegram",
            "amount": 2.5,
            "endTime": "2026-04-07T00:00:00.000Z",
        },
    }
    session = DummySession(
        {
            ("GET", "https://prod-v3.pvadeals.com/v3/api/services/all"): DummyResponse(status=200, json_data=sample_catalog),
            ("POST", "https://prod-v3.pvadeals.com/v3/api/purchase-ltr"): DummyResponse(status=200, json_data=rental_payload),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.rent_number("Telegram", country="US", duration=7)
    assert result["success"] is True
    assert result["order_id"] == "ltr_1"
    assert result["price"] == 2.5
    assert session.calls[-1]["json"] == {"serviceId": "svc_us_tg", "duration": 7}


@pytest.mark.asyncio
async def test_pvadeals_all_services_unlimited_is_28_days_only(monkeypatch):
    session = DummySession({})

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.get_rental_prices("ALL_SERVICES", country="US")
    assert result["success"] is True
    assert result["options"] == [
        {
            "country": "United States",
            "duration": 672,
            "duration_days": 28,
            "duration_label": "28d",
            "price": 12.99,
            "count": 1,
        }
    ]


@pytest.mark.asyncio
async def test_pvadeals_all_services_rent_number_posts_fixed_duration(monkeypatch):
    rental_payload = {
        "success": True,
        "data": {
            "_id": "ltr_all_1",
            "number": "+13130001234",
            "serviceId": "ALL_SERVICES",
            "serviceName": "All Services",
            "amount": 12.99,
            "endTime": "2026-04-07T00:00:00.000Z",
        },
    }
    session = DummySession(
        {
            ("POST", "https://prod-v3.pvadeals.com/v3/api/purchase-ltr"): DummyResponse(status=200, json_data=rental_payload),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.rent_number("ALL_SERVICES", country="US", duration=7)
    assert result["success"] is True
    assert session.calls[-1]["json"] == {"serviceId": "ALL_SERVICES", "duration": 28}


@pytest.mark.asyncio
async def test_pvadeals_get_sms_reads_request_details(monkeypatch):
    request_payload = {
        "success": True,
        "data": {
            "_id": "req_1",
            "status": "COMPLETED",
            "messages": [{"message": "Your code is 123456"}],
        },
    }
    session = DummySession(
        {
            ("GET", "https://prod-v3.pvadeals.com/v3/api/request/req_1"): DummyResponse(status=200, json_data=request_payload),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.get_sms("req_1")
    assert result["success"] is True
    assert result["messages"] == ["Your code is 123456"]


@pytest.mark.asyncio
async def test_pvadeals_get_sms_reads_codes_pin_payload(monkeypatch):
    request_payload = {
        "success": True,
        "data": {
            "_id": "req_1",
            "status": "COMPLETED",
            "codes": [
                {
                    "message": "Your Claude verification code is: 413873",
                    "pin": "413873",
                }
            ],
        },
    }
    session = DummySession(
        {
            ("GET", "https://prod-v3.pvadeals.com/v3/api/request/req_1"): DummyResponse(status=200, json_data=request_payload),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.get_sms("req_1")
    assert result["success"] is True
    assert "413873" in result["messages"]
    assert "Your Claude verification code is: 413873" in result["messages"]


@pytest.mark.asyncio
async def test_pvadeals_get_sms_marks_completed_request_without_sms_terminal(monkeypatch):
    request_payload = {
        "success": True,
        "data": {
            "_id": "req_1",
            "status": "COMPLETED",
            "messages": [],
            "codes": [],
        },
    }
    session = DummySession(
        {
            ("GET", "https://prod-v3.pvadeals.com/v3/api/request/req_1"): DummyResponse(status=200, json_data=request_payload),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    result = await provider.get_sms("req_1")

    assert result["success"] is True
    assert result["messages"] == []
    assert result["raw"]["provider_terminal_no_sms"] is True


@pytest.mark.asyncio
async def test_pvadeals_cancel_resend_and_renew(monkeypatch):
    session = DummySession(
        {
            ("POST", "https://prod-v3.pvadeals.com/v3/api/flag/req_1"): DummyResponse(status=200, json_data={"success": True, "data": True}),
            ("POST", "https://prod-v3.pvadeals.com/v3/api/reuse/req_1"): DummyResponse(status=200, json_data={"success": True, "data": {"_id": "req_1"}}),
            ("POST", "https://prod-v3.pvadeals.com/v3/api/renew-ltr/req_1"): DummyResponse(status=200, json_data={"success": True, "data": {"_id": "req_1", "autoRenewEnabled": True}}),
        }
    )

    async def fake_get_session():
        return session

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    provider = PVADealsProvider()

    cancel = await provider.cancel("req_1")
    resend = await provider.resend("req_1")
    renew = await provider.renew_rental("req_1")

    assert cancel["success"] is True
    assert resend is True
    assert renew["success"] is True
