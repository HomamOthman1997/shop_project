from __future__ import annotations

from aiogram import Bot

from config import settings
from database.bots_repo import get_bot_token
from utils.bot_menu_context import extract_bot_id_from_token


def _configured_token(bot_id: int) -> str:
    for name in ("bot_main_token", "bot_numbers_token", "bot_digital_products_token", "bot_card_ex_token", "bot_admin_token"):
        token = str(getattr(settings, name, "") or "").strip()
        if token and extract_bot_id_from_token(token) == int(bot_id):
            return token
    return ""


async def send_ticket_message(ticket: dict, text: str) -> bool:
    source_bot_id = int((ticket or {}).get("source_bot_id") or 0)
    user_id = int((ticket or {}).get("user_id") or 0)
    if source_bot_id <= 0 or user_id <= 0:
        return False
    token = _configured_token(source_bot_id)
    if not token:
        try:
            token = str(await get_bot_token(source_bot_id) or "").strip()
        except Exception:
            token = ""
    if not token:
        return False
    bot = Bot(token=token)
    try:
        await bot.send_message(chat_id=user_id, text=str(text))
        return True
    finally:
        await bot.session.close()
