import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

import utils.reseller_setup_guard as reseller_setup_guard


@pytest.mark.asyncio
async def test_setup_ready_requires_configured_enabled_method_and_payment_routing(monkeypatch):
    async def fake_methods(_reseller_id):
        return [
            {"code": "good", "enabled": True, "target": "wallet-123"},
            {"code": "off", "enabled": False, "target": "SET_UNUSED"},
        ]

    async def fake_pay_route(_reseller_id):
        return {"chat_id": -100123, "message_thread_id": 77}

    async def fake_ex_route(_reseller_id):
        return None

    monkeypatch.setattr(reseller_setup_guard, "get_payment_methods", fake_methods)
    monkeypatch.setattr(reseller_setup_guard, "get_recharge_routing", fake_pay_route)
    monkeypatch.setattr(reseller_setup_guard, "get_exchange_routing", fake_ex_route)

    status = await reseller_setup_guard.get_reseller_setup_status(55)

    assert status["ready"] is True
    assert status["payment_methods_ready"] is True
    assert status["payment_routing_ok"] is True
    assert status["exchange_routing_ok"] is False
    assert status["group_ready"] is True
    assert status["topics_enabled"] is True
    assert status["configured_methods_count"] == 1
    assert status["enabled_methods_count"] == 1


@pytest.mark.asyncio
async def test_setup_not_ready_when_enabled_placeholder_method_remains(monkeypatch):
    async def fake_methods(_reseller_id):
        return [
            {"code": "good", "enabled": True, "target": "wallet-123"},
            {"code": "bad", "enabled": True, "target": "SET_NEEDS_CONFIG"},
        ]

    async def fake_pay_route(_reseller_id):
        return {"chat_id": -100123, "message_thread_id": None}

    async def fake_ex_route(_reseller_id):
        return {"chat_id": -100123, "message_thread_id": None}

    monkeypatch.setattr(reseller_setup_guard, "get_payment_methods", fake_methods)
    monkeypatch.setattr(reseller_setup_guard, "get_recharge_routing", fake_pay_route)
    monkeypatch.setattr(reseller_setup_guard, "get_exchange_routing", fake_ex_route)

    status = await reseller_setup_guard.get_reseller_setup_status(55)

    assert status["ready"] is False
    assert status["has_configured_payment_method"] is True
    assert status["payment_methods_ready"] is False
    assert status["payment_routing_ok"] is True
    assert status["topics_enabled"] is False
    assert status["configured_methods_count"] == 1
    assert status["enabled_methods_count"] == 2


def test_render_notice_calls_out_missing_items():
    text = reseller_setup_guard.render_reseller_setup_notice(
        "en",
        {
            "payment_methods_ready": False,
            "has_configured_payment_method": False,
            "payment_routing_ok": False,
            "configured_methods_count": 0,
            "enabled_methods_count": 2,
        },
    )

    assert "Set up at least one usable payment method" in text
    assert "Bind a payment topic or private group target" in text
