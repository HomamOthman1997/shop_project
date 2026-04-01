from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from utils.translations import t


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text=t(lang, "btn_proxies")),
            KeyboardButton(text=t(lang, "btn_numbers")),
        ],
        [KeyboardButton(text=t(lang, "btn_create_bot"))],
        [
            KeyboardButton(text=t(lang, "btn_balance")),
            KeyboardButton(text=t(lang, "btn_settings")),
        ],
    ]
    keyboard.append([KeyboardButton(text=t(lang, "btn_support"))])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def reseller_user_main_menu(lang: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text=t(lang, "btn_balance")),
            KeyboardButton(text=t(lang, "btn_settings")),
        ],
        [KeyboardButton(text=t(lang, "btn_cyberzone_services"))],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def digital_products_main_menu(lang: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=t(lang, "btn_games_topups"))],
        [
            KeyboardButton(text=t(lang, "btn_mobile_topups")),
            KeyboardButton(text=t(lang, "btn_esim")),
        ],
        [
            KeyboardButton(text=t(lang, "btn_balance")),
            KeyboardButton(text=t(lang, "btn_settings")),
        ],
        [KeyboardButton(text=t(lang, "btn_support"))],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )
