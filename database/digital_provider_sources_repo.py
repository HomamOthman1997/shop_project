from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from .mongo import db


def _now() -> datetime:
    return datetime.now(UTC)


async def bootstrap_digital_provider_sources_indexes() -> None:
    await db.digital_provider_sources.create_index([("provider", 1), ("source_ref", 1)], unique=True, background=True)
    await db.digital_provider_sources.create_index([("source_token", 1)], unique=True, sparse=True, background=True)
    await db.digital_provider_sources.create_index([("compare_key", 1), ("provider", 1), ("price_status", 1)], background=True)
    await db.digital_provider_sources.create_index([("provider", 1), ("price_status", 1), ("last_seen_at", -1)], background=True)
    await db.digital_price_watch_runs.create_index([("provider", 1), ("started_at", -1)], background=True)


def _source_key(provider: str, source_ref: str) -> str:
    return f"{str(provider or '').strip().lower()}:{str(source_ref or '').strip()}"


def _source_token(source_id: str) -> str:
    return hashlib.sha1(str(source_id or "").encode("utf-8")).hexdigest()[:12]


async def list_active_provider_sources(*, provider: str | None = None) -> list[dict[str, Any]]:
    query: dict[str, Any] = {
        "price_status": "active",
        "available": True,
        "compare_key": {"$nin": [None, ""]},
    }
    if provider:
        query["provider"] = str(provider).strip().lower()
    cursor = db.digital_provider_sources.find(query).sort([("provider", 1), ("active_price", 1)])
    return await cursor.to_list(length=None)


