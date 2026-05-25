from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from database.mongo import db


async def record_provider_webhook_event(
    *,
    provider_code: str,
    event_type: str,
    provider_order_id: str,
    payload: dict[str, Any],
    status: str,
    reason: str = "",
    order_id: Any = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    doc = {
        "provider": str(provider_code or "").strip().lower(),
        "event_type": str(event_type or "").strip(),
        "provider_order_id": str(provider_order_id or "").strip(),
        "order_id": order_id,
        "status": str(status or "").strip() or "received",
        "reason": str(reason or "").strip(),
        "payload": payload if isinstance(payload, dict) else {},
        "created_at": now,
        "updated_at": now,
    }
    result = await db.provider_webhook_events.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def serialize_provider_webhook_event(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc.get("_id") or ""),
        "provider": str(doc.get("provider") or ""),
        "event_type": str(doc.get("event_type") or ""),
        "provider_order_id": str(doc.get("provider_order_id") or ""),
        "order_id": str(doc.get("order_id") or "") if doc.get("order_id") is not None else "",
        "status": str(doc.get("status") or ""),
        "reason": str(doc.get("reason") or ""),
        "payload": doc.get("payload") if isinstance(doc.get("payload"), dict) else {},
        "replay_status": str(doc.get("replay_status") or ""),
        "replay_reason": str(doc.get("replay_reason") or ""),
        "replayed_at": doc.get("replayed_at").isoformat() if hasattr(doc.get("replayed_at"), "isoformat") else None,
        "created_at": doc.get("created_at").isoformat() if hasattr(doc.get("created_at"), "isoformat") else None,
        "updated_at": doc.get("updated_at").isoformat() if hasattr(doc.get("updated_at"), "isoformat") else None,
    }


async def list_provider_webhook_events(
    *,
    provider: str = "",
    status: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if str(provider or "").strip():
        query["provider"] = str(provider or "").strip().lower()
    if str(status or "").strip():
        query["status"] = str(status or "").strip()
    cursor = db.provider_webhook_events.find(query).sort("created_at", -1).limit(max(1, int(limit)))
    return [serialize_provider_webhook_event(doc) async for doc in cursor]


async def get_provider_webhook_event(event_id: str) -> dict[str, Any] | None:
    try:
        oid = ObjectId(str(event_id))
    except Exception:
        return None
    return await db.provider_webhook_events.find_one({"_id": oid})


async def mark_provider_webhook_event_replayed(
    *,
    event_id: str,
    replay_status: str,
    replay_reason: str,
    order_id: Any = None,
) -> dict[str, Any] | None:
    try:
        oid = ObjectId(str(event_id))
    except Exception:
        return None
    now = datetime.now(UTC)
    patch: dict[str, Any] = {
        "replay_status": str(replay_status or "").strip(),
        "replay_reason": str(replay_reason or "").strip(),
        "replayed_at": now,
        "updated_at": now,
    }
    if order_id is not None:
        patch["order_id"] = order_id
    result = await db.provider_webhook_events.update_one({"_id": oid}, {"$set": patch})
    if not bool(result.matched_count):
        return None
    return await db.provider_webhook_events.find_one({"_id": oid})
