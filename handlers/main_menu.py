from datetime import UTC, datetime, timedelta
from html import escape
from io import BytesIO
import logging

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from config import OWNER_ID, settings
from database.bots_repo import get_bot_token, get_reseller_id_for_bot
from database.financial_ledger import credit_user_wallet, get_reseller_wallet_balance, get_user_wallet_balance
from database.mongo import db
from database.recharge_repo import create_recharge_request
from database.owner_payment_settings_repo import get_owner_exchange_rate, get_owner_payment_methods
from database.reseller_settings_repo import (
    get_exchange_rate_meta,
    get_exchange_routing,
    get_payment_methods,
    get_recharge_routing,
    get_support_routing,
    mark_exchange_rate_reminded_today
)
from database.support_topics_repo import get_support_target
from database.support_tickets_repo import (
    begin_support_ticket_bug_reward,
    create_support_ticket,
    get_support_ticket,
    has_open_support_ticket,
    mark_support_ticket_bug_reward_failed,
    mark_support_ticket_bug_reward_paid,
    mark_support_ticket_bug_triage,
    mark_support_ticket_replied,
    mark_support_ticket_solved,
    set_ticket_delivery,
)
from database.user_repo import get_user, get_user_reseller_for_bot, set_user_reseller_for_bot
from keyboards.recharge_methods_keyboard import recharge_methods_keyboard
from keyboards.reseller_main_menu import reseller_main_menu
from utils.bot_menu_context import (
    card_ex_bot_url,
    digital_products_bot_url,
    extract_bot_id_from_token,
    is_digital_products_bot,
    is_main_bot,
    is_numbers_bot,
    numbers_bot_url,
    is_reseller_owned_bot,
    menu_for_current_bot,
    resolve_runtime_bot_id,
    send_digital_products_message,
)
from services.subscriptions.presentation import subscription_summary_lines
from services.numbers.handlers.core_numbers_buy import _handle_rental_exit_message_guard
from utils.permissions import is_reseller
from utils.platform_services import render_other_services_text
from utils.recharge_ui import owner_reseller_topup_review_kb, user_recharge_review_kb
from utils.loading_sticker import send_loading_sticker
from utils.translations import t
from utils.user_money import format_usd

router = Router()
logger = logging.getLogger(__name__)


def _btn_values(key: str) -> set[str]:
    return {t("en", key), t("ar", key)}


def _is_btn(text: str | None, key: str) -> bool:
    return (text or "").strip() in _btn_values(key)


def _is_account_button(text: str | None) -> bool:
    raw = (text or "").strip()
    return raw in {t("en", "user_settings_my_account"), t("ar", "user_settings_my_account")} or _is_btn(raw, "btn_settings")


def _is_slash_command(text: str | None, command: str) -> bool:
    first = (text or "").strip().split(maxsplit=1)[0].lower()
    name = str(command or "").strip().lower().lstrip("/")
    if not first or not name:
        return False
    return first == f"/{name}" or first.startswith(f"/{name}@")


def _as_utc(dt: datetime | None) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _pay_nav_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="recharge:back")],
            [InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="recharge:cancel")],
        ]
    )


async def _wallet_scope_error_text(*, lang: str, bot_id: int) -> str:
    if await _uses_platform_wallet(bot_id):
        return t(lang, "platform_wallet_scope_missing")
    return t(lang, "no_reseller_link_found")


async def _effective_recharge_per_credit(method: dict) -> float:
    try:
        per_credit = float(method.get("per_credit") or 0)
    except Exception:
        per_credit = 0.0
    if per_credit > 0:
        return per_credit
    currency = str(method.get("currency", "USD")).upper()
    if currency == "SYP":
        return float(await get_owner_exchange_rate())
    return 1.0


def _recharge_rate_line(lang: str, rate: float, currency: str) -> str:
    is_ar = str(lang or "").lower().startswith("ar")
    if is_ar:
        return f"السعر: <b>1 كريدت = {rate:.4f} {currency}</b>"
    return f"Rate: <b>1 credit = {rate:.4f} {currency}</b>"


async def _uses_platform_wallet(bot_id: int) -> bool:
    return await is_main_bot(bot_id) or await is_digital_products_bot(bot_id) or await is_numbers_bot(bot_id)


async def _current_bot_id(bot) -> int:
    return int(await resolve_runtime_bot_id(bot) or 0)


async def _safe_edit_text(
    message: types.Message,
    text: str,
    *,
    reply_markup: types.InlineKeyboardMarkup | None = None,
):
    try:
        return await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        msg = str(exc).lower()
        if "message is not modified" in msg:
            return message
        if "message can't be edited" in msg:
            return await message.answer(text, reply_markup=reply_markup)
        raise


def _support_bridge_token() -> str:
    return str(getattr(settings, "bot_admin_token", "") or "").strip()


async def _platform_bridge_bot(current_bot: Bot) -> Bot:
    token = _support_bridge_token()
    if not token:
        raise TelegramBadRequest(method="sendMessage", message="platform bridge bot is not configured")
    return Bot(token=token)


async def _download_telegram_file(bot: Bot, file_id: str) -> tuple[bytes, str]:
    file = await bot.get_file(file_id)
    buf = BytesIO()
    await bot.download(file, destination=buf)
    filename = str(getattr(file, "file_path", "") or "").split("/")[-1] or "file.bin"
    return buf.getvalue(), filename


def _extract_support_payload(message: types.Message) -> dict:
    if message.photo:
        return {
            "kind": "photo",
            "file_id": str(message.photo[-1].file_id),
            "caption": message.caption,
        }
    if message.document:
        return {
            "kind": "document",
            "file_id": str(message.document.file_id),
            "caption": message.caption,
            "filename": message.document.file_name,
        }
    if message.video:
        return {
            "kind": "video",
            "file_id": str(message.video.file_id),
            "caption": message.caption,
        }
    if message.voice:
        return {
            "kind": "voice",
            "file_id": str(message.voice.file_id),
            "caption": message.caption,
        }
    if message.audio:
        return {
            "kind": "audio",
            "file_id": str(message.audio.file_id),
            "caption": message.caption,
        }
    if message.text:
        return {"kind": "text", "text": message.text}
    return {"kind": "unsupported"}


async def _relay_support_payload(source_bot: Bot, bridge_bot: Bot, payload: dict, *, target: dict, user_id: int) -> None:
    kwargs = {"chat_id": int(target["chat_id"])}
    if target.get("message_thread_id") is not None:
        kwargs["message_thread_id"] = int(target["message_thread_id"])

    kind = str(payload.get("kind") or "").strip().lower()
    if kind == "photo":
        data, filename = await _download_telegram_file(source_bot, str(payload.get("file_id") or ""))
        await bridge_bot.send_photo(
            photo=BufferedInputFile(data, filename=filename or "photo.jpg"),
            caption=payload.get("caption"),
            **kwargs,
        )
        return
    if kind == "document":
        data, filename = await _download_telegram_file(source_bot, str(payload.get("file_id") or ""))
        await bridge_bot.send_document(
            document=BufferedInputFile(data, filename=str(payload.get("filename") or filename or "document.bin")),
            caption=payload.get("caption"),
            **kwargs,
        )
        return
    if kind == "video":
        data, filename = await _download_telegram_file(source_bot, str(payload.get("file_id") or ""))
        await bridge_bot.send_video(
            video=BufferedInputFile(data, filename=filename or "video.mp4"),
            caption=payload.get("caption"),
            **kwargs,
        )
        return
    if kind == "voice":
        data, filename = await _download_telegram_file(source_bot, str(payload.get("file_id") or ""))
        await bridge_bot.send_voice(
            voice=BufferedInputFile(data, filename=filename or "voice.ogg"),
            caption=payload.get("caption"),
            **kwargs,
        )
        return
    if kind == "audio":
        data, filename = await _download_telegram_file(source_bot, str(payload.get("file_id") or ""))
        await bridge_bot.send_audio(
            audio=BufferedInputFile(data, filename=filename or "audio.mp3"),
            caption=payload.get("caption"),
            **kwargs,
        )
        return
    if kind == "text":
        await bridge_bot.send_message(text=str(payload.get("text") or ""), **kwargs)
        return
    fallback_text = f"Unsupported support message type from user {int(user_id)}."
    await bridge_bot.send_message(text=fallback_text, **kwargs)


async def _hide_reply_keyboard(message: types.Message, lang: str) -> None:
    try:
        await send_loading_sticker(
            message,
            remove_keyboard=True,
            fallback_text=t(lang, "keyboard_cleanup_placeholder"),
        )
    except Exception:
        pass


def _user_settings_doc(user_doc: dict | None) -> dict:
    raw = (user_doc or {}).get("user_settings")
    if isinstance(raw, dict):
        return raw
    return {}


def _language_label(language: str) -> str:
    return "Arabic" if str(language or "").strip().lower() == "ar" else "English"


