from __future__ import annotations

from datetime import UTC, datetime, timedelta
import time
from typing import Any

from pymongo import ReturnDocument

from .mongo import db


async def bootstrap_website_auth_indexes() -> None:
    await db.website_accounts.create_index("email_normalized", unique=True, background=True)
    await db.website_accounts.create_index("telegram_id", unique=True, sparse=True, background=True)
    await db.website_sessions.create_index("token_hash", unique=True, background=True)
    await db.website_sessions.create_index("expires_at", expireAfterSeconds=0, background=True)
    await db.telegram_link_tokens.create_index("token_hash", unique=True, background=True)
    await db.telegram_link_tokens.create_index("expires_at", expireAfterSeconds=0, background=True)
    await db.email_verification_tokens.create_index("expires_at", expireAfterSeconds=0, background=True)
    await db.email_verification_tokens.create_index([("account_id", 1), ("created_at", -1)], background=True)
    await db.website_auth_rate_limits.create_index("expires_at", expireAfterSeconds=0, background=True)
    await db.identity_verification_requests.create_index([("account_id", 1), ("created_at", -1)], background=True)
    await db.identity_verification_requests.create_index([("status", 1), ("created_at", 1)], background=True)
    await db.owner_admin_audit.create_index([("created_at", -1)], background=True)
    await db.owner_admin_audit.create_index([("actor_id", 1), ("created_at", -1)], background=True)
    await db.owner_admin_audit.create_index([("action", 1), ("created_at", -1)], background=True)


async def allocate_website_customer_id() -> int:
    doc = await db.system_counters.find_one_and_update(
        {"_id": "website_customer_id"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return 900_000_000_000 + int((doc or {}).get("value") or 0)


async def find_website_account_by_email(email_normalized: str) -> dict[str, Any] | None:
    return await db.website_accounts.find_one({"email_normalized": email_normalized})


async def find_website_account_by_id(account_id: str) -> dict[str, Any] | None:
    return await db.website_accounts.find_one({"_id": account_id})


async def find_website_account_by_telegram_id(telegram_id: int) -> dict[str, Any] | None:
    return await db.website_accounts.find_one({"telegram_id": int(telegram_id)})


async def create_website_account(doc: dict[str, Any]) -> None:
    await db.website_accounts.insert_one(doc)


async def create_website_user_profile(*, customer_id: int, email: str, now: datetime) -> None:
    await db.users.update_one(
        {"telegram_id": int(customer_id)},
        {
            "$setOnInsert": {
                "telegram_id": int(customer_id),
                "username": "",
                "email": email,
                "reseller_id": int(customer_id),
                "language": "ar",
                "bot_version": 0,
                "banned": False,
                "identity_source": "website",
                "created_at": now,
            }
        },
        upsert=True,
    )


async def create_website_session(doc: dict[str, Any]) -> None:
    await db.website_sessions.insert_one(doc)


async def find_website_session(token_hash: str, *, now: datetime) -> dict[str, Any] | None:
    return await db.website_sessions.find_one({"token_hash": token_hash, "expires_at": {"$gt": now}})


async def delete_website_session(token_hash: str) -> None:
    await db.website_sessions.delete_one({"token_hash": token_hash})


async def create_telegram_link_token(doc: dict[str, Any]) -> None:
    await db.telegram_link_tokens.insert_one(doc)


async def consume_telegram_link_token(token_hash: str, *, now: datetime) -> dict[str, Any] | None:
    return await db.telegram_link_tokens.find_one_and_update(
        {
            "token_hash": token_hash,
            "expires_at": {"$gt": now},
            "used_at": None,
        },
        {"$set": {"used_at": now}},
        return_document=ReturnDocument.AFTER,
    )


async def link_telegram_account(account_id: str, telegram_id: int, *, now: datetime) -> bool:
    result = await db.website_accounts.update_one(
        {
            "_id": account_id,
            "$or": [{"telegram_id": {"$exists": False}}, {"telegram_id": None}, {"telegram_id": telegram_id}],
        },
        {"$set": {"telegram_id": telegram_id, "telegram_linked_at": now, "updated_at": now}},
    )
    return bool(result.modified_count or result.matched_count)


async def unlink_telegram_account(account_id: str, *, now: datetime) -> None:
    await db.website_accounts.update_one(
        {"_id": account_id},
        {
            "$unset": {"telegram_id": "", "telegram_linked_at": ""},
            "$set": {"updated_at": now},
        },
    )


async def update_website_account_language(account_id: str, customer_id: int, language: str, *, now: datetime) -> dict[str, Any] | None:
    account = await db.website_accounts.find_one_and_update(
        {"_id": account_id},
        {"$set": {"language": language, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if int(customer_id or 0) > 0:
        await db.users.update_one(
            {"telegram_id": int(customer_id), "identity_source": "website"},
            {"$set": {"language": language, "updated_at": now}},
        )
    return account


async def create_email_verification_token(doc: dict[str, Any]) -> None:
    await db.email_verification_tokens.insert_one(doc)


async def consume_email_verification_token(account_id: str, code_hash: str, *, now: datetime) -> dict[str, Any] | None:
    return await db.email_verification_tokens.find_one_and_update(
        {
            "account_id": account_id,
            "code_hash": code_hash,
            "expires_at": {"$gt": now},
            "used_at": None,
        },
        {"$set": {"used_at": now}},
        sort=[("created_at", -1)],
        return_document=ReturnDocument.AFTER,
    )


async def mark_website_email_verified(account_id: str, *, now: datetime) -> dict[str, Any] | None:
    account = await db.website_accounts.find_one_and_update(
        {"_id": account_id},
        {
            "$set": {
                "email_verified_at": now,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    customer_id = int((account or {}).get("customer_id") or 0)
    if customer_id > 0:
        await db.users.update_one(
            {"telegram_id": customer_id, "identity_source": "website"},
            {"$set": {"email_verified_at": now}},
        )
    return account


async def create_identity_verification_request(doc: dict[str, Any]) -> None:
    await db.identity_verification_requests.insert_one(doc)
    await db.website_accounts.update_one(
        {"_id": doc["account_id"]},
        {"$set": {"identity_status": "pending", "identity_updated_at": doc["created_at"], "updated_at": doc["created_at"]}},
    )


async def find_latest_identity_verification(account_id: str) -> dict[str, Any] | None:
    return await db.identity_verification_requests.find_one({"account_id": account_id}, sort=[("created_at", -1)])


async def consume_website_auth_rate_limit(subject_hash: str, *, bucket: str, limit: int, window_seconds: int = 60) -> bool:
    now_ts = int(time.time())
    window = now_ts - (now_ts % int(window_seconds))
    expires_at = datetime.now(UTC) + timedelta(seconds=int(window_seconds) * 2)
    doc = await db.website_auth_rate_limits.find_one_and_update(
        {"_id": f"{bucket}:{subject_hash}:{window}"},
        {
            "$setOnInsert": {
                "bucket": bucket,
                "window_start": window,
                "expires_at": expires_at,
            },
            "$inc": {"count": 1},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int((doc or {}).get("count") or 0) <= int(limit)
