from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from config import settings
from database.mongo import db

_REFERRAL_CONFIG_ID = "referral_config"


def _default_referral_config() -> dict[str, Any]:
    return {
        "_id": _REFERRAL_CONFIG_ID,
        "enabled": bool(getattr(settings, "referral_enabled", False)),
        "reward_percent": float(getattr(settings, "referral_reward_percent", 0.0) or 0.0),
        "max_reward_usd": float(getattr(settings, "referral_max_reward_usd", 0.0) or 0.0),
        "min_order_usd": float(getattr(settings, "referral_min_order_usd", 0.0) or 0.0),
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


async def get_referral_config() -> dict[str, Any]:
    doc = await db.system_settings.find_one({"_id": _REFERRAL_CONFIG_ID})
    if isinstance(doc, dict):
        return doc
    default_doc = _default_referral_config()
    await db.system_settings.update_one(
        {"_id": _REFERRAL_CONFIG_ID},
        {"$setOnInsert": default_doc},
        upsert=True,
    )
    return await db.system_settings.find_one({"_id": _REFERRAL_CONFIG_ID}) or default_doc


async def update_referral_config(**patch: Any) -> dict[str, Any]:
    updates = {str(k): v for k, v in (patch or {}).items() if k}
    updates["updated_at"] = datetime.now(UTC)
    await db.system_settings.update_one(
        {"_id": _REFERRAL_CONFIG_ID},
        {"$set": updates, "$setOnInsert": _default_referral_config()},
        upsert=True,
    )
    return await get_referral_config()
