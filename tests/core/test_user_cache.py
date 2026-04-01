import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(0, os.getcwd())

from utils.user_cache import (
    USER_CACHE_TTL,
    get_ram_cached_user,
    invalidate_ram_cached_user,
    set_ram_cached_user,
)


def test_ram_user_cache_respects_ttl():
    user_id = 101
    now = datetime.now(UTC)
    set_ram_cached_user(user_id, {"telegram_id": user_id, "banned": False}, now)

    assert get_ram_cached_user(user_id, now) is not None
    assert get_ram_cached_user(user_id, now + USER_CACHE_TTL + timedelta(seconds=1)) is None

    invalidate_ram_cached_user(user_id)


@pytest.mark.asyncio
async def test_user_repo_updates_invalidate_cache(monkeypatch):
    import database.user_repo as user_repo

    calls: list[tuple[int, dict]] = []

    class FakeUsers:
        async def update_one(self, query, payload):
            calls.append((query["telegram_id"], payload["$set"]))

    class FakeDB:
        users = FakeUsers()

    cleared: list[int] = []

    async def fake_invalidate(user_id: int):
        cleared.append(int(user_id))

    monkeypatch.setattr(user_repo, "db", FakeDB())
    monkeypatch.setattr(user_repo, "invalidate_user_cache", fake_invalidate)

    await user_repo.update_user_language(55, "ar")
    await user_repo.update_user_version(55, 9)
    await user_repo.ban_user(55)
    await user_repo.unban_user(55)

    assert calls == [
        (55, {"language": "ar"}),
        (55, {"bot_version": 9}),
        (55, {"banned": True}),
        (55, {"banned": False}),
    ]
    assert cleared == [55, 55, 55, 55]
