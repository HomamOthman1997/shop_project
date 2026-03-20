from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from utils.translations import t


def reseller_main_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Dashboard", callback_data="rsmenu:dashboard")],
            [
                InlineKeyboardButton(text=t(lang, "btn_reseller_balance"), callback_data="rsmenu:balance"),
                InlineKeyboardButton(text=t(lang, "btn_reseller_stats"), callback_data="rsmenu:stats"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "btn_recharge_requests"), callback_data="rsmenu:recharge_requests"),
                InlineKeyboardButton(text=t(lang, "btn_reseller_core_topup"), callback_data="rsmenu:core_topup"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "btn_custom_services"), callback_data="rsmenu:custom_services"),
            ],
            [InlineKeyboardButton(text=t(lang, "btn_adjust_user_balance"), callback_data="rsmenu:adjust_user_balance")],
            [InlineKeyboardButton(text=t(lang, "btn_reseller_settings"), callback_data="rsmenu:settings")],
        ]
    )
