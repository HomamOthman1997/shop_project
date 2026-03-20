# keyboards/subscription_kb.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.translations import t


def subscription_keyboard(channel: str, lang: str = "en") -> InlineKeyboardMarkup:
    channel = channel.replace("@", "")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "join_channel_button"),
                    url=f"https://t.me/{channel}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "check_sub_button"),
                    callback_data="check_sub",
                )
            ],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="sub:back_lang")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="sub:cancel", style="danger")],
        ]
    )
