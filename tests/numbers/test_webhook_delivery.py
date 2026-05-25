from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from services.platform import webhook_delivery
from services.platform.webhooks import webhook_signature


@pytest.mark.asyncio
async def test_deliver_webhook_once_marks_success_and_sends_signed_body(monkeypatch):
    calls = {}

    async def fake_post(url, body, headers, timeout_sec):
        calls["url"] = url
        calls["body"] = body
        calls["headers"] = headers
        calls["timeout_sec"] = timeout_sec
        return 204, "ok"

    async def fake_success(**kwargs):
        calls["success"] = kwargs

    monkeypatch.setattr(webhook_delivery, "mark_webhook_delivery_success", fake_success)

    event = {"id": "evt_1", "type": "numbers.order.sms", "created_at": datetime.now(UTC).isoformat(), "data": {"code": "123456"}}
    result = await webhook_delivery.deliver_webhook_once(
        {
            "_id": "delivery-1",
            "url": "https://client.example/webhook",
            "secret": "whsec_test",
            "event": event,
            "attempts": 0,
        },
        post_fn=fake_post,
    )

    assert result == {"status": "delivered", "status_code": 204}
    assert calls["url"] == "https://client.example/webhook"
    assert json.loads(calls["body"].decode("utf-8")) == event
    assert calls["headers"]["X-Webhook-Event"] == "numbers.order.sms"
    assert calls["headers"]["X-Webhook-Id"] == "evt_1"
    assert calls["headers"]["X-Webhook-Signature"] == webhook_signature("whsec_test", event)
    assert calls["success"]["delivery_id"] == "delivery-1"
    assert calls["success"]["status_code"] == 204


@pytest.mark.asyncio
async def test_deliver_webhook_once_retries_5xx(monkeypatch):
    calls = {}

    async def fake_post(url, body, headers, timeout_sec):
        return 500, "server error"

    async def fake_failure(**kwargs):
        calls["failure"] = kwargs

    monkeypatch.setattr(webhook_delivery, "mark_webhook_delivery_failure", fake_failure)

    result = await webhook_delivery.deliver_webhook_once(
        {
            "_id": "delivery-2",
            "url": "https://client.example/webhook",
            "secret": "whsec_test",
            "event": {"id": "evt_2", "type": "numbers.order.created", "data": {}},
            "attempts": 1,
        },
        post_fn=fake_post,
        max_attempts=4,
    )

    assert result == {"status": "retry", "status_code": 500}
    assert calls["failure"]["delivery_id"] == "delivery-2"
    assert calls["failure"]["status_code"] == 500
    assert calls["failure"]["terminal"] is False
    assert calls["failure"]["next_attempt_at"] is not None


@pytest.mark.asyncio
async def test_deliver_webhook_once_terminal_failure_after_max_attempts(monkeypatch):
    calls = {}

    async def fake_post(url, body, headers, timeout_sec):
        return 404, "missing"

    async def fake_failure(**kwargs):
        calls["failure"] = kwargs

    monkeypatch.setattr(webhook_delivery, "mark_webhook_delivery_failure", fake_failure)

    result = await webhook_delivery.deliver_webhook_once(
        {
            "_id": "delivery-3",
            "url": "https://client.example/webhook",
            "secret": "whsec_test",
            "event": {"id": "evt_3", "type": "numbers.order.refunded", "data": {}},
            "attempts": 2,
        },
        post_fn=fake_post,
        max_attempts=3,
    )

    assert result == {"status": "failed", "status_code": 404}
    assert calls["failure"]["terminal"] is True
    assert calls["failure"]["next_attempt_at"] is None


@pytest.mark.asyncio
async def test_run_webhook_delivery_sweep_counts_results(monkeypatch):
    async def fake_due(**kwargs):
        return [
            {"_id": "delivery-1"},
            {"_id": "delivery-2"},
            {"_id": "delivery-3"},
        ]

    results = iter(
        [
            {"status": "delivered"},
            {"status": "retry"},
            {"status": "failed"},
        ]
    )

    async def fake_deliver_once(delivery, **kwargs):
        return next(results)

    monkeypatch.setattr(webhook_delivery, "list_due_webhook_deliveries", fake_due)
    monkeypatch.setattr(webhook_delivery, "deliver_webhook_once", fake_deliver_once)

    assert await webhook_delivery.run_webhook_delivery_sweep(limit=10) == {
        "checked": 3,
        "delivered": 1,
        "retry": 1,
        "failed": 1,
    }
