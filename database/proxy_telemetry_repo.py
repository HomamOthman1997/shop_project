from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .mongo import db


async def bootstrap_proxy_events_indexes() -> None:
    await db.proxy_events.create_index([("created_at", -1)])
    await db.proxy_events.create_index([("provider", 1), ("created_at", -1)])
    await db.proxy_events.create_index([("event_type", 1), ("created_at", -1)])


async def record_proxy_event(
    *,
    event_type: str,
    provider: str,
    success: bool | None = None,
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    await db.proxy_events.insert_one(
        {
            "event_type": str(event_type or "").strip().lower(),
            "provider": str(provider or "").strip().lower(),
            "success": None if success is None else bool(success),
            "reason": str(reason or "").strip().lower() if reason else "",
            "extra": dict(extra or {}),
            "created_at": datetime.now(UTC),
        }
    )


async def summarize_proxy_events(*, hours: int = 24) -> dict[str, Any]:
    window = max(1, min(int(hours or 24), 168))
    since = datetime.now(UTC) - timedelta(hours=window)
    match = {"created_at": {"$gte": since}}
    total = await db.proxy_events.count_documents(match)
    success = await db.proxy_events.count_documents({**match, "success": True})
    failed = await db.proxy_events.count_documents({**match, "success": False})
    by_provider_rows = await db.proxy_events.aggregate(
        [
            {"$match": match},
            {
                "$group": {
                    "_id": "$provider",
                    "count": {"$sum": 1},
                    "failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}},
                    "success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
                }
            },
            {"$sort": {"count": -1}},
        ]
    ).to_list(None)
    reasons = await db.proxy_events.aggregate(
        [
            {"$match": {**match, "reason": {"$ne": ""}}},
            {"$group": {"_id": "$reason", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
    ).to_list(None)
    providers: list[dict[str, Any]] = []
    for row in by_provider_rows:
        providers.append(
            {
                "provider": str(row.get("_id") or ""),
                "count": int(row.get("count") or 0),
                "failed": int(row.get("failed") or 0),
                "success": int(row.get("success") or 0),
            }
        )
    top_reasons = [{"reason": str(r.get("_id") or ""), "count": int(r.get("count") or 0)} for r in reasons]
    fail_rate = (float(failed) / float(total) * 100.0) if total > 0 else 0.0
    return {
        "window_hours": window,
        "total": int(total),
        "success": int(success),
        "failed": int(failed),
        "fail_rate_percent": round(fail_rate, 2),
        "providers": providers,
        "top_reasons": top_reasons,
    }
