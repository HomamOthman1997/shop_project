
import asyncio
import os
import sys
from datetime import UTC, datetime

# Ø£Ø¶Ù Ù…Ø³Ø§Ø± Ø§Ù„Ù…Ø´Ø±ÙˆØ¹ Ø§Ù„Ø¬Ø°Ø±ÙŠ Ø­ØªÙ‰ ØªØ¹Ù…Ù„ import database Ø¨Ø´ÙƒÙ„ ØµØ­ÙŠØ­
root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if root not in sys.path:
    sys.path.insert(0, root)

from database.mongo import db
from aiogram import Bot

async def add_first_bot(token: str, owner_id: int):
    bot = Bot(token=token)
    me = await bot.get_me()
    bot_id = me.id
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
            "version": 1
        },
        "reseller": {"verified": True}
    })
    print(f"ØªÙ…Øª Ø¥Ø¶Ø§ÙØ© Ø£ÙˆÙ„ Ø¨ÙˆØª Ø¨Ù†Ø¬Ø§Ø­! Bot ID: {bot_id}")

if __name__ == "__main__":
    TOKEN = input("Ø§Ø¯Ø®Ù„ ØªÙˆÙƒÙ† Ø§Ù„Ø¨ÙˆØª: ").strip()
    OWNER_ID = int(input("Ø§Ø¯Ø®Ù„ Telegram User ID Ù„ØµØ§Ø­Ø¨ Ø§Ù„Ø±ÙŠØ³ÙŠÙ„Ø± (ØµØ§Ø­Ø¨ API): ").strip())
    asyncio.run(add_first_bot(TOKEN, OWNER_ID))

