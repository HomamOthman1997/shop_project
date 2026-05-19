from datetime import UTC, datetime, timedelta
from html import escape
import re
from urllib.parse import parse_qs, urlparse

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bson import ObjectId

from config import OWNER_ID, settings
from database.bots_repo import get_bot_settings
from services.subscriptions.bot_subscription_service import get_bot_subscription, set_bot_subscription_plan, sync_bot_subscription
from services.subscriptions.presentation import (
    format_subscription_dt,
    reseller_subscription_kb,
    subscription_status_label,
    subscription_summary_lines,
)
from database.financial_ledger import credit_user_wallet, get_reseller_wallet_balance, get_user_wallet_balance
from database.mongo import db
from database.owner_payment_settings_repo import (
    get_owner_exchange_rate,
    get_owner_payment_methods,
    render_owner_method_instructions,
)
from database.recharge_repo import create_recharge_request, get_recharge_requests_for_reseller, update_recharge_request
from database.reseller_settings_repo import (
    add_recharge_address,
    clear_exchange_routing,
    clear_recharge_routing,
    delete_recharge_address,
    get_exchange_routing,
    get_recharge_addresses,
    get_recharge_routing,
    get_exchange_rate,
    get_payment_methods,
    set_exchange_rate,
    set_recharge_routing,
    set_support_routing,
    set_exchange_routing,
    get_all_support_routing,
    render_method_instructions,
    update_payment_method,
)
from database.user_repo import get_user, get_user_by_username, get_user_reseller_for_bot
from keyboards.balance_keyboard import balance_keyboard
from keyboards.reseller_main_menu import reseller_main_menu
from utils.bot_menu_context import extract_bot_id_from_token, main_bot_url, send_main_bot_message
from utils.permissions import is_reseller, owner_only
from utils.recharge_ui import (
    format_owner_reseller_topup_text,
    owner_reseller_topup_review_kb,
    user_recharge_review_kb,
)
from utils.translations import t
from utils.reseller_setup_guard import get_reseller_setup_status, render_reseller_setup_notice
from utils.user_money import format_usd

router = Router()


def _configured_platform_bot_token(bot_id: int) -> str:
    for attr in (
        "bot_main_token",
        "bot_numbers_token",
        "bot_digital_products_token",
        "bot_card_ex_token",
        "bot_cards_token",
        "bot_admin_token",
    ):
        token = str(getattr(settings, attr, "") or "").strip()
        if token and extract_bot_id_from_token(token) == int(bot_id):
            return token
    return ""


async def _resolve_request_user_notification_bot(req: dict, fallback_bot: Bot) -> Bot:
    details = req.get("details") or {}
    source_bot_id = int(details.get("source_bot_id") or 0)
    fallback_id = int((await fallback_bot.get_me()).id)
    if source_bot_id <= 0 or source_bot_id == fallback_id:
        return fallback_bot

    token = _configured_platform_bot_token(source_bot_id)
    if not token:
        bot_row = await db.bots.find_one({"bot_id": source_bot_id, "active": True}, {"token": 1})
        token = str((bot_row or {}).get("token") or "").strip()
    if not token:
        return fallback_bot
    return Bot(token=token)


async def _notify_recharge_request_user(
    req: dict,
    fallback_bot: Bot,
    text: str,
    *,
    reply_markup=None,
) -> None:
    notify_bot = await _resolve_request_user_notification_bot(req, fallback_bot)
    try:
        await notify_bot.send_message(
            int(req.get("user_id") or 0),
            text,
            reply_markup=reply_markup,
        )
    finally:
        if notify_bot is not fallback_bot:
            try:
                await notify_bot.session.close()
            except Exception:
                pass


async def _clear_reply_markup_safely(message: types.Message | None) -> None:
    if not message:
        return
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise
    except Exception:
        return


async def _replace_inline_message(
    message: types.Message | None,
    text: str,
    *,
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> types.Message | None:
    if not message:
        return None
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return message
    except TelegramBadRequest as exc:
        error_text = str(exc).lower()
        if "message is not modified" in error_text:
            return message
        fallback_errors = ("message can't be edited", "message cant be edited", "there is no text in the message to edit")
        if not any(item in error_text for item in fallback_errors):
            raise
    return await message.answer(text, reply_markup=reply_markup)


async def _edit_bot_message_text(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> bool:
    if int(chat_id or 0) == 0 or int(message_id or 0) <= 0:
        return False
    try:
        await bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=text,
            reply_markup=reply_markup,
        )
        return True
    except AttributeError:
        return False
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return True
        return False


_SUPPORT_TOPIC_CATEGORIES = (
    ("services", "Support - Custom Services"),
    ("user_balance", "Support - User Balance"),
)


class ResellerRechargeFSM(StatesGroup):
    waiting_for_address = State()


class ResellerAdjustFSM(StatesGroup):
    waiting_for_target = State()
    waiting_for_action = State()
    waiting_for_amount = State()
    waiting_for_confirm = State()


class ManualRechargeDecisionFSM(StatesGroup):
    waiting_manual_amount = State()


class NeedProofFSM(StatesGroup):
    waiting_reason = State()


class ResellerSettingsFSM(StatesGroup):
    waiting_payment_topic_target = State()
    waiting_exchange_topic_target = State()
    waiting_auto_topics_group_target = State()
    waiting_support_topics_group_target = State()
    waiting_exchange_rate = State()
    waiting_method_value = State()


class ResellerCoreTopupFSM(StatesGroup):
    waiting_method = State()
    waiting_amount = State()
    waiting_proof = State()


class OwnerResellerTopupFSM(StatesGroup):
    waiting_manual_amount = State()


class ResellerBroadcastFSM(StatesGroup):
    waiting_payload = State()
    waiting_confirm = State()
    waiting_text = State()


def _text_eq(text: str | None, *candidates: str) -> bool:
    raw = (text or "").strip().lower()
    return raw in {x.strip().lower() for x in candidates}


def _reseller_broadcast_kb(lang: str = "en") -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text=_txt(lang, "✍️ نص", "✍️ Text"), callback_data="rs_broadcast:text"),
                types.InlineKeyboardButton(text=_txt(lang, "🖼 صورة", "🖼 Photo"), callback_data="rs_broadcast:photo"),
            ],
            [
                types.InlineKeyboardButton(text=_txt(lang, "🎬 فيديو", "🎬 Video"), callback_data="rs_broadcast:video"),
                types.InlineKeyboardButton(text=_txt(lang, "📎 ملف", "📎 File"), callback_data="rs_broadcast:document"),
            ],
            [types.InlineKeyboardButton(text=_txt(lang, "🔁 نسخ رسالة جاهزة", "🔁 Copy Ready Message"), callback_data="rs_broadcast:copy")],
            [types.InlineKeyboardButton(text=_txt(lang, "⬅️ رجوع للوحة الريسيلر", "⬅️ Back to Reseller Menu"), callback_data="rsmenu:menu")],
        ]
    )


def _reseller_broadcast_wait_kb(lang: str = "en") -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=_txt(lang, "❌ إلغاء", "❌ Cancel"), callback_data="rs_broadcast:cancel")],
            [types.InlineKeyboardButton(text=_txt(lang, "↩️ اختيار نوع آخر", "↩️ Choose Another Type"), callback_data="rs_broadcast:restart")],
        ]
    )


def _reseller_broadcast_confirm_kb(lang: str = "en") -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=_txt(lang, "✅ إرسال الآن", "✅ Send Now"), callback_data="rs_broadcast:send")],
            [
                types.InlineKeyboardButton(text=_txt(lang, "🔕 إرسال صامت", "🔕 Send Silent"), callback_data="rs_broadcast:silent"),
                types.InlineKeyboardButton(text=_txt(lang, "📌 إرسال وتثبيت", "📌 Send & Pin"), callback_data="rs_broadcast:pin"),
            ],
            [types.InlineKeyboardButton(text=_txt(lang, "🔒 إرسال محمي", "🔒 Send Protected"), callback_data="rs_broadcast:protect")],
            [
                types.InlineKeyboardButton(text=_txt(lang, "↩️ تعديل/إعادة إرسال", "↩️ Edit / Resend"), callback_data="rs_broadcast:restart"),
                types.InlineKeyboardButton(text=_txt(lang, "❌ إلغاء", "❌ Cancel"), callback_data="rs_broadcast:cancel"),
            ],
        ]
    )


def _broadcast_type_label(lang: str, kind: str) -> str:
    labels = {
        "text": ("نص", "Text"),
        "photo": ("صورة", "Photo"),
        "video": ("فيديو", "Video"),
        "document": ("ملف", "File"),
        "copy": ("رسالة جاهزة", "Ready message"),
    }
    ar, en = labels.get(str(kind or ""), labels["copy"])
    return _txt(lang, ar, en)


def _broadcast_prompt_text(lang: str, kind: str) -> str:
    if _is_ar(lang):
        prompts = {
            "text": "أرسل نص الإذاعة الآن كما يجب أن يظهر في القناة.",
            "photo": "أرسل الصورة الآن. يمكنك إضافة كابشن إذا احتجت.",
            "video": "أرسل الفيديو الآن. يمكنك إضافة كابشن إذا احتجت.",
            "document": "أرسل الملف الآن. يمكنك إضافة كابشن إذا احتجت.",
            "copy": "أرسل أي رسالة جاهزة تريد نسخها للقناة كما هي: نص، صورة، فيديو، ملف، صوت، أو رسالة بكابشن.",
        }
        return f"{prompts.get(kind, prompts['copy'])}\n\nللإلغاء أرسل /cancel أو استخدم الأزرار."
    prompts = {
        "text": "Send the broadcast text exactly as it should appear in the channel.",
        "photo": "Send the photo now. You can include a caption.",
        "video": "Send the video now. You can include a caption.",
        "document": "Send the file now. You can include a caption.",
        "copy": "Send any ready message to copy into the channel as-is: text, photo, video, file, audio, or a captioned message.",
    }
    return f"{prompts.get(kind, prompts['copy'])}\n\nSend /cancel or use the buttons to cancel."


def _message_matches_broadcast_kind(message: types.Message, kind: str) -> bool:
    if kind == "text":
        return bool((message.text or "").strip())
    if kind == "photo":
        return bool(getattr(message, "photo", None))
    if kind == "video":
        return bool(getattr(message, "video", None))
    if kind == "document":
        return bool(getattr(message, "document", None))
    return any(bool(getattr(message, attr, None)) for attr in ("text", "photo", "video", "document", "animation", "audio", "voice", "video_note"))


def _broadcast_payload_summary(message: types.Message, lang: str, kind: str) -> str:
    label = _broadcast_type_label(lang, kind)
    caption = str(getattr(message, "caption", "") or "").strip()
    text = str(getattr(message, "text", "") or "").strip()
    if _is_ar(lang):
        extra = f"طول النص: {len(text)} حرف" if kind == "text" else ("مع كابشن" if caption else "بدون كابشن")
        return f"نوع الإذاعة: {label}\n{extra}"
    extra = f"Text length: {len(text)} chars" if kind == "text" else ("with caption" if caption else "without caption")
    return f"Broadcast type: {label}\n{extra}"


def _broadcast_fallback_payload(message: types.Message, kind: str) -> dict:
    caption = str(getattr(message, "caption", "") or "").strip()
    if kind == "text":
        return {"kind": "text", "text": str(getattr(message, "text", "") or "").strip()}
    if kind == "photo" and getattr(message, "photo", None):
        return {"kind": "photo", "file_id": getattr(message.photo[-1], "file_id", ""), "caption": caption}
    if kind == "video" and getattr(message, "video", None):
        return {"kind": "video", "file_id": getattr(message.video, "file_id", ""), "caption": caption}
    if kind == "document" and getattr(message, "document", None):
        return {"kind": "document", "file_id": getattr(message.document, "file_id", ""), "caption": caption}
    if kind == "copy":
        for fallback_kind in ("text", "photo", "video", "document"):
            payload = _broadcast_fallback_payload(message, fallback_kind)
            if payload.get("text") or payload.get("file_id"):
                return payload
    return {"kind": kind}


async def _current_bot_broadcast_channel(bot: Bot) -> str | None:
    me = await bot.get_me()
    settings_doc = await get_bot_settings(int(me.id))
    raw = str((settings_doc or {}).get("subscription_channel") or "").strip()
    return raw or None


async def _broadcast_channel_status(bot: Bot) -> tuple[bool, str | None, str]:
    channel = await _current_bot_broadcast_channel(bot)
    if not channel:
        return False, None, "قناة البوت غير مربوطة أو البوت ليس Admin فيها."
    try:
        chat = await bot.get_chat(channel)
        if str(getattr(chat, "type", "") or "") != "channel":
            return False, channel, "القناة المحفوظة لهذا البوت ليست قناة تيليغرام صالحة."
    except Exception:
        return False, channel, "قناة البوت غير مربوطة أو البوت ليس Admin فيها."
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id=channel, user_id=int(me.id))
        status = str(getattr(member, "status", "") or "").lower()
        if status not in {"administrator", "creator"}:
            return False, channel, "قناة البوت غير مربوطة أو البوت ليس Admin فيها."
    except Exception:
        return False, channel, "قناة البوت غير مربوطة أو البوت ليس Admin فيها."
    return True, channel, ""


async def _send_broadcast_post(bot: Bot, text: str) -> tuple[bool, str]:
    ok, channel, error_text = await _broadcast_channel_status(bot)
    if not ok or not channel:
        return False, error_text
    try:
        await bot.send_message(chat_id=channel, text=text)
    except Exception as exc:
        return False, f"Broadcast failed: {exc}"
    return True, f"Broadcast sent to {channel}."


async def _send_broadcast_copy(
    bot: Bot,
    *,
    source_chat_id: int,
    source_message_id: int,
    fallback_payload: dict | None = None,
    silent: bool = False,
    pin: bool = False,
    protect: bool = False,
) -> tuple[bool, str]:
    ok, channel, error_text = await _broadcast_channel_status(bot)
    if not ok or not channel:
        return False, error_text
    try:
        copied = await bot.copy_message(
            chat_id=channel,
            from_chat_id=int(source_chat_id),
            message_id=int(source_message_id),
            disable_notification=bool(silent or pin),
            protect_content=bool(protect),
        )
    except Exception as exc:
        copied = await _send_broadcast_fallback(
            bot,
            channel=channel,
            payload=fallback_payload,
            silent=silent or pin,
            protect=protect,
        )
        if copied is None:
            return False, f"Broadcast failed: {exc}"

    copied_message_id = int(getattr(copied, "message_id", 0) or 0)
    if pin:
        if copied_message_id <= 0:
            return True, f"Broadcast sent to {channel}, but pin status could not be verified."
        try:
            await bot.pin_chat_message(chat_id=channel, message_id=copied_message_id, disable_notification=True)
        except Exception as exc:
            return True, f"Broadcast sent to {channel}, but pin failed: {exc}"
        return True, f"Broadcast sent and pinned in {channel}."
    return True, f"Broadcast sent to {channel}."


