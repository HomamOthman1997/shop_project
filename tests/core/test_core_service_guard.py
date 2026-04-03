import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

from utils import core_service_guard


class _DummyMessage:
    def __init__(self):
        self.bot = SimpleNamespace()


class _DummyCallback:
    def __init__(self):
        self.bot = SimpleNamespace()


@pytest.mark.asyncio
async def test_guard_core_service_message_allows_platform_bots(monkeypatch):
    message = _DummyMessage()

    async def _true(*_args, **_kwargs):
        return True

    async def _false(*_args, **_kwargs):
        return False

    async def _bad(*_args, **_kwargs):
        raise AssertionError("reseller redirect path should not be reached for platform bots")

    monkeypatch.setattr(core_service_guard, "is_main_bot", _false)
    monkeypatch.setattr(core_service_guard, "is_digital_products_bot", _true)
    monkeypatch.setattr(core_service_guard, "is_card_ex_bot", _false)
    monkeypatch.setattr(core_service_guard, "_resolve_reseller_for_bot", _bad)
    monkeypatch.setattr(core_service_guard, "send_main_bot_message", _bad)

    assert await core_service_guard.guard_core_service_message(message, "ar") is True


@pytest.mark.asyncio
async def test_guard_core_service_callback_allows_platform_bots(monkeypatch):
    callback = _DummyCallback()

    async def _true(*_args, **_kwargs):
        return True

    async def _false(*_args, **_kwargs):
        return False

    async def _bad(*_args, **_kwargs):
        raise AssertionError("reseller redirect path should not be reached for platform bots")

    monkeypatch.setattr(core_service_guard, "is_main_bot", _false)
    monkeypatch.setattr(core_service_guard, "is_digital_products_bot", _false)
    monkeypatch.setattr(core_service_guard, "is_card_ex_bot", _true)
    monkeypatch.setattr(core_service_guard, "_resolve_reseller_for_bot", _bad)
    monkeypatch.setattr(core_service_guard, "send_main_bot_message", _bad)

    assert await core_service_guard.guard_core_service_callback(callback, "ar") is True
