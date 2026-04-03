import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

from utils.bot_kind_filter import BotKindFilter
from utils import bot_kind_filter


@pytest.mark.asyncio
async def test_bot_kind_filter_accepts_matching_kind(monkeypatch):
    async def _digital(_bot):
        return "digital"

    monkeypatch.setattr(bot_kind_filter, "resolve_bot_kind", _digital)
    flt = BotKindFilter("digital")

    assert await flt(SimpleNamespace(), SimpleNamespace()) is True


@pytest.mark.asyncio
async def test_bot_kind_filter_rejects_other_kind(monkeypatch):
    async def _main(_bot):
        return "main"

    monkeypatch.setattr(bot_kind_filter, "resolve_bot_kind", _main)
    flt = BotKindFilter("digital", "card")

    assert await flt(SimpleNamespace(), SimpleNamespace()) is False
