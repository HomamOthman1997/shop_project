from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.translations import t


def language_keyboard(lang: str = "en", show_nav: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="English", callback_data="lang_en")],
        [InlineKeyboardButton(text="العربية", callback_data="lang_ar")],
    ]
    if show_nav:
        rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="lang_back")])
        rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="lang_cancel", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
