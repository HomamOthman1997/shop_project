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
    update_bot_token,
    update_bot_channel,
    update_reseller_info,
    verify_bot,
)
from database.bot_logs_repo import get_bot_logs_target
from services.subscriptions.bot_subscription_service import sync_bot_subscription
from database.custom_services_repo import clone_catalog_from_reseller_template
from database.financial_ledger import get_user_wallet_balance
from database.mongo import db
from database.reseller_settings_repo import (
    get_exchange_routing,
    get_recharge_routing,
    set_exchange_routing,
    set_recharge_routing,
)
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
BOT_TOKEN_RE = re.compile(r"\d{8,12}:[A-Za-z0-9_-]{20,}")
CHANNEL_PICKER_REQUEST_ID = 1
SYRIA_COUNTRY_CODE = "SY"
SYRIA_APPROX_POLYGON = (
    (35.62, 32.31),
    (36.84, 32.31),
    (38.80, 33.37),
    (42.38, 37.32),
    (41.25, 37.22),
    (39.10, 36.88),
    (37.15, 36.70),
    (35.78, 35.92),
    (35.62, 33.25),
)


def is_valid_token(text: str):
    return bool(BOT_TOKEN_RE.fullmatch(_normalize_token_input(text)))


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
    m = BOT_TOKEN_RE.search(cleaned)
    if m:
        return m.group(0)
    return cleaned


def _clean_bot_username(username: str | None) -> str:
    return str(username or "").strip().lstrip("@")


def _safe_deep_link_payload(payload: str | None) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "", str(payload or ""))
    return (clean[:64] or "true")


def _token_bot_id_hint(bot_token: str | None) -> str:
    token = str(bot_token or "").strip()
    if ":" not in token:
        return "-"
    return token.split(":", 1)[0].strip() or "-"


async def _refresh_flow_bot_identity(
    bot_token: str,
    state: FSMContext | None = None,
    *,
    fallback_username: str = "",
) -> str:
    username = _clean_bot_username(fallback_username)
    if not bot_token:
        return username

    bot = None
    try:
        bot = Bot(token=bot_token)
        me = await bot.get_me()
        resolved_username = _clean_bot_username(getattr(me, "username", ""))
        updates = {}
        try:
            updates["bot_id"] = int(getattr(me, "id", 0) or 0)
        except Exception:
            pass
        if resolved_username:
            updates["bot_username"] = resolved_username
        title = str(getattr(me, "first_name", "") or "").strip()
        if title:
            updates["bot_title"] = title
        if state is not None and updates:
            await state.update_data(**updates)
        return resolved_username or username
    except Exception as exc:
        logger.warning(
            "create_bot_identity_refresh_failed token_bot_id=%s fallback_username=%s err=%s",
            _token_bot_id_hint(bot_token),
            username or "-",
            exc,
        )
        return username
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass


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
    title = "إنشاء بوتك الخاص" if _is_ar(lang) else "Create Your Bot"
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


def _bot_token_updated_text(lang: str, bot_username: str | None = None) -> str:
    username = _clean_bot_username(bot_username)
    suffix = f" @{username}" if username else ""
    if _is_ar(lang):
        return (
            f"✅ تم تحديث توكن البوت{suffix} بنجاح.\n\n"
            "استخدمت توكن جديد لنفس البوت الموجود عندنا، لذلك حدّثت التوكن بدل إنشاء بوت جديد.\n"
            "هذا مناسب إذا عملت Revoke للتوكن من BotFather."
        )
    return (
        f"✅ Bot token updated successfully{suffix}.\n\n"
        "You sent a new token for the same bot already registered here, so I updated the stored token instead of creating a new bot.\n"
        "Use this when you revoke/regenerate the token in BotFather."
    )


def _add_to_channel_url(bot_username: str) -> str:
    username = _clean_bot_username(bot_username)
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
    return f"https://t.me/{username}?startchannel=true&admin={perms}"


def _add_to_group_url(bot_username: str, start_payload: str | None = None) -> str:
    username = _clean_bot_username(bot_username)
    payload = _safe_deep_link_payload(start_payload)
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
    return f"https://t.me/{username}?startgroup={payload}&admin={perms}"


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


def _subscription_activation_collected(subscription: dict) -> bool:
    status = str((subscription or {}).get("status") or "").strip().lower()
    return status in {"trial_active", "active"}


def _phone_request_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "phone_share_button"), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
    )


def _location_request_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "location_share_button"), request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
    )


