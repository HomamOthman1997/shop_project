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
