from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from config import settings
from utils.translations import t


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=t(lang, "btn_services"))],
        [
            KeyboardButton(text=t(lang, "btn_numbers")),
            KeyboardButton(text=t(lang, "btn_proxies")),
        ],
        [
            KeyboardButton(text=t(lang, "btn_store")),
        ],
        [
            KeyboardButton(text=t(lang, "btn_balance")),
            KeyboardButton(text=t(lang, "btn_settings")),
        ],
    ]
    if not (bool(getattr(settings, "beta_mode_enabled", False)) and bool(getattr(settings, "beta_disable_create_bot", False))):
        keyboard.append([KeyboardButton(text=t(lang, "btn_create_bot"))])
    keyboard.append([KeyboardButton(text=t(lang, "btn_support"))])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )
