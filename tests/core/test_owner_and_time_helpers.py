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
from handlers.reseller_recharge import _build_reseller_stats_text
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
    assert "Reseller Stats" in text
    assert "Reseller ID: 7731488539" in text
    assert "Active bots: 2" in text
    assert "Linked users: 18" in text
    assert "Payment methods configured: 2" in text
