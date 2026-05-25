import pytest

from services.platform import webhooks


def test_webhook_signature_is_stable():
    event = {"type": "numbers.order.sms", "data": {"code": "123456"}}

    first = webhooks.webhook_signature("whsec_secret", event)
    second = webhooks.webhook_signature("whsec_secret", {"data": {"code": "123456"}, "type": "numbers.order.sms"})

    assert first == second
    assert first.startswith("sha256=")


@pytest.mark.asyncio
async def test_enqueue_event_for_user_queues_matching_hooks(monkeypatch):
    calls = []

    async def fake_active_webhooks_for_event(**kwargs):
        calls.append(("active", kwargs))
        return [{"_id": "hook-1", "user_id": 123, "reseller_id": 456, "url": "https://example.com", "secret": "s"}]

    async def fake_enqueue_webhook_delivery(**kwargs):
        calls.append(("enqueue", kwargs))
        return {"_id": "delivery-1"}

    monkeypatch.setattr(webhooks, "active_webhooks_for_event", fake_active_webhooks_for_event)
    monkeypatch.setattr(webhooks, "enqueue_webhook_delivery", fake_enqueue_webhook_delivery)

    result = await webhooks.enqueue_event_for_user(
        user_id=123,
        reseller_id=456,
        event_type="numbers.order.sms",
        data={"order": {"id": "order-1"}},
    )

    assert result == {"matched": 1, "queued": 1}
    assert calls[0] == (
        "active",
        {"user_id": 123, "reseller_id": 456, "event_type": "numbers.order.sms"},
    )
    assert calls[1][1]["event"]["type"] == "numbers.order.sms"
    assert calls[1][1]["event"]["data"] == {"order": {"id": "order-1"}}
