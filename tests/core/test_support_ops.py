import pytest

from services.platform import support_ops


@pytest.mark.asyncio
async def test_pay_ticket_bug_reward_credits_resolved_wallet_once(monkeypatch):
    ticket = {"_id": "ticket-1", "user_id": 7, "source_bot_id": 8}
    calls = {}

    async def begin(ticket_id, *, actor_id, amount):
        calls["begin"] = (ticket_id, actor_id, amount)
        return ticket

    async def scope(_ticket):
        return 9

    async def credit(*args, **kwargs):
        calls["credit"] = (args, kwargs)
        return {"_id": "ledger-1"}

    async def paid(*args, **kwargs):
        calls["paid"] = (args, kwargs)

    async def notify(_ticket, _text):
        return True

    monkeypatch.setattr(support_ops, "begin_support_ticket_bug_reward", begin)
    monkeypatch.setattr(support_ops, "resolve_ticket_wallet_scope", scope)
    monkeypatch.setattr(support_ops, "credit_user_wallet", credit)
    monkeypatch.setattr(support_ops, "mark_support_ticket_bug_reward_paid", paid)
    monkeypatch.setattr(support_ops, "send_ticket_message", notify)

    ok, reason, reward = await support_ops.pay_ticket_bug_reward(ticket, actor_id=11)

    assert ok
    assert reason == "paid"
    assert reward["wallet_scope_id"] == 9
    assert calls["credit"][0] == (7, 9, 1.0, "support_bug_reward")


@pytest.mark.asyncio
async def test_pay_ticket_bug_reward_rejects_paid_ticket(monkeypatch):
    ticket = {"_id": "ticket-1", "bug_reward": {"status": "paid"}}

    ok, reason, _ = await support_ops.pay_ticket_bug_reward(ticket, actor_id=11)

    assert not ok
    assert reason == "already_paid"
