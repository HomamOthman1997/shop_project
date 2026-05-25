from __future__ import annotations

from typing import Any

from database.mongo import db


async def get_idempotent_response(*, user_id: int, key: str, operation: str) -> dict[str, Any] | None:
    raw_key = str(key or "").strip()
    if not raw_key:
        return None
    row = await db.api_idempotency_keys.find_one(
        {"user_id": int(user_id), "key": raw_key, "operation": str(operation or "").strip()}
    )
    response = row.get("response") if isinstance(row, dict) else None
    return response if isinstance(response, dict) else None


async def save_idempotent_response(*, user_id: int, key: str, operation: str, response: dict[str, Any]) -> None:
    raw_key = str(key or "").strip()
    if not raw_key:
        return
    from services.numbers.shared.temp_order import _utc_now

    await db.api_idempotency_keys.update_one(
        {"user_id": int(user_id), "key": raw_key, "operation": str(operation or "").strip()},
        {
            "$set": {
                "user_id": int(user_id),
                "key": raw_key,
                "operation": str(operation or "").strip(),
                "response": response,
                "updated_at": _utc_now(),
            },
            "$setOnInsert": {"created_at": _utc_now()},
        },
        upsert=True,
    )
