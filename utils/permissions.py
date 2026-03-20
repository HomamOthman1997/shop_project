from aiogram import types

from config import OWNER_ID
from database.bots_repo import db
from database.user_repo import get_user
from utils.translations import t


async def is_reseller(user_id: int, bot_id: int = None) -> bool:
    query = {"owner_id": user_id, "active": True}
    if bot_id is not None:
        query["bot_id"] = bot_id
    bot = await db.bots.find_one(query)
    return bool(bot)


async def reseller_only(message: types.Message):
    current_bot_id = (await message.bot.get_me()).id
    if await is_reseller(message.from_user.id, bot_id=current_bot_id):
        return True
    try:
        await message.answer("This command is available to resellers only.")
    except Exception:
        pass
    return False


async def owner_only(message: types.Message):
    if int(message.from_user.id) == int(OWNER_ID):
        return True

    lang = "ar"
    try:
        user = await get_user(message.from_user.id)
        if user:
            lang = user.get("language", "ar")
    except Exception:
        pass

    try:
        await message.answer(t(lang, "no_permission"))
    except Exception:
        await message.answer("You do not have permission to use this command.")

    return False
