from datetime import UTC, datetime

from datetime import timedelta
from bson import ObjectId

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    KeyboardButton,
    KeyboardButtonRequestChat,
    KeyboardButtonRequestUsers,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import OWNER_ID, settings
from database.bots_repo import get_bot_settings
from services.subscriptions.bot_subscription_service import activate_bot_subscription
from database.financial_ledger import (
    credit_reseller_main_wallet,
    get_reseller_wallet_balance,
)
from database.bot_logs_repo import bind_bot_logs_target, get_bot_logs_target
from database.mongo import db
from database.owner_payment_settings_repo import (
    get_owner_exchange_rate,
    get_owner_payment_methods,
    set_owner_exchange_rate,
    update_owner_payment_method,
)
from database.provider_balance_alert_repo import (
    bind_provider_balance_alert_target,
    get_provider_balance_alert_settings,
    set_provider_balance_alert_threshold,
    toggle_provider_balance_alert_enabled,
)
from database.support_topics_repo import bind_support_target, get_all_support_targets, migrate_legacy_games_support_topic
from database.support_tickets_repo import get_support_ticket, mark_support_ticket_replied, mark_support_ticket_solved
from database.digital_products_config_repo import (
    get_digital_products_markup_percent,
    set_digital_products_markup_percent,
)
from database.custom_services_repo import (
    get_next_pending_preorder,
    get_pending_preorder_position,
    get_preorder_request,
    mark_preorder_fulfilling,
    mark_preorder_fulfilled,
    reset_preorder_to_pending,
)
from database.orders_repo import update_order_details, update_order_status
from database.user_repo import get_user_by_username
from utils.permissions import owner_only
from utils.recharge_ui import format_owner_reseller_topup_text, owner_reseller_topup_review_kb
from utils.translations import t
from utils.user_money import format_usd

router = Router()
_CLEAN_KEYBOARD_COMMANDS = {"/clean_keyboard", "/clean_kb", "/rkoff"}

_OWNER_QUICK_ACTIONS: dict[str, dict[str, str]] = {
    "reseller_deposit": {"code": "rdp", "button": "Deposit", "title": "Reseller Deposit"},
}
_OWNER_QUICK_CODE_TO_ACTION = {v["code"]: k for k, v in _OWNER_QUICK_ACTIONS.items()}

_RESELLER_TARGET_CACHE_TTL_SECONDS = 20
_reseller_targets_cache: dict[str, object] = {
    "expires_at": datetime.fromtimestamp(0, UTC),
    "targets": [],
}
_OWNER_USERS_PICKER_REQUEST_ID = 91001
_OWNER_CHAT_PICKER_REQUEST_ID = 91002


def _configured_numbers_markup_percent() -> float:
    try:
        return max(0.0, float(getattr(settings, "numbers_service_markup_percent", 0.0) or 0.0))
    except Exception:
        return 0.0


class OwnerPanelFlow(StatesGroup):
    waiting_payload = State()
    waiting_reseller_deposit_amount = State()
    waiting_owner_exchange_rate = State()
    waiting_owner_payment_method_value = State()
    waiting_numbers_markup = State()
    waiting_digital_products_markup = State()
    waiting_provider_balance_threshold = State()


class SupportOwnerReplyFlow(StatesGroup):
    waiting_message = State()


class CustomPreorderOwnerFlow(StatesGroup):
    waiting_delivery = State()


class OwnerBroadcastFlow(StatesGroup):
    waiting_text = State()


async def _hide_owner_reply_keyboard(message: types.Message) -> None:
    try:
        sent = await message.answer(
            t("en", "keyboard_cleanup_placeholder"),
            reply_markup=ReplyKeyboardRemove(),
        )
        try:
            await sent.delete()
        except Exception:
            pass
    except Exception:
        pass


