from datetime import UTC, datetime

import pytest

from database import support_tickets_repo


class _UpdateResult:
    def __init__(self, modified_count: int = 0):
        self.modified_count = modified_count


class _FakeSupportTickets:
    def __init__(self, *, count: int = 0, modified_count: int = 0):
        self.count = count
        self.modified_count = modified_count
        self.update_query = None
        self.update_patch = None
        self.count_query = None

    async def update_many(self, query, patch):
        self.update_query = query
        self.update_patch = patch
        return _UpdateResult(self.modified_count)

    async def count_documents(self, query):
        self.count_query = query
        return self.count


class _FakeDB:
    def __init__(self, tickets: _FakeSupportTickets):
        self.support_tickets = tickets


@pytest.mark.asyncio
async def test_support_ticket_limit_allows_fewer_than_five_open_tickets(monkeypatch):
    tickets = _FakeSupportTickets(count=4)
    monkeypatch.setattr(support_tickets_repo, "db", _FakeDB(tickets))

    reached = await support_tickets_repo.has_reached_open_support_ticket_limit(
        scope="platform",
        owner_id=None,
        user_id=123,
    )

    assert reached is False
    assert tickets.count_query["user_id"] == 123
    assert "category" not in tickets.count_query


@pytest.mark.asyncio
async def test_support_ticket_limit_blocks_five_open_tickets(monkeypatch):
    tickets = _FakeSupportTickets(count=5)
    monkeypatch.setattr(support_tickets_repo, "db", _FakeDB(tickets))

    reached = await support_tickets_repo.has_reached_open_support_ticket_limit(
        scope="platform",
        owner_id=None,
        user_id=123,
    )

    assert reached is True


@pytest.mark.asyncio
async def test_support_ticket_limit_auto_solves_stale_open_tickets_before_count(monkeypatch):
    tickets = _FakeSupportTickets(count=0, modified_count=2)
    now = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(support_tickets_repo, "db", _FakeDB(tickets))
    monkeypatch.setattr(support_tickets_repo, "_now", lambda: now)

    reached = await support_tickets_repo.has_reached_open_support_ticket_limit(
        scope="platform",
        owner_id=None,
        user_id=123,
    )

    assert reached is False
    assert tickets.update_query["opened_at"]["$lte"] == now - support_tickets_repo.SUPPORT_TICKET_AUTO_SOLVE_AFTER
    assert tickets.update_patch["$set"]["status"] == "solved"
    assert tickets.update_patch["$set"]["solved_reason"] == "auto_stale_3d"
