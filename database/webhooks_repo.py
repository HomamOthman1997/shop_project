from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from database.mongo import db


def new_webhook_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


def serialize_webhook_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc.get("_id") or ""),
        "url": str(doc.get("url") or ""),
        "events": [str(item) for item in (doc.get("events") or [])],
        "status": str(doc.get("status") or ""),
        "created_at": doc.get("created_at").isoformat() if hasattr(doc.get("created_at"), "isoformat") else None,
        "updated_at": doc.get("updated_at").isoformat() if hasattr(doc.get("updated_at"), "isoformat") else None,
    }


async def create_webhook(
    *,
    user_id: int,
    reseller_id: int,
    url: str,
    events: list[str],
) -> tuple[str, dict[str, Any]]:
    now = datetime.now(UTC)
    secret = new_webhook_secret()
    doc = {
        "user_id": int(user_id),
        "reseller_id": int(reseller_id),
        "url": str(url or "").strip(),
        "secret": secret,
        "events": sorted({str(item).strip() for item in events if str(item).strip()}),
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    result = await db.api_webhooks.insert_one(doc)
    doc["_id"] = result.inserted_id
    return secret, doc


async def list_webhooks(*, reseller_id: int) -> list[dict[str, Any]]:
    cursor = db.api_webhooks.find({"reseller_id": int(reseller_id)}).sort("created_at", -1)
    return [serialize_webhook_doc(doc) async for doc in cursor]


async def revoke_webhook(*, webhook_id: str, reseller_id: int | None = None) -> bool:
    try:
        oid = ObjectId(str(webhook_id))
    except Exception:
        return False
    query: dict[str, Any] = {"_id": oid}
    if reseller_id is not None:
        query["reseller_id"] = int(reseller_id)
    result = await db.api_webhooks.update_one(
        query,
        {"$set": {"status": "revoked", "updated_at": datetime.now(UTC), "revoked_at": datetime.now(UTC)}},
    )
    return bool(result.modified_count)


async def active_webhooks_for_event(*, user_id: int, reseller_id: int, event_type: str) -> list[dict[str, Any]]:
    event = str(event_type or "").strip()
    cursor = db.api_webhooks.find(
        {
            "user_id": int(user_id),
            "reseller_id": int(reseller_id),
            "status": "active",
            "events": event,
        }
    )
    return await cursor.to_list(length=100)


async def enqueue_webhook_delivery(*, webhook: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    doc = {
        "webhook_id": webhook.get("_id"),
        "user_id": int(webhook.get("user_id") or 0),
        "reseller_id": int(webhook.get("reseller_id") or 0),
        "url": str(webhook.get("url") or ""),
        "secret": str(webhook.get("secret") or ""),
        "event": event,
        "status": "pending",
        "attempts": 0,
        "next_attempt_at": now,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.api_webhook_deliveries.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def list_due_webhook_deliveries(*, now: datetime, limit: int = 100) -> list[dict[str, Any]]:
    cursor = (
        db.api_webhook_deliveries.find(
            {
                "status": {"$in": ["pending", "retry"]},
                "next_attempt_at": {"$lte": now},
            }
        )
        .sort("next_attempt_at", 1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def mark_webhook_delivery_success(*, delivery_id: Any, status_code: int, response_text: str) -> None:
    await db.api_webhook_deliveries.update_one(
        {"_id": delivery_id},
        {
            "$set": {
                "status": "delivered",
                "last_status_code": int(status_code),
                "last_response": str(response_text or "")[:2000],
                "delivered_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        },
    )


async def mark_webhook_delivery_failure(
    *,
    delivery_id: Any,
    status_code: int | None,
    response_text: str,
    next_attempt_at: datetime | None,
    terminal: bool,
) -> None:
    patch = {
        "status": "failed" if terminal else "retry",
        "last_status_code": int(status_code) if status_code is not None else None,
        "last_response": str(response_text or "")[:2000],
        "updated_at": datetime.now(UTC),
    }
    if next_attempt_at is not None:
        patch["next_attempt_at"] = next_attempt_at
    await db.api_webhook_deliveries.update_one({"_id": delivery_id}, {"$set": patch, "$inc": {"attempts": 1}})
