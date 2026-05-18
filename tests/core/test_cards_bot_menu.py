import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

from services.cards_bot import handlers as cards_handlers
from datetime import UTC, datetime

from services.cards_bot.handlers import (
    _cards_today_report_text,
    _card_summary_text,
    _group_cards_export_files,
    _is_cards_admin,
    _is_menu_btn,
    _operation_failed_text,
    _price_sheet_text,
    _split_message_text,
)
from services.cards_bot.keyboards import cards_admin_panel_kb, cards_main_menu


def test_cards_main_menu_uses_arabic_labels_for_ar():
    kb = cards_main_menu("ar")
    labels = [button.text for row in kb.keyboard for button in row]
    assert "بيع كرت" in labels
    assert "بطاقات وقسائم" not in labels
    assert "المحفظة" in labels
    assert "بطاقاتي" in labels
    assert "طلب سحب" in labels
    assert "سحوباتي" in labels


def test_cards_menu_button_aliases_accept_arabic_and_english():
    assert _is_menu_btn("Sell Card", "Sell Card")
    assert _is_menu_btn("بيع كرت", "Sell Card")
    assert _is_menu_btn("Wallet", "Wallet")
    assert _is_menu_btn("المحفظة", "Wallet")
    assert _is_menu_btn("بطاقاتي", "My Cards")
    assert _is_menu_btn("طلب سحب", "Withdraw")
    assert _is_menu_btn("سحوباتي", "My Withdrawals")


def test_cards_main_menu_shows_admin_panel_and_card_actions_for_admins():
    kb = cards_main_menu("en", is_admin=True)
    labels = [button.text for row in kb.keyboard for button in row]
    assert "Admin Panel" in labels
    assert "Sell Card" in labels
    assert "Price Sheet" in labels


def test_cards_admin_panel_has_daily_export_button():
    kb = cards_admin_panel_kb("ar")
    callbacks = [button.callback_data for row in kb.inline_keyboard for button in row]
    assert "cardx:panel:today_report" in callbacks
    assert "cardx:panel:export_today" in callbacks
    assert "cardx:panel:set_pricing" in callbacks
    assert "cardx:panel:price_sheet" in callbacks


def test_card_daily_report_summarizes_counts():
    text = _cards_today_report_text(
        "en",
        day=datetime(2026, 5, 14, tzinfo=UTC),
        rows=[
            {"brand": "Amazon", "status": "submitted"},
            {"brand": "Amazon", "status": "customer_pending_credit"},
            {"brand": "Steam", "status": "submitted"},
        ],
        pending_reviews=2,
        missing_pricing=1,
        open_withdrawals=3,
    )

    assert "Today's cards: 3" in text
    assert "Pending review: 2" in text
    assert "- AMAZON: 2" in text
    assert "- SUBMITTED: 2" in text


def test_card_daily_export_groups_files_by_brand():
    day = datetime(2026, 5, 14, tzinfo=UTC)
    files = _group_cards_export_files(
        [
            {
                "_id": "c1",
                "brand": "Amazon",
                "code": "AAA",
                "pin": "111",
                "denomination": 10,
                "currency": "USD",
                "region": "US",
                "status": "customer_pending_credit",
            },
            {
                "_id": "c2",
                "brand": "Steam",
                "code": "BBB",
                "pin": None,
                "denomination": 20,
                "currency": "USD",
                "region": "GLOBAL",
                "status": "submitted",
            },
        ],
        day=day,
    )

    assert [name for name, _, _ in files] == ["cardex_2026-05-14_AMAZON.txt", "cardex_2026-05-14_STEAM.txt"]
    assert "AAA | 111 | 10.00 USD | US" in files[0][1]
    assert "BBB | - | 20.00 USD | GLOBAL" in files[1][1]


def test_cardex_operation_failed_text_does_not_expose_exception_details():
    text = _operation_failed_text("en")
    assert "connection failed" not in text.lower()
    assert "neon.tech" not in text.lower()
    assert "try again later" in text.lower()


def test_card_summary_includes_configured_price():
    text = _card_summary_text(
        "en",
        {
            "brand": "APPLE",
            "denomination": "6",
            "currency": "USD",
            "region": "USA",
            "code": "abc",
            "pin": None,
            "price_configured": True,
            "quoted_customer_value_usd": 4.8,
            "quoted_customer_rate_percent": 80,
            "quoted_public_note": "Physical card only",
        },
    )

    assert "Card price:" in text
    assert "4.80" in text
    assert "(80%)" in text
    assert "Physical card only" in text


def test_card_summary_shows_missing_price_before_confirm():
    text = _card_summary_text(
        "en",
        {
            "brand": "APPLE",
            "denomination": "6",
            "currency": "USD",
            "region": "USA",
            "code": "abc",
            "pin": None,
            "price_configured": False,
        },
    )

    assert "Card price: not configured yet" in text


def test_price_sheet_lists_rates_and_public_notes():
    text = _price_sheet_text(
        "en",
        [
            {
                "brand": "APPLE",
                "denomination": 6,
                "currency": "USD",
                "region": "USA",
                "customer_buy_rate_percent": 80,
                "public_note": "Physical card only",
            }
        ],
    )

    assert "Today's Card Prices" in text
    assert "APPLE | 6.00 USD | USA | 80%" in text
    assert "Physical card only" in text


def test_long_card_messages_are_split_under_telegram_limit():
    text = "Header\n\n" + "\n".join(f"- APPLE | {idx}.00 USD | USA | 80% | note" for idx in range(300))
    chunks = _split_message_text(text, limit=500)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


@pytest.mark.asyncio
async def test_cards_admin_ids_include_owner_and_configured_admins(monkeypatch):
    monkeypatch.setattr(
        cards_handlers,
        "settings",
        SimpleNamespace(owner_id=10, cardex_admin_ids="20,30"),
    )
    assert _is_cards_admin(10) is True
    assert _is_cards_admin(20) is True
    assert _is_cards_admin(30) is True
    assert _is_cards_admin(99) is False