def _channel_request_kb(lang: str) -> ReplyKeyboardMarkup:
    # Keep request lightweight; admin rights are verified in the next step.
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=t(lang, "channel_picker_button"),
                    request_chat=KeyboardButtonRequestChat(
                        request_id=CHANNEL_PICKER_REQUEST_ID,
                        chat_is_channel=True,
                        chat_has_username=True,
                        request_title=True,
                        request_username=True,
                    ),
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
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
    await _refresh_reply_keyboard(
        bot=bot,
        chat_id=chat_id,
        state=state,
        reply_markup=_channel_request_kb(lang),
        text=t(lang, "channel_picker_ready"),
    )


async def _show_phone_request_keyboard(bot: Bot, chat_id: int, state: FSMContext, lang: str):
    await _refresh_reply_keyboard(
        bot=bot,
        chat_id=chat_id,
        state=state,
        reply_markup=_phone_request_kb(lang),
        text=t(lang, "phone_keyboard_ready"),
    )


async def _show_location_request_keyboard(bot: Bot, chat_id: int, state: FSMContext, lang: str):
    await _refresh_reply_keyboard(
        bot=bot,
        chat_id=chat_id,
        state=state,
        reply_markup=_location_request_kb(lang),
        text=t(lang, "location_keyboard_ready"),
    )


async def _refresh_reply_keyboard(
    bot: Bot,
    chat_id: int,
    state: FSMContext | None = None,
    reply_markup: ReplyKeyboardMarkup | None = None,
    text: str | None = None,
):
    if reply_markup is None:
        return
    if state is not None:
        await _clear_reply_keyboard_anchor(bot, chat_id, state)
    try:
        sent = await _safe_bot_send_message(
            bot=bot,
            chat_id=chat_id,
            text=(str(text or "").strip() or "\u2800"),
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
    intro_text = t(
        lang,
        "reseller_create_intro",
        trial_days=_settings_int("reseller_bot_trial_days", 30),
        grace_days=_settings_int("reseller_bot_grace_days", 3),
        trial_price=format_usd(_settings_float("reseller_bot_trial_price_usd", 1.0)),
        monthly_price=format_usd(_settings_float("reseller_bot_monthly_price_usd", 10.0)),
    )
    lines = intro_text.splitlines()
    if len(lines) <= 1:
        return intro_text
    return "\n".join(lines[1:]).strip()


def _settings_float(name: str, default: float) -> float:
    try:
        value = float(getattr(settings, name, default) or default)
    except Exception:
        value = default
    return value if value > 0 else default


def _settings_int(name: str, default: int) -> int:
    try:
        value = int(getattr(settings, name, default) or default)
    except Exception:
        value = default
    return value if value > 0 else default


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
        "address": "الموقع" if str(lang or "").lower().startswith("ar") else "Location",
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
        return "يرجى مشاركة موقعك من تيليغرام بدل كتابة العنوان."
    return "Please share your Telegram location instead of typing an address."


async def _is_bot_admin_with_topics(bot_token: str, chat_id: int) -> tuple[bool, str]:
    if not bot_token or not chat_id:
        return False, "missing token/chat"
    bot = None
    try:
        bot = Bot(token=bot_token)
        return await _bot_can_manage_topics_in_chat(bot, int(chat_id))
    except Exception as exc:
        return False, str(exc)
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass


async def _bot_can_manage_topics_in_chat(bot: Bot, chat_id: int) -> tuple[bool, str]:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id=int(chat_id), user_id=int(me.id))
    except Exception as exc:
        return False, str(exc)

    status = _member_status_value(getattr(member, "status", None))
    if status not in {"administrator", "creator"}:
        return False, "bot is not admin in group"
    can_manage_topics = getattr(member, "can_manage_topics", None)
    if status != "creator" and can_manage_topics is False:
        return False, "missing Manage Topics permission"
    return True, ""


async def _create_forum_topic_safe(bot: Bot, chat_id: int, name: str) -> tuple[int | None, str | None]:
    try:
        topic = await bot.create_forum_topic(chat_id=int(chat_id), name=name)
        thread_id = int(getattr(topic, "message_thread_id", 0) or 0)
        if thread_id <= 0:
            return None, "invalid topic id"
        return thread_id, None
    except Exception as exc:
        return None, str(exc)


def _chat_is_group(chat) -> bool:
    chat_type = _chat_type_value(getattr(chat, "type", None))
    return chat_type in {"group", "supergroup"}


def _append_unique_chat_id(values: list[int], chat_id) -> None:
    try:
        value = int(chat_id)
    except Exception:
        return
    if value and value not in values:
        values.append(value)


