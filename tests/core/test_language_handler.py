import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

import handlers.language as language_handler


class DummyMessage:
    def __init__(self):
        self.edits = []
        self.answers = []
        self.stickers = []

    async def edit_text(self, text, reply_markup=None):
        self.edits.append({"text": text, "reply_markup": reply_markup})

    async def answer(self, text, reply_markup=None):
        self.answers.append({"text": text, "reply_markup": reply_markup})

    async def answer_sticker(self, sticker, reply_markup=None):
        self.stickers.append({"sticker": sticker, "reply_markup": reply_markup})


class DummyBot:
    def __init__(self, bot_id: int):
        self._bot_id = bot_id

    async def get_me(self):
        return SimpleNamespace(id=self._bot_id)


class DummyCallback:
    def __init__(self, bot_id: int = 123, user_id: int = 456):
        self.from_user = SimpleNamespace(id=user_id)
        self.bot = DummyBot(bot_id)
        self.message = DummyMessage()
        self.message.bot = self.bot
        self.message.from_user = self.from_user
        self.answered = False

    async def answer(self):
        self.answered = True


class DummyState:
    def __init__(self):
        self.data = {}
        self.state = None
        self.cleared = False

    async def clear(self):
        self.cleared = True
        self.data.clear()

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.state = state


@pytest.mark.asyncio
async def test_language_selection_opens_digital_menu_without_channel_gate(monkeypatch):
    callback = DummyCallback(bot_id=777, user_id=888)
    calls = {"settings": 0}

    async def fake_update_language(user_id, lang):
        assert user_id == 888
        assert lang == "en"

    async def fake_get_settings(_bot_id):
        calls["settings"] += 1
        return {}

    async def fake_true(_bot_id):
        return True

    async def fake_false(_bot_id):
        return False

    async def fake_menu(lang, bot_id, user_id=None):
        assert lang == "en"
        assert bot_id == 777
        assert user_id == 888
        return "DIGITAL_MENU"

    monkeypatch.setattr(language_handler, "update_user_language", fake_update_language)
    monkeypatch.setattr(language_handler, "get_bot_settings", fake_get_settings)
    monkeypatch.setattr(language_handler, "is_main_bot", fake_false)
    monkeypatch.setattr(language_handler, "is_numbers_bot", fake_false)
    monkeypatch.setattr(language_handler, "is_digital_products_bot", fake_true)
    monkeypatch.setattr(language_handler, "is_card_ex_bot", fake_false)
    monkeypatch.setattr(language_handler, "menu_for_current_bot", fake_menu)

    await language_handler._apply_language(callback, "en")

    assert callback.answered is True
    assert calls["settings"] == 0
    assert callback.message.edits == [{"text": "Main Menu", "reply_markup": "DIGITAL_MENU"}]


@pytest.mark.asyncio
async def test_language_selection_keeps_channel_warning_for_reseller_bot(monkeypatch):
    callback = DummyCallback(bot_id=321, user_id=654)

    async def fake_update_language(_user_id, _lang):
        return None

    async def fake_get_settings(_bot_id):
        return {}

    async def fake_false(_bot_id):
        return False

    monkeypatch.setattr(language_handler, "update_user_language", fake_update_language)
    monkeypatch.setattr(language_handler, "get_bot_settings", fake_get_settings)
    monkeypatch.setattr(language_handler, "is_main_bot", fake_false)
    monkeypatch.setattr(language_handler, "is_numbers_bot", fake_false)
    monkeypatch.setattr(language_handler, "is_digital_products_bot", fake_false)
    monkeypatch.setattr(language_handler, "is_card_ex_bot", fake_false)

    await language_handler._apply_language(callback, "en")

    assert callback.answered is True
    assert len(callback.message.edits) == 1
    assert "Subscription channel is not configured" in callback.message.edits[0]["text"]
    assert callback.message.edits[0]["reply_markup"] is None


@pytest.mark.asyncio
async def test_language_selection_opens_numbers_type_menu(monkeypatch):
    callback = DummyCallback(bot_id=879, user_id=654)
    state = DummyState()

    async def fake_update_language(_user_id, _lang):
        return None

    async def fake_true(_bot_id):
        return True

    async def fake_false(_bot_id):
        return False

    async def fake_menu(_lang, _bot_id, user_id=None):
        return "REPLY_MENU"

    monkeypatch.setattr(language_handler, "update_user_language", fake_update_language)
    monkeypatch.setattr(language_handler, "is_numbers_bot", fake_true)
    monkeypatch.setattr(language_handler, "is_main_bot", fake_false)
    monkeypatch.setattr(language_handler, "is_digital_products_bot", fake_false)
    monkeypatch.setattr(language_handler, "is_card_ex_bot", fake_false)
    monkeypatch.setattr("handlers.start.menu_for_current_bot", fake_menu)

    await language_handler._apply_language(callback, "en", state)

    assert callback.answered is True
    assert state.cleared is True
    assert state.data["lang"] == "en"
    assert state.state.state == "NumberFlow:num_type"
    assert callback.message.answers
    assert callback.message.answers[0]["text"] == "Menu"
    assert callback.message.answers[0]["reply_markup"].keyboard[0][0].text == "📦 My Numbers"
    assert callback.message.stickers
    assert callback.message.stickers[0]["reply_markup"].inline_keyboard[0][0].callback_data == "flow:type:temp"
    assert all(
        row[0].callback_data != "flow:cancel"
        for row in callback.message.stickers[0]["reply_markup"].inline_keyboard
    )
