from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.translations import t


def recharge_methods_keyboard(methods=None, lang: str = "en"):
    methods = methods or []
    rows: list[list[InlineKeyboardButton]] = []
    for title, code in methods:
        safe_code = str(code or title or "").strip()
        if not safe_code:
            continue
        rows.append([InlineKeyboardButton(text=str(title or safe_code), callback_data=f"recharge:method:{safe_code}")])

    rows.append([InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="recharge:back")])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="recharge:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
