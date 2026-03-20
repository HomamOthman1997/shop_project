
from datetime import UTC, datetime
from database.mongo import db
from config import settings


async def add_bot(token: str, owner_id: int, bot_id: int):
    await db.bots.insert_one({
        "bot_id": bot_id,
        "token": token,
        "owner_id": owner_id,
        "active": True,
        "created_at": datetime.now(UTC),
        "webhook_url": None,
        "settings": {
            "language": "en",
            "subscription_channel": None,
            "version": settings.bot_version
        }
    })


async def get_active_bots():
    return await db.bots.find({"active": True}).to_list(None)


async def deactivate_bot(bot_id: int):
    await db.bots.update_one(
        {"bot_id": bot_id},
        {"$set": {"active": False}}
    )
async def get_bot_settings(bot_id: int):
    bot = await db.bots.find_one({"bot_id": bot_id})
    if not bot:                     # âœ”ï¸ Ø­Ù…Ø§ÙŠØ© Ù…Ù† None
        return {}
    return bot.get("settings", {})  # âœ”ï¸ Ø¢Ù…Ù†Ø© Ø§Ù„Ø¢Ù†


async def update_bot_channel(bot_id: int, channel: str):
    await db.bots.update_one(
        {"bot_id": bot_id},
        {"$set": {"settings.subscription_channel": channel}}
    )
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
    # In this project owner_id is the reseller account that owns this bot.
    return bot.get("owner_id")

async def update_reseller_info(bot_id, fullname, phone, address):
    await db.bots.update_one(
        {"bot_id": bot_id},
        {"$set": {
            "reseller.full_name": fullname,
            "reseller.phone": phone,
            "reseller.address": address
        }}
    )

async def verify_bot(bot_id):
    await db.bots.update_one(
        {"bot_id": bot_id},
        {"$set": {"reseller.verified": True}}
    )



