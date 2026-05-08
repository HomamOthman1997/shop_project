from datetime import UTC, datetime
from typing import Any

from .mongo import db


async def bootstrap_temp_number_stats_indexes() -> None:
    await db.temp_number_events.create_index([("created_at", -1)], background=True)
    await db.temp_number_events.create_index([("provider", 1), ("service_id", 1), ("created_at", -1)], background=True)
    await db.temp_number_events.create_index([("service_id", 1), ("created_at", -1)], background=True)
    await db.temp_number_events.create_index(
        [("service_id", 1), ("provider", 1), ("payload.country", 1), ("payload.state", 1), ("created_at", -1)],
        background=True,
    )
    await db.temp_number_events.create_index([("user_id", 1), ("provider", 1), ("service_id", 1), ("created_at", -1)], background=True)
    await db.temp_number_events.create_index([("order_id", 1), ("created_at", -1)], background=True)
    await db.temp_number_events.create_index([("event", 1), ("created_at", -1)], background=True)
    await db.temp_number_user_locks.create_index(
        [("user_id", 1), ("provider", 1), ("service_id", 1), ("lock_type", 1)],
        unique=True,
        background=True,
    )
    await db.temp_number_user_locks.create_index([("expires_at", 1)], expireAfterSeconds=0, background=True)


async def log_temp_number_event(
    order_id,
    *,
    user_id: int,
    provider: str,
    service_id: str,
    event: str,
    payload: dict[str, Any] | None = None,
):
    doc = {
        "order_id": order_id,
        "user_id": int(user_id),
        "provider": str(provider or "").lower(),
        "service_id": str(service_id or ""),
        "event": str(event or "unknown"),
        "payload": dict(payload or {}),
        "created_at": datetime.now(UTC),
    }
    await db.temp_number_events.insert_one(doc)
    return doc


def _window_start_utc(lookback_days: int) -> datetime:
    safe_days = max(1, int(lookback_days or 1))
    now = datetime.now(UTC)
    return datetime.fromtimestamp(now.timestamp() - (safe_days * 86400), tz=UTC)


