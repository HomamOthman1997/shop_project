import os
import sys

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

    monkeypatch.setattr(start, "_has_active_temp_order", _fake_has_temp)
    monkeypatch.setattr(start, "_has_active_rental_order", _fake_has_rental)

    message = _DummyMessage()
    await start._notify_active_temp_order_if_any(message, "en")

    assert len(message.answers) == 1
    text, reply_markup = message.answers[0]
    assert "Use the buttons below" not in text
    assert "Tap Numbers below" in text
    assert reply_markup.inline_keyboard[0][0].callback_data == "flow:type:temp"
