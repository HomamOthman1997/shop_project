from aiogram import types

from config import OWNER_ID
from database.bots_repo import db
from database.user_repo import get_user
from utils.translations import t


async def is_reseller(user_id: int, bot_id: int | None = None) -> bool:
    query = {"owner_id": user_id, "active": True}
    if bot_id is not None:
        query["bot_id"] = bot_id
    bot = await db.bots.find_one(query)
    return bool(bot)


async def _resolve_user_lang(user_id: int, default: str = "ar") -> str:
    try:
        user = await get_user(user_id)
    except Exception:
        return default
    if not user:
        return default
    return str(user.get("language", default) or default)


async def _safe_answer(message: types.Message, lang: str, key: str, *, fallback_lang: str | None = None) -> None:
    try:
        await message.answer(t(lang, key))
    except Exception:
        if fallback_lang:
            await message.answer(t(fallback_lang, key))


async def reseller_only(message: types.Message) -> bool:
    current_bot_id = (await message.bot.get_me()).id
    if await is_reseller(message.from_user.id, bot_id=current_bot_id):
        return True
    lang = await _resolve_user_lang(message.from_user.id)
    await _safe_answer(message, lang, "reseller_only_command")
    return False


async def owner_only(message: types.Message) -> bool:
    if int(message.from_user.id) == int(OWNER_ID):
        return True

    lang = await _resolve_user_lang(message.from_user.id)
    await _safe_answer(message, lang, "no_permission", fallback_lang="en")

    return False
