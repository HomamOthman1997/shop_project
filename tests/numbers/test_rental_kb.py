import os
import sys
from datetime import UTC, datetime, timedelta

import pytest
from aiogram.exceptions import TelegramBadRequest

sys.path.insert(0, os.getcwd())

from services.numbers.handlers import core_numbers, core_numbers_buy
from services.numbers.keyboards import core_numbers_kb
from services.numbers.keyboards.core_numbers_kb import number_type_kb, rental_providers_kb


def test_rental_providers_kb_uses_internal_provider_codes_for_layout():
    kb = rental_providers_kb(
        provider_rows=[
            {"provider": "smspool", "pricing_mode": "monthly", "avg_price": 10.0, "available_for_buy": True},
            {"provider": "textverified", "pricing_mode": "monthly", "avg_price": 11.0, "available_for_buy": True},
            {"provider": "pvadeals", "pricing_mode": "monthly", "avg_price": 12.0, "available_for_buy": True},
        ],
        lang="en",
        provider_options={
            "smspool": [
                {"provider": "smspool", "duration": 24, "price": 1.0},
                {"provider": "smspool", "duration": 168, "price": 2.0},
                {"provider": "smspool", "duration": 672, "price": 3.0},
                {"provider": "smspool", "duration": 720, "price": 4.0},
            ],
            "textverified": [
                {"provider": "textverified", "duration": 24, "price": 1.0},
                {"provider": "textverified", "duration": 72, "price": 2.0},
                {"provider": "textverified", "duration": 168, "price": 3.0},
                {"provider": "textverified", "duration": 336, "price": 4.0},
                {"provider": "textverified", "duration": 720, "price": 5.0},
            ],
            "pvadeals": [
                {"provider": "pvadeals", "duration": 72, "price": 6.0},
                {"provider": "pvadeals", "duration": 168, "price": 7.0},
                {"provider": "pvadeals", "duration": 336, "price": 8.0},
                {"provider": "pvadeals", "duration": 720, "price": 10.0},
            ],
        },
        usd_to_syp=0,
    )
    rows = [[button.text for button in row] for row in kb.inline_keyboard]
    assert rows[0] == ["Charlie"]
    assert rows[1] == ["1D | 1.00 💲", "7D | 2.00 💲", "28D | 3.00 💲"]
    assert rows[2] == ["Bravo"]
    assert rows[3] == ["1D | 1.00 💲", "3D | 2.00 💲", "7D | 3.00 💲"]
    assert rows[4] == ["14D | 4.00 💲", "30D | 5.00 💲"]
    assert rows[5] == ["Echo"]
    assert rows[6] == ["3D | 6.00 💲", "7D | 7.00 💲", "14D | 8.00 💲"]
    assert rows[7] == ["30D | 10.00 💲"]
    assert kb.inline_keyboard[0][0].style == "primary"
    assert getattr(kb.inline_keyboard[1][0], "style", None) is None


def test_number_type_kb_removes_free_emoji_when_custom_icon_is_set(monkeypatch):
    monkeypatch.setattr(core_numbers_kb, "_ICON_TEMP_NUMBERS", "custom-temp")
    monkeypatch.setattr(core_numbers_kb, "_ICON_RENTAL_NUMBERS", "custom-rental")
    monkeypatch.setattr(core_numbers_kb, "_ICON_CALL_NUMBER", "custom-call")

    kb = number_type_kb("en", show_cancel=False)

    assert kb.inline_keyboard[0][0].text == "Temp Number"
    assert kb.inline_keyboard[0][0].icon_custom_emoji_id == "custom-temp"
    assert kb.inline_keyboard[0][1].text == "Rental Number"
    assert kb.inline_keyboard[0][1].icon_custom_emoji_id == "custom-rental"
    assert kb.inline_keyboard[1][0].text == "Call Number"
    assert kb.inline_keyboard[1][0].icon_custom_emoji_id == "custom-call"


