from __future__ import annotations

from database.mongo import db


async def bootstrap_platform_api_indexes() -> None:
    await db.api_keys.create_index("key_hash", unique=True, background=True)
    await db.api_keys.create_index([("reseller_id", 1), ("status", 1), ("created_at", -1)], background=True)
    await db.api_keys.create_index([("user_id", 1), ("status", 1)], background=True)
    await db.api_rate_limits.create_index([("api_key_id", 1), ("bucket", 1), ("reset_at", 1)], background=True)
    await db.api_rate_limits.create_index("expires_at", expireAfterSeconds=0, background=True)
    await db.numbers_api_idempotency_keys.create_index(
        [("user_id", 1), ("key", 1), ("operation", 1)],
        unique=True,
        background=True,
    )
    await db.numbers_api_idempotency_keys.create_index([("updated_at", -1)], background=True)
