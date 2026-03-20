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
from bson import ObjectId

from config import OWNER_ID, settings
from database.bots_repo import add_bot, update_bot_channel, update_reseller_info, verify_bot
from database.custom_services_repo import clone_catalog_from_reseller_template
from database.mongo import db
from database.reseller_settings_repo import get_exchange_routing, get_recharge_routing
from database.user_repo import get_user
from keyboards.main_menu_kb import main_menu
from keyboards.reseller_main_menu import reseller_main_menu
from utils.beta_mode import beta_disable_create_bot
from utils.permissions import is_reseller
from utils.translations import t

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


async def _beta_block_create_bot(
    target: types.Message | types.CallbackQuery,
    *,
    state: FSMContext | None = None,
    lang: str = "en",
) -> bool:
    if not beta_disable_create_bot():
        return False
    if state is not None:
        await state.clear()
    text = t(lang, "beta_create_bot_disabled")
    if isinstance(target, types.CallbackQuery):
        await target.answer(text, show_alert=True)
        if target.message:
            await target.message.answer(text)
    else:
        await target.answer(text)
    return True


async def _get_owner_target() -> tuple[int, int | None]:
    try:
        doc = await db.system_settings.find_one({"_id": "owner_notifications"})
        if doc and isinstance(doc.get("chat_id"), int):
            chat_id = int(doc["chat_id"])
            thread_id = doc.get("message_thread_id")
            if isinstance(thread_id, int):
                return chat_id, thread_id
            return chat_id, None
    except Exception:
        pass
    return OWNER_ID, None

def is_valid_token(text: str):
    return bool(_extract_token_input(text))


def _normalize_token_input(raw: str) -> str:
    if not raw:
        return ""
    cleaned = raw.strip().strip("`'\"")
    # Normalize common unicode punctuation that breaks token parsing.
    cleaned = cleaned.replace(":", ":").replace("?", ":")
    cleaned = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\s]+", "", cleaned)
    return cleaned


def _extract_token_input(raw: str) -> str:
    cleaned = _normalize_token_input(raw)
    if not cleaned:
        return ""
    m = re.search(r"(\d{9,10}:[A-Za-z0-9_-]{30,})", cleaned)
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


def _verify_confirm_kb(lang: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "confirm_create_bot"), callback_data="verify:confirm_create")
    kb.button(text="👥 Create Group + Add Bot", callback_data="verify:open_group_create")
    kb.button(text="🛠 Setup Help", callback_data="verify:setup_help")
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
    kb.button(text="👥 Create Group + Add Bot", url=group_add_url)
    kb.button(text="🔁 Recheck Setup", callback_data="verify:confirm_create")
    kb.button(text=t(lang, "back"), callback_data="verify_nav:back")
    kb.button(text=t(lang, "cancel"), callback_data="verify:cancel_create", style="danger")
    kb.adjust(1)
    return kb.as_markup()


def _owner_review_kb(lang: str, request_id: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "owner_approve_create"), callback_data=f"verify_owner:approve:{request_id}")
    kb.button(text=t(lang, "owner_reject_create"), callback_data=f"verify_owner:reject:{request_id}")
    kb.adjust(1)
    return kb.as_markup()


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


async def _show_channel_picker_prompt(bot: Bot, chat_id: int, state: FSMContext, lang: str):
    # Apply channel picker reply keyboard without adding visible extra messages.
    await _refresh_reply_keyboard(bot=bot, chat_id=chat_id, reply_markup=_channel_request_kb(lang))


async def _show_phone_request_keyboard(bot: Bot, chat_id: int, lang: str):
    # Apply phone-contact reply keyboard without adding visible extra messages.
    await _refresh_reply_keyboard(bot=bot, chat_id=chat_id, reply_markup=_phone_request_kb(lang))


