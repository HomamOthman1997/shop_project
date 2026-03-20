from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from utils.translations import t


def recharge_methods_keyboard(methods=None, lang: str = "en"):
    methods = methods or []
    rows = []
    two = []
    for title, _code in methods:
        two.append(KeyboardButton(text=title))
        if len(two) == 2:
            rows.append(two)
            two = []
    if two:
        rows.append(two)

    rows.append([KeyboardButton(text=t(lang, "btn_back"))])
    rows.append([KeyboardButton(text=t(lang, "btn_cancel"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
