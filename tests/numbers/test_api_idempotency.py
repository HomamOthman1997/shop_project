import pytest

from services.platform import api_idempotency


class FakeCollection:
    def __init__(self):
        self.row = None
        self.update_call = None

    async def find_one(self, query):
        self.find_query = query
        return self.row

    async def update_one(self, query, update, *, upsert=False):
        self.update_call = {"query": query, "update": update, "upsert": upsert}


class FakeDb:
    def __init__(self):
        self.api_idempotency_keys = FakeCollection()


@pytest.mark.asyncio
async def test_get_idempotent_response_returns_saved_response(monkeypatch):
    fake_db = FakeDb()
    fake_db.api_idempotency_keys.row = {"response": {"ok": True}}
    monkeypatch.setattr(api_idempotency, "db", fake_db)

    response = await api_idempotency.get_idempotent_response(user_id=123, key="idem-1", operation="op")

    assert response == {"ok": True}
    assert fake_db.api_idempotency_keys.find_query == {"user_id": 123, "key": "idem-1", "operation": "op"}


@pytest.mark.asyncio
async def test_save_idempotent_response_upserts(monkeypatch):
    fake_db = FakeDb()
    monkeypatch.setattr(api_idempotency, "db", fake_db)

    await api_idempotency.save_idempotent_response(user_id=123, key="idem-1", operation="op", response={"ok": True})

    assert fake_db.api_idempotency_keys.update_call["query"] == {"user_id": 123, "key": "idem-1", "operation": "op"}
    assert fake_db.api_idempotency_keys.update_call["update"]["$set"]["response"] == {"ok": True}
    assert fake_db.api_idempotency_keys.update_call["upsert"] is True