async def _refresh_reply_keyboard(bot: Bot, chat_id: int, reply_markup: ReplyKeyboardMarkup):
    try:
        sent = await _safe_bot_send_message(
            bot=bot,
            chat_id=chat_id,
            text=t("en", "keyboard_cleanup_placeholder"),
            reply_markup=reply_markup,
        )
        try:
            await bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
        except Exception:
            pass
    except Exception:
        pass


async def _hide_reply_keyboard(bot: Bot, chat_id: int):
    try:
        sent = await _safe_bot_send_message(
            bot=bot,
            chat_id=chat_id,
            text=t("en", "keyboard_cleanup_placeholder"),
            reply_markup=ReplyKeyboardRemove(),
        )
        try:
            await bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
        except Exception:
            pass
    except Exception:
        pass


async def _return_to_main_menu(target: types.Message | types.CallbackQuery, user_id: int, lang: str, bot: Bot, state: FSMContext):
    bot_id = (await bot.get_me()).id
    if await is_reseller(user_id, bot_id=bot_id):
        markup = reseller_main_menu(lang)
    else:
        markup = main_menu(lang)

    chat_id = target.message.chat.id if isinstance(target, types.CallbackQuery) else target.chat.id
    await _delete_intro_message(bot, chat_id, state)
    await _delete_state_message_by_key(bot, chat_id, state, PHONE_PROMPT_MSG_ID_KEY)
    await _delete_state_message_by_key(bot, chat_id, state, ADDRESS_PROMPT_MSG_ID_KEY)
    await _delete_state_message_by_key(bot, chat_id, state, CHANNEL_PROMPT_MSG_ID_KEY)
    if await is_reseller(user_id, bot_id=bot_id):
        await _hide_reply_keyboard(bot, chat_id)
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

    is_ar = str(lang or "").lower().startswith("ar")
    lines = [
        t(lang, "preflight_title"),
        f"{mark(checks.get('token', False))} {t(lang, 'preflight_token_check')}",
        f"{mark(checks.get('channel', False))} {t(lang, 'preflight_channel_check')}",
        f"{mark(checks.get('admin', False))} {t(lang, 'preflight_admin_check')}",
        f"{mark(checks.get('reseller_group', False))} Reseller group routing + admin/topic permission (post-approval)",
    ]
    if checks.get("error"):
        lines.append(f"{t(lang, 'preflight_error_prefix')}: {checks['error']}")
    if checks.get("warning"):
        lines.append(f"Warning: {checks['warning']}")
    if not bool(checks.get("reseller_group")):
        if is_ar:
            lines.extend(
                [
                    "",
                    "خطوات اختيارية بعد الموافقة (وضع متقدم):",
                    "1) أنشئ غروب خاص للدفعات.",
                    "2) فعّل Topics من إعدادات الغروب.",
                    "3) أضف البوت كأدمن بصلاحيات إرسال الرسائل + Manage Topics.",
                    "4) من Reseller Settings نفّذ Auto Setup Topics.",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "Optional after approval (advanced mode):",
                    "1) Create a private payment group.",
                    "2) Enable Topics in group settings.",
                    "3) Add the bot as admin with Send Messages + Manage Topics.",
                    "4) From Reseller Settings run Auto Setup Topics.",
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

    # Group/topic routing is no longer a hard blocker during create request.
    # It is validated as advisory and enforced after approval/onboarding.
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

    return True, out

async def _is_bot_id_already_registered(bot_id: int) -> bool:
    doc = await db.bots.find_one({"bot_id": bot_id, "active": True}, {"_id": 1})
    return doc is not None


async def _has_pending_bot_request_for_user(user_id: int) -> bool:
    doc = await db.bot_creation_requests.find_one(
        {"requester_id": user_id, "status": "pending"},
        {"_id": 1},
    )
    return doc is not None


async def _has_pending_bot_request_for_bot_id(bot_id: int) -> bool:
    doc = await db.bot_creation_requests.find_one(
        {"payload.bot_id": bot_id, "status": "pending"},
        {"_id": 1},
    )
    return doc is not None


def _approval_packet_text(lang: str, payload: dict) -> str:
    return t(lang, "request_approved_packet").format(
        bot_title=payload.get("bot_title") or "-",
        bot_username=(f"@{payload.get('bot_username')}" if payload.get("bot_username") else "-"),
        bot_id=payload.get("bot_id") or "-",
        channel=payload.get("channel") or "-",
    )


async def _notify_requester_via_source_bot(req: dict, text: str) -> None:
    requester_id = req.get("requester_id")
    token = req.get("source_bot_token")
    if not requester_id or not token:
        return
    notify_bot = None
    try:
        notify_bot = Bot(token=token)
        await _safe_bot_send_message(bot=notify_bot, chat_id=int(requester_id), text=text)
    except Exception:
        pass
    finally:
        if notify_bot is not None:
            try:
                await notify_bot.session.close()
            except Exception:
                pass


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
    if await _beta_block_create_bot(message, state=state, lang=lang):
        return
    await state.update_data(**{INTRO_MSG_ID_KEY: None, FLOW_REF_KEY: _new_flow_ref(), "lang": lang})
    await _hide_reply_keyboard(message.bot, message.chat.id)

    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_as_html_quote(_intro_rest_text(lang)),
        reply_markup=_verify_intro_kb(lang),
        parse_mode="HTML",
    )
    await state.set_state(VerifyReseller.waiting_for_intro)


@router.callback_query(VerifyReseller.waiting_for_intro, lambda c: c.data == "verify:start_token")
async def start_token_step(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "en") if user else "en"
    if await _beta_block_create_bot(callback, state=state, lang=lang):
        return
    await callback.answer()
    await _set_or_edit_prompt(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        state=state,
        text=_as_html_quote(_token_rest_text(lang)),
        reply_markup=_verify_nav_kb(lang, include_back=False),
        parse_mode="HTML",
    )
    await state.set_state(VerifyReseller.waiting_for_token)



@router.message(VerifyReseller.waiting_for_intro)
async def ignore_intro_text(message: types.Message):
    # Intro step accepts only inline buttons (Continue/Cancel).
    await _safe_delete_user_message(message, context="verify_waiting_intro")
@router.message(VerifyReseller.waiting_for_token)
async def save_token(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    token = _extract_token_input(message.text or "")
    bot = None

    await _safe_delete_user_message(message, context="verify_waiting_token")

    if not is_valid_token(token):
        return await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=f"{escape(t(lang, 'invalid_token'))}\n\n{_as_html_quote(_token_rest_text(lang))}",
            reply_markup=_verify_nav_kb(lang, include_back=False),
            parse_mode="HTML",
        )

    try:
        bot = Bot(token=token)
        me = await bot.get_me()

        if await _is_bot_id_already_registered(me.id):
            await _set_or_edit_prompt(
                bot=message.bot,
                chat_id=message.chat.id,
                state=state,
                text=f"{escape(t(lang, 'bot_already_registered'))}\n\n{_as_html_quote(_token_rest_text(lang))}",
                reply_markup=_verify_nav_kb(lang, include_back=False),
                parse_mode="HTML",
            )
            return

        if await _has_pending_bot_request_for_bot_id(me.id):
            await _set_or_edit_prompt(
                bot=message.bot,
                chat_id=message.chat.id,
                state=state,
                text=f"{escape(t(lang, 'bot_pending_review_exists'))}\n\n{_as_html_quote(_token_rest_text(lang))}",
                reply_markup=_verify_nav_kb(lang, include_back=False),
                parse_mode="HTML",
            )
            return

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
            text=_as_html_quote(t(lang, "send_channel")),
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
            text=f"{escape(t(lang, 'token_verify_network'))}\n\n{_as_html_quote(_token_rest_text(lang))}",
            reply_markup=_verify_nav_kb(lang, include_back=False),
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
            text=f"{escape(t(lang, key))}\n\n{_as_html_quote(_token_rest_text(lang))}",
            reply_markup=_verify_nav_kb(lang, include_back=False),
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
            text=f"{escape(t(lang, 'token_verify_failed'))}\n\n{_as_html_quote(_token_rest_text(lang))}",
            reply_markup=_verify_nav_kb(lang, include_back=False),
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
    # Channel step accepts only chat-share button; text input is ignored silently.
    await _safe_delete_user_message(message, context="verify_waiting_channel_text")
    return


async def _handle_channel_value(message: types.Message, state: FSMContext, lang: str, channel_norm: str):
    if not channel_norm:
        await _set_or_edit_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            state=state,
            text=_as_html_quote(f"{t(lang, 'invalid_channel')}\n\n{t(lang, 'send_channel')}"),
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
            text=_as_html_quote(t(lang, "channel_admin_required")),
            reply_markup=_verify_channel_admin_kb(lang, add_url, include_back=True),
            parse_mode="HTML",
        )
        await _show_channel_picker_prompt(message.bot, message.chat.id, state, lang)
        return

    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_as_html_quote(t(lang, "checking_channel_admin")),
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
            text=_as_html_quote(t(lang, "channel_admin_required")),
            reply_markup=_verify_channel_admin_kb(lang, add_url, include_back=True),
            parse_mode="HTML",
        )
        await _show_channel_picker_prompt(message.bot, message.chat.id, state, lang)
        return

    await state.update_data(channel_verified=True, admin_verified=True)
    await _delete_state_message_by_key(message.bot, message.chat.id, state, CHANNEL_PROMPT_MSG_ID_KEY)
    await _hide_reply_keyboard(message.bot, message.chat.id)
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_as_html_quote(t(lang, "send_fullname")),
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
        text=_as_html_quote(t(lang, "checking_channel_admin")),
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
            text=_as_html_quote(t(lang, "channel_admin_required")),
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
            text=_as_html_quote(t(lang, "send_channel")),
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
            text=_as_html_quote(t(lang, "channel_admin_required")),
            reply_markup=_verify_channel_admin_kb(lang, add_url, include_back=True),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await _show_channel_picker_prompt(callback.bot, callback.message.chat.id, state, lang)
        return

    await state.update_data(channel_verified=True, admin_verified=True)
    await _delete_state_message_by_key(callback.bot, callback.message.chat.id, state, CHANNEL_PROMPT_MSG_ID_KEY)
    await _hide_reply_keyboard(callback.bot, callback.message.chat.id)
    await _set_or_edit_prompt(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        state=state,
        text=_as_html_quote(t(lang, "send_fullname")),
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
            text=_as_html_quote(f"{t(lang, 'full_name_required')}\n\n{t(lang, 'send_fullname')}"),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
    await state.update_data(fullname=fullname)
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_as_html_quote(t(lang, "send_phone")),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
    )
    await _show_phone_request_keyboard(message.bot, message.chat.id, lang)
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
            text=_as_html_quote(f"{t(lang, 'phone_contact_only')}\n\n{t(lang, 'send_phone')}"),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await _show_phone_request_keyboard(message.bot, message.chat.id, lang)
        return
    phone = (message.contact.phone_number or "").strip()
    phone_country = _extract_phone_country(phone)
    await state.update_data(phone=phone, phone_country=phone_country)
    await _hide_reply_keyboard(message.bot, message.chat.id)
    await state.update_data(**{ADDRESS_PROMPT_MSG_ID_KEY: None})
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_as_html_quote(t(lang, "send_address")),
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
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_as_html_quote(f"{t(lang, 'phone_contact_only')}\n\n{t(lang, 'send_phone')}"),
        reply_markup=_verify_nav_kb(lang, include_back=True),
        parse_mode="HTML",
    )
    await _show_phone_request_keyboard(message.bot, message.chat.id, lang)
    await state.update_data(**{PHONE_PROMPT_MSG_ID_KEY: None})


