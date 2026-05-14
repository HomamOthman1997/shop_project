from datetime import UTC, datetime
import asyncio
import logging
import re
import uuid
from html import escape

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    KeyboardButton,
    KeyboardButtonRequestChat,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import settings
from database.bots_repo import (
    BotAlreadyRegisteredError,
    add_bot,
    mark_bot_provisioning_status,
    update_bot_channel,
    update_reseller_info,
    verify_bot,
)
from services.subscriptions.bot_subscription_service import get_bot_subscription
from database.custom_services_repo import clone_catalog_from_reseller_template
from database.financial_ledger import get_reseller_wallet_balance
from database.mongo import db
from database.reseller_settings_repo import get_exchange_routing, get_recharge_routing
from database.user_repo import get_user
from keyboards.reseller_main_menu import reseller_main_menu
from utils.bot_menu_context import is_reseller_owned_bot, menu_for_current_bot, send_main_bot_message
from utils.permissions import is_reseller
from utils.translations import t
from utils.user_money import format_usd

router = Router()
logger = logging.getLogger("verify_reseller")


class VerifyReseller(StatesGroup):
    waiting_for_intro = State()
    waiting_for_token = State()
    waiting_for_channel = State()
    waiting_for_fullname = State()
    waiting_for_phone = State()
    waiting_for_address = State()
    waiting_for_confirm = State()


PROMPT_MSG_ID_KEY = "verify_prompt_msg_id"
INTRO_MSG_ID_KEY = "verify_intro_msg_id"
PHONE_PROMPT_MSG_ID_KEY = "verify_phone_prompt_msg_id"
ADDRESS_PROMPT_MSG_ID_KEY = "verify_address_prompt_msg_id"
CHANNEL_PROMPT_MSG_ID_KEY = "verify_channel_prompt_msg_id"
FLOW_REF_KEY = "verify_flow_ref"
REPLY_KB_ANCHOR_MSG_ID_KEY = "verify_reply_kb_anchor_msg_id"


def is_valid_token(text: str):
    return bool(_extract_token_input(text))


def _normalize_token_input(raw: str) -> str:
    if not raw:
        return ""
    cleaned = raw.strip().strip("`'\"<>[](){}")
    # Normalize common unicode punctuation that breaks token parsing.
    cleaned = re.sub(r"[：﹕꞉∶ː]", ":", cleaned)
    cleaned = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\s]+", "", cleaned)
    return cleaned


def _extract_token_input(raw: str) -> str:
    cleaned = _normalize_token_input(raw)
    if not cleaned:
        return ""
    m = re.search(r"(\d{8,12}:[A-Za-z0-9_-]{20,})", cleaned)
    if m:
        return m.group(1)
    return cleaned


def _verify_nav_kb(lang: str, include_back: bool) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if include_back:
        kb.button(text=t(lang, "back"), callback_data="verify_nav:back")
    kb.button(text=t(lang, "cancel"), callback_data="verify_nav:cancel", style="danger")
    kb.adjust(1)
    return kb.as_markup()


def _verify_token_kb(lang: str, include_back: bool = False, *, retry: bool = False) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if retry:
        kb.button(text=t(lang, "send_new_token_button"), callback_data="verify:retry_token")
    kb.button(text=t(lang, "open_botfather_button"), url="https://t.me/BotFather")
    if include_back:
        kb.button(text=t(lang, "back"), callback_data="verify_nav:back")
    kb.button(text=t(lang, "cancel"), callback_data="verify_nav:cancel", style="danger")
    kb.adjust(1)
    return kb.as_markup()


def _verify_confirm_kb(
    lang: str,
    *,
    setup_required: bool = False,
) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if setup_required:
        kb.button(text=t(lang, "verify_create_group_add_bot"), callback_data="verify:open_group_create")
        kb.button(text=t(lang, "verify_recheck_setup"), callback_data="verify:confirm_create")
    else:
        kb.button(text=t(lang, "confirm_create_bot"), callback_data="verify:confirm_create")
    kb.button(text=t(lang, "back"), callback_data="verify_nav:back")
    kb.button(text=t(lang, "cancel"), callback_data="verify:cancel_create", style="danger")
    kb.adjust(1)
    return kb.as_markup()


def _verify_intro_kb(lang: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "continue_create_flow"), callback_data="verify:start_token")
    kb.button(text=t(lang, "cancel"), callback_data="verify_nav:cancel", style="danger")
    kb.adjust(1)
    return kb.as_markup()


def _is_ar(lang: str) -> bool:
    return str(lang or "").lower().startswith("ar")


def _step_label(lang: str, step: int, title_en: str, title_ar: str) -> str:
    if _is_ar(lang):
        return f"الخطوة {step}/6 - {title_ar}"
    return f"Step {step}/6 - {title_en}"


def _step_prompt_html(lang: str, step: int, title_en: str, title_ar: str, body: str) -> str:
    return f"<b>{escape(_step_label(lang, step, title_en, title_ar))}</b>\n\n{_as_html_quote(body)}"


def _intro_prompt_html(lang: str) -> str:
    title = "قبل ما نبدأ" if _is_ar(lang) else "Before We Start"
    return f"<b>{escape(title)}</b>\n\n{_as_html_quote(_intro_rest_text(lang))}"


def _token_prompt_html(lang: str, prefix: str | None = None) -> str:
    body = _token_rest_text(lang)
    if prefix:
        body = f"{prefix}\n\n{body}"
    return _step_prompt_html(lang, 1, "Bot Token", "توكن البوت", body)


def _summary_prompt_html(lang: str, summary_text: str) -> str:
    return _step_prompt_html(lang, 6, "Review & Activate", "المراجعة والتفعيل", summary_text)


def _bot_already_registered_text(lang: str) -> str:
    return t(lang, "bot_already_registered_detail")


def _add_to_channel_url(bot_username: str) -> str:
    username = (bot_username or "").lstrip("@").strip()
    # Ask for broad admin rights up front to avoid future permission gaps.
    perms = "+".join(
        [
            "manage_chat",
            "post_messages",
            "edit_messages",
            "delete_messages",
            "invite_users",
            "restrict_members",
            "promote_members",
            "change_info",
            "manage_video_chats",
            "pin_messages",
            "anonymous",
        ]
    )
    return f"https://t.me/{username}?startchannel&admin={perms}"


def _add_to_group_url(bot_username: str) -> str:
    username = (bot_username or "").lstrip("@").strip()
    perms = "+".join(
        [
            "manage_chat",
            "invite_users",
            "delete_messages",
            "restrict_members",
            "promote_members",
            "change_info",
            "manage_video_chats",
            "pin_messages",
            "anonymous",
            "manage_topics",
        ]
    )
    return f"https://t.me/{username}?startgroup=true&admin={perms}"