async def _user_settings_main_text(user_doc: dict | None, *, lang: str, bot_id: int, user_id: int) -> str:
    profile_text = await _user_profile_settings_text(
        user_doc,
        lang=lang,
        bot_id=bot_id,
        user_id=user_id,
    )
    balance_text = await _account_balance_text(
        user_doc,
        lang=lang,
        bot_id=bot_id,
        user_id=user_id,
    )
    return t(lang, "user_settings_main_text").format(
        title=t(lang, "user_settings_my_account"),
        balance_text=balance_text,
        profile_text=profile_text,
        hint=t(lang, "user_settings_hint"),
    )


SUPPORT_CATEGORIES = ("proxies", "numbers", "services", "user_balance")
NUMBERS_BOT_SUPPORT_CATEGORIES = ("numbers", "user_balance")
MAIN_BOT_SUPPORT_CATEGORIES = ("services", "user_balance")


def _support_category_label(lang: str, category: str) -> str:
    return t(lang, f"support_category_{category}")


def _support_menu_text(lang: str) -> str:
    return t(lang, "support_menu_text")


async def _support_categories_for_bot(bot_id: int) -> tuple[str, ...]:
    if await is_numbers_bot(bot_id):
        return NUMBERS_BOT_SUPPORT_CATEGORIES
    if await is_main_bot(bot_id):
        return MAIN_BOT_SUPPORT_CATEGORIES
    return SUPPORT_CATEGORIES


def _support_menu_kb(lang: str, categories: tuple[str, ...] = SUPPORT_CATEGORIES) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_support_category_label(lang, category), callback_data=f"support:cat:{category}")]
        for category in categories
        if category in SUPPORT_CATEGORIES
    ]
    rows.append([InlineKeyboardButton(text=t(lang, "user_settings_close"), callback_data="support:close")])
    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def _support_session_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, "support_done_button"))],
            [KeyboardButton(text=t(lang, "btn_cancel"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
    )


def _support_session_inline_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "support_done_button"), callback_data="support:done")],
            [InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="support:cancel")],
        ]
    )


def _support_session_intro(lang: str, category: str) -> str:
    return t(lang, "support_session_intro").format(category=_support_category_label(lang, category))


def _support_owner_reply_kb(*, lang: str, category: str, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "support_reply_button"),
                    callback_data=f"support:reply:{category}:{int(user_id)}",
                )
            ]
        ]
    )


def _support_ticket_action_kb(
    *,
    lang: str,
    ticket_id: str,
    bug_reward_paid: bool = False,
    bug_triage_status: str = "",
) -> InlineKeyboardMarkup:
    reward_text = "Rewarded $1" if bug_reward_paid else ("مكافأة $1" if str(lang or "").lower().startswith("ar") else "Reward bug $1")
    reward_callback = "support:bug_reward_paid" if bug_reward_paid else f"support:bug_reward:{ticket_id}"
    triage_status = str(bug_triage_status or "").lower()
    confirmed_text = "Bug confirmed" if triage_status != "confirmed" else "Confirmed bug"
    not_bug_text = "Not a bug"
    if str(lang or "").lower().startswith("ar"):
        confirmed_text = "تأكيد البغ" if triage_status != "confirmed" else "بغ مؤكد"
        not_bug_text = "ليس بغ"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t(lang, "support_reply_button"), callback_data=f"support:reply_ticket:{ticket_id}"),
                InlineKeyboardButton(text=t(lang, "support_solved_button"), callback_data=f"support:solve_ticket:{ticket_id}"),
            ],
            [
                InlineKeyboardButton(
                    text=confirmed_text,
                    callback_data="support:bug_triage_done" if triage_status == "confirmed" else f"support:bug_triage:confirmed:{ticket_id}",
                ),
                InlineKeyboardButton(
                    text=not_bug_text,
                    callback_data="support:bug_triage_done" if triage_status == "not_bug" else f"support:bug_triage:not_bug:{ticket_id}",
                ),
            ],
            [InlineKeyboardButton(text=reward_text, callback_data=reward_callback)],
        ]
    )


def _support_ticket_header(
    *,
    lang: str,
    ticket_no: int | None = None,
    category: str,
    user_doc: dict | None,
    user_id: int,
    bot_username: str,
) -> str:
    username_raw = str((user_doc or {}).get("username") or "").strip()
    username_display = f"@{username_raw}" if username_raw else "-"
    full_name = str((user_doc or {}).get("full_name") or "").strip() or "-"
    return t(lang, "support_ticket_header").format(
        ticket_no=int(ticket_no or 0),
        category=_support_category_label(lang, category),
        user_id=int(user_id),
        username=username_display,
        full_name=full_name,
        bot_username=bot_username or "-",
    )


async def _support_scope_for_bot(bot_id: int) -> tuple[str, int | None]:
    if await is_reseller_owned_bot(bot_id):
        reseller_id = await get_reseller_id_for_bot(bot_id)
        return "reseller", int(reseller_id) if reseller_id else None
    return "platform", None


async def _resolve_support_target(bot_id: int, category: str) -> dict | None:
    scope, owner_id = await _support_scope_for_bot(bot_id)
    if scope == "reseller" and owner_id:
        return await get_support_routing(owner_id, category)
    return await get_support_target(category)


async def _support_bot_for_scope(scope: str, current_bot: Bot) -> Bot:
    if scope == "platform":
        token = _support_bridge_token()
        if not token:
            raise TelegramBadRequest(method="sendMessage", message="support bridge bot is not configured")
        return Bot(token=token)
    return current_bot


def _configured_platform_bot_token(bot_id: int) -> str:
    for attr in (
        "bot_main_token",
        "bot_numbers_token",
        "bot_digital_products_token",
        "bot_card_ex_token",
        "bot_admin_token",
    ):
        token = str(getattr(settings, attr, "") or "").strip()
        if token and extract_bot_id_from_token(token) == int(bot_id):
            return token
    return ""


async def _support_reply_bot_for_ticket(ticket: dict, current_bot: Bot) -> tuple[Bot, bool]:
    source_bot_id = int((ticket or {}).get("source_bot_id") or 0)
    current_bot_id = int(await _current_bot_id(current_bot) or 0)
    if source_bot_id <= 0 or source_bot_id == current_bot_id:
        return current_bot, False

    token = _configured_platform_bot_token(source_bot_id)
    if not token:
        try:
            token = str(await get_bot_token(source_bot_id) or "").strip()
        except Exception:
            token = ""
    if not token:
        return current_bot, False
    return Bot(token=token), True


def _user_settings_main_kb(lang: str, user_doc: dict | None) -> InlineKeyboardMarkup:
    user_lang = str((user_doc or {}).get("language") or "en").strip().lower()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_add_balance"), callback_data="uset:recharge")],
            [
                InlineKeyboardButton(
                    text=f"{t(lang, 'user_settings_lang')}: {_language_label(user_lang)}",
                    callback_data="uset:lang",
                )
            ],
            [InlineKeyboardButton(text=t(lang, "user_settings_close"), callback_data="uset:close")],
        ]
    )


def _user_settings_lang_kb(lang: str, current_lang: str) -> InlineKeyboardMarkup:
    current = str(current_lang or "en").strip().lower()
    en_text = t(lang, "lang_en_button")
    ar_text = t(lang, "lang_ar_button")
    if current == "en":
        en_text = f"• {en_text}"
    else:
        ar_text = f"• {ar_text}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=en_text, callback_data="uset:langset:en")],
            [InlineKeyboardButton(text=ar_text, callback_data="uset:langset:ar")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="uset:open")],
        ]
    )


def _user_settings_back_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="uset:open")],
            [InlineKeyboardButton(text=t(lang, "user_settings_close"), callback_data="uset:close")],
        ]
    )


def _account_balance_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_add_balance"), callback_data="uset:recharge")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="uset:open")],
            [InlineKeyboardButton(text=t(lang, "user_settings_close"), callback_data="uset:close")],
        ]
    )


async def _update_user_settings(user_id: int, patch: dict) -> None:
    updates: dict[str, object] = {}
    for key, value in (patch or {}).items():
        updates[f"user_settings.{str(key)}"] = value
    if not updates:
        return
    await db.users.update_one({"telegram_id": int(user_id)}, {"$set": updates})


def _format_joined_date(value) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return "-"


async def _user_profile_settings_text(user_doc: dict | None, *, lang: str, bot_id: int, user_id: int) -> str:
    user_doc = user_doc or {}
    username_raw = str(user_doc.get("username") or "").strip()
    username_display = f"@{username_raw}" if username_raw else "-"
    language = _language_label(str(user_doc.get("language") or "en"))
    joined_at = _format_joined_date(user_doc.get("created_at"))
    if str(lang or "").lower().startswith("ar"):
        return (
            "تفاصيل الحساب\n"
            f"User ID: {int(user_id)}\n"
            f"Username: {username_display}\n"
            f"اللغة: {language}\n"
            f"تاريخ الانضمام: {joined_at}"
        )
    return (
        "Account details\n"
        f"User ID: {int(user_id)}\n"
        f"Username: {username_display}\n"
        f"Language: {language}\n"
        f"Joined: {joined_at}"
    )


