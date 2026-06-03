import os
import sys

import pytest

sys.path.insert(0, os.getcwd())


class _FakeAggregate:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length=None):
        return list(self.rows)


class _FakeTempNumberEvents:
    def __init__(self, rows):
        self.rows = rows
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return _FakeAggregate(self.rows)


class _FakeDb:
    def __init__(self, rows):
        self.temp_number_events = _FakeTempNumberEvents(rows)


@pytest.mark.asyncio
async def test_provider_success_rates_count_monitor_recovery_events(monkeypatch):
    from database import temp_number_stats_repo

    fake_db = _FakeDb(
        [
            {
                "_id": "alpha",
                "attempts": 4,
                "successes": 2,
                "failed": 1,
            }
        ]
    )
    monkeypatch.setattr(temp_number_stats_repo, "db", fake_db)

    result = await temp_number_stats_repo.get_provider_success_rates(
        service_id="whatsapp",
        providers=["alpha"],
        min_attempts=1,
    )

    group_stage = fake_db.temp_number_events.pipeline[1]["$group"]
    got_code_events = group_stage["got_code"]["$max"]["$cond"][0]["$in"][1]
    failed_events = group_stage["failed_no_code"]["$max"]["$cond"][0]["$in"][1]

    assert "code_received_recovery" in got_code_events
    assert "guard_sms_detected" in got_code_events
    assert "wait_timeout" in failed_events
    assert result["alpha"]["success_rate"] == 50.0
    assert result["alpha"]["failed"] == 1