async def _discover_setup_group_candidates(bot_token: str, flow_ref: str | None = None) -> list[int]:
    exact: list[int] = []
    generic: list[int] = []
    payload = f"setup_{str(flow_ref or '').strip()}".lower() if flow_ref else ""
    bot = None
    try:
        bot = Bot(token=bot_token)
        try:
            await bot.delete_webhook(drop_pending_updates=False)
        except Exception:
            pass
        updates = await bot.get_updates(
            limit=50,
            timeout=0,
            allowed_updates=["message", "my_chat_member"],
            request_timeout=20,
        )
    except Exception as exc:
        logger.info(
            "create_bot_setup_group_discovery_failed token_bot_id=%s err=%s",
            _token_bot_id_hint(bot_token),
            exc,
        )
        return []
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass

    for update in reversed(updates or []):
        message = getattr(update, "message", None)
        if message is not None:
            chat = getattr(message, "chat", None)
            text = str(getattr(message, "text", "") or "").strip().lower()
            if _chat_is_group(chat):
                if payload and payload in text:
                    _append_unique_chat_id(exact, getattr(chat, "id", None))
                elif text.startswith("/start"):
                    _append_unique_chat_id(generic, getattr(chat, "id", None))

        member_update = getattr(update, "my_chat_member", None)
        if member_update is not None:
            chat = getattr(member_update, "chat", None)
            new_member = getattr(member_update, "new_chat_member", None)
            status = _member_status_value(getattr(new_member, "status", None))
            if _chat_is_group(chat) and status in {"administrator", "creator", "member"}:
                _append_unique_chat_id(generic, getattr(chat, "id", None))

    return exact + [chat_id for chat_id in generic if chat_id not in exact]


def _routing_thread_id(route: dict | None, chat_id: int) -> int | None:
    if not route:
        return None
    try:
        if int(route.get("chat_id")) != int(chat_id):
            return None
    except Exception:
        return None
    raw = route.get("message_thread_id")
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except Exception:
        return None
    return value if value > 0 else None


async def _auto_setup_reseller_topics(
    *,
    bot_token: str,
    reseller_id: int,
    data: dict,
    pay_route: dict | None,
    ex_route: dict | None,
) -> tuple[bool, str]:
    candidates: list[int] = []
    for route in (pay_route, ex_route):
        if route and route.get("chat_id") is not None:
            _append_unique_chat_id(candidates, route.get("chat_id"))

    for chat_id in await _discover_setup_group_candidates(bot_token, data.get(FLOW_REF_KEY)):
        _append_unique_chat_id(candidates, chat_id)

    if not candidates:
        return False, "payment group is not configured yet"

    bot = None
    last_error = ""
    try:
        bot = Bot(token=bot_token)
        for chat_id in candidates:
            ok_admin, admin_err = await _bot_can_manage_topics_in_chat(bot, chat_id)
            if not ok_admin:
                last_error = f"group permission check pending: {admin_err}"
                continue

            payment_thread_id = _routing_thread_id(pay_route, chat_id)
            exchange_thread_id = _routing_thread_id(ex_route, chat_id)
            if payment_thread_id is None:
                payment_thread_id, pay_err = await _create_forum_topic_safe(bot, chat_id, "Payment Requests")
                if payment_thread_id is None:
                    last_error = f"Auto Setup Topics failed for payment topic: {pay_err}"
                    continue
            if exchange_thread_id is None:
                exchange_thread_id, ex_err = await _create_forum_topic_safe(bot, chat_id, "Exchange Alerts")
                if exchange_thread_id is None:
                    last_error = f"Auto Setup Topics failed for exchange topic: {ex_err}"
                    continue

            await set_recharge_routing(int(reseller_id), int(chat_id), int(payment_thread_id))
            await set_exchange_routing(int(reseller_id), int(chat_id), int(exchange_thread_id))
            logger.info(
                "create_bot_auto_topics_completed reseller_id=%s bot_id=%s chat_id=%s payment_thread_id=%s exchange_thread_id=%s",
                reseller_id,
                _token_bot_id_hint(bot_token),
                chat_id,
                payment_thread_id,
                exchange_thread_id,
            )
            return True, ""
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass

    return False, last_error or "Auto Setup Topics could not find a ready group"


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
            ex_route = await get_exchange_routing(rid)
            pay_ready = bool(pay_route and pay_route.get("chat_id") is not None and pay_route.get("message_thread_id") is not None)
            ex_ready = bool(ex_route and ex_route.get("chat_id") is not None and ex_route.get("message_thread_id") is not None)
            auto_attempted = False
            if pay_route and pay_route.get("chat_id") is not None:
                pay_chat_id = int(pay_route.get("chat_id"))
                ok_group, group_err = await _is_bot_admin_with_topics(token, pay_chat_id)
                if ok_group and pay_ready and ex_ready:
                    ex_ok = True
                    if ex_route and ex_route.get("chat_id") is not None:
                        ex_chat_id = int(ex_route.get("chat_id"))
                        ex_ok, _ex_err = await _is_bot_admin_with_topics(token, ex_chat_id)
                    out["reseller_group"] = bool(ex_ok)
                else:
                    auto_attempted = True
                    auto_ok, auto_err = await _auto_setup_reseller_topics(
                        bot_token=token,
                        reseller_id=rid,
                        data=data,
                        pay_route=pay_route,
                        ex_route=ex_route,
                    )
                    out["reseller_group"] = bool(auto_ok)
                    out["auto_topics"] = bool(auto_ok)
                    if not auto_ok:
                        out["warning"] = auto_err or f"group permission check pending: {group_err}"
            if not out["reseller_group"] and not auto_attempted:
                auto_ok, auto_err = await _auto_setup_reseller_topics(
                    bot_token=token,
                    reseller_id=rid,
                    data=data,
                    pay_route=pay_route,
                    ex_route=ex_route,
                )
                out["reseller_group"] = bool(auto_ok)
                out["auto_topics"] = bool(auto_ok)
                if not auto_ok and not out["warning"]:
                    out["warning"] = auto_err or "payment routing group is not configured yet"
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