def _owner_payload_picker_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Pick User",
                    request_users=KeyboardButtonRequestUsers(
                        request_id=_OWNER_USERS_PICKER_REQUEST_ID,
                        user_is_bot=False,
                        max_quantity=1,
                    ),
                )
            ],
            [
                KeyboardButton(
                    text="Pick Chat",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=_OWNER_CHAT_PICKER_REQUEST_ID,
                        chat_is_channel=False,
                        request_title=True,
                        request_username=True,
                    ),
                )
            ],
            [KeyboardButton(text="/cancel")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


async def _safe_edit_text(
    message: types.Message,
    text: str,
    *,
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


async def _collect_reseller_ids() -> list[int]:
    ids: set[int] = set()
    sources = [
        await db.wallets.distinct("owner_id", {"owner_type": "reseller"}),
        await db.ledger_entries.distinct("owner_id", {"owner_type": "reseller"}),
        await db.bots.distinct("owner_id", {"active": True}),
        await db.reseller_settings.distinct("reseller_id"),
        await db.user_reseller_links.distinct("reseller_id"),
        await db.recharge_requests.distinct("reseller_id"),
    ]
    for source in sources:
        for raw in source or []:
            try:
                rid = int(raw)
            except Exception:
                continue
            if rid > 0:
                ids.add(rid)
    return sorted(ids)


def _invalidate_reseller_targets_cache() -> None:
    _reseller_targets_cache["expires_at"] = datetime.fromtimestamp(0, UTC)
    _reseller_targets_cache["targets"] = []


async def _collect_reseller_targets(*, force_refresh: bool = False) -> list[dict]:
    now = datetime.now(UTC)
    if not force_refresh:
        expires_at = _reseller_targets_cache.get("expires_at")
        cached_targets = _reseller_targets_cache.get("targets")
        if isinstance(expires_at, datetime) and isinstance(cached_targets, list) and expires_at > now:
            return [dict(x) for x in cached_targets]

    reseller_ids = await _collect_reseller_ids()
    if not reseller_ids:
        _invalidate_reseller_targets_cache()
        return []

    user_rows = await db.users.find(
        {"telegram_id": {"$in": [int(x) for x in reseller_ids]}},
        {"telegram_id": 1, "username": 1},
    ).to_list(None)
    username_by_id = {
        int(row.get("telegram_id")): str(row.get("username") or "").strip()
        for row in user_rows
        if row.get("telegram_id") is not None
    }

    bot_rows = await db.bots.find(
        {"active": True, "owner_id": {"$in": [int(x) for x in reseller_ids]}},
        {"owner_id": 1, "bot_id": 1, "created_at": 1, "username_lc": 1, "bot_username_lc": 1},
    ).sort("created_at", -1).to_list(None)
    bot_by_owner: dict[int, dict] = {}
    for row in bot_rows:
        try:
            rid = int(row.get("owner_id"))
            bid = int(row.get("bot_id"))
        except Exception:
            continue
        if rid <= 0 or bid <= 0:
            continue
        if rid not in bot_by_owner:
            bot_by_owner[rid] = {
                "bot_id": bid,
                "username": str(row.get("bot_username_lc") or row.get("username_lc") or "").strip(),
            }

    targets: list[dict] = []
    for rid in reseller_ids:
        rid = int(rid)
        uname = username_by_id.get(rid, "")
        bot_meta = bot_by_owner.get(rid) or {}
        bot_id = int(bot_meta.get("bot_id") or 0)
        if bot_id:
            bot_username = str(bot_meta.get("username") or "").strip()
            if bot_username:
                label = f"@{bot_username}"
            else:
                label = f"Bot {bot_id}"
        else:
            label = f"Reseller {rid}"
        if uname:
            label = f"{label} | owner=@{uname}"
        targets.append({"reseller_id": rid, "label": label})

    _reseller_targets_cache["targets"] = [dict(x) for x in targets]
    _reseller_targets_cache["expires_at"] = now + timedelta(seconds=_RESELLER_TARGET_CACHE_TTL_SECONDS)
    return targets


async def _reseller_label(reseller_id: int) -> str:
    rid = int(reseller_id)
    targets = await _collect_reseller_targets()
    for item in targets:
        if int(item.get("reseller_id") or 0) == rid:
            return str(item.get("label") or f"Reseller {rid}")
    return f"Reseller {rid}"


def _owner_quick_action_kb(action: str, targets: list[dict]) -> types.InlineKeyboardMarkup:
    meta = _OWNER_QUICK_ACTIONS[action]
    rows: list[list[types.InlineKeyboardButton]] = []
    for item in targets:
        rid = int(item["reseller_id"])
        label = str(item.get("label") or f"Reseller {rid}")
        rows.append(
            [
                types.InlineKeyboardButton(text=label[:52], callback_data=f"owner_quick:info:{rid}"),
                types.InlineKeyboardButton(
                    text=meta["button"],
                    callback_data=f"owner_quick:run:{meta['code']}:{rid}",
                ),
            ]
        )
    rows.append(
        [
            types.InlineKeyboardButton(text="Refresh", callback_data=f"owner_quick:refresh:{meta['code']}"),
            types.InlineKeyboardButton(text="Back", callback_data="owner_panel:open"),
        ]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _owner_quick_menu_text(action: str, count: int) -> str:
    meta = _OWNER_QUICK_ACTIONS[action]
    right_action = "open amount options" if action == "reseller_deposit" else "run action now"
    return (
        f"{meta['title']}\n\n"
        f"Available reseller bots: {count}\n\n"
        "Select reseller bot:\n"
        "- Left button = bot label (info only)\n"
        f"- Right button = {right_action}"
    )


def _owner_deposit_amount_kb(reseller_id: int) -> types.InlineKeyboardMarkup:
    rid = int(reseller_id)
    rows = [
        [
            types.InlineKeyboardButton(text="+💲 10", callback_data=f"owner_deposit:apply:{rid}:10"),
            types.InlineKeyboardButton(text="+💲 25", callback_data=f"owner_deposit:apply:{rid}:25"),
            types.InlineKeyboardButton(text="+💲 50", callback_data=f"owner_deposit:apply:{rid}:50"),
        ],
        [
            types.InlineKeyboardButton(text="+💲 100", callback_data=f"owner_deposit:apply:{rid}:100"),
            types.InlineKeyboardButton(text="+💲 250", callback_data=f"owner_deposit:apply:{rid}:250"),
            types.InlineKeyboardButton(text="+💲 500", callback_data=f"owner_deposit:apply:{rid}:500"),
        ],
        [types.InlineKeyboardButton(text="Custom Amount", callback_data=f"owner_deposit:custom:{rid}")],
        [
            types.InlineKeyboardButton(text="Back To Resellers", callback_data="owner_quick:refresh:rdp"),
            types.InlineKeyboardButton(text="Owner Panel", callback_data="owner_panel:open"),
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _owner_reseller_topup_review_kb(request_id) -> types.InlineKeyboardMarkup:
    return owner_reseller_topup_review_kb(request_id)


def _owner_reseller_topup_text(req: dict) -> str:
    return format_owner_reseller_topup_text(req, include_approved=False)


def _owner_payment_methods_kb(methods: list[dict]) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = []
    for method in methods:
        code = str(method.get("code") or "")
        title = str(method.get("title") or code)
        rows.append([types.InlineKeyboardButton(text=f"{title} ({code})", callback_data=f"owner_pm:method:{code}")])
    rows.append([types.InlineKeyboardButton(text="Set Owner Exchange Rate", callback_data="owner_pm:exchange_rate")])
    rows.append([types.InlineKeyboardButton(text="Back to Owner Panel", callback_data="owner_panel:open")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _owner_payment_method_kb(code: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Set Title", callback_data=f"owner_pm:set:title:{code}")],
            [types.InlineKeyboardButton(text="Set Target", callback_data=f"owner_pm:set:target:{code}")],
            [types.InlineKeyboardButton(text="Set Currency (💲/local)", callback_data=f"owner_pm:set:currency:{code}")],
            [types.InlineKeyboardButton(text="Enable/Disable Method", callback_data=f"owner_pm:set:enabled:{code}")],
            [types.InlineKeyboardButton(text="Set Support", callback_data=f"owner_pm:set:support:{code}")],
            [types.InlineKeyboardButton(text="Set Instructions", callback_data=f"owner_pm:set:text:{code}")],
            [types.InlineKeyboardButton(text="Back to Methods", callback_data="owner_pm:open")],
        ]
    )


def _owner_payment_methods_text(methods: list[dict], exchange_rate: float) -> str:
    lines = [
        "Owner Payment Methods (Global for all resellers)\n",
        f"Owner Exchange Rate: 1 💲 = {exchange_rate:.2f} local\n",
    ]
    for method in methods:
        currency = str(method.get('currency', 'USD')).upper()
        currency_label = "local" if currency == "SYP" else "💲"
        effective_rate = float(exchange_rate) if currency == "SYP" else 1.0
        lines.append(
            f"- {method.get('code')}: {method.get('title')} | "
            f"{currency_label} | "
            f"credit_rate={effective_rate:.4f}"
        )
    lines.append("\nSelect method below to edit.")
    return "\n".join(lines)


def _owner_payment_method_details(method: dict) -> str:
    rendered = str(method.get("instructions") or "")
    if len(rendered) > 700:
        rendered = rendered[:700] + "..."
    currency = str(method.get('currency', 'USD')).upper()
    currency_label = "local" if currency == "SYP" else "💲"
    effective_rate = float(method.get('per_credit', 1.0))
    return (
        "Owner Payment Method\n\n"
        f"Code: {method.get('code')}\n"
        f"Title: {method.get('title')}\n"
        f"Currency: {currency_label}\n"
        f"Enabled: {bool(method.get('enabled', True))}\n"
        f"Effective Credit Rate: {effective_rate:.4f}\n"
        "Rate Source: global owner exchange rate for local, fixed 1.0 for 💲\n"
        f"Target: {method.get('target')}\n"
        f"Support: {method.get('support')}\n\n"
        f"Instructions:\n{rendered}"
    )


def _is_owner_callback(callback: types.CallbackQuery) -> bool:
    return bool(callback.from_user and int(callback.from_user.id) == int(OWNER_ID))


async def _find_owner_payment_method(code: str) -> dict | None:
    methods = await get_owner_payment_methods()
    for method in methods:
        if str(method.get("code")) == str(code):
            return method
    return None


def _previous_cycle_key() -> str:
    now = datetime.now(UTC)
    if now.month == 1:
        return f"{now.year - 1}-12"
    return f"{now.year}-{now.month - 1:02d}"


def _parse_cycle_key_or_none(raw: str) -> str | None:
    try:
        dt = datetime.strptime(raw, "%Y-%m")
        return f"{dt.year}-{dt.month:02d}"
    except Exception:
        return None


def _owner_panel_main_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Dashboard", callback_data="owner_panel:act:dashboard")
    kb.button(text="Subscriptions", callback_data="owner_panel:cat:subscriptions")
    kb.button(text="Main Bot", callback_data="owner_panel:cat:main_bot")
    kb.button(text="System", callback_data="owner_panel:cat:system")
    kb.adjust(1, 2, 1)
    return kb.as_markup()


def _owner_dashboard_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Back", callback_data="owner_panel:open")],
        ]
    )


def _owner_panel_category_kb(category: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if category == "financial":
        category = "subscriptions"
    if category == "subscriptions":
        kb.button(text="Reseller Deposit", callback_data="owner_panel:act:reseller_deposit")
        kb.button(text="Reseller Topup Requests", callback_data="owner_panel:act:reseller_topup_requests")
        kb.adjust(1, 1)
    elif category == "main_bot":
        kb.button(text="إذاعة", callback_data="owner_panel:act:broadcast")
        kb.button(text="Owner Payment Methods", callback_data="owner_panel:act:owner_payment_methods")
        kb.button(text="Owner Exchange Rate", callback_data="owner_panel:act:owner_exchange_rate")
        kb.button(text="Numbers Margin %", callback_data="owner_panel:act:numbers_margin")
        kb.button(text="Digital Products Margin %", callback_data="owner_panel:act:digital_products_margin")
        kb.adjust(1, 1, 1, 1, 1)
    elif category == "system":
        kb.button(text="Bind Owner Target Here", callback_data="owner_panel:act:bind_owner_target_here")
        kb.button(text="Bind Reseller Topup Target Here", callback_data="owner_panel:act:bind_reseller_topup_target_here")
        kb.button(text="Bind Support / Proxies Here", callback_data="owner_panel:act:bind_support_proxies_here")
        kb.button(text="Bind Support / Numbers Here", callback_data="owner_panel:act:bind_support_numbers_here")
        kb.button(text="Bind Support / Services Here", callback_data="owner_panel:act:bind_support_services_here")
        kb.button(text="Bind Support / Balance Here", callback_data="owner_panel:act:bind_support_user_balance_here")
        kb.button(text="Support Topics Status", callback_data="owner_panel:act:support_topics_status")
        kb.button(text="Bind Balance Alert Here", callback_data="owner_panel:act:bind_balance_alert_here")
        kb.button(text="Bind Logs Here", callback_data="owner_panel:act:bind_logs_here")
        kb.button(text="Logs Status", callback_data="owner_panel:act:logs_status")
        kb.button(text="Send Test Log", callback_data="owner_panel:act:send_test_log")
        kb.button(text="Balance Alert Threshold", callback_data="owner_panel:act:provider_balance_threshold")
        kb.button(text="Balance Alert Enable/Disable", callback_data="owner_panel:act:provider_balance_toggle")
        kb.adjust(1)
    kb.button(text="Back", callback_data="owner_panel:open")
    kb.adjust(1)
    return kb.as_markup()


def _owner_action_prompt(action: str) -> str:
    prompts = {
        "reseller_deposit": "Send: <reseller_id_or_@username> <amount>\nExample: 7731488539 200",
        "owner_exchange_rate": "Send: <local_per_dollar>\nExample: 13250",
    }
    return prompts.get(action, "Send input payload for this action.")


def _owner_broadcast_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="نص فقط", callback_data="owner_broadcast:text")],
            [types.InlineKeyboardButton(text="Back", callback_data="owner_panel:cat:main_bot")],
        ]
    )


async def _owner_current_bot_broadcast_channel(bot: Bot) -> str | None:
    me = await bot.get_me()
    settings_doc = await get_bot_settings(int(me.id))
    raw = str((settings_doc or {}).get("subscription_channel") or "").strip()
    return raw or None


async def _owner_send_broadcast_post(bot: Bot, text: str) -> tuple[bool, str]:
    channel = await _owner_current_bot_broadcast_channel(bot)
    if not channel:
        return False, "No channel is configured for this bot yet."
    try:
        await bot.send_message(chat_id=channel, text=text)
    except Exception as exc:
        return False, f"Broadcast failed: {exc}"
    return True, f"Broadcast sent to {channel}."


async def _build_owner_dashboard_text() -> str:
    await migrate_legacy_games_support_topic()
    reseller_targets = await _collect_reseller_targets()
    reseller_ids = [int(item.get("reseller_id") or 0) for item in reseller_targets if int(item.get("reseller_id") or 0) > 0]
    active_bots = await db.bots.count_documents({"active": True})
    pending_reseller_topups = await db.recharge_requests.count_documents(
        {"status": "pending", "wallet_type": {"$in": ["reseller_main", "main", "reseller"]}}
    )
    pending_user_topups = await db.recharge_requests.count_documents(
        {"status": "pending", "wallet_type": {"$nin": ["reseller_main", "main", "reseller"]}}
    )
    need_more_proof = await db.recharge_requests.count_documents({"status": "need_more_proof"})
    trial_active_bots = await db.bots.count_documents({"active": True, "subscription.status": "trial_active"})
    active_sub_bots = await db.bots.count_documents({"active": True, "subscription.status": "active"})
    grace_bots = await db.bots.count_documents({"active": True, "subscription.status": "grace_period"})
    suspended_bots = await db.bots.count_documents({"active": True, "subscription.status": {"$in": ["payment_required", "suspended"]}})
    pending_payment_bots = await db.bots.count_documents({"active": True, "subscription.status": "payment_required"})
    numbers_orders_open = await db.orders.count_documents(
        {"service_type": {"$in": ["temp", "rental"]}, "status": {"$in": ["pending", "paid", "active", "waiting_code"]}}
    )
    proxy_orders_open = await db.orders.count_documents(
        {"service_type": "proxy_rental", "status": {"$in": ["pending", "paid", "active"]}}
    )
    reseller_main_total = 0.0
    reseller_earnings_total = 0.0
    cursor = db.wallets.find(
        {"owner_type": "reseller", "wallet_type": {"$in": ["reseller_main", "reseller_earnings"]}},
        {"wallet_type": 1, "balance": 1},
    )
    async for row in cursor:
        balance = float(row.get("balance") or 0.0)
        if str(row.get("wallet_type")) == "reseller_main":
            reseller_main_total += balance
        elif str(row.get("wallet_type")) == "reseller_earnings":
            reseller_earnings_total += balance

    balance_cfg = await get_provider_balance_alert_settings()
    logs_target = await get_bot_logs_target()
    owner_target = await db.system_settings.find_one({"_id": "owner_notifications"}) or {}
    reseller_topup_target = await db.system_settings.find_one({"_id": "owner_reseller_topups"}) or {}
    owner_methods = await get_owner_payment_methods()
    enabled_owner_methods = sum(1 for item in owner_methods if bool(item.get("enabled", True)))
    owner_rate = await get_owner_exchange_rate()
    numbers_margin = _configured_numbers_markup_percent()
    digital_products_margin = await get_digital_products_markup_percent()
    main_bot_username = str(getattr(settings, "main_bot_username", "") or "").strip()
    support_targets = await get_all_support_targets()
    support_bound_count = sum(1 for item in support_targets.values() if isinstance(item.get("chat_id"), int))

    owner_target_txt = (
        f"{owner_target.get('chat_id')} / topic {owner_target.get('message_thread_id') or '-'}"
        if isinstance(owner_target.get("chat_id"), int)
        else "not bound"
    )
    reseller_topup_target_txt = (
        f"{reseller_topup_target.get('chat_id')} / topic {reseller_topup_target.get('message_thread_id') or '-'}"
        if isinstance(reseller_topup_target.get("chat_id"), int)
        else "inherits owner target"
    )
    logs_target_txt = (
        f"{logs_target.get('chat_id')} / topic {logs_target.get('message_thread_id') or '-'}"
        if logs_target and isinstance(logs_target.get("chat_id"), int)
        else "not bound"
    )
    provider_target_txt = (
        f"{balance_cfg.get('chat_id')} / topic {balance_cfg.get('message_thread_id') or '-'}"
        if isinstance(balance_cfg.get("chat_id"), int)
        else "inherits owner/log target"
    )

    return (
        "Owner Dashboard\n\n"
        "Overview\n"
        f"- Active reseller owners: {len(reseller_ids)}\n"
        f"- Active bots: {active_bots}\n\n"
        "Subscriptions\n"
        f"- Trial: {trial_active_bots}\n"
        f"- Active: {active_sub_bots}\n"
        f"- Grace: {grace_bots}\n"
        f"- Awaiting first payment: {pending_payment_bots}\n"
        f"- Suspended: {suspended_bots}\n\n"
        "Operations\n"
        f"- Open numbers orders: {numbers_orders_open}\n"
        f"- Open proxy orders: {proxy_orders_open}\n"
        f"- Pending reseller topups: {pending_reseller_topups}\n"
        f"- Pending user topups: {pending_user_topups}\n"
        f"- Need-more-proof: {need_more_proof}\n\n"
        "Wallet Totals\n"
        f"- Reseller main: {format_usd(reseller_main_total)}\n"
        f"- Reseller custom profit: {format_usd(reseller_earnings_total)}\n\n"
        "Main Bot\n"
        f"- Username: @{main_bot_username.lstrip('@') or '-'}\n"
        f"- Owner payment methods: {enabled_owner_methods}/{len(owner_methods)} enabled\n"
        f"- Owner exchange rate: 1 💲 = {owner_rate:.2f} local\n"
        f"- Numbers margin: {numbers_margin:.2f}%\n"
        f"- Digital products margin: {digital_products_margin:.2f}%\n\n"
        "Routing\n"
        f"- Owner target: {owner_target_txt}\n"
        f"- Reseller topup target: {reseller_topup_target_txt}\n"
        f"- Support topics: {support_bound_count}/4 bound\n"
        f"- Provider alert target: {provider_target_txt}\n"
        f"- Logs target: {logs_target_txt}\n"
        f"- Provider alert: {'on' if bool(balance_cfg.get('enabled')) else 'off'} @ {format_usd(float(balance_cfg.get('threshold_usd') or 0.0))}"
    )


def _owner_panel_home_text() -> str:
    return (
        "Owner Panel\n\n"
        "Choose a section:\n"
        "- Dashboard: platform status and totals\n"
        "- Subscriptions: reseller deposits and topup review\n"
        "- Main Bot: owner payment methods and pricing\n"
        "- System: routing, support topics, logs, and alerts"
    )


@router.message(lambda msg: (msg.text or "").strip() in {"/owner", "/owner_panel"})
async def owner_panel_open_command(message: types.Message):
    if not await owner_only(message):
        return
    await _hide_owner_reply_keyboard(message)
    await message.answer(
        _owner_panel_home_text(),
        reply_markup=_owner_panel_main_kb(),
    )


@router.callback_query(lambda c: c.data == "owner_panel:open")
async def owner_panel_open_callback(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    await state.clear()
    if callback.message:
        await _hide_owner_reply_keyboard(callback.message)
        await _safe_edit_text(
            callback.message,
            _owner_panel_home_text(),
            reply_markup=_owner_panel_main_kb(),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("owner_panel:cat:"))
async def owner_panel_category(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    category = (callback.data or "").split(":", 2)[2]
    if category == "financial":
        category = "subscriptions"
    await state.clear()
    if callback.message:
        await _hide_owner_reply_keyboard(callback.message)
        hints = {
            "subscriptions": "Bot subscriptions and reseller funding operations.",
            "main_bot": "Main bot pricing, methods, and platform controls.",
            "system": "System routing and owner target settings.",
        }
        display_category = "Main Bot" if category == "main_bot" else category.title()
        await _safe_edit_text(
            callback.message,
            f"Owner Panel / {display_category}\n\n{hints.get(category, '')}",
            reply_markup=_owner_panel_category_kb(category),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("owner_panel:act:"))
async def owner_panel_action(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    action = (callback.data or "").split(":", 2)[2]

    if action == "dashboard":
        if callback.message:
            await _safe_edit_text(
                callback.message,
                await _build_owner_dashboard_text(),
                reply_markup=_owner_dashboard_kb(),
            )
        return await callback.answer()

    if action == "broadcast":
        if callback.message:
            await _safe_edit_text(
                callback.message,
                "إذاعة\n\n"
                "هذه الرسالة ستُنشر في قناة البوت الحالي.\n"
                "اختر نوع الإرسال.",
                reply_markup=_owner_broadcast_kb(),
            )
        return await callback.answer()

    if action == "resellers":
        result = await _execute_owner_action(action="resellers", payload="", actor_id=callback.from_user.id)
        if callback.message:
            await callback.message.answer(result)
        return await callback.answer("Done")

    if action == "bind_owner_target_here":
        if callback.message:
            await db.system_settings.update_one(
                {"_id": "owner_notifications"},
                {
                    "$set": {
                        "chat_id": callback.message.chat.id,
                        "message_thread_id": getattr(callback.message, "message_thread_id", None),
                        "updated_at": datetime.now(UTC),
                    }
                },
                upsert=True,
            )
            await callback.message.answer(
                f"Owner target bound.\nchat_id={callback.message.chat.id}\n"
                f"topic_id={getattr(callback.message, 'message_thread_id', None) or '-'}"
            )
        return await callback.answer("Bound")

    if action == "bind_reseller_topup_target_here":
        if callback.message:
            await db.system_settings.update_one(
                {"_id": "owner_reseller_topups"},
                {
                    "$set": {
                        "chat_id": callback.message.chat.id,
                        "message_thread_id": getattr(callback.message, "message_thread_id", None),
                        "updated_at": datetime.now(UTC),
                    }
                },
                upsert=True,
            )
            await callback.message.answer(
                f"Reseller topup target bound.\nchat_id={callback.message.chat.id}\n"
                f"topic_id={getattr(callback.message, 'message_thread_id', None) or '-'}"
            )
        return await callback.answer("Bound")

    if action in {
        "bind_support_proxies_here",
        "bind_support_numbers_here",
        "bind_support_services_here",
        "bind_support_user_balance_here",
    }:
        if callback.message:
            category = action.removeprefix("bind_support_").removesuffix("_here")
            await bind_support_target(
                category,
                chat_id=int(callback.message.chat.id),
                message_thread_id=getattr(callback.message, "message_thread_id", None),
            )
            await callback.message.answer(
                f"Support topic bound for {category}.\n"
                f"chat_id={callback.message.chat.id}\n"
                f"topic_id={getattr(callback.message, 'message_thread_id', None) or '-'}"
            )
        return await callback.answer("Bound")

    if action == "support_topics_status":
        targets = await get_all_support_targets()
        lines = ["Support topics status\n"]
        for category in ("proxies", "numbers", "services", "user_balance"):
            target = targets.get(category) or {}
            if isinstance(target.get("chat_id"), int):
                lines.append(
                    f"- {category}: {target.get('chat_id')} / topic {target.get('message_thread_id') or '-'}"
                )
            else:
                lines.append(f"- {category}: not bound")
        if callback.message:
            await callback.message.answer("\n".join(lines))
        return await callback.answer("Shown")

    if action == "bind_balance_alert_here":
        if callback.message:
            await bind_provider_balance_alert_target(
                chat_id=int(callback.message.chat.id),
                message_thread_id=getattr(callback.message, "message_thread_id", None),
            )
            current = await get_provider_balance_alert_settings()
            await callback.message.answer(
                "Provider balance alert target bound.\n"
                f"chat_id={callback.message.chat.id}\n"
                f"topic_id={getattr(callback.message, 'message_thread_id', None) or '-'}\n"
                f"enabled={bool(current.get('enabled'))}\n"
                f"threshold={format_usd(float(current.get('threshold_usd') or 0))}"
            )
        return await callback.answer("Bound")

    if action == "bind_logs_here":
        if callback.message:
            await bind_bot_logs_target(
                chat_id=int(callback.message.chat.id),
                message_thread_id=getattr(callback.message, "message_thread_id", None),
            )
            await callback.message.answer(
                "Bot logs target bound.\n"
                f"chat_id={callback.message.chat.id}\n"
                f"topic_id={getattr(callback.message, 'message_thread_id', None) or '-'}"
            )
        return await callback.answer("Bound")

    if action == "logs_status":
        target = await get_bot_logs_target()
        text = (
            "Logs target is ready.\n"
            f"chat_id={target['chat_id']}\n"
            f"topic_id={target.get('message_thread_id') or '-'}"
            if target
            else "Logs target is not bound yet.\nOpen the wanted owner-group topic then press: Bind Logs Here."
        )
        if callback.message:
            await callback.message.answer(text)
        return await callback.answer("Shown")

    if action == "send_test_log":
        import logging

        logging.getLogger("owner.logs").info("Owner test log: manual test from owner panel.")
        if callback.message:
            await callback.message.answer("Test log emitted. Check the bound logs topic.")
        return await callback.answer("Sent")

    if action == "provider_balance_threshold":
        current = await get_provider_balance_alert_settings()
        await state.set_state(OwnerPanelFlow.waiting_provider_balance_threshold)
        if callback.message:
            await callback.message.answer(
                "Send provider balance alert threshold in dollar now.\n"
                f"Current: {format_usd(float(current.get('threshold_usd') or 0))}\n"
                "Example: 1.5"
            )
        return await callback.answer()

    if action == "provider_balance_toggle":
        enabled = await toggle_provider_balance_alert_enabled()
        current = await get_provider_balance_alert_settings()
        if callback.message:
            await callback.message.answer(
                "Provider balance alert updated.\n"
                f"Enabled: {enabled}\n"
                f"Threshold: {format_usd(float(current.get('threshold_usd') or 0))}"
            )
        return await callback.answer("Updated")

    if action == "reseller_topup_requests":
        rows = await db.recharge_requests.find(
            {
                "status": "pending",
                "wallet_type": {"$in": ["reseller_main", "main", "reseller"]},
            }
        ).sort("created_at", -1).limit(20).to_list(20)
        if not rows:
            return await callback.answer("No pending reseller topup requests.", show_alert=True)
        if callback.message:
            await callback.message.answer(f"Pending reseller topup requests: {len(rows)}")
            for req in rows:
                text = _owner_reseller_topup_text(req)
                kb = _owner_reseller_topup_review_kb(req.get("_id"))
                if req.get("proof_file_id"):
                    await callback.message.answer_photo(req["proof_file_id"], caption=text, reply_markup=kb)
                else:
                    await callback.message.answer(text, reply_markup=kb)
        return await callback.answer("Loaded")

    if action == "owner_payment_methods":
        methods = await get_owner_payment_methods()
        rate = await get_owner_exchange_rate()
        if callback.message:
            await _safe_edit_text(
                callback.message,
                _owner_payment_methods_text(methods, rate),
                reply_markup=_owner_payment_methods_kb(methods),
            )
        return await callback.answer()

    if action == "owner_exchange_rate":
        await state.set_state(OwnerPanelFlow.waiting_owner_exchange_rate)
        current = await get_owner_exchange_rate()
        if callback.message:
            await callback.message.answer(
                "Send owner local-to-dollar exchange rate now.\n"
                f"Current: {current:.2f}\n\n"
                "This rate is shared globally for all resellers using owner payment methods."
            )
        return await callback.answer()

    if action == "numbers_margin":
        current = _configured_numbers_markup_percent()
        if callback.message:
            await callback.message.answer(
                "Numbers margin is config-controlled.\n"
                f"Current: {current:.2f}%\n"
                "Change NUMBERS_SERVICE_MARKUP_PERCENT and restart the bot."
            )
        return await callback.answer()

    if action == "digital_products_margin":
        await state.set_state(OwnerPanelFlow.waiting_digital_products_markup)
        current = await get_digital_products_markup_percent(2.0)
        if callback.message:
            await callback.message.answer(
                "Send digital products margin percent now (global).\n"
                f"Current: {current:.2f}%\n"
                "Example: 2"
            )
        return await callback.answer()

    if action in _OWNER_QUICK_ACTIONS:
        await state.clear()
        targets = await _collect_reseller_targets()
        if not targets:
            return await callback.answer("No reseller bots found.", show_alert=True)
        if callback.message:
            await _safe_edit_text(
                callback.message,
                _owner_quick_menu_text(action, len(targets)),
                reply_markup=_owner_quick_action_kb(action, targets),
            )
        return await callback.answer()

    await state.set_state(OwnerPanelFlow.waiting_payload)
    await state.update_data(owner_action=action)
    if callback.message:
        await callback.message.answer(
            f"Action: {action}\n\n{_owner_action_prompt(action)}\n\nSend payload now, or send /owner_panel to cancel.",
            reply_markup=_owner_payload_picker_kb(),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "owner_broadcast:text")
async def owner_broadcast_text_start(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    await state.set_state(OwnerBroadcastFlow.waiting_text)
    if callback.message:
        await callback.message.answer(
            "أرسل الآن نص الإذاعة كما يجب أن يظهر في القناة.\n"
            "للإلغاء أرسل /cancel"
        )
    await callback.answer()


@router.message(OwnerBroadcastFlow.waiting_text)
async def owner_broadcast_text_submit(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        await state.clear()
        return
    payload = (message.text or "").strip()
    if payload.lower() in {"/cancel", "cancel", "/owner_panel"}:
        await state.clear()
        await _hide_owner_reply_keyboard(message)
        await message.answer("Canceled.", reply_markup=_owner_panel_main_kb())
        return
    if not payload:
        await message.answer("أرسل نصًا فقط.")
        return
    ok, result = await _owner_send_broadcast_post(message.bot, payload)
    await state.clear()
    await _hide_owner_reply_keyboard(message)
    await message.answer(result, reply_markup=_owner_panel_main_kb())


@router.message(OwnerPanelFlow.waiting_payload)
async def owner_panel_payload_input(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        return

    data = await state.get_data()
    action = data.get("owner_action")
    payload = (message.text or "").strip()
    if not action:
        await state.clear()
        return await message.answer("No pending action. Use /owner_panel")

    if payload.lower() in _CLEAN_KEYBOARD_COMMANDS:
        await state.clear()
        await message.answer("Keyboard cleaned.", reply_markup=types.ReplyKeyboardRemove())
        return await message.answer("Owner Panel", reply_markup=_owner_panel_main_kb())

    if payload.lower() in {"/cancel", "cancel", "/owner_panel"}:
        await state.clear()
        await _hide_owner_reply_keyboard(message)
        return await message.answer("Canceled.", reply_markup=_owner_panel_main_kb())

    result = await _execute_owner_action(action=action, payload=payload, actor_id=message.from_user.id)
    await message.answer(result)
    await state.clear()
    await _hide_owner_reply_keyboard(message)
    await message.answer("Owner Panel", reply_markup=_owner_panel_main_kb())


@router.message(OwnerPanelFlow.waiting_payload, lambda m: bool(getattr(m, "users_shared", None)))
async def owner_panel_payload_users_shared(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        return
    users_shared = getattr(message, "users_shared", None)
    if not users_shared:
        return
    if int(getattr(users_shared, "request_id", 0) or 0) != _OWNER_USERS_PICKER_REQUEST_ID:
        return
    users = list(getattr(users_shared, "users", []) or [])
    if not users:
        return await message.answer("No user selected. You can still type payload manually.")
    user_id = int(getattr(users[0], "user_id", 0) or 0)
    if user_id <= 0:
        return await message.answer("Invalid user selection.")
    await message.answer(
        f"Selected user id: {user_id}\nNow send full payload using this id.",
        reply_markup=_owner_payload_picker_kb(),
    )


@router.message(OwnerPanelFlow.waiting_payload, lambda m: bool(getattr(m, "chat_shared", None)))
async def owner_panel_payload_chat_shared(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        return
    chat_shared = getattr(message, "chat_shared", None)
    if not chat_shared:
        return
    if int(getattr(chat_shared, "request_id", 0) or 0) != _OWNER_CHAT_PICKER_REQUEST_ID:
        return
    chat_id = int(getattr(chat_shared, "chat_id", 0) or 0)
    if chat_id == 0:
        return await message.answer("Invalid chat selection.")
    await message.answer(
        f"Selected chat id: {chat_id}\nNow send full payload using this chat id.",
        reply_markup=_owner_payload_picker_kb(),
    )


@router.callback_query(lambda c: c.data == "owner_pm:open")
async def owner_payment_methods_open(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    try:
        await callback.answer()
    except TelegramBadRequest as exc:
        if "query is too old" not in str(exc).lower():
            raise
    await state.clear()
    methods = await get_owner_payment_methods()
    rate = await get_owner_exchange_rate()
    if callback.message:
        await _safe_edit_text(
            callback.message,
            _owner_payment_methods_text(methods, rate),
            reply_markup=_owner_payment_methods_kb(methods),
        )


@router.callback_query(lambda c: c.data and c.data.startswith("owner_pm:method:"))
async def owner_payment_method_details(callback: types.CallbackQuery):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    code = (callback.data or "").split(":", 2)[2]
    method = await _find_owner_payment_method(code)
    if not method:
        return await callback.answer("Method not found", show_alert=True)
    if callback.message:
        await _safe_edit_text(
            callback.message,
            _owner_payment_method_details(method),
            reply_markup=_owner_payment_method_kb(code),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "owner_pm:exchange_rate")
async def owner_payment_exchange_rate_start(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    await state.set_state(OwnerPanelFlow.waiting_owner_exchange_rate)
    current = await get_owner_exchange_rate()
    if callback.message:
        await callback.message.answer(
            "Send owner local-to-dollar exchange rate now.\n"
            f"Current: {current:.2f}\n\n"
            "This rate is shared globally for all resellers."
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("owner_pm:set:"))
async def owner_payment_method_edit_start(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)

    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        return await callback.answer("Invalid action", show_alert=True)
    field, code = parts[2], parts[3]
    method = await _find_owner_payment_method(code)
    if not method:
        return await callback.answer("Method not found", show_alert=True)

    prompts = {
        "title": "Send new method title.",
        "target": "Send new target/address text. You can send multiple lines (one target per line).",
        "currency": "Send currency code: 💲 or local",
        "enabled": "Send method status: on/off",
        "support": "Send support username (example: @support_user).",
        "text": "Send full instructions text now.",
    }
    if field not in prompts:
        return await callback.answer("Unknown field", show_alert=True)

    await state.set_state(OwnerPanelFlow.waiting_owner_payment_method_value)
    await state.update_data(owner_pm_code=code, owner_pm_field=field)
    if callback.message:
        await callback.message.answer(prompts[field])
    await callback.answer()


@router.message(OwnerPanelFlow.waiting_owner_exchange_rate)
async def owner_exchange_rate_apply(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel", "/owner_panel"}:
        await state.clear()
        return await message.answer("Canceled.", reply_markup=_owner_panel_main_kb())
    try:
        rate = float(raw)
    except Exception:
        return await message.answer("Invalid value. Send numeric rate only.")
    if rate <= 0:
        return await message.answer("Rate must be greater than zero.")

    await set_owner_exchange_rate(rate)
    await state.clear()
    await message.answer(
        f"Owner exchange rate updated: 1 💲 = {rate:.2f} local",
        reply_markup=_owner_panel_main_kb(),
    )


@router.message(OwnerPanelFlow.waiting_owner_payment_method_value)
async def owner_payment_method_edit_apply(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        await state.clear()
        return

    raw = (message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel", "/owner_panel"}:
        await state.clear()
        return await message.answer("Canceled.", reply_markup=_owner_panel_main_kb())

    data = await state.get_data()
    code = str(data.get("owner_pm_code") or "").strip()
    field = str(data.get("owner_pm_field") or "").strip()
    if not code or not field:
        await state.clear()
        return await message.answer("Settings context lost.", reply_markup=_owner_panel_main_kb())

    kwargs: dict = {}
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
    else:
        await state.clear()
        return await message.answer("Unknown field.")

    ok = await update_owner_payment_method(code, **kwargs)
    await state.clear()
    if not ok:
        return await message.answer("Method code not found.", reply_markup=_owner_panel_main_kb())

    method = await _find_owner_payment_method(code)
    if not method:
        return await message.answer("Updated. Failed to reload method details.", reply_markup=_owner_panel_main_kb())
    await message.answer(
        _owner_payment_method_details(method),
        reply_markup=_owner_payment_method_kb(code),
    )


@router.message(OwnerPanelFlow.waiting_provider_balance_threshold)
async def owner_provider_balance_threshold_apply(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel", "/owner_panel"}:
        await state.clear()
        return await message.answer("Canceled.", reply_markup=_owner_panel_main_kb())
    try:
        threshold = float(raw)
    except Exception:
        return await message.answer("Invalid value. Send numeric threshold only.")
    if threshold <= 0:
        return await message.answer("Threshold must be greater than zero.")

    updated = await set_provider_balance_alert_threshold(threshold)
    await state.clear()
    await message.answer(
        f"Provider balance alert threshold updated: {format_usd(updated)}",
        reply_markup=_owner_panel_main_kb(),
    )


@router.message(OwnerPanelFlow.waiting_numbers_markup)
async def owner_numbers_margin_apply(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel", "/owner_panel"}:
        await state.clear()
        return await message.answer("Canceled.", reply_markup=_owner_panel_main_kb())
    await state.clear()
    await message.answer(
        "Numbers margin is config-controlled.\n"
        f"Current: {_configured_numbers_markup_percent():.2f}%\n"
        "Update NUMBERS_SERVICE_MARKUP_PERCENT and restart the bot.",
        reply_markup=_owner_panel_main_kb(),
    )


@router.message(OwnerPanelFlow.waiting_digital_products_markup)
async def owner_digital_products_margin_apply(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel", "/owner_panel"}:
        await state.clear()
        return await message.answer("Canceled.", reply_markup=_owner_panel_main_kb())
    try:
        pct = float(raw)
    except Exception:
        return await message.answer("Invalid value. Send numeric percent only.")
    if pct < 0:
        return await message.answer("Percent must be >= 0.")

    applied = await set_digital_products_markup_percent(pct)
    await state.clear()
    await message.answer(
        f"Digital products margin updated: {applied:.2f}%",
        reply_markup=_owner_panel_main_kb(),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("owner_quick:info:"))
async def owner_quick_info(callback: types.CallbackQuery):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        return await callback.answer("Invalid selection", show_alert=True)
    rid_raw = parts[2]
    if not rid_raw.isdigit():
        return await callback.answer("Invalid reseller id", show_alert=True)
    rid = int(rid_raw)
    label = await _reseller_label(rid)
    main_balance = await get_reseller_wallet_balance(rid, wallet_type="main")
    earnings_balance = await get_reseller_wallet_balance(rid, wallet_type="earnings")
    pending_topups = await db.recharge_requests.count_documents(
        {
            "reseller_id": rid,
            "status": "pending",
            "wallet_type": {"$in": ["reseller_main", "main", "reseller"]},
        }
    )
    await callback.answer(
        f"{label}\nMain: {format_usd(main_balance)} | Earnings: {format_usd(earnings_balance)}\nPending topups: {pending_topups}",
        show_alert=True,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("owner_quick:run:"))
async def owner_quick_run(callback: types.CallbackQuery):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        return await callback.answer("Invalid action", show_alert=True)

    code = parts[2]
    rid_raw = parts[3]
    action = _OWNER_QUICK_CODE_TO_ACTION.get(code)
    if not action:
        return await callback.answer("Unknown action", show_alert=True)
    if not rid_raw.isdigit():
        return await callback.answer("Invalid reseller id", show_alert=True)
    rid = int(rid_raw)

    if action == "reseller_deposit":
        label = await _reseller_label(rid)
        if callback.message:
            await _safe_edit_text(
                callback.message,
                f"Reseller Deposit\n\nSelected: {label}\n\nChoose amount to add:",
                reply_markup=_owner_deposit_amount_kb(rid),
            )
        return await callback.answer()

    result = await _execute_owner_action(
        action=action,
        payload=str(rid),
        actor_id=int(callback.from_user.id),
    )
    if callback.message:
        await callback.message.answer(result)
        refreshed = await _collect_reseller_targets(force_refresh=True)
        await _safe_edit_text(
            callback.message,
            _owner_quick_menu_text(action, len(refreshed)),
            reply_markup=_owner_quick_action_kb(action, refreshed),
        )
    await callback.answer("Done")


@router.callback_query(lambda c: c.data and c.data.startswith("owner_quick:refresh:"))
async def owner_quick_refresh(callback: types.CallbackQuery):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        return await callback.answer("Invalid action", show_alert=True)

    code = parts[2]
    action = _OWNER_QUICK_CODE_TO_ACTION.get(code)
    if not action:
        return await callback.answer("Unknown action", show_alert=True)

    refreshed = await _collect_reseller_targets(force_refresh=True)
    if callback.message:
        await _safe_edit_text(
            callback.message,
            _owner_quick_menu_text(action, len(refreshed)),
            reply_markup=_owner_quick_action_kb(action, refreshed),
        )
    await callback.answer("Refreshed")


@router.callback_query(lambda c: c.data and c.data.startswith("owner_deposit:apply:"))
async def owner_deposit_apply(callback: types.CallbackQuery):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        return await callback.answer("Invalid action", show_alert=True)
    rid_raw = parts[2]
    amount_raw = parts[3]
    if not rid_raw.isdigit():
        return await callback.answer("Invalid reseller id", show_alert=True)
    try:
        amount = float(amount_raw)
    except Exception:
        return await callback.answer("Invalid amount", show_alert=True)
    if amount <= 0:
        return await callback.answer("Amount must be positive", show_alert=True)

    result = await _execute_owner_action(
        action="reseller_deposit",
        payload=f"{int(rid_raw)} {amount}",
        actor_id=int(callback.from_user.id),
    )
    if callback.message:
        await callback.message.answer(result)
        label = await _reseller_label(int(rid_raw))
        await _safe_edit_text(
            callback.message,
            f"Reseller Deposit\n\nSelected: {label}\n\nChoose amount to add:",
            reply_markup=_owner_deposit_amount_kb(int(rid_raw)),
        )
    await callback.answer("Done")


@router.callback_query(lambda c: c.data and c.data.startswith("owner_deposit:custom:"))
async def owner_deposit_custom_start(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        return await callback.answer("Invalid action", show_alert=True)
    rid_raw = parts[2]
    if not rid_raw.isdigit():
        return await callback.answer("Invalid reseller id", show_alert=True)
    rid = int(rid_raw)
    await state.set_state(OwnerPanelFlow.waiting_reseller_deposit_amount)
    await state.update_data(owner_deposit_reseller_id=rid)
    label = await _reseller_label(rid)
    if callback.message:
        await callback.message.answer(
            f"Send deposit amount for:\n{label}\n\nExample: 125.5\nOr send /cancel",
        )
    await callback.answer()


@router.message(OwnerPanelFlow.waiting_reseller_deposit_amount)
async def owner_deposit_custom_apply(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        return
    raw = (message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel", "/owner_panel"}:
        await state.clear()
        return await message.answer("Canceled.", reply_markup=_owner_panel_main_kb())

    data = await state.get_data()
    rid = int(data.get("owner_deposit_reseller_id") or 0)
    if rid <= 0:
        await state.clear()
        return await message.answer("Reseller context lost. Open panel again.")
    try:
        amount = float(raw)
    except Exception:
        return await message.answer("Invalid amount. Send numeric value only.")
    if amount <= 0:
        return await message.answer("Amount must be positive.")

    result = await _execute_owner_action(
        action="reseller_deposit",
        payload=f"{rid} {amount}",
        actor_id=int(message.from_user.id),
    )
    await state.clear()
    await message.answer(result)
    targets = await _collect_reseller_targets()
    await message.answer(
        _owner_quick_menu_text("reseller_deposit", len(targets)),
        reply_markup=_owner_quick_action_kb("reseller_deposit", targets),
    )


async def _execute_owner_action(*, action: str, payload: str, actor_id: int) -> str:
    parts = payload.split()

    if action == "resellers":
        ids = await _collect_reseller_ids()
        if not ids:
            return "No reseller accounts found."

        lines = []
        for rid in ids:
            main_bal = await get_reseller_wallet_balance(int(rid), wallet_type="main")
            earnings_bal = await get_reseller_wallet_balance(int(rid), wallet_type="earnings")
            user = await db.users.find_one({"telegram_id": int(rid)}, {"username": 1})
            username = (user or {}).get("username")
            suffix = f" (@{username})" if username else ""
            lines.append(f"{rid}{suffix}: main={format_usd(main_bal)} | earnings={format_usd(earnings_bal)}")
        return "\n".join(lines)

    if action == "reseller_deposit":
        if len(parts) != 2:
            return "Usage: <reseller_id_or_@username> <amount>"
        target, amount_raw = parts[0], parts[1]
        try:
            amount = float(amount_raw)
        except Exception:
            return "Invalid amount."
        if amount <= 0:
            return "Amount must be positive."
        if target.isdigit():
            rid = int(target)
        else:
            u = await get_user_by_username(target.lstrip("@"))
            if not u:
                return "User not found."
            rid = int(u.get("reseller_id") or u.get("telegram_id"))
        await credit_reseller_main_wallet(
            reseller_id=rid,
            amount=amount,
            reason="owner_reseller_deposit",
            actor_id=actor_id,
        )
        return f"Added {format_usd(amount)} to reseller {rid}"

    if action == "owner_exchange_rate":
        if len(parts) != 1:
            return "Usage: <local_per_dollar>"
        try:
            rate = float(parts[0])
        except Exception:
            return "Invalid exchange rate value."
        if rate <= 0:
            return "Exchange rate must be greater than zero."
        await set_owner_exchange_rate(rate)
        return f"Owner exchange rate updated: 1 💲 = {rate:.2f} local"

    return "Unknown action."


async def _run_owner_action_from_command(message: types.Message, action: str) -> None:
    if not await owner_only(message):
        return

    parts = (message.text or "").split()
    payload = " ".join(parts[1:]) if len(parts) > 1 else ""
    result = await _execute_owner_action(
        action=action,
        payload=payload,
        actor_id=message.from_user.id,
    )
    await message.answer(result)


@router.message(lambda msg: (msg.text or "").strip().lower() in _CLEAN_KEYBOARD_COMMANDS)
async def owner_clean_keyboard_command(message: types.Message, state: FSMContext):
    if not await owner_only(message):
        return
    await state.clear()
    await message.answer("Keyboard cleaned.", reply_markup=types.ReplyKeyboardRemove())
    await message.answer("Owner Panel", reply_markup=_owner_panel_main_kb())


@router.message(lambda msg: msg.text and msg.text.startswith('/reseller_deposit'))
async def reseller_deposit_command(message: types.Message):
    await _run_owner_action_from_command(message, "reseller_deposit")


@router.message(lambda msg: msg.text and msg.text.startswith('/resellers'))
async def resellers_command(message: types.Message):
    await _run_owner_action_from_command(message, "resellers")


@router.message(lambda msg: msg.text and msg.text.startswith('/activate_bot_subscription'))
async def activate_bot_subscription_command(message: types.Message):
    if not await owner_only(message):
        return
    parts = str(message.text or "").split()
    if len(parts) < 2:
        await message.answer("Usage: /activate_bot_subscription <bot_id> [1|6|12] [note]")
        return
    if not str(parts[1]).isdigit():
        await message.answer("bot_id must be numeric.")
        return
    bot_id = int(parts[1])
    months = 1
    note = None
    if len(parts) >= 3:
        if str(parts[2]).isdigit():
            months = int(parts[2])
            if len(parts) >= 4:
                note = " ".join(parts[3:]).strip() or None
        else:
            note = " ".join(parts[2:]).strip() or None
    if months not in {1, 6, 12}:
        await message.answer("Months must be one of: 1, 6, 12")
        return
    subscription = await activate_bot_subscription(bot_id, months=months, note=note)
    if not subscription:
        await message.answer("Bot not found.")
        return
    await message.answer(
        "Bot subscription activated\n\n"
        f"Bot ID: {bot_id}\n"
        f"Months: {months}\n"
        f"Renewal amount: {format_usd(float(subscription.get('renewal_charge_usd') or 0.0))}\n"
        f"Renewal plan: {int(subscription.get('renewal_plan_months') or 1)} month(s)\n"
        f"Status: {subscription.get('status')}\n"
        f"Subscription ends: {subscription.get('subscription_ends_at')}\n"
        f"Grace ends: {subscription.get('grace_ends_at')}"
    )


@router.callback_query(lambda c: c.data and c.data.startswith("support:reply_ticket:"))
async def support_owner_reply_open(callback: types.CallbackQuery, state: FSMContext):
    if int(callback.from_user.id) != int(OWNER_ID):
        await callback.answer("No permission.", show_alert=True)
        return
    ticket_id = str(callback.data or "").split(":", 2)[2].strip()
    ticket = await get_support_ticket(ticket_id)
    if not ticket:
        await callback.answer("Support ticket not found.", show_alert=True)
        return
    await state.clear()
    await state.set_state(SupportOwnerReplyFlow.waiting_message)
    await state.update_data(
        support_reply_user_id=int(ticket.get("user_id") or 0),
        support_reply_category=str(ticket.get("category") or ""),
        support_reply_ticket_id=str(ticket["_id"]),
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Send the reply now to user {int(ticket.get('user_id') or 0)} for {str(ticket.get('category') or '')}. Send /done when finished.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="/done")], [KeyboardButton(text="/cancel")]],
                resize_keyboard=True,
            ),
        )


@router.message(SupportOwnerReplyFlow.waiting_message)
async def support_owner_reply_router(message: types.Message, state: FSMContext):
    if int(message.from_user.id) != int(OWNER_ID):
        return
    raw = (message.text or "").strip().lower()
    if raw == "/done":
        await state.clear()
        await message.answer("Support reply session closed.", reply_markup=ReplyKeyboardRemove())
        return
    if raw == "/cancel":
        await state.clear()
        await message.answer("Support reply session cancelled.", reply_markup=ReplyKeyboardRemove())
        return

    data = await state.get_data()
    target_user_id = int(data.get("support_reply_user_id") or 0)
    ticket_id = str(data.get("support_reply_ticket_id") or "").strip()
    if target_user_id <= 0:
        await state.clear()
        await message.answer("Support reply session cancelled.", reply_markup=ReplyKeyboardRemove())
        return

    try:
        await message.copy_to(chat_id=target_user_id)
        if ticket_id:
            await mark_support_ticket_replied(ticket_id, actor_id=int(message.from_user.id))
        await message.answer("Reply sent to the user.", reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="/done")], [KeyboardButton(text="/cancel")]],
            resize_keyboard=True,
        ))
    except TelegramBadRequest:
        await message.answer("Reply could not be delivered to the user.")


@router.callback_query(lambda c: c.data and c.data.startswith("support:solve_ticket:"))
async def support_ticket_solve(callback: types.CallbackQuery):
    if int(callback.from_user.id) != int(OWNER_ID):
        await callback.answer("No permission.", show_alert=True)
        return
    ticket_id = str(callback.data or "").split(":", 2)[2].strip()
    ticket = await get_support_ticket(ticket_id)
    if not ticket:
        await callback.answer("Support ticket not found.", show_alert=True)
        return
    await mark_support_ticket_solved(ticket_id, actor_id=int(callback.from_user.id))
    try:
        await callback.bot.send_message(chat_id=int(ticket.get("user_id") or 0), text="Your support ticket has been marked as solved.")
    except Exception:
        pass
    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text="Solved", callback_data="support:ticket_solved")]
                    ]
                )
            )
        except Exception:
            pass
    await callback.answer("Ticket marked as solved.", show_alert=True)


@router.callback_query(lambda c: c.data == "support:ticket_solved")
async def support_ticket_solved_badge(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("custom_preorder:fulfill:"))
async def custom_preorder_fulfill_open(callback: types.CallbackQuery, state: FSMContext):
    if int(callback.from_user.id) != int(OWNER_ID):
        return await callback.answer("No permission.", show_alert=True)

    preorder_id = str(callback.data or "").split(":", 2)[2].strip()
    preorder = await get_preorder_request(preorder_id)
    if not preorder:
        return await callback.answer("Queue item not found.", show_alert=True)

    next_pending = await get_next_pending_preorder(preorder.get("endpoint_id"))
    if not next_pending:
        return await callback.answer("No pending preorder left.", show_alert=True)
    if str(next_pending.get("_id")) != preorder_id:
        position = await get_pending_preorder_position(preorder_id)
        return await callback.answer(f"FIFO enforced. This request is position #{position}.", show_alert=True)

    claimed = await mark_preorder_fulfilling(preorder_id, actor_id=int(callback.from_user.id))
    if not claimed:
        return await callback.answer("This preorder is already being handled.", show_alert=True)

    await state.clear()
    await state.set_state(CustomPreorderOwnerFlow.waiting_delivery)
    await state.update_data(
        preorder_id=preorder_id,
        preorder_user_id=int(preorder.get("buyer_user_id") or 0),
        preorder_order_id=str(preorder.get("order_id") or ""),
        preorder_service_name=str(preorder.get("service_name") or ""),
        preorder_endpoint_id=str(preorder.get("endpoint_id") or ""),
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Send the delivery payload now. The next message/file/photo/document will be copied to the user.\n"
            "Send /cancel to abort."
        )


@router.message(CustomPreorderOwnerFlow.waiting_delivery)
async def custom_preorder_delivery_router(message: types.Message, state: FSMContext):
    if int(message.from_user.id) != int(OWNER_ID):
        return
    raw = (message.text or "").strip().lower()
    if raw == "/cancel":
        preorder_id = str((await state.get_data()).get("preorder_id") or "").strip()
        if preorder_id:
            await reset_preorder_to_pending(preorder_id)
        await state.clear()
        await message.answer("Preorder delivery session cancelled.", reply_markup=ReplyKeyboardRemove())
        return

    data = await state.get_data()
    target_user_id = int(data.get("preorder_user_id") or 0)
    preorder_id = str(data.get("preorder_id") or "").strip()
    order_id = str(data.get("preorder_order_id") or "").strip()
    if target_user_id <= 0 or not preorder_id:
        await state.clear()
        return await message.answer("Preorder delivery session cancelled.", reply_markup=ReplyKeyboardRemove())

    try:
        await message.copy_to(chat_id=target_user_id)
        await mark_preorder_fulfilled(preorder_id, actor_id=int(message.from_user.id))
        if order_id:
            await update_order_details(ObjectId(order_id), {"custom_preorder": True, "status": "success"})
            await update_order_status(ObjectId(order_id), "success")
        await state.clear()
        await message.answer("Preorder delivered to the user.", reply_markup=ReplyKeyboardRemove())
    except TelegramBadRequest:
        await message.answer("Delivery could not be sent to the user.")







