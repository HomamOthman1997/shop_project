import os
import sys

import pytest
from utils.translations import t

sys.path.insert(0, os.getcwd())

from utils import bot_menu_context
from keyboards.main_menu_kb import digital_products_main_menu, main_menu, numbers_main_menu, reseller_user_main_menu
from keyboards.reseller_main_menu import reseller_main_menu
from services.cards_bot.keyboards import cards_main_menu


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

    assert t("en", "btn_services") in main_buttons
    assert t("en", "btn_proxies") not in main_buttons
    assert [btn.text for btn in main_menu("en").keyboard[1]] == [t("en", "btn_numbers"), t("en", "btn_create_bot")]
    assert t("en", "btn_services") in reseller_buttons
    assert "rsmenu:custom_services" in inline_callbacks
    assert "rsmenu:dashboard" in inline_callbacks
    assert "rsmenu:recharge_requests" in inline_callbacks
    assert "rsmenu:adjust_user_balance" in inline_callbacks
    assert "rsmenu:core_topup" in inline_callbacks
    assert "rsmenu:stats" in inline_callbacks


def test_digital_products_menu_exposes_miniapp_button_when_enabled(monkeypatch):
    from keyboards import main_menu_kb

    monkeypatch.setattr(main_menu_kb.settings, "digital_products_miniapp_enabled", True)
    monkeypatch.setattr(main_menu_kb.settings, "digital_products_miniapp_public_url", "https://store.example.com")

    kb = digital_products_main_menu("en")
    first_button = kb.keyboard[0][0]
    labels = [btn.text for row in kb.keyboard for btn in row]

    assert first_button.web_app is not None
    assert first_button.web_app.url == "https://store.example.com/mini/digital"
    assert t("en", "btn_giftcards") not in labels
    assert t("en", "btn_games_topups") not in labels
    assert t("en", "btn_sim_topup") not in labels


def test_numbers_menu_is_numbers_only():
    labels = [btn.text for row in numbers_main_menu("en").keyboard for btn in row]

    assert labels == [
        t("en", "btn_my_numbers"),
        t("en", "user_settings_my_account"),
        t("en", "btn_support"),
    ]
    assert t("en", "btn_services") not in labels
    assert t("en", "btn_create_bot") not in labels
    assert t("en", "btn_proxies") not in labels


@pytest.mark.asyncio
async def test_menu_for_current_bot_prioritizes_platform_store_bots_over_reseller_owned(monkeypatch):
    async def _true(*_args, **_kwargs):
        return True

    async def _false(*_args, **_kwargs):
        return False

    monkeypatch.setattr(bot_menu_context, "is_reseller_owned_bot", _true)
    monkeypatch.setattr(bot_menu_context, "is_main_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_numbers_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_digital_products_bot", _true)
    monkeypatch.setattr(bot_menu_context, "is_card_ex_bot", _false)

    kb = await bot_menu_context.menu_for_current_bot("ar", 123)
    labels = [btn.text for row in kb.keyboard for btn in row]

    assert labels == [btn.text for row in bot_menu_context.digital_products_main_menu("ar").keyboard for btn in row]
    assert t("ar", "btn_giftcards") in labels


@pytest.mark.asyncio
async def test_menu_for_current_bot_uses_numbers_menu(monkeypatch):
    async def _false(*_args, **_kwargs):
        return False

    async def _true(*_args, **_kwargs):
        return True

    monkeypatch.setattr(bot_menu_context, "is_main_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_numbers_bot", _true)
    monkeypatch.setattr(bot_menu_context, "is_digital_products_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_card_ex_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_reseller_owned_bot", _false)

    kb = await bot_menu_context.menu_for_current_bot("ar", 123)
    labels = [btn.text for row in kb.keyboard for btn in row]

    assert labels == [btn.text for row in numbers_main_menu("ar").keyboard for btn in row]


@pytest.mark.asyncio
async def test_menu_for_current_bot_uses_cards_menu_before_reseller_menu(monkeypatch):
    async def _true(*_args, **_kwargs):
        return True

    async def _false(*_args, **_kwargs):
        return False

    monkeypatch.setattr(bot_menu_context, "is_reseller_owned_bot", _true)
    monkeypatch.setattr(bot_menu_context, "is_main_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_numbers_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_digital_products_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_card_ex_bot", _true)

    kb = await bot_menu_context.menu_for_current_bot("ar", 123)
    labels = [btn.text for row in kb.keyboard for btn in row]

    assert labels == [btn.text for row in cards_main_menu("ar").keyboard for btn in row]


@pytest.mark.asyncio
async def test_menu_for_current_bot_shows_card_admin_button_for_admin_user(monkeypatch):
    async def _false(*_args, **_kwargs):
        return False

    async def _true(*_args, **_kwargs):
        return True

    monkeypatch.setattr(bot_menu_context, "is_main_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_numbers_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_digital_products_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_card_ex_bot", _true)
    monkeypatch.setattr(bot_menu_context, "is_reseller_owned_bot", _false)
    monkeypatch.setattr(bot_menu_context, "_cardex_admin_ids", lambda: {10})

    kb = await bot_menu_context.menu_for_current_bot("ar", 123, user_id=10)
    labels = [btn.text for row in kb.keyboard for btn in row]

    assert "لوحة الإدارة" in labels


@pytest.mark.asyncio
async def test_resolve_bot_kind_prioritizes_platform_kinds_over_reseller(monkeypatch):
    async def _true(*_args, **_kwargs):
        return True

    async def _false(*_args, **_kwargs):
        return False

    monkeypatch.setattr(bot_menu_context, "is_main_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_numbers_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_digital_products_bot", _true)
    monkeypatch.setattr(bot_menu_context, "is_card_ex_bot", _false)
    monkeypatch.setattr(bot_menu_context, "is_reseller_owned_bot", _true)

    assert await bot_menu_context.resolve_bot_kind(123) == bot_menu_context.BOT_KIND_DIGITAL
