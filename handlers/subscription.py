from aiogram import Router, types

from database.bots_repo import get_bot_settings
from database.user_repo import get_user
from keyboards.language_kb import language_keyboard
from keyboards.main_menu_kb import main_menu
from keyboards.reseller_main_menu import reseller_main_menu
from utils.permissions import is_reseller
from utils.translations import t

router = Router()


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


@router.callback_query(lambda c: c.data == "check_sub")
async def check_subscription(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    user = await get_user(user_id)
    lang = user.get("language", "en") if user else "en"

    bot_id = (await callback.bot.get_me()).id
    settings = await get_bot_settings(bot_id)
    subscription_channel = settings.get("subscription_channel")

    try:
        member = await callback.bot.get_chat_member(subscription_channel, user_id)

        if member.status in ("member", "administrator", "creator"):
            if await is_reseller(user_id, bot_id=bot_id):
                await _hide_reply_keyboard(callback.message, lang)
                await callback.message.answer(
                    t(lang, "main_menu"),
                    reply_markup=reseller_main_menu(lang),
                )
            else:
                await callback.message.answer(
                    t(lang, "main_menu"),
                    reply_markup=main_menu(lang),
                )

            await callback.message.delete()
        else:
            await callback.answer(t(lang, "must_join"), show_alert=True)

    except Exception:
        await callback.answer(t(lang, "subscription_error"), show_alert=True)


@router.callback_query(lambda c: c.data == "sub:back_lang")
async def back_to_language(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "en") if user else "en"
    await callback.message.edit_text(
        t(lang, "choose_language"),
        reply_markup=language_keyboard(lang),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "sub:cancel")
async def cancel_subscription_prompt(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()
