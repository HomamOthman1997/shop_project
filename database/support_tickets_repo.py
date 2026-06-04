from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument

from database.mongo import db


SUPPORT_TICKET_OPEN_STATUSES = {"open", "awaiting_user", "awaiting_admin", "replied"}
SUPPORT_TICKET_MAX_OPEN_PER_USER = 5
SUPPORT_TICKET_AUTO_SOLVE_AFTER = timedelta(days=3)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_object_id(ticket_id: str | ObjectId) -> ObjectId:
    if isinstance(ticket_id, ObjectId):
        return ticket_id
    return ObjectId(str(ticket_id))


async def create_support_ticket(
    *,
    scope: str,
    owner_id: int | None,
    source_bot_id: int,
    chat_id: int,
    user_id: int,
    username: str | None,
    full_name: str | None,
    category: str,
    payload_count: int,
) -> dict[str, Any]:
    now = _now()
    counter_key = f"support_ticket_seq:{scope}:{int(owner_id or 0)}"
    seq_row = await db.counters.find_one_and_update(
        {"_id": counter_key},
        {"$inc": {"value": 1}, "$set": {"updated_at": now}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    ticket_no = int((seq_row or {}).get("value") or 1)
    doc: dict[str, Any] = {
        "scope": str(scope),
        "owner_id": int(owner_id) if owner_id is not None else None,
        "source_bot_id": int(source_bot_id),
        "chat_id": int(chat_id),
        "user_id": int(user_id),
        "username": str(username or "").strip(),
        "full_name": str(full_name or "").strip(),
        "category": str(category).strip().lower(),
        "status": "open",
        "ticket_no": ticket_no,
        "payload_count": int(payload_count),
        "opened_at": now,
        "updated_at": now,
    }
    result = await db.support_tickets.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def set_ticket_delivery(
    ticket_id: str | ObjectId,
    *,
    target_chat_id: int,
    target_thread_id: int | None,
    header_message_id: int | None,
) -> None:
    await db.support_tickets.update_one(
        {"_id": _as_object_id(ticket_id)},
        {
            "$set": {
                "delivery.chat_id": int(target_chat_id),
                "delivery.message_thread_id": int(target_thread_id) if target_thread_id is not None else None,
                "delivery.header_message_id": int(header_message_id) if header_message_id is not None else None,
                "updated_at": _now(),
            }
        },
    )


async def get_support_ticket(ticket_id: str | ObjectId) -> dict[str, Any] | None:
    return await db.support_tickets.find_one({"_id": _as_object_id(ticket_id)})


async def mark_support_ticket_replied(ticket_id: str | ObjectId, *, actor_id: int) -> None:
    await db.support_tickets.update_one(
        {"_id": _as_object_id(ticket_id)},
        {
            "$set": {
                "status": "replied",
                "last_reply_by": int(actor_id),
                "last_reply_at": _now(),
                "updated_at": _now(),
            }
        },
    )


async def mark_support_ticket_solved(ticket_id: str | ObjectId, *, actor_id: int) -> None:
    await db.support_tickets.update_one(
        {"_id": _as_object_id(ticket_id)},
        {
            "$set": {
                "status": "solved",
                "solved_by": int(actor_id),
                "solved_at": _now(),
                "updated_at": _now(),
            }
        },
    )


async def mark_support_ticket_bug_triage(ticket_id: str | ObjectId, *, actor_id: int, status: str) -> None:
    normalized = str(status or "").strip().lower()
    if normalized not in {"confirmed", "not_bug"}:
        raise ValueError("invalid bug triage status")
    await db.support_tickets.update_one(
        {"_id": _as_object_id(ticket_id)},
        {
            "$set": {
                "bug_triage.status": normalized,
                "bug_triage.marked_by": int(actor_id),
                "bug_triage.marked_at": _now(),
                "updated_at": _now(),
            }
        },
    )


async def begin_support_ticket_bug_reward(
    ticket_id: str | ObjectId,
    *,
    actor_id: int,
    amount: float = 1.0,
) -> dict[str, Any] | None:
    now = _now()
    return await db.support_tickets.find_one_and_update(
        {
            "_id": _as_object_id(ticket_id),
            "$or": [
                {"bug_reward.status": {"$exists": False}},
                {"bug_reward.status": {"$in": ["failed"]}},
            ],
        },
        {
            "$set": {
                "bug_reward.status": "processing",
                "bug_reward.amount": float(amount),
                "bug_reward.started_by": int(actor_id),
                "bug_reward.started_at": now,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )


async def mark_support_ticket_bug_reward_paid(
    ticket_id: str | ObjectId,
    *,
    actor_id: int,
    amount: float,
    wallet_scope_id: int,
    ledger_id: Any = None,
) -> None:
    now = _now()
    payload: dict[str, Any] = {
        "bug_reward.status": "paid",
        "bug_reward.amount": float(amount),
        "bug_reward.wallet_scope_id": int(wallet_scope_id),
        "bug_reward.paid_by": int(actor_id),
        "bug_reward.paid_at": now,
        "updated_at": now,
    }
    if ledger_id is not None:
        payload["bug_reward.ledger_id"] = str(ledger_id)
    await db.support_tickets.update_one({"_id": _as_object_id(ticket_id)}, {"$set": payload})


async def mark_support_ticket_bug_reward_failed(
    ticket_id: str | ObjectId,
    *,
    actor_id: int,
    error: str,
) -> None:
    now = _now()
    await db.support_tickets.update_one(
        {"_id": _as_object_id(ticket_id)},
        {
            "$set": {
                "bug_reward.status": "failed",
                "bug_reward.failed_by": int(actor_id),
                "bug_reward.failed_at": now,
                "bug_reward.error": str(error or "")[:300],
                "updated_at": now,
            }
        },
    )


async def has_open_support_ticket(
    *,
    scope: str,
    owner_id: int | None,
    user_id: int,
    category: str,
) -> bool:
    return await has_reached_open_support_ticket_limit(
        scope=scope,
        owner_id=owner_id,
        user_id=user_id,
    )


async def has_reached_open_support_ticket_limit(
    *,
    scope: str,
    owner_id: int | None,
    user_id: int,
    limit: int = SUPPORT_TICKET_MAX_OPEN_PER_USER,
) -> bool:
    await solve_stale_open_support_tickets(scope=scope, owner_id=owner_id, user_id=user_id)
    query: dict[str, Any] = {
        "scope": str(scope),
        "owner_id": int(owner_id) if owner_id is not None else None,
        "user_id": int(user_id),
        "status": {"$in": sorted(SUPPORT_TICKET_OPEN_STATUSES)},
    }
    count = await db.support_tickets.count_documents(query)
    return int(count or 0) >= max(1, int(limit or SUPPORT_TICKET_MAX_OPEN_PER_USER))


async def solve_stale_open_support_tickets(
    *,
    scope: str,
    owner_id: int | None,
    user_id: int,
) -> int:
    now = _now()
    cutoff = now - SUPPORT_TICKET_AUTO_SOLVE_AFTER
    result = await db.support_tickets.update_many(
        {
            "scope": str(scope),
            "owner_id": int(owner_id) if owner_id is not None else None,
            "user_id": int(user_id),
            "status": {"$in": sorted(SUPPORT_TICKET_OPEN_STATUSES)},
            "opened_at": {"$lte": cutoff},
        },
        {
            "$set": {
                "status": "solved",
                "solved_by": 0,
                "solved_at": now,
                "solved_reason": "auto_stale_3d",
                "updated_at": now,
            }
        },
    )
    return int(getattr(result, "modified_count", 0) or 0)
