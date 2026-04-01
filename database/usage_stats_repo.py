from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .mongo import db


async def bootstrap_usage_stats_indexes() -> None:
    await db.usage_stats.create_index([("category", 1), ("service_name", 1)], unique=True)
    await db.usage_stats.create_index([("category", 1), ("count", -1)])


async def increment_service_usage(*, service_name: str, category: str = "general") -> None:
    name = str(service_name or "").strip().lower()
    cat = str(category or "general").strip().lower()
    if not name:
        return
    now = datetime.now(UTC)
    await db.usage_stats.update_one(
        {"category": cat, "service_name": name},
        {
            "$inc": {"count": 1},
            "$set": {"updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


async def get_top_usage(*, category: str = "general", limit: int = 10) -> list[dict[str, Any]]:
    cat = str(category or "general").strip().lower()
    lim = max(1, min(int(limit or 10), 100))
    rows = (
        await db.usage_stats.find({"category": cat})
        .sort("count", -1)
        .limit(lim)
        .to_list(lim)
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "service_name": str(row.get("service_name") or ""),
                "count": int(row.get("count") or 0),
                "updated_at": row.get("updated_at"),
            }
        )
    return out
