import os
import sys
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

from config import settings
from database.financial_ledger import _cycle_bounds
from handlers.admin_services import _parse_owner_target_payload
from handlers.main_menu import _as_utc as main_menu_as_utc
from handlers.reseller_recharge import _build_reseller_dashboard_text, _build_reseller_stats_text
from middlewares.version_check import _as_utc as version_check_as_utc, _allow_owner_panel_callback


def test_parse_owner_target_payload_chat_and_topic():
    assert _parse_owner_target_payload("-1001234567890 44") == (-1001234567890, 44)
    assert _parse_owner_target_payload("-1001234567890") == (-1001234567890, None)


def test_parse_owner_target_payload_link():
    parsed = _parse_owner_target_payload("https://t.me/c/1234567890/77?thread=55")
    assert parsed == (-1001234567890, 55)


def test_parse_owner_target_payload_invalid():
    assert _parse_owner_target_payload("not_a_target") is None
    assert _parse_owner_target_payload("https://example.com/x") is None


def test_cycle_bounds_are_utc_aware():
    start, end = _cycle_bounds("2026-03")
    assert start.tzinfo is not None
    assert end.tzinfo is not None
    assert start.tzinfo == UTC
    assert end.tzinfo == UTC
    assert start < end
    assert start.month == 3
    assert end.month == 4


def test_as_utc_helpers_convert_naive_and_aware():
    naive = datetime(2026, 3, 1, 10, 30, 0)
    converted_main = main_menu_as_utc(naive)
    converted_version = version_check_as_utc(naive)

    assert converted_main is not None and converted_main.tzinfo == UTC
    assert converted_version is not None and converted_version.tzinfo == UTC

    aware_plus_3 = datetime(2026, 3, 1, 13, 30, 0, tzinfo=timezone(timedelta(hours=3)))
    converted = main_menu_as_utc(aware_plus_3)
    assert converted is not None
    assert converted.tzinfo == UTC
    assert converted.hour == 10


def test_owner_panel_callback_bypass_only_for_owner():
    owner_id = int(settings.owner_id)
    assert _allow_owner_panel_callback(owner_id, "owner_panel:open") is True
    assert _allow_owner_panel_callback(owner_id, "owner_pm:open") is True
    assert _allow_owner_panel_callback(owner_id, "lang_en") is False
    assert _allow_owner_panel_callback(1, "owner_panel:open") is False


@pytest.mark.asyncio
async def test_reseller_stats_text_renders(monkeypatch):
    async def fake_balance(_rid, wallet_type="main"):
        return 125.5 if wallet_type == "main" else 30.0

    async def fake_methods(_rid):
        return [{"code": "usdt"}, {"code": "cash"}]

    async def fake_rate(_rid):
        return 13250.0

    class RechargeRequests:
        async def count_documents(self, query):
            status = str(query.get("status") or "")
            if status == "pending":
                return 4
            if status == "need_more_proof":
                return 1
            return 0

    class FixedCount:
        def __init__(self, value):
            self.value = value

        async def count_documents(self, _query):
            return self.value

    fake_db = SimpleNamespace(
        recharge_requests=RechargeRequests(),
        user_reseller_links=FixedCount(18),
        bots=FixedCount(2),
        orders=FixedCount(3),
    )

    import handlers.reseller_recharge as reseller_recharge

    monkeypatch.setattr(reseller_recharge, "get_reseller_wallet_balance", fake_balance)
    monkeypatch.setattr(reseller_recharge, "get_payment_methods", fake_methods)
    monkeypatch.setattr(reseller_recharge, "get_exchange_rate", fake_rate)
    monkeypatch.setattr(reseller_recharge, "db", fake_db)

    text = await _build_reseller_stats_text(7731488539)
    assert "Sales & Profit" in text
    assert "Reseller ID: 7731488539" in text
    assert "Active bots: 2" in text
    assert "Linked users: 18" in text
    assert "Sales last 24h" in text
    assert "Payment methods configured: 2" in text


@pytest.mark.asyncio
async def test_reseller_dashboard_text_is_actionable(monkeypatch):
    async def fake_balance(_rid, wallet_type="main"):
        return 15.0 if wallet_type == "main" else 4.0

    async def fake_methods(_rid):
        return [{"code": "usdt", "enabled": True}, {"code": "cash", "enabled": False}]

    async def fake_rate(_rid):
        return 13250.0

    async def fake_setup(_rid):
        return False, {
            "payment_routing_ok": False,
            "exchange_routing_ok": True,
            "topics_enabled": False,
        }

    async def fake_subscription(_bot_id):
        return {
            "status": "payment_required",
            "trial_available": True,
            "trial_price_usd": 1.0,
            "renewal_plan_months": 1,
        }

    async def fake_support(_rid):
        return {"services": {"chat_id": -1001}, "user_balance": {"chat_id": -1001}}

    class FixedCount:
        def __init__(self, value):
            self.value = value

        async def count_documents(self, _query):
            return self.value

    class RechargeRequests:
        async def count_documents(self, query):
            return 3 if str(query.get("status") or "") == "pending" else 1

    fake_db = SimpleNamespace(
        recharge_requests=RechargeRequests(),
        user_reseller_links=FixedCount(9),
        bots=FixedCount(1),
        orders=FixedCount(2),
    )

    import handlers.reseller_recharge as reseller_recharge

    monkeypatch.setattr(reseller_recharge, "get_reseller_wallet_balance", fake_balance)
    monkeypatch.setattr(reseller_recharge, "get_payment_methods", fake_methods)
    monkeypatch.setattr(reseller_recharge, "get_exchange_rate", fake_rate)
    monkeypatch.setattr(reseller_recharge, "_reseller_setup_ready", fake_setup)
    monkeypatch.setattr(reseller_recharge, "get_bot_subscription", fake_subscription)
    monkeypatch.setattr(reseller_recharge, "get_all_support_routing", fake_support)
    monkeypatch.setattr(reseller_recharge, "db", fake_db)

    text = await _build_reseller_dashboard_text(77, 555, "en")

    assert "Control Center" in text
    assert "Next:" in text
    assert "Set a real number or wallet" in text
    assert "Customer support: 2/2 ready (optional)" in text
    assert "Payment methods: 0/1 ready" in text
    assert "Open numbers orders" not in text
    assert "Custom-services profit" not in text
    assert "Exchange routing" not in text