@router.message(VerifyReseller.waiting_for_address)
async def receive_address(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    try:
        await message.delete()
    except Exception:
        pass

    await _delete_state_message_by_key(message.bot, message.chat.id, state, ADDRESS_PROMPT_MSG_ID_KEY)
    await state.update_data(address=(message.text or "").strip())
    data = await state.get_data()

    preflight_ok, preflight_checks = await _run_preflight_checks(data, requester_id=int(message.from_user.id))
    await state.update_data(preflight_ok=preflight_ok, preflight_checks=preflight_checks)

    summary_text = _build_summary_text(data, lang, preflight_checks)

    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_as_html_quote(summary_text),
        reply_markup=_verify_confirm_kb(lang),
        parse_mode="HTML",
    )
    await state.set_state(VerifyReseller.waiting_for_confirm)


@router.callback_query(
    VerifyReseller.waiting_for_confirm,
    lambda c: c.data in {"verify:confirm_create", "verify:cancel_create", "verify:open_group_create", "verify:setup_help"},
)
async def confirm_create_flow(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "en") if user else "en"
    if await _beta_block_create_bot(callback, state=state, lang=lang):
        return

    if callback.data == "verify:cancel_create":
        await callback.answer()
        return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)

    if callback.data in {"verify:open_group_create", "verify:setup_help"}:
        data = await state.get_data()
        group_url = _add_to_group_url(str(data.get("bot_username") or ""))
        setup_help_text = (
            "Group setup quick action:\n\n"
            "1) Tap 'Create Group + Add Bot'.\n"
            "2) In the new group, enable Topics.\n"
            "3) Keep bot as admin with Manage Topics.\n"
            "4) Complete approval first.\n"
            "5) After approval, open Reseller Settings and run Auto Setup Topics.\n"
            "6) Tap 'Recheck Setup'."
        )
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_as_html_quote(setup_help_text),
            reply_markup=_verify_setup_help_kb(lang, group_url),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await callback.answer()
        return

    data = await state.get_data()
    required = ("bot_token", "bot_id", "channel", "fullname", "phone", "address")

    if await _has_pending_bot_request_for_user(callback.from_user.id):
        await callback.answer(t(lang, "pending_request_exists"), show_alert=True)
        return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)

    if await _is_bot_id_already_registered(int(data.get("bot_id", 0) or 0)):
        await callback.answer(t(lang, "bot_already_registered"), show_alert=True)
        return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)

    if await _has_pending_bot_request_for_bot_id(int(data.get("bot_id", 0) or 0)):
        await callback.answer(t(lang, "bot_pending_review_exists"), show_alert=True)
        return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)
    if any(not data.get(k) for k in required):
        await callback.answer(t(lang, "invalid_token"), show_alert=True)
        return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)

    preflight_checks = data.get("preflight_checks") or {}
    preflight_ok = bool(data.get("preflight_ok"))
    if not preflight_checks:
        preflight_ok, preflight_checks = await _run_preflight_checks(data, requester_id=int(callback.from_user.id))
        await state.update_data(preflight_ok=preflight_ok, preflight_checks=preflight_checks)
    if not preflight_ok:
        summary_text = _build_summary_text(data, lang, preflight_checks)
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_as_html_quote(f"{summary_text}\n\n{t(lang, 'preflight_fix_and_retry')}"),
            reply_markup=_verify_confirm_kb(lang),
            parse_mode="HTML",
            preferred_message_id=callback.message.message_id,
        )
        await callback.answer(t(lang, "preflight_failed_alert"), show_alert=True)
        return

    req_doc = {
        "requester_id": callback.from_user.id,
        "requester_username": callback.from_user.username or "",
        "requester_lang": lang,
        "source_bot_id": (await callback.bot.get_me()).id,
        "source_bot_token": callback.bot.token,
        "payload": {
            "bot_token": data["bot_token"],
            "bot_id": data["bot_id"],
            "bot_title": data.get("bot_title", ""),
            "bot_username": data.get("bot_username", ""),
            "channel": data["channel"],
            "fullname": data["fullname"],
            "phone": data["phone"],
            "phone_country": data.get("phone_country", "Unknown"),
            "address": data["address"],
        },
        "status": "pending",
        "created_at": datetime.now(UTC),
    }
    ins = await db.bot_creation_requests.insert_one(req_doc)
    request_id = str(ins.inserted_id)

    requester = (
        f"@{req_doc['requester_username']} ({req_doc['requester_id']})"
        if req_doc["requester_username"]
        else str(req_doc["requester_id"])
    )

    owner_text = t(lang, "owner_review_request").format(
        requester=requester,
        bot_title=req_doc["payload"].get("bot_title") or "-",
        bot_username=(f"@{req_doc['payload'].get('bot_username')}" if req_doc["payload"].get("bot_username") else "-"),
        channel=req_doc["payload"]["channel"],
        fullname=req_doc["payload"]["fullname"],
        phone=req_doc["payload"]["phone"],
        phone_country=req_doc["payload"].get("phone_country", "Unknown"),
        address=req_doc["payload"]["address"],
        request_id=request_id,
    )

    admin_bot = None
    try:
        owner_chat_id, owner_thread_id = await _get_owner_target()
        send_kwargs = {
            "reply_markup": _owner_review_kb(lang, request_id),
        }
        if owner_thread_id is not None:
            send_kwargs["message_thread_id"] = owner_thread_id

        admin_bot = Bot(token=settings.bot_admin_token)
        owner_msg = await _safe_bot_send_message(
            bot=admin_bot,
            chat_id=owner_chat_id,
            text=owner_text,
            **send_kwargs,
        )
        await db.bot_creation_requests.update_one(
            {"_id": ins.inserted_id},
            {
                "$set": {
                    "owner_chat_id": owner_chat_id,
                    "owner_message_thread_id": owner_thread_id,
                    "owner_message_id": owner_msg.message_id,
                }
            },
        )
    except Exception as exc:
        logger.exception("failed to notify owner for request=%s: %s", request_id, exc)
        await callback.message.answer(t(lang, "owner_notify_failed"))
    finally:
        if admin_bot is not None:
            try:
                await admin_bot.session.close()
            except Exception:
                pass

    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(t(lang, "request_submitted_owner_review"))
    await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)


