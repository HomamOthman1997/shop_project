from datetime import UTC, datetime
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
    waiting_text = State()

def _text_eq(text: str | None, *candidates: str) -> bool:
    raw = (text or "").strip().lower()
    return raw in {x.strip().lower() for x in candidates}


def _reseller_broadcast_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="نص فقط", callback_data="rs_broadcast:text")],
            [types.InlineKeyboardButton(text="⬅️ Back to Reseller Menu", callback_data="rsmenu:menu")],
        ]
    )


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
        if not payment_methods_ready or configured_methods < enabled_methods:
            return "أكمل بيانات وسائل الدفع أو عطّل الوسائل غير المستخدمة."
        if not payment_routing_ok:
            return "اربط توبيك الدفع من الإعدادات."
        if support_ready < support_total:
            return "جهّز تبويبات دعم الخدمات الخاصة والرصيد من الإعدادات."
        if pending_recharge > 0:
            return "راجع طلبات الشحن المعلقة."
        if ready:
            return "البوت جاهز. استخدم الأزرار بالأسفل فقط عند الحاجة."
        return "أكمل الإعدادات الناقصة قبل نشر البوت."

    if not enabled_methods:
        return "Enable at least one payment method in Settings."
    if not payment_methods_ready or configured_methods < enabled_methods:
        return "Finish payment method details or disable unused methods."
    if not payment_routing_ok:
        return "Bind the payment topic from Settings."
    if support_ready < support_total:
        return "Set up Custom Services and Balance support topics from Settings."
    if pending_recharge > 0:
        return "Review pending recharge requests."
    if ready:
        return "Your bot is ready. Use the buttons below only when needed."
    return "Finish the missing setup before publishing this bot."


def _reseller_dashboard_kb(lang: str) -> types.InlineKeyboardMarkup:
    rows = [
        [
            types.InlineKeyboardButton(text=_txt(lang, "⚙️ الإعدادات", "⚙️ Settings"), callback_data="rsmenu:settings"),
            types.InlineKeyboardButton(text=_txt(lang, "🧾 طلبات الشحن", "🧾 Recharge Requests"), callback_data="rsmenu:recharge_requests"),
        ],
        [
            types.InlineKeyboardButton(text=_txt(lang, "💳 الرصيد والاشتراك", "💳 Balance & Subscription"), callback_data="rsmenu:balance"),
        ],
    ]
    url = main_bot_url("hub")
    if url:
        rows.append([types.InlineKeyboardButton(text=_txt(lang, "🚀 فتح البوت الرئيسي", "🚀 Open Main Bot"), url=url)])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


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


