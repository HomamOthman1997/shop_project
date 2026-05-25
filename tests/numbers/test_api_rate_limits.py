import pytest

from services.platform import api_rate_limits
from services.platform.api_auth import ApiAuthContext


class FakeRateLimitCollection:
    def __init__(self, count):
        self.count = count
        self.calls = []

    async def find_one_and_update(self, query, update, **kwargs):
        self.calls.append({"query": query, "update": update, "kwargs": kwargs})
        return {"count": self.count}


class FakeDb:
    def __init__(self, count):
        self.api_rate_limits = FakeRateLimitCollection(count)


def auth_context(scopes=("numbers:quotes",)):
    return ApiAuthContext(key_id="key-1", user_id=123, reseller_id=456, scopes=scopes)


@pytest.mark.asyncio
async def test_check_api_rate_limit_allows_under_limit(monkeypatch):
    fake_db = FakeDb(count=7)
    monkeypatch.setattr(api_rate_limits, "db", fake_db)
    monkeypatch.setattr(api_rate_limits.time, "time", lambda: 1001)

    decision = await api_rate_limits.check_api_rate_limit(
        auth_context(),
        bucket="numbers:quotes",
        limit=10,
        window_seconds=60,
    )

    assert decision.remaining == 3
    assert decision.reset_at == 1020
    call = fake_db.api_rate_limits.calls[0]
    assert call["query"]["_id"] == "api:key-1:numbers:quotes:960"
    assert call["update"]["$inc"] == {"count": 1}


@pytest.mark.asyncio
async def test_check_api_rate_limit_raises_over_limit(monkeypatch):
    monkeypatch.setattr(api_rate_limits, "db", FakeDb(count=11))
    monkeypatch.setattr(api_rate_limits.time, "time", lambda: 1001)

    with pytest.raises(api_rate_limits.ApiRateLimitExceeded) as exc:
        await api_rate_limits.check_api_rate_limit(
            auth_context(),
            bucket="numbers:quotes",
            limit=10,
            window_seconds=60,
        )

    assert exc.value.decision.remaining == 0


@pytest.mark.asyncio
async def test_check_api_rate_limit_skips_super_keys(monkeypatch):
    fake_db = FakeDb(count=99)
    monkeypatch.setattr(api_rate_limits, "db", fake_db)
    monkeypatch.setattr(api_rate_limits.time, "time", lambda: 1001)

    decision = await api_rate_limits.check_api_rate_limit(
        auth_context(scopes=("*",)),
        bucket="numbers:quotes",
        limit=10,
        window_seconds=60,
    )

    assert decision.remaining == 10
    assert fake_db.api_rate_limits.calls == []