def _verify_channel_admin_kb(lang: str, add_url: str, include_back: bool = True) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "add_bot_to_channel"), url=add_url)
    kb.button(text=t(lang, "check_channel_admin"), callback_data="verify:check_channel_admin")
    if include_back:
        kb.button(text=t(lang, "back"), callback_data="verify_nav:back")
    kb.button(text=t(lang, "cancel"), callback_data="verify_nav:cancel", style="danger")
    kb.adjust(1)
    return kb.as_markup()


def _verify_setup_help_kb(lang: str, group_add_url: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "verify_create_group_add_bot"), url=group_add_url)
    kb.button(text=t(lang, "verify_recheck_setup"), callback_data="verify:confirm_create")
    kb.button(text=t(lang, "back"), callback_data="verify:back_summary")
    kb.button(text=t(lang, "cancel"), callback_data="verify:cancel_create", style="danger")
    kb.adjust(1)
    return kb.as_markup()


def _approval_followup_kb(lang: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "open_reseller_settings_button"), callback_data="rsmenu:settings")
    kb.button(text=t(lang, "open_reseller_dashboard_button"), callback_data="rsmenu:dashboard")
    kb.adjust(1)
    return kb.as_markup()


def _subscription_notice_text(lang: str, subscription: dict) -> str:
    status = str(subscription.get("status") or "").strip().lower()
    price = float(subscription.get("monthly_price_usd") or 10.0)
    trial_price = float(subscription.get("trial_price_usd") or 1.0)
    trial_ends = subscription.get("trial_ends_at")
    if str(lang or "").lower().startswith("ar"):
        if status == "trial_active":
            end_txt = trial_ends.strftime("%Y-%m-%d %H:%M UTC") if isinstance(trial_ends, datetime) else "-"
            return (
                "حالة الاشتراك:\n"
                f"- تم تفعيل أول شهر تجريبي مدفوع بقيمة {format_usd(trial_price)}.\n"
                f"- رسم التجديد بعد الشهر التجريبي: {format_usd(price)} شهريًا.\n"
                f"- ينتهي الشهر التجريبي بتاريخ: {end_txt}"
            )
        return (
            "حالة الاشتراك:\n"
            f"- هذا البوت يحتاج دفعة أولى بقيمة {format_usd(trial_price)} للتفعيل.\n"
            f"- يتم سحبها من رصيد الريسيلر في البوت المركزي.\n"
            f"- رسم التجديد بعد ذلك: {format_usd(price)} شهريًا."
        )
    if status == "trial_active":
        end_txt = trial_ends.strftime("%Y-%m-%d %H:%M UTC") if isinstance(trial_ends, datetime) else "-"
        return (
            "Subscription status:\n"
            f"- The first paid trial month was activated for {format_usd(trial_price)}.\n"
            f"- Renewal after the trial month: {format_usd(price)} per month.\n"
            f"- Trial month ends at: {end_txt}"
        )
    return (
        "Subscription status:\n"
        f"- This bot needs an initial {format_usd(trial_price)} payment to activate.\n"
            "- The amount is collected from the reseller balance in the main bot.\n"
        f"- Renewal after that: {format_usd(price)} per month."
    )


def _phone_request_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "phone_share_button"), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _channel_request_kb(lang: str) -> ReplyKeyboardMarkup:
    # Keep request lightweight; admin rights are verified in the next step.
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=t(lang, "channel_picker_button"),
                    request_chat=KeyboardButtonRequestChat(
                        request_id=1,
                        chat_is_channel=True,
                        chat_has_username=True,
                        request_title=True,
                        request_username=True,
                    ),
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _safe_message_answer(message: types.Message, text: str, **kwargs):
    for attempt in range(3):
        try:
            return await message.answer(text, request_timeout=20, **kwargs)
        except TelegramNetworkError:
            if attempt == 2:
                raise
            await asyncio.sleep(0.8 * (attempt + 1))


async def _safe_bot_send_message(bot: Bot, chat_id: int, **kwargs):
    for attempt in range(3):
        try:
            return await bot.send_message(chat_id=chat_id, request_timeout=20, **kwargs)
        except TelegramNetworkError:
            if attempt == 2:
                raise
            await asyncio.sleep(0.8 * (attempt + 1))

async def _safe_delete_user_message(message: types.Message, *, context: str) -> None:
    for attempt in range(3):
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
            return
        except TelegramNetworkError:
            if attempt == 2:
                logger.warning("delete message network failure context=%s chat_id=%s msg_id=%s", context, message.chat.id, message.message_id)
                return
            await asyncio.sleep(0.5 * (attempt + 1))
        except TelegramBadRequest as exc:
            logger.warning(
                "delete message rejected context=%s chat_id=%s msg_id=%s err=%s",
                context,
                message.chat.id,
                message.message_id,
                exc,
            )
            return
        except Exception as exc:
            logger.warning(
                "delete message unexpected context=%s chat_id=%s msg_id=%s err=%s",
                context,
                message.chat.id,
                message.message_id,
                exc,
            )
            return


async def _set_or_edit_prompt(
    *,
    bot: Bot,
    chat_id: int,
    state: FSMContext,
    text: str,
    reply_markup: types.InlineKeyboardMarkup,
    parse_mode: str | None = None,
    preferred_message_id: int | None = None,
):
    data = await state.get_data()
    flow_ref = data.get(FLOW_REF_KEY)
    if flow_ref:
        ref_line = t(data.get("lang", "en"), "request_ref_line").format(ref=flow_ref)
        if parse_mode == "HTML":
            text = f"{text}\n\n<blockquote>{escape(ref_line)}</blockquote>"
        else:
            text = f"{text}\n\n{ref_line}"

    msg_id = preferred_message_id or data.get(PROMPT_MSG_ID_KEY)
    if msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            await state.update_data(**{PROMPT_MSG_ID_KEY: msg_id})
            return
        except TelegramBadRequest as exc:
            msg = str(exc).lower()
            if "message is not modified" in msg:
                await state.update_data(**{PROMPT_MSG_ID_KEY: msg_id})
                return
            if "message can't be edited" not in msg:
                pass
        except Exception:
            pass

    sent = await _safe_bot_send_message(
        bot=bot,
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )
    await state.update_data(**{PROMPT_MSG_ID_KEY: sent.message_id})


async def _delete_intro_message(bot: Bot, chat_id: int, state: FSMContext):
    data = await state.get_data()
    intro_id = data.get(INTRO_MSG_ID_KEY)
    if not intro_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=intro_id)
    except Exception:
        pass
    await state.update_data(**{INTRO_MSG_ID_KEY: None})


async def _delete_state_message_by_key(bot: Bot, chat_id: int, state: FSMContext, key: str):
    data = await state.get_data()
    msg_id = data.get(key)
    if not msg_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
    await state.update_data(**{key: None})


async def _clear_reply_keyboard_anchor(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    anchor_id = data.get(REPLY_KB_ANCHOR_MSG_ID_KEY)
    if not anchor_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=int(anchor_id))
    except Exception:
        pass
    await state.update_data(**{REPLY_KB_ANCHOR_MSG_ID_KEY: None})


