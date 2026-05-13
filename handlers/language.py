from aiogram import Router, types
from aiogram.fsm.context import FSMContext

from database.bots_repo import get_bot_settings
from database.user_repo import update_user_language
from keyboards.language_kb import language_keyboard
from keyboards.subscription_kb import subscription_keyboard
from services.numbers.handlers.core_numbers import NumberFlow, _compose_numbers_screen
from services.numbers.keyboards.core_numbers_kb import number_type_kb
from utils.bot_menu_context import is_card_ex_bot, is_digital_products_bot, is_main_bot, is_numbers_bot, menu_for_current_bot
from utils.translations import t

router = Router()


async def _apply_language(callback: types.CallbackQuery, lang: str, state: FSMContext | None = None):
    user_id = callback.from_user.id
    await update_user_language(user_id, lang)

    bot_id = (await callback.bot.get_me()).id
    if await is_numbers_bot(bot_id):
        if state is not None:
            await state.clear()
            await state.update_data(lang=lang)
            await state.set_state(NumberFlow.num_type)
        note = t(lang, "temp_numbers_type_note")
        await callback.message.answer(
            t(lang, "main_menu"),
            reply_markup=await menu_for_current_bot(lang, bot_id, user_id=user_id),
        )
        await callback.message.edit_text(
            _compose_numbers_screen(t(lang, "choose_number_type"), trailing_lines=[note]),
            reply_markup=number_type_kb(lang, show_cancel=False),
        )
        await callback.answer()
        return

    if await is_main_bot(bot_id) or await is_digital_products_bot(bot_id) or await is_card_ex_bot(bot_id):
        await callback.message.edit_text(
            t(lang, "main_menu"),
            reply_markup=await menu_for_current_bot(lang, bot_id, user_id=user_id),
        )
        await callback.answer()
        return

    bot_settings = await get_bot_settings(bot_id)
    channel = bot_settings.get("subscription_channel")

    if not channel:
        await callback.message.edit_text(t(lang, "no_channel_set"))
        await callback.answer()
        return

    await callback.message.edit_text(
        t(lang, "join_channel"),
        reply_markup=subscription_keyboard(channel, lang),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "lang_en")
async def set_language_en(callback: types.CallbackQuery, state: FSMContext):
    await _apply_language(callback, "en", state)


@router.callback_query(lambda c: c.data == "lang_ar")
async def set_language_ar(callback: types.CallbackQuery, state: FSMContext):
    await _apply_language(callback, "ar", state)


@router.callback_query(lambda c: c.data == "lang_back")
async def language_back(callback: types.CallbackQuery):
    await callback.message.edit_text(
        t("en", "choose_language"),
        reply_markup=language_keyboard("en"),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "lang_cancel")
async def language_cancel(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        await callback.message.edit_text(
            t("en", "choose_language"),
            reply_markup=language_keyboard("en"),
        )
    await callback.answer()
