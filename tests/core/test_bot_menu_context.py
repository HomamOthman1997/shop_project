import os
import sys

import pytest
from utils.translations import t

sys.path.insert(0, os.getcwd())

from utils import bot_menu_context
from keyboards.main_menu_kb import main_menu, reseller_user_main_menu
from keyboards.reseller_main_menu import reseller_main_menu


class _DummyMessage:
    def __init__(self):
        self.calls = []

    async def answer(self, text, reply_markup=None):
        self.calls.append((text, reply_markup))


@pytest.mark.asyncio
async def test_send_main_bot_message_clears_reply_keyboard_first(monkeypatch):
    message = _DummyMessage()

    monkeypatch.setattr(bot_menu_context, "main_bot_services_text", lambda lang: "go main")
    monkeypatch.setattr(bot_menu_context, "main_bot_services_kb", lambda lang, back_callback="back_to_main_menu": "INLINE")

    async def _fake_text(lang):
        return "go main"

    monkeypatch.setattr(bot_menu_context, "main_bot_services_text", _fake_text)

    await bot_menu_context.send_main_bot_message(message, lang="en")

    assert len(message.calls) == 2
    assert message.calls[0][0] == "\u2800"
    assert message.calls[0][1].__class__.__name__ == "ReplyKeyboardRemove"
    assert message.calls[1] == ("go main", "INLINE")


@pytest.mark.asyncio
async def test_send_digital_products_message_clears_reply_keyboard_first(monkeypatch):
    message = _DummyMessage()

    monkeypatch.setattr(bot_menu_context, "digital_products_bot_url", lambda start="hub": "https://t.me/testbot?start=hub")

    await bot_menu_context.send_digital_products_message(message, lang="en")

    assert len(message.calls) == 2
    assert message.calls[0][0] == "\u2800"
    assert message.calls[0][1].__class__.__name__ == "ReplyKeyboardRemove"
    assert message.calls[1][0]
    assert message.calls[1][1].__class__.__name__ == "InlineKeyboardMarkup"


def test_main_menus_do_not_show_custom_services_button():
    main_buttons = [btn.text for row in main_menu("en").keyboard for btn in row]
    reseller_buttons = [btn.text for row in reseller_user_main_menu("en").keyboard for btn in row]
    inline_callbacks = [
        btn.callback_data
        for row in reseller_main_menu("en").inline_keyboard
        for btn in row
        if btn.callback_data
    ]

    assert t("en", "btn_services") not in main_buttons
    assert t("en", "btn_services") not in reseller_buttons
    assert "rsmenu:custom_services" not in inline_callbacks
