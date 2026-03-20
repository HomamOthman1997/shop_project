import pytest

from services.numbers.core.session_manager import SessionManager
from services.numbers.providers.textverified_provider import TextVerifiedProvider


class DummyResp:
    def __init__(self, status: int, payload, headers=None):
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return str(self._payload)

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_textverified_get_rental_prices(monkeypatch):
    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    class DummySession:
        def post(self, url, headers=None, json=None):
            if url.endswith("/pub/v2/pricing/rentals"):
                duration = (json or {}).get("duration")
                renewable = bool((json or {}).get("isRenewable"))
                if duration == "oneDay" and renewable is False:
                    return DummyResp(200, {"serviceName": "gmail", "price": 0.75})
                if duration == "sevenDay" and renewable is True:
                    return DummyResp(200, {"serviceName": "gmail", "price": 2.25})
                return DummyResp(400, {"errorCode": "Unsupported", "errorDescription": "unsupported"})
            raise AssertionError(f"unexpected url: {url}")

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)
    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    res = await provider.get_rental_prices("gmail")
    assert res["success"] is True
    assert len(res["options"]) == 2
    by_key = {row["tv_duration_key"]: row for row in res["options"]}
    assert by_key["oneDay"]["price"] == 0.75
    assert by_key["oneDay"]["duration_label"] == "1d"
    assert by_key["oneDay"]["duration"] == 24
    assert by_key["oneDay"]["tv_is_renewable"] is False
    assert by_key["sevenDay"]["price"] == 2.25
    assert by_key["sevenDay"]["tv_is_renewable"] is True


@pytest.mark.asyncio
async def test_textverified_rent_number_follow_sale_and_reservation(monkeypatch):
    provider = TextVerifiedProvider()

    async def fake_auth(self):
        return "tok"

    class DummySession:
        def post(self, url, headers=None, json=None):
            if url.endswith("/pub/v2/reservations/rental"):
                return DummyResp(201, {"href": "https://www.textverified.com/pub/v2/sales/sale_001", "method": "GET"})
            raise AssertionError(f"unexpected post url: {url}")

        def request(self, method, url, headers=None):
            m = (method or "").upper()
            if m == "GET" and url.endswith("/pub/v2/sales/sale_001"):
                return DummyResp(
                    200,
                    {
                        "id": "sale_001",
                        "total": 0.75,
                        "reservations": [
                            {
                                "id": "lr_001",
                                "link": {"href": "https://www.textverified.com/pub/v2/reservations/rental/nonrenewable/lr_001", "method": "GET"},
                            }
                        ],
                    },
                )
            if m == "GET" and url.endswith("/pub/v2/reservations/rental/nonrenewable/lr_001"):
                return DummyResp(
                    200,
                    {
                        "id": "lr_001",
                        "number": "+15550001111",
                        "endsAt": "2026-03-10T04:00:00+00:00",
                    },
                )
            raise AssertionError(f"unexpected request {method} {url}")

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)
    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    res = await provider.rent_number("gmail", duration=24, tv_duration_key="oneDay", tv_is_renewable=False)
    assert res["success"] is True
    assert res["order_id"] == "lr_001"
    assert res["number"] == "+15550001111"
    assert res["price"] == 0.75


@pytest.mark.asyncio
async def test_textverified_rent_number_with_state_uses_area_code(monkeypatch):
    provider = TextVerifiedProvider()
    captured = {}

    async def fake_auth(self):
        return "tok"

    class DummySession:
        def post(self, url, headers=None, json=None):
            if url.endswith("/pub/v2/reservations/rental"):
                captured["payload"] = dict(json or {})
                return DummyResp(201, {"href": "https://www.textverified.com/pub/v2/sales/sale_002", "method": "GET"})
            raise AssertionError(f"unexpected post url: {url}")

        def request(self, method, url, headers=None):
            m = (method or "").upper()
            if m == "GET" and url.endswith("/pub/v2/sales/sale_002"):
                return DummyResp(
                    200,
                    {
                        "id": "sale_002",
                        "total": 2.75,
                        "reservations": [
                            {
                                "id": "lr_002",
                                "link": {"href": "https://www.textverified.com/pub/v2/reservations/rental/nonrenewable/lr_002", "method": "GET"},
                            }
                        ],
                    },
                )
            if m == "GET" and url.endswith("/pub/v2/reservations/rental/nonrenewable/lr_002"):
                return DummyResp(
                    200,
                    {
                        "id": "lr_002",
                        "number": "+15550002222",
                        "endsAt": "2026-03-10T05:00:00+00:00",
                    },
                )
            raise AssertionError(f"unexpected request {method} {url}")

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(TextVerifiedProvider, "_auth", fake_auth)
    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)

    res = await provider.rent_number(
        "gmail",
        duration=24,
        tv_duration_key="oneDay",
        tv_is_renewable=False,
        tv_with_state=True,
        state_code="NY",
    )
    assert res["success"] is True
    assert captured["payload"]["allowBackOrderReservations"] is False
    assert captured["payload"]["duration"] == "oneDay"
    assert captured["payload"]["isRenewable"] is False
    assert captured["payload"]["areaCodeSelectOption"] == ["212"]