async def _show_channel_picker_prompt(bot: Bot, chat_id: int, state: FSMContext, lang: str):
    await _refresh_reply_keyboard(bot=bot, chat_id=chat_id, state=state, reply_markup=_channel_request_kb(lang))


async def _show_phone_request_keyboard(bot: Bot, chat_id: int, state: FSMContext, lang: str):
    await _refresh_reply_keyboard(bot=bot, chat_id=chat_id, state=state, reply_markup=_phone_request_kb(lang))


async def _refresh_reply_keyboard(
    bot: Bot,
    chat_id: int,
    state: FSMContext | None = None,
    reply_markup: ReplyKeyboardMarkup | None = None,
):
    if reply_markup is None:
        return
    if state is not None:
        await _clear_reply_keyboard_anchor(bot, chat_id, state)
    try:
        sent = await _safe_bot_send_message(
            bot=bot,
            chat_id=chat_id,
            text="\u2800",
            reply_markup=reply_markup,
        )
        if state is not None:
            await state.update_data(**{REPLY_KB_ANCHOR_MSG_ID_KEY: getattr(sent, "message_id", None)})
    except Exception:
        pass


async def _hide_reply_keyboard(bot: Bot, chat_id: int, state: FSMContext | None = None):
    if state is not None:
        await _clear_reply_keyboard_anchor(bot, chat_id, state)
    try:
        sent = await _safe_bot_send_message(
            bot=bot,
            chat_id=chat_id,
            text="\u2800",
            reply_markup=ReplyKeyboardRemove(),
        )
        if state is not None:
            await state.update_data(**{REPLY_KB_ANCHOR_MSG_ID_KEY: getattr(sent, "message_id", None)})
    except Exception:
        pass


async def _return_to_main_menu(target: types.Message | types.CallbackQuery, user_id: int, lang: str, bot: Bot, state: FSMContext):
    bot_id = (await bot.get_me()).id
    if await is_reseller(user_id, bot_id=bot_id):
        markup = reseller_main_menu(lang)
    else:
        markup = await menu_for_current_bot(lang, bot_id)

    chat_id = target.message.chat.id if isinstance(target, types.CallbackQuery) else target.chat.id
    await _delete_intro_message(bot, chat_id, state)
    await _delete_state_message_by_key(bot, chat_id, state, PHONE_PROMPT_MSG_ID_KEY)
    await _delete_state_message_by_key(bot, chat_id, state, ADDRESS_PROMPT_MSG_ID_KEY)
    await _delete_state_message_by_key(bot, chat_id, state, CHANNEL_PROMPT_MSG_ID_KEY)
    await _clear_reply_keyboard_anchor(bot, chat_id, state)
    if await is_reseller(user_id, bot_id=bot_id):
        await _hide_reply_keyboard(bot, chat_id, state)
    await state.clear()
    if isinstance(target, types.CallbackQuery):
        await target.message.answer(t(lang, "main_menu"), reply_markup=markup)
    else:
        await target.answer(t(lang, "main_menu"), reply_markup=markup)


def _token_rest_text(lang: str) -> str:
    token_text = t(lang, "send_token")
    lines = token_text.splitlines()
    if len(lines) <= 1:
        return token_text
    return "\n".join(lines[1:]).strip()


def _intro_rest_text(lang: str) -> str:
    intro_text = t(lang, "reseller_create_intro")
    lines = intro_text.splitlines()
    if len(lines) <= 1:
        return intro_text
    return "\n".join(lines[1:]).strip()


def _as_html_quote(text: str) -> str:
    return f"<blockquote>{escape(text)}</blockquote>"


def _new_flow_ref() -> str:
    return uuid.uuid4().hex[:8].upper()


def _build_preflight_block(lang: str, checks: dict) -> str:
    def mark(v: bool) -> str:
        return t(lang, "preflight_ok_mark") if v else t(lang, "preflight_fail_mark")

    lines = [
        t(lang, "preflight_title"),
        f"{mark(checks.get('token', False))} {t(lang, 'preflight_token_check')}",
        f"{mark(checks.get('channel', False))} {t(lang, 'preflight_channel_check')}",
        f"{mark(checks.get('admin', False))} {t(lang, 'preflight_admin_check')}",
        f"{mark(checks.get('reseller_group', False))} {t(lang, 'preflight_reseller_group_check')}",
    ]
    if checks.get("error"):
        lines.append(f"{t(lang, 'preflight_error_prefix')}: {checks['error']}")
    if checks.get("warning"):
        lines.append(f"{t(lang, 'warning_plain')}: {checks['warning']}")
    if not bool(checks.get("reseller_group")):
        lines.extend(
            [
                "",
                t(lang, "preflight_required_before_approval_title"),
                t(lang, "preflight_optional_after_approval_step_1"),
                t(lang, "preflight_optional_after_approval_step_2"),
                t(lang, "preflight_optional_after_approval_step_3"),
                t(lang, "preflight_optional_after_approval_step_4"),
            ]
        )
    return "\n".join(lines)


def _build_summary_text(data: dict, lang: str, checks: dict | None = None) -> str:
    summary = t(lang, "create_bot_summary").format(
        bot_title=data.get("bot_title", "-"),
        bot_username=(f"@{data.get('bot_username')}" if data.get("bot_username") else "-"),
        channel=data.get("channel", "-"),
        fullname=data.get("fullname", "-"),
        phone=data.get("phone", "-"),
        address=data.get("address", "-"),
    )
    if checks is not None:
        summary = f"{summary}\n\n{_build_preflight_block(lang, checks)}"
    return summary


def _manual_channel_hint(lang: str) -> str:
    if str(lang or "").lower().startswith("ar"):
        return "يمكنك اختيار القناة من الزر أو إرسال معرف القناة/يوزر القناة يدويًا مثل: @channelusername"
    return "You can use the channel picker button or send the channel manually like: @channelusername"


def _channel_target_invalid_text(lang: str) -> str:
    if str(lang or "").lower().startswith("ar"):
        return "الهدف المحدد ليس قناة تيليغرام صالحة. اختر قناة من الزر أو أرسل يوزر قناة صحيح."
    return "The selected target is not a valid Telegram channel. Use the picker or send a valid channel username."


def _missing_fields_text(lang: str, data: dict) -> str:
    labels = {
        "bot_token": "التوكن" if str(lang or "").lower().startswith("ar") else "Bot token",
        "bot_id": "معرف البوت" if str(lang or "").lower().startswith("ar") else "Bot ID",
        "channel": "القناة" if str(lang or "").lower().startswith("ar") else "Channel",
        "fullname": "الاسم الكامل" if str(lang or "").lower().startswith("ar") else "Full name",
        "phone": "رقم الهاتف" if str(lang or "").lower().startswith("ar") else "Phone number",
        "address": "العنوان" if str(lang or "").lower().startswith("ar") else "Address",
    }
    missing = [label for key, label in labels.items() if not data.get(key)]
    if str(lang or "").lower().startswith("ar"):
        return "البيانات غير مكتملة:\n- " + "\n- ".join(missing)
    return "The form is incomplete:\n- " + "\n- ".join(missing)