@pytest.mark.asyncio
async def test_safe_edit_text_falls_back_when_source_message_is_sticker():
    class _Message:
        def __init__(self):
            self.answers = []
            self.deleted = False

        async def edit_text(self, *_args, **_kwargs):
            raise TelegramBadRequest(method="editMessageText", message="Bad Request: there is no text in the message to edit")

        async def delete(self):
            self.deleted = True

        async def answer(self, text, reply_markup=None, parse_mode=None):
            self.answers.append((text, reply_markup, parse_mode))
            return "new-message"

    message = _Message()

    result = await core_numbers._safe_edit_text(message, "Next", reply_markup="KB", parse_mode="HTML")

    assert result == "new-message"
    assert message.deleted is True
    assert message.answers == [("Next", "KB", "HTML")]


@pytest.mark.asyncio
async def test_rental_type_goes_directly_to_service_selection():
    class _Message:
        def __init__(self):
            self.message_id = 44
            self.edits = []

        async def edit_text(self, text, reply_markup=None, parse_mode=None):
            self.edits.append((text, reply_markup, parse_mode))
            return self

    class _State:
        def __init__(self):
            self.data = {"lang": "en"}
            self.last_state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, state):
            self.last_state = state

    callback = type(
        "CB",
        (),
        {
            "data": "flow:type:rental",
            "message": _Message(),
        },
    )()
    state = _State()

    await core_numbers.choose_number_type(callback, state)

    assert state.data["num_type"] == "rental"
    assert state.last_state == core_numbers.NumberFlow.service
    assert callback.message.edits
    text, markup, parse_mode = callback.message.edits[0]
    assert "Rental Numbers Menu" not in text
    assert markup.inline_keyboard
    assert parse_mode == "HTML"


@pytest.mark.asyncio
async def test_voice_type_shows_call_number_service_selection():
    class _Message:
        def __init__(self):
            self.message_id = 46
            self.edits = []

        async def edit_text(self, text, reply_markup=None, parse_mode=None):
            self.edits.append((text, reply_markup, parse_mode))
            return self

    class _State:
        def __init__(self):
            self.data = {"lang": "en"}
            self.last_state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, state):
            self.last_state = state

    callback = type("CB", (), {"data": "flow:type:voice", "message": _Message()})()
    state = _State()

    await core_numbers.choose_number_type(callback, state)

    assert state.data["num_type"] == "voice"
    assert state.last_state == core_numbers.NumberFlow.service
    text, markup, parse_mode = callback.message.edits[0]
    assert "Mode: Call Number" in text
    assert "Mode: ⏱️ Temp Number" not in text
    assert markup.inline_keyboard
    assert parse_mode == "HTML"


@pytest.mark.asyncio
async def test_voice_inline_service_selection_skips_country_selection(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_load_service_prices(chat_id, bot, state, service_name):
        captured["chat_id"] = chat_id
        captured["service_name"] = service_name

    monkeypatch.setattr(core_numbers, "_load_service_prices", fake_load_service_prices)

    class _State:
        def __init__(self):
            self.data = {"lang": "en", "num_type": "voice", "last_msg_id": 50}
            self.last_state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, state):
            self.last_state = state

    class _Message:
        def __init__(self):
            self.text = "/select_service_gmail"
            self.chat = type("Chat", (), {"id": 123})()
            self.bot = object()
            self.deleted = False

        async def delete(self):
            self.deleted = True

    message = _Message()
    state = _State()

    await core_numbers.handle_inline_service_selection(message, state)

    assert message.deleted is True
    assert captured == {"chat_id": 123, "service_name": "gmail"}
    assert state.data["service"] == "gmail"
    assert state.data["country"] == "1"
    assert state.data["state"] == "none"
    assert state.last_state is None