async def _build_reseller_stats_text(reseller_id: int, bot_id: int | None = None) -> str:
    rid = int(reseller_id)
    main_balance = await get_reseller_wallet_balance(rid, wallet_type="main")
    earnings_balance = await get_reseller_wallet_balance(rid, wallet_type="earnings")
    pending_recharge = await db.recharge_requests.count_documents({"reseller_id": rid, "status": "pending"})
    need_more_proof = await db.recharge_requests.count_documents({"reseller_id": rid, "status": "need_more_proof"})
    linked_users = await db.user_reseller_links.count_documents({"reseller_id": rid})
    active_bots = await db.bots.count_documents({"owner_id": rid, "active": True})
    methods = await get_payment_methods(rid)
    rate = await get_exchange_rate(rid)
    resolved_bot_id = int(bot_id or 0)
    if resolved_bot_id <= 0:
        subscription = {}
    else:
        subscription = await get_bot_subscription(resolved_bot_id)

    return (
        "Reseller Stats\n\n"
        f"Reseller ID: {rid}\n"
        f"Active bots: {active_bots}\n"
        f"Linked users: {linked_users}\n"
        f"Main Bot balance: {format_usd(main_balance)}\n"
        f"Custom-profit wallet: {format_usd(earnings_balance)}\n"
        + "\n".join(subscription_summary_lines("en", subscription))
        + "\n"
        "Custom-profit wallet use: profit from your own services\n"
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
        return (
            "📊 لوحة الريسيلر\n\n"
            f"• حالة البوت: {_ready_mark(ready)} {_ready_word(lang, ready)}\n"
            f"• الاشتراك: {sub_status}\n"
            f"• ينتهي: {format_subscription_dt(sub_end)}\n"
            f"• رصيد البوت الرئيسي: {format_usd(main_balance)}\n"
            f"• وسائل الدفع: {payment_line} جاهزة\n"
            f"• توبيك الدفع: {_ready_mark(setup.get('payment_routing_ok'))} {_ready_word(lang, setup.get('payment_routing_ok'))}\n"
            f"• دعم الزبائن: {support_line} جاهز (الخدمات الخاصة + الرصيد)\n"
            f"• طلبات الشحن: {recharge_line}\n\n"
            f"المطلوب الآن: {next_step}"
        )

    recharge_line = f"{pending_recharge} pending" if pending_recharge else "none pending"
    return (
        "📊 Reseller Dashboard\n\n"
        f"• Bot status: {_ready_mark(ready)} {_ready_word(lang, ready)}\n"
        f"• Subscription: {sub_status}\n"
        f"• Ends at: {format_subscription_dt(sub_end)}\n\n"
        f"• Main Bot balance: {format_usd(main_balance)}\n"
        f"• Payment methods: {payment_line} ready\n"
        f"• Payment topic: {_ready_mark(setup.get('payment_routing_ok'))} {_ready_word(lang, setup.get('payment_routing_ok'))}\n"
        f"• Customer support: {support_line} ready (Custom Services + Balance)\n"
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
        await callback.message.answer(
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
        await callback.message.answer(t(lang, "main_menu"), reply_markup=reseller_main_menu(lang))


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
        await callback.message.answer(
            "إذاعة\n\n"
            "هذه الرسالة ستُنشر في قناة هذا البوت الحالية.\n"
            "اختر نوع الإرسال.",
            reply_markup=_reseller_broadcast_kb(),
        )


@router.callback_query(lambda c: c.data == "rs_broadcast:text")
async def reseller_broadcast_text_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.set_state(ResellerBroadcastFSM.waiting_text)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "أرسل الآن نص الإذاعة كما يجب أن يظهر في القناة.\n"
            "للإلغاء أرسل /cancel"
        )


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
            await _settings_overview_text(callback.from_user.id),
            reply_markup=await _settings_main_kb(callback.from_user.id),
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
        await callback.message.answer(
            await _build_reseller_stats_text(callback.from_user.id, (await callback.bot.get_me()).id)
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
async def reseller_broadcast_text_submit(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return await message.answer("Reseller only.")
    raw = (message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel"}:
        await state.clear()
        lang = await _reseller_lang(message.from_user.id)
        return await message.answer("Canceled.", reply_markup=reseller_main_menu(lang))
    if not raw:
        return await message.answer("أرسل نصًا فقط.")
    ok, result_text = await _send_broadcast_post(message.bot, raw)
    await state.clear()
    lang = await _reseller_lang(message.from_user.id)
    await message.answer(result_text, reply_markup=reseller_main_menu(lang))


async def _settings_main_kb(reseller_id: int) -> types.InlineKeyboardMarkup:
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
    pay_label = f"Payment Topic {'✅' if pay_ok else 'DM (Easy)'}"
    ex_label = f"Exchange Topic {'✅' if ex_ok else 'DM (Easy)'}"
    support_label = f"Support Topics {'✅' if support_ok else '⚠️'}"
    rate_label = f"Exchange Rate: {rate:.2f}"
    methods_label = f"Payment Methods ({enabled_count}/{total_count} ON)"
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="Help & Guide", callback_data="rs:help"),
                types.InlineKeyboardButton(text=methods_label, callback_data="rs:methods"),
            ],
            [types.InlineKeyboardButton(text="Auto Setup Topics", callback_data="rs:auto:topics")],
            [types.InlineKeyboardButton(text=support_label, callback_data="rs:auto:support_topics")],
            [types.InlineKeyboardButton(text=pay_label, callback_data="rs:bind:pay:link")],
            [types.InlineKeyboardButton(text=ex_label, callback_data="rs:bind:ex:link")],
            [types.InlineKeyboardButton(text="Use DM Routing (Easy)", callback_data="rs:routing:dm")],
            [types.InlineKeyboardButton(text=rate_label, callback_data="rs:rate")],
            [types.InlineKeyboardButton(text="⬅️ Back to Reseller Menu", callback_data="rs:close")],
        ]
    )


def _settings_help_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="⬅️ Back to Settings", callback_data="rs:open")],
            [types.InlineKeyboardButton(text="⬅️ Back to Reseller Menu", callback_data="rs:close")],
        ]
    )