def _normalize_manual_phone(raw: str) -> str:
    normalized = re.sub(r"[^\d+]", "", raw or "")
    if not normalized:
        return ""
    if normalized.startswith("00"):
        normalized = f"+{normalized[2:]}"
    digits = re.sub(r"\D", "", normalized)
    if len(digits) < 8 or len(digits) > 15:
        return ""
    return normalized


def _address_invalid_text(lang: str) -> str:
    if str(lang or "").lower().startswith("ar"):
        return "يرجى إرسال عنوان واضح وليس قصيرًا جدًا."
    return "Please send a clear address. It is too short right now."


async def _is_bot_admin_with_topics(bot_token: str, chat_id: int) -> tuple[bool, str]:
    if not bot_token or not chat_id:
        return False, "missing token/chat"
    bot = None
    try:
        bot = Bot(token=bot_token)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id=int(chat_id), user_id=int(me.id))
        status = str(getattr(member, "status", "") or "").lower()
        if status not in {"administrator", "creator"}:
            return False, "bot is not admin in group"
        can_manage_topics = getattr(member, "can_manage_topics", None)
        if status != "creator" and can_manage_topics is False:
            return False, "missing Manage Topics permission"
        return True, ""
    except Exception as exc:
        return False, str(exc)
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass


async def _run_preflight_checks(data: dict, requester_id: int | None = None) -> tuple[bool, dict]:
    out = {
        "token": bool(data.get("token_verified")),
        "channel": bool(data.get("channel_verified")),
        "admin": bool(data.get("admin_verified")),
        "reseller_group": False,
        "error": "",
        "warning": "",
    }

    token = data.get("bot_token", "")
    bot_id = int(data.get("bot_id", 0) or 0)
    channel = data.get("channel", "")

    if not token or not bot_id or not channel:
        out["error"] = "missing required setup fields"
        return False, out

    if not out["token"]:
        out["error"] = "token is not verified"
        return False, out
    if not out["channel"]:
        out["error"] = "channel is invalid or inaccessible"
        return False, out
    if not out["admin"]:
        out["error"] = "bot is not admin in channel"
        return False, out

    rid = int(requester_id or 0)
    if rid > 0:
        try:
            pay_route = await get_recharge_routing(rid)
            if pay_route and pay_route.get("chat_id") is not None:
                pay_chat_id = int(pay_route.get("chat_id"))
                ok_group, group_err = await _is_bot_admin_with_topics(token, pay_chat_id)
                if ok_group:
                    ex_ok = True
                    ex_route = await get_exchange_routing(rid)
                    if ex_route and ex_route.get("chat_id") is not None:
                        ex_chat_id = int(ex_route.get("chat_id"))
                        ex_ok, _ex_err = await _is_bot_admin_with_topics(token, ex_chat_id)
                    out["reseller_group"] = bool(ex_ok)
                else:
                    out["warning"] = f"group permission check pending: {group_err}"
            else:
                out["warning"] = "payment routing group is not configured yet"
        except Exception as exc:
            out["warning"] = f"group setup check skipped: {exc}"
    if not out["reseller_group"]:
        if not out["error"]:
            out["error"] = out["warning"] or "reseller payment routing group is not ready"
        return False, out

    return True, out

async def _is_bot_id_already_registered(bot_id: int) -> bool:
    doc = await db.bots.find_one({"bot_id": int(bot_id)}, {"_id": 1})
    return doc is not None


async def _has_pending_bot_request_for_bot_id(bot_id: int) -> bool:
    doc = await db.bot_creation_requests.find_one(
        {
            "status": "pending",
            "$or": [
                {"payload.bot_id": int(bot_id)},
                {"bot_id": int(bot_id)},
            ],
        },
        {"_id": 1},
    )
    return doc is not None


async def _resolve_template_reseller_id() -> int | None:
    username = str(getattr(settings, "main_bot_username", "") or "").strip().lstrip("@").lower()
    if not username:
        return None

    direct_bot = await db.bots.find_one(
        {
            "active": True,
            "$or": [
                {"username_lc": username},
                {"bot_username_lc": username},
                {"reseller.bot_username_lc": username},
            ],
        }
    )
    if direct_bot and direct_bot.get("owner_id") is not None:
        try:
            return int(direct_bot.get("owner_id"))
        except Exception:
            pass

    return None


def _approval_packet_text(lang: str, payload: dict) -> str:
    return t(lang, "request_approved_packet").format(
        bot_title=payload.get("bot_title") or "-",
        bot_username=(f"@{payload.get('bot_username')}" if payload.get("bot_username") else "-"),
        bot_id=payload.get("bot_id") or "-",
        channel=payload.get("channel") or "-",
    )




def _extract_phone_country(phone_raw: str) -> str:
    normalized = re.sub(r"[^\d+]", "", phone_raw or "")
    if not normalized:
        return "Unknown"
    try:
        import phonenumbers  # type: ignore
        from phonenumbers import geocoder  # type: ignore

        parsed = phonenumbers.parse(normalized, None)
        region = phonenumbers.region_code_for_number(parsed) or ""
        country_name = geocoder.country_name_for_number(parsed, "en") or region or ""
        label = country_name.strip() if country_name else region
        if label:
            return label
        return "Unknown"
    except Exception:
        return "Unknown"


def _normalize_channel_input(raw: str) -> str:
    clean = re.sub(r"[\u202a-\u202e\u200f\u200e\s]+", "", raw)
    clean = clean.replace("https://", "").replace("http://", "")
    if clean.lower().startswith("t.me/"):
        clean = clean[5:]
    if clean.startswith("telegram.me/"):
        clean = clean[len("telegram.me/") :]
    if not clean:
        return ""
    if clean.startswith("@"):
        return clean
    if clean.startswith("-100"):
        return clean
    return f"@{clean.lstrip('@')}"


async def _is_channel_target(bot_token: str, channel_ref: str) -> bool:
    if not bot_token or not channel_ref:
        return False
    bot = None
    try:
        bot = Bot(token=bot_token)
        chat = await bot.get_chat(channel_ref)
        return getattr(chat, "type", None) == "channel"
    except Exception:
        return False
    finally:
        if bot is not None:
            await bot.session.close()


async def _is_bot_admin_in_channel(bot_token: str, channel_ref: str) -> bool:
    if not bot_token or not channel_ref:
        return False

    bot = None
    try:
        bot = Bot(token=bot_token)
        me = await bot.get_me()

        for attempt in range(4):
            try:
                chat = await bot.get_chat(channel_ref)

                # Fast path: direct membership check.
                member = await bot.get_chat_member(chat.id, me.id)
                if member.status in {"administrator", "creator"}:
                    return True

                # Not admin yet (or stale state). retry a bit.
                await asyncio.sleep(1.0)
                continue

            except TelegramBadRequest as exc:
                err = str(exc).lower()

                # Fallback for channels where member list endpoint can be limited.
                if "member list is inaccessible" in err:
                    try:
                        admins = await bot.get_chat_administrators(chat.id)
                        if any(getattr(a.user, "id", None) == me.id for a in admins):
                            return True
                    except Exception:
                        pass

                # transient/propagation issues: retry shortly
                if attempt < 3:
                    await asyncio.sleep(1.0)
                    continue
                return False

            except TelegramNetworkError:
                if attempt < 3:
                    await asyncio.sleep(1.0)
                    continue
                return False

            except Exception:
                if attempt < 3:
                    await asyncio.sleep(1.0)
                    continue
                return False

        return False

    finally:
        if bot is not None:
            await bot.session.close()


