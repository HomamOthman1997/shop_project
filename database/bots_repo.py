from datetime import UTC, datetime

from config import settings
from database.mongo import db
from services.subscriptions.bot_subscription_service import (
    activate_bot_subscription,
    bot_subscription_is_blocked,
    build_initial_subscription_for_owner,
    get_bot_subscription,
    get_bot_subscription_status,
    get_subscription_plan_options,
    mark_bot_subscription_grace_notice,
    run_bot_subscription_sweep,
    set_bot_subscription_plan,
    sync_bot_subscription,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def add_bot(token: str, owner_id: int, bot_id: int):
    now = _utc_now()
    subscription = await build_initial_subscription_for_owner(int(owner_id), now=now)
    await db.bots.insert_one(
        {
            "bot_id": bot_id,
            "token": token,
            "owner_id": owner_id,
            "active": True,
            "created_at": now,
            "webhook_url": None,
            "subscription": subscription,
            "settings": {
                "language": "en",
                "subscription_channel": None,
                "version": settings.bot_version,
            },
        }
    )
    await sync_bot_subscription(int(bot_id), collect_due=True)


async def get_active_bots():
    return await db.bots.find({"active": True}).to_list(None)


async def deactivate_bot(bot_id: int):
    await db.bots.update_one({"bot_id": bot_id}, {"$set": {"active": False}})


async def get_bot_settings(bot_id: int):
    bot = await db.bots.find_one({"bot_id": bot_id})
    if not bot:
        return {}
    return bot.get("settings", {})


async def update_bot_channel(bot_id: int, channel: str):
    await db.bots.update_one({"bot_id": bot_id}, {"$set": {"settings.subscription_channel": channel}})


async def get_verified_bots():
    return await db.bots.find({"active": True, "reseller.verified": True}).to_list(None)


async def get_bot_token(bot_id: int):
    bot = await db.bots.find_one({"bot_id": bot_id})
    return bot["token"]


async def get_bot_by_id(bot_id: int):
    return await db.bots.find_one({"bot_id": bot_id, "active": True})


async def get_reseller_id_for_bot(bot_id: int):
    bot = await get_bot_by_id(bot_id)
    if not bot:
        return None
    return bot.get("owner_id")


async def update_reseller_info(bot_id, fullname, phone, address):
    await db.bots.update_one(
        {"bot_id": bot_id},
        {
            "$set": {
                "reseller.full_name": fullname,
                "reseller.phone": phone,
                "reseller.address": address,
            }
        },
    )


async def verify_bot(bot_id):
    await db.bots.update_one({"bot_id": bot_id}, {"$set": {"reseller.verified": True}})