async def _get_registered_bot_for_token_update(bot_id: int) -> dict | None:
    return await db.bots.find_one(
        {"bot_id": int(bot_id)},
        {"_id": 1, "bot_id": 1, "owner_id": 1, "token": 1, "active": 1, "provisioning": 1, "settings": 1},
    )


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


def _owner_review_kb(request_id) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("en", "owner_approve_create"), callback_data=f"verify_owner:approve:{request_id}")
    kb.button(text=t("en", "owner_reject_create"), callback_data=f"verify_owner:reject:{request_id}")
    kb.adjust(1)
    return kb.as_markup()


def _bot_creation_review_text(req: dict, payload: dict, reasons: list[str]) -> str:
    user = req.get("requester") or {}
    username = str(user.get("username") or "").strip()
    uname = f"@{username}" if username else "-"
    loc = payload.get("location") or {}
    reason_text = "\n".join(f"- {reason}" for reason in reasons) or "-"
    bot_username = f"@{payload.get('bot_username')}" if payload.get("bot_username") else "-"
    return (
        "Manual Bot Creation Review\n\n"
        f"Request ID: {req.get('_id')}\n"
        f"Reason:\n{reason_text}\n\n"
        f"Requester ID: {req.get('requester_id')}\n"
        f"Username: {uname}\n"
        f"Name: {user.get('full_name') or '-'}\n\n"
        f"Bot Name: {payload.get('bot_title') or '-'}\n"
        f"Bot Username: {bot_username}\n"
        f"Bot ID: {payload.get('bot_id') or '-'}\n"
        f"Channel: {payload.get('channel') or '-'}\n"
        f"Full Name: {payload.get('fullname') or '-'}\n"
        f"Phone: {payload.get('phone') or '-'}\n"
        f"Phone Country: {payload.get('phone_country') or '-'} ({payload.get('phone_region') or '-'})\n"
        f"Location: {loc.get('latitude') or '-'}, {loc.get('longitude') or '-'}\n"
        f"Location Country: {loc.get('country_code') or '-'}\n"
        f"Live Location: {'yes' if loc.get('live') else 'no'}"
    )


async def _owner_bot_creation_target() -> dict | None:
    target = await db.system_settings.find_one({"_id": "owner_bot_creation_requests"}) or {}
    if not isinstance(target.get("chat_id"), int):
        target = await db.system_settings.find_one({"_id": "owner_notifications"}) or {}
    if isinstance(target.get("chat_id"), int):
        thread_id = target.get("message_thread_id")
        return {
            "chat_id": int(target["chat_id"]),
            "message_thread_id": int(thread_id) if isinstance(thread_id, int) else None,
        }
    logs_target = await get_bot_logs_target()
    if logs_target and isinstance(logs_target.get("chat_id"), int):
        return {
            "chat_id": int(logs_target["chat_id"]),
            "message_thread_id": logs_target.get("message_thread_id"),
        }
    owner_id = int(getattr(settings, "owner_id", 0) or 0)
    if owner_id > 0:
        return {"chat_id": owner_id, "message_thread_id": None}
    return None


async def _notify_owner_bot_creation_review(source_bot: Bot, req: dict, payload: dict, reasons: list[str]) -> tuple[bool, str, dict]:
    target = await _owner_bot_creation_target()
    if not target:
        return False, "owner_target_not_bound", {}

    bot = source_bot
    close_bot = False
    admin_token = str(getattr(settings, "bot_admin_token", "") or "").strip()
    if admin_token:
        try:
            bot = Bot(token=admin_token)
            close_bot = True
        except Exception:
            bot = source_bot
            close_bot = False

    try:
        kwargs = {
            "chat_id": int(target["chat_id"]),
            "text": _bot_creation_review_text(req, payload, reasons),
            "reply_markup": _owner_review_kb(req["_id"]),
        }
        if target.get("message_thread_id") is not None:
            kwargs["message_thread_id"] = int(target["message_thread_id"])
        sent = await bot.send_message(**kwargs)
        delivery = {
            "chat_id": int(target["chat_id"]),
            "message_id": int(getattr(sent, "message_id", 0) or 0),
            "message_thread_id": target.get("message_thread_id"),
            "bot": "admin" if close_bot else "source",
        }
        return True, "owner_review", delivery
    except Exception as exc:
        return False, str(exc), dict(target)
    finally:
        if close_bot:
            try:
                await bot.session.close()
            except Exception:
                pass