@pytest.mark.asyncio
async def test_voice_price_loading_forces_us_without_state(monkeypatch):
    calls: list[tuple[str, str, str, bool]] = []

    async def fake_get_all_voice_prices(service_name, country, state_code, ignore_balance=True):
        calls.append((service_name, country, state_code, ignore_balance))
        return {
            "textverified": {
                "success": True,
                "price": 1.0,
                "available_for_buy": True,
                "success_rate": 100.0,
                "success_attempts": 0,
            }
        }

    async def fake_rate():
        return 0.0

    monkeypatch.setattr(core_numbers, "get_all_voice_prices", fake_get_all_voice_prices)
    monkeypatch.setattr(core_numbers, "_resolve_usd_to_syp_rate", fake_rate)

    class _Bot:
        def __init__(self):
            self.edits = []

        async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode=None):
            self.edits.append(
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "reply_markup": reply_markup,
                    "parse_mode": parse_mode,
                }
            )

    class _State:
        def __init__(self):
            self.data = {"lang": "en", "num_type": "voice", "country": "90", "state": "CA", "last_msg_id": 51}
            self.last_state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, state):
            self.last_state = state

    bot = _Bot()
    state = _State()

    await core_numbers._load_service_prices(123, bot, state, "gmail")

    assert calls == [("gmail", "1", "none", True)]
    assert state.data["country"] == "1"
    assert state.data["state"] == "none"
    assert state.last_state == core_numbers.NumberFlow.confirm_buy
    assert "Country: United States" in bot.edits[-1]["text"]
    assert "State:" not in bot.edits[-1]["text"]


@pytest.mark.asyncio
async def test_rental_add_number_returns_to_number_type_selection():
    class _Message:
        def __init__(self):
            self.message_id = 45
            self.edits = []

        async def edit_text(self, text, reply_markup=None, parse_mode=None):
            self.edits.append((text, reply_markup, parse_mode))
            return self

    class _State:
        def __init__(self):
            self.data = {"lang": "en", "num_type": "rental", "service": "telegram", "country": "1"}
            self.last_state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, state):
            self.last_state = state

    callback = type("CB", (), {"data": "flow:rental:add", "message": _Message()})()
    state = _State()

    await core_numbers.rental_add_number(callback, state)

    assert state.last_state == core_numbers.NumberFlow.num_type
    assert state.data["num_type"] is None
    assert state.data["service"] is None
    text, markup, parse_mode = callback.message.edits[0]
    assert text == core_numbers.t("en", "choose_number_type")
    assert parse_mode is None
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert callbacks == ["flow:type:temp", "flow:type:rental", "flow:type:voice"]


def test_my_numbers_only_lists_provisioned_successful_numbers():
    assert core_numbers_buy._is_manageable_my_number(
        {
            "number_mode": "temp",
            "status": "success",
            "provisioning_state": "provisioned",
            "provider_order_id": "act-1",
            "provider_number": "+15550001111",
        }
    )
    assert not core_numbers_buy._is_manageable_my_number(
        {
            "number_mode": "temp",
            "status": "paid",
            "provisioning_state": "charged_pending_provider",
            "provider_order_id": "act-1",
            "provider_number": "+15550001111",
        }
    )
    assert not core_numbers_buy._is_manageable_my_number(
        {
            "number_mode": "temp",
            "status": "success",
            "provisioning_state": "provider_failed_refunded",
            "provider_order_id": "act-1",
            "provider_number": "+15550001111",
        }
    )
    assert not core_numbers_buy._is_manageable_my_number(
        {
            "number_mode": "rental",
            "status": "success",
            "provisioning_state": "provisioned",
            "provider_order_id": "rent-1",
            "provider_number": "",
        }
    )


def test_temp_resend_stays_available_for_my_numbers_retention():
    now = datetime.now(UTC)
    valid_order = {
        "number_mode": "temp",
        "status": "success",
        "provisioning_state": "provisioned",
        "provider_order_id": "act-1",
        "provider_number": "+15550001111",
        "created_at": now - timedelta(hours=2),
        "temp_reuse_warranty_until": now - timedelta(minutes=90),
    }
    expired_order = {**valid_order, "created_at": now - timedelta(days=6)}

    assert core_numbers_buy._temp_resend_available(valid_order)
    assert not core_numbers_buy._temp_resend_available(expired_order)