@router.message(lambda msg: bool(msg.text) and ((msg.text or "").strip() in {t("en", "btn_create_bot"), t("ar", "btn_create_bot")}))
async def ask_token(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    if await is_reseller_owned_bot(message.bot):
        await send_main_bot_message(message, lang=lang)
        return
    await state.update_data(**{INTRO_MSG_ID_KEY: None, FLOW_REF_KEY: _new_flow_ref(), "lang": lang})
    await _hide_reply_keyboard(message.bot, message.chat.id, state)

    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_intro_prompt_html(lang),
        reply_markup=_verify_intro_kb(lang),
        parse_mode="HTML",
    )
    await state.set_state(VerifyReseller.waiting_for_intro)


@router.callback_query(VerifyReseller.waiting_for_intro, lambda c: c.data == "verify:start_token")
async def start_token_step(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "en") if user else "en"
    await callback.answer()
    await _set_or_edit_prompt(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        state=state,
        text=_token_prompt_html(lang),
        reply_markup=_verify_token_kb(lang, include_back=False),
        parse_mode="HTML",
    )
    await state.set_state(VerifyReseller.waiting_for_token)



@router.message(VerifyReseller.waiting_for_intro)
async def ignore_intro_text(message: types.Message):
    # Intro step accepts only inline buttons (Continue/Cancel).
    await _safe_delete_user_message(message, context="verify_waiting_intro")


@router.callback_query(VerifyReseller.waiting_for_token, lambda c: c.data == "verify:retry_token")
async def retry_token_step(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "en") if user else "en"
    await callback.answer()
    await _set_or_edit_prompt(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        state=state,
        text=_token_prompt_html(lang),
        reply_markup=_verify_token_kb(lang, include_back=False),
        parse_mode="HTML",
        preferred_message_id=callback.message.message_id,
    )


@router.message(VerifyReseller.waiting_for_token)
async def save_token(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    token = _extract_token_input(message.text or "")
    bot = None

    await _safe_delete_user_message(message, context="verify_waiting_token")

    if not is_valid_token(token):
        logger.info("create_bot_token_invalid user_id=%s token_prefix=%s", message.from_user.id, token[:12])
        return await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_token_prompt_html(lang, t(lang, "invalid_token")),
            reply_markup=_verify_token_kb(lang, include_back=False, retry=True),
            parse_mode="HTML",
        )

    try:
        bot = Bot(token=token)
        me = await bot.get_me()

        if await _is_bot_id_already_registered(me.id):
            logger.info(
                "create_bot_token_registered user_id=%s bot_id=%s bot_username=%s",
                message.from_user.id,
                me.id,
                me.username or "",
            )
            await _set_or_edit_prompt(
                bot=message.bot,
                chat_id=message.chat.id,
                state=state,
                text=_token_prompt_html(lang, _bot_already_registered_text(lang)),
                reply_markup=_verify_token_kb(lang, include_back=False, retry=True),
                parse_mode="HTML",
            )
            return

        if await _has_pending_bot_request_for_bot_id(me.id):
            logger.info(
                "create_bot_token_pending_review user_id=%s bot_id=%s bot_username=%s",
                message.from_user.id,
                me.id,
                me.username or "",
            )
            await _set_or_edit_prompt(
                bot=message.bot,
                chat_id=message.chat.id,
                state=state,
                text=_token_prompt_html(lang, t(lang, "bot_pending_review_exists")),
                reply_markup=_verify_token_kb(lang, include_back=False, retry=True),
                parse_mode="HTML",
            )
            return

        logger.info(
            "create_bot_token_accepted user_id=%s bot_id=%s bot_username=%s",
            message.from_user.id,
            me.id,
            me.username or "",
        )
        await state.update_data(
            bot_token=token,
            bot_id=me.id,
            bot_username=me.username or "",
            bot_title=me.first_name or "",
            token_verified=True,
            channel_verified=False,
            admin_verified=False,
            preflight_ok=False,
            preflight_checks=None,
        )
        await _delete_intro_message(message.bot, message.chat.id, state)
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", f"{t(lang, 'send_channel')}\n\n{_manual_channel_hint(lang)}"),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await _show_channel_picker_prompt(message.bot, message.chat.id, state, lang)
        await state.set_state(VerifyReseller.waiting_for_channel)
    except TelegramNetworkError as exc:
        logger.warning(
            "token verification network error user_id=%s token_prefix=%s err=%s",
            message.from_user.id,
            token[:12],
            exc,
        )
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_token_prompt_html(lang, t(lang, "token_verify_network")),
            reply_markup=_verify_token_kb(lang, include_back=False, retry=True),
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        logger.warning(
            "token verification bad request user_id=%s token_prefix=%s err=%s",
            message.from_user.id,
            token[:12],
            exc,
        )
        err = str(exc).lower()
        key = "invalid_token" if ("unauthorized" in err or "token" in err) else "token_verify_failed"
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_token_prompt_html(lang, t(lang, key)),
            reply_markup=_verify_token_kb(lang, include_back=False, retry=True),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception(
            "token verification unexpected error user_id=%s token_prefix=%s",
            message.from_user.id,
            token[:12],
        )
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_token_prompt_html(lang, t(lang, "token_verify_failed")),
            reply_markup=_verify_token_kb(lang, include_back=False, retry=True),
            parse_mode="HTML",
        )
    finally:
        if bot is not None:
            await bot.session.close()


