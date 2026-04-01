from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from utils.translations import t


def reseller_main_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t(lang, "btn_services"), callback_data="rsmenu:custom_services"),
                InlineKeyboardButton(text=t(lang, "btn_reseller_balance"), callback_data="rsmenu:balance"),
            ],
            [
                InlineKeyboardButton(text="إذاعة", callback_data="rsmenu:broadcast"),
                InlineKeyboardButton(text=t(lang, "btn_reseller_settings"), callback_data="rsmenu:settings"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "btn_cyberzone_services"), callback_data="rsmenu:main_bot_services"),
            ],
        ]
    )
