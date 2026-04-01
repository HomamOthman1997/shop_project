from __future__ import annotations

from aiogram import types

from database.bots_repo import get_reseller_id_for_bot
from utils.bot_menu_context import send_main_bot_message


def core_service_paused_text(lang: str) -> str:
    if str(lang or "").lower().startswith("ar"):
        return "الخدمة متوقفة من قبل الادمن."
    return "This service is currently paused by the admin."


def finance_error_public_text(lang: str, code: str | None) -> str:
    normalized = str(code or "").strip()
    if normalized == "INSUFFICIENT_USER_BALANCE":
        return "الرصيد غير كاف." if str(lang or "").lower().startswith("ar") else "Insufficient balance."
    if normalized == "LOCKED":
        return "انتظر قليلا ثم أعد المحاولة." if str(lang or "").lower().startswith("ar") else "Please wait a second and try again."
    return "فشلت العملية، حاول مجددا." if str(lang or "").lower().startswith("ar") else "Request failed, try again."


async def _resolve_reseller_for_bot(bot) -> int:
    try:
        bot_id = int((await bot.get_me()).id)
    except Exception:
        return 0
    return int(await get_reseller_id_for_bot(bot_id) or 0)


async def guard_core_service_message(message: types.Message, lang: str) -> bool:
    reseller_id = await _resolve_reseller_for_bot(message.bot)
    if reseller_id <= 0:
        return True
    await send_main_bot_message(message, lang=lang)
    return False


async def guard_core_service_callback(callback: types.CallbackQuery, lang: str) -> bool:
    reseller_id = await _resolve_reseller_for_bot(callback.bot)
    if reseller_id <= 0:
        return True
    notice = "هذه الخدمة متاحة عبر البوت الرئيسي." if str(lang or "").lower().startswith("ar") else "This service is available in the main bot."
    await callback.answer(notice, show_alert=True)
    await send_main_bot_message(callback, lang=lang)
    return False
