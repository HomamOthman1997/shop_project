from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from utils.translations import t


def update_required_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "start_button"), callback_data="force_start")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="update:cancel", style="danger")],
        ]
    )
