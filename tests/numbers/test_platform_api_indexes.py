import pytest

from database import platform_api_repo


class FakeCollection:
    def __init__(self):
        self.calls = []

    async def create_index(self, keys, **kwargs):
        self.calls.append((keys, kwargs))


class FakeDb:
    def __init__(self):
        self.api_keys = FakeCollection()
        self.api_rate_limits = FakeCollection()
        self.numbers_api_idempotency_keys = FakeCollection()


@pytest.mark.asyncio
async def test_bootstrap_platform_api_indexes(monkeypatch):
    fake_db = FakeDb()
    monkeypatch.setattr(platform_api_repo, "db", fake_db)

    await platform_api_repo.bootstrap_platform_api_indexes()

    assert ("key_hash", {"unique": True, "background": True}) in fake_db.api_keys.calls
    assert ("expires_at", {"expireAfterSeconds": 0, "background": True}) in fake_db.api_rate_limits.calls
    assert (
        [("user_id", 1), ("key", 1), ("operation", 1)],
        {"unique": True, "background": True},
    ) in fake_db.numbers_api_idempotency_keys.calls
