from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import settings
from utils.translations import t


def _main_bot_button(lang: str) -> InlineKeyboardButton:
    username = str(getattr(settings, "main_bot_username", "") or "").strip().lstrip("@")
    if username:
        return InlineKeyboardButton(text=t(lang, "btn_cyberzone_services"), url=f"https://t.me/{username}?start=hub")
    return InlineKeyboardButton(text=t(lang, "btn_cyberzone_services"), callback_data="rsmenu:main_bot_services")


def reseller_main_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="لوحة التحكم", callback_data="rsmenu:dashboard"),
                InlineKeyboardButton(text=t(lang, "btn_reseller_balance"), callback_data="rsmenu:balance"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "btn_services"), callback_data="rsmenu:custom_services"),
                _main_bot_button(lang),
            ],
            [
                InlineKeyboardButton(text="طلبات الشحن", callback_data="rsmenu:recharge_requests"),
                InlineKeyboardButton(text="تعديل رصيد مستخدم", callback_data="rsmenu:adjust_user_balance"),
            ],
            [
                InlineKeyboardButton(text="شحن رصيد البوت الرئيسي", callback_data="rsmenu:core_topup"),
                InlineKeyboardButton(text="إذاعة", callback_data="rsmenu:broadcast"),
            ],
            [
                InlineKeyboardButton(text="الإحصائيات", callback_data="rsmenu:stats"),
                InlineKeyboardButton(text=t(lang, "btn_reseller_settings"), callback_data="rsmenu:settings"),
            ],
        ]
    )