@router.message(VerifyReseller.waiting_for_channel, lambda msg: msg.chat_shared is not None)
async def receive_channel_shared(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    try:
        await message.delete()
    except Exception:
        pass

    shared = message.chat_shared
    channel_norm = ""
    if shared:
        shared_username = getattr(shared, "chat_username", None)
        shared_chat_id = getattr(shared, "chat_id", None)
        if shared_username:
            channel_norm = f"@{str(shared_username).lstrip('@')}"
        elif shared_chat_id:
            channel_norm = str(shared_chat_id)

    await _handle_channel_value(message, state, lang, channel_norm)


@router.message(VerifyReseller.waiting_for_channel)
async def receive_channel(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    raw = (message.text or "").strip()
    token = _extract_token_input(raw)
    if is_valid_token(token):
        await state.set_state(VerifyReseller.waiting_for_token)
        return await save_token(message, state)
    await _safe_delete_user_message(message, context="verify_waiting_channel_text")
    channel_norm = _normalize_channel_input(raw)
    if not channel_norm:
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", f"{t(lang, 'send_channel')}\n\n{_manual_channel_hint(lang)}"),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await _show_channel_picker_prompt(message.bot, message.chat.id, state, lang)
        return
    await _handle_channel_value(message, state, lang, channel_norm)


async def _handle_channel_value(message: types.Message, state: FSMContext, lang: str, channel_norm: str):
    if not channel_norm:
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", f"{t(lang, 'invalid_channel')}\n\n{t(lang, 'send_channel')}\n\n{_manual_channel_hint(lang)}"),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await _show_channel_picker_prompt(message.bot, message.chat.id, state, lang)
        return

    await state.update_data(channel=channel_norm)
    data = await state.get_data()
    bot_token = data.get("bot_token", "")
    bot_username = data.get("bot_username", "")
    add_url = _add_to_channel_url(bot_username)

    is_channel = await _is_channel_target(bot_token, channel_norm)
    if not is_channel:
        await state.update_data(channel_verified=False, admin_verified=False, preflight_ok=False, preflight_checks=None)
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", f"{_channel_target_invalid_text(lang)}\n\n{_manual_channel_hint(lang)}"),
            reply_markup=_verify_channel_admin_kb(lang, add_url, include_back=True),
            parse_mode="HTML",
        )
        await _show_channel_picker_prompt(message.bot, message.chat.id, state, lang)
        return

    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", t(lang, "checking_channel_admin")),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
    )

    is_admin = await _is_bot_admin_in_channel(bot_token, channel_norm)
    if not is_admin:
        await state.update_data(channel_verified=True, admin_verified=False, preflight_ok=False, preflight_checks=None)
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", t(lang, "channel_admin_required")),
            reply_markup=_verify_channel_admin_kb(lang, add_url, include_back=True),
            parse_mode="HTML",
        )
        await _show_channel_picker_prompt(message.bot, message.chat.id, state, lang)
        return

    await state.update_data(channel_verified=True, admin_verified=True)
    await _delete_state_message_by_key(message.bot, message.chat.id, state, CHANNEL_PROMPT_MSG_ID_KEY)
    await _hide_reply_keyboard(message.bot, message.chat.id, state)
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_step_prompt_html(lang, 3, "Full Name", "الاسم الكامل", t(lang, "send_fullname")),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
    )
    await state.set_state(VerifyReseller.waiting_for_fullname)


@router.callback_query(VerifyReseller.waiting_for_channel, lambda c: c.data == "verify:check_channel_admin")
async def recheck_channel_admin(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "en") if user else "en"
    data = await state.get_data()
    channel = data.get("channel", "")
    bot_token = data.get("bot_token", "")
    bot_username = data.get("bot_username", "")
    add_url = _add_to_channel_url(bot_username)

    await callback.answer()

    await _set_or_edit_prompt(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        state=state,
        text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", t(lang, "checking_channel_admin")),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
        preferred_message_id=callback.message.message_id,
    )

    is_channel = await _is_channel_target(bot_token, channel) if channel else False
    if channel and not is_channel:
        await state.update_data(channel_verified=False, admin_verified=False, preflight_ok=False, preflight_checks=None)
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", f"{_channel_target_invalid_text(lang)}\n\n{_manual_channel_hint(lang)}"),
            reply_markup=_verify_channel_admin_kb(lang, add_url, include_back=True),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await _show_channel_picker_prompt(callback.bot, callback.message.chat.id, state, lang)
        return

    if not channel:
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", f"{t(lang, 'send_channel')}\n\n{_manual_channel_hint(lang)}"),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await _show_channel_picker_prompt(callback.bot, callback.message.chat.id, state, lang)
        return

    is_admin = await _is_bot_admin_in_channel(bot_token, channel)
    if not is_admin:
        await state.update_data(channel_verified=True, admin_verified=False, preflight_ok=False, preflight_checks=None)
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", t(lang, "channel_admin_required")),
            reply_markup=_verify_channel_admin_kb(lang, add_url, include_back=True),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await _show_channel_picker_prompt(callback.bot, callback.message.chat.id, state, lang)
        return

    await state.update_data(channel_verified=True, admin_verified=True)
    await _delete_state_message_by_key(callback.bot, callback.message.chat.id, state, CHANNEL_PROMPT_MSG_ID_KEY)
    await _hide_reply_keyboard(callback.bot, callback.message.chat.id, state)
    await _set_or_edit_prompt(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        state=state,
        text=_step_prompt_html(lang, 3, "Full Name", "الاسم الكامل", t(lang, "send_fullname")),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
        preferred_message_id=callback.message.message_id,
    )
    await state.set_state(VerifyReseller.waiting_for_fullname)


@router.message(VerifyReseller.waiting_for_fullname)
async def receive_fullname(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    try:
        await message.delete()
    except Exception:
        pass
    fullname = (message.text or "").strip()
    if len([x for x in fullname.split() if x]) < 2:
        return await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 3, "Full Name", "الاسم الكامل", f"{t(lang, 'full_name_required')}\n\n{t(lang, 'send_fullname')}"),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
    await state.update_data(fullname=fullname)
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_step_prompt_html(lang, 4, "Phone Number", "رقم الهاتف", t(lang, "send_phone")),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
    )
    await _show_phone_request_keyboard(message.bot, message.chat.id, state, lang)
    await state.update_data(**{PHONE_PROMPT_MSG_ID_KEY: None})
    await state.set_state(VerifyReseller.waiting_for_phone)


@router.message(VerifyReseller.waiting_for_phone, lambda msg: msg.contact is not None)
async def receive_phone(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    try:
        await message.delete()
    except Exception:
        pass
    if not message.contact or message.contact.user_id != message.from_user.id:
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 4, "Phone Number", "رقم الهاتف", f"{t(lang, 'phone_contact_only')}\n\n{t(lang, 'send_phone')}"),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await _show_phone_request_keyboard(message.bot, message.chat.id, state, lang)
        return
    phone = (message.contact.phone_number or "").strip()
    phone_country = _extract_phone_country(phone)
    await state.update_data(phone=phone, phone_country=phone_country)
    await _hide_reply_keyboard(message.bot, message.chat.id, state)
    await state.update_data(**{ADDRESS_PROMPT_MSG_ID_KEY: None})
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_step_prompt_html(lang, 5, "Address", "العنوان", t(lang, "send_address")),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
    )
    await state.set_state(VerifyReseller.waiting_for_address)


