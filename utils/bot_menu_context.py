from __future__ import annotations

from aiogram import Bot, types

from config import settings
from database.bots_repo import get_reseller_id_for_bot
from keyboards.main_menu_kb import digital_products_main_menu, main_menu, reseller_user_main_menu
from services.cards_bot.keyboards import cards_main_menu
from utils.platform_services import render_main_product_lines
from utils.translations import t

_cached_digital_products_bot_id: int | None = None
_cached_card_ex_bot_id: int | None = None
_cached_main_bot_id: int | None = None


def extract_bot_id_from_token(token: str | None) -> int | None:
    raw = str(token or "").strip()
    if not raw or ":" not in raw:
        return None
    head = raw.split(":", 1)[0].strip()
    try:
        value = int(head)
    except Exception:
        return None
    return value if value > 0 else None


async def resolve_runtime_bot_id(bot_or_id) -> int | None:
    try:
        value = int(bot_or_id)
        return value if value > 0 else None
    except Exception:
        pass

    token = str(getattr(bot_or_id, "token", "") or "").strip()
    token_id = extract_bot_id_from_token(token)
    if token_id:
        return token_id

    try:
        me = await bot_or_id.get_me()
        value = int(me.id)
        return value if value > 0 else None
    except Exception:
        return None


async def is_reseller_owned_bot(bot_or_id) -> bool:
    bot_id = await resolve_runtime_bot_id(bot_or_id)
    if not bot_id:
        return False
    reseller_id = await get_reseller_id_for_bot(bot_id)
    return bool(reseller_id)


async def resolve_main_bot_id() -> int | None:
    global _cached_main_bot_id
    if isinstance(_cached_main_bot_id, int) and _cached_main_bot_id > 0:
        return _cached_main_bot_id
    _cached_main_bot_id = extract_bot_id_from_token(getattr(settings, "bot_main_token", ""))
    return _cached_main_bot_id


def main_bot_username() -> str:
    return str(getattr(settings, "main_bot_username", "") or "").strip().lstrip("@")


def main_bot_url(start: str | None = None) -> str | None:
    username = main_bot_username()
    if not username:
        return None
    return f"https://t.me/{username}?start={start or 'hub'}"


def digital_products_bot_username() -> str:
    return str(getattr(settings, "digital_products_bot_username", "") or "").strip().lstrip("@")


def digital_products_bot_url(start: str | None = None) -> str | None:
    username = digital_products_bot_username()
    if not username:
        return None
    return f"https://t.me/{username}?start={start or 'hub'}"


def card_ex_bot_username() -> str:
    return str(getattr(settings, "card_ex_bot_username", "") or "").strip().lstrip("@")


def card_ex_bot_url(start: str | None = None) -> str | None:
    username = card_ex_bot_username()
    if not username:
        return None
    return f"https://t.me/{username}?start={start or 'cards'}"


async def resolve_digital_products_bot_id() -> int | None:
    global _cached_digital_products_bot_id
    if isinstance(_cached_digital_products_bot_id, int) and _cached_digital_products_bot_id > 0:
        return _cached_digital_products_bot_id
    _cached_digital_products_bot_id = extract_bot_id_from_token(getattr(settings, "bot_digital_products_token", ""))
    return _cached_digital_products_bot_id


async def resolve_card_ex_bot_id() -> int | None:
    global _cached_card_ex_bot_id
    if isinstance(_cached_card_ex_bot_id, int) and _cached_card_ex_bot_id > 0:
        return _cached_card_ex_bot_id
    _cached_card_ex_bot_id = extract_bot_id_from_token(getattr(settings, "bot_card_ex_token", ""))
    return _cached_card_ex_bot_id


async def is_digital_products_bot(bot_or_id) -> bool:
    bot_id = await resolve_runtime_bot_id(bot_or_id)
    target_bot_id = await resolve_digital_products_bot_id()
    return isinstance(target_bot_id, int) and bot_id == target_bot_id


async def is_main_bot(bot_or_id) -> bool:
    bot_id = await resolve_runtime_bot_id(bot_or_id)
    target_bot_id = await resolve_main_bot_id()
    return isinstance(target_bot_id, int) and bot_id == target_bot_id


async def is_card_ex_bot(bot_or_id) -> bool:
    bot_id = await resolve_runtime_bot_id(bot_or_id)
    target_bot_id = await resolve_card_ex_bot_id()
    return isinstance(target_bot_id, int) and bot_id == target_bot_id


def main_bot_services_kb(lang: str, *, back_callback: str = "back_to_main_menu") -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = []
    main_url = main_bot_url("hub")
    create_url = main_bot_url("create_bot")
    if main_url:
        rows.append([types.InlineKeyboardButton(text=t(lang, "open_main_bot_button"), url=main_url)])
    if create_url:
        rows.append([types.InlineKeyboardButton(text=t(lang, "open_create_bot_button"), url=create_url)])
    rows.append([types.InlineKeyboardButton(text=t(lang, "back"), callback_data=back_callback)])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


async def main_bot_services_text(lang: str) -> str:
    if main_bot_username():
        base = t(lang, "main_bot_redirect_text")
        return f"{base}\n\n{render_main_product_lines(lang)}"
    return t(lang, "main_bot_not_configured_text")


async def menu_for_current_bot(lang: str, bot_or_id):
    if await is_reseller_owned_bot(bot_or_id):
        return reseller_user_main_menu(lang)
    if await is_digital_products_bot(bot_or_id):
        return digital_products_main_menu(lang)
    if await is_card_ex_bot(bot_or_id):
        return cards_main_menu(lang)
    return main_menu(lang)


async def _remove_reply_keyboard_if_message(target: types.Message | types.CallbackQuery) -> None:
    if isinstance(target, types.CallbackQuery):
        return
    try:
        await target.answer("\u2800", reply_markup=types.ReplyKeyboardRemove())
    except Exception:
        return


async def send_main_bot_message(
    target: types.Message | types.CallbackQuery,
    *,
    lang: str,
    back_callback: str = "back_to_main_menu",
) -> None:
    text = await main_bot_services_text(lang)
    kb = main_bot_services_kb(lang, back_callback=back_callback)
    await _remove_reply_keyboard_if_message(target)
    if isinstance(target, types.CallbackQuery):
        if target.message:
            await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


async def send_digital_products_message(
    target: types.Message | types.CallbackQuery,
    *,
    lang: str,
) -> None:
    url = digital_products_bot_url("hub")
    text = t(lang, "digital_products_redirect_text") if url else t(lang, "digital_products_not_configured_text")
    rows: list[list[types.InlineKeyboardButton]] = []
    if url:
        rows.append([types.InlineKeyboardButton(text=t(lang, "open_digital_products_button"), url=url)])
    kb = types.InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    await _remove_reply_keyboard_if_message(target)
    if isinstance(target, types.CallbackQuery):
        if target.message:
            await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)
