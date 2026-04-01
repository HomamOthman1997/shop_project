from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database.mongo import db


_DOC_ID = "bot_logs_target"


async def bind_bot_logs_target(*, chat_id: int, message_thread_id: int | None = None) -> None:
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


async def get_bot_logs_target() -> dict[str, Any] | None:
    try:
        doc = await db.system_settings.find_one({"_id": _DOC_ID}) or {}
    except Exception:
        # Logging must not crash runtime when DB is temporarily unreachable.
        return None
    chat_id = doc.get("chat_id")
    if not isinstance(chat_id, int):
        return None
    thread_id = doc.get("message_thread_id")
    return {
        "chat_id": int(chat_id),
        "message_thread_id": int(thread_id) if isinstance(thread_id, int) else None,
        "updated_at": doc.get("updated_at"),
    }
