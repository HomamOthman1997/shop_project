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

    async def _fake_provider_resolution(service_key: str, provider_code: str):
        return {"resolved_provider_service": "svc_1", "provider_reason": "resolved_provider_lookup"}

    monkeypatch.setattr(
        manager,
        "PROVIDERS",
        {"smspool": _LowBalanceProvider(), "nonvoip": _EnoughBalanceProvider()},
        raising=False,
    )
    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", _fake_provider_resolution)
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)
    monkeypatch.setattr(manager.settings, "numbers_show_all_providers_for_testing", False)

    prices = await manager.get_all_prices("paypal", "1", None)
    assert "smspool" not in prices
    assert "nonvoip" in prices
    assert prices["nonvoip"]["base_price"] == 0.55


@pytest.mark.asyncio
async def test_get_all_prices_marks_low_balance_provider_not_buyable_in_testing_mode(monkeypatch):
    from services.numbers import manager

    class _LowBalanceProvider:
        async def get_price(self, service, country=None, state=None):
            return {"success": True, "price": 0.50}

        async def get_balance(self):
            return 0.03

    async def _fake_provider_resolution(service_key: str, provider_code: str):
        return {"resolved_provider_service": "svc_1", "provider_reason": "resolved_provider_lookup"}

    monkeypatch.setattr(
        manager,
        "PROVIDERS",
        {"smspool": _LowBalanceProvider()},
        raising=False,
    )
    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", _fake_provider_resolution)
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)
    monkeypatch.setattr(manager.settings, "numbers_show_all_providers_for_testing", True)

    prices = await manager.get_all_prices("paypal", "1", None)
    assert "smspool" in prices
    assert prices["smspool"]["available_for_buy"] is False
    assert prices["smspool"]["provider_reason"] == "provider_balance_low"


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


@pytest.mark.asyncio
async def test_get_all_prices_uses_simulated_provider_balance(monkeypatch):
    from services.numbers import manager

    class _Provider:
        async def get_price(self, service, country=None, state=None):
            return {"success": True, "price": 0.5}

        async def get_balance(self):
            return 0.0

    async def _fake_provider_resolution(service_key: str, provider_code: str):
        return {"resolved_provider_service": "svc_1", "provider_reason": "resolved_provider_lookup"}

    monkeypatch.setattr(
        manager,
        "PROVIDERS",
        {"smspool": _Provider()},
        raising=False,
    )
    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", _fake_provider_resolution)
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)
    monkeypatch.setattr(manager.settings, "numbers_show_all_providers_for_testing", False)
    monkeypatch.setattr(manager.settings, "numbers_provider_balance_simulation", '{"smspool": 5}')
    manager._PROVIDER_BALANCE_CACHE.clear()

    prices = await manager.get_all_prices("paypal", "1", None)
    assert "smspool" in prices
    assert prices["smspool"]["available_for_buy"] is True
    assert prices["smspool"]["provider_balance"] == 5.0


@pytest.mark.asyncio
async def test_get_all_prices_keeps_provider_visible_when_balance_unknown(monkeypatch):
    from services.numbers import manager

    class _Provider:
        async def get_price(self, service, country=None, state=None):
            return {"success": True, "price": 0.5}

        async def get_balance(self):
            raise RuntimeError("balance endpoint down")

    async def _fake_provider_resolution(service_key: str, provider_code: str):
        return {"resolved_provider_service": "svc_1", "provider_reason": "resolved_provider_lookup"}

    monkeypatch.setattr(
        manager,
        "PROVIDERS",
        {"smspool": _Provider()},
        raising=False,
    )
    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", _fake_provider_resolution)
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)
    monkeypatch.setattr(manager.settings, "numbers_show_all_providers_for_testing", False)
    manager._PROVIDER_BALANCE_CACHE.clear()

    prices = await manager.get_all_prices("paypal", "1", None)
    assert "smspool" in prices
    assert prices["smspool"]["base_price"] == 0.5
    assert prices["smspool"]["provider_reason"] == "provider_balance_unknown"


@pytest.mark.asyncio
async def test_get_all_prices_does_not_block_on_slow_balance(monkeypatch):
    from services.numbers import manager

    class _Provider:
        async def get_price(self, service, country=None, state=None):
            return {"success": True, "price": 0.5}

        async def get_balance(self):
            await __import__("asyncio").sleep(0.7)
            return 10.0

    async def _fake_provider_resolution(service_key: str, provider_code: str):
        return {"resolved_provider_service": "svc_1", "provider_reason": "resolved_provider_lookup"}

    monkeypatch.setattr(
        manager,
        "PROVIDERS",
        {"smspool": _Provider()},
        raising=False,
    )
    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", _fake_provider_resolution)
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)
    monkeypatch.setattr(manager.settings, "numbers_show_all_providers_for_testing", False)
    monkeypatch.setattr(manager, "_price_screen_balance_timeout_sec", lambda: 0.01)
    manager._PROVIDER_BALANCE_CACHE.clear()

    prices = await manager.get_all_prices("paypal", "1", None)
    assert "smspool" in prices
    assert prices["smspool"]["base_price"] == 0.5
    assert prices["smspool"]["provider_reason"] == "provider_balance_unknown"


@pytest.mark.asyncio
async def test_get_all_prices_ignore_balance_skips_balance_endpoint(monkeypatch):
    from services.numbers import manager

    class _Provider:
        async def get_price(self, service, country=None, state=None):
            return {"success": True, "price": 0.5}

        async def get_balance(self):
            raise AssertionError("price screen should not call balance when ignore_balance=True")

    async def _fake_provider_resolution(service_key: str, provider_code: str):
        return {"resolved_provider_service": "svc_1", "provider_reason": "resolved_provider_lookup"}

    monkeypatch.setattr(
        manager,
        "PROVIDERS",
        {"smspool": _Provider()},
        raising=False,
    )
    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", _fake_provider_resolution)
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)
    monkeypatch.setattr(manager.settings, "numbers_show_all_providers_for_testing", False)
    manager._PROVIDER_BALANCE_CACHE.clear()

    prices = await manager.get_all_prices("paypal", "1", None, ignore_balance=True)

    assert "smspool" in prices
    assert prices["smspool"]["available_for_buy"] is True
    assert prices["smspool"]["base_price"] == 0.5
