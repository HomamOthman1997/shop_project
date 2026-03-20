from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database.mongo import db


_DOC_ID = "provider_balance_alert_settings"
_DEFAULT_THRESHOLD_USD = 1.0
_DEFAULT_COOLDOWN_MINUTES = 45


def _sanitize_threshold(value: float | int | str | None) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = _DEFAULT_THRESHOLD_USD
    return max(0.01, min(10000.0, parsed))


def _sanitize_cooldown_minutes(value: float | int | str | None) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = _DEFAULT_COOLDOWN_MINUTES
    return max(5, min(1440, parsed))


async def get_provider_balance_alert_settings() -> dict[str, Any]:
    doc = await db.system_settings.find_one({"_id": _DOC_ID}) or {}
    enabled = bool(doc.get("enabled", True))
    threshold_usd = _sanitize_threshold(doc.get("threshold_usd"))
    cooldown_minutes = _sanitize_cooldown_minutes(doc.get("cooldown_minutes"))
    chat_id = doc.get("chat_id")
    thread_id = doc.get("message_thread_id")
    if not isinstance(chat_id, int):
        chat_id = None
    if not isinstance(thread_id, int):
        thread_id = None
    return {
        "enabled": enabled,
        "threshold_usd": threshold_usd,
        "cooldown_minutes": cooldown_minutes,
        "chat_id": chat_id,
        "message_thread_id": thread_id,
    }


async def set_provider_balance_alert_threshold(threshold_usd: float) -> float:
    threshold = _sanitize_threshold(threshold_usd)
    await db.system_settings.update_one(
        {"_id": _DOC_ID},
        {"$set": {"threshold_usd": threshold, "updated_at": datetime.now(UTC)}},
        upsert=True,
    )
    return threshold


async def set_provider_balance_alert_enabled(enabled: bool) -> bool:
    value = bool(enabled)
    await db.system_settings.update_one(
        {"_id": _DOC_ID},
        {"$set": {"enabled": value, "updated_at": datetime.now(UTC)}},
        upsert=True,
    )
    return value


async def toggle_provider_balance_alert_enabled() -> bool:
    current = await get_provider_balance_alert_settings()
    return await set_provider_balance_alert_enabled(not bool(current.get("enabled")))


async def bind_provider_balance_alert_target(chat_id: int, message_thread_id: int | None) -> None:
    await db.system_settings.update_one(
        {"_id": _DOC_ID},
        {
            "$set": {
                "chat_id": int(chat_id),
                "message_thread_id": int(message_thread_id) if isinstance(message_thread_id, int) else None,
                "updated_at": datetime.now(UTC),
            }
        },
        upsert=True,
    )

