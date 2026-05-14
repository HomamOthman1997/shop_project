import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

import handlers.verify_reseller as verify_reseller


@pytest.mark.asyncio
async def test_refresh_reply_keyboard_keeps_placeholder_message(monkeypatch):
    calls: list[tuple[str, object]] = []

    class FakeBot:
        async def delete_message(self, **kwargs):
            calls.append(("delete", kwargs))

    async def fake_send_message(**kwargs):
        calls.append(("send", kwargs))
        return type("Msg", (), {"message_id": 123})()

    monkeypatch.setattr(verify_reseller, "_safe_bot_send_message", fake_send_message)

    await verify_reseller._refresh_reply_keyboard(
        bot=FakeBot(),
        chat_id=555,
        reply_markup=verify_reseller._phone_request_kb("ar"),
    )

    assert calls
    assert calls[0][0] == "send"
    assert all(kind != "delete" for kind, _ in calls)


@pytest.mark.asyncio
async def test_channel_picker_keyboard_is_visible_and_persistent(monkeypatch):
    calls: list[tuple[str, object]] = []

    class FakeState:
        def __init__(self):
            self.data = {}

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

    class FakeBot:
        async def delete_message(self, **kwargs):
            calls.append(("delete", kwargs))

    async def fake_send_message(**kwargs):
        calls.append(("send", kwargs))
        return type("Msg", (), {"message_id": 456})()

    monkeypatch.setattr(verify_reseller, "_safe_bot_send_message", fake_send_message)

    state = FakeState()
    await verify_reseller._show_channel_picker_prompt(FakeBot(), 555, state, "en")

    send = next(payload for kind, payload in calls if kind == "send")
    assert "Tap Add Your Channel" in send["text"]
    markup = send["reply_markup"]
    assert markup.is_persistent is True
    assert markup.one_time_keyboard is False
    assert markup.keyboard[0][0].text == "Add Your Channel"
    assert state.data["verify_reply_kb_anchor_msg_id"] == 456
