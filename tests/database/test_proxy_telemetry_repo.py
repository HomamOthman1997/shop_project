import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

import database.proxy_telemetry_repo as proxy_telemetry_repo


class _FakeCollection:
    def __init__(self):
        self.inserted = None

    async def insert_one(self, doc):
        self.inserted = doc


class _FakeDb:
    def __init__(self):
        self.proxy_events = _FakeCollection()


@pytest.mark.asyncio
async def test_record_proxy_event_redacts_nested_credentials(monkeypatch):
    fake_db = _FakeDb()
    monkeypatch.setattr(proxy_telemetry_repo, "db", fake_db)

    await proxy_telemetry_repo.record_proxy_event(
        event_type="rent_offer",
        provider="test",
        reason="failed username=alice password=hunter2",
        extra={
            "username": "alice",
            "nested": {"api_key": "key-123", "endpoint": "https://alice:hunter2@example.com/path"},
        },
    )

    inserted = fake_db.proxy_events.inserted
    assert inserted["extra"]["username"] == "[redacted]"
    assert inserted["extra"]["nested"]["api_key"] == "[redacted]"
    assert "hunter2" not in inserted["extra"]["nested"]["endpoint"]
    assert "alice" not in inserted["extra"]["nested"]["endpoint"]
    assert "hunter2" not in inserted["reason"]
    assert "alice" not in inserted["reason"]


@pytest.mark.asyncio
async def test_record_proxy_event_limits_large_provider_errors(monkeypatch):
    fake_db = _FakeDb()
    monkeypatch.setattr(proxy_telemetry_repo, "db", fake_db)

    await proxy_telemetry_repo.record_proxy_event(
        event_type="catalog_fetch",
        provider="test",
        reason="<html>" + ("x" * 1000),
        extra={"response": "y" * 1000},
    )

    inserted = fake_db.proxy_events.inserted
    assert len(inserted["reason"]) == 240
    assert len(inserted["extra"]["response"]) == 500
