from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .mongo import db

_SCHEMA_DOC_ID = "schema_versions"
_CLEANUP_DOC_ID = "lifecycle_cleanup_metrics"

_CRITICAL_COLLECTION_VERSIONS: dict[str, int] = {
    "wallets": 1,
    "ledger_entries": 1,
    "orders": 3,
    "recharge_requests": 2,
    "bots": 2,
    "custom_services": 2,
    "proxy_events": 1,
    "number_order_events": 1,
    "usage_stats": 1,
}


async def ensure_schema_markers() -> None:
    now = datetime.now(UTC)
    existing = await db.system_settings.find_one({"_id": _SCHEMA_DOC_ID}) or {}
    merged = dict(existing.get("collections") or {})
    for key, version in _CRITICAL_COLLECTION_VERSIONS.items():
        old = merged.get(key)
        try:
            old_ver = int(old)
        except Exception:
            old_ver = 0
        merged[key] = max(old_ver, int(version))
    await db.system_settings.update_one(
        {"_id": _SCHEMA_DOC_ID},
        {
            "$set": {
                "collections": merged,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


async def get_last_cleanup_metrics() -> dict[str, Any] | None:
    return await db.system_settings.find_one({"_id": _CLEANUP_DOC_ID})


async def run_lifecycle_cleanup(
    *,
    telemetry_retention_days: int = 30,
    number_events_retention_days: int = 120,
    usage_retention_days: int = 180,
    archived_orders_retention_days: int = 365,
    order_archive_age_days: int = 120,
    order_archive_batch_size: int = 400,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    metrics: dict[str, Any] = {
        "ran_at": now,
        "proxy_events_deleted": 0,
        "number_events_deleted": 0,
        "usage_stats_deleted": 0,
        "orders_archived": 0,
        "orders_deleted_after_archive": 0,
        "orders_archive_errors": 0,
        "orders_archive_retention_deleted": 0,
    }

    proxy_cutoff = now - timedelta(days=max(1, int(telemetry_retention_days or 30)))
    num_evt_cutoff = now - timedelta(days=max(1, int(number_events_retention_days or 120)))
    usage_cutoff = now - timedelta(days=max(7, int(usage_retention_days or 180)))
    archived_cutoff = now - timedelta(days=max(30, int(archived_orders_retention_days or 365)))
    orders_cutoff = now - timedelta(days=max(7, int(order_archive_age_days or 120)))

    proxy_del = await db.proxy_events.delete_many({"created_at": {"$lt": proxy_cutoff}})
    metrics["proxy_events_deleted"] = int(proxy_del.deleted_count or 0)

    number_del = await db.number_order_events.delete_many({"created_at": {"$lt": num_evt_cutoff}})
    metrics["number_events_deleted"] = int(number_del.deleted_count or 0)

    usage_del = await db.usage_stats.delete_many(
        {
            "updated_at": {"$lt": usage_cutoff},
            "count": {"$lte": 1},
        }
    )
    metrics["usage_stats_deleted"] = int(usage_del.deleted_count or 0)

    await db.orders_archive.create_index([("source_order_id", 1)], unique=True)
    await db.orders_archive.create_index([("archived_at", -1)])

    stale_rows = (
        await db.orders.find(
            {
                "status": {"$in": ["success", "done", "failed", "refunded", "cancelled", "expired"]},
                "created_at": {"$lt": orders_cutoff},
            }
        )
        .sort("created_at", 1)
        .limit(max(50, int(order_archive_batch_size or 400)))
        .to_list(None)
    )
    archived_ids: list[Any] = []
    for row in stale_rows:
        source_id = row.get("_id")
        if source_id is None:
            continue
        archived_doc = dict(row)
        archived_doc["source_order_id"] = source_id
        archived_doc["archived_at"] = now
        archived_doc.pop("_id", None)
        try:
            await db.orders_archive.update_one(
                {"source_order_id": source_id},
                {"$setOnInsert": archived_doc},
                upsert=True,
            )
            archived_ids.append(source_id)
        except Exception:
            metrics["orders_archive_errors"] = int(metrics["orders_archive_errors"]) + 1

    metrics["orders_archived"] = len(archived_ids)
    if archived_ids:
        order_del = await db.orders.delete_many({"_id": {"$in": archived_ids}})
        metrics["orders_deleted_after_archive"] = int(order_del.deleted_count or 0)

    old_archive_del = await db.orders_archive.delete_many({"archived_at": {"$lt": archived_cutoff}})
    metrics["orders_archive_retention_deleted"] = int(old_archive_del.deleted_count or 0)

    await db.system_settings.update_one(
        {"_id": _CLEANUP_DOC_ID},
        {
            "$set": {
                **metrics,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return metrics