async def _submit_manual_bot_creation_review(
    *,
    callback: types.CallbackQuery,
    state: FSMContext,
    lang: str,
    payload: dict,
    reasons: list[str],
    preflight_checks: dict,
) -> None:
    user = await get_user(callback.from_user.id)
    requester = {
        "username": getattr(callback.from_user, "username", "") or (user or {}).get("username", ""),
        "full_name": " ".join(
            part for part in [getattr(callback.from_user, "first_name", ""), getattr(callback.from_user, "last_name", "")]
            if part
        ).strip(),
    }
    now = datetime.now(UTC)
    req = {
        "status": "pending",
        "requester_id": int(callback.from_user.id),
        "requester_lang": lang,
        "source_bot_token": str(getattr(settings, "bot_main_token", "") or ""),
        "source_bot_id": int((await callback.bot.get_me()).id),
        "requester": requester,
        "payload": payload,
        "review_reasons": reasons,
        "preflight_checks": preflight_checks,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.bot_creation_requests.insert_one(req)
    req["_id"] = result.inserted_id
    delivered, route, delivery = await _notify_owner_bot_creation_review(callback.bot, req, payload, reasons)
    await db.bot_creation_requests.update_one(
        {"_id": result.inserted_id},
        {
            "$set": {
                "owner_notified": bool(delivered),
                "owner_notify_route": route,
                "delivery": delivery,
                "updated_at": datetime.now(UTC),
            }
        },
    )
    if not delivered:
        logger.warning("create_bot_manual_review_notify_failed request_id=%s route=%s", result.inserted_id, route)

    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    text = (
        f"{t(lang, 'manual_review_required_text')}\n\n{_manual_review_reasons_text(lang, reasons)}"
    )
    await callback.message.answer(text)
    await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)


def _normalize_phone_for_region(phone_raw: str) -> str:
    normalized = re.sub(r"[^\d+]", "", phone_raw or "")
    if not normalized:
        return ""
    if normalized.startswith("00"):
        normalized = f"+{normalized[2:]}"
    digits = re.sub(r"\D", "", normalized)
    if not normalized.startswith("+") and digits:
        normalized = f"+{digits}"
    return normalized


def _extract_phone_region(phone_raw: str) -> str:
    normalized = _normalize_phone_for_region(phone_raw)
    if not normalized:
        return ""
    digits = re.sub(r"\D", "", normalized)
    if digits.startswith("963"):
        return SYRIA_COUNTRY_CODE
    try:
        import phonenumbers  # type: ignore

        parsed = phonenumbers.parse(normalized, None)
        return (phonenumbers.region_code_for_number(parsed) or "").upper()
    except Exception:
        return ""


def _phone_is_syrian(phone_raw: str) -> bool:
    return _extract_phone_region(phone_raw) == SYRIA_COUNTRY_CODE


def _extract_phone_country(phone_raw: str) -> str:
    normalized = _normalize_phone_for_region(phone_raw)
    if not normalized:
        return "Unknown"
    try:
        import phonenumbers  # type: ignore
        from phonenumbers import geocoder  # type: ignore

        parsed = phonenumbers.parse(normalized, None)
        region = (phonenumbers.region_code_for_number(parsed) or "").upper()
        country_name = geocoder.country_name_for_number(parsed, "en") or region or ""
        label = country_name.strip() if country_name else region
        if label:
            return label
        return "Unknown"
    except Exception:
        if _extract_phone_region(phone_raw) == SYRIA_COUNTRY_CODE:
            return "Syria"
        return "Unknown"


def _point_in_polygon(lon: float, lat: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        crosses = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        )
        if crosses:
            inside = not inside
        j = i
    return inside


def _is_location_in_syria(latitude: float, longitude: float) -> bool:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except Exception:
        return False
    if lat < 32.0 or lat > 37.6 or lon < 35.4 or lon > 42.5:
        return False
    return _point_in_polygon(lon, lat, SYRIA_APPROX_POLYGON)


def _location_address_text(latitude: float, longitude: float, *, live: bool) -> str:
    kind = "Telegram live location" if live else "Telegram location"
    return f"{kind}: {float(latitude):.6f}, {float(longitude):.6f}"