async def _account_balance_text(user_doc: dict | None, *, lang: str, bot_id: int, user_id: int) -> str:
    wallet_scope_id = await _resolve_user_reseller(user_doc, bot_id=bot_id, user_id=user_id)
    if not wallet_scope_id:
        return await _wallet_scope_error_text(lang=lang, bot_id=bot_id)
    balance = await get_user_wallet_balance(user_id, int(wallet_scope_id))
    if await _uses_platform_wallet(bot_id):
        note = t(lang, "available_wallet_balance_note_platform_shared")
        return f"{t(lang, 'balance_info').format(balance=balance)}\n{note}"
    return t(lang, "balance_info").format(balance=balance)


async def _open_user_settings_message(message: types.Message, user_doc: dict | None, lang: str):
    bot_id = (await message.bot.get_me()).id
    text = await _user_settings_main_text(
        user_doc,
        lang=lang,
        bot_id=bot_id,
        user_id=message.from_user.id,
    )
    await message.answer(
        text,
        reply_markup=_user_settings_main_kb(lang, user_doc),
    )


async def _open_support_menu_message(message: types.Message, lang: str) -> None:
    bot_id = int(await _current_bot_id(message.bot) or 0)
    categories = await _support_categories_for_bot(bot_id)
    await message.answer(
        _support_menu_text(lang),
        reply_markup=_support_menu_kb(lang, categories),
    )


def _more_services_entries(lang: str) -> list[tuple[str, InlineKeyboardButton]]:
    entries: list[tuple[str, InlineKeyboardButton]] = []
    numbers_url = numbers_bot_url("numbers")
    digital_url = digital_products_bot_url("hub")
    card_url = card_ex_bot_url("cards")
    if numbers_url:
        entries.append(("numbers", InlineKeyboardButton(text=t(lang, "open_numbers_bot_button"), url=numbers_url)))
    if digital_url:
        entries.append(("digital_store", InlineKeyboardButton(text=t(lang, "open_digital_products_button"), url=digital_url)))
    if card_url:
        entries.append(("card_ex", InlineKeyboardButton(text=t(lang, "open_card_ex_bot_button"), url=card_url)))
    return entries


def _more_services_kb(lang: str) -> InlineKeyboardMarkup | None:
    entries = _more_services_entries(lang)
    if not entries:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[button] for _, button in entries])


async def _open_more_services_message(message: types.Message, lang: str) -> None:
    entries = _more_services_entries(lang)
    markup = InlineKeyboardMarkup(inline_keyboard=[[button] for _, button in entries]) if entries else None
    text = render_other_services_text(lang, [key for key, _ in entries]) if entries else t(lang, "more_services_not_configured_text")
    await message.answer(text, reply_markup=markup)


async def _send_support_header_if_needed(
    source_bot: Bot,
    *,
    state: FSMContext,
    lang: str,
    category: str,
    user_doc: dict | None,
    target: dict,
    user_id: int,
    source_chat_id: int,
) -> tuple[dict, Bot]:
    data = await state.get_data()
    scope, owner_id = await _support_scope_for_bot(int(await _current_bot_id(source_bot) or 0))
    bridge_bot = await _support_bot_for_scope(scope, source_bot)
    if data.get("support_ticket_id"):
        ticket = await get_support_ticket(str(data["support_ticket_id"]))
        if ticket:
            return ticket, bridge_bot

    me = await source_bot.get_me()
    payload_count = int(data.get("support_payload_count") or 0)
    ticket = await create_support_ticket(
        scope=scope,
        owner_id=owner_id,
        source_bot_id=int(await _current_bot_id(source_bot) or 0),
        chat_id=int(source_chat_id),
        user_id=user_id,
        username=str((user_doc or {}).get("username") or "").strip(),
        full_name=str((user_doc or {}).get("full_name") or "").strip(),
        category=category,
        payload_count=payload_count,
    )
    try:
        sent = await bridge_bot.send_message(
            chat_id=int(target["chat_id"]),
            text=_support_ticket_header(
                lang=lang,
                ticket_no=int(ticket.get("ticket_no") or 0),
                category=category,
                user_doc=user_doc,
                user_id=user_id,
                bot_username=f"@{me.username}" if getattr(me, "username", None) else str(me.id),
            ),
            message_thread_id=target.get("message_thread_id"),
            reply_markup=_support_ticket_action_kb(lang=lang, ticket_id=str(ticket["_id"])),
        )
        await set_ticket_delivery(
            ticket["_id"],
            target_chat_id=int(target["chat_id"]),
            target_thread_id=int(target["message_thread_id"]) if target.get("message_thread_id") is not None else None,
            header_message_id=int(getattr(sent, "message_id", 0) or 0),
        )
        await state.update_data(support_ticket_id=str(ticket["_id"]))
        return ticket, bridge_bot
    except Exception:
        if bridge_bot is not source_bot:
            try:
                await bridge_bot.session.close()
            except Exception:
                pass
        raise


async def _forward_support_message(
    source_bot: Bot,
    *,
    category: str,
    lang: str,
    state: FSMContext,
    user_doc: dict | None,
    user_id: int,
    source_chat_id: int,
    payloads: list[dict],
) -> bool:
    bot_id = int(await _current_bot_id(source_bot) or 0)
    target = await _resolve_support_target(bot_id, category)
    if not target or not isinstance(target.get("chat_id"), int):
        return False

    bridge_bot: Bot | None = None
    try:
        _, bridge_bot = await _send_support_header_if_needed(
            source_bot,
            state=state,
            lang=lang,
            category=category,
            user_doc=user_doc,
            target=target,
            user_id=user_id,
            source_chat_id=source_chat_id,
        )
        for payload in payloads:
            await _relay_support_payload(source_bot, bridge_bot, payload, target=target, user_id=user_id)
        return True
    except TelegramBadRequest as exc:
        logger.warning("support delivery failed category=%s user_id=%s error=%s", category, user_id, exc)
    except Exception:
        logger.exception("support delivery failed category=%s user_id=%s", category, user_id)
    finally:
        if bridge_bot is not None and bridge_bot is not source_bot:
            try:
                await bridge_bot.session.close()
            except Exception:
                pass
    return False


async def _build_reseller_stats_text(reseller_id: int, bot_id: int | None = None, lang: str = "en") -> str:
    rid = int(reseller_id)
    is_ar = str(lang or "").lower().startswith("ar")
    main_balance = await get_reseller_wallet_balance(rid, wallet_type="main")
    earnings_balance = await get_reseller_wallet_balance(rid, wallet_type="earnings")
    pending_recharge = await db.recharge_requests.count_documents({"reseller_id": rid, "status": "pending"})
    need_more_proof = await db.recharge_requests.count_documents({"reseller_id": rid, "status": "need_more_proof"})
    if is_ar:
        return (
            "📈 المبيعات والأرباح\n\n"
            f"معرّف الريسيلر: {rid}\n"
            f"رصيد البوت الرئيسي: {format_usd(main_balance)}\n"
            f"محفظة أرباح الكتالوج: {format_usd(earnings_balance)}\n"
            f"طلبات الشحن المعلقة: {pending_recharge}\n"
            f"طلبات تحتاج إثبات إضافي: {need_more_proof}"
        )
    return (
        "📈 Sales & Profit\n\n"
        f"Reseller ID: {rid}\n"
        f"Main Bot balance: {format_usd(main_balance)}\n"
        f"Catalog-profit wallet: {format_usd(earnings_balance)}\n"
        f"Pending recharge requests: {pending_recharge}\n"
        f"Need-more-proof requests: {need_more_proof}"
    )


async def _owned_bots_subscription_lines(owner_id: int, *, lang: str) -> list[str]:
    rows = await db.bots.find(
        {"owner_id": int(owner_id), "active": True},
        {"bot_id": 1, "subscription": 1, "username_lc": 1, "bot_username_lc": 1, "reseller.bot_username_lc": 1},
    ).sort("created_at", 1).to_list(length=20)
    if not rows:
        return []

    lines: list[str] = []
    for row in rows:
        label = (
            str(row.get("bot_username_lc") or "").strip()
            or str(row.get("username_lc") or "").strip()
            or str(((row.get("reseller") or {}).get("bot_username_lc")) or "").strip()
            or f"bot-{int(row.get('bot_id') or 0)}"
        )
        if not label.startswith("@") and not label.startswith("bot-"):
            label = f"@{label}"
        summary = subscription_summary_lines(lang, dict(row.get("subscription") or {}))
        compact = " | ".join(summary[:3])
        lines.append(f"- {label}: {compact}")
    return lines