async def get_provider_success_rates(
    *,
    service_id: str,
    providers: list[str] | tuple[str, ...] | None = None,
    country: str | None = None,
    state: str | None = None,
    lookback_days: int = 14,
    min_attempts: int = 3,
    default_rate: float = 100.0,
) -> dict[str, dict[str, Any]]:
    service = str(service_id or "").strip()
    if not service:
        return {}

    provider_filter = [str(p or "").strip().lower() for p in (providers or []) if str(p or "").strip()]
    match_filter: dict[str, Any] = {
        "service_id": service,
        "created_at": {"$gte": _window_start_utc(lookback_days)},
    }
    if provider_filter:
        match_filter["provider"] = {"$in": provider_filter}
    country_value = str(country or "").strip()
    state_value = str(state or "").strip()
    if country_value:
        match_filter["payload.country"] = country_value
    if state_value:
        match_filter["payload.state"] = state_value

    pipeline = [
        {"$match": match_filter},
        {
            "$group": {
                "_id": {"provider": "$provider", "order_id": "$order_id"},
                "purchased": {
                    "$max": {
                        "$cond": [{"$eq": ["$event", "purchase_success"]}, 1, 0]
                    }
                },
                "got_code": {
                    "$max": {
                        "$cond": [
                            {"$in": ["$event", ["code_received", "refresh_code_received"]]},
                            1,
                            0,
                        ]
                    }
                },
                "failed_no_code": {
                    "$max": {
                        "$cond": [
                            {"$in": ["$event", ["wait_timeout", "wait_timeout_auto_refunded", "cancelled_refunded"]]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {
            "$group": {
                "_id": "$_id.provider",
                "attempts": {"$sum": "$purchased"},
                "successes": {
                    "$sum": {
                        "$cond": [
                            {"$and": [{"$eq": ["$purchased", 1]}, {"$eq": ["$got_code", 1]}]},
                            1,
                            0,
                        ]
                    }
                },
                "failed": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$eq": ["$purchased", 1]},
                                    {"$eq": ["$got_code", 0]},
                                    {"$eq": ["$failed_no_code", 1]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]

    rows = await db.temp_number_events.aggregate(pipeline).to_list(length=None)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        provider = str(row.get("_id") or "").strip().lower()
        if not provider:
            continue
        attempts = int(row.get("attempts") or 0)
        successes = int(row.get("successes") or 0)
        failed = int(row.get("failed") or 0)
        pending = max(0, attempts - successes - failed)
        if attempts >= max(1, int(min_attempts or 1)):
            rate = (float(successes) / float(attempts)) * 100.0 if attempts > 0 else float(default_rate)
        else:
            rate = float(default_rate)
        out[provider] = {
            "success_rate": max(0.0, min(100.0, float(rate))),
            "attempts": attempts,
            "successes": successes,
            "failed": failed,
            "pending": pending,
            "sample_sufficient": attempts >= max(1, int(min_attempts or 1)),
        }

    # Ensure callers get a deterministic fallback entry for all requested providers.
    for provider in provider_filter:
        out.setdefault(
            provider,
            {
                "success_rate": float(default_rate),
                "attempts": 0,
                "successes": 0,
                "failed": 0,
                "pending": 0,
                "sample_sufficient": False,
            },
        )
    return out


_POSITIVE_EVENTS = ("code_received", "refresh_code_received")
_NEGATIVE_EVENTS = ("wait_timeout_auto_refunded", "cancelled_refunded")


async def get_user_trust_snapshot(
    *,
    user_id: int,
    service_id: str,
    provider: str,
    lookback_hours: int,
) -> dict[str, int]:
    uid = int(user_id)
    service = str(service_id or "").strip()
    prov = str(provider or "").strip().lower()
    if not service or not prov:
        return {"positive": 0, "negative": 0, "score": 0}

    hours = max(1, int(lookback_hours or 1))
    since = datetime.fromtimestamp(datetime.now(UTC).timestamp() - (hours * 3600), tz=UTC)

    pipeline = [
        {
            "$match": {
                "user_id": uid,
                "service_id": service,
                "provider": prov,
                "created_at": {"$gte": since},
                "event": {"$in": list(_POSITIVE_EVENTS + _NEGATIVE_EVENTS)},
            }
        },
        {
            "$group": {
                "_id": "$order_id",
                "positive": {
                    "$max": {
                        "$cond": [{"$in": ["$event", list(_POSITIVE_EVENTS)]}, 1, 0]
                    }
                },
                "negative": {
                    "$max": {
                        "$cond": [{"$in": ["$event", list(_NEGATIVE_EVENTS)]}, 1, 0]
                    }
                },
            }
        },
        {
            "$group": {
                "_id": None,
                "positive": {"$sum": "$positive"},
                "negative": {"$sum": "$negative"},
            }
        },
    ]
    rows = await db.temp_number_events.aggregate(pipeline).to_list(length=1)
    if not rows:
        return {"positive": 0, "negative": 0, "score": 0}
    row = rows[0] or {}
    positive = int(row.get("positive") or 0)
    negative = int(row.get("negative") or 0)
    return {
        "positive": positive,
        "negative": negative,
        "score": max(0, negative - positive),
    }


async def count_recent_negative_attempts(
    *,
    user_id: int,
    service_id: str,
    provider: str,
    lookback_minutes: int,
) -> int:
    uid = int(user_id)
    service = str(service_id or "").strip()
    prov = str(provider or "").strip().lower()
    if not service or not prov:
        return 0

    minutes = max(1, int(lookback_minutes or 1))
    since = datetime.fromtimestamp(datetime.now(UTC).timestamp() - (minutes * 60), tz=UTC)

    pipeline = [
        {
            "$match": {
                "user_id": uid,
                "service_id": service,
                "provider": prov,
                "created_at": {"$gte": since},
                "event": {"$in": list(_NEGATIVE_EVENTS)},
            }
        },
        {"$group": {"_id": "$order_id"}},
        {"$count": "attempts"},
    ]
    rows = await db.temp_number_events.aggregate(pipeline).to_list(length=1)
    if not rows:
        return 0
    return int((rows[0] or {}).get("attempts") or 0)


async def get_active_user_temp_lock(
    *,
    user_id: int,
    service_id: str,
    provider: str,
    lock_type: str,
) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    doc = await db.temp_number_user_locks.find_one(
        {
            "user_id": int(user_id),
            "service_id": str(service_id or "").strip(),
            "provider": str(provider or "").strip().lower(),
            "lock_type": str(lock_type or "").strip().lower(),
            "expires_at": {"$gt": now},
        }
    )
    return doc


async def set_user_temp_lock(
    *,
    user_id: int,
    service_id: str,
    provider: str,
    lock_type: str,
    ttl_sec: int,
    reason: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    safe_ttl = max(1, int(ttl_sec or 1))
    expires_at = datetime.fromtimestamp(now.timestamp() + safe_ttl, tz=UTC)
    doc = {
        "user_id": int(user_id),
        "service_id": str(service_id or "").strip(),
        "provider": str(provider or "").strip().lower(),
        "lock_type": str(lock_type or "").strip().lower(),
        "reason": str(reason or "").strip(),
        "payload": dict(payload or {}),
        "updated_at": now,
        "expires_at": expires_at,
    }
    await db.temp_number_user_locks.update_one(
        {
            "user_id": doc["user_id"],
            "service_id": doc["service_id"],
            "provider": doc["provider"],
            "lock_type": doc["lock_type"],
        },
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return doc
