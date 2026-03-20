from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_reseller_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='History', callback_data='rcharge:history')],
            [
                InlineKeyboardButton(text='Add Address', callback_data='rcharge:add_address'),
                InlineKeyboardButton(text='List Addresses', callback_data='rcharge:list_addresses'),
            ],
            [InlineKeyboardButton(text='Back', callback_data='rcharge:back')],
        ]
    )
