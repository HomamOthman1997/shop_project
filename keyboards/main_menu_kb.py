import os

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

from config import settings
from utils.translations import t


def _icon(icon_id: str | None) -> str | None:
    value = str(icon_id or "").strip()
    return value or None


def _strip_leading_symbol(text: str, *, icon_id: str | None = None) -> str:
    if not icon_id:
        return text
    return str(text or "").lstrip("🆘💳⚙️🔢➕🧩🎮🎁📱 ").strip() or str(text or "").strip()


_ICON_ACCOUNT = _icon(getattr(settings, "tg_icon_account", None))
_ICON_SUPPORT = _icon(getattr(settings, "tg_icon_support", None))


def _label(lang: str, en: str, ar: str) -> str:
    return ar if str(lang or "").lower().startswith("ar") else en


def _kb_button(text: str, *, icon_id: str | None = None, web_app: WebAppInfo | None = None) -> KeyboardButton:
    kwargs = {}
    if web_app is not None:
        kwargs["web_app"] = web_app
    if icon_id:
        kwargs["icon_custom_emoji_id"] = icon_id
    return KeyboardButton(text=_strip_leading_symbol(text, icon_id=icon_id), **kwargs)


def _digital_store_webapp_url() -> str:
    raw = str(getattr(settings, "digital_products_miniapp_public_url", "") or "").strip().rstrip("/")
    if not raw:
        return ""
    if raw.endswith("/mini/digital"):
        return raw
    return f"{raw}/mini/digital"


def _miniapp_base_url(*keys: str) -> str:
    for key in keys:
        raw = str(getattr(settings, key, "") or "").strip().rstrip("/")
        if raw:
            break
    else:
        raw = str(os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL") or "").strip().rstrip("/")
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    for suffix in ("/mini/numbers", "/mini/digital", "/mini/cardex"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    return raw.rstrip("/")


def _numbers_miniapp_url() -> str:
    base = _miniapp_base_url("numbers_miniapp_public_url", "digital_products_miniapp_public_url")
    return f"{base}/mini/numbers" if base else ""


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=t(lang, "btn_services"))],
        [
            KeyboardButton(text=t(lang, "btn_create_bot")),
        ],
        [
            _kb_button(t(lang, "user_settings_my_account"), icon_id=_ICON_ACCOUNT),
            _kb_button(t(lang, "btn_support"), icon_id=_ICON_SUPPORT),
        ],
        [
            _kb_button(t(lang, "btn_more_services")),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def numbers_main_menu(lang: str) -> ReplyKeyboardMarkup:
    miniapp_url = _numbers_miniapp_url()
    miniapp_ready = bool(getattr(settings, "numbers_miniapp_enabled", False)) and bool(miniapp_url)
    keyboard = [
        *(
            [[_kb_button(_label(lang, "Open Numbers App", "فتح تطبيق الأرقام"), web_app=WebAppInfo(url=miniapp_url))]]
            if miniapp_ready
            else []
        ),
        [
            _kb_button(t(lang, "btn_my_numbers")),
        ],
        [
            _kb_button(t(lang, "user_settings_my_account"), icon_id=_ICON_ACCOUNT),
            _kb_button(t(lang, "btn_support"), icon_id=_ICON_SUPPORT),
        ],
        [
            _kb_button(t(lang, "btn_more_services")),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def reseller_user_main_menu(lang: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=t(lang, "btn_services"))],
        [
            _kb_button(t(lang, "user_settings_my_account"), icon_id=_ICON_ACCOUNT),
        ],
        [KeyboardButton(text=t(lang, "btn_cyberzone_services"))],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def digital_products_main_menu(lang: str) -> ReplyKeyboardMarkup:
    miniapp_url = _digital_store_webapp_url()
    miniapp_ready = bool(getattr(settings, "digital_products_miniapp_enabled", False)) and bool(miniapp_url)
    if miniapp_ready:
        keyboard = [
            [_kb_button(_label(lang, "Open Digital Store", "فتح المتجر الرقمي"), web_app=WebAppInfo(url=miniapp_url))],
            [
                _kb_button(t(lang, "user_settings_my_account"), icon_id=_ICON_ACCOUNT),
                _kb_button(t(lang, "btn_support"), icon_id=_ICON_SUPPORT),
            ],
        ]
    else:
        keyboard = [
            [
                KeyboardButton(text=t(lang, "btn_games_topups")),
                KeyboardButton(text=t(lang, "btn_giftcards")),
            ],
            [KeyboardButton(text=t(lang, "btn_sim_topup"))],
            [
                _kb_button(t(lang, "user_settings_my_account"), icon_id=_ICON_ACCOUNT),
                _kb_button(t(lang, "btn_support"), icon_id=_ICON_SUPPORT),
            ],
        ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )
