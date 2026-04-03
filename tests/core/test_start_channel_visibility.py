import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

import handlers.start as start_handler


@pytest.mark.asyncio
async def test_channel_setup_warning_hidden_for_normal_user(monkeypatch):
    monkeypatch.setattr(start_handler, "settings", SimpleNamespace(owner_id=999))

    async def fake_is_reseller(_user_id, *, bot_id):
        assert bot_id == 123
        return False

    monkeypatch.setattr(start_handler, "is_reseller", fake_is_reseller)

    result = await start_handler._should_show_channel_setup_warning(
        user_id=111,
        bot_id=123,
        inferred_reseller_id=555,
    )

    assert result is False


@pytest.mark.asyncio
async def test_channel_setup_warning_visible_for_bot_owner(monkeypatch):
    monkeypatch.setattr(start_handler, "settings", SimpleNamespace(owner_id=999))

    async def fake_is_reseller(_user_id, *, bot_id):
        assert bot_id == 123
        return False

    monkeypatch.setattr(start_handler, "is_reseller", fake_is_reseller)

    result = await start_handler._should_show_channel_setup_warning(
        user_id=555,
        bot_id=123,
        inferred_reseller_id=555,
    )

    assert result is True
