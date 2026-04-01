from __future__ import annotations

from datetime import UTC, datetime

from database.mongo import db


_DOC_ID = "numbers_pricing_settings"


def _sanitize_percent(value: float) -> float:
    try:
        pct = float(value)
    except Exception:
        pct = 0.0
    # Keep a sane range for safety.
    return max(0.0, min(500.0, pct))


async def get_numbers_markup_percent(default_value: float = 0.0) -> float:
    doc = await db.system_settings.find_one({"_id": _DOC_ID}, {"markup_percent": 1})
    if not doc or doc.get("markup_percent") is None:
        return _sanitize_percent(default_value)
    return _sanitize_percent(float(doc.get("markup_percent")))


async def set_numbers_markup_percent(value: float) -> float:
    pct = _sanitize_percent(value)
    await db.system_settings.update_one(
        {"_id": _DOC_ID},
        {
            "$set": {
                "markup_percent": pct,
                "updated_at": datetime.now(UTC),
            }
        },
        upsert=True,
    )
    return pct
