import os
import sys

import pytest

sys.path.insert(0, os.getcwd())


@pytest.mark.asyncio
async def test_get_all_prices_filters_provider_with_insufficient_balance(monkeypatch):
    from services.numbers import manager

    class _LowBalanceProvider:
        async def get_price(self, service, country=None, state=None):
            return {"success": True, "price": 0.50}

        async def get_balance(self):
            return 0.03

    class _EnoughBalanceProvider:
        async def get_price(self, service, country=None, state=None):
            return {"success": True, "price": 0.55}

        async def get_balance(self):
            return 10.0

    async def _fake_provider_service_name(service_key: str, provider_code: str):
        return "svc_1"

    monkeypatch.setattr(
        manager,
        "PROVIDERS",
        {"smspool": _LowBalanceProvider(), "smsman": _EnoughBalanceProvider()},
        raising=False,
    )
    monkeypatch.setattr(manager, "get_provider_service_name_dynamic", _fake_provider_service_name)
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)
    monkeypatch.setattr(manager.settings, "numbers_show_all_providers_for_testing", False)
    manager._PRICE_CACHE.clear()

    prices = await manager.get_all_prices("paypal", "1", None)
    assert "smspool" not in prices
    assert "smsman" in prices
    assert prices["smsman"]["base_price"] == 0.55


@pytest.mark.asyncio
async def test_smspool_buy_number_returns_selected_pool(monkeypatch):
    from services.numbers.providers.smspool_provider import SMSPoolProvider
    from services.numbers.core.session_manager import SessionManager
    from config import settings

    monkeypatch.setattr(settings, "smspool_key", "dummy")

    class _DummyResp:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return {"order_id": "ord_1", "number": "12025550123", "pool": "sierra"}

    class _DummySession:
        def post(self, *args, **kwargs):
            return _DummyResp()

    async def _fake_get_session():
        return _DummySession()

    monkeypatch.setattr(SessionManager, "get_session", _fake_get_session)

    provider = SMSPoolProvider()
    result = await provider.buy_number("123", country="1", state=None)
    assert result["success"] is True
    assert result["pool"] == "sierra"
