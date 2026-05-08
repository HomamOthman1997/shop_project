import os
import sys

import pytest

sys.path.insert(0, os.getcwd())


@pytest.mark.asyncio
async def test_apply_dynamic_success_rates_blends_context_stats(monkeypatch):
    import services.numbers.manager as manager

    calls = []

    async def _fake_success_rates(**kwargs):
        calls.append(kwargs)
        if kwargs.get("country"):
            return {
                "herosms": {
                    "success_rate": 50.0,
                    "attempts": 1,
                    "sample_sufficient": False,
                }
            }
        return {
            "herosms": {
                "success_rate": 90.0,
                "attempts": 10,
                "sample_sufficient": True,
            }
        }

    monkeypatch.setattr(manager, "_success_rate_enabled", lambda: True)
    monkeypatch.setattr(manager, "_success_rate_min_attempts", lambda: 3)
    monkeypatch.setattr(manager.temp_number_stats_repo, "get_provider_success_rates", _fake_success_rates)

    results = {"herosms": {"price": 0.5, "api_service_name": "wa"}}
    await manager._apply_dynamic_success_rates(results, "whatsapp", country="US", state="CA")

    assert calls[1]["country"] == "US"
    assert calls[1]["state"] == "CA"
    assert results["herosms"]["success_rate"] == 90.0
    assert results["herosms"]["context_success_rate"] == 50.0
    assert results["herosms"]["context_success_attempts"] == 1
    assert 60.0 < results["herosms"]["recommended_success_rate"] < 90.0


@pytest.mark.asyncio
async def test_apply_dynamic_success_rates_uses_sufficient_context(monkeypatch):
    import services.numbers.manager as manager

    async def _fake_success_rates(**kwargs):
        if kwargs.get("country"):
            return {
                "telabot": {
                    "success_rate": 40.0,
                    "attempts": 4,
                    "sample_sufficient": True,
                }
            }
        return {
            "telabot": {
                "success_rate": 95.0,
                "attempts": 20,
                "sample_sufficient": True,
            }
        }

    monkeypatch.setattr(manager, "_success_rate_enabled", lambda: True)
    monkeypatch.setattr(manager, "_success_rate_min_attempts", lambda: 3)
    monkeypatch.setattr(manager.temp_number_stats_repo, "get_provider_success_rates", _fake_success_rates)

    results = {"telabot": {"price": 0.5, "api_service_name": "wa"}}
    await manager._apply_dynamic_success_rates(results, "whatsapp", country="US", state="none")

    assert results["telabot"]["recommended_success_rate"] == 40.0