async def _send_broadcast_fallback(
    bot: Bot,
    *,
    channel: str,
    payload: dict | None,
    silent: bool = False,
    protect: bool = False,
):
    payload = dict(payload or {})
    kind = str(payload.get("kind") or "")
    common = {"chat_id": channel, "disable_notification": bool(silent), "protect_content": bool(protect)}
    if kind == "text" and str(payload.get("text") or "").strip():
        return await bot.send_message(text=str(payload["text"]), **common)
    if kind == "photo" and str(payload.get("file_id") or "").strip():
        return await bot.send_photo(photo=str(payload["file_id"]), caption=str(payload.get("caption") or "") or None, **common)
    if kind == "video" and str(payload.get("file_id") or "").strip():
        return await bot.send_video(video=str(payload["file_id"]), caption=str(payload.get("caption") or "") or None, **common)
    if kind == "document" and str(payload.get("file_id") or "").strip():
        return await bot.send_document(document=str(payload["file_id"]), caption=str(payload.get("caption") or "") or None, **common)
    return None


async def _is_current_bot_reseller(user_id: int, bot) -> bool:
    bot_id = (await bot.get_me()).id
    return await is_reseller(user_id, bot_id=bot_id)


async def _resolve_target_user_id(raw: str) -> int | None:
    txt = (raw or "").strip()
    if not txt:
        return None
    if txt.startswith("@"):
        user = await get_user_by_username(txt[1:])
        if not user:
            return None
        return int(user.get("telegram_id"))
    if txt.isdigit():
        return int(txt)
    return None


async def _resolve_user_wallet_reseller(_user_id: int, fallback_reseller_id: int, bot_id: int) -> int | None:
    linked = await get_user_reseller_for_bot(int(_user_id), int(bot_id))
    if linked is None:
        return None
    if int(linked) != int(fallback_reseller_id):
        return None
    return int(linked)


ADJUST_ACTION_META = {
    "add": {
        "label": "Add Balance",
        "reason": "reseller_manual_credit",
    },
    "set": {
        "label": "Set Balance",
        "reason": "reseller_manual_set",
    },
    "decrease": {
        "label": "Decrease Balance",
        "reason": "reseller_manual_debit",
    },
}


def _reseller_adjust_action_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Add Balance", callback_data="rsadj:add")],
            [types.InlineKeyboardButton(text="Set Balance", callback_data="rsadj:set")],
            [types.InlineKeyboardButton(text="Decrease Balance", callback_data="rsadj:decrease")],
            [types.InlineKeyboardButton(text="Cancel", callback_data="rsadj:cancel")],
        ]
    )


async def _reseller_lang(user_id: int) -> str:
    user = await get_user(int(user_id))
    return (user or {}).get("language", "en")


async def _reseller_setup_ready(reseller_id: int) -> tuple[bool, dict]:
    status = await get_reseller_setup_status(int(reseller_id))
    return bool(status.get("ready")), status


def _is_ar(lang: str) -> bool:
    return str(lang or "").lower().startswith("ar")


def _txt(lang: str, ar: str, en: str) -> str:
    return ar if _is_ar(lang) else en


def _ready_mark(value: bool) -> str:
    return "✅" if bool(value) else "❌"


def _ready_word(lang: str, value: bool) -> str:
    if _is_ar(lang):
        return "جاهز" if bool(value) else "ناقص"
    return "Ready" if bool(value) else "Needs setup"


def _dashboard_next_step(
    lang: str,
    *,
    ready: bool,
    setup: dict,
    enabled_methods: int,
    configured_methods: int,
    support_ready: int,
    support_total: int,
    pending_recharge: int,
) -> str:
    payment_methods_ready = bool(setup.get("payment_methods_ready"))
    payment_routing_ok = bool(setup.get("payment_routing_ok"))
    if _is_ar(lang):
        if not enabled_methods:
            return "فعّل وسيلة دفع من الإعدادات."
        if not payment_methods_ready:
            return "اكتب رقم أو عنوان محفظة لوسيلة دفع واحدة على الأقل."
        if configured_methods < enabled_methods:
            return "البوت قابل للاستخدام الآن. عطّل أو أكمل وسائل الدفع الزائدة لاحقًا."
        if not payment_routing_ok:
            return "طلبات الدفع ستصلك على الرسائل الخاصة. اربط توبيك لاحقًا إذا أردت تنظيمها في غروب."
        if support_ready < support_total:
            return "إعدادات الدعم اختيارية ويمكن إكمالها لاحقًا."
        if pending_recharge > 0:
            return "راجع طلبات الشحن المعلقة."
        if ready:
            return "البوت جاهز."
        return "أكمل الإعدادات الناقصة قبل نشر البوت."

    if not enabled_methods:
        return "Enable at least one payment method in Settings."
    if not payment_methods_ready:
        return "Set a real number or wallet for at least one payment method."
    if configured_methods < enabled_methods:
        return "The bot can run now. Disable or finish the extra enabled methods later."
    if not payment_routing_ok:
        return "Payment requests will arrive by direct message. Bind a topic later if you want group review."
    if support_ready < support_total:
        return "Support topics are optional and can be finished later."
    if pending_recharge > 0:
        return "Review pending recharge requests."
    if ready:
        return "Your bot is ready."
    return "Finish the missing setup before publishing this bot."


def _reseller_dashboard_kb(lang: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=_txt(lang, "🔄 تحديث لوحة التحكم", "🔄 Refresh Control Center"), callback_data="rsmenu:dashboard")],
            [types.InlineKeyboardButton(text=_txt(lang, "⚙️ إعداد التشغيل", "⚙️ Setup"), callback_data="rsmenu:settings")],
            [types.InlineKeyboardButton(text=_txt(lang, "⬅️ رجوع لقائمة الريسيلر", "⬅️ Back to Reseller Menu"), callback_data="rsmenu:menu")],
        ]
    )


def _reseller_stats_kb(lang: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=_txt(lang, "🔄 تحديث التقرير", "🔄 Refresh Report"), callback_data="rsmenu:stats")],
            [types.InlineKeyboardButton(text=_txt(lang, "⬅️ رجوع للوحة التحكم", "⬅️ Back to Control Center"), callback_data="rsmenu:dashboard")],
        ]
    )


async def _guard_reseller_setup(callback: types.CallbackQuery, *, allow_settings: bool = False) -> bool:
    if not callback.message:
        return False
    lang = await _reseller_lang(callback.from_user.id)
    ready, status = await _reseller_setup_ready(callback.from_user.id)
    if ready:
        return True
    if allow_settings:
        return True
    await callback.answer(t(lang, "reseller_setup_blocked_alert"), show_alert=True)
    await callback.message.answer(render_reseller_setup_notice(lang, status))
    return False


async def _hide_reply_keyboard(bot, chat_id: int, lang: str) -> None:
    try:
        sent = await bot.send_message(
            chat_id=int(chat_id),
            text=t(lang, "keyboard_cleanup_placeholder"),
            reply_markup=types.ReplyKeyboardRemove(),
        )
        try:
            await bot.delete_message(chat_id=int(chat_id), message_id=int(sent.message_id))
        except Exception:
            pass
    except Exception:
        pass


async def _render_reseller_balance_text(reseller_id: int, bot_id: int, lang: str) -> str:
    main_balance = await get_reseller_wallet_balance(int(reseller_id), wallet_type="main")
    earnings_balance = await get_reseller_wallet_balance(int(reseller_id), wallet_type="earnings")
    subscription = await get_bot_subscription(int(bot_id))
    is_ar = str(lang or "").lower().startswith("ar")
    header = "رصيدك في البوت الرئيسي" if is_ar else "Your Main Bot balance"
    profit_label = "أرباح خدماتك الخاصة" if is_ar else "Custom-services profit"
    note = (
        "يتم سحب الاشتراك الشهري من هذا الرصيد داخل البوت المركزي."
        if is_ar
        else "Bot subscription is charged from this balance inside the main bot."
    )
    return (
        f"{header}: {format_usd(main_balance)}\n"
        f"{profit_label}: {format_usd(earnings_balance)}\n"
        f"{note}\n\n"
        + "\n".join(subscription_summary_lines(lang, subscription))
    )


async def _send_reseller_balance(message: types.Message, reseller_id: int, lang: str) -> None:
    bot_id = (await message.bot.get_me()).id
    subscription = await get_bot_subscription(int(bot_id))
    await message.answer(
        await _render_reseller_balance_text(reseller_id, bot_id, lang),
        reply_markup=reseller_subscription_kb(subscription, lang),
    )


