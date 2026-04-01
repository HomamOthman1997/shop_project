from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument

from database.mongo import db


SUPPORT_TICKET_OPEN_STATUSES = {"open", "awaiting_user", "awaiting_admin", "replied"}


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


async def has_open_support_ticket(
    *,
    scope: str,
    owner_id: int | None,
    user_id: int,
    category: str,
) -> bool:
    query: dict[str, Any] = {
        "scope": str(scope),
        "owner_id": int(owner_id) if owner_id is not None else None,
        "user_id": int(user_id),
        "category": str(category).strip().lower(),
        "status": {"$in": sorted(SUPPORT_TICKET_OPEN_STATUSES)},
    }
    row = await db.support_tickets.find_one(query, {"_id": 1})
    return row is not None
