import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())


@pytest.mark.asyncio
async def test_has_active_temp_order_only_counts_real_active_states(monkeypatch):
    from handlers import start

    seen_queries = []

    class _DummyOrders:
        async def find_one(self, query, projection):
            seen_queries.append(query)
            return None

    class _DummyDB:
        orders = _DummyOrders()

    monkeypatch.setattr(start, "db", _DummyDB())

    result = await start._has_active_temp_order(123)
    assert result is False
    assert seen_queries
    assert seen_queries[0]["temp_wait_state"]["$in"] == ["waiting", "code_received"]
    assert "created_at" in seen_queries[0]


@pytest.mark.asyncio
async def test_notify_active_temp_order_message_does_not_reference_missing_buttons(monkeypatch):
    from handlers import start

    class _DummyMessage:
        def __init__(self):
            self.from_user = type("U", (), {"id": 55})()
            self.answers = []

        async def answer(self, text, reply_markup=None):
            self.answers.append((text, reply_markup))

    async def _fake_has_temp(_user_id):
        return True

    async def _fake_has_rental(_user_id):
        return False

    async def _fake_show_notice(_message):
        return True

    monkeypatch.setattr(start, "_has_active_temp_order", _fake_has_temp)
    monkeypatch.setattr(start, "_has_active_rental_order", _fake_has_rental)
    monkeypatch.setattr(start, "_should_show_active_numbers_notice", _fake_show_notice)

    message = _DummyMessage()
    await start._notify_active_temp_order_if_any(message, "en")

    assert len(message.answers) == 1
    text, reply_markup = message.answers[0]
    assert "Use the buttons below" not in text
    assert "Tap Numbers below" in text
    assert reply_markup.inline_keyboard[0][0].callback_data == "flow:type:temp"


@pytest.mark.asyncio
async def test_notify_active_temp_order_skips_non_numbers_bots(monkeypatch):
    from handlers import start

    class _DummyMessage:
        def __init__(self):
            self.from_user = type("U", (), {"id": 55})()
            self.answers = []

        async def answer(self, text, reply_markup=None):
            self.answers.append((text, reply_markup))

    async def _fake_show_notice(_message):
        return False

    async def _fake_get_flags(_user_id):
        raise AssertionError("active number orders must not be queried for non-number bots")

    monkeypatch.setattr(start, "_should_show_active_numbers_notice", _fake_show_notice)
    monkeypatch.setattr(start, "_get_active_order_flags", _fake_get_flags)

    message = _DummyMessage()
    await start._notify_active_temp_order_if_any(message, "en")

    assert message.answers == []


@pytest.mark.asyncio
async def test_numbers_start_guards_skip_digital_and_card_bots(monkeypatch):
    from handlers import start

    async def _fake_is_digital(bot_id):
        return int(bot_id) == 10

    async def _fake_is_card(bot_id):
        return int(bot_id) == 20

    monkeypatch.setattr(start, "is_digital_products_bot", _fake_is_digital)
    monkeypatch.setattr(start, "is_card_ex_bot", _fake_is_card)

    assert await start._should_run_numbers_start_guards(10) is False
    assert await start._should_run_numbers_start_guards(20) is False
    assert await start._should_run_numbers_start_guards(30) is True


@pytest.mark.asyncio
async def test_open_numbers_start_menu_sets_number_type_state(monkeypatch):
    from handlers import start

    class _DummyState:
        def __init__(self):
            self.data = {}
            self.state = None

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, state):
            self.state = state

    class _DummyMessage:
        def __init__(self):
            self.from_user = type("U", (), {"id": 55})()
            self.answers = []
            self.stickers = []

        async def answer(self, text, reply_markup=None):
            self.answers.append((text, reply_markup))

        async def answer_sticker(self, sticker, reply_markup=None):
            self.stickers.append((sticker, reply_markup))

    message = _DummyMessage()
    state = _DummyState()

    await start._open_numbers_start_menu(message, state, lang="en")

    assert state.data["lang"] == "en"
    assert state.state.state == "NumberFlow:num_type"
    assert message.stickers
    assert message.answers == []
    assert message.stickers[0][1].inline_keyboard[0][0].callback_data == "flow:type:temp"
    assert all(row[0].callback_data != "flow:cancel" for row in message.stickers[0][1].inline_keyboard)


@pytest.mark.asyncio
async def test_numbers_bot_cancel_returns_to_number_type_entry(monkeypatch):
    from services.numbers.handlers import core_numbers

    async def fake_get_user(_user_id):
        return {"language": "en"}

    async def fake_true(_bot_id):
        return True

    async def fake_rental_guard(*_args, **_kwargs):
        return False

    class _DummyState:
        def __init__(self):
            self.data = {}
            self.cleared = False
            self.state = None

        async def clear(self):
            self.data.clear()
            self.cleared = True

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, state):
            self.state = state

    class _DummyMessage:
        def __init__(self):
            self.deleted = False
            self.answers = []
            self.stickers = []

        async def delete(self):
            self.deleted = True

        async def answer(self, text, reply_markup=None):
            self.answers.append((text, reply_markup))

        async def answer_sticker(self, sticker, reply_markup=None):
            self.stickers.append((sticker, reply_markup))

    class _DummyBot:
        async def get_me(self):
            return SimpleNamespace(id=879)

    message = _DummyMessage()
    callback = SimpleNamespace(from_user=SimpleNamespace(id=55), bot=_DummyBot(), message=message)
    state = _DummyState()

    monkeypatch.setattr(core_numbers, "get_user", fake_get_user)
    monkeypatch.setattr(core_numbers, "is_numbers_bot", fake_true)
    monkeypatch.setattr(core_numbers, "_handle_rental_exit_callback_guard", fake_rental_guard)

    await core_numbers.back_to_main(callback, state)

    assert state.cleared is True
    assert state.data["lang"] == "en"
    assert state.state.state == "NumberFlow:num_type"
    assert message.deleted is True
    assert message.stickers
    assert message.answers == []
    assert message.stickers[0][1].inline_keyboard[0][0].callback_data == "flow:type:temp"
