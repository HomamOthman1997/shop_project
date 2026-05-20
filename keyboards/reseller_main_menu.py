from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import settings
from utils.translations import t


def _is_ar(lang: str) -> bool:
    return str(lang or "").lower().startswith("ar")


def _label(lang: str, ar: str, en: str) -> str:
    return ar if _is_ar(lang) else en


def _main_bot_button(lang: str) -> InlineKeyboardButton:
    username = str(getattr(settings, "main_bot_username", "") or "").strip().lstrip("@")
    if username:
        return InlineKeyboardButton(text=_label(lang, "🚀 مركز CyberZone", "🚀 CyberZone Hub"), url=f"https://t.me/{username}?start=hub")
    return InlineKeyboardButton(text=t(lang, "btn_cyberzone_services"), callback_data="rsmenu:main_bot_services")


def reseller_main_menu(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_label(lang, "📊 لوحة التحكم", "📊 Control Center"), callback_data="rsmenu:dashboard")],
            [
                InlineKeyboardButton(text=_label(lang, "🧩 كتالوج البوت", "🧩 Bot Catalog"), callback_data="rsmenu:custom_services"),
                InlineKeyboardButton(text=_label(lang, "⚙️ إعداد التشغيل", "⚙️ Setup"), callback_data="rsmenu:settings"),
            ],
            [InlineKeyboardButton(text=_label(lang, "💳 الرصيد والاشتراك", "💳 Balance & Subscription"), callback_data="rsmenu:balance")],
            [
                InlineKeyboardButton(text=_label(lang, "🧾 طلبات الشحن", "🧾 Recharge Requests"), callback_data="rsmenu:recharge_requests"),
                InlineKeyboardButton(text=_label(lang, "📈 المبيعات والأرباح", "📈 Sales & Profit"), callback_data="rsmenu:stats"),
            ],
            [
                InlineKeyboardButton(text=_label(lang, "👤 رصيد مستخدم", "👤 User Balance"), callback_data="rsmenu:adjust_user_balance"),
                InlineKeyboardButton(text=_label(lang, "📣 إذاعة", "📣 Broadcast"), callback_data="rsmenu:broadcast"),
            ],
            [_main_bot_button(lang)],
        ]
    )
