from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.translations import t


def get_reseller_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "reseller_history_button"), callback_data="rcharge:history")],
            [
                InlineKeyboardButton(text=t(lang, "reseller_add_address_button"), callback_data="rcharge:add_address"),
                InlineKeyboardButton(text=t(lang, "reseller_list_addresses_button"), callback_data="rcharge:list_addresses"),
            ],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="rcharge:back")],
        ]
    )
