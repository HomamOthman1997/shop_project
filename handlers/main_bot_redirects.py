from aiogram import F, Router, types

from database.user_repo import get_user
from utils.bot_menu_context import send_main_bot_message
from utils.translations import t

router = Router()

_NUMBERS_CALLBACK_PREFIXES = (
    "flow:rental:",
    "flow:country:",
    "flow:service:",
    "rentprov:",
    "rtv:",
    "rent:",
    "renthead:",
    "rentna:",
    "rentpick:",
    "rentopt:",
    "rentguard:",
    "buy:",
    "temp:",
    "num_resend_",
)
_PROXY_CALLBACK_PREFIXES = (
    "proxy:",
)


def _is_numbers_button(text: str | None) -> bool:
    raw = str(text or "").strip()
    return raw in {t("en", "btn_numbers"), t("ar", "btn_numbers")}


def _is_proxies_button(text: str | None) -> bool:
    raw = str(text or "").strip()
    return raw in {t("en", "btn_proxies"), t("ar", "btn_proxies")}


def _is_numbers_callback(data: str | None) -> bool:
    raw = str(data or "").strip()
    if not raw:
        return False
    return raw.startswith(_NUMBERS_CALLBACK_PREFIXES)


def _is_proxy_callback(data: str | None) -> bool:
    raw = str(data or "").strip()
    if not raw:
        return False
    return raw.startswith(_PROXY_CALLBACK_PREFIXES)


async def _lang_for(user_id: int) -> str:
    user = await get_user(int(user_id))
    return str((user or {}).get("language") or "en")


@router.message(lambda msg: _is_numbers_button(msg.text))
async def redirect_numbers_button(message: types.Message) -> None:
    lang = await _lang_for(message.from_user.id)
    await send_main_bot_message(message, lang=lang)


@router.message(lambda msg: _is_proxies_button(msg.text))
async def redirect_proxies_button(message: types.Message) -> None:
    lang = await _lang_for(message.from_user.id)
    await send_main_bot_message(message, lang=lang)


@router.message(F.text.startswith("/select_country_"))
@router.message(F.text.startswith("/select_state_"))
@router.message(F.text.startswith("/select_service_"))
async def redirect_numbers_command(message: types.Message) -> None:
    lang = await _lang_for(message.from_user.id)
    await send_main_bot_message(message, lang=lang)


@router.message(F.text.startswith("/proxy_country_"))
@router.message(F.text.startswith("/proxy_state_"))
@router.message(F.text.startswith("/proxy_city_"))
async def redirect_proxy_command(message: types.Message) -> None:
    lang = await _lang_for(message.from_user.id)
    await send_main_bot_message(message, lang=lang)


@router.callback_query(lambda c: _is_numbers_callback(c.data))
async def redirect_numbers_callback(callback: types.CallbackQuery) -> None:
    lang = await _lang_for(callback.from_user.id)
    await callback.answer(
        "هذه الخدمة متاحة عبر مركز CyberZone." if lang.startswith("ar") else "This service is available in CyberZone Hub.",
        show_alert=True,
    )
    await send_main_bot_message(callback, lang=lang)


@router.callback_query(lambda c: _is_proxy_callback(c.data))
async def redirect_proxy_callback(callback: types.CallbackQuery) -> None:
    lang = await _lang_for(callback.from_user.id)
    await callback.answer(
        "هذه الخدمة متاحة عبر مركز CyberZone." if lang.startswith("ar") else "This service is available in CyberZone Hub.",
        show_alert=True,
    )
    await send_main_bot_message(callback, lang=lang)
