from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo import ReplaceOne

from .mongo import db

# Fields the admin can edit in the staging review. On re-import these are
# preserved when `admin_edited` is set, so a refresh never clobbers curation.
ADMIN_EDITABLE_FIELDS = (
    "service_key",
    "family_key",
    "family_name",
    "sub_category",
    "package_name",
    "suggested_price_usd",
    "execution_policy",
    "status",
    "drop_reason",
)

VALID_STATUSES = {"new", "review", "duplicate", "dropped", "approved", "stale"}


def _now() -> datetime:
    return datetime.now(UTC)


async def bootstrap_digital_catalog_staging_indexes() -> None:
    await db.digital_catalog_staging.create_index(
        [("owner_id", 1), ("staging_key", 1)], unique=True, background=True
    )
    await db.digital_catalog_staging.create_index([("owner_id", 1), ("status", 1)], background=True)
    await db.digital_catalog_staging.create_index(
        [("owner_id", 1), ("service_key", 1), ("family_key", 1)], background=True
    )


async def upsert_staging_items(owner_id: int, run_id: str, items: list[dict[str, Any]]) -> dict[str, int]:
    """Upsert staged items by (owner_id, staging_key).

    Refreshes provider/import-derived fields. Preserves admin-edited fields
    (price, placement, status) when the existing row has `admin_edited=True`.
    """
    owner = int(owner_id)
    keys = [str(item.get("staging_key") or "").strip() for item in items if str(item.get("staging_key") or "").strip()]
    existing_map: dict[str, dict[str, Any]] = {}
    if keys:
        cursor = db.digital_catalog_staging.find({"owner_id": owner, "staging_key": {"$in": keys}})
        for row in await cursor.to_list(length=None):
            existing_map[str(row.get("staging_key") or "")] = row

    now = _now()
    ops: list[ReplaceOne] = []
    inserted = updated = preserved = 0
    for item in items:
        staging_key = str(item.get("staging_key") or "").strip()
        if not staging_key:
            continue
        existing = existing_map.get(staging_key)
        doc = dict(item)
        doc["owner_id"] = owner
        doc["staging_key"] = staging_key
        doc["run_id"] = str(run_id)
        doc["updated_at"] = now
        if existing:
            doc["_id"] = existing["_id"]
            doc["imported_at"] = existing.get("imported_at") or now
            admin_edited = bool(existing.get("admin_edited"))
            doc["admin_edited"] = admin_edited
            if admin_edited:
                for field in ADMIN_EDITABLE_FIELDS:
                    if field in existing:
                        doc[field] = existing[field]
                preserved += 1
            else:
                updated += 1
        else:
            doc["imported_at"] = now
            doc.setdefault("admin_edited", False)
            doc.setdefault("status", "new")
            inserted += 1
        ops.append(ReplaceOne({"owner_id": owner, "staging_key": staging_key}, doc, upsert=True))

    if ops:
        await db.digital_catalog_staging.bulk_write(ops, ordered=False)
    return {"inserted": inserted, "updated": updated, "preserved": preserved, "total": inserted + updated + preserved}


async def list_staging_items(
    owner_id: int,
    *,
    status: str | None = None,
    service_key: str | None = None,
    family_key: str | None = None,
    limit: int = 0,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"owner_id": int(owner_id)}
    if status:
        query["status"] = str(status).strip().lower()
    if service_key:
        query["service_key"] = str(service_key).strip()
    if family_key:
        query["family_key"] = str(family_key).strip()
    cursor = db.digital_catalog_staging.find(query).sort(
        [("service_key", 1), ("family_key", 1), ("sub_category", 1), ("suggested_price_usd", 1)]
    )
    if int(offset) > 0:
        cursor = cursor.skip(int(offset))
    length = None if int(limit) <= 0 else max(1, int(limit))
    return await cursor.to_list(length=length)


async def get_staging_item(owner_id: int, item_id: str) -> dict[str, Any] | None:
    try:
        oid = ObjectId(str(item_id))
    except Exception:
        return None
    return await db.digital_catalog_staging.find_one({"_id": oid, "owner_id": int(owner_id)})


async def update_staging_item(owner_id: int, item_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    try:
        oid = ObjectId(str(item_id))
    except Exception:
        return None
    clean = {key: value for key, value in (patch or {}).items() if key in ADMIN_EDITABLE_FIELDS}
    if not clean:
        return await db.digital_catalog_staging.find_one({"_id": oid, "owner_id": int(owner_id)})
    if "status" in clean and str(clean["status"]).strip().lower() not in VALID_STATUSES:
        clean.pop("status")
    clean["admin_edited"] = True
    clean["updated_at"] = _now()
    await db.digital_catalog_staging.update_one(
        {"_id": oid, "owner_id": int(owner_id)}, {"$set": clean}
    )
    return await db.digital_catalog_staging.find_one({"_id": oid, "owner_id": int(owner_id)})


async def set_staging_status(owner_id: int, item_ids: list[str], status: str, *, drop_reason: str = "") -> int:
    clean_status = str(status or "").strip().lower()
    if clean_status not in VALID_STATUSES:
        return 0
    oids: list[ObjectId] = []
    for item_id in item_ids or []:
        try:
            oids.append(ObjectId(str(item_id)))
        except Exception:
            continue
    if not oids:
        return 0
    patch: dict[str, Any] = {"status": clean_status, "admin_edited": True, "updated_at": _now()}
    if clean_status == "dropped":
        patch["drop_reason"] = str(drop_reason or "manual")
    result = await db.digital_catalog_staging.update_many(
        {"_id": {"$in": oids}, "owner_id": int(owner_id)}, {"$set": patch}
    )
    return int(result.modified_count or 0)


async def staging_status_counts(owner_id: int) -> dict[str, int]:
    pipeline = [
        {"$match": {"owner_id": int(owner_id)}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    counts: dict[str, int] = {}
    async for row in db.digital_catalog_staging.aggregate(pipeline):
        counts[str(row.get("_id") or "unknown")] = int(row.get("count") or 0)
    return counts


async def clear_staging(owner_id: int, *, only_status: str | None = None) -> int:
    query: dict[str, Any] = {"owner_id": int(owner_id)}
    if only_status:
        query["status"] = str(only_status).strip().lower()
    result = await db.digital_catalog_staging.delete_many(query)
    return int(result.deleted_count or 0)


async def set_import_run(owner_id: int, patch: dict[str, Any]) -> None:
    """Upsert the (single) background import-run status doc for an owner."""
    doc = {**patch, "owner_id": int(owner_id), "updated_at": _now()}
    await db.digital_catalog_staging_runs.update_one(
        {"owner_id": int(owner_id)}, {"$set": doc}, upsert=True
    )


async def get_import_run(owner_id: int) -> dict[str, Any] | None:
    return await db.digital_catalog_staging_runs.find_one({"owner_id": int(owner_id)})


async def set_staging_job_run(owner_id: int, job: str, patch: dict[str, Any]) -> None:
    """Upsert a background-job status doc per (owner, job) — e.g. approve, cutover.

    Kept separate from the import-run doc so the heavy approve/cutover steps can
    run in the background (a synchronous run exceeds Cloudflare's timeout -> 524)."""
    doc = {**patch, "owner_id": int(owner_id), "job": str(job), "updated_at": _now()}
    await db.digital_catalog_staging_jobs.update_one(
        {"owner_id": int(owner_id), "job": str(job)}, {"$set": doc}, upsert=True
    )


async def get_staging_job_run(owner_id: int, job: str) -> dict[str, Any] | None:
    return await db.digital_catalog_staging_jobs.find_one({"owner_id": int(owner_id), "job": str(job)})