async def list_provider_sources(
    *,
    provider: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if provider:
        query["provider"] = str(provider).strip().lower()
    if status:
        query["price_status"] = str(status).strip().lower()
    cursor = db.digital_provider_sources.find(query).sort([("updated_at", -1), ("last_seen_at", -1)])
    rows = await cursor.to_list(length=max(1, min(100, int(limit or 20))))
    for row in rows:
        if not row.get("source_token") and row.get("_id"):
            token = _source_token(str(row["_id"]))
            row["source_token"] = token
            await db.digital_provider_sources.update_one({"_id": row["_id"]}, {"$set": {"source_token": token}})
    return rows


async def get_provider_source(source_id: str) -> dict[str, Any] | None:
    raw = str(source_id or "").strip()
    if not raw:
        return None
    return await db.digital_provider_sources.find_one({"$or": [{"_id": raw}, {"source_token": raw}]})


async def approve_provider_source(source_id: str, *, actor_id: int | None = None) -> dict[str, Any] | None:
    now = _now()
    current = await get_provider_source(source_id)
    if not current:
        return None
    observed = round(float(current.get("observed_price") or current.get("active_price") or 0.0), 6)
    compare_key = str(current.get("compare_key") or "").strip()
    if observed <= 0 or not compare_key:
        return current
    await db.digital_provider_sources.update_one(
        {"_id": current["_id"]},
        {
            "$set": {
                "active_price": observed,
                "price_status": "active",
                "review_reason": "",
                "available": True,
                "approved_by": int(actor_id or 0) if actor_id else None,
                "approved_at": now,
                "updated_at": now,
            }
        },
    )
    return await get_provider_source(str(current["_id"]))


async def disable_provider_source(source_id: str, *, actor_id: int | None = None) -> dict[str, Any] | None:
    now = _now()
    current = await get_provider_source(source_id)
    if not current:
        return None
    await db.digital_provider_sources.update_one(
        {"_id": current["_id"]},
        {
            "$set": {
                "price_status": "disabled",
                "available": False,
                "disabled_by": int(actor_id or 0) if actor_id else None,
                "disabled_at": now,
                "updated_at": now,
            }
        },
    )
    return await get_provider_source(str(current["_id"]))


async def list_price_watch_runs(*, provider: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if provider:
        query["provider"] = str(provider).strip().lower()
    cursor = db.digital_price_watch_runs.find(query).sort([("started_at", -1)])
    return await cursor.to_list(length=max(1, min(20, int(limit or 5))))


async def upsert_provider_source(
    *,
    provider: str,
    source_ref: str,
    compare_key: str,
    source_url: str,
    source_product_name: str,
    source_denomination_name: str,
    active_price: float | None,
    observed_price: float,
    available: bool,
    fulfillment_mode: str,
    parse_confidence: float,
    parser_version: str,
    source_payload: dict[str, Any] | None = None,
    max_auto_change_percent: float = 10.0,
) -> dict[str, Any]:
    provider_code = str(provider or "").strip().lower()
    ref = str(source_ref or "").strip()
    if not provider_code or not ref:
        return {"ok": False, "status": "invalid", "reason": "missing_source_ref"}

    now = _now()
    key = _source_key(provider_code, ref)
    current = await db.digital_provider_sources.find_one({"_id": key})
    observed = round(float(observed_price or 0.0), 6)
    confidence = max(0.0, min(1.0, float(parse_confidence or 0.0)))
    cmp_key = str(compare_key or "").strip()

    status = "active"
    reason = ""
    approved_price = observed
    if observed <= 0:
        status = "under_review"
        reason = "invalid_price"
    elif not cmp_key:
        status = "unmapped"
        reason = "missing_compare_key"
    elif confidence < 0.75:
        status = "under_review"
        reason = "low_parse_confidence"
    elif current:
        previous_key = str(current.get("compare_key") or "").strip()
        previous_price = float(current.get("active_price") or current.get("observed_price") or 0.0)
        previous_status = str(current.get("price_status") or "").strip().lower()
        if previous_key and previous_key != cmp_key:
            status = "under_review"
            reason = "compare_key_changed"
            approved_price = float(current.get("active_price") or previous_price or observed)
        elif previous_price > 0:
            delta = abs(observed - previous_price) / previous_price * 100.0
            if delta > max(0.0, float(max_auto_change_percent or 10.0)):
                status = "under_review"
                reason = "price_change_gt_guardrail"
                approved_price = float(current.get("active_price") or previous_price)
        elif previous_status == "disabled":
            status = "disabled"
            reason = "disabled"
            approved_price = float(current.get("active_price") or observed)
    elif active_price is not None and float(active_price or 0.0) > 0:
        approved_price = round(float(active_price or 0.0), 6)

    payload = {
        "_id": key,
        "source_token": _source_token(key),
        "provider": provider_code,
        "source_ref": ref,
        "compare_key": cmp_key,
        "source_url": str(source_url or "").strip(),
        "source_product_name": str(source_product_name or "").strip(),
        "source_denomination_name": str(source_denomination_name or "").strip(),
        "fulfillment_mode": str(fulfillment_mode or "").strip(),
        "active_price": round(float(approved_price or 0.0), 6),
        "observed_price": observed,
        "available": bool(available),
        "price_status": status,
        "review_reason": reason,
        "parse_confidence": confidence,
        "parser_version": str(parser_version or "").strip(),
        "source_payload": dict(source_payload or {}),
        "last_seen_at": now,
        "updated_at": now,
    }
    if status == "active":
        payload["last_success_at"] = now
        payload["last_error"] = ""
    if current:
        payload["previous_observed_price"] = float(current.get("observed_price") or 0.0)

    await db.digital_provider_sources.update_one(
        {"_id": key},
        {"$set": payload, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"ok": True, "status": status, "reason": reason, "source": payload}


async def record_price_watch_run(
    *,
    provider: str,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    stats: dict[str, Any],
    errors: list[str] | None = None,
) -> dict[str, Any]:
    doc = {
        "provider": str(provider or "").strip().lower(),
        "started_at": started_at,
        "finished_at": finished_at,
        "status": str(status or "").strip().lower() or "unknown",
        "stats": dict(stats or {}),
        "errors": list(errors or []),
        "created_at": _now(),
    }
    await db.digital_price_watch_runs.insert_one(doc)
    return doc
