from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from database.mongo import db

KEY_PREFIX = "ph_live_"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(str(api_key or "").strip().encode("utf-8")).hexdigest()


def new_api_key() -> str:
    return f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"


def constant_time_key_match(raw_key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(raw_key), str(stored_hash or ""))


async def create_api_key(
    *,
    user_id: int,
    reseller_id: int | None = None,
    name: str = "",
    scopes: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, dict[str, Any]]:
    api_key = new_api_key()
    now = datetime.now(UTC)
    doc = {
        "key_hash": hash_api_key(api_key),
        "prefix": api_key[:12],
        "user_id": int(user_id),
        "reseller_id": int(reseller_id or user_id),
        "name": str(name or "").strip(),
        "scopes": sorted({str(scope).strip() for scope in (scopes or []) if str(scope).strip()}),
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "last_used_at": None,
    }
    result = await db.api_keys.insert_one(doc)
    doc["_id"] = result.inserted_id
    return api_key, doc


async def find_active_api_key(api_key: str) -> dict[str, Any] | None:
    raw = str(api_key or "").strip()
    if not raw:
        return None
    doc = await db.api_keys.find_one({"key_hash": hash_api_key(raw), "status": "active"})
    if not isinstance(doc, dict):
        return None
    if not constant_time_key_match(raw, str(doc.get("key_hash") or "")):
        return None
    await db.api_keys.update_one({"_id": doc["_id"]}, {"$set": {"last_used_at": datetime.now(UTC)}})
    return doc


def serialize_api_key_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc.get("_id") or ""),
        "prefix": str(doc.get("prefix") or ""),
        "name": str(doc.get("name") or ""),
        "user_id": int(doc.get("user_id") or 0),
        "reseller_id": int(doc.get("reseller_id") or 0),
        "scopes": [str(scope) for scope in (doc.get("scopes") or [])],
        "status": str(doc.get("status") or ""),
        "created_at": doc.get("created_at").isoformat() if hasattr(doc.get("created_at"), "isoformat") else None,
        "updated_at": doc.get("updated_at").isoformat() if hasattr(doc.get("updated_at"), "isoformat") else None,
        "last_used_at": doc.get("last_used_at").isoformat() if hasattr(doc.get("last_used_at"), "isoformat") else None,
    }


async def list_api_keys(*, reseller_id: int) -> list[dict[str, Any]]:
    cursor = db.api_keys.find({"reseller_id": int(reseller_id)}).sort("created_at", -1)
    return [serialize_api_key_doc(doc) async for doc in cursor]


async def revoke_api_key(*, key_id: str, reseller_id: int | None = None) -> bool:
    try:
        oid = ObjectId(str(key_id))
    except Exception:
        return False
    query: dict[str, Any] = {"_id": oid}
    if reseller_id is not None:
        query["reseller_id"] = int(reseller_id)
    result = await db.api_keys.update_one(
        query,
        {"$set": {"status": "revoked", "revoked_at": datetime.now(UTC), "updated_at": datetime.now(UTC)}},
    )
    return bool(result.modified_count)


def has_scope(doc: dict[str, Any], required_scope: str) -> bool:
    required = str(required_scope or "").strip()
    scopes = {str(scope).strip() for scope in (doc.get("scopes") or []) if str(scope).strip()}
    return "*" in scopes or required in scopes
