import os
import sys

sys.path.insert(0, os.getcwd())

from services.cards_bot.handlers import _is_menu_btn
from services.cards_bot.keyboards import cards_main_menu


def test_cards_main_menu_uses_arabic_labels_for_ar():
    kb = cards_main_menu("ar")
    labels = [button.text for row in kb.keyboard for button in row]
    assert "بيع كرت" in labels
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
