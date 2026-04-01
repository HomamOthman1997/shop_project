from datetime import UTC, datetime

from database.mongo import db

SUPPORT_TOPIC_KEYS = {
    "proxies": "owner_support_proxies",
    "numbers": "owner_support_numbers",
    "services": "owner_support_services",
    "user_balance": "owner_support_user_balance",
}


def _doc_id(category: str) -> str:
    key = str(category or "").strip().lower()
    if key not in SUPPORT_TOPIC_KEYS:
        raise ValueError(f"Unsupported support category: {category}")
    return SUPPORT_TOPIC_KEYS[key]


async def bind_support_target(category: str, *, chat_id: int, message_thread_id: int | None) -> None:
    await db.system_settings.update_one(
        {"_id": _doc_id(category)},
        {
            "$set": {
                "chat_id": int(chat_id),
                "message_thread_id": int(message_thread_id) if message_thread_id is not None else None,
                "updated_at": datetime.now(UTC),
            }
        },
        upsert=True,
    )


async def get_support_target(category: str) -> dict | None:
    if str(category or "").strip().lower() == "services":
        await migrate_legacy_games_support_topic()
    return await db.system_settings.find_one({"_id": _doc_id(category)})


async def get_all_support_targets() -> dict[str, dict]:
    rows = await db.system_settings.find({"_id": {"$in": list(SUPPORT_TOPIC_KEYS.values())}}).to_list(None)
    by_id = {str(row.get("_id")): row for row in rows}
    result: dict[str, dict] = {}
    for category, doc_id in SUPPORT_TOPIC_KEYS.items():
        result[category] = by_id.get(doc_id) or {}
    return result


async def migrate_legacy_games_support_topic() -> None:
    legacy = await db.system_settings.find_one({"_id": "owner_support_games"})
    current = await db.system_settings.find_one({"_id": "owner_support_services"})
    if legacy and not current:
        await db.system_settings.update_one(
            {"_id": "owner_support_services"},
            {
                "$set": {
                    "chat_id": legacy.get("chat_id"),
                    "message_thread_id": legacy.get("message_thread_id"),
                    "updated_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
    if legacy:
        await db.system_settings.delete_one({"_id": "owner_support_games"})