def _manual_review_reasons(data: dict) -> list[str]:
    reasons: list[str] = []
    if data.get("phone_region") != SYRIA_COUNTRY_CODE:
        reasons.append("phone_not_syria")
    if data.get("location_country_code") != SYRIA_COUNTRY_CODE:
        reasons.append("location_not_syria")
    return reasons


def _manual_review_reasons_text(lang: str, reasons: list[str]) -> str:
    is_ar = _is_ar(lang)
    labels = {
        "phone_not_syria": "رقم الهاتف ليس سورياً" if is_ar else "Phone number is not Syrian",
        "location_not_syria": "الموقع خارج سوريا" if is_ar else "Location is outside Syria",
    }
    return "\n".join(f"- {labels.get(reason, reason)}" for reason in reasons)


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


def _telegram_chat_ref(channel_ref: str):
    clean = str(channel_ref or "").strip()
    if re.fullmatch(r"-?\d+", clean):
        return int(clean)
    return clean


def _chat_type_value(chat_type) -> str:
    return str(getattr(chat_type, "value", chat_type) or "").lower()


def _member_status_value(status) -> str:
    return str(getattr(status, "value", status) or "").lower()


async def _chat_admins_include_bot(bot: Bot, chat_id, bot_id: int) -> bool:
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except Exception as exc:
        logger.info(
            "create_bot_channel_admins_lookup_failed bot_id=%s chat_id=%s err=%s",
            bot_id,
            chat_id,
            exc,
        )
        return False
    return any(getattr(getattr(admin, "user", None), "id", None) == bot_id for admin in admins)


