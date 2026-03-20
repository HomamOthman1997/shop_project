from __future__ import annotations

import asyncio
import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from rapidfuzz import fuzz

from config import settings
from database.bots_repo import get_reseller_id_for_bot
from database.custom_services_repo import ensure_root_node, list_children
from database.financial_ledger import create_order_v3, get_user_wallet_balance
from database.game_store_config_repo import get_game_store_markup_percent
from database.mongo import db
from database.orders_repo import update_order_details, update_order_status
from database.reseller_settings_repo import get_exchange_rate
from database.user_repo import get_user, get_user_reseller_for_bot, set_user_reseller_for_bot
from keyboards.main_menu_kb import main_menu
from services.game_store.g2bulk_client import G2BulkClient
from services.game_store.catalog_service import get_catalog_snapshot, get_game_topups
from utils.financial_manager import FinancialManager
from utils.translations import t

router = Router()

TWOPLACES = Decimal("0.01")

_CATALOG_ID_INFO = "id_info"
_GAME_USAGE_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "game_search_usage.json"))
_GAME_DEFAULT_ORDER = ("pubg", "mobile legends", "free fire", "honor of kings", "new state")
_GAME_KEYWORDS = (
    "pubg",
    "free fire",
    "mobile legends",
    "honor of kings",
    "new state",
    "newstate",
    "cod",
    "call of duty",
    "ludo",
    "mlbb",
    "genshin",
    "roblox",
    "fortnite",
    "valorant",
)

_PRIORITY_GIFTCARD_BRANDS = (
    "discord",
    "imo",
    "itunes",
    "jawaker",
    "nintendo",
    "playstation",
    "razer",
    "roblox",
    "steam",
    "xbox",
    "yalla ludo",
)


class GameStoreFlow(StatesGroup):
    waiting_topup_player = State()
    waiting_topup_server = State()


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _money_decimal(value: Any) -> Decimal:
    return _to_decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _apply_markup_decimal(price: Any, markup_percent: Any) -> Decimal:
    base = _money_decimal(price)
    pct = _to_decimal(markup_percent)
    if pct <= 0:
        return base
    multiplier = Decimal("1") + (pct / Decimal("100"))
    return (base * multiplier).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _norm(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _natural_sort_key(text: str) -> list[Any]:
    raw = _norm(text)
    parts = re.split(r"(\d+)", raw)
    key: list[Any] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part)
    return key


async def _hide_reply_keyboard(message: types.Message, lang: str) -> None:
    try:
        sent = await message.answer(
            t(lang, "keyboard_cleanup_placeholder"),
            reply_markup=ReplyKeyboardRemove(),
        )
        try:
            await sent.delete()
        except Exception:
            pass
    except Exception:
        pass


def _is_games_trigger(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    exact = {
        t("en", "btn_games_topups"),
        t("ar", "btn_games_topups"),
        "game top-ups",
        "games",
        "topups",
        "/games",
    }
    return raw in exact or lowered in exact


def _is_store_trigger(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    exact = {
        t("en", "btn_store"),
        t("ar", "btn_store"),
        "game store",
        "/store",
    }
    return raw in exact or lowered in exact


def _is_giftcards_trigger(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    exact = {
        t("en", "btn_giftcards"),
        t("ar", "btn_giftcards"),
        "giftcards & vouchers",
        "giftcards",
        "vouchers",
        "/giftcards",
    }
    return raw in exact or lowered in exact


def _is_game_category(name: str | None) -> bool:
    text = _norm(name)
    return bool(text) and any(k in text for k in _GAME_KEYWORDS)


def _simplify_gift_name(name: str | None) -> str:
    label = str(name or "").strip()
    if not label:
        return "-"
    label = re.sub(r"\([^)]*\)", " ", label, flags=re.IGNORECASE)
    label = re.sub(r"\b(gift\s*cards?|giftcards?|vouchers?|voucher|accounts?)\b", " ", label, flags=re.IGNORECASE)
    label = re.sub(r"\b(official|usa|us|uk|eu)\b", " ", label, flags=re.IGNORECASE)
    label = re.sub(r"\s+", " ", label).strip(" -|/")
    return label or str(name or "").strip()


def _is_priority_gift_brand(name: str | None) -> bool:
    n = _norm(name)
    if not n:
        return False
    return any(brand in n for brand in _PRIORITY_GIFTCARD_BRANDS)


def _brand_button_style(name: str | None) -> str:
    n = _norm(name)
    if not n:
        return "primary"
    # Green brands
    if any(k in n for k in ("xbox", "razer")):
        return "success"
    # Red brands
    if any(k in n for k in ("nintendo", "yalla ludo")):
        return "danger"
    # Blue brands
    return "primary"


def _prepare_gift_categories(categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize gift categories for cleaner UI:
    - remove obvious test/demo categories
    - deduplicate by cleaned display name
    - keep the category with higher product count when duplicates exist
    """
    dedup: dict[str, dict[str, Any]] = {}
    for cat in categories:
        cat_id = str(cat.get("id") or "").strip()
        if not cat_id:
            continue
        raw_name = str(cat.get("clean_name") or cat.get("name") or "-").strip()
        if not raw_name:
            continue
        n = _norm(raw_name)
        if any(k in n for k in ("test", "demo", "sample")):
            continue
        key = n
        current = dedup.get(key)
        if not current:
            dedup[key] = dict(cat)
            continue
        cur_count = _to_int(current.get("count"))
        new_count = _to_int(cat.get("count"))
        if new_count > cur_count:
            dedup[key] = dict(cat)
    prepared = list(dedup.values())
    prepared.sort(key=lambda c: _natural_sort_key(str(c.get("clean_name") or c.get("name") or "")))
    return prepared


def _gift_category_button(cat: dict[str, Any], *, force_blue: bool = False) -> InlineKeyboardButton:
    cat_id = str(cat.get("id") or "").strip()
    label = str(cat.get("clean_name") or cat.get("name") or "-").strip()[:28]
    if force_blue:
        return InlineKeyboardButton(text=label, callback_data=f"gst:giftcat:{cat_id}", style="primary")
    return InlineKeyboardButton(text=label, callback_data=f"gst:giftcat:{cat_id}")


def _build_gift_categories_rows(categories: list[dict[str, Any]]) -> list[list[InlineKeyboardButton]]:
    playstation: list[dict[str, Any]] = []
    steam: list[dict[str, Any]] = []
    itunes: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []

    for cat in categories:
        name = _norm(str(cat.get("clean_name") or cat.get("name") or ""))
        if "playstation" in name or "psn" in name:
            playstation.append(cat)
        elif "steam" in name:
            steam.append(cat)
        elif "itunes" in name or "apple" in name:
            itunes.append(cat)
        else:
            others.append(cat)

    rows: list[list[InlineKeyboardButton]] = []

    # iTunes pinned at the top as a single highlighted row.
    if itunes:
        rows.append([_gift_category_button(itunes[0], force_blue=True)])
        itunes = itunes[1:]

    # Keep PlayStation/Steam visually in one column (left) while preserving two-column layout.
    grouped_left = playstation + steam
    other_pool = list(others)
    for left_cat in grouped_left:
        row = [_gift_category_button(left_cat)]
        if other_pool:
            row.append(_gift_category_button(other_pool.pop(0)))
        rows.append(row)

    # Any additional iTunes variants stay blue and single.
    for cat in itunes:
        rows.append([_gift_category_button(cat, force_blue=True)])

    # Remaining categories as normal two-column grid.
    row: list[InlineKeyboardButton] = []
    for cat in other_pool:
        row.append(_gift_category_button(cat))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    return rows


async def _resolve_user_reseller(user_id: int, bot_id: int) -> int | None:
    reseller_id = await get_user_reseller_for_bot(user_id, bot_id)
    if reseller_id:
        return int(reseller_id)
    inferred = await get_reseller_id_for_bot(bot_id)
    if inferred:
        await set_user_reseller_for_bot(user_id, bot_id, int(inferred))
        return int(inferred)
    return None


async def _resolve_usd_to_syp_rate(bot_id: int) -> float:
    try:
        reseller_id = await get_reseller_id_for_bot(int(bot_id))
        if reseller_id:
            rate = float(await get_exchange_rate(int(reseller_id)))
            if rate > 0:
                return rate
    except Exception:
        pass
    return 118.0


async def _resolve_game_store_markup_percent() -> float:
    try:
        return float(await get_game_store_markup_percent(2.0))
    except Exception:
        return 2.0


def _fmt_dual_price(usd: float, usd_to_syp_rate: float) -> str:
    usd_value = _to_float(usd)
    syp = usd_value * max(1.0, _to_float(usd_to_syp_rate))
    return f"{usd_value:.2f}$ ({syp:.1f} SYP)"


def _extract_provider_error(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("error", "message", "msg", "error_message", "error_msg"):
            raw = str(payload.get(key) or "").strip()
            if raw:
                return raw[:200]
        nested = payload.get("data")
        if isinstance(nested, dict):
            for key in ("error", "message", "msg", "error_message", "error_msg"):
                raw = str(nested.get(key) or "").strip()
                if raw:
                    return raw[:200]
    if isinstance(payload, str) and payload.strip():
        return payload.strip()[:200]
    return "Provider request failed."


def _provider_ok(resp: dict[str, Any]) -> bool:
    status = _to_int(resp.get("status"))
    data = resp.get("data")
    if status < 200 or status >= 300:
        return False
    if isinstance(data, dict):
        success = data.get("success")
        if success in {False, 0, "0", "false", "False"}:
            return False
        if str(data.get("status") or "").strip().lower() in {"error", "failed", "fail"}:
            return False
        if any(str(data.get(k) or "").strip() for k in ("error", "error_message", "error_msg")):
            return False
    return True


def _extract_provider_status(payload: Any) -> str:
    if isinstance(payload, dict):
        nested = payload.get("data")
        if isinstance(nested, dict):
            for key in ("status", "order_status", "state"):
                raw = str(nested.get(key) or "").strip().lower()
                if raw:
                    return raw
        for key in ("status", "order_status", "state"):
            raw = str(payload.get(key) or "").strip().lower()
            if raw:
                return raw
    return ""


def _provider_status_is_success(payload: Any) -> bool:
    status = _extract_provider_status(payload)
    return status in {
        "success",
        "successful",
        "done",
        "completed",
        "complete",
        "finished",
        "fulfilled",
        "delivered",
        "paid",
    }


def _provider_status_is_failure(payload: Any) -> bool:
    status = _extract_provider_status(payload)
    return status in {
        "error",
        "failed",
        "fail",
        "cancelled",
        "canceled",
        "rejected",
        "expired",
        "refunded",
        "void",
    }


async def _poll_g2bulk_order_status(
    client: G2BulkClient,
    external_order_id: str,
    *,
    attempts: int = 5,
    delay_sec: float = 3.0,
) -> dict[str, Any] | None:
    if not str(external_order_id or "").strip():
        return None
    last_resp: dict[str, Any] | None = None
    for attempt in range(max(1, int(attempts))):
        last_resp = await client.get_order_status(external_order_id)
        if _provider_status_is_success(last_resp) or _provider_status_is_failure(last_resp):
            return last_resp
        if attempt < attempts - 1:
            await asyncio.sleep(max(0.0, float(delay_sec)))
    return last_resp


def _extract_external_order_id(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("order_id", "id", "invoice_id", "reference", "ref"):
            raw = str(payload.get(key) or "").strip()
            if raw:
                return raw
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("order_id", "id", "invoice_id", "reference", "ref"):
                raw = str(data.get(key) or "").strip()
                if raw:
                    return raw
    return ""


def _extract_voucher_lines(payload: Any) -> list[str]:
    lines: list[str] = []
    candidates: list[Any] = []
    if isinstance(payload, dict):
        candidates.extend(
            [
                payload.get("code"),
                payload.get("pin"),
                payload.get("voucher"),
                payload.get("voucher_code"),
                payload.get("cards"),
                payload.get("vouchers"),
                payload.get("codes"),
                payload.get("data"),
            ]
        )
    for item in candidates:
        if isinstance(item, str) and item.strip():
            lines.append(item.strip())
        elif isinstance(item, dict):
            for key in ("code", "pin", "voucher", "serial", "account", "password"):
                raw = str(item.get(key) or "").strip()
                if raw:
                    lines.append(f"{key.title()}: {raw}")
        elif isinstance(item, list):
            for row in item:
                if isinstance(row, str) and row.strip():
                    lines.append(row.strip())
                elif isinstance(row, dict):
                    parts: list[str] = []
                    for key in ("code", "pin", "voucher", "serial", "account", "password"):
                        raw = str(row.get(key) or "").strip()
                        if raw:
                            parts.append(f"{key.title()}: {raw}")
                    if parts:
                        lines.append(" | ".join(parts))
    unique: list[str] = []
    seen = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        unique.append(line)
    return unique[:5]


def _finance_error_text(code: str) -> str:
    mapping = {
        "INSUFFICIENT_USER_BALANCE": "Insufficient balance.",
        "INSUFFICIENT_RESELLER_MAIN": "Provider wallet is currently unavailable.",
        "LOCKED": "Please wait a second and try again.",
        "FINANCIAL_ERROR": "Financial processing failed, try again.",
    }
    return mapping.get(str(code or "").strip(), "Purchase failed.")


async def _core_charge(
    *,
    user_id: int,
    reseller_id: int,
    service_ref_id: str,
    sale_price: float,
    cost_price: float,
) -> tuple[dict[str, Any] | None, str | None]:
    sale_price = float(_money_decimal(sale_price))
    cost_price = float(_money_decimal(cost_price))
    order = await create_order_v3(
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        service_type="core_game_store",
        service_ref_id=str(service_ref_id),
        retail_amount=float(sale_price),
        wholesale_amount=float(cost_price),
        owner_fee_amount=0.0,
        reseller_profit_amount=0.0,
        status="pending",
    )
    order_id = order.get("_id")
    ok, reason = await FinancialManager.process_core_purchase(
        user_id=int(user_id),
        order_id=order_id,
        sale_price=float(sale_price),
        cost_price=float(cost_price),
        reseller_id=int(reseller_id),
    )
    if not ok:
        await update_order_status(order_id, "failed")
        return None, _finance_error_text(reason)
    await update_order_status(order_id, "paid")
    return order, None


async def _core_refund(
    *,
    user_id: int,
    reseller_id: int,
    order: dict[str, Any],
    sale_price: float,
    cost_price: float,
) -> None:
    sale_price = float(_money_decimal(sale_price))
    cost_price = float(_money_decimal(cost_price))
    order_id = order.get("_id")
    ok, _ = await FinancialManager.refund_core_purchase(
        user_id=int(user_id),
        order_id=order_id,
        sale_price=float(sale_price),
        cost_price=float(cost_price),
        reseller_id=int(reseller_id),
    )
    await update_order_status(order_id, "refunded" if ok else "failed")


async def _notify_owner_stock_issue(
    *,
    bot: types.Bot,
    user_id: int,
    reseller_id: int,
    item_name: str,
    provider_error: str,
) -> None:
    target_chat_id = None
    target_thread_id = None
    try:
        doc = await db.system_settings.find_one({"_id": "owner_notifications"})
        if isinstance((doc or {}).get("chat_id"), int):
            target_chat_id = int(doc["chat_id"])
            if isinstance(doc.get("message_thread_id"), int):
                target_thread_id = int(doc["message_thread_id"])
    except Exception:
        target_chat_id = None
        target_thread_id = None
    if target_chat_id is None:
        try:
            owner_id = int(getattr(settings, "owner_id", 0) or 0)
        except Exception:
            owner_id = 0
        if owner_id > 0:
            target_chat_id = owner_id
    if target_chat_id is None:
        return
    try:
        await bot.send_message(
            chat_id=int(target_chat_id),
            message_thread_id=int(target_thread_id) if target_thread_id is not None else None,
            text=(
                "Gift/Game store stock issue alert\n"
                f"User: {int(user_id)}\n"
                f"Reseller: {int(reseller_id)}\n"
                f"Item: {item_name}\n"
                f"Provider error: {provider_error[:300]}"
            ),
        )
    except Exception:
        pass


def _load_usage() -> dict[str, int]:
    try:
        with open(_GAME_USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): int(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _save_usage(data: dict[str, int]) -> None:
    try:
        os.makedirs(os.path.dirname(_GAME_USAGE_FILE), exist_ok=True)
        with open(_GAME_USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _increment_usage(name: str | None) -> None:
    key = _norm(name)
    if not key:
        return
    usage = _load_usage()
    usage[key] = int(usage.get(key, 0) or 0) + 1
    _save_usage(usage)


def _rank_games(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usage = _load_usage()
    scored: list[tuple[int, int, str, dict[str, Any]]] = []
    for node in nodes:
        name = str(node.get("name") or "")
        norm_name = _norm(name)
        count = int(usage.get(norm_name, 0))
        bias = 0
        for idx, k in enumerate(_GAME_DEFAULT_ORDER):
            if k in norm_name:
                bias = len(_GAME_DEFAULT_ORDER) - idx
                break
        scored.append((count, bias, norm_name, node))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [x[3] for x in scored]


def _grid(nodes: list[dict[str, Any]], *, columns: int = 3, simplify_gifts: bool = False) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for node in nodes:
        node_id = str(node.get("_id") or "").strip()
        if not node_id:
            continue
        raw_name = str(node.get("name") or "-")
        label = _simplify_gift_name(raw_name) if simplify_gifts else raw_name
        row.append(InlineKeyboardButton(text=label[:40], callback_data=f"cstm:open:{node_id}"))
        if len(row) >= columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def _product_grid(
    items: list[dict[str, Any]],
    *,
    callback_prefix: str,
    columns: int = 2,
    usd_to_syp_rate: float = 118.0,
    markup_percent: float = 0.0,
) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        price = float(_apply_markup_decimal(item.get("price"), markup_percent))
        name = str(item.get("clean_name") or item.get("name") or "-").strip()
        text = f"{name[:12]} | {_fmt_dual_price(price, usd_to_syp_rate)}" if price > 0 else name[:28]
        row.append(InlineKeyboardButton(text=text, callback_data=f"{callback_prefix}:{item_id}"))
        if len(row) >= columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def _gift_products_rows(
    products: list[dict[str, Any]],
    *,
    category_id: str,
    page: int,
    usd_to_syp_rate: float,
    markup_percent: float,
    force_blue: bool = False,
) -> tuple[list[list[InlineKeyboardButton]], int]:
    total = len(products)
    if total <= 0:
        return [], 1
    # Show one page for small lists, split to two pages only when list is large.
    split_threshold = 8
    if total <= split_threshold:
        per_page = total
        page_count = 1
    else:
        per_page = max(1, (total + 1) // 2)
        page_count = 2 if total > per_page else 1
    page = 0 if page <= 0 else 1
    if page_count == 1:
        page = 0
    start = page * per_page
    end = min(total, start + per_page)
    items = products[start:end]

    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        raw_name = str(item.get("name") or "-").strip()
        price = float(_apply_markup_decimal(item.get("price"), markup_percent))
        label = f"{raw_name} | Price: {_fmt_dual_price(price, usd_to_syp_rate)}"[:62]
        cb = f"gst:giftitem:{category_id}:{item_id}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=cb,
                    style="primary" if force_blue else _service_button_style(raw_name),
                )
            ]
        )
    return rows, page_count


def _service_button_style(name: str) -> str:
    return _brand_button_style(name)


@router.message(lambda m: _is_giftcards_trigger(m.text))
async def open_giftcards_section(message: types.Message, state):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    await _hide_reply_keyboard(message, lang)

    # Primary source: G2Bulk API catalogue.
    snapshot = await get_catalog_snapshot(force=False)
    if bool(snapshot.get("enabled")):
        categories = _prepare_gift_categories(list(snapshot.get("gift_categories") or []))
        if not categories:
            return await message.answer(t(lang, "store_no_gift_categories"), reply_markup=ReplyKeyboardRemove())
        rows = _build_gift_categories_rows(categories[:60])
        rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="cstm:cancel")])
        await message.answer(
            f"{t(lang, 'store_gift_title')}\n\n{t(lang, 'store_search_pick_hint')}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return

    # ID-INFO fallback is archived.
    return await message.answer(t(lang, "store_no_gift_categories"), reply_markup=ReplyKeyboardRemove())


@router.message(lambda m: _is_store_trigger(m.text))
async def open_store_hub(message: types.Message):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    await _hide_reply_keyboard(message, lang)
    rows = [
        [
            InlineKeyboardButton(text=t(lang, "store_btn_giftcards"), callback_data="gst:hub:gift", style="primary"),
            InlineKeyboardButton(text=t(lang, "store_btn_games"), callback_data="gst:hub:games", style="success"),
        ],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data="cstm:cancel", style="danger")],
    ]
    await message.answer(
        f"{t(lang, 'store_hub_title')}\n\n{t(lang, 'store_hub_hint')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.message(lambda m: _is_games_trigger(m.text))
async def open_games_section(message: types.Message, state):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    await _hide_reply_keyboard(message, lang)

    # Primary source: G2Bulk games API.
    snapshot = await get_catalog_snapshot(force=False)
    if bool(snapshot.get("enabled")):
        games = list(snapshot.get("games") or [])
        if not games:
            return await message.answer(t(lang, "store_no_game_categories"), reply_markup=ReplyKeyboardRemove())
        top = games[:5]
        kb_rows: list[list[InlineKeyboardButton]] = []
        row: list[InlineKeyboardButton] = []
        for g in top:
            gid = str(g.get("id") or "").strip()
            if not gid:
                continue
            row.append(InlineKeyboardButton(text=str(g.get("name") or "-")[:28], callback_data=f"gst:game:{gid}"))
            if len(row) >= 2:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)
        kb_rows.append([InlineKeyboardButton(text=t(lang, "store_more_games"), switch_inline_query_current_chat="game ")])
        kb_rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="cstm:cancel")])
        await message.answer(
            f"{t(lang, 'store_top_games_title')}\n\n{t(lang, 'store_search_pick_hint')}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        )
        return

    # ID-INFO fallback is archived.
    return await message.answer(t(lang, "store_no_game_categories"), reply_markup=ReplyKeyboardRemove())


@router.callback_query(lambda c: c.data == "gst:hub:gift")
async def open_store_hub_gift(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    snapshot = await get_catalog_snapshot(force=False)
    if bool(snapshot.get("enabled")):
        categories = _prepare_gift_categories(list(snapshot.get("gift_categories") or []))
        if not categories:
            await callback.answer(t(lang, "store_no_gift_categories"), show_alert=True)
            return
        rows = _build_gift_categories_rows(categories[:60])
        rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:hub:back", style="danger")])
        if callback.message:
            await callback.message.edit_text(
                f"{t(lang, 'store_gift_title')}\n\n{t(lang, 'store_search_pick_hint')}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
    else:
        await callback.answer(t(lang, "store_no_gift_categories"), show_alert=True)
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:hub:games")
async def open_store_hub_games(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    snapshot = await get_catalog_snapshot(force=False)
    if bool(snapshot.get("enabled")):
        games = list(snapshot.get("games") or [])
        if not games:
            await callback.answer(t(lang, "store_no_game_categories"), show_alert=True)
            return
        top = games[:5]
        kb_rows: list[list[InlineKeyboardButton]] = []
        row: list[InlineKeyboardButton] = []
        for g in top:
            gid = str(g.get("id") or "").strip()
            if not gid:
                continue
            row.append(InlineKeyboardButton(text=str(g.get("name") or "-")[:28], callback_data=f"gst:game:{gid}"))
            if len(row) >= 2:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)
        kb_rows.append([InlineKeyboardButton(text=t(lang, "store_more_games"), switch_inline_query_current_chat="game ")])
        kb_rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:hub:back", style="danger")])
        if callback.message:
            await callback.message.edit_text(
                f"{t(lang, 'store_top_games_title')}\n\n{t(lang, 'store_search_pick_hint')}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
            )
    else:
        await callback.answer(t(lang, "store_no_game_categories"), show_alert=True)
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:hub:back")
async def open_store_hub_back(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    rows = [
        [
            InlineKeyboardButton(text=t(lang, "store_btn_giftcards"), callback_data="gst:hub:gift", style="primary"),
            InlineKeyboardButton(text=t(lang, "store_btn_games"), callback_data="gst:hub:games", style="success"),
        ],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data="cstm:cancel", style="danger")],
    ]
    if callback.message:
        await callback.message.edit_text(
            f"{t(lang, 'store_hub_title')}\n\n{t(lang, 'store_hub_hint')}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    await callback.answer()


@router.inline_query(lambda iq: (iq.query or "").strip().lower().startswith("game"))
async def inline_games_search(iq: types.InlineQuery):
    user_id = int(getattr(iq.from_user, "id", 0) or 0)
    if user_id <= 0:
        return await iq.answer([], cache_time=5, is_personal=True)
    bot_id = (await iq.bot.get_me()).id

    snapshot = await get_catalog_snapshot(force=False)
    if bool(snapshot.get("enabled")):
        games = list(snapshot.get("games") or [])
        if not games:
            return await iq.answer([], cache_time=15, is_personal=True)
        q = re.sub(r"^\s*game\s*", "", str(iq.query or "").strip(), flags=re.IGNORECASE).strip().lower()
        scored: list[tuple[float, dict[str, Any]]] = []
        for game in games:
            name = str(game.get("name") or "")
            score = float(fuzz.partial_ratio(q, name.lower())) if q else 1.0
            if q and score < 45:
                continue
            scored.append((score, game))
        scored.sort(key=lambda x: -x[0])
        top = [x[1] for x in scored[:20]]
        if q and top:
            _increment_usage(str(top[0].get("name") or ""))

        results: list[types.InlineQueryResultArticle] = []
        for game in top:
            gid = str(game.get("id") or "").strip()
            name = str(game.get("name") or "-")
            if not gid:
                continue
            results.append(
                types.InlineQueryResultArticle(
                    id=f"g2_game_{gid}",
                    title=name,
                    description=t("en", "store_search_pick_hint"),
                    input_message_content=types.InputTextMessageContent(message_text=f"ðŸŽ® {name}"),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text=t("en", "store_search_pick_hint"), callback_data=f"gst:game:{gid}")]]
                    ),
                )
            )
        return await iq.answer(results, cache_time=10, is_personal=True)

    # ID-INFO legacy fallback is archived.
    return await iq.answer([], cache_time=10, is_personal=True)


@router.callback_query(lambda c: c.data and c.data.startswith("gst:giftcat:"))
async def open_g2bulk_gift_category(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    parts = str(callback.data or "").split(":")
    cat_id = str(parts[2]).strip() if len(parts) >= 3 else ""
    page = 0
    if len(parts) >= 4:
        try:
            page = int(parts[3])
        except Exception:
            page = 0
    if not cat_id:
        return await callback.answer("Category not found.", show_alert=True)
    snapshot = await get_catalog_snapshot(force=False)
    products = list((snapshot.get("products_by_category") or {}).get(cat_id) or [])
    if not products:
        return await callback.answer(t(lang, "store_no_gift_categories"), show_alert=True)
    products.sort(key=lambda x: _natural_sort_key(str(x.get("name") or x.get("clean_name") or "")))
    cat_name = ""
    for cat in list(snapshot.get("gift_categories") or []):
        if str(cat.get("id") or "").strip() == cat_id:
            cat_name = str(cat.get("clean_name") or cat.get("name") or "")
            break
    force_blue = any(k in _norm(cat_name) for k in ("itunes", "apple"))
    usd_to_syp_rate = await _resolve_usd_to_syp_rate(callback.bot.id)
    markup_percent = await _resolve_game_store_markup_percent()
    rows, page_count = _gift_products_rows(
        products[:60],
        category_id=cat_id,
        page=page,
        usd_to_syp_rate=usd_to_syp_rate,
        markup_percent=markup_percent,
        force_blue=force_blue,
    )
    if page_count > 1:
        if page <= 0:
            rows.append([InlineKeyboardButton(text="Next â–¶ï¸", callback_data=f"gst:giftcat:{cat_id}:1")])
        else:
            rows.append([InlineKeyboardButton(text="â—€ï¸ Prev", callback_data=f"gst:giftcat:{cat_id}:0")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:giftroot")])
    await callback.message.edit_text(t(lang, "store_gift_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:giftroot")
async def open_g2bulk_gift_root(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    snapshot = await get_catalog_snapshot(force=False)
    categories = _prepare_gift_categories(list(snapshot.get("gift_categories") or []))
    if not categories:
        return await callback.answer(t(lang, "store_no_gift_categories"), show_alert=True)
    rows = _build_gift_categories_rows(categories[:60])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="cstm:cancel")])
    await callback.message.edit_text(t(lang, "store_gift_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("gst:giftitem:"))
async def open_g2bulk_gift_item(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    parts = str(callback.data or "").split(":")
    if len(parts) < 4:
        return await callback.answer("Invalid product.", show_alert=True)
    cat_id = str(parts[2]).strip()
    product_id = str(parts[3]).strip()
    snapshot = await get_catalog_snapshot(force=False)
    found: dict[str, Any] | None = None
    for item in ((snapshot.get("products_by_category") or {}).get(cat_id) or []):
        if str(item.get("id") or "").strip() == product_id:
            found = item
            break
    if not found:
        return await callback.answer("Product not found.", show_alert=True)
    usd_to_syp_rate = await _resolve_usd_to_syp_rate(callback.bot.id)
    name = str(found.get("name") or "-")
    markup_percent = await _resolve_game_store_markup_percent()
    price = float(_apply_markup_decimal(found.get("price"), markup_percent))
    stock = int(found.get("stock") or 0)
    text = (
        f"{name}\n\n"
        f"Price: {_fmt_dual_price(price, usd_to_syp_rate)}\n"
        f"Stock: {stock}\n\n"
        "Confirm purchase?"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data=f"gst:giftconfirm:{cat_id}:{product_id}")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"gst:giftcat:{cat_id}:0")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("gst:game:"))
async def open_g2bulk_game(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    game_id = str(callback.data.split(":", 2)[2]).strip()
    items = await get_game_topups(game_id)
    if not items:
        return await callback.answer(t(lang, "store_no_game_categories"), show_alert=True)
    usd_to_syp_rate = await _resolve_usd_to_syp_rate(callback.bot.id)
    markup_percent = await _resolve_game_store_markup_percent()
    rows = _product_grid(
        items[:60],
        callback_prefix=f"gst:gameitem:{game_id}",
        columns=2,
        usd_to_syp_rate=usd_to_syp_rate,
        markup_percent=markup_percent,
    )
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:gameroot")])
    await callback.message.edit_text(t(lang, "store_top_games_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:gameroot")
async def open_g2bulk_games_root(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    snapshot = await get_catalog_snapshot(force=False)
    games = list(snapshot.get("games") or [])
    if not games:
        return await callback.answer(t(lang, "store_no_game_categories"), show_alert=True)
    top = games[:5]
    kb_rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for g in top:
        gid = str(g.get("id") or "").strip()
        if not gid:
            continue
        row.append(InlineKeyboardButton(text=str(g.get("name") or "-")[:28], callback_data=f"gst:game:{gid}"))
        if len(row) >= 2:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    kb_rows.append([InlineKeyboardButton(text=t(lang, "store_more_games"), switch_inline_query_current_chat="game ")])
    kb_rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="cstm:cancel")])
    await callback.message.edit_text(t(lang, "store_top_games_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("gst:gameitem:"))
async def open_g2bulk_game_item(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    parts = str(callback.data or "").split(":")
    if len(parts) < 4:
        return await callback.answer("Invalid package.", show_alert=True)
    game_id = str(parts[2]).strip()
    item_id = str(parts[3]).strip()
    items = await get_game_topups(game_id)
    found: dict[str, Any] | None = None
    for item in items:
        if str(item.get("id") or "").strip() == item_id:
            found = item
            break
    if not found:
        return await callback.answer("Top-up package not found.", show_alert=True)
    usd_to_syp_rate = await _resolve_usd_to_syp_rate(callback.bot.id)
    name = str(found.get("name") or "-")
    markup_percent = await _resolve_game_store_markup_percent()
    price = float(_apply_markup_decimal(found.get("price"), markup_percent))
    requires_server = bool(found.get("requires_server"))
    server_note = "Server ID required." if requires_server else "Server ID optional."
    text = (
        f"{name}\n\n"
        f"Price: {_fmt_dual_price(price, usd_to_syp_rate)}\n"
        f"{server_note}\n\n"
        "Press Buy and send your Player ID."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data=f"gst:buygame:{game_id}:{item_id}")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"gst:game:{game_id}")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("gst:giftconfirm:"))
async def confirm_g2bulk_gift_purchase(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    parts = str(callback.data or "").split(":")
    if len(parts) < 4:
        return await callback.answer("Invalid product.", show_alert=True)
    cat_id = str(parts[2]).strip()
    product_id = str(parts[3]).strip()

    snapshot = await get_catalog_snapshot(force=False)
    selected: dict[str, Any] | None = None
    for item in ((snapshot.get("products_by_category") or {}).get(cat_id) or []):
        if str(item.get("id") or "").strip() == product_id:
            selected = item
            break
    if not selected:
        return await callback.answer("Product not found.", show_alert=True)

    reseller_id = await get_reseller_id_for_bot(callback.bot.id)
    if not reseller_id:
        return await callback.answer("Reseller is not linked to this bot.", show_alert=True)

    stock = _to_int(selected.get("stock"))
    if stock <= 0:
        return await callback.answer("Out of stock.", show_alert=True)

    markup_percent = await _resolve_game_store_markup_percent()
    cost_price = float(_money_decimal(selected.get("price")))
    sale_price = float(_apply_markup_decimal(cost_price, markup_percent))
    order, err = await _core_charge(
        user_id=int(callback.from_user.id),
        reseller_id=int(reseller_id),
        service_ref_id=f"g2bulk:gift:{product_id}",
        sale_price=sale_price,
        cost_price=cost_price,
    )
    if not order or err:
        return await callback.answer(err or "Purchase failed.", show_alert=True)

    await callback.answer(t(lang, "processing_order"), show_alert=False)
    client = G2BulkClient()
    provider_resp = await client.create_voucher_order(product_id=product_id, quantity=1)
    if not _provider_ok(provider_resp):
        await _core_refund(
            user_id=int(callback.from_user.id),
            reseller_id=int(reseller_id),
            order=order,
            sale_price=sale_price,
            cost_price=cost_price,
        )
        error_text = _extract_provider_error(provider_resp.get("data") or provider_resp)
        await update_order_details(order["_id"], {"provider_response": provider_resp, "provider_error": error_text})
        await _notify_owner_stock_issue(
            bot=callback.bot,
            user_id=int(callback.from_user.id),
            reseller_id=int(reseller_id),
            item_name=str(selected.get("name") or f"Product {product_id}"),
            provider_error=error_text,
        )
        if callback.message:
            await callback.message.edit_text(
                "Out of stock right now.\n"
                "Admin has been notified.\n"
                "Please try again within 6 hours."
            )
            await callback.message.answer(t(lang, "main_menu"), reply_markup=main_menu(lang))
        return

    order_id_str = str(order.get("_id"))
    provider_data = provider_resp.get("data")
    external_order_id = _extract_external_order_id(provider_data)
    voucher_lines = _extract_voucher_lines(provider_data)

    await update_order_details(
        order["_id"],
        {
            "provider_code": "g2bulk",
            "provider_order_id": external_order_id,
            "provider_response": provider_resp,
            "delivery_lines": voucher_lines,
            "number_mode": "game_store",
        },
    )
    await update_order_status(order["_id"], "success")

    usd_to_syp_rate = await _resolve_usd_to_syp_rate(callback.bot.id)
    debit_line = f"Debited: {_fmt_dual_price(sale_price, usd_to_syp_rate)}"
    balance = await get_user_wallet_balance(callback.from_user.id, int(reseller_id))
    balance_line = f"Balance: {float(balance or 0):.2f}$"
    body = [f"âœ… Purchase complete", debit_line, balance_line, f"Order: {order_id_str}"]
    if external_order_id:
        body.append(f"Provider Ref: {external_order_id}")
    if voucher_lines:
        body.append("")
        body.append("Delivery:")
        body.extend([f"- {line}" for line in voucher_lines])
    await callback.message.edit_text(
        "\n".join(body),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="cstm:cancel")]
            ]
        ),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("gst:buygame:"))
async def start_g2bulk_game_checkout(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    parts = str(callback.data or "").split(":")
    if len(parts) < 4:
        return await callback.answer("Invalid package.", show_alert=True)
    game_id = str(parts[2]).strip()
    item_id = str(parts[3]).strip()
    items = await get_game_topups(game_id)
    selected: dict[str, Any] | None = None
    for item in items:
        if str(item.get("id") or "").strip() == item_id:
            selected = item
            break
    if not selected:
        return await callback.answer("Top-up package not found.", show_alert=True)

    await state.set_state(GameStoreFlow.waiting_topup_player)
    markup_percent = await _resolve_game_store_markup_percent()
    provider_price = _money_decimal(selected.get("price"))
    sale_price = _apply_markup_decimal(provider_price, markup_percent)
    await state.update_data(
        gst_pending_buy={
            "type": "game_topup",
            "game_id": game_id,
            "item_id": item_id,
            "name": str(selected.get("name") or "-"),
            "catalogue_name": str(selected.get("catalogue_name") or selected.get("name") or "-"),
            "provider_price": float(provider_price),
            "sale_price": float(sale_price),
            "requires_server": bool(selected.get("requires_server")),
        }
    )
    await callback.message.edit_text(
        "Send Player ID now:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"gst:game:{game_id}")],
                [InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="gst:buycancel")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:buycancel")
async def cancel_g2bulk_buy_flow(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await callback.message.edit_text(
        "Cancelled.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:gameroot")],
                [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="cstm:cancel")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:noop")
async def store_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.message(GameStoreFlow.waiting_topup_player)
async def g2bulk_collect_player_id(message: types.Message, state: FSMContext):
    player_id = str(message.text or "").strip()
    if not player_id:
        return await message.answer("Player ID cannot be empty. Send Player ID:")
    data = await state.get_data()
    pending = dict(data.get("gst_pending_buy") or {})
    if not pending:
        await state.clear()
        return await message.answer("Session expired. Start again.")
    pending["player_id"] = player_id
    await state.update_data(gst_pending_buy=pending)

    if bool(pending.get("requires_server")):
        await state.set_state(GameStoreFlow.waiting_topup_server)
        return await message.answer("Send Server ID now:")

    await state.clear()
    await _execute_g2bulk_game_purchase(message, pending, server_id="")


@router.message(GameStoreFlow.waiting_topup_server)
async def g2bulk_collect_server_id(message: types.Message, state: FSMContext):
    server_id = str(message.text or "").strip()
    if not server_id:
        return await message.answer("Server ID cannot be empty. Send Server ID:")
    data = await state.get_data()
    pending = dict(data.get("gst_pending_buy") or {})
    if not pending:
        await state.clear()
        return await message.answer("Session expired. Start again.")
    await state.clear()
    await _execute_g2bulk_game_purchase(message, pending, server_id=server_id)


async def _execute_g2bulk_game_purchase(message: types.Message, pending: dict[str, Any], *, server_id: str) -> None:
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    reseller_id = await get_reseller_id_for_bot((await message.bot.get_me()).id)
    if not reseller_id:
        return await message.answer("Reseller is not linked to this bot.")

    game_id = str(pending.get("game_id") or "").strip()
    item_id = str(pending.get("item_id") or "").strip()
    player_id = str(pending.get("player_id") or "").strip()
    name = str(pending.get("name") or "-")
    cost_price = float(_money_decimal(pending.get("provider_price", pending.get("sale_price", 0))))
    sale_price = float(_money_decimal(pending.get("sale_price", cost_price)))

    order, err = await _core_charge(
        user_id=int(message.from_user.id),
        reseller_id=int(reseller_id),
        service_ref_id=f"g2bulk:topup:{item_id}",
        sale_price=sale_price,
        cost_price=cost_price,
    )
    if not order or err:
        return await message.answer(err or "Purchase failed.")

    await message.answer(t(lang, "processing_order"), reply_markup=ReplyKeyboardRemove())
    client = G2BulkClient()
    provider_resp = await client.create_topup_order(
        product_id=item_id,
        player_id=player_id,
        server_id=server_id or None,
        quantity=1,
        game_code=game_id,
        catalogue_name=str(pending.get("catalogue_name") or name or "").strip(),
    )
    if not _provider_ok(provider_resp):
        await _core_refund(
            user_id=int(message.from_user.id),
            reseller_id=int(reseller_id),
            order=order,
            sale_price=sale_price,
            cost_price=cost_price,
        )
        error_text = _extract_provider_error(provider_resp.get("data") or provider_resp)
        await update_order_details(order["_id"], {"provider_response": provider_resp, "provider_error": error_text})
        await _notify_owner_stock_issue(
            bot=message.bot,
            user_id=int(message.from_user.id),
            reseller_id=int(reseller_id),
            item_name=name,
            provider_error=error_text,
        )
        await message.answer(
            "Out of stock right now.\n"
            "Admin has been notified.\n"
            "Please try again within 6 hours."
        )
        await message.answer(t(lang, "main_menu"), reply_markup=main_menu(lang))
        return

    provider_data = provider_resp.get("data")
    external_order_id = _extract_external_order_id(provider_data)
    details_payload = {
        "provider_code": "g2bulk",
        "provider_order_id": external_order_id,
        "provider_response": provider_resp,
        "game_id": game_id,
        "player_id": player_id,
        "server_id": server_id,
        "number_mode": "game_store",
    }
    await update_order_details(
        order["_id"],
        details_payload,
    )

    if not external_order_id:
        await update_order_details(
            order["_id"],
            {
                "provider_manual_review_required": True,
                "provider_error": "MISSING_PROVIDER_ORDER_ID",
            },
        )
        await _notify_owner_stock_issue(
            bot=message.bot,
            user_id=int(message.from_user.id),
            reseller_id=int(reseller_id),
            item_name=name,
            provider_error="G2Bulk accepted the request but did not return a verifiable order id.",
        )
        await message.answer(
            "Top-up request submitted and is awaiting provider confirmation.\n"
            "Admin has been notified to review it."
        )
        return

    status_resp = await _poll_g2bulk_order_status(client, external_order_id)
    if status_resp is not None:
        await update_order_details(
            order["_id"],
            {
                "provider_status_response": status_resp,
                "provider_status": _extract_provider_status(status_resp),
            },
        )

    if status_resp is not None and _provider_status_is_failure(status_resp):
        await _core_refund(
            user_id=int(message.from_user.id),
            reseller_id=int(reseller_id),
            order=order,
            sale_price=sale_price,
            cost_price=cost_price,
        )
        error_text = _extract_provider_error(status_resp.get("data") if isinstance(status_resp, dict) else status_resp)
        await update_order_details(order["_id"], {"provider_error": error_text})
        await message.answer(
            "Provider could not confirm this top-up.\n"
            "Your balance was refunded automatically."
        )
        return

    if not (status_resp is not None and _provider_status_is_success(status_resp)):
        await update_order_details(order["_id"], {"provider_manual_review_required": True})
        await _notify_owner_stock_issue(
            bot=message.bot,
            user_id=int(message.from_user.id),
            reseller_id=int(reseller_id),
            item_name=name,
            provider_error="Provider confirmation stayed pending after automatic polling.",
        )
        await message.answer(
            "Top-up request submitted and is still pending provider confirmation.\n"
            "Admin has been notified to follow it up."
        )
        return

    await update_order_status(order["_id"], "success")

    usd_to_syp_rate = await _resolve_usd_to_syp_rate((await message.bot.get_me()).id)
    balance = await get_user_wallet_balance(message.from_user.id, int(reseller_id))
    lines = [
        "âœ… Purchase complete",
        f"Item: {name}",
        f"Price: {_fmt_dual_price(sale_price, usd_to_syp_rate)}",
        f"Order: {order.get('_id')}",
        f"Balance: {float(balance or 0):.2f}$",
    ]
    if external_order_id:
        lines.append(f"Provider Ref: {external_order_id}")
    lines.append("Top-up request submitted successfully.")
    await message.answer("\n".join(lines))