@router.message(VerifyReseller.waiting_for_phone)
async def receive_phone_text_fallback(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    try:
        await message.delete()
    except Exception:
        pass
    phone = _normalize_manual_phone(message.text or "")
    if phone:
        phone_country = _extract_phone_country(phone)
        await state.update_data(phone=phone, phone_country=phone_country)
        await _hide_reply_keyboard(message.bot, message.chat.id, state)
        await state.update_data(**{ADDRESS_PROMPT_MSG_ID_KEY: None})
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 5, "Address", "العنوان", t(lang, "send_address")),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await state.set_state(VerifyReseller.waiting_for_address)
        return
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_step_prompt_html(lang, 4, "Phone Number", "رقم الهاتف", f"{t(lang, 'phone_contact_only')}\n\n{t(lang, 'send_phone')}"),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
    )
    await _show_phone_request_keyboard(message.bot, message.chat.id, state, lang)
    await state.update_data(**{PHONE_PROMPT_MSG_ID_KEY: None})


@router.message(VerifyReseller.waiting_for_address)
async def receive_address(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    try:
        await message.delete()
    except Exception:
        pass

    address = (message.text or "").strip()
    if len(address) < 6:
        return await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 5, "Address", "العنوان", f"{_address_invalid_text(lang)}\n\n{t(lang, 'send_address')}"),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )

    await _delete_state_message_by_key(message.bot, message.chat.id, state, ADDRESS_PROMPT_MSG_ID_KEY)
    await state.update_data(address=address)
    data = await state.get_data()

    preflight_ok, preflight_checks = await _run_preflight_checks(data, requester_id=int(message.from_user.id))
    await state.update_data(preflight_ok=preflight_ok, preflight_checks=preflight_checks)
    logger.info(
        "create_bot_preflight user_id=%s bot_id=%s ok=%s checks=%s",
        message.from_user.id,
        data.get("bot_id"),
        preflight_ok,
        preflight_checks,
    )

    summary_text = _build_summary_text(data, lang, preflight_checks)

    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_summary_prompt_html(lang, summary_text),
        reply_markup=_verify_confirm_kb(lang, setup_required=not bool(preflight_ok)),
        parse_mode="HTML",
    )
    await state.set_state(VerifyReseller.waiting_for_confirm)


@router.callback_query(
    VerifyReseller.waiting_for_confirm,
    lambda c: c.data in {"verify:confirm_create", "verify:cancel_create", "verify:open_group_create", "verify:back_summary"},
)
async def confirm_create_flow(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "en") if user else "en"
    if callback.data == "verify:cancel_create":
        await callback.answer()
        return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)

    if callback.data == "verify:back_summary":
        data = await state.get_data()
        preflight_checks = data.get("preflight_checks") or {}
        summary_text = _build_summary_text(data, lang, preflight_checks)
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_summary_prompt_html(lang, summary_text),
            reply_markup=_verify_confirm_kb(lang, setup_required=not bool(data.get("preflight_ok"))),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await callback.answer()
        return

    if callback.data == "verify:open_group_create":
        data = await state.get_data()
        group_url = _add_to_group_url(str(data.get("bot_username") or ""))
        setup_help_text = f"{t(lang, 'verify_setup_help_text')}\n\n{t(lang, 'preflight_required_before_approval_title')}"
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 6, "Setup Checklist", "قائمة الإعداد", setup_help_text),
            reply_markup=_verify_setup_help_kb(lang, group_url),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await callback.answer()
        return

    data = await state.get_data()
    required = ("bot_token", "bot_id", "channel", "fullname", "phone", "address")

    if await _is_bot_id_already_registered(int(data.get("bot_id", 0) or 0)):
        logger.info("create_bot_confirm_registered user_id=%s bot_id=%s", callback.from_user.id, data.get("bot_id"))
        await callback.answer(_bot_already_registered_text(lang), show_alert=True)
        return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)
    if any(not data.get(k) for k in required):
        missing_text = _missing_fields_text(lang, data)
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_summary_prompt_html(lang, f"{_build_summary_text(data, lang)}\n\n{missing_text}"),
            reply_markup=_verify_confirm_kb(lang, setup_required=True),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await callback.answer(missing_text, show_alert=True)
        return

    preflight_checks = data.get("preflight_checks") or {}
    preflight_ok = bool(data.get("preflight_ok"))
    if not preflight_checks:
        preflight_ok, preflight_checks = await _run_preflight_checks(data, requester_id=int(callback.from_user.id))
        await state.update_data(preflight_ok=preflight_ok, preflight_checks=preflight_checks)
        logger.info(
            "create_bot_preflight_recheck user_id=%s bot_id=%s ok=%s checks=%s",
            callback.from_user.id,
            data.get("bot_id"),
            preflight_ok,
            preflight_checks,
        )
    if not preflight_ok:
        summary_text = _build_summary_text(data, lang, preflight_checks)
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_summary_prompt_html(lang, f"{summary_text}\n\n{t(lang, 'preflight_fix_and_retry')}"),
            reply_markup=_verify_confirm_kb(lang, setup_required=True),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await callback.answer(t(lang, "preflight_failed_alert"), show_alert=True)
        return

    trial_price = float(getattr(settings, "reseller_bot_trial_price_usd", 1.0) or 1.0)
    current_balance = await get_reseller_wallet_balance(int(callback.from_user.id), wallet_type="main")
    if current_balance + 1e-9 < trial_price:
        logger.info(
            "create_bot_insufficient_balance user_id=%s bot_id=%s required=%.4f balance=%.4f",
            callback.from_user.id,
            data.get("bot_id"),
            trial_price,
            current_balance,
        )
        insufficient_text = (
            f"الرصيد غير كافٍ لتفعيل أول شهر تجريبي مدفوع.\n"
            f"المطلوب: {format_usd(trial_price)}\n"
            f"الرصيد الحالي: {format_usd(current_balance)}\n\n"
            "اشحن رصيدك في البوت المركزي ثم أعد المحاولة."
            if str(lang).lower().startswith("ar")
            else
            f"Your balance is not enough to activate the paid trial month.\n"
            f"Required: {format_usd(trial_price)}\n"
            f"Current balance: {format_usd(current_balance)}\n\n"
            "Top up your balance in the main bot and try again."
        )
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_summary_prompt_html(lang, f"{_build_summary_text(data, lang, preflight_checks)}\n\n{insufficient_text}"),
            reply_markup=_verify_confirm_kb(lang, setup_required=not bool(preflight_ok)),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await callback.answer(show_alert=True)
        return

    payload = {
        "bot_token": data["bot_token"],
        "bot_id": data["bot_id"],
        "bot_title": data.get("bot_title", ""),
        "bot_username": data.get("bot_username", ""),
        "channel": data["channel"],
        "fullname": data["fullname"],
        "phone": data["phone"],
        "phone_country": data.get("phone_country", "Unknown"),
        "address": data["address"],
    }

    created_new_bot = False
    core_activated = False
    try:
        exists = await db.bots.find_one({"bot_id": payload.get("bot_id")})
        if exists:
            logger.info(
                "create_bot_confirm_existing_record user_id=%s bot_id=%s active=%s",
                callback.from_user.id,
                payload.get("bot_id"),
                exists.get("active"),
            )
            await callback.answer(_bot_already_registered_text(lang), show_alert=True)
            return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)

        await add_bot(payload["bot_token"], callback.from_user.id, payload["bot_id"])
        created_new_bot = True
        logger.info(
            "create_bot_record_inserted user_id=%s bot_id=%s bot_username=%s",
            callback.from_user.id,
            payload.get("bot_id"),
            payload.get("bot_username") or "",
        )

        subscription = await get_bot_subscription(int(payload["bot_id"]))
        if str(subscription.get("status") or "").strip().lower() == "payment_required":
            await db.bots.delete_one({"bot_id": payload["bot_id"], "owner_id": int(callback.from_user.id)})
            created_new_bot = False
            retry_balance = await get_reseller_wallet_balance(int(callback.from_user.id), wallet_type="main")
            logger.info(
                "create_bot_subscription_payment_required user_id=%s bot_id=%s required=%.4f balance=%.4f",
                callback.from_user.id,
                payload.get("bot_id"),
                trial_price,
                retry_balance,
            )
            insufficient_text = (
                f"تعذر تفعيل البوت لأن الرصيد لم يعد كافيًا.\n"
                f"المطلوب: {format_usd(trial_price)}\n"
                f"الرصيد الحالي: {format_usd(retry_balance)}\n\n"
                "اشحن رصيدك في البوت المركزي ثم أعد المحاولة."
                if str(lang).lower().startswith("ar")
                else
                f"Bot activation failed because the balance is no longer sufficient.\n"
                f"Required: {format_usd(trial_price)}\n"
                f"Current balance: {format_usd(retry_balance)}\n\n"
            "Top up your balance in the main bot and try again."
            )
            await _set_or_edit_prompt(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                state=state,
                text=_summary_prompt_html(lang, f"{_build_summary_text(data, lang, preflight_checks)}\n\n{insufficient_text}"),
                reply_markup=_verify_confirm_kb(lang, setup_required=not bool(preflight_ok)),
                parse_mode="HTML",
                preferred_message_id=callback.message.message_id,
            )
            await callback.answer(show_alert=True)
            return

        bot_username = str(payload.get("bot_username") or "").strip().lstrip("@").lower()
        if bot_username:
            await db.bots.update_one(
                {"bot_id": payload.get("bot_id")},
                {
                    "$set": {
                        "username_lc": bot_username,
                        "bot_username_lc": bot_username,
                        "reseller.bot_username_lc": bot_username,
                    }
                },
            )
        await update_bot_channel(payload["bot_id"], payload["channel"])
        await update_reseller_info(payload["bot_id"], payload["fullname"], payload["phone"], payload["address"])
        await verify_bot(payload["bot_id"])
        await mark_bot_provisioning_status(int(payload["bot_id"]), "active", active=True)
        core_activated = True

        template_reseller_id = await _resolve_template_reseller_id()
        if template_reseller_id and int(callback.from_user.id) != int(template_reseller_id):
            try:
                clone_res = await clone_catalog_from_reseller_template(
                    source_reseller_id=int(template_reseller_id),
                    target_reseller_id=int(callback.from_user.id),
                    catalog_type="custom",
                )
                logger.info(
                    "custom template clone result source=%s target=%s success=%s reason=%s copied=%s",
                    template_reseller_id,
                    callback.from_user.id,
                    clone_res.get("success"),
                    clone_res.get("reason"),
                    clone_res.get("copied"),
                )
            except Exception:
                logger.exception(
                    "custom template clone failed after bot activation user_id=%s bot_id=%s",
                    callback.from_user.id,
                    payload.get("bot_id"),
                )

        await callback.answer()
        try:
            await callback.message.delete()
        except Exception:
            pass
        success_text = (
            f"{_approval_packet_text(lang, payload)}\n\n"
            f"{_subscription_notice_text(lang, subscription)}\n\n"
            f"{t(lang, 'reseller_setup_post_approval')}\n\n"
            f"{t(lang, 'request_approved_next_step')}"
        )
        await callback.message.answer(success_text, reply_markup=_approval_followup_kb(lang))
        logger.info(
            "create_bot_success user_id=%s bot_id=%s bot_username=%s subscription_status=%s",
            callback.from_user.id,
            payload.get("bot_id"),
            payload.get("bot_username") or "",
            subscription.get("status"),
        )
        await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)
    except BotAlreadyRegisteredError:
        logger.info("create_bot_duplicate_insert user_id=%s bot_id=%s", callback.from_user.id, payload.get("bot_id"))
        await callback.answer(_bot_already_registered_text(lang), show_alert=True)
        return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)
    except Exception as exc:
        logger.exception("auto create bot failed user_id=%s bot_id=%s: %s", callback.from_user.id, payload.get("bot_id"), exc)
        if created_new_bot and not core_activated:
            try:
                await mark_bot_provisioning_status(int(payload["bot_id"]), "failed", active=False, error=str(exc))
            except Exception:
                logger.exception("failed to mark create_bot provisioning failure bot_id=%s", payload.get("bot_id"))
        await callback.answer(t(lang, "owner_approve_failed").format(error=exc), show_alert=True)