async def _sum_reseller_order_sales(reseller_id: int, *, since: datetime | None = None) -> float:
    orders = getattr(db, "orders", None)
    if orders is None or not hasattr(orders, "aggregate"):
        return 0.0
    match: dict = {
        "reseller_id": int(reseller_id),
        "status": {"$in": ["paid", "success", "done", "completed"]},
    }
    if since is not None:
        match["created_at"] = {"$gte": since}
    cursor = orders.aggregate(
        [
            {"$match": match},
            {
                "$project": {
                    "amount": {
                        "$ifNull": [
                            "$retail_amount",
                            {"$ifNull": ["$selling_price", 0]},
                        ]
                    }
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]
    )
    rows = await cursor.to_list(length=1)
    return float((rows[0] if rows else {}).get("total") or 0.0)


async def _sum_reseller_profit_ledger(reseller_id: int, *, since: datetime | None = None) -> float:
    ledger = getattr(db, "ledger_entries", None)
    if ledger is None or not hasattr(ledger, "aggregate"):
        return 0.0
    match: dict = {
        "owner_type": "reseller",
        "owner_id": int(reseller_id),
        "reseller_id": int(reseller_id),
        "wallet_type": "reseller_earnings",
    }
    if since is not None:
        match["created_at"] = {"$gte": since}
    cursor = ledger.aggregate(
        [
            {"$match": match},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]
    )
    rows = await cursor.to_list(length=1)
    return float((rows[0] if rows else {}).get("total") or 0.0)


async def _build_reseller_stats_text(reseller_id: int, bot_id: int | None = None, lang: str = "en") -> str:
    rid = int(reseller_id)
    lang = lang or "en"
    is_ar = _is_ar(lang)
    main_balance = await get_reseller_wallet_balance(rid, wallet_type="main")
    earnings_balance = await get_reseller_wallet_balance(rid, wallet_type="earnings")
    pending_recharge = await db.recharge_requests.count_documents({"reseller_id": rid, "status": "pending"})
    need_more_proof = await db.recharge_requests.count_documents({"reseller_id": rid, "status": "need_more_proof"})
    linked_users = await db.user_reseller_links.count_documents({"reseller_id": rid})
    active_bots = await db.bots.count_documents({"owner_id": rid, "active": True})
    now = datetime.now(UTC)
    day_start = now - timedelta(days=1)
    month_start = now - timedelta(days=30)
    paid_statuses = {"$in": ["paid", "success", "done", "completed"]}
    sales_24h_count = await db.orders.count_documents({"reseller_id": rid, "status": paid_statuses, "created_at": {"$gte": day_start}})
    sales_30d_count = await db.orders.count_documents({"reseller_id": rid, "status": paid_statuses, "created_at": {"$gte": month_start}})
    sales_24h_amount = await _sum_reseller_order_sales(rid, since=day_start)
    sales_30d_amount = await _sum_reseller_order_sales(rid, since=month_start)
    profit_24h = await _sum_reseller_profit_ledger(rid, since=day_start)
    profit_30d = await _sum_reseller_profit_ledger(rid, since=month_start)
    methods = await get_payment_methods(rid)
    rate = await get_exchange_rate(rid)
    resolved_bot_id = int(bot_id or 0)
    if resolved_bot_id <= 0:
        subscription = {}
    else:
        subscription = await get_bot_subscription(resolved_bot_id)

    subscription_lines = "\n".join(subscription_summary_lines(lang, subscription))
    if is_ar:
        return (
            "📈 المبيعات والأرباح\n\n"
            f"• معرّف الريسيلر: {rid}\n"
            f"• البوتات الفعالة: {active_bots}\n"
            f"• الزبائن المرتبطون: {linked_users}\n"
            f"• رصيد البوت الرئيسي: {format_usd(main_balance)}\n"
            f"• محفظة أرباح الكتالوج: {format_usd(earnings_balance)}\n"
            f"• مبيعات آخر 24 ساعة: {sales_24h_count} طلب | {format_usd(sales_24h_amount)}\n"
            f"• أرباح آخر 24 ساعة: {format_usd(profit_24h)}\n"
            f"• مبيعات آخر 30 يوم: {sales_30d_count} طلب | {format_usd(sales_30d_amount)}\n"
            f"• أرباح آخر 30 يوم: {format_usd(profit_30d)}\n"
            f"{subscription_lines}\n"
            "استخدام محفظة الأرباح: أرباح العناصر التي تضيفها في كتالوج بوتك\n"
            f"سعر الصرف: 1 💲 = {rate:.2f} محلي\n"
            f"وسائل الدفع المضبوطة: {len(methods)}\n"
            f"طلبات الشحن المعلقة: {pending_recharge}\n"
            f"طلبات تحتاج إثبات إضافي: {need_more_proof}"
        )

    return (
        "📈 Sales & Profit\n\n"
        f"Reseller ID: {rid}\n"
        f"Active bots: {active_bots}\n"
        f"Linked users: {linked_users}\n"
        f"Main Bot balance: {format_usd(main_balance)}\n"
        f"Catalog-profit wallet: {format_usd(earnings_balance)}\n"
        f"Sales last 24h: {sales_24h_count} orders | {format_usd(sales_24h_amount)}\n"
        f"Profit last 24h: {format_usd(profit_24h)}\n"
        f"Sales last 30d: {sales_30d_count} orders | {format_usd(sales_30d_amount)}\n"
        f"Profit last 30d: {format_usd(profit_30d)}\n"
        f"{subscription_lines}\n"
        "Catalog-profit wallet use: profit from your own items\n"
        f"Exchange rate: 1 💲 = {rate:.2f} local\n"
        f"Payment methods configured: {len(methods)}\n"
        f"Pending recharge requests: {pending_recharge}\n"
        f"Need-more-proof requests: {need_more_proof}"
    )


async def _build_reseller_dashboard_text(reseller_id: int, bot_id: int, lang: str | None = None) -> str:
    rid = int(reseller_id)
    lang = lang or await _reseller_lang(rid)
    is_ar = _is_ar(lang)
    main_balance = await get_reseller_wallet_balance(rid, wallet_type="main")
    pending_recharge = await db.recharge_requests.count_documents({"reseller_id": rid, "status": "pending"})
    methods = await get_payment_methods(rid)
    enabled_methods = sum(1 for item in methods if bool(item.get("enabled", True)))
    ready, setup = await _reseller_setup_ready(rid)
    subscription = await get_bot_subscription(int(bot_id))
    support_routes = await get_all_support_routing(rid)
    support_total = len(_SUPPORT_TOPIC_CATEGORIES)
    support_ready = sum(1 for cat, _title in _SUPPORT_TOPIC_CATEGORIES if (support_routes.get(cat) or {}).get("chat_id"))
    sub_status = subscription_status_label(lang, str(subscription.get("status") or ""))
    sub_end = (
        subscription.get("trial_ends_at")
        if str(subscription.get("status") or "").strip().lower() == "trial_active"
        else subscription.get("subscription_ends_at")
    )
    configured_methods = int(setup.get("configured_methods_count") or 0)
    payment_line = f"{configured_methods}/{enabled_methods}" if enabled_methods else "0/0"
    support_line = f"{support_ready}/{support_total}"
    next_step = _dashboard_next_step(
        lang,
        ready=ready,
        setup=setup,
        enabled_methods=enabled_methods,
        configured_methods=configured_methods,
        support_ready=support_ready,
        support_total=support_total,
        pending_recharge=pending_recharge,
    )

    if is_ar:
        recharge_line = f"{pending_recharge} معلقة" if pending_recharge else "لا يوجد طلبات معلقة"
        payment_route_line = (
            f"{_ready_mark(True)} رسائل خاصة"
            if not setup.get("payment_routing_ok")
            else f"{_ready_mark(True)} توبيك/غروب"
        )
        return (
            "📊 لوحة التحكم\n\n"
            f"• حالة البوت: {_ready_mark(ready)} {_ready_word(lang, ready)}\n"
            f"• الاشتراك: {sub_status}\n"
            f"• ينتهي: {format_subscription_dt(sub_end)}\n"
            f"• رصيد البوت الرئيسي: {format_usd(main_balance)}\n"
            f"• وسائل الدفع: {payment_line} جاهزة\n"
            f"• استلام طلبات الدفع: {payment_route_line}\n"
            f"• دعم الزبائن: {support_line} جاهز (اختياري)\n"
            f"• طلبات الشحن: {recharge_line}\n\n"
            f"المطلوب الآن: {next_step}"
        )

    recharge_line = f"{pending_recharge} pending" if pending_recharge else "none pending"
    payment_route_line = "✅ Direct messages" if not setup.get("payment_routing_ok") else "✅ Topic/group"
    return (
        "📊 Control Center\n\n"
        f"• Bot status: {_ready_mark(ready)} {_ready_word(lang, ready)}\n"
        f"• Subscription: {sub_status}\n"
        f"• Ends at: {format_subscription_dt(sub_end)}\n\n"
        f"• Main Bot balance: {format_usd(main_balance)}\n"
        f"• Payment methods: {payment_line} ready\n"
        f"• Payment request delivery: {payment_route_line}\n"
        f"• Customer support: {support_line} ready (optional)\n"
        f"• Recharge requests: {recharge_line}\n\n"
        f"Next: {next_step}"
    )


async def _send_recharge_requests_list(message: types.Message, reseller_id: int) -> None:
    requests = await get_recharge_requests_for_reseller(int(reseller_id))
    if not requests:
        await message.answer("No pending recharge requests.")
        return

    for req in requests:
        user = await get_user(req["user_id"])
        username = user.get("username", "") if user else str(req["user_id"])
        details = req.get("details") or {}
        paid_amount = float(details.get("paid_amount", 0))
        paid_currency = str(details.get("paid_currency", "USD"))
        text = (
            f"Recharge request from @{username}\n"
            f"Method: {req['method']}\n"
            f"Paid: {paid_amount:.2f} {paid_currency}\n"
            f"Credits: {float(req.get('amount', 0)):.4f}\n"
            f"Status: {req['status']}"
        )
        kb = user_recharge_review_kb(req["_id"])
        if req.get("proof_file_id"):
            await message.answer_photo(req["proof_file_id"], caption=text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)


@router.callback_query(lambda c: c.data == "rsmenu:balance")
async def reseller_menu_balance(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    if not await _guard_reseller_setup(callback):
        return
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await _hide_reply_keyboard(callback.bot, callback.message.chat.id, lang)
        await _send_reseller_balance(callback.message, callback.from_user.id, lang)


@router.callback_query(lambda c: c.data and c.data.startswith("rs_sub:plan:"))
async def reseller_subscription_plan_set(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    if not callback.message:
        return await callback.answer()
    raw = (callback.data or "").split(":")[-1]
    try:
        months = int(raw)
    except Exception:
        return await callback.answer("Invalid plan", show_alert=True)
    bot_id = (await callback.bot.get_me()).id
    subscription = await set_bot_subscription_plan(int(bot_id), months=months)
    if not subscription:
        return await callback.answer("Plan update failed", show_alert=True)
    lang = await _reseller_lang(callback.from_user.id)
    await callback.message.edit_text(
        await _render_reseller_balance_text(callback.from_user.id, bot_id, lang),
        reply_markup=reseller_subscription_kb(subscription, lang),
    )
    await callback.answer("Subscription plan updated")


@router.callback_query(lambda c: c.data == "rs_sub:activate")
async def reseller_subscription_activate(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    if not callback.message:
        return await callback.answer()
    bot_id = (await callback.bot.get_me()).id
    before = await get_bot_subscription(int(bot_id))
    subscription = await sync_bot_subscription(int(bot_id), collect_due=True)
    lang = await _reseller_lang(callback.from_user.id)
    await callback.message.edit_text(
        await _render_reseller_balance_text(callback.from_user.id, bot_id, lang),
        reply_markup=reseller_subscription_kb(subscription, lang),
    )
    before_status = str(before.get("status") or "").strip().lower()
    after_status = str(subscription.get("status") or "").strip().lower()
    if after_status != before_status and after_status in {"trial_active", "active"}:
        text = "تم تفعيل الاشتراك." if str(lang).lower().startswith("ar") else "Subscription activated."
        return await callback.answer(text, show_alert=True)
    if after_status in {"payment_required", "suspended"}:
        text = (
            "الرصيد غير كافٍ. افتح البوت الرئيسي واشحن رصيدك ثم اضغط تفعيل."
            if str(lang).lower().startswith("ar")
            else "Insufficient balance. Open the Main Bot, top up, then press Activate."
        )
        return await callback.answer(text, show_alert=True)
    await callback.answer("Subscription checked")


@router.callback_query(lambda c: c.data == "rsmenu:dashboard")
async def reseller_menu_dashboard(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await _hide_reply_keyboard(callback.bot, callback.message.chat.id, lang)
        bot_id = (await callback.bot.get_me()).id
        await _replace_inline_message(
            callback.message,
            await _build_reseller_dashboard_text(callback.from_user.id, bot_id, lang),
            reply_markup=_reseller_dashboard_kb(lang),
        )


@router.callback_query(lambda c: c.data == "rsmenu:menu")
async def reseller_menu_root(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await _hide_reply_keyboard(callback.bot, callback.message.chat.id, lang)
        await callback.message.answer(t(lang, "reseller_menu_title"), reply_markup=reseller_main_menu(lang))


@router.callback_query(lambda c: c.data == "rsmenu:main_bot_services")
async def reseller_menu_main_bot_services(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await _hide_reply_keyboard(callback.bot, callback.message.chat.id, lang)
        await send_main_bot_message(callback.message, lang=lang, back_callback="rsmenu:menu")


@router.callback_query(lambda c: c.data == "rsmenu:broadcast")
async def reseller_menu_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.clear()
    ok, _channel, error_text = await _broadcast_channel_status(callback.bot)
    if not ok:
        return await callback.answer(error_text, show_alert=True)
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await _hide_reply_keyboard(callback.bot, callback.message.chat.id, lang)
        await _replace_inline_message(
            callback.message,
            _txt(
                lang,
                "📣 الإذاعة\n\nهذه الرسالة ستُنشر في قناة هذا البوت الحالية.\nاختر نوع الإرسال، وبعدها ستراجع المحتوى قبل النشر.",
                "📣 Broadcast\n\nThis post will be published to this bot's current channel.\nChoose a content type, then confirm before publishing.",
            ),
            reply_markup=_reseller_broadcast_kb(lang),
        )


@router.callback_query(lambda c: c.data in {"rs_broadcast:text", "rs_broadcast:photo", "rs_broadcast:video", "rs_broadcast:document", "rs_broadcast:copy"})
async def reseller_broadcast_payload_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    kind = str(callback.data or "").split(":")[-1]
    await state.set_state(ResellerBroadcastFSM.waiting_payload)
    await state.update_data(rs_broadcast_kind=kind)
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        prompt_message = await _replace_inline_message(
            callback.message,
            _broadcast_prompt_text(lang, kind),
            reply_markup=_reseller_broadcast_wait_kb(lang),
        )
        if prompt_message:
            prompt_chat = getattr(prompt_message, "chat", None) or getattr(callback.message, "chat", None)
            prompt_message_id = int(getattr(prompt_message, "message_id", 0) or 0)
            prompt_chat_id = int(getattr(prompt_chat, "id", 0) or 0)
            if prompt_chat_id <= 0 or prompt_message_id <= 0:
                return
            await state.update_data(
                rs_broadcast_prompt_chat_id=prompt_chat_id,
                rs_broadcast_prompt_message_id=prompt_message_id,
            )


@router.callback_query(lambda c: c.data in {"rs_broadcast:restart", "rs_broadcast:cancel"})
async def reseller_broadcast_restart_or_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.clear()
    lang = await _reseller_lang(callback.from_user.id)
    await callback.answer(_txt(lang, "تم الإلغاء", "Canceled") if callback.data == "rs_broadcast:cancel" else None)
    if not callback.message:
        return
    if callback.data == "rs_broadcast:cancel":
        await _replace_inline_message(
            callback.message,
            _txt(lang, "تم إلغاء الإذاعة.", "Broadcast canceled."),
            reply_markup=reseller_main_menu(lang),
        )
        return
    await _replace_inline_message(
        callback.message,
        _txt(lang, "اختر نوع الإذاعة من جديد.", "Choose the broadcast type again."),
        reply_markup=_reseller_broadcast_kb(lang),
    )


@router.callback_query(lambda c: c.data in {"rs_broadcast:send", "rs_broadcast:silent", "rs_broadcast:pin", "rs_broadcast:protect"})
async def reseller_broadcast_confirm_send(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    data = await state.get_data()
    source_chat_id = int(data.get("rs_broadcast_source_chat_id") or 0)
    source_message_id = int(data.get("rs_broadcast_source_message_id") or 0)
    if source_chat_id == 0 or source_message_id <= 0:
        return await callback.answer("Broadcast draft expired. Start again.", show_alert=True)
    mode = str(callback.data or "").split(":")[-1]
    ok, result_text = await _send_broadcast_copy(
        callback.bot,
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        fallback_payload=data.get("rs_broadcast_fallback_payload"),
        silent=(mode == "silent"),
        pin=(mode == "pin"),
        protect=(mode == "protect"),
    )
    await state.clear()
    lang = await _reseller_lang(callback.from_user.id)
    if callback.message:
        await _replace_inline_message(callback.message, result_text, reply_markup=reseller_main_menu(lang))
    await callback.answer(_txt(lang, "تم الإرسال", "Sent") if ok else _txt(lang, "فشل الإرسال", "Send failed"), show_alert=not ok)


@router.callback_query(lambda c: c.data == "rsmenu:recharge_requests")
async def reseller_menu_recharge_requests(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    if not await _guard_reseller_setup(callback):
        return
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await _hide_reply_keyboard(callback.bot, callback.message.chat.id, lang)
        await _send_recharge_requests_list(callback.message, callback.from_user.id)


@router.callback_query(lambda c: c.data == "rsmenu:adjust_user_balance")
async def reseller_menu_adjust_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    if not await _guard_reseller_setup(callback):
        return
    await state.set_state(ResellerAdjustFSM.waiting_for_target)
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await _hide_reply_keyboard(callback.bot, callback.message.chat.id, lang)
        await callback.message.answer("Send target username (@username) or user id.")


@router.callback_query(lambda c: c.data == "rsmenu:settings")
async def reseller_menu_settings(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.clear()
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await _hide_reply_keyboard(callback.bot, callback.message.chat.id, lang)
        await callback.message.edit_text(
            await _settings_overview_text(callback.from_user.id, lang),
            reply_markup=await _settings_main_kb(callback.from_user.id, lang),
        )


@router.callback_query(lambda c: c.data == "rsmenu:stats")
async def reseller_menu_stats(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    if not await _guard_reseller_setup(callback):
        return
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await _hide_reply_keyboard(callback.bot, callback.message.chat.id, lang)
        await _replace_inline_message(
            callback.message,
            await _build_reseller_stats_text(callback.from_user.id, (await callback.bot.get_me()).id, lang),
            reply_markup=_reseller_stats_kb(lang),
        )


@router.callback_query(lambda c: c.data == "rsmenu:core_topup")
async def reseller_core_topup_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.clear()
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await send_main_bot_message(callback.message, lang=lang, back_callback="rsmenu:menu")


@router.callback_query(lambda c: c.data == "rs_core_topup:cancel")
async def reseller_core_topup_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.answer("Canceled.", reply_markup=reseller_main_menu(lang))
    await callback.answer("Canceled")


@router.callback_query(lambda c: c.data and c.data.startswith("rs_core_topup:method:"))
async def reseller_core_topup_method(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    code = (callback.data or "").split(":", 2)[2]
    method = await _find_owner_payment_method(code)
    if not method:
        return await callback.answer("Method not found", show_alert=True)

    await state.set_state(ResellerCoreTopupFSM.waiting_amount)
    await state.update_data(rs_core_topup_method=method)

    if callback.message:
        await callback.message.answer(
            _format_owner_topup_method_details(method) + "\n\nSend paid amount now, or /cancel.",
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(ResellerCoreTopupFSM.waiting_amount)
async def reseller_core_topup_amount(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")

    raw = (message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel"}:
        await state.clear()
        lang = await _reseller_lang(message.from_user.id)
        return await message.answer("Canceled.", reply_markup=reseller_main_menu(lang))

    try:
        paid_amount = float(raw)
    except Exception:
        return await message.answer("Invalid amount. Send numeric value only.")
    if paid_amount <= 0:
        return await message.answer("Amount must be greater than zero.")

    data = await state.get_data()
    method = data.get("rs_core_topup_method") or {}
    per_credit = float(method.get("per_credit", 1.0) or 1.0)
    if per_credit <= 0:
        per_credit = 1.0
    credits = paid_amount / per_credit

    await state.update_data(rs_core_paid_amount=paid_amount, rs_core_credits=round(credits, 6))
    await state.set_state(ResellerCoreTopupFSM.waiting_proof)
    await message.answer(
        "Send payment proof screenshot now.\n"
        f"Expected credits (by selected method rate): {credits:.4f}\n"
        "Or /cancel"
    )


@router.message(ResellerCoreTopupFSM.waiting_proof, lambda msg: bool(msg.photo))
async def reseller_core_topup_proof(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")

    data = await state.get_data()
    method = data.get("rs_core_topup_method") or {}
    paid_amount = float(data.get("rs_core_paid_amount") or 0)
    credits = float(data.get("rs_core_credits") or 0)
    if not method or paid_amount <= 0 or credits <= 0:
        await state.clear()
        return await message.answer("Topup context lost. Please start again.")

    req = await create_recharge_request(
        user_id=int(message.from_user.id),
        method=str(method.get("title") or method.get("code") or "owner_payment"),
        amount=credits,
        proof_file_id=message.photo[-1].file_id,
        reseller_id=int(message.from_user.id),
        details={
            "scope": "reseller_core_wallet",
            "method_code": method.get("code"),
            "paid_amount": paid_amount,
            "paid_currency": str(method.get("currency", "USD")).upper(),
            "per_credit": float(method.get("per_credit", 1.0)),
            "credits": credits,
            "source_bot_id": int((await message.bot.get_me()).id),
        },
        wallet_type="reseller_main",
    )

    reseller_doc = await get_user(message.from_user.id)
    delivered, route, msg_id, chat_id, thread_id = await _notify_owner_reseller_topup_request(message, req, reseller_doc)
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

    lang = await _reseller_lang(message.from_user.id)
    if delivered:
        await message.answer(
            "Topup request sent to owner for review.\n"
            f"Expected credits: {credits:.4f}",
            reply_markup=reseller_main_menu(lang),
        )
    else:
        await message.answer(
            "Topup request saved, but owner delivery failed.\n"
            "Owner can still review it from Owner Panel -> Finance -> Reseller Topup Requests.",
            reply_markup=reseller_main_menu(lang),
        )


@router.message(ResellerCoreTopupFSM.waiting_proof)
async def reseller_core_topup_proof_text(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip().lower()
    if raw in {"/cancel", "cancel"}:
        await state.clear()
        lang = await _reseller_lang(message.from_user.id)
        return await message.answer("Canceled.", reply_markup=reseller_main_menu(lang))
    return await message.answer("Send screenshot proof only, or /cancel.")


@router.message(ResellerBroadcastFSM.waiting_text)
@router.message(ResellerBroadcastFSM.waiting_payload)
async def reseller_broadcast_payload_submit(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")
    raw = (message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel"}:
        await state.clear()
        lang = await _reseller_lang(message.from_user.id)
        return await message.answer("Canceled.", reply_markup=reseller_main_menu(lang))

    data = await state.get_data()
    kind = str(data.get("rs_broadcast_kind") or "text")
    lang = await _reseller_lang(message.from_user.id)
    if not _message_matches_broadcast_kind(message, kind):
        return await message.answer(_broadcast_prompt_text(lang, kind), reply_markup=_reseller_broadcast_wait_kb(lang))

    await state.update_data(
        rs_broadcast_source_chat_id=int(message.chat.id),
        rs_broadcast_source_message_id=int(message.message_id),
        rs_broadcast_fallback_payload=_broadcast_fallback_payload(message, kind),
    )
    await state.set_state(ResellerBroadcastFSM.waiting_confirm)
    confirm_text = _txt(
        lang,
        f"تم تجهيز الإذاعة للمراجعة.\n{_broadcast_payload_summary(message, lang, kind)}\n\nراجع الرسالة التي أرسلتها فوق، ثم اختر طريقة النشر.",
        f"Broadcast draft is ready.\n{_broadcast_payload_summary(message, lang, kind)}\n\nReview the message you sent above, then choose how to publish.",
    )
    prompt_chat_id = int(data.get("rs_broadcast_prompt_chat_id") or 0)
    prompt_message_id = int(data.get("rs_broadcast_prompt_message_id") or 0)
    edited = await _edit_bot_message_text(
        message.bot,
        chat_id=prompt_chat_id,
        message_id=prompt_message_id,
        text=confirm_text,
        reply_markup=_reseller_broadcast_confirm_kb(lang),
    )
    if not edited:
        await message.answer(confirm_text, reply_markup=_reseller_broadcast_confirm_kb(lang))


async def _settings_main_kb(reseller_id: int, lang: str = "en") -> types.InlineKeyboardMarkup:
    pay_route = await get_recharge_routing(int(reseller_id))
    ex_route = await get_exchange_routing(int(reseller_id))
    support_routes = await get_all_support_routing(int(reseller_id))
    methods = await get_payment_methods(int(reseller_id))
    enabled_count = sum(1 for m in methods if bool(m.get("enabled", True)))
    total_count = len(methods)
    rate = await get_exchange_rate(int(reseller_id))
    pay_ok = bool(pay_route and pay_route.get("chat_id"))
    ex_ok = bool(ex_route and ex_route.get("chat_id"))
    support_ok = all(bool((support_routes.get(cat) or {}).get("chat_id")) for cat, _ in _SUPPORT_TOPIC_CATEGORIES)
    pay_label = _txt(lang, f"استلام الدفع {'✅ توبيك' if pay_ok else 'رسائل خاصة'}", f"Payment Delivery {'✅ Topic' if pay_ok else 'Direct Messages'}")
    ex_label = _txt(lang, f"تنبيهات الصرف {'✅ توبيك' if ex_ok else 'رسائل خاصة'}", f"Exchange Alerts {'✅ Topic' if ex_ok else 'Direct Messages'}")
    support_label = _txt(lang, f"توبيكات الدعم {'✅' if support_ok else 'اختياري'}", f"Support Topics {'✅' if support_ok else 'Optional'}")
    rate_label = _txt(lang, f"سعر الصرف: {rate:.2f}", f"Exchange Rate: {rate:.2f}")
    ready_count = sum(
        1
        for m in methods
        if bool(m.get("enabled", True)) and not _payment_method_needs_target(m)
    )
    methods_label = _txt(lang, f"وسائل الدفع ({ready_count}/{enabled_count} جاهزة)", f"Payment Methods ({ready_count}/{enabled_count} ready)")
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text=_txt(lang, "دليل سريع", "Quick Guide"), callback_data="rs:help"),
                types.InlineKeyboardButton(text=methods_label, callback_data="rs:methods"),
            ],
            [types.InlineKeyboardButton(text=_txt(lang, "إعداد توبيكات الدفع تلقائياً", "Auto Setup Payment Topics"), callback_data="rs:auto:topics")],
            [types.InlineKeyboardButton(text=support_label, callback_data="rs:auto:support_topics")],
            [types.InlineKeyboardButton(text=pay_label, callback_data="rs:bind:pay:link")],
            [types.InlineKeyboardButton(text=ex_label, callback_data="rs:bind:ex:link")],
            [types.InlineKeyboardButton(text=rate_label, callback_data="rs:rate")],
            [types.InlineKeyboardButton(text=_txt(lang, "⬅️ رجوع للوحة الريسيلر", "⬅️ Back to Reseller Menu"), callback_data="rs:close")],
        ]
    )


def _settings_help_kb(lang: str = "en") -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=_txt(lang, "⬅️ رجوع للإعداد", "⬅️ Back to Setup"), callback_data="rs:open")],
            [types.InlineKeyboardButton(text=_txt(lang, "⬅️ رجوع للوحة الريسيلر", "⬅️ Back to Reseller Menu"), callback_data="rs:close")],
        ]
    )


def _settings_wait_input_kb(lang: str = "en") -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=_txt(lang, "⬅️ رجوع للإعداد", "⬅️ Back to Setup"), callback_data="rs:open")],
        ]
    )


async def _settings_overview_text(reseller_id: int, lang: str = "en") -> str:
    pay_route = await get_recharge_routing(int(reseller_id))
    ex_route = await get_exchange_routing(int(reseller_id))
    support_routes = await get_all_support_routing(int(reseller_id))
    methods = await get_payment_methods(int(reseller_id))
    enabled_count = sum(1 for m in methods if bool(m.get("enabled", True)))
    ready_count = sum(
        1
        for m in methods
        if bool(m.get("enabled", True)) and not _payment_method_needs_target(m)
    )
    total_count = len(methods)
    rate = await get_exchange_rate(int(reseller_id))

    pay_status = _txt(lang, "✅ مربوط" if (pay_route and pay_route.get("chat_id")) else "رسائل خاصة", "✅ Bound" if (pay_route and pay_route.get("chat_id")) else "Direct messages")
    ex_status = _txt(lang, "✅ مربوط" if (ex_route and ex_route.get("chat_id")) else "رسائل خاصة", "✅ Bound" if (ex_route and ex_route.get("chat_id")) else "Direct messages")
    support_ready = sum(1 for cat, _ in _SUPPORT_TOPIC_CATEGORIES if (support_routes.get(cat) or {}).get("chat_id"))
    support_total = len(_SUPPORT_TOPIC_CATEGORIES)

    if _is_ar(lang):
        return (
            "⚙️ إعداد تشغيل البوت\n\n"
            "أقل شيء لتشغيل أول بوت: فعّل وسيلة دفع واحدة وضع رقمك الحقيقي أو عنوان محفظتك.\n"
            "الغروبات والتوبيكات اختيارية؛ إذا ما ربطتها ستصلك طلبات الشحن على الخاص.\n\n"
            f"• استلام طلبات الدفع: {pay_status}\n"
            f"• تنبيهات سعر الصرف: {ex_status}\n"
            f"• توبيكات الدعم: {support_ready}/{support_total} جاهزة (اختياري)\n"
            f"• سعر الصرف: {rate:.2f} محلي لكل 1 💲\n"
            f"• وسائل الدفع: {ready_count}/{enabled_count} جاهزة، {enabled_count}/{total_count} مفعّلة\n\n"
            "اختر الشيء الذي تريد تعديله:"
        )

    return (
        "⚙️ Bot Setup\n\n"
        "Minimum to start: one enabled payment method with your real number or wallet.\n"
        "Groups/topics are optional; without them, recharge requests go to your DM.\n\n"
        f"• Payment delivery: {pay_status}\n"
        f"• Exchange alerts: {ex_status}\n"
        f"• Support topics: {support_ready}/{support_total} ready (optional)\n"
        f"• Exchange rate: {rate:.2f} local per 1 💲\n"
        f"• Payment methods: {ready_count}/{enabled_count} ready, {enabled_count}/{total_count} enabled\n\n"
        "Choose what you want to update:"
    )


async def _bot_can_manage_topics(bot: Bot, chat_id: int) -> tuple[bool, str | None]:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id=chat_id, user_id=int(me.id))
    except Exception as exc:
        return False, f"failed_to_read_bot_member: {exc}"

    status = str(getattr(member, "status", "") or "").lower()
    if status not in {"administrator", "creator"}:
        return False, "bot_is_not_admin"

    can_manage_topics = getattr(member, "can_manage_topics", None)
    if can_manage_topics is False:
        return False, "missing_manage_topics_permission"
    return True, None


async def _create_forum_topic_safe(bot: Bot, chat_id: int, name: str) -> tuple[int | None, str | None]:
    try:
        topic = await bot.create_forum_topic(chat_id=chat_id, name=name)
        thread_id = int(getattr(topic, "message_thread_id", 0) or 0)
        if thread_id <= 0:
            return None, "invalid_thread_id"
        return thread_id, None
    except Exception as exc:
        return None, str(exc)


def _settings_methods_kb(methods: list[dict], lang: str = "en") -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = []
    for m in methods:
        code = str(m.get("code") or "")
        title = str(m.get("title") or code)
        status = "✅" if bool(m.get("enabled", True)) else "⛔"
        rows.append([types.InlineKeyboardButton(text=f"{status} {title} ({code})", callback_data=f"rs:method:{code}")])
    rows.append([types.InlineKeyboardButton(text=_txt(lang, "رجوع للإعداد", "Back to Setup"), callback_data="rs:open")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _payment_method_needs_target(method: dict) -> bool:
    raw = str(method.get("target") or "").strip()
    if not raw:
        return True
    upper = raw.upper()
    return upper.startswith("SET_") or "YOUR_" in upper


def _settings_method_kb(code: str, lang: str = "en") -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=_txt(lang, "استخدم هذه الوسيلة فقط", "Use This Method Only"), callback_data=f"rs:mset:only:{code}")],
            [types.InlineKeyboardButton(text=_txt(lang, "ضع رقم/محفظة الدفع", "Set Payment Number/Wallet"), callback_data=f"rs:mset:target:{code}")],
            [types.InlineKeyboardButton(text=_txt(lang, "تشغيل/إيقاف الوسيلة", "Turn Method ON/OFF"), callback_data=f"rs:mset:enabled:{code}")],
            [types.InlineKeyboardButton(text=_txt(lang, "عملة الوسيلة (USD/SYP)", "Set Currency (USD/SYP)"), callback_data=f"rs:mset:currency:{code}")],
            [types.InlineKeyboardButton(text=_txt(lang, "سعر كل كريدت", "Set Rate per Credit"), callback_data=f"rs:mset:rate:{code}")],
            [types.InlineKeyboardButton(text=_txt(lang, "اسم الوسيلة للزبون", "Set Display Name"), callback_data=f"rs:mset:title:{code}")],
            [types.InlineKeyboardButton(text=_txt(lang, "يوزر الدعم", "Set Support Username"), callback_data=f"rs:mset:support:{code}")],
            [types.InlineKeyboardButton(text=_txt(lang, "نص التعليمات", "Set Instructions Text"), callback_data=f"rs:mset:text:{code}")],
            [types.InlineKeyboardButton(text=_txt(lang, "رجوع لوسائل الدفع", "Back to Methods"), callback_data="rs:methods")],
            [types.InlineKeyboardButton(text=_txt(lang, "رجوع للإعداد", "Back to Setup"), callback_data="rs:open")],
        ]
    )


def _payment_setup_help_text(lang: str = "en") -> str:
    if _is_ar(lang):
        return (
            "دليل إعداد الريسيلر:\n\n"
            "الإعداد الأساسي لأول بوت:\n"
            "- تحتاج فقط وسيلة دفع واحدة عليها رقمك الحقيقي أو عنوان محفظتك.\n"
            "- يمكنك ترك الاستلام على الرسائل الخاصة؛ الغروب غير مطلوب لتشغيل أول بوت.\n"
            "- افتح وسائل الدفع، اختر الوسيلة، اضغط ضع رقم/محفظة الدفع، ثم أرسل الرقم أو العنوان.\n"
            "- اضغط استخدم هذه الوسيلة فقط إذا لا تريد ضبط كل الوسائل الافتراضية.\n\n"
            "الوضع المتقدم بالغروب اختياري:\n"
            "- فعّل Topics في الغروب الخاص قبل إضافة البوت.\n"
            "- أضف بوت الريسيلر Admin مع صلاحية Manage Topics.\n\n"
            "1) لاستلام طلبات الدفع:\n"
            "- انسخ رابط توبيك Payment Requests ثم استخدم زر استلام الدفع.\n\n"
            "2) لتنبيهات سعر الصرف:\n"
            "- انسخ رابط توبيك Exchange ثم استخدم زر تنبيهات الصرف.\n\n"
            "3) لسعر الصرف:\n"
            "- استخدم زر سعر الصرف. السعر مستقل لكل ريسيلر.\n\n"
            "4) لوسائل الدفع:\n"
            "- لكل وسيلة يمكنك ضبط الاسم، الرقم/المحفظة، الدعم، التعليمات، وسعر الكريدت."
        )
    return (
        "Reseller setup guide:\n\n"
        "Basic setup:\n"
        "- You only need one payment method with a real number or wallet.\n"
        "- You can receive payment requests by direct message; no group is required for a first bot.\n"
        "- Open Payment Methods, choose the method, tap Set Payment Number/Wallet, then paste your number/address.\n"
        "- Tap Use This Method Only if you want to avoid configuring every default method.\n\n"
        "Optional advanced group mode:\n"
        "- Enable Topics in your private group before adding the bot.\n"
        "- Add your reseller bot as Admin with all permissions, especially Manage Topics.\n\n"
        "1) For payment requests delivery:\n"
        "- Create a private group.\n"
        "- Enable Topics.\n"
        "- Create a topic named Payment Requests.\n"
        "- Open that topic, copy topic link, then use Reseller Settings > Bind Payment Topic (By Link).\n\n"
        "2) For exchange reminders:\n"
        "- Create/open your Exchange topic.\n"
        "- Copy topic link, then use Reseller Settings > Bind Exchange Topic (By Link).\n\n"
        "3) For exchange rate:\n"
        "- Use Reseller Settings > Set Exchange Rate.\n"
        "- Rate is stored per reseller account (each reseller has independent value).\n\n"
        "4) For payment methods:\n"
        "- Use Reseller Settings > Payment Methods.\n"
        "- For each method you can set: title, target address, support username, instructions, and per-credit rate."
    )


def _format_payment_methods_text(methods: list[dict], lang: str = "en") -> str:
    is_ar = _is_ar(lang)
    lines = [
        "وسائل الدفع\n" if is_ar else "Payment Methods\n",
        "أقل إعداد مطلوب: شغّل وسيلة واحدة وضع رقمك الحقيقي أو عنوان محفظتك بدل القيمة المؤقتة.\n" if is_ar else "Minimum setup: make one method ON and replace its placeholder target with your real payment number or wallet.\n",
    ]
    for m in methods:
        enabled = bool(m.get("enabled", True))
        if not enabled:
            status = "متوقفة" if is_ar else "OFF"
        elif _payment_method_needs_target(m):
            status = "تحتاج رقم/محفظة" if is_ar else "NEEDS NUMBER/WALLET"
        else:
            status = "جاهزة" if is_ar else "READY"
        lines.append(
            f"- {m.get('code')}: {m.get('title')} | "
            f"{('local' if str(m.get('currency', 'USD')).upper() == 'SYP' else '💲')} | "
            f"per_credit={float(m.get('per_credit', 1.0)):.4f} | {status}"
        )
    lines.append(
        "\nاختر وسيلة من الأسفل. لأول بوت اضبط وسيلة واحدة واضغط 'استخدم هذه الوسيلة فقط'."
        if is_ar
        else "\nSelect a method below. For a first bot, configure one method and use 'Use This Method Only'."
    )
    return "\n".join(lines)


def _format_payment_method_details(method: dict, lang: str = "en") -> str:
    is_ar = _is_ar(lang)
    rendered = str(method.get("instructions") or "")
    preview = render_method_instructions(method)
    if len(rendered) > 500:
        rendered = rendered[:500] + "..."
    if len(preview) > 700:
        preview = preview[:700] + "..."
    setup_state = _txt(lang, "جاهزة", "Ready") if bool(method.get("enabled", True)) and not _payment_method_needs_target(method) else _txt(lang, "تحتاج رقم/محفظة", "Needs number/wallet")
    if not bool(method.get("enabled", True)):
        setup_state = _txt(lang, "متوقفة", "Off")
    if is_ar:
        return (
            "تفاصيل وسيلة الدفع\n\n"
            f"الكود: {method.get('code')}\n"
            f"الاسم: {method.get('title')}\n"
            f"الحالة: {setup_state}\n"
            f"العملة: {('محلي' if str(method.get('currency', 'USD')).upper() == 'SYP' else '💲')}\n"
            f"مفعّلة: {bool(method.get('enabled', True))}\n"
            f"سعر كل كريدت: {float(method.get('per_credit', 1.0)):.4f}\n"
            f"الرقم/المحفظة: {method.get('target')}\n"
            f"الدعم: {method.get('support')}\n\n"
            f"نص التعليمات:\n{rendered}\n\n"
            f"المعاينة للزبون:\n{preview}"
        )
    return (
        "Payment Method Details\n\n"
        f"Code: {method.get('code')}\n"
        f"Title: {method.get('title')}\n"
        f"Setup: {setup_state}\n"
        f"Currency: {('local' if str(method.get('currency', 'USD')).upper() == 'SYP' else '💲')}\n"
        f"Enabled: {bool(method.get('enabled', True))}\n"
        f"Per Credit: {float(method.get('per_credit', 1.0)):.4f}\n"
        f"Target: {method.get('target')}\n"
        f"Support: {method.get('support')}\n\n"
        f"Text template:\n{rendered}\n\n"
        f"User preview:\n{preview}"
    )


def _parse_payment_currency(raw: str) -> str | None:
    value = str(raw or "").strip().lower()
    normalized = value.replace("$", "usd").replace("💲", "usd")
    if normalized in {"usd", "dollar", "dollars", "usdt"}:
        return "USD"
    if normalized in {"syp", "local", "lira", "ليرة", "ليره", "ل.س", "محلي", "محلية"}:
        return "SYP"
    return None


async def _find_payment_method(reseller_id: int, method_code: str) -> dict | None:
    methods = await get_payment_methods(reseller_id)
    for m in methods:
        if str(m.get("code")) == str(method_code):
            return m
    return None


def _owner_topup_methods_kb(methods: list[dict]) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = []
    for method in methods:
        code = str(method.get("code") or "")
        title = str(method.get("title") or code)
        rows.append(
            [types.InlineKeyboardButton(text=f"{title} ({code})", callback_data=f"rs_core_topup:method:{code}")]
        )
    rows.append([types.InlineKeyboardButton(text="Cancel", callback_data="rs_core_topup:cancel")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _owner_topup_review_kb(request_id) -> types.InlineKeyboardMarkup:
    return owner_reseller_topup_review_kb(request_id)


def _format_owner_topup_method_details(method: dict) -> str:
    raw_target = str(method.get("target") or "").strip()
    target_block = f"<code>{escape(raw_target or '-')}</code>"

    instructions = str(render_owner_method_instructions(method) or "")
    if raw_target:
        instructions = instructions.replace(raw_target, "").strip()

    return (
            "<b>Main Bot Balance Topup (Owner Payment)</b>\n\n"
        f"Method: <b>{escape(str(method.get('title') or '-'))}</b> ({escape(str(method.get('code') or '-'))})\n"
        f"Currency: <b>{escape('local' if str(method.get('currency', 'USD')).upper() == 'SYP' else '💲')}</b>\n"
        f"Per Credit: <b>{float(method.get('per_credit', 1.0)):.4f}</b>\n\n"
        "Payment target:\n"
        f"{target_block}\n\n"
        f"{escape(instructions)}"
    )


async def _find_owner_payment_method(method_code: str) -> dict | None:
    methods = await get_owner_payment_methods()
    for method in methods:
        if str(method.get("code")) == str(method_code) and bool(method.get("enabled", True)):
            return method
    return None


async def _owner_notifications_target() -> dict | None:
    doc = await db.system_settings.find_one({"_id": "owner_notifications"})
    if not doc:
        return None
    chat_id_raw = doc.get("chat_id")
    if chat_id_raw in (None, ""):
        return None
    try:
        chat_id = int(chat_id_raw)
    except Exception:
        return None
    thread_raw = doc.get("message_thread_id")
    thread_id: int | None = None
    if thread_raw not in (None, ""):
        try:
            thread_id = int(thread_raw)
        except Exception:
            thread_id = None
    return {
        "chat_id": chat_id,
        "message_thread_id": thread_id,
    }


async def _owner_reseller_topup_target() -> dict | None:
    doc = await db.system_settings.find_one({"_id": "owner_reseller_topups"})
    if not doc:
        return await _owner_notifications_target()
    chat_id_raw = doc.get("chat_id")
    if chat_id_raw in (None, ""):
        return await _owner_notifications_target()
    try:
        chat_id = int(chat_id_raw)
    except Exception:
        return await _owner_notifications_target()
    thread_raw = doc.get("message_thread_id")
    thread_id: int | None = None
    if thread_raw not in (None, ""):
        try:
            thread_id = int(thread_raw)
        except Exception:
            thread_id = None
    return {
        "chat_id": chat_id,
        "message_thread_id": thread_id,
    }


async def _notify_owner_reseller_topup_request(
    message: types.Message,
    req: dict,
    reseller_doc: dict | None,
) -> tuple[bool, str, int | None, int | None, int | None]:
    details = req.get("details") or {}
    paid_amount = float(details.get("paid_amount", 0))
    paid_currency = str(details.get("paid_currency", "USD")).upper()
    expected_credits = float(details.get("credits", req.get("amount", 0)))
    req_id = str(req.get("_id") or "-")
    reseller_id = int(req.get("reseller_id") or 0)
    username = str((reseller_doc or {}).get("username") or "").strip()
    uname = f"@{username}" if username else "-"
    full_name = " ".join(
        x for x in [message.from_user.first_name, message.from_user.last_name] if x
    ).strip() or "-"

    caption = (
            "Reseller Main Bot Balance Topup Request\n\n"
        f"Request ID: {req_id}\n"
        f"Reseller ID: {reseller_id}\n"
        f"Username: {uname}\n"
        f"Name: {full_name}\n"
        f"Method: {req.get('method')}\n"
        f"Paid: {paid_amount:.2f} {paid_currency}\n"
        f"Expected Credits: {expected_credits:.4f}\n"
        "Status: Pending owner review"
    )

    kwargs = {
        "reply_markup": _owner_topup_review_kb(req.get("_id")),
    }

    async def _send_to(chat_id: int, thread_id: int | None, route: str):
        send_kwargs = dict(kwargs)
        send_kwargs["chat_id"] = int(chat_id)
        if thread_id is not None:
            send_kwargs["message_thread_id"] = int(thread_id)
        if req.get("proof_file_id"):
            sent = await message.bot.send_photo(photo=req["proof_file_id"], caption=caption, **send_kwargs)
        else:
            sent = await message.bot.send_message(text=caption, **send_kwargs)
        return (
            True,
            route,
            int(getattr(sent, "message_id", 0) or 0),
            int(chat_id),
            int(thread_id) if thread_id is not None else None,
        )

    target = await _owner_reseller_topup_target()
    target_error: Exception | None = None
    if target:
        try:
            return await _send_to(int(target["chat_id"]), target.get("message_thread_id"), "owner_topic")
        except Exception as exc:
            target_error = exc

    # Fallback: deliver directly to owner DM from this reseller bot.
    # This keeps requests reachable even when owner topic binding points to a chat
    # where the reseller bot has no access.
    owner_error: Exception | None = None
    if int(OWNER_ID) > 0:
        try:
            return await _send_to(int(OWNER_ID), None, "owner_dm_fallback")
        except Exception as exc:
            owner_error = exc

    target_chat_id = int(target.get("chat_id")) if target else None
    target_thread_id = (
        int(target.get("message_thread_id"))
        if target and target.get("message_thread_id") is not None
        else None
    )
    if target_error and owner_error:
        return (
            False,
            f"owner_delivery_failed:{target_error};owner_dm_failed:{owner_error}",
            None,
            target_chat_id,
            target_thread_id,
        )
    if target_error:
        return False, f"owner_delivery_failed:{target_error}", None, target_chat_id, target_thread_id
    if owner_error:
        return False, f"owner_dm_failed:{owner_error}", None, int(OWNER_ID), None
    return False, "owner_target_not_bound", None, None, None


def _owner_reseller_topup_text(req: dict) -> str:
    return format_owner_reseller_topup_text(req, include_approved=True)


async def _edit_owner_topup_card_message(bot, req: dict) -> None:
    delivery = req.get("delivery") or {}
    chat_id = delivery.get("chat_id")
    message_id = delivery.get("message_id")
    if chat_id is None or message_id is None:
        return

    text = _owner_reseller_topup_text(req)
    try:
        if req.get("proof_file_id"):
            await bot.edit_message_caption(
                chat_id=int(chat_id),
                message_id=int(message_id),
                caption=text,
                reply_markup=None,
            )
        else:
            await bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(message_id),
                text=text,
                reply_markup=None,
            )
    except Exception:
        return


def _is_owner_actor(user_id: int) -> bool:
    return int(user_id) == int(OWNER_ID)


async def _notify_reseller_with_fallback(bot, reseller_id: int, text: str) -> bool:
    rid = int(reseller_id)
    try:
        await bot.send_message(rid, text)
        return True
    except Exception:
        pass

    row = await db.bots.find_one({"owner_id": rid, "active": True}, {"token": 1})
    token = str((row or {}).get("token") or "").strip()
    if not token:
        return False

    tmp_bot = Bot(token=token)
    try:
        await tmp_bot.send_message(rid, text)
        return True
    except Exception:
        return False
    finally:
        try:
            await tmp_bot.session.close()
        except Exception:
            pass


async def _apply_owner_reseller_topup_decision(bot, owner_id: int, request_id: str, decision: str, approved_amount: float | None = None):
    if not _is_owner_actor(owner_id):
        return False, "No permission", None

    try:
        oid = ObjectId(str(request_id))
    except Exception:
        return False, "Invalid request id", None

    req = await db.recharge_requests.find_one({"_id": oid})
    if not req:
        return False, "Request not found", None

    wallet_type = str(req.get("wallet_type") or "").lower()
    main_bot_user_topup = wallet_type == "user" and str(((req.get("details") or {}).get("wallet_scope")) or "").strip().lower() == "main_bot"
    reseller_main_topup = wallet_type in {"reseller_main", "main", "reseller"}
    if not reseller_main_topup and not main_bot_user_topup:
        return False, "This request is not reviewable from the owner recharge flow.", req

    if decision not in {"accepted", "rejected"}:
        return False, "Invalid decision", req

    updated = await update_recharge_request(
        oid,
        decision,
        reviewed_by=int(owner_id),
        decision_note="owner_reseller_topup_review",
        approved_amount=approved_amount,
        expected_reseller_id=int(req.get("reseller_id") or 0),
    )
    if not updated:
        return False, "Request already handled or missing", req

    req = await db.recharge_requests.find_one({"_id": oid})
    if not req:
        return False, "Request not found after update", None

    if main_bot_user_topup:
        if decision == "accepted" and req.get("status") == "accepted":
            user_id = int(req.get("user_id") or 0)
            wallet_scope_id = int(req.get("reseller_id") or user_id)
            amount_done = float(req.get("approved_amount") or req.get("amount") or 0)
            new_bal = await get_user_wallet_balance(user_id, wallet_scope_id)
            try:
                await _notify_recharge_request_user(
                    req,
                    bot,
                    "Your balance was topped up.\n"
                    f"Added: {amount_done:.4f} credits\n"
                    f"Current balance: {format_usd(new_bal)}",
                )
            except Exception:
                pass
            await _edit_request_card_message(bot, req)
            return True, "Main Bot balance request accepted", req

        if decision == "rejected" and req.get("status") == "rejected":
            try:
                await _notify_recharge_request_user(
                    req,
                    bot,
                    "Main Bot balance request rejected.",
                )
            except Exception:
                pass
            await _edit_request_card_message(bot, req)
            return True, "Main Bot balance request rejected", req

        return False, f"Owner review not applied. status={req.get('status')}", req

    if decision == "accepted" and req.get("status") == "accepted":
        reseller_id = int(req.get("reseller_id") or 0)
        amount_done = float(req.get("approved_amount") or req.get("amount") or 0)
        new_bal = await get_reseller_wallet_balance(reseller_id, wallet_type="main")
        await _notify_reseller_with_fallback(
            bot,
            reseller_id,
            "Topup approved by owner.\n"
            f"Added credits: {amount_done:.4f}\n"
                        f"Current Main Bot balance: {format_usd(new_bal)}",
        )
        await _edit_owner_topup_card_message(bot, req)
        return True, "Topup accepted", req

    if decision == "rejected" and req.get("status") == "rejected":
        await _notify_reseller_with_fallback(
            bot,
            int(req.get("reseller_id") or 0),
            "Topup request rejected by owner.",
        )
        await _edit_owner_topup_card_message(bot, req)
        return True, "Topup rejected", req

    return False, f"Topup review not applied. status={req.get('status')}", req


def _extract_thread_from_url(parsed) -> int | None:
    query = parse_qs(parsed.query or "")
    for key in ("thread", "topic", "comment"):
        value = (query.get(key) or [None])[0]
        if value is not None and str(value).isdigit():
            return int(value)
    return None


async def _parse_topic_target(raw: str, bot) -> tuple[int, int | None] | None:
    text = (raw or "").strip()
    if not text:
        return None

    m = re.fullmatch(r"@?([A-Za-z0-9_]{4,})", text)
    if m:
        username = m.group(1)
        try:
            chat = await bot.get_chat(f"@{username}")
        except Exception:
            return None
        return int(chat.id), None

    m = re.fullmatch(r"(-100\d+)\s*[:\s,|]\s*(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.fullmatch(r"(-100\d+)", text)
    if m:
        return int(m.group(1)), None

    candidate = text
    if candidate.startswith("t.me/") or candidate.startswith("telegram.me/"):
        candidate = "https://" + candidate
    elif candidate.startswith("tg://resolve?"):
        parsed = urlparse(candidate)
        query = parse_qs(parsed.query or "")
        domain = str((query.get("domain") or [""])[0]).strip()
        if not domain:
            return None
        thread_id = _extract_thread_from_url(parsed)
        try:
            chat = await bot.get_chat(f"@{domain.lstrip('@')}")
        except Exception:
            return None
        return int(chat.id), thread_id

    if not (candidate.startswith("http://") or candidate.startswith("https://")):
        return None

    parsed = urlparse(candidate)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in {"t.me", "telegram.me"}:
        return None

    parts = [x for x in (parsed.path or "").split("/") if x]
    thread_id = _extract_thread_from_url(parsed)

    if len(parts) >= 2 and parts[0] == "c" and parts[1].isdigit():
        chat_id = int(f"-100{parts[1]}")
        # Accept common topic-link variants:
        # /c/<chat>/<topic>
        # /c/<chat>/<topic>/<message>
        if thread_id is None and len(parts) >= 3 and parts[2].isdigit():
            thread_id = int(parts[2])
        if thread_id is None and len(parts) >= 4 and parts[3].isdigit():
            thread_id = int(parts[3])
        return chat_id, thread_id

    if not parts:
        return None

    username = parts[0].lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{4,}", username):
        return None
    try:
        chat = await bot.get_chat(f"@{username}")
    except Exception:
        return None
    return int(chat.id), thread_id


def _topic_target_parse_error(raw: str) -> str:
    text = (raw or "").strip()
    if "t.me/+" in text or "telegram.me/+" in text or "/joinchat/" in text:
        return (
            "Private invite links cannot be converted to chat id automatically.\n"
            "Send one of these instead:\n"
            "1) Topic link copied from inside the group (t.me/c/...)\n"
            "2) Public @groupusername\n"
            "3) -100CHAT_ID or -100CHAT_ID TOPIC_ID"
        )
    return "Could not parse target.\nSend a topic link, @groupusername, or: -100CHAT_ID TOPIC_ID"


@router.message(lambda msg: _text_eq(msg.text, "add recharge address", "? ????? ????? ???", "/add_recharge_address"))
async def add_address_start(message: types.Message, state: FSMContext):
    if not await is_reseller(message.from_user.id):
        return await message.answer("This action is reseller-only.")
    await message.answer("Send the new recharge address.")
    await state.set_state(ResellerRechargeFSM.waiting_for_address)


@router.message(ResellerRechargeFSM.waiting_for_address)
async def save_address(message: types.Message, state: FSMContext):
    address = (message.text or "").strip()
    if not address:
        return await message.answer("Address cannot be empty.")
    await add_recharge_address(message.from_user.id, address)
    lang = await _reseller_lang(message.from_user.id)
    await _hide_reply_keyboard(message.bot, message.chat.id, lang)
    await message.answer("Recharge address added.", reply_markup=reseller_main_menu(lang))
    await state.clear()


@router.message(lambda msg: _text_eq(msg.text, "list recharge addresses", "?? ?????? ?????", "/list_recharge_addresses"))
async def list_addresses(message: types.Message):
    if not await is_reseller(message.from_user.id):
        return await message.answer("This action is reseller-only.")
    addresses = await get_recharge_addresses(message.from_user.id)
    if not addresses:
        return await message.answer("No recharge addresses found.")

    text = "\n".join(f"{i + 1}. {addr['address']}" for i, addr in enumerate(addresses))
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=f"Delete {i + 1}", callback_data=f"del_addr_{addr['_id']}")]
            for i, addr in enumerate(addresses)
        ]
    )
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("del_addr_"))
async def delete_address(callback: types.CallbackQuery):
    addr_id = callback.data.replace("del_addr_", "")
    await delete_recharge_address(callback.from_user.id, ObjectId(addr_id))
    await callback.answer("Address deleted.")
    await callback.message.delete()


@router.message(lambda msg: bool(msg.text) and ((msg.text or "").strip() in {t("en", "btn_adjust_user_balance"), t("ar", "btn_adjust_user_balance")}) or ((msg.text or "").startswith("/adjust_user_balance")) )
async def start_adjust_user_balance(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("This action is reseller-only.")
    await message.answer("Send target username (@username) or user id.")
    await state.set_state(ResellerAdjustFSM.waiting_for_target)


@router.message(ResellerAdjustFSM.waiting_for_target)
async def received_target_user(message: types.Message, state: FSMContext):
    target_id = await _resolve_target_user_id(message.text or "")
    if not target_id:
        return await message.answer("Invalid target. Send @username or numeric user id.")

    await state.update_data(target_user_id=target_id)
    await message.answer("Choose operation:", reply_markup=_reseller_adjust_action_kb())
    await state.set_state(ResellerAdjustFSM.waiting_for_action)


@router.callback_query(ResellerAdjustFSM.waiting_for_action, lambda c: c.data and c.data.startswith("rsadj:"))
async def received_adjust_action(callback: types.CallbackQuery, state: FSMContext):
    action = (callback.data or "").split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        lang = await _reseller_lang(callback.from_user.id)
        await callback.answer("Cancelled.")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("Cancelled.", reply_markup=reseller_main_menu(lang))
        return
    if action not in ADJUST_ACTION_META:
        return await callback.answer("Invalid action", show_alert=True)

    await state.update_data(adjust_action=action)
    await state.set_state(ResellerAdjustFSM.waiting_for_amount)
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Send amount in 💲 (example: 10 or 10.50).")


@router.message(ResellerAdjustFSM.waiting_for_action)
async def received_adjust_action_text_fallback(message: types.Message):
    await message.answer("Use inline buttons to choose operation.")


@router.message(ResellerAdjustFSM.waiting_for_amount)
async def received_adjust_amount(message: types.Message, state: FSMContext):
    try:
        amount = float((message.text or "").strip())
    except Exception:
        return await message.answer("Invalid amount format.")

    if amount <= 0:
        return await message.answer("Amount must be greater than zero.")

    data = await state.get_data()
    action = data.get("adjust_action")
    target_id = data.get("target_user_id")
    if not action or not target_id:
        await state.clear()
        return await message.answer("Operation context lost. Please retry.")

    meta = ADJUST_ACTION_META.get(str(action))
    if not meta:
        await state.clear()
        return await message.answer("Invalid action context. Please retry.")

    await state.update_data(pending_amount=amount)
    confirm_text = f"Confirm `{meta['label']}` for user `{target_id}` with amount `{format_usd(amount)}`?"
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Confirm", callback_data="reseller_apply")],
            [types.InlineKeyboardButton(text="Cancel", callback_data="reseller_cancel")],
        ]
    )
    await message.answer(confirm_text, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(ResellerAdjustFSM.waiting_for_confirm)


@router.callback_query(lambda c: c.data == "reseller_cancel")
async def reseller_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await _reseller_lang(callback.from_user.id)
    await callback.answer("Cancelled.")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Cancelled.", reply_markup=reseller_main_menu(lang))


@router.callback_query(lambda c: c.data == "reseller_apply")
async def reseller_apply(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        await state.clear()
        return await callback.answer("Reseller only", show_alert=True)

    data = await state.get_data()
    action = data.get("adjust_action")
    target_id = data.get("target_user_id")
    amount = float(data.get("pending_amount") or 0)
    if not action or not target_id or amount <= 0:
        await state.clear()
        return await callback.answer("Invalid operation context", show_alert=True)

    reseller_id = callback.from_user.id
    wallet_reseller_id = await _resolve_user_wallet_reseller(int(target_id), int(reseller_id), (await callback.bot.get_me()).id)
    if wallet_reseller_id is None:
        await state.clear()
        return await callback.answer("User is not linked to your reseller bot.", show_alert=True)

    current = await get_user_wallet_balance(int(target_id), int(wallet_reseller_id))

    if action == "add":
        delta = amount
        reason = str(ADJUST_ACTION_META["add"]["reason"])
        result_text = f"Added {format_usd(amount)} to user {target_id}."
    elif action == "decrease":
        delta = -amount
        reason = str(ADJUST_ACTION_META["decrease"]["reason"])
        result_text = f"Decreased {format_usd(amount)} from user {target_id}."
    else:
        delta = amount - current
        reason = str(ADJUST_ACTION_META["set"]["reason"])
        if abs(delta) < 0.0001:
            await state.clear()
            await callback.answer("No change needed.", show_alert=True)
            await callback.message.edit_reply_markup(reply_markup=None)
            return
        result_text = f"Set user {target_id} balance to {format_usd(amount)}."

    try:
        await credit_user_wallet(
            user_id=int(target_id),
            reseller_id=int(wallet_reseller_id),
            amount=float(delta),
            reason=reason,
            actor_id=int(reseller_id),
        )
    except Exception as exc:
        await state.clear()
        await callback.answer(f"Balance update failed: {exc}", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    new_balance = await get_user_wallet_balance(int(target_id), int(wallet_reseller_id))
    await state.clear()
    await callback.answer("Done.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"{result_text}\nNew balance: {format_usd(new_balance)}")


@router.message(lambda msg: bool(msg.text) and ((msg.text or "").strip() in {t("en", "btn_recharge_requests"), t("ar", "btn_recharge_requests")}) or ((msg.text or "").startswith("/recharge_requests")) )
async def show_recharge_requests(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("This action is reseller-only.")
    await _send_recharge_requests_list(message, message.from_user.id)


async def _format_request_status(req: dict) -> str:
    status = str(req.get("status") or "pending")
    approved = "Pending"
    if status == "accepted":
        approved = "Yes"
    elif status == "rejected":
        approved = "No"
    elif status == "need_more_proof":
        approved = "Need More Proof"

    paid_display = "-"
    details = req.get("details") or {}
    if details:
        paid_amount = float(details.get("paid_amount", 0) or 0)
        paid_currency = str(details.get("paid_currency", "USD"))
        paid_display = f"{paid_amount:.2f} {paid_currency}"

    credited_amount = float(req.get("approved_amount") or req.get("amount") or 0)
    return (
        f"Approved: {approved}\n"
        f"Paid Amount: {paid_display}\n"
        f"Credited To User: {credited_amount:.4f}"
    )


async def _edit_request_card_message(bot, req: dict):
    delivery = req.get("delivery") or {}
    chat_id = delivery.get("chat_id")
    message_id = delivery.get("message_id")
    if chat_id is None or message_id is None:
        return

    details_line = await _format_request_status(req)

    base = (
        f"Manual Payment Request\n\n"
        f"Request ID: {str(req.get('_id'))}\n"
        f"User ID: {req.get('user_id')}\n"
        f"Method: {req.get('method', '-')}\n"
        f"Created At: {req.get('created_at')}\n"
        f"Credits Unit: 💲 credits\n"
        f"{details_line}"
    )

    try:
        # card is usually a photo message
        await bot.edit_message_caption(
            chat_id=int(chat_id),
            message_id=int(message_id),
            caption=base,
            reply_markup=None,
        )
        return
    except Exception:
        pass

    try:
        await bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=base,
            reply_markup=None,
        )
    except Exception:
        return


async def _apply_recharge_decision_by_id(bot, reseller_id: int, request_id: str, decision: str, approved_amount: float | None = None):
    try:
        oid = ObjectId(request_id)
    except Exception:
        return False, "Invalid request id", None

    updated = await update_recharge_request(
        oid,
        decision,
        reseller_id,
        approved_amount=approved_amount,
        decision_note=("accepted_manual_amount" if approved_amount is not None else None),
        expected_reseller_id=reseller_id,
    )
    if not updated:
        return False, "Request already handled or missing", None

    req = await db.recharge_requests.find_one({"_id": oid})
    if not req:
        return False, "Request not found after update", None

    if decision == "accepted":
        if req.get("status") != "accepted":
            return False, f"Recharge not applied. status={req.get('status')} note={req.get('decision_note') or '-'}", req
        try:
            wallet_reseller_id = int(req.get("reseller_id"))
            new_bal = await get_user_wallet_balance(int(req["user_id"]), wallet_reseller_id)
            amount_done = float(req.get("approved_amount") or req.get("amount") or 0)
            u = await get_user(int(req["user_id"]))
            lang = (u or {}).get("language", "en")
            await bot.send_message(
                int(req["user_id"]),
                f"Recharge accepted.\nAmount: {amount_done:.4f} credits\nNew balance: {format_usd(new_bal)}",
                reply_markup=balance_keyboard(lang),
            )
        except Exception:
            pass
        await _edit_request_card_message(bot, req)
        return True, "Recharge accepted", req

    try:
        await bot.send_message(
            int(req["user_id"]),
            f"Recharge request rejected.\nCredits requested: {float(req.get('amount', 0)):.4f}",
        )
    except Exception:
        pass

    await _edit_request_card_message(bot, req)
    return True, "Recharge rejected", req


@router.callback_query(lambda c: c.data and c.data.startswith("recharge_accept_"))
async def accept_recharge_request(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    req_id = callback.data.replace("recharge_accept_", "")
    ok, text, _ = await _apply_recharge_decision_by_id(callback.bot, int(callback.from_user.id), req_id, "accepted")
    await callback.answer(text if not ok else "Done")
    if ok:
        await _clear_reply_markup_safely(callback.message)


@router.callback_query(lambda c: c.data and c.data.startswith("recharge_reject_"))
async def reject_recharge_request(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    req_id = callback.data.replace("recharge_reject_", "")
    ok, text, _ = await _apply_recharge_decision_by_id(callback.bot, int(callback.from_user.id), req_id, "rejected")
    await callback.answer(text if not ok else "Done")
    if ok:
        await _clear_reply_markup_safely(callback.message)


@router.callback_query(lambda c: c.data and c.data.startswith("owner_rchg:accept:"))
async def owner_accept_reseller_topup(callback: types.CallbackQuery):
    req_id = (callback.data or "").split(":", 2)[2]
    ok, text, _ = await _apply_owner_reseller_topup_decision(
        callback.bot,
        int(callback.from_user.id),
        req_id,
        "accepted",
    )
    await callback.answer(text if not ok else "Done")
    if ok and callback.message:
        await _clear_reply_markup_safely(callback.message)


@router.callback_query(lambda c: c.data and c.data.startswith("owner_rchg:reject:"))
async def owner_reject_reseller_topup(callback: types.CallbackQuery):
    req_id = (callback.data or "").split(":", 2)[2]
    ok, text, _ = await _apply_owner_reseller_topup_decision(
        callback.bot,
        int(callback.from_user.id),
        req_id,
        "rejected",
    )
    await callback.answer(text if not ok else "Done")
    if ok and callback.message:
        await _clear_reply_markup_safely(callback.message)


@router.callback_query(lambda c: c.data and c.data.startswith("owner_rchg:manual:"))
async def owner_manual_reseller_topup_start(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner_actor(int(callback.from_user.id)):
        return await callback.answer("No permission", show_alert=True)
    req_id = (callback.data or "").split(":", 2)[2]
    await state.set_state(OwnerResellerTopupFSM.waiting_manual_amount)
    await state.update_data(owner_manual_reseller_topup_req_id=req_id)
    if callback.message:
        await callback.message.answer(
            f"Send approved credits amount for request {req_id}\n"
            "Example: 120.5\nOr /cancel"
        )
    await callback.answer()


@router.message(OwnerResellerTopupFSM.waiting_manual_amount)
async def owner_manual_reseller_topup_apply(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        await state.clear()
        return

    raw = (message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel", "/owner_panel"}:
        await state.clear()
        return await message.answer("Canceled.")

    try:
        amount = float(raw)
    except Exception:
        return await message.answer("Invalid amount. Send numeric value only.")
    if amount <= 0:
        return await message.answer("Amount must be greater than zero.")

    data = await state.get_data()
    req_id = str(data.get("owner_manual_reseller_topup_req_id") or "").strip()
    if not req_id:
        await state.clear()
        return await message.answer("Request context lost.")

    ok, text, _ = await _apply_owner_reseller_topup_decision(
        message.bot,
        int(message.from_user.id),
        req_id,
        "accepted",
        approved_amount=amount,
    )
    await state.clear()
    await message.answer(text)


@router.message(lambda msg: bool(msg.text) and (msg.text or "").strip() in {t("en", "btn_reseller_settings"), t("ar", "btn_reseller_settings")})
async def open_reseller_settings(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("This action is reseller-only.")
    await state.clear()
    lang = await _reseller_lang(message.from_user.id)
    await _hide_reply_keyboard(message.bot, message.chat.id, lang)
    await message.answer(
        await _settings_overview_text(message.from_user.id, lang),
        reply_markup=await _settings_main_kb(message.from_user.id, lang),
    )


@router.callback_query(lambda c: c.data == "rs:open")
async def settings_open_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.clear()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.edit_text(
            await _settings_overview_text(callback.from_user.id, lang),
            reply_markup=await _settings_main_kb(callback.from_user.id, lang),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "rs:routing:dm")
async def settings_use_dm_routing(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.clear()
    rid = int(callback.from_user.id)
    await clear_recharge_routing(rid)
    await clear_exchange_routing(rid)
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.edit_text(
            await _settings_overview_text(rid, lang),
            reply_markup=await _settings_main_kb(rid, lang),
        )
    lang = await _reseller_lang(callback.from_user.id)
    await callback.answer(_txt(lang, "تم تفعيل الاستلام على الخاص", "DM routing enabled"))


@router.callback_query(lambda c: c.data == "rs:close")
async def settings_close_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.clear()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.edit_text(
            t(lang, "reseller_menu_title"),
            reply_markup=reseller_main_menu(lang),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "rs:help")
async def settings_help_callback(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.edit_text(_payment_setup_help_text(lang), reply_markup=_settings_help_kb(lang))
    await callback.answer()


@router.callback_query(lambda c: c.data in {"rs:bind:pay:here", "rs:bind:ex:here"})
async def settings_bind_here(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    # Deprecated action kept for old messages that still carry these callbacks.
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.edit_text(
            await _settings_overview_text(callback.from_user.id, lang),
            reply_markup=await _settings_main_kb(callback.from_user.id, lang),
        )
    await callback.answer("Use By Link")


@router.callback_query(lambda c: c.data in {"rs:bind:pay:link", "rs:bind:ex:link"})
async def settings_bind_by_link_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    if callback.data == "rs:bind:pay:link":
        await state.set_state(ResellerSettingsFSM.waiting_payment_topic_target)
        kind = "payment"
    else:
        await state.set_state(ResellerSettingsFSM.waiting_exchange_topic_target)
        kind = "exchange"
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        text = (
            (
                f"أرسل رابط/هدف توبيك {'الدفع' if kind == 'payment' else 'الصرف'} الآن.\n\n"
                "الصيغ المقبولة:\n"
                "1) رابط التوبيك من تيليغرام (t.me/c/...)\n"
                "2) -100CHAT_ID TOPIC_ID\n"
                "3) -100CHAT_ID بدون توبيك\n\n"
                "مثال: -1001234567890 44"
            )
            if _is_ar(lang)
            else (
                f"Send {kind} topic target now.\n\n"
                "Supported formats:\n"
                "1) Topic link copied from Telegram (t.me/c/...)\n"
                "2) -100CHAT_ID TOPIC_ID\n"
                "3) -100CHAT_ID (without topic)\n\n"
                "Example: -1001234567890 44"
            )
        )
        await callback.message.edit_text(
            text,
            reply_markup=_settings_wait_input_kb(lang),
        )


@router.callback_query(lambda c: c.data == "rs:auto:topics")
async def settings_auto_topics_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.set_state(ResellerSettingsFSM.waiting_auto_topics_group_target)
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.edit_text(
            (
                "إعداد توبيكات الدفع تلقائياً\n\n"
                "أرسل رابط/آيدي الغروب الخاص الآن.\n"
                "الصيغ المقبولة:\n"
                "1) رابط الغروب من تيليغرام (t.me/c/...)\n"
                "2) -100CHAT_ID\n\n"
                "ملاحظة: فعّل Topics قبل إضافة البوت، ثم أعطه Admin وخاصة صلاحية Manage Topics."
            )
            if _is_ar(lang)
            else (
                "Auto setup topics\n\n"
                "Send your private group target now.\n"
                "Supported formats:\n"
                "1) Group link copied from Telegram (t.me/c/...)\n"
                "2) -100CHAT_ID\n\n"
                "Note: enable Topics before adding the bot, then grant all admin permissions, especially Manage Topics."
            ),
            reply_markup=_settings_wait_input_kb(lang),
        )


@router.callback_query(lambda c: c.data == "rs:auto:support_topics")
async def settings_auto_support_topics_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.set_state(ResellerSettingsFSM.waiting_support_topics_group_target)
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.edit_text(
            (
                "إعداد توبيكات الدعم تلقائياً\n\n"
                "أرسل رابط/آيدي الغروب الخاص الآن.\n"
                "الصيغ المقبولة:\n"
                "1) رابط الغروب من تيليغرام (t.me/c/...)\n"
                "2) -100CHAT_ID\n\n"
                "ملاحظة: فعّل Topics قبل إضافة البوت، ثم أعطه Admin وخاصة صلاحية Manage Topics."
            )
            if _is_ar(lang)
            else (
                "Auto setup support topics\n\n"
                "Send your private group target now.\n"
                "Supported formats:\n"
                "1) Group link copied from Telegram (t.me/c/...)\n"
                "2) -100CHAT_ID\n\n"
                "Note: enable Topics before adding the bot, then grant all admin permissions, especially Manage Topics."
            ),
            reply_markup=_settings_wait_input_kb(lang),
        )


@router.message(ResellerSettingsFSM.waiting_auto_topics_group_target)
async def settings_auto_topics_apply(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")

    parsed = await _parse_topic_target(message.text or "", message.bot)
    if not parsed:
        return await message.answer(_topic_target_parse_error(message.text or ""))
    chat_id = int(parsed[0])

    ok_admin, admin_err = await _bot_can_manage_topics(message.bot, chat_id)
    if not ok_admin:
        await state.clear()
        return await message.answer(
            "Auto setup failed.\n"
            f"Reason: {admin_err}\n\n"
            "Please enable Topics first, then add the bot as admin with all permissions, especially Manage Topics, and retry."
        )

    pay_thread_id, pay_err = await _create_forum_topic_safe(message.bot, chat_id, "Payment Requests")
    ex_thread_id, ex_err = await _create_forum_topic_safe(message.bot, chat_id, "Exchange Alerts")
    if pay_thread_id is None or ex_thread_id is None:
        await state.clear()
        return await message.answer(
            "Auto setup could not create topics.\n"
            f"Payment topic: {'ok' if pay_thread_id else 'failed'} ({pay_err or '-'})\n"
            f"Exchange topic: {'ok' if ex_thread_id else 'failed'} ({ex_err or '-'})\n\n"
            "You can still bind manually using the By Link buttons."
        )

    await set_recharge_routing(
        reseller_id=message.from_user.id,
        chat_id=chat_id,
        message_thread_id=pay_thread_id,
    )
    await set_exchange_routing(
        reseller_id=message.from_user.id,
        chat_id=chat_id,
        message_thread_id=ex_thread_id,
    )
    await state.clear()
    lang = await _reseller_lang(message.from_user.id)
    await message.answer(
        "Auto setup completed.\n\n"
        f"Payment Requests topic: {pay_thread_id}\n"
        f"Exchange Alerts topic: {ex_thread_id}",
        reply_markup=await _settings_main_kb(message.from_user.id, lang),
    )


@router.message(ResellerSettingsFSM.waiting_support_topics_group_target)
async def settings_auto_support_topics_apply(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")

    parsed = await _parse_topic_target(message.text or "", message.bot)
    if not parsed:
        return await message.answer(_topic_target_parse_error(message.text or ""))
    chat_id = int(parsed[0])

    ok_admin, admin_err = await _bot_can_manage_topics(message.bot, chat_id)
    if not ok_admin:
        await state.clear()
        return await message.answer(
            "Auto setup failed.\n"
            f"Reason: {admin_err}\n\n"
            "Please enable Topics first, then add the bot as admin with all permissions, especially Manage Topics, and retry."
        )

    created: list[tuple[str, int]] = []
    failures: list[str] = []
    for category, title in _SUPPORT_TOPIC_CATEGORIES:
        thread_id, err = await _create_forum_topic_safe(message.bot, chat_id, title)
        if thread_id is None:
            failures.append(f"{title}: {err or '-'}")
            continue
        await set_support_routing(message.from_user.id, category, chat_id=chat_id, message_thread_id=thread_id)
        created.append((title, thread_id))

    await state.clear()
    lang = await _reseller_lang(message.from_user.id)
    if failures:
        details = "\n".join(failures)
        return await message.answer(
            "Support topics setup finished with errors.\n\n"
            f"Created: {len(created)}/{len(_SUPPORT_TOPIC_CATEGORIES)}\n"
            f"{details}",
            reply_markup=await _settings_main_kb(message.from_user.id, lang),
        )

    created_lines = "\n".join(f"{title}: {thread_id}" for title, thread_id in created)
    await message.answer(
        "Support topics setup completed.\n\n"
        f"{created_lines}",
        reply_markup=await _settings_main_kb(message.from_user.id, lang),
    )


@router.message(ResellerSettingsFSM.waiting_payment_topic_target)
async def settings_bind_payment_by_link_apply(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")
    parsed = await _parse_topic_target(message.text or "", message.bot)
    if not parsed:
        return await message.answer(_topic_target_parse_error(message.text or ""))
    chat_id, thread_id = parsed
    await set_recharge_routing(
        reseller_id=message.from_user.id,
        chat_id=chat_id,
        message_thread_id=thread_id,
    )
    await state.clear()
    lang = await _reseller_lang(message.from_user.id)
    await message.answer(
        "Payment topic routing updated.\n"
        f"chat_id={chat_id}\n"
        f"topic_id={thread_id or '-'}",
        reply_markup=await _settings_main_kb(message.from_user.id, lang),
    )


@router.message(ResellerSettingsFSM.waiting_exchange_topic_target)
async def settings_bind_exchange_by_link_apply(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")
    parsed = await _parse_topic_target(message.text or "", message.bot)
    if not parsed:
        return await message.answer(_topic_target_parse_error(message.text or ""))
    chat_id, thread_id = parsed
    await set_exchange_routing(
        reseller_id=message.from_user.id,
        chat_id=chat_id,
        message_thread_id=thread_id,
    )
    await state.clear()
    lang = await _reseller_lang(message.from_user.id)
    await message.answer(
        "Exchange reminder routing updated.\n"
        f"chat_id={chat_id}\n"
        f"topic_id={thread_id or '-'}",
        reply_markup=await _settings_main_kb(message.from_user.id, lang),
    )


@router.callback_query(lambda c: c.data == "rs:rate")
async def settings_exchange_rate_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    current = await get_exchange_rate(callback.from_user.id)
    await state.set_state(ResellerSettingsFSM.waiting_exchange_rate)
    await callback.answer()
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.edit_text(
            (
                "أرسل سعر الدولار مقابل العملة المحلية الآن.\n"
                f"السعر الحالي لحسابك: {current:.2f}\n\n"
                "هذا السعر خاص بحسابك كريسيلر ولا يؤثر على غيرك."
            )
            if _is_ar(lang)
            else (
                "Send your local-to-dollar rate now.\n"
                f"Current rate for your reseller account: {current:.2f}\n\n"
                "This value is private per reseller (each reseller has independent rate)."
            ),
            reply_markup=_settings_wait_input_kb(lang),
        )


@router.message(ResellerSettingsFSM.waiting_exchange_rate)
async def settings_exchange_rate_apply(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")
    raw = (message.text or "").strip()
    try:
        rate = float(raw)
    except Exception:
        return await message.answer("Invalid value. Send a numeric rate, example: 10500")
    if rate <= 0:
        return await message.answer("Rate must be greater than zero.")
    await set_exchange_rate(message.from_user.id, rate)
    await state.clear()
    lang = await _reseller_lang(message.from_user.id)
    await message.answer(
        f"Exchange rate updated for your reseller account: 1 💲 = {rate:.2f} local",
        reply_markup=await _settings_main_kb(message.from_user.id, lang),
    )


@router.callback_query(lambda c: c.data == "rs:methods")
async def settings_methods_menu(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    methods = await get_payment_methods(callback.from_user.id)
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.edit_text(
            _format_payment_methods_text(methods, lang),
            reply_markup=_settings_methods_kb(methods, lang),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rs:method:"))
async def settings_method_details(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    code = (callback.data or "").split(":", 2)[2]
    method = await _find_payment_method(callback.from_user.id, code)
    if not method:
        return await callback.answer("Method not found", show_alert=True)
    if callback.message:
        lang = await _reseller_lang(callback.from_user.id)
        await callback.message.edit_text(
            _format_payment_method_details(method, lang),
            reply_markup=_settings_method_kb(code, lang),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rs:mset:"))
async def settings_method_edit_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        return await callback.answer("Invalid action", show_alert=True)
    field = parts[2]
    code = parts[3]
    method = await _find_payment_method(callback.from_user.id, code)
    if not method:
        return await callback.answer("Method not found", show_alert=True)
    if field == "only":
        methods = await get_payment_methods(callback.from_user.id)
        for row in methods:
            row_code = str(row.get("code") or "")
            await update_payment_method(callback.from_user.id, row_code, enabled=(row_code == code))
        method = await _find_payment_method(callback.from_user.id, code)
        await state.clear()
        lang = await _reseller_lang(callback.from_user.id)
        await callback.answer(_txt(lang, "صارت هذه وسيلة الدفع الوحيدة المفعّلة.", "This is now the only enabled payment method."))
        if callback.message and method:
            await callback.message.edit_text(
                _format_payment_method_details(method, lang),
                reply_markup=_settings_method_kb(code, lang),
            )
        return

    lang = await _reseller_lang(callback.from_user.id)
    prompts = (
        {
            "title": "أرسل الاسم الذي سيظهر للزبون. مثال: Syriatel Cash",
            "target": "أرسل رقم الدفع الحقيقي أو الحساب أو عنوان المحفظة. يمكن إرسال أكثر من سطر.",
            "currency": "أرسل العملة: USD, SYP, dollar, local, 💲, أو ليرة",
            "enabled": "أرسل حالة الوسيلة: on/off أو تشغيل/إيقاف",
            "support": "أرسل يوزر الدعم. مثال: @support_user",
            "text": (
                "أرسل نص التعليمات كاملًا الآن.\n"
                "المتغيرات المسموحة: {target} {support} {per_credit} {currency}"
            ),
            "rate": "أرسل سعر الكريدت الجديد كرقم أكبر من صفر.",
        }
        if _is_ar(lang)
        else {
            "title": "Send the display name customers will see. Example: Syriatel Cash",
            "target": "Send your real payment number, account, or wallet address. Multiple lines are OK.",
            "currency": "Send currency: USD, SYP, dollar, local, 💲, or ليرة",
            "enabled": "Send method status: on/off, enable/disable, or تشغيل/إيقاف",
            "support": "Send support username (example: @support_user).",
            "text": (
                "Send full instructions text now.\n"
                "Allowed placeholders: {target} {support} {per_credit} {currency}"
            ),
            "rate": "Send new per-credit value (numeric, > 0).",
        }
    )
    if field not in prompts:
        return await callback.answer("Unknown field", show_alert=True)

    await state.update_data(rs_method_code=code, rs_method_field=field)
    await state.set_state(ResellerSettingsFSM.waiting_method_value)
    await callback.answer()
    if callback.message:
        await callback.message.answer(prompts[field])


@router.message(ResellerSettingsFSM.waiting_method_value)
async def settings_method_edit_apply(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")

    data = await state.get_data()
    code = str(data.get("rs_method_code") or "").strip()
    field = str(data.get("rs_method_field") or "").strip()
    if not code or not field:
        await state.clear()
        return await message.answer("Settings context lost. Open settings again.")

    raw = (message.text or "").strip()
    if not raw:
        return await message.answer("Value cannot be empty.")

    kwargs = {}
    if field == "title":
        kwargs["title"] = raw
    elif field == "target":
        kwargs["target"] = raw
    elif field == "support":
        kwargs["support"] = raw
    elif field == "currency":
        cur = _parse_payment_currency(raw)
        if cur is None:
            return await message.answer("Invalid currency. Send USD, SYP, dollar, local, 💲, or ليرة.")
        kwargs["currency"] = cur
    elif field == "enabled":
        low = raw.lower().strip()
        if low in {"on", "true", "1", "yes", "enable", "enabled", "تشغيل", "تفعيل", "مفعل", "مفعلة"}:
            kwargs["enabled"] = True
        elif low in {"off", "false", "0", "no", "disable", "disabled", "إيقاف", "ايقاف", "تعطيل", "معطل", "معطلة"}:
            kwargs["enabled"] = False
        else:
            return await message.answer("Invalid status. Send on/off or تشغيل/إيقاف.")
    elif field == "text":
        kwargs["instructions"] = raw
    elif field == "rate":
        try:
            value = float(raw)
        except Exception:
            return await message.answer("Invalid rate value. Send a numeric value.")
        if value <= 0:
            return await message.answer("Rate must be greater than zero.")
        kwargs["per_credit"] = value
    else:
        await state.clear()
        return await message.answer("Unknown edit field.")

    ok = await update_payment_method(message.from_user.id, code, **kwargs)
    await state.clear()
    if not ok:
        return await message.answer("Method code not found.")

    method = await _find_payment_method(message.from_user.id, code)
    if not method:
        return await message.answer("Updated, but failed to reload method details.")
    lang = await _reseller_lang(message.from_user.id)
    await message.answer(
        _format_payment_method_details(method, lang),
        reply_markup=_settings_method_kb(code, lang),
    )


@router.message(lambda msg: (msg.text or "").startswith("/approve_recharge"))
async def approve_recharge_command(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("Reseller only.")
    parts = (message.text or "").split()
    if len(parts) not in {2, 3}:
        return await message.answer("Usage: /approve_recharge <request_id> [amount]")

    req_id = parts[1]
    amount = None
    if len(parts) == 3:
        try:
            amount = float(parts[2])
        except Exception:
            return await message.answer("Invalid amount")
        if amount <= 0:
            return await message.answer("Amount must be > 0")

    ok, text, _ = await _apply_recharge_decision_by_id(message.bot, int(message.from_user.id), req_id, "accepted", approved_amount=amount)
    await message.answer(text)


@router.message(lambda msg: (msg.text or "").startswith("/reject_recharge"))
async def reject_recharge_command(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("Reseller only.")
    parts = (message.text or "").split()
    if len(parts) != 2:
        return await message.answer("Usage: /reject_recharge <request_id>")
    req_id = parts[1]
    ok, text, _ = await _apply_recharge_decision_by_id(message.bot, int(message.from_user.id), req_id, "rejected")
    await message.answer(text)


@router.message(lambda msg: (msg.text or "").startswith("/payment_setup_help"))
async def payment_setup_help(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("This action is reseller-only.")
    lang = await _reseller_lang(message.from_user.id)
    await message.answer(_payment_setup_help_text(lang), reply_markup=_settings_help_kb(lang))


@router.message(lambda msg: (msg.text or "").startswith("/bind_payment_topic"))
async def bind_payment_topic(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("This action is reseller-only.")

    thread_id = getattr(message, "message_thread_id", None)
    await set_recharge_routing(
        reseller_id=message.from_user.id,
        chat_id=message.chat.id,
        message_thread_id=thread_id,
    )
    await message.answer(
        f"Payment requests bound to this chat/topic.\nchat_id={message.chat.id}\ntopic_id={thread_id or '-'}\n\n"
        "You can also manage this from Reseller Settings."
    )


@router.message(lambda msg: (msg.text or "").startswith("/set_exchange_rate"))
async def set_exchange_rate_cmd(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("Reseller only.")
    parts = (message.text or "").split()
    if len(parts) != 2:
        current = await get_exchange_rate(message.from_user.id)
        return await message.answer(
            "Usage: /set_exchange_rate <local_per_dollar>\n"
            f"Current (your reseller only): {current:.2f}\n"
            "Tip: You can update this from Reseller Settings."
        )
    try:
        rate = float(parts[1])
    except Exception:
        return await message.answer("Invalid rate.")
    if rate <= 0:
        return await message.answer("Rate must be > 0")
    await set_exchange_rate(message.from_user.id, rate)
    await message.answer(f"Exchange rate updated for your reseller account: 1 💲 = {rate:.2f} local")


@router.message(lambda msg: (msg.text or "").startswith("/payment_methods"))
async def payment_methods_cmd(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("Reseller only.")
    methods = await get_payment_methods(message.from_user.id)
    lines = []
    for m in methods:
        lines.append(
            f"{m.get('code')}: {m.get('title')} | "
            f"{('local' if str(m.get('currency', 'USD')).upper() == 'SYP' else '💲')} | "
            f"per_credit={float(m.get('per_credit', 1.0)):.4f}"
        )
    await message.answer("\n".join(lines) if lines else "No payment methods configured")


@router.message(lambda msg: (msg.text or "").startswith("/set_payment_target"))
async def set_payment_target_cmd(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("Reseller only.")
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer("Usage: /set_payment_target <method_code> <target_text>")
    ok = await update_payment_method(message.from_user.id, parts[1], target=parts[2])
    await message.answer("Updated" if ok else "Method code not found")


@router.message(lambda msg: (msg.text or "").startswith("/set_payment_support"))
async def set_payment_support_cmd(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("Reseller only.")
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer("Usage: /set_payment_support <method_code> <@support_username>")
    ok = await update_payment_method(message.from_user.id, parts[1], support=parts[2])
    await message.answer("Updated" if ok else "Method code not found")


@router.message(lambda msg: (msg.text or "").startswith("/set_payment_text"))
async def set_payment_text_cmd(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("Reseller only.")
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer(
            "Usage: /set_payment_text <method_code> <full text>\n"
            "Allowed placeholders: {target} {support} {per_credit} {currency}"
        )
    ok = await update_payment_method(message.from_user.id, parts[1], instructions=parts[2])
    await message.answer("Updated" if ok else "Method code not found")


@router.callback_query(lambda c: c.data and c.data.startswith("recharge_manual_"))
async def recharge_manual_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    req_id = callback.data.replace("recharge_manual_", "")
    try:
        oid = ObjectId(req_id)
    except Exception:
        return await callback.answer("Invalid request id", show_alert=True)

    req = await db.recharge_requests.find_one({"_id": oid})
    if not req or req.get("status") != "pending":
        return await callback.answer("Request not pending", show_alert=True)
    if int(req.get("reseller_id") or 0) != int(callback.from_user.id):
        return await callback.answer("This request is not yours.", show_alert=True)

    await state.update_data(manual_recharge_req_id=req_id)
    await state.set_state(ManualRechargeDecisionFSM.waiting_manual_amount)
    await callback.answer()
    details = req.get("details") or {}
    paid_amount = float(details.get("paid_amount", 0) or 0)
    paid_currency = str(details.get("paid_currency", "USD")).upper()
    requested_credits = float(req.get("amount", 0) or 0)
    per_credit = float(details.get("per_credit", 1.0) or 1.0)
    entry_hint = "Enter approved amount in the same payment currency."
    if paid_currency == "SYP":
        entry_hint = f"Enter approved amount in SYP. It will be converted using 1 💲 = {per_credit:.2f} local."
    await callback.message.reply(
        f"Enter approved amount for request {req_id}.\n"
        f"Paid amount by reseller: {paid_amount:.2f} {paid_currency}\n"
        f"Requested credits: {requested_credits:.4f}\n\n"
        f"{entry_hint}"
    )


@router.message(ManualRechargeDecisionFSM.waiting_manual_amount)
async def recharge_manual_apply(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")

    data = await state.get_data()
    req_id = data.get("manual_recharge_req_id")
    if not req_id:
        await state.clear()
        return await message.answer("Request context lost. Try again.")

    raw_amount = (message.text or "").strip()
    try:
        entered_amount = float(raw_amount)
    except Exception:
        return await message.answer("Invalid amount. Example: 10 or 10.50")
    if entered_amount <= 0:
        return await message.answer("Amount must be greater than zero.")

    req = await db.recharge_requests.find_one({"_id": ObjectId(req_id)})
    if not req:
        await state.clear()
        return await message.answer("Request already handled or missing.")
    details = req.get("details") or {}
    paid_currency = str(details.get("paid_currency", "USD")).upper()
    per_credit = float(details.get("per_credit", 1.0) or 1.0)
    if per_credit <= 0:
        per_credit = 1.0
    amount = entered_amount / per_credit if paid_currency == "SYP" else entered_amount

    updated = await update_recharge_request(
        ObjectId(req_id),
        "accepted",
        message.from_user.id,
        decision_note="accepted_manual_amount",
        approved_amount=amount,
        expected_reseller_id=message.from_user.id,
    )
    await state.clear()
    if not updated:
        return await message.answer("Request already handled or missing.")

    req = await db.recharge_requests.find_one({"_id": ObjectId(req_id)})
    if req and req.get("status") == "accepted":
        try:
            reseller_id = int(req.get("reseller_id") or req.get("user_id"))
            new_bal = await get_user_wallet_balance(int(req["user_id"]), reseller_id)
            u = await get_user(int(req["user_id"]))
            lang = (u or {}).get("language", "en")
            await _notify_recharge_request_user(
                req,
                message.bot,
                f"Recharge accepted manually.\nAmount: {amount:.4f} credits\nNew balance: {format_usd(new_bal)}",
                reply_markup=balance_keyboard(lang),
            )
        except Exception:
            pass
        await _edit_request_card_message(message.bot, req)

    await message.answer(f"Manual credits added: {amount:.4f} (request {req_id})")


@router.callback_query(lambda c: c.data and c.data.startswith("recharge_needproof_"))
async def recharge_need_proof_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    req_id = callback.data.replace("recharge_needproof_", "")
    try:
        oid = ObjectId(req_id)
    except Exception:
        return await callback.answer("Invalid request id", show_alert=True)

    req = await db.recharge_requests.find_one({"_id": oid})
    if not req or req.get("status") != "pending":
        return await callback.answer("Request not pending", show_alert=True)
    if int(req.get("reseller_id") or 0) != int(callback.from_user.id):
        return await callback.answer("This request is not yours.", show_alert=True)

    await state.update_data(need_proof_req_id=req_id)
    await state.set_state(NeedProofFSM.waiting_reason)
    await callback.answer()
    await callback.message.reply(
        f"Send your note to user for request {req_id}.\nExample: proof image is unclear, please resend."
    )


@router.message(NeedProofFSM.waiting_reason)
async def recharge_need_proof_send(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")

    note = (message.text or "").strip()
    if len(note) < 5:
        return await message.answer("Please send a clearer note (at least 5 chars).")

    data = await state.get_data()
    req_id = data.get("need_proof_req_id")
    if not req_id:
        await state.clear()
        return await message.answer("Request context lost. Try again.")

    try:
        oid = ObjectId(req_id)
    except Exception:
        await state.clear()
        return await message.answer("Invalid request id.")

    req = await db.recharge_requests.find_one({"_id": oid})
    if not req or req.get("status") != "pending":
        await state.clear()
        return await message.answer("Request not pending anymore.")
    if int(req.get("reseller_id") or 0) != int(message.from_user.id):
        await state.clear()
        return await message.answer("This request is not yours.")

    await db.recharge_requests.update_one(
        {"_id": oid, "status": "pending"},
        {
            "$set": {
                "status": "need_more_proof",
                "needs_more_proof_at": datetime.now(UTC),
                "decision_note": f"need_more_proof: {note}",
                "proof_file_id": None,
                "proof_deleted_at": datetime.now(UTC),
            }
        },
    )

    req = await db.recharge_requests.find_one({"_id": oid})
    if req:
        await _edit_request_card_message(message.bot, req)

    try:
        u = await get_user(int(req["user_id"]))
        lang = (u or {}).get("language", "en")
        kb = types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text=t(lang, "btn_resend_proof"))]],
            resize_keyboard=True,
            one_time_keyboard=False,
        )
        await _notify_recharge_request_user(
            req,
            message.bot,
            "Your payment request needs clearer proof.\n\n"
            f"Reseller note:\n{note}\n\n"
            "Please submit a new payment proof to continue.\n"
            "Send the screenshot directly in this chat to update the same request.",
            reply_markup=kb,
        )
    except Exception:
        pass

    await state.clear()
    await message.answer(f"Need-more-proof note sent to user for request {req_id}.")



@router.message(lambda msg: (msg.text or "").startswith("/set_payment_rate"))
async def set_payment_rate_cmd(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("Reseller only.")
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer("Usage: /set_payment_rate <method_code> <per_credit>")
    try:
        rate = float(parts[2])
    except Exception:
        return await message.answer("Invalid rate value")
    if rate <= 0:
        return await message.answer("Rate must be > 0")
    ok = await update_payment_method(message.from_user.id, parts[1], per_credit=rate)
    await message.answer("Updated" if ok else "Method code not found")


@router.message(lambda msg: (msg.text or "").startswith("/bind_exchange_topic"))
async def bind_exchange_topic(message: types.Message):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("This action is reseller-only.")

    thread_id = getattr(message, "message_thread_id", None)
    await set_exchange_routing(
        reseller_id=message.from_user.id,
        chat_id=message.chat.id,
        message_thread_id=thread_id,
    )
    await message.answer(
        f"Exchange-rate reminders bound to this chat/topic.\nchat_id={message.chat.id}\ntopic_id={thread_id or '-'}"
    )



























