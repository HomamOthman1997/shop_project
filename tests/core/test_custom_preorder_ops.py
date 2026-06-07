import pytest

from services.platform import custom_preorder_ops


@pytest.mark.asyncio
async def test_fulfill_preorder_enforces_fifo(monkeypatch):
    row = {"_id": "newer", "status": "pending", "endpoint_id": "endpoint-1"}

    async def get_preorder(_preorder_id):
        return row

    async def next_pending(_endpoint_id):
        return {"_id": "older"}

    monkeypatch.setattr(custom_preorder_ops, "get_preorder_request", get_preorder)
    monkeypatch.setattr(custom_preorder_ops, "get_next_pending_preorder", next_pending)

    ok, reason, _ = await custom_preorder_ops.fulfill_preorder_from_owner(
        "newer",
        actor_id=7,
        delivery_text="CODE-123",
    )

    assert not ok
    assert reason == "fifo_violation"


@pytest.mark.asyncio
async def test_fulfill_preorder_does_not_complete_when_delivery_fails(monkeypatch):
    row = {
        "_id": "pre-1",
        "status": "pending",
        "endpoint_id": "endpoint-1",
        "source_bot_id": 5,
        "buyer_user_id": 8,
    }
    completed = False

    async def get_preorder(_preorder_id):
        return row

    async def next_pending(_endpoint_id):
        return row

    async def claim(_preorder_id, *, actor_id):
        return {**row, "status": "fulfilling", "fulfilling_by": actor_id}

    async def deliver(**_kwargs):
        return False

    async def complete(*_args, **_kwargs):
        nonlocal completed
        completed = True

    monkeypatch.setattr(custom_preorder_ops, "get_preorder_request", get_preorder)
    monkeypatch.setattr(custom_preorder_ops, "get_next_pending_preorder", next_pending)
    monkeypatch.setattr(custom_preorder_ops, "mark_preorder_fulfilling", claim)
    monkeypatch.setattr(custom_preorder_ops, "send_source_bot_message", deliver)
    monkeypatch.setattr(custom_preorder_ops, "mark_preorder_fulfilled", complete)

    ok, reason, _ = await custom_preorder_ops.fulfill_preorder_from_owner(
        "pre-1",
        actor_id=7,
        delivery_text="CODE-123",
    )

    assert not ok
    assert reason == "delivery_failed"
    assert not completed


@pytest.mark.asyncio
async def test_fulfill_preorder_attachment_completes_after_delivery(monkeypatch):
    row = {
        "_id": "pre-1",
        "status": "fulfilling",
        "source_bot_id": 5,
        "buyer_user_id": 8,
        "order_id": "order-1",
    }
    details = {}

    async def get_preorder(_preorder_id):
        return row

    async def deliver(_ticket, **kwargs):
        assert kwargs["content"] == b"file"
        return True, "document"

    async def complete(_preorder_id, *, actor_id):
        return {**row, "status": "fulfilled", "fulfilled_by": actor_id}

    async def update_details(_order_id, payload):
        details.update(payload)

    async def update_status(*_args):
        return None

    monkeypatch.setattr(custom_preorder_ops, "get_preorder_request", get_preorder)
    monkeypatch.setattr(custom_preorder_ops, "send_ticket_attachment", deliver)
    monkeypatch.setattr(custom_preorder_ops, "mark_preorder_fulfilled", complete)
    monkeypatch.setattr(custom_preorder_ops, "update_order_details", update_details)
    monkeypatch.setattr(custom_preorder_ops, "update_order_status", update_status)

    ok, reason, _ = await custom_preorder_ops.fulfill_preorder_attachment_from_owner(
        "pre-1",
        actor_id=7,
        content=b"file",
        filename="code.txt",
        content_type="text/plain",
    )

    assert ok
    assert reason == "fulfilled"
    assert details["custom_preorder_delivery_kind"] == "document"
    assert details["custom_preorder_delivery_filename"] == "code.txt"


@pytest.mark.asyncio
async def test_reject_preorder_refunds_and_closes_order(monkeypatch):
    row = {
        "_id": "pre-1",
        "status": "pending",
        "order_id": "order-1",
        "buyer_user_id": 8,
        "wallet_scope_id": 9,
        "total_price": 4.5,
        "source_bot_id": 5,
    }
    calls = []

    async def get_preorder(_preorder_id):
        return row

    async def refunding(_preorder_id, *, actor_id):
        return {**row, "status": "refunding", "actor_id": actor_id}

    async def refund(*_args, **_kwargs):
        return True, "ok"

    async def rejected(_preorder_id, *, actor_id, reason):
        return {**row, "status": "rejected", "actor_id": actor_id, "reason": reason}

    async def details(*args):
        calls.append(("details", args))

    async def status(*args):
        calls.append(("status", args))

    async def deliver(**_kwargs):
        return True

    monkeypatch.setattr(custom_preorder_ops, "get_preorder_request", get_preorder)
    monkeypatch.setattr(custom_preorder_ops, "mark_preorder_refunding", refunding)
    monkeypatch.setattr(custom_preorder_ops.FinancialManager, "refund_custom_purchase", refund)
    monkeypatch.setattr(custom_preorder_ops, "mark_preorder_rejected", rejected)
    monkeypatch.setattr(custom_preorder_ops, "update_order_details", details)
    monkeypatch.setattr(custom_preorder_ops, "update_order_status", status)
    monkeypatch.setattr(custom_preorder_ops, "send_source_bot_message", deliver)

    ok, reason, result = await custom_preorder_ops.reject_preorder_from_owner(
        "pre-1",
        actor_id=7,
        reason="Unavailable",
    )

    assert ok
    assert reason == "rejected"
    assert result["status"] == "rejected"
    assert calls[-1] == ("status", ("order-1", "refunded"))
