from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

from config import settings
from utils.translations import t


def _digital_store_webapp_url() -> str:
    raw = str(getattr(settings, "digital_products_miniapp_public_url", "") or "").strip().rstrip("/")
    if not raw:
        return ""
    if raw.endswith("/mini/digital"):
        return raw
    return f"{raw}/mini/digital"


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=t(lang, "btn_services"))],
        [
            KeyboardButton(text=t(lang, "btn_proxies")),
            KeyboardButton(text=t(lang, "btn_numbers")),
        ],
        [KeyboardButton(text=t(lang, "btn_create_bot"))],
        [
            KeyboardButton(text=t(lang, "btn_balance")),
            KeyboardButton(text=t(lang, "btn_settings")),
        ],
    ]
    keyboard.append([KeyboardButton(text=t(lang, "btn_support"))])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def reseller_user_main_menu(lang: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=t(lang, "btn_services"))],
        [
            KeyboardButton(text=t(lang, "btn_balance")),
            KeyboardButton(text=t(lang, "btn_settings")),
        ],
        [KeyboardButton(text=t(lang, "btn_cyberzone_services"))],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def digital_products_main_menu(lang: str) -> ReplyKeyboardMarkup:
    miniapp_url = _digital_store_webapp_url()
    keyboard = [
        (
            [KeyboardButton(text="Open Digital Store", web_app=WebAppInfo(url=miniapp_url))]
            if bool(getattr(settings, "digital_products_miniapp_enabled", False)) and miniapp_url
            else []
        ),
        [
            KeyboardButton(text=t(lang, "btn_games_topups")),
            KeyboardButton(text=t(lang, "btn_giftcards")),
        ],
        [KeyboardButton(text=t(lang, "btn_sim_topup"))],
        [
            KeyboardButton(text=t(lang, "btn_balance")),
            KeyboardButton(text=t(lang, "btn_settings")),
        ],
        [KeyboardButton(text=t(lang, "btn_support"))],
    ]
    keyboard = [row for row in keyboard if row]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )
