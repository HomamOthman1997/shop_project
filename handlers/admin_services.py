from datetime import UTC, datetime

from datetime import timedelta

import re
from urllib.parse import parse_qs, urlparse

from aiogram import Router, types
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

from config import OWNER_ID
from database.financial_ledger import (
    confirm_settlement_payment,
    confirm_monthly_settlement,
    credit_reseller_main_wallet,
    generate_monthly_settlement_drafts,
    get_monthly_settlement_preview,
    get_reseller_wallet_balance,
    reconcile_recharge_requests_vs_ledger,
    scan_financial_anomalies,
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
from database.game_store_config_repo import (
    get_game_store_markup_percent,
    set_game_store_markup_percent,
)
from database.numbers_config_repo import (
    get_numbers_markup_percent,
    set_numbers_markup_percent,
)
from database.user_repo import get_user_by_username
from utils.permissions import owner_only
from utils.recharge_ui import format_owner_reseller_topup_text, owner_reseller_topup_review_kb
from utils.translations import t

router = Router()
_CLEAN_KEYBOARD_COMMANDS = {"/clean_keyboard", "/clean_kb", "/rkoff"}

_OWNER_QUICK_ACTIONS: dict[str, dict[str, str]] = {
    "reseller_deposit": {"code": "rdp", "button": "Deposit", "title": "Reseller Deposit"},
    "settlement_preview": {"code": "spv", "button": "Open Preview", "title": "Settlement Preview"},
    "confirm_settlement": {"code": "scf", "button": "Confirm", "title": "Confirm Settlement"},
    "settlement_history": {"code": "shs", "button": "History", "title": "Settlement History"},
    "reconcile_recharge": {"code": "rrc", "button": "Reconcile", "title": "Recharge Reconcile"},
    "financial_audit": {"code": "fad", "button": "Financial Audit", "title": "Financial Audit"},
    "confirm_settlement_payment": {"code": "scp", "button": "Confirm Payment", "title": "Confirm Settlement Payment"},
}
_OWNER_QUICK_CODE_TO_ACTION = {v["code"]: k for k, v in _OWNER_QUICK_ACTIONS.items()}

_RESELLER_TARGET_CACHE_TTL_SECONDS = 20
_reseller_targets_cache: dict[str, object] = {
    "expires_at": datetime.fromtimestamp(0, UTC),
    "targets": [],
}
_OWNER_USERS_PICKER_REQUEST_ID = 91001
_OWNER_CHAT_PICKER_REQUEST_ID = 91002


class OwnerPanelFlow(StatesGroup):
    waiting_payload = State()
    waiting_reseller_deposit_amount = State()
    waiting_owner_exchange_rate = State()
    waiting_owner_payment_method_value = State()
    waiting_numbers_markup = State()
    waiting_game_store_markup = State()
    waiting_provider_balance_threshold = State()


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
        {"owner_id": 1, "bot_id": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(None)
    bot_by_owner: dict[int, int] = {}
    for row in bot_rows:
        try:
            rid = int(row.get("owner_id"))
            bid = int(row.get("bot_id"))
        except Exception:
            continue
        if rid <= 0 or bid <= 0:
            continue
        if rid not in bot_by_owner:
            bot_by_owner[rid] = bid

    bot_meta_by_id: dict[int, dict] = {}
    bot_ids = sorted({int(x) for x in bot_by_owner.values() if int(x) > 0})
    if bot_ids:
        req_rows = await db.bot_creation_requests.find(
            {"payload.bot_id": {"$in": bot_ids}},
            {"payload.bot_id": 1, "payload.bot_username": 1, "payload.bot_title": 1, "created_at": 1},
        ).sort("created_at", -1).to_list(None)
        for row in req_rows:
            payload = row.get("payload") or {}
            try:
                bid = int(payload.get("bot_id"))
            except Exception:
                continue
            if bid in bot_meta_by_id:
                continue
            bot_meta_by_id[bid] = {
                "username": str(payload.get("bot_username") or "").strip(),
                "title": str(payload.get("bot_title") or "").strip(),
            }

    targets: list[dict] = []
    for rid in reseller_ids:
        rid = int(rid)
        uname = username_by_id.get(rid, "")
        bot_id = bot_by_owner.get(rid)
        if bot_id:
            meta = bot_meta_by_id.get(bot_id, {})
            bot_username = str(meta.get("username") or "").strip()
            bot_title = str(meta.get("title") or "").strip()
            if bot_username:
                label = f"@{bot_username}"
            elif bot_title:
                label = bot_title
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
            types.InlineKeyboardButton(text="+10$", callback_data=f"owner_deposit:apply:{rid}:10"),
            types.InlineKeyboardButton(text="+25$", callback_data=f"owner_deposit:apply:{rid}:25"),
            types.InlineKeyboardButton(text="+50$", callback_data=f"owner_deposit:apply:{rid}:50"),
        ],
        [
            types.InlineKeyboardButton(text="+100$", callback_data=f"owner_deposit:apply:{rid}:100"),
            types.InlineKeyboardButton(text="+250$", callback_data=f"owner_deposit:apply:{rid}:250"),
            types.InlineKeyboardButton(text="+500$", callback_data=f"owner_deposit:apply:{rid}:500"),
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
            [types.InlineKeyboardButton(text="Set Currency (USD/SYP)", callback_data=f"owner_pm:set:currency:{code}")],
            [types.InlineKeyboardButton(text="Enable/Disable Method", callback_data=f"owner_pm:set:enabled:{code}")],
            [types.InlineKeyboardButton(text="Set Support", callback_data=f"owner_pm:set:support:{code}")],
            [types.InlineKeyboardButton(text="Set Instructions", callback_data=f"owner_pm:set:text:{code}")],
            [types.InlineKeyboardButton(text="Set Per-Credit Rate", callback_data=f"owner_pm:set:rate:{code}")],
            [types.InlineKeyboardButton(text="Back to Methods", callback_data="owner_pm:open")],
        ]
    )


def _owner_payment_methods_text(methods: list[dict], exchange_rate: float) -> str:
    lines = [
        "Owner Payment Methods (Global for all resellers)\n",
        f"Owner Exchange Rate: 1 USD = {exchange_rate:.2f} SYP\n",
    ]
    for method in methods:
        lines.append(
            f"- {method.get('code')}: {method.get('title')} | "
            f"{str(method.get('currency', 'USD')).upper()} | "
            f"per_credit={float(method.get('per_credit', 1.0)):.4f}"
        )
    lines.append("\nSelect method below to edit.")
    return "\n".join(lines)


def _owner_payment_method_details(method: dict) -> str:
    rendered = str(method.get("instructions") or "")
    if len(rendered) > 700:
        rendered = rendered[:700] + "..."
    return (
        "Owner Payment Method\n\n"
        f"Code: {method.get('code')}\n"
        f"Title: {method.get('title')}\n"
        f"Currency: {str(method.get('currency', 'USD')).upper()}\n"
        f"Enabled: {bool(method.get('enabled', True))}\n"
        f"Per Credit: {float(method.get('per_credit', 1.0)):.4f}\n"
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


def _current_cycle_key() -> str:
    now = datetime.now(UTC)
    return f"{now.year}-{now.month:02d}"


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
    kb.button(text="Finance", callback_data="owner_panel:cat:financial")
    kb.button(text="Settlements", callback_data="owner_panel:cat:settlements")
    kb.button(text="Audit", callback_data="owner_panel:cat:audit")
    kb.button(text="System", callback_data="owner_panel:cat:system")
    kb.adjust(1, 2, 2)
    return kb.as_markup()


def _owner_panel_category_kb(category: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if category == "financial":
        kb.button(text="Reseller Deposit", callback_data="owner_panel:act:reseller_deposit")
        kb.button(text="List Resellers", callback_data="owner_panel:act:resellers")
        kb.button(text="Reseller Topup Requests", callback_data="owner_panel:act:reseller_topup_requests")
        kb.button(text="Owner Payment Methods", callback_data="owner_panel:act:owner_payment_methods")
        kb.button(text="Owner Exchange Rate", callback_data="owner_panel:act:owner_exchange_rate")
        kb.button(text="Numbers Margin %", callback_data="owner_panel:act:numbers_margin")
        kb.button(text="Game Store Margin %", callback_data="owner_panel:act:game_store_margin")
        kb.adjust(1, 1, 1, 1, 1, 1, 1)
    elif category == "settlements":
        kb.button(text="Settlement Preview", callback_data="owner_panel:act:settlement_preview")
        kb.button(text="Confirm Settlement", callback_data="owner_panel:act:confirm_settlement")
        kb.button(text="Settlement History", callback_data="owner_panel:act:settlement_history")
        kb.button(text="Generate Drafts", callback_data="owner_panel:act:generate_settlement_drafts")
        kb.button(text="Confirm Payment", callback_data="owner_panel:act:confirm_settlement_payment")
        kb.adjust(2, 2, 1)
    elif category == "audit":
        kb.button(text="Recharge Reconcile", callback_data="owner_panel:act:reconcile_recharge")
        kb.button(text="Financial Audit", callback_data="owner_panel:act:financial_audit")
        kb.adjust(1)
    elif category == "system":
        kb.button(text="Bind Owner Target Here", callback_data="owner_panel:act:bind_owner_target_here")
        kb.button(text="Bind Owner Target By Link", callback_data="owner_panel:act:bind_owner_target_link")
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
        "settlement_preview": "Send: <reseller_id> [YYYY-MM]\nExample: 7731488539 2026-03",
        "confirm_settlement": "Send: <reseller_id> [YYYY-MM]\nExample: 7731488539 2026-03",
        "settlement_history": "Send: <reseller_id> [limit]\nExample: 7731488539 6",
        "generate_settlement_drafts": "Send optional cycle: [YYYY-MM]\nExample: 2026-03\nOr send: now",
        "reconcile_recharge": "Send: <reseller_id> [YYYY-MM] [max_rows]\nExample: 7731488539 2026-03 20",
        "financial_audit": "Send optional args: [days] [max_rows]\nExample: 30 20",
        "confirm_settlement_payment": "Send: <reseller_id> [YYYY-MM] [note]\nExample: 7731488539 2026-03 paid_by_bank",
        "owner_exchange_rate": "Send: <SYP_per_USD>\nExample: 13250",
        "bind_owner_target_link": (
            "Send topic target in one of these formats:\n"
            "- Topic link: https://t.me/c/<chat>/<msg>?thread=<topic_id>\n"
            "- chat/topic ids: -1001234567890 44\n"
            "- chat id only: -1001234567890"
        ),
    }
    return prompts.get(action, "Send input payload for this action.")


def _parse_owner_target_payload(payload: str) -> tuple[int, int | None] | None:
    text = (payload or "").strip()
    if not text:
        return None

    m = re.fullmatch(r"(-100\d+)\s*[:\s,|]\s*(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.fullmatch(r"(-100\d+)", text)
    if m:
        return int(m.group(1)), None

    candidate = text
    if candidate.startswith("t.me/") or candidate.startswith("telegram.me/"):
        candidate = "https://" + candidate
    if not (candidate.startswith("http://") or candidate.startswith("https://")):
        return None

    parsed = urlparse(candidate)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in {"t.me", "telegram.me"}:
        return None

    parts = [x for x in (parsed.path or "").split("/") if x]
    if len(parts) < 2 or parts[0] != "c" or (not parts[1].isdigit()):
        return None

    chat_id = int(f"-100{parts[1]}")
    thread_id = None
    query = parse_qs(parsed.query or "")
    for key in ("thread", "topic", "comment"):
        value = (query.get(key) or [None])[0]
        if value is not None and str(value).isdigit():
            thread_id = int(value)
            break

    if thread_id is None and len(parts) >= 4 and parts[3].isdigit():
        thread_id = int(parts[3])

    return chat_id, thread_id


async def _build_owner_dashboard_text() -> str:
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
    settlements_overdue = await db.settlements.count_documents(
        {"payment_status": {"$in": ["pending", "overdue"]}, "services_locked": True}
    )
    numbers_orders_open = await db.orders.count_documents(
        {"service_type": {"$in": ["temp", "rental"]}, "status": {"$in": ["pending", "paid", "active", "waiting_code"]}}
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

    audit = await scan_financial_anomalies(days=7, max_rows=1)
    balance_cfg = await get_provider_balance_alert_settings()
    logs_target = await get_bot_logs_target()
    owner_target = await db.system_settings.find_one({"_id": "owner_notifications"}) or {}

    owner_target_txt = (
        f"{owner_target.get('chat_id')} / topic {owner_target.get('message_thread_id') or '-'}"
        if isinstance(owner_target.get("chat_id"), int)
        else "not bound"
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
        f"Active reseller owners: {len(reseller_ids)}\n"
        f"Active bots: {active_bots}\n"
        f"Open numbers orders: {numbers_orders_open}\n\n"
        f"Reseller main wallets total: ${reseller_main_total:.2f}\n"
        f"Reseller earnings wallets total: ${reseller_earnings_total:.2f}\n\n"
        f"Pending reseller topups: {pending_reseller_topups}\n"
        f"Pending user topups: {pending_user_topups}\n"
        f"Need-more-proof requests: {need_more_proof}\n"
        f"Locked overdue settlements: {settlements_overdue}\n\n"
        "Audit snapshot (7d)\n"
        f"- Negative wallets: {audit['negative_wallets_count']}\n"
        f"- Orders missing ledger: {audit['orders_missing_ledger_count']}\n"
        f"- Accepted recharges missing ledger: {audit['accepted_recharges_without_ledger_count']}\n\n"
        "Routing\n"
        f"- Owner target: {owner_target_txt}\n"
        f"- Provider alert target: {provider_target_txt}\n"
        f"- Logs target: {logs_target_txt}\n"
        f"- Provider alert enabled: {bool(balance_cfg.get('enabled'))}\n"
        f"- Provider alert threshold: {float(balance_cfg.get('threshold_usd') or 0.0):.2f}$"
    )


@router.message(lambda msg: (msg.text or "").strip() in {"/owner", "/owner_panel"})
async def owner_panel_open_command(message: types.Message):
    if not await owner_only(message):
        return
    await _hide_owner_reply_keyboard(message)
    await message.answer(
        await _build_owner_dashboard_text(),
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
            await _build_owner_dashboard_text(),
            reply_markup=_owner_panel_main_kb(),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("owner_panel:cat:"))
async def owner_panel_category(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner_callback(callback):
        return await callback.answer("No permission", show_alert=True)
    category = (callback.data or "").split(":", 2)[2]
    await state.clear()
    if callback.message:
        await _hide_owner_reply_keyboard(callback.message)
        hints = {
            "financial": "Finance / deposits and wallet operations.",
            "settlements": "Settlement workflows per reseller bot (button-driven).",
            "audit": "Audit and reconciliation operations.",
            "system": "System routing and owner target settings.",
        }
        await _safe_edit_text(
            callback.message,
            f"Owner Panel / {category.title()}\n\n{hints.get(category, '')}",
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
                reply_markup=_owner_panel_main_kb(),
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
                f"threshold={float(current.get('threshold_usd') or 0):.2f}$"
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

        logging.getLogger("owner.logs").error("Owner test log: manual test from owner panel.")
        if callback.message:
            await callback.message.answer("Test log emitted. Check the bound logs topic.")
        return await callback.answer("Sent")

    if action == "provider_balance_threshold":
        current = await get_provider_balance_alert_settings()
        await state.set_state(OwnerPanelFlow.waiting_provider_balance_threshold)
        if callback.message:
            await callback.message.answer(
                "Send provider balance alert threshold in USD now.\n"
                f"Current: {float(current.get('threshold_usd') or 0):.2f}$\n"
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
                f"Threshold: {float(current.get('threshold_usd') or 0):.2f}$"
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
                "Send owner USD/SYP exchange rate now.\n"
                f"Current: {current:.2f}\n\n"
                "This rate is shared globally for all resellers using owner payment methods."
            )
        return await callback.answer()

    if action == "numbers_margin":
        await state.set_state(OwnerPanelFlow.waiting_numbers_markup)
        current = await get_numbers_markup_percent(25.0)
        if callback.message:
            await callback.message.answer(
                "Send numbers margin percent now (global).\n"
                f"Current: {current:.2f}%\n"
                "Example: 25"
            )
        return await callback.answer()

    if action == "game_store_margin":
        await state.set_state(OwnerPanelFlow.waiting_game_store_markup)
        current = await get_game_store_markup_percent(2.0)
        if callback.message:
            await callback.message.answer(
                "Send game store margin percent now (global).\n"
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
    await state.clear()
    methods = await get_owner_payment_methods()
    rate = await get_owner_exchange_rate()
    if callback.message:
        await _safe_edit_text(
            callback.message,
            _owner_payment_methods_text(methods, rate),
            reply_markup=_owner_payment_methods_kb(methods),
        )
    await callback.answer()


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
            "Send owner USD/SYP exchange rate now.\n"
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
        "currency": "Send currency code: USD or SYP",
        "enabled": "Send method status: on/off",
        "support": "Send support username (example: @support_user).",
        "text": "Send full instructions text now.",
        "rate": "Send new per-credit value (numeric, > 0).",
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
        f"Owner exchange rate updated: 1 USD = {rate:.2f} SYP",
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
            return await message.answer("Invalid currency. Send USD or SYP.")
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
            return await message.answer("Invalid rate value.")
        if value <= 0:
            return await message.answer("Rate must be greater than zero.")
        kwargs["per_credit"] = value
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
        f"Provider balance alert threshold updated: {updated:.2f}$",
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
    try:
        pct = float(raw)
    except Exception:
        return await message.answer("Invalid value. Send numeric percent only.")
    if pct < 0:
        return await message.answer("Percent must be >= 0.")

    applied = await set_numbers_markup_percent(pct)
    await state.clear()
    await message.answer(
        f"Numbers margin updated: {applied:.2f}%",
        reply_markup=_owner_panel_main_kb(),
    )


@router.message(OwnerPanelFlow.waiting_game_store_markup)
async def owner_game_store_margin_apply(message: types.Message, state: FSMContext):
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

    applied = await set_game_store_markup_percent(pct)
    await state.clear()
    await message.answer(
        f"Game store margin updated: {applied:.2f}%",
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
        f"{label}\nMain: {main_balance:.2f}$ | Earnings: {earnings_balance:.2f}$\nPending topups: {pending_topups}",
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
            lines.append(f"{rid}{suffix}: main={main_bal:.2f}$ | earnings={earnings_bal:.2f}$")
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
        return f"Added {amount:.2f}$ to reseller {rid}"

    if action == "owner_exchange_rate":
        if len(parts) != 1:
            return "Usage: <SYP_per_USD>"
        try:
            rate = float(parts[0])
        except Exception:
            return "Invalid exchange rate value."
        if rate <= 0:
            return "Exchange rate must be greater than zero."
        await set_owner_exchange_rate(rate)
        return f"Owner exchange rate updated: 1 USD = {rate:.2f} SYP"

    if action == "settlement_preview":
        if len(parts) not in {1, 2}:
            return "Usage: <reseller_id> [YYYY-MM]"
        if not parts[0].isdigit():
            return "reseller_id must be numeric."
        reseller_id = int(parts[0])
        cycle_key = _parse_cycle_key_or_none(parts[1]) if len(parts) == 2 else _current_cycle_key()
        if cycle_key is None:
            return "Cycle must be YYYY-MM."
        preview = await get_monthly_settlement_preview(reseller_id=reseller_id, cycle_key=cycle_key)
        return (
            "Settlement Preview\n\n"
            f"Reseller: {reseller_id}\nCycle: {cycle_key}\n"
            f"Core Commissions: {preview['core_commissions']:.2f}$\n"
            f"Custom Profit: {preview['custom_profit']:.2f}$\n"
            f"Owner Fees: {preview['owner_fees']:.2f}$\n"
            f"Net Due (period): {preview['net_due']:.2f}$\n"
            f"Current Earnings Wallet: {preview['current_earnings_wallet']:.2f}$"
        )

    if action == "confirm_settlement":
        if len(parts) not in {1, 2}:
            return "Usage: <reseller_id> [YYYY-MM]"
        if not parts[0].isdigit():
            return "reseller_id must be numeric."
        reseller_id = int(parts[0])
        cycle_key = _parse_cycle_key_or_none(parts[1]) if len(parts) == 2 else _current_cycle_key()
        if cycle_key is None:
            return "Cycle must be YYYY-MM."
        doc = await confirm_monthly_settlement(reseller_id=reseller_id, cycle_key=cycle_key, owner_id=actor_id)
        return (
            "Settlement Confirmed\n\n"
            f"Reseller: {reseller_id}\nCycle: {cycle_key}\n"
            f"Net Due: {float(doc.get('net_due', 0)):.2f}$\n"
            f"Anchor TX: {doc.get('closing_anchor_tx_uuid') or '-'}"
        )

    if action == "settlement_history":
        if len(parts) not in {1, 2}:
            return "Usage: <reseller_id> [limit]"
        if not parts[0].isdigit():
            return "reseller_id must be numeric."
        reseller_id = int(parts[0])
        limit = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 6
        limit = max(1, min(limit, 24))
        rows = await db.settlements.find({"reseller_id": reseller_id}).sort("confirmed_at", -1).limit(limit).to_list(limit)
        if not rows:
            return "No settlements found for this reseller."
        lines = [f"Settlement history for {reseller_id}:"]
        for row in rows:
            lines.append(
                f"- {row.get('cycle_key')}: net_due={float(row.get('net_due', 0)):.2f}$ | "
                f"status={row.get('payment_status') or row.get('status')}"
            )
        return "\n".join(lines)

    if action == "generate_settlement_drafts":
        cycle_key = _current_cycle_key()
        if payload.lower() not in {"now", "current", "-"}:
            maybe = _parse_cycle_key_or_none(payload)
            if maybe is None:
                return "Cycle must be YYYY-MM, or send: now"
            cycle_key = maybe
        stats = await generate_monthly_settlement_drafts(cycle_key=cycle_key)
        return (
            "Settlement Draft Generation\n\n"
            f"Cycle: {stats['cycle_key']}\n"
            f"Total Resellers: {stats['total']}\n"
            f"Drafted/Updated: {stats['drafted']}\n"
            f"Skipped Confirmed: {stats['skipped_confirmed']}"
        )

    if action == "reconcile_recharge":
        if len(parts) not in {1, 2, 3}:
            return "Usage: <reseller_id> [YYYY-MM] [max_rows]"
        if not parts[0].isdigit():
            return "reseller_id must be numeric."
        reseller_id = int(parts[0])
        cycle_key = _previous_cycle_key()
        max_rows = 10
        if len(parts) >= 2:
            maybe_cycle = _parse_cycle_key_or_none(parts[1])
            if maybe_cycle is None and not parts[1].isdigit():
                return "Cycle must be YYYY-MM."
            if maybe_cycle is not None:
                cycle_key = maybe_cycle
            else:
                max_rows = max(1, min(int(parts[1]), 100))
        if len(parts) == 3:
            if not parts[2].isdigit():
                return "max_rows must be numeric."
            max_rows = max(1, min(int(parts[2]), 100))
        report = await reconcile_recharge_requests_vs_ledger(
            reseller_id=reseller_id,
            cycle_key=cycle_key,
            max_rows=max_rows,
        )
        return (
            "Recharge Reconciliation\n\n"
            f"Reseller: {reseller_id}\nCycle: {cycle_key}\n"
            f"Accepted Requests: {report['accepted_requests']}\n"
            f"Ledger Entries: {report['ledger_entries']}\n"
            f"Missing Ledger: {report['missing_ledger_count']}\n"
            f"Amount Mismatch: {report['amount_mismatch_count']}\n"
            f"Target Mismatch: {report['target_mismatch_count']}\n"
            f"Orphan Ledger: {report['orphan_ledger_count']}"
        )

    if action == "financial_audit":
        days = 30
        max_rows = 10
        if len(parts) >= 1 and parts[0]:
            if not parts[0].isdigit():
                return "days must be numeric."
            days = max(1, min(int(parts[0]), 365))
        if len(parts) >= 2 and parts[1]:
            if not parts[1].isdigit():
                return "max_rows must be numeric."
            max_rows = max(1, min(int(parts[1]), 100))
        report = await scan_financial_anomalies(days=days, max_rows=max_rows)
        lines = [
            "Financial Audit",
            "",
            f"Window: last {report['days']} days",
            f"Negative Wallets: {report['negative_wallets_count']}",
            f"Orders Missing Ledger: {report['orders_missing_ledger_count']}",
            f"Accepted Recharges Missing Ledger: {report['accepted_recharges_without_ledger_count']}",
            f"Locked Overdue Settlements: {report['locked_overdue_settlements_count']}",
        ]
        if report["negative_wallets"]:
            sample = report["negative_wallets"][0]
            lines.append(
                f"Sample negative wallet: {sample.get('owner_type')}:{sample.get('owner_id')} {sample.get('wallet_type')}={float(sample.get('balance', 0)):.2f}"
            )
        if report["orders_missing_ledger"]:
            sample = report["orders_missing_ledger"][0]
            lines.append(
                f"Sample order gap: {sample.get('order_id')} status={sample.get('status')} type={sample.get('service_type')}"
            )
        if report["accepted_recharges_without_ledger"]:
            sample = report["accepted_recharges_without_ledger"][0]
            lines.append(
                f"Sample recharge gap: {sample.get('request_id')} wallet={sample.get('wallet_type')} amount={float(sample.get('amount', 0)):.2f}"
            )
        if report["locked_overdue_settlements"]:
            sample = report["locked_overdue_settlements"][0]
            lines.append(
                f"Sample locked settlement: reseller={sample.get('reseller_id')} cycle={sample.get('cycle_key')} due={float(sample.get('net_due', 0)):.2f}"
            )
        return "\n".join(lines)

    if action == "confirm_settlement_payment":
        if len(parts) < 1:
            return "Usage: <reseller_id> [YYYY-MM] [note]"
        if not parts[0].isdigit():
            return "reseller_id must be numeric."
        reseller_id = int(parts[0])
        cycle_key = _previous_cycle_key()
        note = None
        if len(parts) >= 2:
            maybe_cycle = _parse_cycle_key_or_none(parts[1])
            if maybe_cycle is not None:
                cycle_key = maybe_cycle
                if len(parts) >= 3:
                    note = " ".join(parts[2:])
            else:
                note = " ".join(parts[1:])
        doc = await confirm_settlement_payment(
            reseller_id=reseller_id,
            cycle_key=cycle_key,
            owner_id=actor_id,
            note=note,
        )
        return (
            "Settlement Payment Confirmed\n\n"
            f"Reseller: {reseller_id}\n"
            f"Cycle: {cycle_key}\n"
            f"Amount due: {float(doc.get('net_due', 0)):.2f}$\n"
            f"Payment status: {doc.get('payment_status')}\n"
            f"Services locked: {bool(doc.get('services_locked'))}"
        )

    if action == "bind_owner_target_link":
        parsed = _parse_owner_target_payload(payload)
        if not parsed:
            return (
                "Invalid target format.\n"
                "Use topic link, or: -100CHAT_ID TOPIC_ID, or: -100CHAT_ID"
            )
        chat_id, thread_id = parsed
        await db.system_settings.update_one(
            {"_id": "owner_notifications"},
            {
                "$set": {
                    "chat_id": int(chat_id),
                    "message_thread_id": int(thread_id) if thread_id is not None else None,
                    "updated_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
        return (
            "Owner target updated.\n\n"
            f"chat_id={chat_id}\n"
            f"topic_id={thread_id or '-'}"
        )

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


@router.message(lambda msg: msg.text and msg.text.startswith('/settlement_preview'))
async def settlement_preview_command(message: types.Message):
    await _run_owner_action_from_command(message, "settlement_preview")


@router.message(lambda msg: msg.text and msg.text.startswith('/confirm_settlement'))
async def confirm_settlement_command(message: types.Message):
    await _run_owner_action_from_command(message, "confirm_settlement")


@router.message(lambda msg: msg.text and msg.text.startswith('/resellers'))
async def resellers_command(message: types.Message):
    await _run_owner_action_from_command(message, "resellers")

@router.message(lambda msg: msg.text and msg.text.startswith('/settlement_history'))
async def settlement_history_command(message: types.Message):
    await _run_owner_action_from_command(message, "settlement_history")


@router.message(lambda msg: msg.text and msg.text.startswith('/generate_settlement_drafts'))
async def generate_settlement_drafts_command(message: types.Message):
    await _run_owner_action_from_command(message, "generate_settlement_drafts")


@router.message(lambda msg: msg.text and msg.text.startswith('/reconcile_recharge'))
async def reconcile_recharge_command(message: types.Message):
    await _run_owner_action_from_command(message, "reconcile_recharge")


@router.message(lambda msg: msg.text and msg.text.startswith('/financial_audit'))
async def financial_audit_command(message: types.Message):
    await _run_owner_action_from_command(message, "financial_audit")


@router.message(lambda msg: msg.text and msg.text.startswith('/confirm_settlement_payment'))
async def confirm_settlement_payment_command(message: types.Message):
    await _run_owner_action_from_command(message, "confirm_settlement_payment")







