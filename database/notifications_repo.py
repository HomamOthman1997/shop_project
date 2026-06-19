"""In-app notification center — one feed per customer, one shared owner feed.

Events (new chat message, order status, identity decision, …) are written here
so both the customer and the owner can see "something new happened" via a bell
with an unread count. Emitting is best-effort: a failure here must never break
the action that triggered it.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from database.mongo import db

logger = logging.getLogger(__name__)

# All owners share a single feed (there is effectively one storefront owner).
OWNER_RECIPIENT_ID = 0
RECIPIENT_CUSTOMER = "customer"
RECIPIENT_OWNER = "owner"


def _now() -> datetime:
    return datetime.now(UTC)


async def bootstrap_notifications_indexes() -> None:
    await db.notifications.create_index(
        [("recipient_type", 1), ("recipient_id", 1), ("created_at", -1)], background=True
    )
    await db.notifications.create_index(
        [("recipient_type", 1), ("recipient_id", 1), ("read", 1)], background=True
    )
    # Bound storage growth: a read notification is purged 30 days after it was read.
    # Unread notifications have no `read_at` field, so MongoDB's TTL never expires them.
    await db.notifications.create_index("read_at", expireAfterSeconds=30 * 24 * 3600, background=True)


async def push_notification(
    *,
    recipient_type: str,
    recipient_id: int,
    kind: str,
    title: str,
    body: str = "",
    link: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    """Insert one notification. Best-effort: never raises to the caller."""
    try:
        await db.notifications.insert_one(
            {
                "recipient_type": str(recipient_type),
                "recipient_id": int(recipient_id or 0),
                "kind": str(kind),
                "title": str(title)[:200],
                "body": str(body)[:500],
                "link": str(link)[:120],
                "meta": dict(meta or {}),
                "read": False,
                "created_at": _now(),
            }
        )
    except Exception as exc:  # noqa: BLE001 - notifications must not break the flow
        logger.warning("notification_push_failed kind=%s recipient=%s/%s err=%s", kind, recipient_type, recipient_id, exc)


async def notify_customer(customer_id: int, *, kind: str, title: str, body: str = "", link: str = "", meta: dict[str, Any] | None = None) -> None:
    if int(customer_id or 0) <= 0:
        return
    await push_notification(
        recipient_type=RECIPIENT_CUSTOMER, recipient_id=int(customer_id), kind=kind, title=title, body=body, link=link, meta=meta
    )


async def notify_owner(*, kind: str, title: str, body: str = "", link: str = "", meta: dict[str, Any] | None = None) -> None:
    await push_notification(
        recipient_type=RECIPIENT_OWNER, recipient_id=OWNER_RECIPIENT_ID, kind=kind, title=title, body=body, link=link, meta=meta
    )


async def list_notifications(*, recipient_type: str, recipient_id: int, limit: int = 30) -> list[dict[str, Any]]:
    cursor = (
        db.notifications.find({"recipient_type": str(recipient_type), "recipient_id": int(recipient_id or 0)})
        .sort("created_at", -1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def unread_count(*, recipient_type: str, recipient_id: int) -> int:
    return int(
        await db.notifications.count_documents(
            {"recipient_type": str(recipient_type), "recipient_id": int(recipient_id or 0), "read": False}
        )
    )


async def mark_all_read(*, recipient_type: str, recipient_id: int) -> None:
    await db.notifications.update_many(
        {"recipient_type": str(recipient_type), "recipient_id": int(recipient_id or 0), "read": False},
        {"$set": {"read": True, "read_at": _now()}},
    )