async def _is_channel_target(bot_token: str, channel_ref: str) -> bool:
    if not bot_token or not channel_ref:
        return False
    bot = None
    try:
        bot = Bot(token=bot_token)
        chat = await bot.get_chat(_telegram_chat_ref(channel_ref))
        return _chat_type_value(getattr(chat, "type", None)) == "channel"
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
        chat_ref = _telegram_chat_ref(channel_ref)

        for attempt in range(4):
            chat_id = chat_ref
            try:
                chat = await bot.get_chat(chat_ref)
                chat_id = chat.id

                # Fast path: direct membership check.
                member = await bot.get_chat_member(chat_id, me.id)
                status = _member_status_value(getattr(member, "status", None))
                if status in {"administrator", "creator"}:
                    return True
                if await _chat_admins_include_bot(bot, chat_id, me.id):
                    logger.info(
                        "create_bot_channel_admins_fallback_success bot_id=%s channel_ref=%s chat_id=%s attempt=%s member_status=%s",
                        me.id,
                        channel_ref,
                        chat_id,
                        attempt + 1,
                        status or "-",
                    )
                    return True
                logger.info(
                    "create_bot_channel_admin_check_non_admin bot_id=%s channel_ref=%s chat_id=%s attempt=%s member_status=%s",
                    me.id,
                    channel_ref,
                    chat_id,
                    attempt + 1,
                    status or "-",
                )

                # Not admin yet (or stale state). retry a bit.
                await asyncio.sleep(1.0)
                continue

            except TelegramBadRequest as exc:
                err = str(exc).lower()
                if await _chat_admins_include_bot(bot, chat_id, me.id):
                    logger.info(
                        "create_bot_channel_admins_fallback_success bot_id=%s channel_ref=%s chat_id=%s attempt=%s bad_request=%s",
                        me.id,
                        channel_ref,
                        chat_id,
                        attempt + 1,
                        err,
                    )
                    return True
                logger.warning(
                    "create_bot_channel_admin_check_bad_request bot_id=%s channel_ref=%s chat_id=%s attempt=%s err=%s",
                    me.id,
                    channel_ref,
                    chat_id,
                    attempt + 1,
                    err,
                )

                # transient/propagation issues: retry shortly
                if attempt < 3:
                    await asyncio.sleep(1.0)
                    continue
                return False

            except TelegramNetworkError as exc:
                logger.warning(
                    "create_bot_channel_admin_check_network bot_id=%s channel_ref=%s attempt=%s err=%s",
                    me.id,
                    channel_ref,
                    attempt + 1,
                    exc,
                )
                if attempt < 3:
                    await asyncio.sleep(1.0)
                    continue
                return False

            except Exception as exc:
                logger.warning(
                    "create_bot_channel_admin_check_unexpected bot_id=%s channel_ref=%s attempt=%s err=%s",
                    me.id,
                    channel_ref,
                    attempt + 1,
                    exc,
                )
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
    await state.update_data(
        **{
            INTRO_MSG_ID_KEY: None,
            PROMPT_MSG_ID_KEY: None,
            CHANNEL_PROMPT_MSG_ID_KEY: None,
            PHONE_PROMPT_MSG_ID_KEY: None,
            ADDRESS_PROMPT_MSG_ID_KEY: None,
            REPLY_KB_ANCHOR_MSG_ID_KEY: None,
            FLOW_REF_KEY: _new_flow_ref(),
            "lang": lang,
            "bot_token": "",
            "bot_id": None,
            "bot_username": "",
            "bot_title": "",
            "token_verified": False,
            "channel": "",
            "channel_verified": False,
            "admin_verified": False,
            "fullname": "",
            "phone": "",
            "phone_country": "",
            "phone_region": "",
            "address": "",
            "location_lat": None,
            "location_lon": None,
            "location_country": "",
            "preflight_ok": False,
            "preflight_checks": None,
        }
    )
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

        registered_bot = await _get_registered_bot_for_token_update(me.id)
        if registered_bot:
            if int(registered_bot.get("owner_id") or 0) == int(message.from_user.id):
                provisioning = registered_bot.get("provisioning") or {}
                reactivate = (
                    not bool(registered_bot.get("active", True))
                    and str(provisioning.get("status") or "").strip().lower() == "token_unauthorized"
                )
                updated = await update_bot_token(int(me.id), int(message.from_user.id), token, reactivate=reactivate)
                logger.info(
                    "create_bot_token_updated_existing user_id=%s bot_id=%s bot_username=%s updated=%s reactivated=%s",
                    message.from_user.id,
                    me.id,
                    me.username or "",
                    updated,
                    reactivate,
                )
                await _delete_intro_message(message.bot, message.chat.id, state)
                await state.clear()
                await _set_or_edit_prompt(
                    bot=message.bot,
                    chat_id=message.chat.id,
                    state=state,
                    text=_bot_token_updated_text(lang, getattr(me, "username", "")),
                    reply_markup=reseller_main_menu(lang),
                )
                return

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

        if await _is_bot_id_already_registered(me.id):
            logger.info(
                "create_bot_token_registered_inactive_or_unknown_owner user_id=%s bot_id=%s bot_username=%s",
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
            bot_username=_clean_bot_username(getattr(me, "username", "")),
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


@router.message(VerifyReseller.waiting_for_channel, lambda msg: getattr(msg, "chat_shared", None) is not None)
async def receive_channel_shared(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    try:
        await message.delete()
    except Exception:
        pass

    shared = getattr(message, "chat_shared", None)
    channel_norm = ""
    if shared:
        request_id = int(getattr(shared, "request_id", 0) or 0)
        if request_id != CHANNEL_PICKER_REQUEST_ID:
            logger.warning(
                "create_bot_channel_shared_unexpected_request_id user_id=%s request_id=%s",
                message.from_user.id,
                request_id,
            )
            return
        shared_username = getattr(shared, "chat_username", None) or getattr(shared, "username", None)
        shared_chat_id = getattr(shared, "chat_id", None)
        if shared_username:
            channel_norm = f"@{str(shared_username).lstrip('@')}"
        elif shared_chat_id:
            channel_norm = str(shared_chat_id)

    logger.info(
        "create_bot_channel_shared user_id=%s channel=%s",
        message.from_user.id,
        channel_norm or "-",
    )
    await _handle_channel_value(message, state, lang, channel_norm, trusted_channel=bool(channel_norm))


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


async def _handle_channel_value(
    message: types.Message,
    state: FSMContext,
    lang: str,
    channel_norm: str,
    *,
    trusted_channel: bool = False,
):
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
    bot_username = await _refresh_flow_bot_identity(
        str(bot_token or ""),
        state,
        fallback_username=str(data.get("bot_username", "") or ""),
    )
    add_url = _add_to_channel_url(bot_username)

    is_channel = True if trusted_channel else await _is_channel_target(bot_token, channel_norm)
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
    bot_username = await _refresh_flow_bot_identity(
        str(bot_token or ""),
        state,
        fallback_username=str(data.get("bot_username", "") or ""),
    )
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
    phone_region = _extract_phone_region(phone)
    await state.update_data(
        phone=phone,
        phone_country=phone_country,
        phone_region=phone_region,
        phone_is_syria=(phone_region == SYRIA_COUNTRY_CODE),
    )
    await _hide_reply_keyboard(message.bot, message.chat.id, state)
    await state.update_data(**{ADDRESS_PROMPT_MSG_ID_KEY: None})
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_step_prompt_html(lang, 5, "Telegram Location", "موقع تيليغرام", t(lang, "send_address")),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
    )
    await _show_location_request_keyboard(message.bot, message.chat.id, state, lang)
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
        phone_region = _extract_phone_region(phone)
        await state.update_data(
            phone=phone,
            phone_country=phone_country,
            phone_region=phone_region,
            phone_is_syria=(phone_region == SYRIA_COUNTRY_CODE),
        )
        await _hide_reply_keyboard(message.bot, message.chat.id, state)
        await state.update_data(**{ADDRESS_PROMPT_MSG_ID_KEY: None})
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 5, "Telegram Location", "موقع تيليغرام", t(lang, "send_address")),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await _show_location_request_keyboard(message.bot, message.chat.id, state, lang)
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