@router.callback_query(lambda c: c.data in {"verify_nav:back", "verify_nav:cancel"})
async def verify_navigation(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "en") if user else "en"
    action = callback.data
    current = await state.get_state()

    if action == "verify_nav:cancel" or not current:
        await callback.answer()
        return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)

    if current == VerifyReseller.waiting_for_token.state:
        await state.set_state(VerifyReseller.waiting_for_intro)
        await callback.answer()
        return await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_intro_prompt_html(lang),
            reply_markup=_verify_intro_kb(lang),
            parse_mode="HTML",
        )

    if current == VerifyReseller.waiting_for_channel.state:
        await state.set_state(VerifyReseller.waiting_for_token)
        await callback.answer()
        return await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_token_prompt_html(lang),
            reply_markup=_verify_token_kb(lang, include_back=False),
            parse_mode="HTML",
        )

    if current == VerifyReseller.waiting_for_fullname.state:
        await state.set_state(VerifyReseller.waiting_for_channel)
        await callback.answer()
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 2, "Subscription Channel", "قناة الاشتراك", f"{t(lang, 'send_channel')}\n\n{_manual_channel_hint(lang)}"),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await _show_channel_picker_prompt(callback.bot, callback.message.chat.id, state, lang)
        return

    if current == VerifyReseller.waiting_for_phone.state:
        await state.set_state(VerifyReseller.waiting_for_fullname)
        await callback.answer()
        return await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 3, "Full Name", "الاسم الكامل", t(lang, "send_fullname")),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )

    if current == VerifyReseller.waiting_for_address.state:
        await state.set_state(VerifyReseller.waiting_for_phone)
        await callback.answer()
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 4, "Phone Number", "رقم الهاتف", t(lang, "send_phone")),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await _show_phone_request_keyboard(callback.bot, callback.message.chat.id, state, lang)
        return

    if current == VerifyReseller.waiting_for_confirm.state:
        await state.set_state(VerifyReseller.waiting_for_address)
        await callback.answer()
        return await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 5, "Address", "العنوان", t(lang, "send_address")),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )

    await callback.answer()
    return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)




























