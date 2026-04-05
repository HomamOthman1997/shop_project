from __future__ import annotations

from aiogram import Bot, types

_STICKER_SET_NAME = "PHanToOoM_ST"
_DEFAULT_LOADING_STICKER_FILE_ID = "CAACAgQAAxkBAAIIPWnRwmAIzduezmiLz84dhY0mnWL2AAKNHwAC3ySQUvS-IVAgK2OLOwQ"
_STICKER_FILE_IDS: dict[int, str] = {}


async def resolve_loading_sticker_file_id(bot: Bot) -> str | None:
    bot_id = int((await bot.get_me()).id)
    cached = _STICKER_FILE_IDS.get(bot_id)
    if cached:
        return cached
    if _DEFAULT_LOADING_STICKER_FILE_ID:
        _STICKER_FILE_IDS[bot_id] = _DEFAULT_LOADING_STICKER_FILE_ID
        return _DEFAULT_LOADING_STICKER_FILE_ID
    try:
        sticker_set = await bot.get_sticker_set(_STICKER_SET_NAME)
    except Exception:
        return None
    stickers = list(getattr(sticker_set, "stickers", []) or [])
    if not stickers:
        return None
    file_id = str(getattr(stickers[0], "file_id", "") or "").strip()
    if not file_id:
        return None
    _STICKER_FILE_IDS[bot_id] = file_id
    return file_id


async def send_loading_sticker(
    message: types.Message,
    *,
    remove_keyboard: bool = False,
    fallback_text: str = "⏳",
) -> types.Message | None:
    reply_markup = types.ReplyKeyboardRemove() if remove_keyboard else None
    file_id = await resolve_loading_sticker_file_id(message.bot)
    if file_id:
        try:
            return await message.answer_sticker(file_id, reply_markup=reply_markup)
        except Exception:
            pass
    try:
        return await message.answer(fallback_text, reply_markup=reply_markup)
    except Exception:
        return None
