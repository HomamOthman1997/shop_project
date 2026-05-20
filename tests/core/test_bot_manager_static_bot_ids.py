import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

import bot_manager


@pytest.mark.asyncio
async def test_digital_products_bot_id_comes_from_token_without_get_me(monkeypatch):
    bot_manager._cached_digital_products_bot_id = None
    monkeypatch.setattr(bot_manager.settings, "bot_digital_products_token", "123456789:token", raising=False)

    def _unexpected_bot(*_args, **_kwargs):
        raise AssertionError("Bot.get_me fallback should not be needed for standard bot tokens")

    monkeypatch.setattr(bot_manager, "Bot", _unexpected_bot)

    assert await bot_manager._resolve_digital_products_bot_id() == 123456789


@pytest.mark.asyncio
async def test_platform_static_bot_ids_are_cached_from_token(monkeypatch):
    bot_manager._cached_main_bot_id = None
    bot_manager._cached_numbers_bot_id = None
    bot_manager._cached_admin_bot_id = None
    bot_manager._cached_card_ex_bot_id = None

    monkeypatch.setattr(bot_manager.settings, "bot_main_token", "111:main", raising=False)
    monkeypatch.setattr(bot_manager.settings, "bot_numbers_token", "222:numbers", raising=False)
    monkeypatch.setattr(bot_manager.settings, "bot_admin_token", "333:admin", raising=False)
    monkeypatch.setattr(bot_manager.settings, "bot_card_ex_token", "444:card", raising=False)

    def _unexpected_bot(*_args, **_kwargs):
        raise AssertionError("Bot.get_me fallback should not be needed for standard bot tokens")

    monkeypatch.setattr(bot_manager, "Bot", _unexpected_bot)

    assert await bot_manager._resolve_main_bot_id() == 111
    assert await bot_manager._resolve_numbers_bot_id() == 222
    assert await bot_manager._resolve_admin_bot_id() == 333
    assert await bot_manager._resolve_card_ex_bot_id() == 444