async def _build_main_bot_reseller_balance_text(reseller_id: int, *, lang: str) -> str:
    main_balance = await get_reseller_wallet_balance(int(reseller_id), wallet_type="main")
    earnings_balance = await get_reseller_wallet_balance(int(reseller_id), wallet_type="earnings")
    bot_lines = await _owned_bots_subscription_lines(int(reseller_id), lang=lang)
    is_ar = str(lang or "").lower().startswith("ar")
    header = "رصيدك في البوت الرئيسي" if is_ar else "Your Main Bot balance"
    profit_label = "أرباح خدماتك الخاصة" if is_ar else "Custom-services profit"
    bots_title = "حالة اشتراك بوتاتك" if is_ar else "Your bot subscriptions"
    text = (
        f"{header}: {format_usd(main_balance)}\n"
        f"{profit_label}: {format_usd(earnings_balance)}\n"
        + ("\n\n" + bots_title + "\n" + "\n".join(bot_lines) if bot_lines else "")
    )
    return text


async def _maybe_send_exchange_rate_reminder(bot, reseller_id: int):
    meta = await get_exchange_rate_meta(int(reseller_id))
    updated_at = _as_utc(meta.get("updated_at"))
    if not updated_at:
        return

    now = datetime.now(UTC)
    if now - updated_at < timedelta(hours=24):
        return

    today = now.date().isoformat()
    if str(meta.get("last_reminder_date") or "") == today:
        return

    routing = await get_exchange_routing(int(reseller_id))
    if not routing:
        routing = await get_recharge_routing(int(reseller_id))
    if not routing:
        return

    text = t("en", "daily_exchange_reminder_card").format(
        rate=float(meta.get("usd_to_syp", 0)),
        updated_at=updated_at,
    )

    try:
        kwargs = {"chat_id": int(routing["chat_id"]), "text": text}
        if routing.get("message_thread_id") is not None:
            kwargs["message_thread_id"] = int(routing["message_thread_id"])
        await bot.send_message(**kwargs)
        await mark_exchange_rate_reminded_today(int(reseller_id))
    except Exception:
        return


async def _notify_recharge_request_to_review_queue(
    message: types.Message,
    req: dict,
    user_doc: dict | None,
    *,
    main_bot_flow: bool,
) -> tuple[bool, str, int | None, int | None, int | None]:
    wallet_scope = str(((req.get("details") or {}).get("wallet_scope")) or "").strip().lower()
    reseller_id = req.get("reseller_id")
    if reseller_id is None:
        return False, "missing_wallet_scope_id", None, None, None

    if not main_bot_flow:
        await _maybe_send_exchange_rate_reminder(message.bot, int(reseller_id))

    username = "@" + user_doc.get("username") if user_doc and user_doc.get("username") else "-"
    full_name = " ".join(filter(None, [message.from_user.first_name, message.from_user.last_name])) or "-"
    request_id = str(req.get("_id", "-"))
    details = req.get("details") or {}
    paid_amount = float(details.get("paid_amount", 0))
    paid_currency = str(details.get("paid_currency", "USD"))
    credits = float(req.get("amount", 0))
    caption = t("en", "user_manual_payment_request_card").format(
        request_id=request_id,
        user_id=message.from_user.id,
        username=username,
        full_name=full_name,
        method=req.get("method", "-"),
        paid_amount=paid_amount,
        paid_currency=paid_currency,
        credits=credits,
        created_at=req.get("created_at"),
    )

    kb = owner_reseller_topup_review_kb(request_id) if main_bot_flow else user_recharge_review_kb(request_id)

    async def _send_to_target(chat_id: int, message_thread_id: int | None = None, *, sender_bot: Bot | None = None):
        prev = req.get("delivery") or {}
        prev_chat = prev.get("chat_id")
        prev_msg = prev.get("message_id")
        prev_thread = prev.get("message_thread_id")
        active_bot = sender_bot or message.bot

        # avoid duplicate request cards: remove old delivery message first when possible
        if prev_chat is not None and prev_msg is not None:
            same_chat = int(prev_chat) == int(chat_id)
            same_thread = int(prev_thread) if prev_thread is not None else None
            now_thread = int(message_thread_id) if message_thread_id is not None else None
            if same_chat and same_thread == now_thread:
                try:
                    await active_bot.delete_message(chat_id=int(chat_id), message_id=int(prev_msg))
                except Exception:
                    pass

        kwargs = {"chat_id": int(chat_id), "reply_markup": kb}
        if message_thread_id is not None:
            kwargs["message_thread_id"] = int(message_thread_id)

        proof_file_id = req.get("proof_file_id")
        if proof_file_id:
            if active_bot is message.bot:
                sent = await active_bot.send_photo(photo=proof_file_id, caption=caption, **kwargs)
            else:
                data, filename = await _download_telegram_file(message.bot, str(proof_file_id))
                sent = await active_bot.send_photo(
                    photo=BufferedInputFile(data, filename=filename or "recharge-proof.jpg"),
                    caption=caption,
                    **kwargs,
                )
        else:
            sent = await active_bot.send_message(text=caption, **kwargs)
        return sent

    errors: list[str] = []
    if main_bot_flow:
        target = await db.system_settings.find_one({"_id": "owner_notifications"}) or {}
        target_chat_id = target.get("chat_id")
        if isinstance(target_chat_id, int):
            bridge_bot: Bot | None = None
            try:
                bridge_bot = await _platform_bridge_bot(message.bot)
                sent = await _send_to_target(
                    int(target_chat_id),
                    target.get("message_thread_id"),
                    sender_bot=bridge_bot,
                )
                return (
                    True,
                    "owner_topic",
                    int(getattr(sent, "message_id", 0) or 0),
                    int(target_chat_id),
                    int(target.get("message_thread_id")) if target.get("message_thread_id") is not None else None,
                )
            except Exception as exc:
                errors.append(f"owner_topic_send_failed:{exc}")
            finally:
                if bridge_bot is not None:
                    try:
                        await bridge_bot.session.close()
                    except Exception:
                        pass
    else:
        routing = await get_recharge_routing(int(reseller_id))
        if routing:
            try:
                sent = await _send_to_target(int(routing["chat_id"]), routing.get("message_thread_id"))
                return (
                    True,
                    "topic",
                    int(getattr(sent, "message_id", 0) or 0),
                    int(routing["chat_id"]),
                    int(routing.get("message_thread_id")) if routing.get("message_thread_id") is not None else None,
                )
            except Exception as exc:
                errors.append(f"topic_send_failed:{exc}")

        try:
            sent = await _send_to_target(int(reseller_id), None)
            return True, "reseller_dm_fallback", int(getattr(sent, "message_id", 0) or 0), int(reseller_id), None
        except Exception as exc:
            errors.append(f"dm_send_failed:{exc}")

    return False, " | ".join(errors) if errors else "delivery_failed", None, None, None


class RechargeFlow(StatesGroup):
    waiting_method = State()
    waiting_amount = State()
    waiting_proof = State()


class SupportFlow(StatesGroup):
    waiting_message = State()


class SupportOwnerReplyFlow(StatesGroup):
    waiting_message = State()


async def _resolve_user_reseller(user_doc: dict | None, *, bot_id: int, user_id: int) -> int | None:
    if await _uses_platform_wallet(bot_id):
        return int(user_id)
    reseller_id = await get_user_reseller_for_bot(user_id, bot_id)
    if reseller_id:
        return int(reseller_id)

    inferred = await get_reseller_id_for_bot(bot_id)
    if inferred:
        await set_user_reseller_for_bot(user_id, bot_id, int(inferred))
        return int(inferred)
    return None


async def _return_main_menu(message: types.Message, user_id: int) -> None:
    bot_id = (await message.bot.get_me()).id
    user = await get_user(user_id)
    lang = user.get("language", "en") if user else "en"
    if await is_reseller(user_id, bot_id=bot_id):
        await _hide_reply_keyboard(message, lang)
        await message.answer(t(lang, "reseller_menu_title"), reply_markup=reseller_main_menu(lang))
    else:
        await message.answer(t(lang, "main_menu"), reply_markup=await menu_for_current_bot(lang, bot_id, user_id=user_id))


@router.message(lambda msg: _is_btn(msg.text, "btn_balance") or _is_btn(msg.text, "btn_reseller_balance") or ((msg.text or "").startswith("/balance")))
async def balance_handler(message: types.Message):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    bot_id = (await message.bot.get_me()).id

    if await is_reseller(message.from_user.id, bot_id=bot_id):
        await message.answer(await _build_main_bot_reseller_balance_text(message.from_user.id, lang=lang))
        return

    wallet_scope_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)
    platform_wallet_flow = await _uses_platform_wallet(bot_id)
    if not wallet_scope_id:
        return await message.answer(await _wallet_scope_error_text(lang=lang, bot_id=bot_id))
    balance = await get_user_wallet_balance(message.from_user.id, int(wallet_scope_id))
    text = t(lang, "balance_info").format(balance=balance)
    if platform_wallet_flow:
        text += "\n" + t(lang, "available_wallet_balance_note_platform_shared")
    await message.answer(text, reply_markup=_account_balance_kb(lang))


