"""Direct owner↔customer conversations — one persistent chat thread per customer.

A lightweight chat-app style channel, distinct from categorized support
tickets: either side can start it, it never auto-solves, and each customer has
exactly one thread. The owner can also open it from any order to follow up.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from database.mongo import db

DIRECTION_OWNER = "owner_to_customer"
DIRECTION_CUSTOMER = "customer_to_owner"


def _now() -> datetime:
    return datetime.now(UTC)


def _as_object_id(conversation_id: str | ObjectId) -> ObjectId:
    if isinstance(conversation_id, ObjectId):
        return conversation_id
    return ObjectId(str(conversation_id))


async def bootstrap_customer_conversation_indexes() -> None:
    await db.customer_conversations.create_index("customer_id", unique=True, background=True)
    await db.customer_conversations.create_index([("last_message_at", -1)], background=True)
    await db.customer_conversation_messages.create_index(
        [("conversation_id", 1), ("created_at", 1)], background=True
    )


async def get_conversation_by_id(conversation_id: str | ObjectId) -> dict[str, Any] | None:
    try:
        oid = _as_object_id(conversation_id)
    except Exception:
        return None
    return await db.customer_conversations.find_one({"_id": oid})


async def get_conversation_for_customer(customer_id: int) -> dict[str, Any] | None:
    return await db.customer_conversations.find_one({"customer_id": int(customer_id)})


async def get_or_create_conversation(
    *, customer_id: int, account_id: str | None = None, customer_email: str | None = None
) -> dict[str, Any]:
    existing = await get_conversation_for_customer(int(customer_id))
    if existing:
        return existing
    now = _now()
    doc: dict[str, Any] = {
        "customer_id": int(customer_id),
        "account_id": str(account_id or "") or None,
        "customer_email": str(customer_email or ""),
        "status": "open",
        "owner_unread": 0,
        "customer_unread": 0,
        "last_message_at": now,
        "last_message_preview": "",
        "last_message_by": "",
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await db.customer_conversations.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc
    except DuplicateKeyError:
        return await get_conversation_for_customer(int(customer_id)) or doc


async def append_message(
    conversation: dict[str, Any],
    *,
    direction: str,
    actor_id: int,
    text: str,
    order_ref: str | None = None,
) -> dict[str, Any]:
    now = _now()
    message: dict[str, Any] = {
        "conversation_id": conversation["_id"],
        "direction": str(direction),
        "actor_id": int(actor_id),
        "text": str(text),
        "order_ref": str(order_ref or ""),
        "created_at": now,
    }
    result = await db.customer_conversation_messages.insert_one(message)
    message["_id"] = result.inserted_id
    sent_by_owner = direction == DIRECTION_OWNER
    inc = {"customer_unread": 1} if sent_by_owner else {"owner_unread": 1}
    await db.customer_conversations.update_one(
        {"_id": conversation["_id"]},
        {
            "$set": {
                "status": "open",
                "last_message_at": now,
                "last_message_preview": str(text)[:120],
                "last_message_by": "owner" if sent_by_owner else "customer",
                "updated_at": now,
            },
            "$inc": inc,
        },
    )
    return message


async def list_messages(conversation_id: str | ObjectId, *, limit: int = 200) -> list[dict[str, Any]]:
    cursor = (
        db.customer_conversation_messages.find({"conversation_id": _as_object_id(conversation_id)})
        .sort("created_at", 1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


def owner_conversations_cursor(query: dict[str, Any] | None = None):
    """Motor cursor of conversations newest-activity first, for owner paging."""
    return db.customer_conversations.find(query or {}).sort("last_message_at", -1)


async def mark_conversation_read(conversation_id: str | ObjectId, *, side: str) -> None:
    field = "owner_unread" if side == "owner" else "customer_unread"
    await db.customer_conversations.update_one(
        {"_id": _as_object_id(conversation_id)},
        {"$set": {field: 0, "updated_at": _now()}},
    )