@router.callback_query(lambda c: c.data and c.data.startswith("verify_owner:"))
async def owner_review_callback(callback: types.CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return await callback.answer(t("en", "no_permission"), show_alert=True)

    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        return await callback.answer("Invalid action", show_alert=True)

    action = parts[1]
    req_id = parts[2]
    try:
        oid = ObjectId(req_id)
    except Exception:
        return await callback.answer(t("en", "owner_request_not_found"), show_alert=True)

    req = await db.bot_creation_requests.find_one({"_id": oid, "status": "pending"})
    if not req:
        return await callback.answer(t("en", "owner_request_not_found"), show_alert=True)

    payload = req.get("payload", {})
    requester_id = req.get("requester_id")
    requester_lang = req.get("requester_lang", "en")

    async def _resolve_template_reseller_id() -> int | None:
        username = str(getattr(settings, "main_reseller_bot_username", "") or "").strip().lstrip("@").lower()
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

        req_doc = await db.bot_creation_requests.find_one(
            {
                "status": "approved",
                "$or": [
                    {"payload.bot_username": {"$regex": f"^@?{re.escape(username)}$", "$options": "i"}},
                    {"payload.bot_username_lc": username},
                ],
            },
            sort=[("reviewed_at", -1), ("created_at", -1)],
        )
        if req_doc:
            try:
                rid = req_doc.get("requester_id")
                return int(rid) if rid is not None else None
            except Exception:
                return None
        return None

    if action == "approve":
        try:
            exists = await db.bots.find_one({"bot_id": payload.get("bot_id")})
            if not exists:
                await add_bot(payload["bot_token"], requester_id, payload["bot_id"])
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

            template_reseller_id = await _resolve_template_reseller_id()
            if template_reseller_id and int(requester_id) != int(template_reseller_id):
                clone_res = await clone_catalog_from_reseller_template(
                    source_reseller_id=int(template_reseller_id),
                    target_reseller_id=int(requester_id),
                    catalog_type="custom",
                )
                logger.info(
                    "custom template clone result source=%s target=%s success=%s reason=%s copied=%s",
                    template_reseller_id,
                    requester_id,
                    clone_res.get("success"),
                    clone_res.get("reason"),
                    clone_res.get("copied"),
                )
            else:
                logger.info(
                    "custom template clone skipped target=%s template=%s",
                    requester_id,
                    template_reseller_id,
                )
            new_status = "approved"
            owner_msg = t("en", "owner_request_approved")
            user_msg = (
                f"{t(requester_lang, 'request_approved_user_details')}\n\n"
                f"{_approval_packet_text(requester_lang, payload)}\n\n"
                f"{t(requester_lang, 'reseller_setup_post_approval')}"
            )
        except Exception as exc:
            logger.exception("owner approve failed for request=%s: %s", req_id, exc)
            new_status = "failed"
            owner_msg = f"Failed to approve: {exc}"
            user_msg = f"Failed to approve request: {exc}"
    else:
        new_status = "rejected"
        owner_msg = t("en", "owner_request_rejected")
        user_msg = t(requester_lang, "request_rejected_user")

    safe_payload = {k: v for k, v in payload.items() if k != "bot_token"}
    await db.bot_creation_requests.update_one(
        {"_id": oid},
        {
            "$set": {
                "status": new_status,
                "reviewed_at": datetime.now(UTC),
                "reviewed_by": callback.from_user.id,
                "reviewed_by_username": callback.from_user.username or "",
                "reviewed_from_chat_id": callback.message.chat.id if callback.message else None,
                "reviewed_from_message_id": callback.message.message_id if callback.message else None,
                "reviewed_from_thread_id": getattr(callback.message, "message_thread_id", None) if callback.message else None,
                "audit": {
                    "action": action,
                    "source": "verify_reseller_router",
                    "reviewed_bot_id": (await callback.bot.get_me()).id,
                    "payload_snapshot": safe_payload,
                },
            }
        },
    )

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer(owner_msg, show_alert=True)

    if requester_id:
        await _notify_requester_via_source_bot(req, user_msg)
        try:
            await callback.bot.send_message(requester_id, user_msg)
        except Exception:
            pass


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
            text=_as_html_quote(_intro_rest_text(lang)),
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
            text=_as_html_quote(_token_rest_text(lang)),
            reply_markup=_verify_nav_kb(lang, include_back=False),
            parse_mode="HTML",
        )

    if current == VerifyReseller.waiting_for_fullname.state:
        await state.set_state(VerifyReseller.waiting_for_channel)
        await callback.answer()
        await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_as_html_quote(t(lang, "send_channel")),
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
            text=_as_html_quote(t(lang, "send_fullname")),
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
            text=_as_html_quote(t(lang, "send_phone")),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        await _show_phone_request_keyboard(callback.bot, callback.message.chat.id, lang)
        return

    if current == VerifyReseller.waiting_for_confirm.state:
        await state.set_state(VerifyReseller.waiting_for_address)
        await callback.answer()
        return await _set_or_edit_prompt(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            state=state,
            text=_as_html_quote(t(lang, "send_address")),
            reply_markup=_verify_nav_kb(lang, include_back=True),
            parse_mode="HTML",
        )

    await callback.answer()
    return await _return_to_main_menu(callback, callback.from_user.id, lang, callback.bot, state)




























