# bot.py -> Admin-only bot

import asyncio
from contextlib import suppress

from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command

from config import settings
from handlers import reseller_recharge
from handlers.admin_services import router as admin_services_router
from handlers.owner_requests import router as owner_requests_router
from middlewares.version_check import VersionCheckMiddleware
from utils.permissions import owner_only
from utils.telegram_error_reporting import install_telegram_error_handler

BOT_TOKEN = settings.bot_admin_token
admin_router = Router()


@admin_router.message(Command("start"))
async def admin_start(message: types.Message):
    if not await owner_only(message):
        return

    try:
        sent = await message.answer("...", reply_markup=types.ReplyKeyboardRemove())
        try:
            await sent.delete()
        except Exception:
            pass
    except Exception:
        pass

    text = "Owner Control Panel\n\nUse inline categories to run owner operations."
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Open Owner Panel", callback_data="owner_panel:open")]
        ]
    )
    await message.answer(text, reply_markup=keyboard)


async def main():
    bot = Bot(token=BOT_TOKEN, timeout=60)
    dp = Dispatcher()
    telegram_error_handler = install_telegram_error_handler(bot_token=BOT_TOKEN)

    dp.message.middleware(VersionCheckMiddleware())
    dp.callback_query.middleware(VersionCheckMiddleware())

    dp.include_router(reseller_recharge.router)
    dp.include_router(admin_router)
    dp.include_router(admin_services_router)
    dp.include_router(owner_requests_router)

    try:
        await dp.start_polling(bot)
    finally:
        if telegram_error_handler is not None:
            with suppress(Exception):
                await telegram_error_handler.aclose()
        with suppress(Exception):
            await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Admin bot stopped.")
