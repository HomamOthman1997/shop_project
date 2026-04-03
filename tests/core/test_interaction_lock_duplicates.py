import os
import sys
from types import SimpleNamespace

import pytest
from aiogram import types

sys.path.insert(0, os.getcwd())

from middlewares.interaction_lock import InteractionLockMiddleware
from utils.translations import t


@pytest.mark.asyncio
async def test_duplicate_callback_is_suppressed(monkeypatch):
    mw = InteractionLockMiddleware()
    called = {"count": 0}
    answers = {"count": 0}

    async def _fake_answer(self, *args, **kwargs):
        answers["count"] += 1
        return True

    monkeypatch.setattr(types.CallbackQuery, "answer", _fake_answer, raising=False)

    async def handler(_event, _data):
        called["count"] += 1
        return "ok"

    event = types.CallbackQuery(
        id="1",
        from_user=types.User(id=42, is_bot=False, first_name="T"),
        chat_instance="x",
        data="btn:test",
    )
    first = await mw(handler, event, {})
    second = await mw(handler, event, {})

    assert first == "ok"
    assert second is None
    assert called["count"] == 1
    assert answers["count"] >= 1


@pytest.mark.asyncio
async def test_top_level_menu_messages_bypass_message_window():
    mw = InteractionLockMiddleware()
    called = {"count": 0}

    async def handler(_event, _data):
        called["count"] += 1
        return "ok"

    event = types.Message(
        message_id=1,
        date=0,
        chat=types.Chat(id=100, type="private"),
        from_user=types.User(id=42, is_bot=False, first_name="T"),
        text=t("ar", "btn_custom_services"),
    )

    first = await mw(handler, event, {})
    second = await mw(handler, event, {})

    assert first == "ok"
    assert second == "ok"
    assert called["count"] == 2
