from __future__ import annotations

import json

import pytest
from aiohttp.test_utils import make_mocked_request

from services.numbers import api
from services.platform.api_auth import ApiAuthContext
from services.platform.api_rate_limits import ApiRateLimitDecision


async def allow_rate_limit(auth, *, bucket, limit, window_seconds=60):
    return ApiRateLimitDecision(bucket=bucket, limit=limit, remaining=limit - 1, reset_at=9999999999, window_seconds=60)


@pytest.mark.asyncio
async def test_list_provider_webhook_audit_events(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return ApiAuthContext(key_id="support", user_id=1, reseller_id=1, scopes=("numbers:support:review",))

    async def fake_list_provider_webhook_events(**kwargs):
        calls["list"] = kwargs
        return [
            {
                "id": "evt-1",
                "provider": "pvadeals",
                "status": "unmatched",
                "provider_order_id": "req-1",
            }
        ]

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "list_provider_webhook_events", fake_list_provider_webhook_events)
    request = make_mocked_request("GET", "/api/v1/numbers/ops/provider-webhook-events?provider=pvadeals&status=unmatched&limit=25")

    response = await api.list_provider_webhook_audit_events(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth_scope"] == "numbers:support:review"
    assert calls["list"] == {"provider": "pvadeals", "status": "unmatched", "limit": 25}
    assert payload["events"][0]["id"] == "evt-1"
    assert response.headers["X-RateLimit-Bucket"] == "numbers:support:review"


@pytest.mark.asyncio
async def test_replay_provider_webhook_audit_event(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return ApiAuthContext(key_id="support", user_id=1, reseller_id=1, scopes=("numbers:support:review",))

    async def fake_replay_provider_webhook_event(event_id):
        calls["replay"] = event_id
        return {"ok": True, "reason": "code_received", "event": {"id": event_id, "replay_status": "processed"}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "replay_provider_webhook_event", fake_replay_provider_webhook_event)
    request = make_mocked_request(
        "POST",
        "/api/v1/numbers/ops/provider-webhook-events/evt-1/replay",
        match_info={"event_id": "evt-1"},
    )

    response = await api.replay_provider_webhook_audit_event(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth_scope"] == "numbers:support:review"
    assert calls["replay"] == "evt-1"
    assert payload["event"]["replay_status"] == "processed"


@pytest.mark.asyncio
async def test_replay_provider_webhook_audit_event_handles_missing(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return ApiAuthContext(key_id="support", user_id=1, reseller_id=1, scopes=("numbers:support:review",))

    async def fake_replay_provider_webhook_event(event_id):
        return {"ok": False, "reason": "event_not_found"}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "replay_provider_webhook_event", fake_replay_provider_webhook_event)
    request = make_mocked_request(
        "POST",
        "/api/v1/numbers/ops/provider-webhook-events/missing/replay",
        match_info={"event_id": "missing"},
    )

    response = await api.replay_provider_webhook_audit_event(request)
    payload = json.loads(response.text)

    assert response.status == 404
    assert payload["code"] == "event_not_found"
