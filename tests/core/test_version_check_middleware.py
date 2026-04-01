import pytest
from aiogram import types

from middlewares.version_check import VersionCheckMiddleware


@pytest.mark.asyncio
async def test_version_check_skips_mongo_when_redis_cache_hits(monkeypatch):
    middleware = VersionCheckMiddleware()
    state = {"ram": None}
    calls = {"mongo": 0, "redis": 0}

    def _get_ram_cached_user(user_id, now):
        return state["ram"]

    async def _get_redis_cached_user(user_id, now):
        calls["redis"] += 1
        return {"language": "en", "bot_version": 1}

    def _set_ram_cached_user(user_id, user, now):
        state["ram"] = dict(user)

    async def _set_redis_cached_user(user_id, user, now):
        return None

    async def _get_user(user_id):
        calls["mongo"] += 1
        return {"language": "en", "bot_version": 1}

    async def _handler(event, data):
        return "ok"

    monkeypatch.setattr("middlewares.version_check.get_ram_cached_user", _get_ram_cached_user)
    monkeypatch.setattr("middlewares.version_check.get_redis_cached_user", _get_redis_cached_user)
    monkeypatch.setattr("middlewares.version_check.set_ram_cached_user", _set_ram_cached_user)
    monkeypatch.setattr("middlewares.version_check.set_redis_cached_user", _set_redis_cached_user)
    monkeypatch.setattr("middlewares.version_check.get_user", _get_user)
    monkeypatch.setattr("middlewares.version_check.settings.bot_version", 1)

    event = types.Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "from": {"id": 123, "is_bot": False, "first_name": "U"},
            "text": "hello",
        }
    )

    result = await middleware(_handler, event, {})

    assert result == "ok"
    assert calls["redis"] == 1
    assert calls["mongo"] == 0