@router.message(lambda msg: _is_btn(msg.text, "btn_add_balance"))
async def show_recharge_methods(message: types.Message, state: FSMContext):
    await _start_recharge_flow(message, state, user_id=message.from_user.id)


async def _start_recharge_flow(message: types.Message, state: FSMContext, *, user_id: int) -> None:
    user = await get_user(user_id)
    lang = user.get("language", "en") if user else "en"
    bot_id = (await message.bot.get_me()).id
    wallet_scope_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=user_id)
    platform_wallet_flow = await _uses_platform_wallet(bot_id)

    if not wallet_scope_id:
        return await message.answer(await _wallet_scope_error_text(lang=lang, bot_id=bot_id))

    methods_source = get_owner_payment_methods if platform_wallet_flow else get_payment_methods
    methods_arg = tuple() if platform_wallet_flow else (int(wallet_scope_id),)
    methods = [m for m in (await methods_source(*methods_arg)) if bool(m.get("enabled", True))]
    if not methods:
        return await message.answer(t(lang, "no_payment_methods_enabled"))
    view = [(m.get("title", m.get("code")), m.get("code")) for m in methods]
    await state.update_data(
        recharge_scope_id=int(wallet_scope_id),
        recharge_is_main_bot=bool(platform_wallet_flow),
        recharge_methods=methods,
        recharge_method_map={m.get("title", m.get("code")): m.get("code") for m in methods},
        recharge_lang=lang,
    )
    await state.set_state(RechargeFlow.waiting_method)
    await message.answer(t(lang, "recharge_choose_method"), reply_markup=recharge_methods_keyboard(view, lang=lang))


async def _select_recharge_method(message: types.Message, state: FSMContext, selected: dict, flow_lang: str) -> None:
    raw_target = str(selected.get("target") or "").strip()
    targets_block = f"<code>{escape(raw_target or '-')}</code>"

    rendered_instructions = str(selected.get("instructions") or "")
    currency_code = str(selected.get("currency", "USD")).upper()
    effective_rate = await _effective_recharge_per_credit(selected)
    try:
        rendered_instructions = rendered_instructions.format(
            target=raw_target or "-",
            support=selected.get("support", "@support"),
            per_credit=effective_rate,
            currency=currency_code,
        )
    except Exception:
        pass
    if raw_target:
        rendered_instructions = rendered_instructions.replace(raw_target, "").strip()

    method_title = escape(str(selected.get("title") or selected.get("code") or t(flow_lang, "payment_plain")))
    currency = escape(currency_code)
    is_ar_flow = str(flow_lang or "").lower().startswith("ar")
    target_label = "بيانات الدفع" if is_ar_flow else "Payment target"
    currency_label = "العملة" if is_ar_flow else "Currency"
    instructions = (
        f"<b>{method_title}</b>\n"
        f"{currency_label}: <b>{currency}</b>\n"
        f"{_recharge_rate_line(flow_lang, effective_rate, currency)}\n\n"
        f"{target_label}:\n"
        f"{targets_block}\n\n"
        f"{escape(rendered_instructions)}"
    ).strip()

    await state.update_data(recharge_method=selected)
    await state.set_state(RechargeFlow.waiting_amount)
    await message.answer(instructions, reply_markup=_pay_nav_kb(flow_lang), parse_mode="HTML")
    await message.answer(t(flow_lang, "send_amount_now"))


@router.callback_query(lambda c: c.data and c.data.startswith("recharge:method:"))
async def recharge_method_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    code = str((callback.data or "").split(":", 2)[2]).strip()
    methods = data.get("recharge_methods") or []
    selected = next((m for m in methods if str(m.get("code") or "").strip() == code), None)
    flow_lang = data.get("recharge_lang", "en")
    if not selected:
        await callback.answer(t(flow_lang, "choose_payment_method_from_keyboard"), show_alert=True)
        return
    await _select_recharge_method(callback.message, state, selected, flow_lang)
    await callback.answer()


@router.callback_query(lambda c: c.data == "recharge:cancel")
async def recharge_cancel_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    await state.clear()
    await _return_main_menu(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(lambda c: c.data == "recharge:back")
async def recharge_back_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    current_state = await state.get_state()
    lang = data.get("recharge_lang", "en")
    if current_state == RechargeFlow.waiting_method.state:
        await state.clear()
        await _return_main_menu(callback.message, callback.from_user.id)
    else:
        methods = data.get("recharge_methods") or []
        view = [(m.get("title", m.get("code")), m.get("code")) for m in methods]
        await state.set_state(RechargeFlow.waiting_method)
        await callback.message.answer(t(lang, "choose_recharge_method"), reply_markup=recharge_methods_keyboard(view, lang=lang))
    await callback.answer()


@router.message(RechargeFlow.waiting_method)
async def ask_recharge_amount(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    data = await state.get_data()
    user = await get_user(message.from_user.id)
    flow_lang = (user or {}).get("language", data.get("recharge_lang", "en"))

    if _is_account_button(text):
        return await _open_user_settings_message(message, user, flow_lang)

    if _is_btn(text, "btn_cancel") or _is_btn(text, "btn_back_main"):
        await state.clear()
        return await _return_main_menu(message, message.from_user.id)

    if _is_btn(text, "btn_balance"):
        user = await get_user(message.from_user.id)
        bot_id = (await message.bot.get_me()).id
        wallet_scope_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)
        if not wallet_scope_id:
            return await message.answer(
                await _wallet_scope_error_text(
                    lang=(user or {}).get("language", "en"),
                    bot_id=bot_id,
                )
            )
        bal = await get_user_wallet_balance(message.from_user.id, int(wallet_scope_id))
        return await message.answer(t((user or {}).get("language", "en"), "balance_info").format(balance=bal), reply_markup=_account_balance_kb((user or {}).get("language", "en")))

    if _is_btn(text, "btn_back"):
        await state.clear()
        return await _return_main_menu(message, message.from_user.id)

    methods = data.get("recharge_methods") or []
    title_to_code = data.get("recharge_method_map") or {}
    selected_code = title_to_code.get(text)
    selected = None
    for m in methods:
        if m.get("code") == selected_code:
            selected = m
            break

    if not selected:
        return await message.answer(t(data.get("recharge_lang", "en"), "choose_payment_method_from_keyboard"))

    await _select_recharge_method(message, state, selected, flow_lang)


@router.message(RechargeFlow.waiting_amount)
async def receive_recharge_amount(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", (await state.get_data()).get("recharge_lang", "en"))
    if _is_account_button(raw):
        return await _open_user_settings_message(message, user, lang)

    if _is_btn(raw, "btn_cancel") or _is_btn(raw, "btn_back_main"):
        await state.clear()
        return await _return_main_menu(message, message.from_user.id)
    if _is_btn(raw, "btn_balance"):
        user = await get_user(message.from_user.id)
        bot_id = (await message.bot.get_me()).id
        wallet_scope_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)
        if not wallet_scope_id:
            return await message.answer(
                await _wallet_scope_error_text(
                    lang=(user or {}).get("language", "en"),
                    bot_id=bot_id,
                )
            )
        bal = await get_user_wallet_balance(message.from_user.id, int(wallet_scope_id))
        return await message.answer(t((user or {}).get("language", "en"), "balance_info").format(balance=bal), reply_markup=_account_balance_kb((user or {}).get("language", "en")))

    if _is_btn(raw, "btn_back"):
        data = await state.get_data()
        methods = data.get("recharge_methods") or []
        view = [(m.get("title", m.get("code")), m.get("code")) for m in methods]
        await state.set_state(RechargeFlow.waiting_method)
        return await message.answer(t(lang, "choose_recharge_method"), reply_markup=recharge_methods_keyboard(view, lang=lang))

    try:
        paid_amount = float(raw)
    except Exception:
        return await message.answer(t(lang, "invalid_amount_send_numeric"))

    if paid_amount <= 0:
        return await message.answer(t(lang, "amount_must_be_greater_than_zero"))

    data = await state.get_data()
    method = data.get("recharge_method") or {}
    per_credit = await _effective_recharge_per_credit(method)
    credits = paid_amount / per_credit

    await state.update_data(
        recharge_paid_amount=paid_amount,
        recharge_credits=float(round(credits, 6)),
        recharge_per_credit=float(per_credit),
    )
    await state.set_state(RechargeFlow.waiting_proof)
    await message.answer(t(lang, "send_payment_proof_now"), reply_markup=_pay_nav_kb(lang))


@router.message(RechargeFlow.waiting_proof, lambda msg: msg.photo)
async def receive_recharge_proof(message: types.Message, state: FSMContext):
    data = await state.get_data()
    paid_amount = float(data.get("recharge_paid_amount") or 0)
    credits = float(data.get("recharge_credits") or 0)
    per_credit = float(data.get("recharge_per_credit") or 1.0)
    method = data.get("recharge_method") or {}
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"

    wallet_scope_id = data.get("recharge_scope_id")
    main_bot_flow = bool(data.get("recharge_is_main_bot"))
    if not wallet_scope_id:
        bot_id = (await message.bot.get_me()).id
        wallet_scope_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)

    if not wallet_scope_id:
        await state.clear()
        return await message.answer(
            t(lang, "recharge_failed_main_wallet_scope" if main_bot_flow else "recharge_failed_user_not_linked")
        )

    req = await create_recharge_request(
        user_id=message.from_user.id,
        method=method.get("title") or method.get("code") or "payment",
        amount=credits,
        proof_file_id=message.photo[-1].file_id,
        reseller_id=int(wallet_scope_id),
        details={
            "method_code": method.get("code"),
            "paid_amount": paid_amount,
            "paid_currency": str(method.get("currency", "USD")).upper(),
            "per_credit": per_credit,
            "credits": credits,
            "wallet_scope": "main_bot" if main_bot_flow else "reseller_bot",
            "source_bot_id": int(await _current_bot_id(message.bot) or 0),
        },
        wallet_type="user",
    )
    delivered, route, msg_id, chat_id, thread_id = await _notify_recharge_request_to_review_queue(
        message,
        req,
        user,
        main_bot_flow=main_bot_flow,
    )
    await db.recharge_requests.update_one(
        {"_id": req["_id"]},
        {
            "$set": {
                "delivery.delivered": bool(delivered),
                "delivery.route": route,
                "delivery.message_id": msg_id,
                "delivery.chat_id": chat_id,
                "delivery.message_thread_id": thread_id,
                "delivery.updated_at": datetime.now(UTC),
            }
        },
    )
    await state.clear()
    if delivered:
        if req.get("_reused"):
            await message.answer(
                t(lang, "recharge_request_updated_resubmitted_main_bot" if main_bot_flow else "recharge_request_updated_resubmitted"),
                reply_markup=types.ReplyKeyboardRemove(),
            )
        else:
            await message.answer(
                t(lang, "recharge_submitted_main_bot" if main_bot_flow else "recharge_submitted"),
                reply_markup=types.ReplyKeyboardRemove(),
            )
    else:
        await message.answer(
            t(lang, "recharge_saved_delivery_failed_main_bot" if main_bot_flow else "recharge_saved_delivery_failed"),
            reply_markup=types.ReplyKeyboardRemove(),
        )
    await _return_main_menu(message, message.from_user.id)



