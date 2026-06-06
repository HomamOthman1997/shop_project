import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

import database.lifecycle_repo as lifecycle_repo


class _DeleteResult:
    def __init__(self, count):
        self.deleted_count = count


class _EmptyCursor:
    def sort(self, *_args):
        return self

    def limit(self, *_args):
        return self

    async def to_list(self, *_args, **_kwargs):
        return []


class _FakeCollection:
    def __init__(self, delete_count=0):
        self.delete_count = delete_count
        self.delete_queries = []

    async def delete_many(self, query):
        self.delete_queries.append(query)
        return _DeleteResult(self.delete_count)

    async def create_index(self, *_args, **_kwargs):
        return None

    def find(self, *_args, **_kwargs):
        return _EmptyCursor()

    async def update_one(self, *_args, **_kwargs):
        return None


class _FakeDb:
    def __init__(self):
        self.proxy_events = _FakeCollection(1)
        self.number_order_events = _FakeCollection(2)
        self.temp_number_events = _FakeCollection(3)
        self.provider_webhook_events = _FakeCollection(4)
        self.ops_validation_reports = _FakeCollection(5)
        self.digital_price_watch_runs = _FakeCollection(6)
        self.number_provider_purchase_blocks = _FakeCollection(7)
        self.usage_stats = _FakeCollection(8)
        self.orders_archive = _FakeCollection(9)
        self.orders = _FakeCollection()
        self.system_settings = _FakeCollection()


@pytest.mark.asyncio
async def test_lifecycle_cleanup_includes_operational_event_collections(monkeypatch):
    fake_db = _FakeDb()
    monkeypatch.setattr(lifecycle_repo, "db", fake_db)

    result = await lifecycle_repo.run_lifecycle_cleanup()

    assert result["temp_number_events_deleted"] == 3
    assert result["provider_webhook_events_deleted"] == 4
    assert result["ops_validation_reports_deleted"] == 5
    assert result["digital_price_watch_runs_deleted"] == 6
    assert result["expired_number_purchase_blocks_deleted"] == 7
    assert fake_db.number_provider_purchase_blocks.delete_queries[0].keys() == {"expires_at"}
