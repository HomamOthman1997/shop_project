from datetime import UTC, datetime

from config import settings
from .mongo import db


async def get_user(telegram_id: int):
    return await db.users.find_one({"telegram_id": telegram_id})


async def create_user(telegram_id: int, username: str, reseller_id: int = None):
    user = {
        "telegram_id": telegram_id,
        "username": username,
        "reseller_id": reseller_id,
        "language": "en",
        "bot_version": settings.bot_version,
        "banned": False,
        "created_at": datetime.now(UTC),
    }
    await db.users.insert_one(user)
    return user


async def get_user_reseller(telegram_id: int):
    user = await db.users.find_one({"telegram_id": telegram_id})
    return user.get("reseller_id") if user else None


async def get_user_reseller_for_bot(telegram_id: int, bot_id: int):
    link = await db.user_reseller_links.find_one({"telegram_id": int(telegram_id), "bot_id": int(bot_id)})
    if link and link.get("reseller_id") is not None:
        return int(link.get("reseller_id"))
    return None


async def update_user_language(telegram_id: int, language: str):
    await db.users.update_one({"telegram_id": telegram_id}, {"$set": {"language": language}})


async def update_user_version(telegram_id: int, version: int):
    await db.users.update_one({"telegram_id": telegram_id}, {"$set": {"bot_version": version}})


async def get_user_by_username(username: str):
    return await db.users.find_one({"username": username})


async def set_user_reseller(telegram_id: int, reseller_id: int):
    await db.users.update_one({"telegram_id": telegram_id}, {"$set": {"reseller_id": reseller_id}})


async def set_user_reseller_for_bot(telegram_id: int, bot_id: int, reseller_id: int):
    now = datetime.now(UTC)
    await db.user_reseller_links.update_one(
        {"telegram_id": int(telegram_id), "bot_id": int(bot_id)},
        {
            "$set": {
                "reseller_id": int(reseller_id),
                "updated_at": now,
            },
            "$setOnInsert": {
                "telegram_id": int(telegram_id),
                "bot_id": int(bot_id),
                "created_at": now,
            },
        },
        upsert=True,
    )


async def get_user_reseller_links(telegram_id: int) -> list[dict]:
    return await db.user_reseller_links.find({"telegram_id": int(telegram_id)}).to_list(None)


async def bootstrap_user_links_indexes():
    await db.user_reseller_links.create_index(
        [("telegram_id", 1), ("bot_id", 1)],
        unique=True,
        background=True,
    )
    await db.user_reseller_links.create_index(
        [("reseller_id", 1), ("bot_id", 1)],
        background=True,
    )


async def ban_user(telegram_id: int):
    await db.users.update_one({"telegram_id": telegram_id}, {"$set": {"banned": True}})


async def unban_user(telegram_id: int):
    await db.users.update_one({"telegram_id": telegram_id}, {"$set": {"banned": False}})