@router.message(RechargeFlow.waiting_proof)
async def receive_recharge_proof_text(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    data = await state.get_data()
    flow_lang = data.get("recharge_lang", "en")
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", flow_lang)

    if _is_account_button(raw):
        return await _open_user_settings_message(message, user, lang)

    if _is_btn(raw, "btn_cancel") or _is_btn(raw, "btn_back_main"):
        await state.clear()
        return await _return_main_menu(message, message.from_user.id)

    if _is_btn(raw, "btn_balance"):
        await state.clear()
        user = await get_user(message.from_user.id)
        bot_id = (await message.bot.get_me()).id
        wallet_scope_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)
        if not wallet_scope_id:
            return await message.answer(
                await _wallet_scope_error_text(
                    lang=(user or {}).get("language", "en"),
                    bot_id=bot_id,
                )
            )
        bal = await get_user_wallet_balance(message.from_user.id, int(wallet_scope_id))
        return await message.answer(
            t((user or {}).get("language", "en"), "balance_info").format(balance=bal),
            reply_markup=_account_balance_kb((user or {}).get("language", "en")),
        )

    if _is_btn(raw, "btn_back"):
        await state.set_state(RechargeFlow.waiting_amount)
        return await message.answer(t(lang, "send_amount_now"), reply_markup=_pay_nav_kb(lang))

    return await message.answer(
        t(lang, "send_payment_proof_screenshot_now"),
        reply_markup=_pay_nav_kb(lang),
    )


