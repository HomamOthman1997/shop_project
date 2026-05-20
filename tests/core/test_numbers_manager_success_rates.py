import pytest

from services.numbers import manager


class _TempProvider:
    async def get_price(self, _service, _country=None, _state=None):
        return {"success": True, "price": 1.0, "api_service_name": "telegram"}


class _RentalProvider:
    async def get_rental_prices(self, _service, country=None):
        return {"success": True, "options": [{"duration": "1h", "price": 2.0}]}


async def _zero_markup():
    return 0.0


async def _provider_balance(*_args, **_kwargs):
    return 100.0


async def _service_resolution(*_args, **_kwargs):
    return {
        "resolved_provider_service": "telegram",
        "provider_reason": "resolved_provider_lookup",
        "requested_service": "telegram",
        "canonical_service": "telegram",
    }


async def _service_name(*_args, **_kwargs):
    return "telegram"


@pytest.mark.asyncio
async def test_get_all_prices_can_skip_dynamic_success_rates(monkeypatch):
    calls = []

    async def _apply(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(manager, "PROVIDERS", {"fake": _TempProvider()})
    monkeypatch.setattr(manager, "provider_allows_temp", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "_provider_balance_with_timeout", _provider_balance)
    monkeypatch.setattr(manager, "_effective_numbers_markup_percent", _zero_markup)
    monkeypatch.setattr(manager, "_price_screen_provider_timeout_sec", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", _service_resolution)
    monkeypatch.setattr(manager, "_apply_dynamic_success_rates", _apply)

    result = await manager.get_all_prices("telegram", "1", "none", with_success_rates=False)

    assert result["fake"]["price"] > 0
    assert calls == []


@pytest.mark.asyncio
async def test_get_all_prices_keeps_dynamic_success_rates_by_default(monkeypatch):
    calls = []

    async def _apply(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(manager, "PROVIDERS", {"fake": _TempProvider()})
    monkeypatch.setattr(manager, "provider_allows_temp", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "_provider_balance_with_timeout", _provider_balance)
    monkeypatch.setattr(manager, "_effective_numbers_markup_percent", _zero_markup)
    monkeypatch.setattr(manager, "_price_screen_provider_timeout_sec", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", _service_resolution)
    monkeypatch.setattr(manager, "_apply_dynamic_success_rates", _apply)

    result = await manager.get_all_prices("telegram", "1", "none")

    assert result["fake"]["price"] > 0
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_get_all_rental_prices_can_skip_dynamic_success_rates(monkeypatch):
    calls = []

    async def _apply(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(manager, "PROVIDERS", {"fake": _RentalProvider()})
    monkeypatch.setattr(manager, "provider_supports_rental", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "provider_supports_unlimited_rental", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(manager, "provider_allows_rental", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "get_provider_service_name_dynamic", _service_name)
    monkeypatch.setattr(manager, "_provider_balance", _provider_balance)
    monkeypatch.setattr(manager, "_effective_numbers_markup_percent", _zero_markup)
    monkeypatch.setattr(manager, "_provider_timeout_sec", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(manager, "_apply_dynamic_success_rates", _apply)

    result = await manager.get_all_rental_prices("telegram", "1", with_success_rates=False)

    assert result["fake"]["options"][0]["price"] == 2.0
    assert calls == []
