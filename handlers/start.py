from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import UTC, datetime, timedelta

from keyboards.language_kb import language_keyboard
from keyboards.subscription_kb import subscription_keyboard
from keyboards.main_menu_kb import main_menu
from keyboards.reseller_main_menu import reseller_main_menu
from utils.permissions import is_reseller

from database.user_repo import get_user, create_user, set_user_reseller_for_bot, update_user_version
from database.bots_repo import get_bot_settings, get_reseller_id_for_bot
from database.mongo import db
from services.numbers.handlers.core_numbers_buy import _handle_rental_exit_message_guard
from utils.translations import t
from config import settings
from utils.reseller_setup_guard import get_reseller_setup_status, render_reseller_setup_notice

router = Router()
_CLEAN_KEYBOARD_COMMANDS = {"/clean_keyboard", "/clean_kb", "/rkoff"}
_TEMP_START_NOTICE_MAX_AGE = timedelta(hours=6)


def _reseller_setup_quick_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="⚙️ Open Reseller Settings", callback_data="rsmenu:settings")],
        ]
    )


async def _hide_reply_keyboard(message: types.Message, lang: str) -> None:
    try:
        sent = await message.answer(
            t(lang, "keyboard_cleanup_placeholder"),
            reply_markup=types.ReplyKeyboardRemove(),
        )
        try:
            await sent.delete()
        except Exception:
            pass
    except Exception:
        pass


async def _has_active_temp_order(user_id: int) -> bool:
    cutoff = datetime.now(UTC) - _TEMP_START_NOTICE_MAX_AGE
    doc = await db.orders.find_one(
        {
            "user_id": int(user_id),
            "number_mode": "temp",
            "status": {"$in": ["success", "pending", "paid"]},
            "temp_wait_state": {"$in": ["waiting", "code_received"]},
            "created_at": {"$gte": cutoff},
        },
        {"_id": 1},
    )
    return doc is not None


async def _has_active_rental_order(user_id: int) -> bool:
    doc = await db.orders.find_one(
        {
            "user_id": int(user_id),
            "number_mode": "rental",
            "status": {"$in": ["success", "pending", "paid"]},
        },
        {"_id": 1},
    )
    return doc is not None


async def _notify_active_temp_order_if_any(message: types.Message, lang: str) -> None:
    has_temp = await _has_active_temp_order(message.from_user.id)
    has_rental = await _has_active_rental_order(message.from_user.id)
    if not has_temp and not has_rental:
        return
    if str(lang or "").lower().startswith("ar"):
        if has_temp and has_rental:
            kind = "لديك طلبات أرقام نشطة (مؤقت + رينتال)."
        elif has_temp:
            kind = "لديك طلب رقم مؤقت نشط."
        else:
            kind = "لديك طلب رينتال نشط."
        text = (
            f"{kind}\n"
            "كبسة /start لا تلغي الطلبات ولا تضيع الرصيد.\n"
            "أكمل من رسالة الطلب الأصلية."
        )
    else:
        if has_temp and has_rental:
            kind = "You have active number orders (temp + rental)."
        elif has_temp:
            kind = "You have an active temp-number order."
        else:
            kind = "You have an active rental-number order."
        text = (
            f"{kind}\n"
            "Tap Numbers below to continue."
        )
    await message.answer(
        text,
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text=t(lang, "numbers"), callback_data="flow:type:temp")]
            ]
        ),
    )


