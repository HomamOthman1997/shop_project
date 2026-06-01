import pytest

from services.numbers import manager
from services.numbers.service_families import normalize_service_key
from services.numbers.service_map import resolve_canonical_service_key


class _TempProvider:
    async def get_price(self, _service, _country=None, _state=None):
        return {"success": True, "price": 1.0, "api_service_name": "telegram"}


class _SlowTempProvider:
    async def get_price(self, _service, _country=None, _state=None):
        await __import__("asyncio").sleep(1)
        return {"success": True, "price": 9.0, "api_service_name": "telegram"}


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


def test_arabic_attapoll_alias_resolves_to_canonical_service():
    assert normalize_service_key("اتابول") == "attapoll"
    assert resolve_canonical_service_key("اتابول") == "attapoll"


def test_numbers_miniapp_bootstrap_includes_arabic_attapoll_alias():
    from services.numbers.miniapp import _bootstrap_payload

    service = next(row for row in _bootstrap_payload()["services"] if row["key"] == "attapoll")

    assert "اتابول" in service["aliases"]


@pytest.mark.asyncio
async def test_get_all_prices_can_skip_dynamic_success_rates(monkeypatch):
    calls = []

    async def _apply(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(manager, "PROVIDERS", {"fake": _TempProvider()})
    monkeypatch.setattr(manager, "provider_quote_enabled", lambda *_args, **_kwargs: True)
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
    monkeypatch.setattr(manager, "provider_quote_enabled", lambda *_args, **_kwargs: True)
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
async def test_get_all_prices_does_not_block_on_slow_success_rates(monkeypatch):
    async def _slow_success_rates(*_args, **_kwargs):
        await __import__("asyncio").sleep(1)
        return {"fake": {"success_rate": 10.0, "attempts": 99, "sample_sufficient": True}}

    monkeypatch.setattr(manager, "PROVIDERS", {"fake": _TempProvider()})
    monkeypatch.setattr(manager, "provider_quote_enabled", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "provider_allows_temp", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "_provider_balance_with_timeout", _provider_balance)
    monkeypatch.setattr(manager, "_effective_numbers_markup_percent", _zero_markup)
    monkeypatch.setattr(manager, "_price_screen_provider_timeout_sec", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(manager, "_success_rate_query_timeout_sec", lambda: 0.01)
    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", _service_resolution)
    monkeypatch.setattr(manager.temp_number_stats_repo, "get_provider_success_rates", _slow_success_rates)

    result = await manager.get_all_prices("telegram", "1", "none")

    assert result["fake"]["price"] > 0
    assert result["fake"].get("success_rate") in (None, 100.0)


@pytest.mark.asyncio
async def test_get_all_prices_soft_timeout_returns_fast_provider(monkeypatch):
    monkeypatch.setattr(manager, "PROVIDERS", {"fast": _TempProvider(), "slow": _SlowTempProvider()})
    monkeypatch.setattr(manager, "provider_quote_enabled", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "provider_allows_temp", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "_provider_balance_with_timeout", _provider_balance)
    monkeypatch.setattr(manager, "_effective_numbers_markup_percent", _zero_markup)
    monkeypatch.setattr(manager, "_price_screen_provider_timeout_sec", lambda *_args, **_kwargs: 2.0)
    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", _service_resolution)
    monkeypatch.setattr(manager, "_apply_dynamic_success_rates", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))

    result = await manager.get_all_prices("telegram", "none", "none", soft_timeout_sec=0.05)

    assert "fast" in result
    assert "slow" not in result


@pytest.mark.asyncio
async def test_get_all_rental_prices_can_skip_dynamic_success_rates(monkeypatch):
    calls = []

    async def _apply(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(manager, "PROVIDERS", {"fake": _RentalProvider()})
    monkeypatch.setattr(manager, "provider_quote_enabled", lambda *_args, **_kwargs: True)
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