async def _finalize_location_step(message: types.Message, state: FSMContext, lang: str, location: types.Location):
    latitude = float(location.latitude)
    longitude = float(location.longitude)
    live_period = getattr(location, "live_period", None)
    is_live = bool(live_period)
    location_is_syria = _is_location_in_syria(latitude, longitude)
    await _delete_state_message_by_key(message.bot, message.chat.id, state, ADDRESS_PROMPT_MSG_ID_KEY)
    await _hide_reply_keyboard(message.bot, message.chat.id, state)
    await state.update_data(
        address=_location_address_text(latitude, longitude, live=is_live),
        location_latitude=latitude,
        location_longitude=longitude,
        location_live=is_live,
        location_live_period=int(live_period) if live_period else None,
        location_country_code=SYRIA_COUNTRY_CODE if location_is_syria else "OUTSIDE_SYRIA",
        location_is_syria=location_is_syria,
    )
    data = await state.get_data()

    preflight_ok, preflight_checks = await _run_preflight_checks(data, requester_id=int(message.from_user.id))
    await state.update_data(preflight_ok=preflight_ok, preflight_checks=preflight_checks)
    logger.info(
        "create_bot_preflight user_id=%s bot_id=%s ok=%s checks=%s phone_region=%s location_is_syria=%s location_live=%s",
        message.from_user.id,
        data.get("bot_id"),
        preflight_ok,
        preflight_checks,
        data.get("phone_region"),
        location_is_syria,
        is_live,
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


@router.message(VerifyReseller.waiting_for_address, lambda msg: msg.location is not None)
async def receive_location(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    try:
        await message.delete()
    except Exception:
        pass
    await _finalize_location_step(message, state, lang, message.location)


@router.message(VerifyReseller.waiting_for_address)
async def receive_address(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    try:
        await message.delete()
    except Exception:
        pass
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_step_prompt_html(lang, 5, "Telegram Location", "موقع تيليغرام", f"{_address_invalid_text(lang)}\n\n{t(lang, 'send_address')}"),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
    )
    await _show_location_request_keyboard(message.bot, message.chat.id, state, lang)


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
        flow_ref = str(data.get(FLOW_REF_KEY) or _new_flow_ref())
        if not data.get(FLOW_REF_KEY):
            await state.update_data(**{FLOW_REF_KEY: flow_ref})
        bot_username = await _refresh_flow_bot_identity(
            str(data.get("bot_token") or ""),
            state,
            fallback_username=str(data.get("bot_username") or ""),
        )
        group_url = _add_to_group_url(bot_username, start_payload=f"setup_{flow_ref}")
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
    if not preflight_checks or not preflight_ok:
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
    current_balance = await get_user_wallet_balance(int(callback.from_user.id), int(callback.from_user.id))
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
        "phone_region": data.get("phone_region", ""),
        "address": data["address"],
        "location": {
            "latitude": data.get("location_latitude"),
            "longitude": data.get("location_longitude"),
            "country_code": data.get("location_country_code", ""),
            "is_syria": bool(data.get("location_is_syria")),
            "live": bool(data.get("location_live")),
            "live_period": data.get("location_live_period"),
        },
    }

    manual_review_reasons = _manual_review_reasons(data)
    if manual_review_reasons:
        logger.info(
            "create_bot_manual_review_required user_id=%s bot_id=%s reasons=%s",
            callback.from_user.id,
            payload.get("bot_id"),
            manual_review_reasons,
        )
        await _submit_manual_bot_creation_review(
            callback=callback,
            state=state,
            lang=lang,
            payload=payload,
            reasons=manual_review_reasons,
            preflight_checks=preflight_checks,
        )
        return

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

        subscription = await sync_bot_subscription(int(payload["bot_id"]), collect_due=True)
        if not _subscription_activation_collected(subscription):
            await db.bots.delete_one({"bot_id": payload["bot_id"], "owner_id": int(callback.from_user.id)})
            created_new_bot = False
            retry_balance = await get_user_wallet_balance(int(callback.from_user.id), int(callback.from_user.id))
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
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_step_prompt_html(lang, 5, "Telegram Location", "موقع تيليغرام", t(lang, "send_address")),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await _show_location_request_keyboard(callback.bot, callback.message.chat.id, state, lang)
        return

    await callback.answer()
    return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)




























