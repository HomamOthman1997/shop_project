import os
import sys
from types import SimpleNamespace

import pytest
from aiogram import types

sys.path.insert(0, os.getcwd())

from middlewares.interaction_lock import InteractionLockMiddleware


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
