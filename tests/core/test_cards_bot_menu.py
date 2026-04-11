import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

from services.cards_bot import handlers as cards_handlers
from services.cards_bot.handlers import _is_cards_admin, _is_menu_btn
from services.cards_bot.keyboards import cards_main_menu


def test_cards_main_menu_uses_arabic_labels_for_ar():
    kb = cards_main_menu("ar")
    labels = [button.text for row in kb.keyboard for button in row]
    assert "بيع كرت" in labels
    assert "🗂 بطاقات وقسائم" in labels
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


def test_cards_main_menu_adds_admin_button_for_admins():
    kb = cards_main_menu("ar", is_admin=True)
    labels = [button.text for row in kb.keyboard for button in row]
    assert "لوحة الإدارة" in labels


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
