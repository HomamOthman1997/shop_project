from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from utils.translations import t


def balance_keyboard(lang="en"):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, "btn_add_balance"))],
            [KeyboardButton(text=t(lang, "btn_back_main"))],
            [KeyboardButton(text=t(lang, "btn_cancel"))],
        ],
        resize_keyboard=True,
    )