@router.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if user and await _handle_rental_exit_message_guard(message, state, target="start", lang=lang):
        return
    await state.clear()
    user_id = message.from_user.id
    user = user or await get_user(user_id)

    bot_id = (await message.bot.get_me()).id
    bot_settings = await get_bot_settings(bot_id)
    subscription_channel = bot_settings.get("subscription_channel")
    inferred_reseller_id = await get_reseller_id_for_bot(bot_id)

    # Ù…Ø³ØªØ®Ø¯Ù… Ø¬Ø¯ÙŠØ¯ â†’ Ù†Ø·Ù„Ø¨ Ù…Ù†Ù‡ Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„Ù„ØºØ©
    if not user:
        username = message.from_user.username or ""
        await create_user(user_id, username, reseller_id=None)
        if inferred_reseller_id:
            await set_user_reseller_for_bot(user_id, bot_id, inferred_reseller_id)

        return await message.answer(
            t("en", "choose_language"),
            reply_markup=language_keyboard("en", show_nav=False)
        )

    if inferred_reseller_id and user.get("reseller_id") != inferred_reseller_id:
        await set_user_reseller_for_bot(user_id, bot_id, inferred_reseller_id)
        user["reseller_id"] = inferred_reseller_id

    lang = user.get("language", "en")

    # Ø§Ù„ØªØ­Ù‚Ù‚ Ù…Ù† ÙˆØ¬ÙˆØ¯ Ù‚Ù†Ø§Ø© Ø§Ø´ØªØ±Ø§Ùƒ
    if not subscription_channel:
        return await message.answer(
            t(lang, "no_channel_set")
        )

    # Ø§Ù„ØªØ­Ù‚Ù‚ Ù…Ù† Ø§Ù„Ø§Ø´ØªØ±Ø§Ùƒ
    try:
        member = await message.bot.get_chat_member(subscription_channel, user_id)

        if member.status in ("member", "administrator", "creator"):
            # If user is a reseller, show reseller menu instead
            if await is_reseller(user_id, bot_id=bot_id):
                await _hide_reply_keyboard(message, lang)
                await message.answer(
                    t(lang, "main_menu"),
                    reply_markup=reseller_main_menu(lang)
                )
                await _notify_active_temp_order_if_any(message, lang)
                status = await get_reseller_setup_status(user_id)
                if not bool(status.get("ready")):
                    await message.answer(
                        render_reseller_setup_notice(lang, status),
                        reply_markup=_reseller_setup_quick_kb(),
                    )
                return
            await message.answer(
                t(lang, "main_menu"),
                reply_markup=main_menu(lang)
            )
            await _notify_active_temp_order_if_any(message, lang)
            return

        return await message.answer(
            t(lang, "join_channel"),
            reply_markup=subscription_keyboard(subscription_channel, lang)
        )

    except Exception:
        return await message.answer(
            t(lang, "join_channel"),
            reply_markup=subscription_keyboard(subscription_channel, lang)
        )


async def _forced_start_flow(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if user and await _handle_rental_exit_message_guard(message, state, target="start", lang=lang):
        return
    await state.clear()
    if not user:
        username = message.from_user.username or ""
        bot_id = (await message.bot.get_me()).id
        inferred_reseller_id = await get_reseller_id_for_bot(bot_id)
        user = await create_user(message.from_user.id, username, reseller_id=None)
        if inferred_reseller_id:
            await set_user_reseller_for_bot(message.from_user.id, bot_id, inferred_reseller_id)

    bot_id = (await message.bot.get_me()).id
    inferred_reseller_id = await get_reseller_id_for_bot(bot_id)
    if inferred_reseller_id and user.get("reseller_id") != inferred_reseller_id:
        await set_user_reseller_for_bot(message.from_user.id, bot_id, inferred_reseller_id)
        user["reseller_id"] = inferred_reseller_id
    lang = user.get("language", "en")

    # âœ”ï¸ ØªØ­Ø¯ÙŠØ« Ù†Ø³Ø®Ø© Ø§Ù„Ø¨ÙˆØª Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù…
    await update_user_version(message.from_user.id, settings.bot_version)

    # Show reseller menu for resellers
    if await is_reseller(message.from_user.id, bot_id=bot_id):
        await _hide_reply_keyboard(message, lang)
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=reseller_main_menu(lang)
        )
        await _notify_active_temp_order_if_any(message, lang)
        status = await get_reseller_setup_status(message.from_user.id)
        if not bool(status.get("ready")):
            await message.answer(
                render_reseller_setup_notice(lang, status),
                reply_markup=_reseller_setup_quick_kb(),
            )
    else:
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=main_menu(lang)
        )
        await _notify_active_temp_order_if_any(message, lang)


# âœ”ï¸ Ø¥ØµÙ„Ø§Ø­ Ø²Ø± Start Ù„ÙŠØ¹Ù…Ù„ Ø¨ÙƒÙ„ Ø§Ù„Ù„ØºØ§Øª
@router.message(lambda msg: msg.text and msg.text.startswith("🔄"))
async def forced_start(message: types.Message, state: FSMContext):
    await _forced_start_flow(message, state)


@router.message(lambda msg: (msg.text or "").strip().lower() in _CLEAN_KEYBOARD_COMMANDS)
async def clean_keyboard_command(message: types.Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    bot_id = (await message.bot.get_me()).id

    await message.answer("Keyboard cleaned.", reply_markup=types.ReplyKeyboardRemove())
    if await is_reseller(message.from_user.id, bot_id=bot_id):
        await message.answer(t(lang, "main_menu"), reply_markup=reseller_main_menu(lang))
    else:
        await message.answer(t(lang, "main_menu"), reply_markup=main_menu(lang))


@router.callback_query(lambda c: c.data == "force_start")
async def forced_start_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.message:
        await _forced_start_flow(callback.message, state)


@router.callback_query(lambda c: c.data == "update:cancel")
async def update_cancel_callback(callback: types.CallbackQuery):
    await callback.answer()
    if not callback.message:
        return
    try:
        await callback.message.delete()
    except Exception:
        pass