def _settings_wait_input_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="⬅️ Back to Settings", callback_data="rs:open")],
        ]
    )


async def _settings_overview_text(reseller_id: int) -> str:
    pay_route = await get_recharge_routing(int(reseller_id))
    ex_route = await get_exchange_routing(int(reseller_id))
    support_routes = await get_all_support_routing(int(reseller_id))
    methods = await get_payment_methods(int(reseller_id))
    enabled_count = sum(1 for m in methods if bool(m.get("enabled", True)))
    total_count = len(methods)
    rate = await get_exchange_rate(int(reseller_id))

    pay_status = "✅ Bound" if (pay_route and pay_route.get("chat_id")) else "DM fallback (easy mode)"
    ex_status = "✅ Bound" if (ex_route and ex_route.get("chat_id")) else "DM fallback (easy mode)"
    support_ready = sum(1 for cat, _ in _SUPPORT_TOPIC_CATEGORIES if (support_routes.get(cat) or {}).get("chat_id"))
    support_total = len(_SUPPORT_TOPIC_CATEGORIES)

    return (
        "Reseller Settings\n\n"
        f"• Payment routing: {pay_status}\n"
        f"• Exchange routing: {ex_status}\n"
        f"• Support topics: {support_ready}/{support_total} ready\n"
        f"• Exchange rate: {rate:.2f} local per 1 💲\n"
        f"• Payment methods: {enabled_count}/{total_count} enabled\n\n"
        "Optional advanced mode: enable Topics in a private group, then add your reseller bot as admin with Manage Topics.\n"
        "Easy mode works without group (requests go to DM fallback).\n\n"
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


def _settings_methods_kb(methods: list[dict]) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = []
    for m in methods:
        code = str(m.get("code") or "")
        title = str(m.get("title") or code)
        status = "✅" if bool(m.get("enabled", True)) else "⛔"
        rows.append([types.InlineKeyboardButton(text=f"{status} {title} ({code})", callback_data=f"rs:method:{code}")])
    rows.append([types.InlineKeyboardButton(text="Back to Settings", callback_data="rs:open")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _settings_method_kb(code: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Set Title", callback_data=f"rs:mset:title:{code}")],
            [types.InlineKeyboardButton(text="Set Payment Address/Target", callback_data=f"rs:mset:target:{code}")],
            [types.InlineKeyboardButton(text="Set Currency (💲/local)", callback_data=f"rs:mset:currency:{code}")],
            [types.InlineKeyboardButton(text="Enable/Disable Method", callback_data=f"rs:mset:enabled:{code}")],
            [types.InlineKeyboardButton(text="Set Support Username", callback_data=f"rs:mset:support:{code}")],
            [types.InlineKeyboardButton(text="Set Instructions Text", callback_data=f"rs:mset:text:{code}")],
            [types.InlineKeyboardButton(text="Set Rate per Credit", callback_data=f"rs:mset:rate:{code}")],
            [types.InlineKeyboardButton(text="Back to Methods", callback_data="rs:methods")],
            [types.InlineKeyboardButton(text="Back to Settings", callback_data="rs:open")],
        ]
    )


def _payment_setup_help_text() -> str:
    return (
        "Reseller setup guide:\n\n"
        "Easy mode:\n"
        "- You can keep routing on DM fallback (no group required).\n"
        "- In Settings, tap 'Use DM Routing (Easy)'.\n\n"
        "Important first step:\n"
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


def _format_payment_methods_text(methods: list[dict]) -> str:
    lines = ["Payment Methods\n"]
    for m in methods:
        status = "ON" if bool(m.get("enabled", True)) else "OFF"
        lines.append(
            f"- {m.get('code')}: {m.get('title')} | "
            f"{('local' if str(m.get('currency', 'USD')).upper() == 'SYP' else '💲')} | "
            f"per_credit={float(m.get('per_credit', 1.0)):.4f} | {status}"
        )
    lines.append("\nSelect a method below to edit details.")
    return "\n".join(lines)


def _format_payment_method_details(method: dict) -> str:
    rendered = str(method.get("instructions") or "")
    if len(rendered) > 600:
        rendered = rendered[:600] + "..."
    return (
        "Payment Method Details\n\n"
        f"Code: {method.get('code')}\n"
        f"Title: {method.get('title')}\n"
        f"Currency: {('local' if str(method.get('currency', 'USD')).upper() == 'SYP' else '💲')}\n"
        f"Enabled: {bool(method.get('enabled', True))}\n"
        f"Per Credit: {float(method.get('per_credit', 1.0)):.4f}\n"
        f"Target: {method.get('target')}\n"
        f"Support: {method.get('support')}\n\n"
        f"Instructions:\n{rendered}"
    )


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
    target_lines = [line.strip() for line in raw_target.replace("\r", "\n").split("\n") if line.strip()]
    if not target_lines and raw_target:
        target_lines = [raw_target]
    if not target_lines:
        target_block = "<code>-</code>"
    else:
        target_block = "\n".join(f"<code>{escape(line)}</code>" for line in target_lines)

    instructions = str(render_owner_method_instructions(method) or "")
    if raw_target:
        instructions = instructions.replace(raw_target, "").strip()

    return (
            "<b>Main Bot Balance Topup (Owner Payment)</b>\n\n"
        f"Method: <b>{escape(str(method.get('title') or '-'))}</b> ({escape(str(method.get('code') or '-'))})\n"
        f"Currency: <b>{escape('local' if str(method.get('currency', 'USD')).upper() == 'SYP' else '💲')}</b>\n"
        f"Per Credit: <b>{float(method.get('per_credit', 1.0)):.4f}</b>\n\n"
        "Targets (copy each line separately):\n"
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
        await _settings_overview_text(message.from_user.id),
        reply_markup=await _settings_main_kb(message.from_user.id),
    )


@router.callback_query(lambda c: c.data == "rs:open")
async def settings_open_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            await _settings_overview_text(callback.from_user.id),
            reply_markup=await _settings_main_kb(callback.from_user.id),
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
        await callback.message.edit_text(
            await _settings_overview_text(rid),
            reply_markup=await _settings_main_kb(rid),
        )
    await callback.answer("DM routing enabled")


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
        await callback.message.edit_text(_payment_setup_help_text(), reply_markup=_settings_help_kb())
    await callback.answer()


@router.callback_query(lambda c: c.data in {"rs:bind:pay:here", "rs:bind:ex:here"})
async def settings_bind_here(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    # Deprecated action kept for old messages that still carry these callbacks.
    if callback.message:
        await callback.message.edit_text(
            await _settings_overview_text(callback.from_user.id),
            reply_markup=await _settings_main_kb(callback.from_user.id),
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
        await callback.message.edit_text(
            f"Send {kind} topic target now.\n\n"
            "Supported formats:\n"
            "1) Topic link copied from Telegram (t.me/c/...)\n"
            "2) -100CHAT_ID TOPIC_ID\n"
            "3) -100CHAT_ID (without topic)\n\n"
            "Example: -1001234567890 44",
            reply_markup=_settings_wait_input_kb(),
        )


@router.callback_query(lambda c: c.data == "rs:auto:topics")
async def settings_auto_topics_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.set_state(ResellerSettingsFSM.waiting_auto_topics_group_target)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Auto setup topics\n\n"
            "Send your private group target now.\n"
            "Supported formats:\n"
            "1) Group link copied from Telegram (t.me/c/...)\n"
            "2) -100CHAT_ID\n\n"
            "Note: enable Topics before adding the bot, then grant all admin permissions, especially Manage Topics.",
            reply_markup=_settings_wait_input_kb(),
        )


@router.callback_query(lambda c: c.data == "rs:auto:support_topics")
async def settings_auto_support_topics_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    await state.set_state(ResellerSettingsFSM.waiting_support_topics_group_target)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Auto setup support topics\n\n"
            "Send your private group target now.\n"
            "Supported formats:\n"
            "1) Group link copied from Telegram (t.me/c/...)\n"
            "2) -100CHAT_ID\n\n"
            "Note: enable Topics before adding the bot, then grant all admin permissions, especially Manage Topics.",
            reply_markup=_settings_wait_input_kb(),
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
    await message.answer(
        "Auto setup completed.\n\n"
        f"Payment Requests topic: {pay_thread_id}\n"
        f"Exchange Alerts topic: {ex_thread_id}",
        reply_markup=await _settings_main_kb(message.from_user.id),
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
    if failures:
        details = "\n".join(failures)
        return await message.answer(
            "Support topics setup finished with errors.\n\n"
            f"Created: {len(created)}/{len(_SUPPORT_TOPIC_CATEGORIES)}\n"
            f"{details}",
            reply_markup=await _settings_main_kb(message.from_user.id),
        )

    created_lines = "\n".join(f"{title}: {thread_id}" for title, thread_id in created)
    await message.answer(
        "Support topics setup completed.\n\n"
        f"{created_lines}",
        reply_markup=await _settings_main_kb(message.from_user.id),
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
    await message.answer(
        "Payment topic routing updated.\n"
        f"chat_id={chat_id}\n"
        f"topic_id={thread_id or '-'}",
        reply_markup=await _settings_main_kb(message.from_user.id),
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
    await message.answer(
        "Exchange reminder routing updated.\n"
        f"chat_id={chat_id}\n"
        f"topic_id={thread_id or '-'}",
        reply_markup=await _settings_main_kb(message.from_user.id),
    )


@router.callback_query(lambda c: c.data == "rs:rate")
async def settings_exchange_rate_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    current = await get_exchange_rate(callback.from_user.id)
    await state.set_state(ResellerSettingsFSM.waiting_exchange_rate)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Send your local-to-dollar rate now.\n"
            f"Current rate for your reseller account: {current:.2f}\n\n"
            "This value is private per reseller (each reseller has independent rate).",
            reply_markup=_settings_wait_input_kb(),
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
    await message.answer(
        f"Exchange rate updated for your reseller account: 1 💲 = {rate:.2f} local",
        reply_markup=await _settings_main_kb(message.from_user.id),
    )


@router.callback_query(lambda c: c.data == "rs:methods")
async def settings_methods_menu(callback: types.CallbackQuery):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    methods = await get_payment_methods(callback.from_user.id)
    if callback.message:
        await callback.message.edit_text(
            _format_payment_methods_text(methods),
            reply_markup=_settings_methods_kb(methods),
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
        await callback.message.edit_text(
            _format_payment_method_details(method),
            reply_markup=_settings_method_kb(code),
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

    prompts = {
        "title": "Send new method title (example: ShamCash Syria).",
        "target": "Send new payment target/address text. You can send multiple lines (one target per line).",
        "currency": "Send currency code: 💲 or local",
        "enabled": "Send method status: on/off",
        "support": "Send support username (example: @support_user).",
        "text": (
            "Send full instructions text now.\n"
            "Allowed placeholders: {target} {support} {per_credit} {currency}"
        ),
        "rate": "Send new per-credit value (numeric, > 0).",
    }
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
        cur = raw.upper().strip()
        if cur not in {"USD", "SYP"}:
            return await message.answer("Invalid currency. Send 💲 or local.")
        kwargs["currency"] = cur
    elif field == "enabled":
        low = raw.lower().strip()
        if low in {"on", "true", "1", "yes"}:
            kwargs["enabled"] = True
        elif low in {"off", "false", "0", "no"}:
            kwargs["enabled"] = False
        else:
            return await message.answer("Invalid status. Send on/off.")
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
    await message.answer(
        _format_payment_method_details(method),
        reply_markup=_settings_method_kb(code),
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
    await message.answer(_payment_setup_help_text(), reply_markup=_settings_help_kb())


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



























