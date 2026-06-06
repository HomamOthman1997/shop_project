from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from typing import Any

from .mongo import db

_REDACTED = "[redacted]"
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "login",
    "pass",
    "passwd",
    "password",
    "secret",
    "token",
    "username",
}
_INLINE_SECRET_RE = re.compile(
    r"(?i)(['\"]?(?:api[_-]?key|authorization|credential(?:s)?|login|pass(?:wd|word)?|secret|token|username)['\"]?\s*[:=]\s*)"
    r"(['\"]?)[^,'\"\s}\]]+\2"
)
_URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@")


def _sanitize_text(value: Any, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    text = _URL_CREDENTIAL_RE.sub(r"\1[redacted]@", text)
    text = _INLINE_SECRET_RE.sub(rf"\1{_REDACTED}", text)
    return text[:limit]


def _sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 5:
        return "[truncated]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:50]:
            key = str(raw_key)
            if key.strip().lower().replace("-", "_") in _SENSITIVE_KEYS:
                sanitized[key] = _REDACTED
            else:
                sanitized[key] = _sanitize_value(raw_value, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item, depth=depth + 1) for item in list(value)[:50]]
    if isinstance(value, str):
        return _sanitize_text(value, limit=500)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_text(value, limit=500)


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
            "reason": _sanitize_text(reason).lower() if reason else "",
            "extra": _sanitize_value(dict(extra or {})),
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