@router.message(lambda msg: _is_btn(msg.text, "btn_resend_proof"))
async def resend_proof_shortcut(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    bot_id = (await message.bot.get_me()).id
    req = await db.recharge_requests.find_one(
        {
            "user_id": int(message.from_user.id),
            "status": "need_more_proof",
        },
        sort=[("needs_more_proof_at", -1)],
    )
    if not req:
        await state.clear()
        return await message.answer(
            t(lang, "resend_proof_no_pending"),
            reply_markup=await menu_for_current_bot(lang, bot_id),
        )

    # Keep same business flow: user only needs to send a new screenshot in private chat.
    await state.clear()
    return await message.answer(
        t(lang, "resend_proof_prompt"),
        reply_markup=types.ReplyKeyboardRemove(),
    )


@router.message(StateFilter(None), lambda msg: bool(msg.photo) and bool(getattr(msg, "chat", None)) and msg.chat.type == "private")
async def receive_replacement_proof(message: types.Message, state: FSMContext):
    # Keep this catch-all narrow so active FSM flows, including reseller broadcast photos, can handle media.
    req = await db.recharge_requests.find_one(
        {
            "user_id": int(message.from_user.id),
            "status": "need_more_proof",
        },
        sort=[("needs_more_proof_at", -1)],
    )
    if not req:
        return

    await db.recharge_requests.update_one(
        {"_id": req["_id"], "status": "need_more_proof"},
        {
            "$set": {
                "status": "pending",
                "proof_file_id": message.photo[-1].file_id,
                "proof_replaced_at": datetime.now(UTC),
                "decision_note": "proof_replaced_after_need_more_proof",
            }
        },
    )

    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    refreshed = await db.recharge_requests.find_one({"_id": req["_id"]})
    refreshed = refreshed or {}
    wallet_scope = str(((refreshed.get("details") or {}).get("wallet_scope") or "")).strip().lower()
    bot_id = (await message.bot.get_me()).id
    main_bot_flow = wallet_scope == "main_bot" or await _uses_platform_wallet(bot_id)
    delivered, route, msg_id, chat_id, thread_id = await _notify_recharge_request_to_review_queue(
        message,
        refreshed,
        user,
        main_bot_flow=main_bot_flow,
    )
    await db.recharge_requests.update_one(
        {"_id": req["_id"]},
        {
            "$set": {
                "delivery.delivered": bool(delivered),
                "delivery.route": route,
                "delivery.message_id": msg_id,
                "delivery.chat_id": chat_id,
                "delivery.message_thread_id": thread_id,
                "delivery.updated_at": datetime.now(UTC),
            }
        },
    )
    await message.answer(
        t(lang, "resend_proof_updated"),
        reply_markup=types.ReplyKeyboardRemove(),
    )



@router.message(
    lambda msg: msg.text and (msg.text.lower() in {"reseller menu", "/reseller_menu"} or "????????" in msg.text)
)
async def show_reseller_menu(message: types.Message):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    bot_id = (await message.bot.get_me()).id

    if await is_reseller(message.from_user.id, bot_id=bot_id):
        await _hide_reply_keyboard(message, lang)
        await message.answer(t(lang, "reseller_menu_title"), reply_markup=reseller_main_menu(lang))
    else:
        await message.answer(t(lang, "reseller_only_command"))










def _norm_text(text: str | None) -> str:
    return (text or "").strip().lower()


@router.message(lambda msg: _is_btn(msg.text, "btn_back_main") or _is_btn(msg.text, "btn_cancel"))
async def back_to_main_menu_handler(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if await _handle_rental_exit_message_guard(message, state, target="main", lang=lang):
        return
    await state.clear()
    await _return_main_menu(message, message.from_user.id)


@router.message(lambda msg: _is_btn(msg.text, "btn_cyberzone_services"))
async def open_other_services_from_reseller_user_menu(message: types.Message):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    await _open_more_services_message(message, lang)


@router.message(lambda msg: _is_btn(msg.text, "btn_store"))
async def open_digital_products_from_main_menu(message: types.Message):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    await send_digital_products_message(message, lang=lang)


@router.message(lambda msg: _is_btn(msg.text, "btn_more_services"))
async def open_more_services_from_numbers_menu(message: types.Message):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    await _open_more_services_message(message, lang)


@router.callback_query(lambda c: c.data == "back_to_main_menu")
async def main_bot_services_back_to_menu(callback: types.CallbackQuery):
    await callback.answer()
    if not callback.message:
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _return_main_menu(callback.message, callback.from_user.id)


@router.message(lambda msg: _is_account_button(msg.text) or _is_btn(msg.text, "btn_reseller_stats") or _is_btn(msg.text, "btn_support"))
async def simple_menu_placeholders(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    if _is_btn(message.text, "btn_support"):
        return await _open_support_menu_message(message, lang)
    if _is_account_button(message.text):
        return await _open_user_settings_message(message, user, lang)
    if _is_btn(message.text, "btn_reseller_stats"):
        bot_id = (await message.bot.get_me()).id
        if not await is_reseller(message.from_user.id, bot_id=bot_id):
            return await message.answer(t(lang, "reseller_only_command"))
        return await message.answer(await _build_reseller_stats_text(message.from_user.id, bot_id, lang))


@router.callback_query(lambda c: c.data and c.data.startswith("support:cat:"))
async def support_category_selected(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    category = str((callback.data or "").split(":", 2)[2]).strip().lower()
    bot_id = int(await _current_bot_id(callback.bot) or 0)
    if category not in await _support_categories_for_bot(bot_id):
        return await callback.answer(t(lang, "support_invalid_category"), show_alert=True)
    target = await _resolve_support_target(bot_id, category)
    if not target or not isinstance(target.get("chat_id"), int):
        return await callback.answer(t(lang, "support_not_configured_text"), show_alert=True)
    scope, owner_id = await _support_scope_for_bot(bot_id)
    if await has_open_support_ticket(
        scope=scope,
        owner_id=owner_id,
        user_id=int(callback.from_user.id),
        category=category,
    ):
        return await callback.answer(t(lang, "support_open_ticket_exists"), show_alert=True)
    await state.clear()
    await state.set_state(SupportFlow.waiting_message)
    await state.update_data(
        support_category=category,
        support_header_sent=False,
        support_payloads=[],
        support_payload_count=0,
        support_ticket_id=None,
    )
    if callback.message:
        await _safe_edit_text(
            callback.message,
            _support_session_intro(lang, category),
            reply_markup=_support_session_inline_kb(lang),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "support:open")
async def support_open_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    await state.clear()
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await _open_support_menu_message(callback.message, lang)
    await callback.answer()


async def _finish_support_session(
    message: types.Message,
    state: FSMContext,
    *,
    user_id: int,
    user_doc: dict | None,
    lang: str,
) -> None:
    data = await state.get_data()
    category = str(data.get("support_category") or "").strip().lower()
    payloads = list(data.get("support_payloads") or [])
    delivered = False
    ticket_id = ""
    ticket_no = 0
    if category in SUPPORT_CATEGORIES and payloads:
        delivered = await _forward_support_message(
            message.bot,
            category=category,
            lang=lang,
            state=state,
            user_doc=user_doc,
            user_id=user_id,
            source_chat_id=message.chat.id,
            payloads=payloads,
        )
        ticket_id = str((await state.get_data()).get("support_ticket_id") or "").strip()
        if ticket_id:
            ticket = await get_support_ticket(ticket_id)
            ticket_no = int((ticket or {}).get("ticket_no") or 0)
    await state.clear()
    if not delivered:
        await message.answer(
            t(lang, "support_not_configured_text"),
            reply_markup=types.ReplyKeyboardRemove(),
        )
        await _return_main_menu(message, user_id)
        return
    await message.answer(
        t(lang, "support_done_eta_text").format(
            category=_support_category_label(lang, category),
            ticket_no=ticket_no or "-",
        ),
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await _return_main_menu(message, user_id)


async def _cancel_support_session(
    message: types.Message,
    state: FSMContext,
    *,
    user_id: int,
    lang: str,
) -> None:
    await state.clear()
    await message.answer(
        t(lang, "support_cancelled_text"),
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await _return_main_menu(message, user_id)


@router.callback_query(lambda c: c.data == "support:close")
async def support_close(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await _return_main_menu(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(lambda c: c.data == "support:done")
async def support_done_callback(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if callback.message:
        await _finish_support_session(
            callback.message,
            state,
            user_id=int(callback.from_user.id),
            user_doc=user,
            lang=lang,
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "support:cancel")
async def support_cancel_callback(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if callback.message:
        await _cancel_support_session(
            callback.message,
            state,
            user_id=int(callback.from_user.id),
            lang=lang,
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "support:ticket_solved")
async def support_ticket_solved_badge(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(lambda c: c.data == "support:bug_reward_paid")
async def support_ticket_bug_reward_paid_badge(callback: types.CallbackQuery):
    await callback.answer("Bug reward already paid.", show_alert=True)


@router.callback_query(lambda c: c.data == "support:bug_triage_done")
async def support_ticket_bug_triage_badge(callback: types.CallbackQuery):
    await callback.answer("Bug triage already set.", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("support:bug_triage:"))
async def support_ticket_bug_triage(callback: types.CallbackQuery):
    parts = str(callback.data or "").split(":", 3)
    if len(parts) != 4:
        await callback.answer("Could not process this action.", show_alert=True)
        return
    status = parts[2].strip().lower()
    ticket_id = parts[3].strip()
    if status not in {"confirmed", "not_bug"}:
        await callback.answer("Could not process this action.", show_alert=True)
        return
    ticket = await get_support_ticket(ticket_id)
    if not ticket:
        await callback.answer(t("en", "support_ticket_not_found"), show_alert=True)
        return
    if not await _support_actor_allowed(callback, ticket):
        await callback.answer(t("en", "no_permission"), show_alert=True)
        return

    await mark_support_ticket_bug_triage(ticket_id, actor_id=int(callback.from_user.id), status=status)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=_support_ticket_action_kb(
                    lang="en",
                    ticket_id=ticket_id,
                    bug_reward_paid=str(((ticket.get("bug_reward") or {}).get("status")) or "").lower() == "paid",
                    bug_triage_status=status,
                )
            )
        except Exception:
            pass
    await callback.answer("Bug confirmed." if status == "confirmed" else "Marked as not a bug.", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("support:bug_reward:"))
async def support_ticket_bug_reward(callback: types.CallbackQuery):
    ticket_id = str(callback.data or "").split(":", 2)[2].strip()
    ticket = await get_support_ticket(ticket_id)
    if not ticket:
        await callback.answer(t("en", "support_ticket_not_found"), show_alert=True)
        return
    if not await _support_actor_allowed(callback, ticket):
        await callback.answer(t("en", "no_permission"), show_alert=True)
        return
    if str(((ticket.get("bug_reward") or {}).get("status")) or "").lower() == "paid":
        await callback.answer("Bug reward already paid.", show_alert=True)
        return

    amount = 1.0
    claimed = await begin_support_ticket_bug_reward(ticket_id, actor_id=int(callback.from_user.id), amount=amount)
    if not claimed:
        await callback.answer("Reward is already being processed or paid.", show_alert=True)
        return

    user_id = int(ticket.get("user_id") or 0)
    source_bot_id = int(ticket.get("source_bot_id") or 0)
    user_doc = await get_user(user_id) if user_id > 0 else None
    wallet_scope_id = (
        await _resolve_user_reseller(user_doc, bot_id=source_bot_id, user_id=user_id)
        if user_id > 0 and source_bot_id > 0
        else None
    )
    if not wallet_scope_id:
        await mark_support_ticket_bug_reward_failed(ticket_id, actor_id=int(callback.from_user.id), error="wallet_scope_missing")
        await callback.answer("Could not resolve user wallet for this ticket.", show_alert=True)
        return

    try:
        ledger = await credit_user_wallet(
            user_id,
            int(wallet_scope_id),
            amount,
            "support_bug_reward",
            actor_id=int(callback.from_user.id),
            order_id=str(ticket["_id"]),
        )
    except Exception as exc:
        logger.exception("support bug reward credit failed ticket_id=%s", ticket_id)
        await mark_support_ticket_bug_reward_failed(ticket_id, actor_id=int(callback.from_user.id), error=str(exc))
        await callback.answer("Could not credit the reward. Try again after checking logs.", show_alert=True)
        return

    await mark_support_ticket_bug_reward_paid(
        ticket_id,
        actor_id=int(callback.from_user.id),
        amount=amount,
        wallet_scope_id=int(wallet_scope_id),
        ledger_id=(ledger or {}).get("_id"),
    )

    notice_bot = callback.bot
    close_notice_bot = False
    try:
        notice_bot, close_notice_bot = await _support_reply_bot_for_ticket(ticket, callback.bot)
        user_lang = str((user_doc or {}).get("language") or "").lower()
        await notice_bot.send_message(
            chat_id=user_id,
            text=(
                "تم إضافة مكافأة $1 لرصيدك بعد تأكيد تقرير المشكلة. شكراً لمساعدتك."
                if user_lang.startswith("ar")
                else "A $1 reward was added to your balance after your bug report was confirmed. Thank you for helping."
            ),
        )
    except Exception:
        pass
    finally:
        if close_notice_bot:
            try:
                await notice_bot.session.close()
            except Exception:
                pass

    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=_support_ticket_action_kb(lang="en", ticket_id=ticket_id, bug_reward_paid=True)
            )
        except Exception:
            pass
    await callback.answer("Bug reward credited: $1.", show_alert=True)


@router.message(SupportFlow.waiting_message)
async def support_message_router(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    raw = (message.text or "").strip()
    if raw == t(lang, "support_done_button") or _is_slash_command(raw, "done"):
        return await _finish_support_session(
            message,
            state,
            user_id=int(message.from_user.id),
            user_doc=user,
            lang=lang,
        )
    if _is_btn(raw, "btn_cancel") or _is_slash_command(raw, "cancel"):
        return await _cancel_support_session(
            message,
            state,
            user_id=int(message.from_user.id),
            lang=lang,
        )

    data = await state.get_data()
    category = str(data.get("support_category") or "").strip().lower()
    if category not in SUPPORT_CATEGORIES:
        await state.clear()
        return await _return_main_menu(message, message.from_user.id)
    payloads = list(data.get("support_payloads") or [])
    payloads.append(_extract_support_payload(message))
    await state.update_data(
        support_payloads=payloads,
        support_payload_count=int(data.get("support_payload_count") or 0) + 1,
    )


async def _support_actor_allowed(callback: types.CallbackQuery, ticket: dict | None) -> bool:
    if not ticket:
        return False
    scope = str(ticket.get("scope") or "").strip().lower()
    if scope == "platform":
        return int(callback.from_user.id) == int(OWNER_ID)
    owner_id = int(ticket.get("owner_id") or 0)
    if owner_id <= 0:
        bot_id = int(await _current_bot_id(callback.bot) or 0)
        owner_id = int(await get_reseller_id_for_bot(bot_id) or 0)
    return owner_id > 0 and int(callback.from_user.id) == owner_id


@router.callback_query(lambda c: c.data and c.data.startswith("support:reply_ticket:"))
async def support_owner_reply_open(callback: types.CallbackQuery, state: FSMContext):
    ticket_id = str(callback.data or "").split(":", 2)[2].strip()
    ticket = await get_support_ticket(ticket_id)
    if not ticket:
        await callback.answer(t("en", "support_ticket_not_found"), show_alert=True)
        return
    if not await _support_actor_allowed(callback, ticket):
        await callback.answer(t("en", "no_permission"), show_alert=True)
        return
    await state.clear()
    await state.set_state(SupportOwnerReplyFlow.waiting_message)
    await state.update_data(
        support_reply_user_id=int(ticket.get("user_id") or 0),
        support_reply_category=str(ticket.get("category") or ""),
        support_reply_ticket_id=str(ticket["_id"]),
        support_reply_actor_id=int(callback.from_user.id),
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            t("en", "support_owner_reply_prompt").format(
                user_id=int(ticket.get("user_id") or 0),
                category=_support_category_label("en", str(ticket.get("category") or "")),
            ),
            reply_markup=_support_session_kb("en"),
        )


@router.message(SupportOwnerReplyFlow.waiting_message)
async def support_owner_reply_router(message: types.Message, state: FSMContext):
    data = await state.get_data()
    actor_id = int(data.get("support_reply_actor_id") or OWNER_ID)
    if int(message.from_user.id) != actor_id:
        return
    raw = (message.text or "").strip()
    if raw in {t("en", "support_done_button"), t("ar", "support_done_button")} or _is_slash_command(raw, "done"):
        await state.clear()
        await message.answer(t("en", "support_owner_reply_done"), reply_markup=types.ReplyKeyboardRemove())
        return
    if raw in {t("en", "btn_cancel"), t("ar", "btn_cancel")} or _is_slash_command(raw, "cancel"):
        await state.clear()
        await message.answer(t("en", "support_owner_reply_cancelled"), reply_markup=types.ReplyKeyboardRemove())
        return

    target_user_id = int(data.get("support_reply_user_id") or 0)
    ticket_id = str(data.get("support_reply_ticket_id") or "").strip()
    if target_user_id <= 0:
        await state.clear()
        await message.answer(t("en", "support_owner_reply_cancelled"), reply_markup=types.ReplyKeyboardRemove())
        return

    reply_bot = message.bot
    close_reply_bot = False
    try:
        ticket = await get_support_ticket(ticket_id) if ticket_id else None
        if ticket:
            reply_bot, close_reply_bot = await _support_reply_bot_for_ticket(ticket, message.bot)
        await _relay_support_payload(
            message.bot,
            reply_bot,
            _extract_support_payload(message),
            target={"chat_id": target_user_id},
            user_id=target_user_id,
        )
        if ticket_id:
            await mark_support_ticket_replied(ticket_id, actor_id=int(message.from_user.id))
        await message.answer(t("en", "support_owner_reply_sent"), reply_markup=_support_session_kb("en"))
    except TelegramBadRequest:
        await message.answer(t("en", "support_owner_reply_failed_user"), reply_markup=_support_session_kb("en"))
    except Exception:
        logger.exception("support owner reply failed user_id=%s", target_user_id)
        await message.answer(t("en", "support_owner_reply_failed_user"), reply_markup=_support_session_kb("en"))
    finally:
        if close_reply_bot:
            try:
                await reply_bot.session.close()
            except Exception:
                pass


@router.callback_query(lambda c: c.data and c.data.startswith("support:solve_ticket:"))
async def support_ticket_solve(callback: types.CallbackQuery):
    ticket_id = str(callback.data or "").split(":", 2)[2].strip()
    ticket = await get_support_ticket(ticket_id)
    if not ticket:
        await callback.answer(t("en", "support_ticket_not_found"), show_alert=True)
        return
    if not await _support_actor_allowed(callback, ticket):
        await callback.answer(t("en", "no_permission"), show_alert=True)
        return
    await mark_support_ticket_solved(ticket_id, actor_id=int(callback.from_user.id))
    notice_bot = callback.bot
    close_notice_bot = False
    try:
        notice_bot, close_notice_bot = await _support_reply_bot_for_ticket(ticket, callback.bot)
        await notice_bot.send_message(
            chat_id=int(ticket.get("user_id") or 0),
            text=t("en", "support_ticket_solved_user"),
        )
    except Exception:
        pass
    finally:
        if close_notice_bot:
            try:
                await notice_bot.session.close()
            except Exception:
                pass
    await callback.answer(t("en", "support_ticket_solved_admin"), show_alert=True)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=t("en", "support_ticket_solved_badge"), callback_data="support:ticket_solved")]
                    ]
                )
            )
        except Exception:
            pass


@router.callback_query(lambda c: c.data == "uset:open")
async def user_settings_open_callback(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    bot_id = (await callback.bot.get_me()).id
    await callback.message.edit_text(
        await _user_settings_main_text(
            user,
            lang=lang,
            bot_id=bot_id,
            user_id=callback.from_user.id,
        ),
        reply_markup=_user_settings_main_kb(lang, user),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "uset:balance")
async def user_settings_balance_callback(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    bot_id = (await callback.bot.get_me()).id
    await callback.message.edit_text(
        await _account_balance_text(
            user,
            lang=lang,
            bot_id=bot_id,
            user_id=callback.from_user.id,
        ),
        reply_markup=_account_balance_kb(lang),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "uset:recharge")
async def user_settings_recharge_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    await _start_recharge_flow(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(lambda c: c.data == "uset:lang")
async def user_settings_language_menu(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    current_lang = str((user or {}).get("language") or "en")
    await callback.message.edit_text(
        t(lang, "user_settings_choose_lang"),
        reply_markup=_user_settings_lang_kb(lang, current_lang),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("uset:langset:"))
async def user_settings_language_set(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    selected = callback.data.split(":", 2)[2].strip().lower()
    current_lang = str((await get_user(callback.from_user.id) or {}).get("language") or "en")
    if selected not in {"en", "ar"}:
        return await callback.answer(t(current_lang, "invalid_language"), show_alert=True)
    await db.users.update_one({"telegram_id": int(callback.from_user.id)}, {"$set": {"language": selected}})
    user = await get_user(callback.from_user.id)
    lang = selected
    bot_id = (await callback.bot.get_me()).id
    if await is_numbers_bot(bot_id):
        await state.clear()
        from handlers.start import _open_numbers_start_menu

        await _open_numbers_start_menu(callback.message, state, lang=lang)
        await callback.answer(t(lang, "user_settings_saved"), show_alert=True)
        return

    await callback.message.edit_text(
        await _user_settings_main_text(
            user,
            lang=lang,
            bot_id=bot_id,
            user_id=callback.from_user.id,
        ),
        reply_markup=_user_settings_main_kb(lang, user),
    )
    await callback.message.answer(
        t(lang, "main_menu"),
        reply_markup=await menu_for_current_bot(lang, bot_id, user_id=callback.from_user.id),
    )
    await callback.answer(t(lang, "user_settings_saved"), show_alert=True)


@router.callback_query(lambda c: c.data == "uset:profile")
async def user_settings_profile(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    bot_id = (await callback.bot.get_me()).id
    profile_text = await _user_profile_settings_text(
        user,
        lang=lang,
        bot_id=bot_id,
        user_id=callback.from_user.id,
    )
    await callback.message.edit_text(profile_text, reply_markup=_user_settings_back_kb(lang))
    await callback.answer()


@router.callback_query(lambda c: c.data == "uset:close")
async def user_settings_close(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _return_main_menu(callback.message, callback.from_user.id)
    await callback.answer()





















