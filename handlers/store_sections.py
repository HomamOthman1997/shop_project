from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from uuid import uuid4

from bson import ObjectId

try:
    import pytz as _pytz
except Exception:
    _pytz = None


from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from rapidfuzz import fuzz

from config import settings
from database.bots_repo import get_reseller_id_for_bot, get_store_owner_scope_for_bot
from database.custom_services_repo import ensure_root_node, list_children
from database.financial_ledger import create_order_v3, get_user_wallet_balance
from database.digital_products_config_repo import get_digital_products_markup_percent
from database.mongo import db
from database.orders_repo import extract_order_amounts, update_order_details, update_order_status
from database.usage_stats_repo import increment_service_usage
from database.reseller_settings_repo import get_exchange_rate
from database.user_repo import get_user, get_user_reseller_for_bot, set_user_reseller_for_bot
from utils.bot_menu_context import is_digital_products_bot, is_main_bot, menu_for_current_bot
from services.digital_products.g2bulk_client import G2BulkClient
from services.digital_products.catalog_service import (
    digital_provider_enabled,
    extract_provider_offers,
    get_catalog_snapshot,
    get_game_topups,
)
from services.digital_products.fulfillment_rules import MANUAL_TOPUP_MODE, manual_feature_info
from services.digital_products.lona_cards import (
    MANUAL_FULFILLMENT_PROVIDER as LONA_CARD_PROVIDER,
    find_lona_product,
    is_lona_category_id,
    is_lona_managed_category_name,
    lona_categories,
    lona_products_for_category,
    lona_validation_message,
    parse_face_value,
    quote_lona_product,
    validate_lona_amount,
)
from services.digital_products.esim_access_client import EsimAccessClient
from services.digital_products.miniapp import consume_selection
from services.digital_products.za3em_client import Za3emClient
from services.digital_products.zendit_client import ZenditClient
from services.digital_products.esim_route_service import (
    available_days as esim_available_days,
    build_single_country_offers,
    build_single_country_offers_live,
    build_route_offers,
    build_route_offers_live,
    choose_recommended_offer,
    country_slug,
    offer_button_label as esim_offer_button_label,
    offer_summary as esim_offer_summary,
    plans_for_days as esim_plans_for_days,
    plans_for_usage as esim_plans_for_usage,
    route_available_days,
    route_available_days_live,
    search_countries as esim_search_countries,
    search_countries_live as esim_search_countries_live,
    single_country_plans,
    single_country_plans_live,
    usage_label as esim_usage_label,
)
from services.numbers.handlers.core_numbers import _compose_numbers_screen, render_preselected_temp_service_countries
from services.numbers.keyboards.core_numbers_kb import number_type_kb
from services.numbers.states.core_numbers_states import NumberFlow
from utils.core_service_guard import finance_error_public_text, guard_core_service_callback, guard_core_service_message
from utils.financial_manager import FinancialManager
from utils.translations import t
from utils.user_money import format_usd

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

_GAME_TOPUP_HINTS = (
    "diamond",
    "diamonds",
    "gold",
    "gems",
    "gem",
    "coins",
    "coin",
    "cash",
    "crystals",
    "crystal",
    "jade",
    "uc",
    "opals",
    "opals",
    "voucher",
    "vouchers",
    "token",
    "tokens",
    "credits",
    "origeometry",
)

_GAME_PASS_HINTS = (
    "prime",
    "pass",
    "monthly",
    "weekly",
    "card",
    "subscription",
    "membership",
    "elite",
    "royale",
    "battle pass",
)

_GAME_SPECIAL_HINTS = (
    "pack",
    "bundle",
    "box",
    "chest",
    "deal",
    "lucky",
    "material",
    "emblem",
    "skin",
    "bundle",
    "value",
    "first purchase",
    "rebate",
)

_GAME_GROUP_OVERRIDES: dict[str, dict[str, tuple[str, ...]]] = {
    "pubgm": {
        "passes": ("prime", "prime plus", "elite pass"),
        "specials": ("weekly", "mythic", "materials", "first purchase"),
    },
    "mlbb": {
        "passes": ("weekly elite", "monthly elite", "weekly", "twilight"),
    },
    "mlbb_br": {
        "passes": ("weekly elite", "monthly elite", "weekly"),
    },
    "mlbb_exclusive": {
        "passes": ("weekly", "twilight"),
    },
    "mla": {
        "passes": (),
        "specials": (),
    },
    "hok": {
        "passes": ("weekly card", "weekly card plus"),
        "specials": ("lucky bag", "value pack", "rebate"),
    },
    "afkjourney": {
        "passes": ("monthly", "gazette"),
        "specials": ("growth bundle",),
    },
    "age_of_magic": {
        "passes": ("daily", "weekly"),
        "specials": ("festive", "unique", "set"),
    },
}


class GameStoreFlow(StatesGroup):
    waiting_topup_player = State()
    waiting_topup_server = State()


class GiftStoreFlow(StatesGroup):
    waiting_lona_amount = State()
    waiting_quantity = State()
    waiting_param = State()


class EsimRouteFlow(StatesGroup):
    choosing_mode = State()
    choosing_countries = State()
    single_country_prompt = State()
    choosing_days = State()
    choosing_usage = State()
    choosing_package = State()
    confirming_purchase = State()


class SimTopupFlow(StatesGroup):
    choosing_topup_kind = State()
    choosing_physical_kind = State()
    waiting_phone = State()
    choosing_country = State()
    waiting_brand_search = State()
    choosing_brand = State()
    choosing_offer = State()
    confirming_purchase = State()


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


def _round_sale_price_decimal(value: Any) -> Decimal:
    amount = _to_decimal(value)
    if amount <= 0:
        return Decimal("0.00")
    return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _apply_markup_decimal(price: Any, markup_percent: Any) -> Decimal:
    base = _money_decimal(price)
    pct = _to_decimal(markup_percent)
    if pct <= 0:
        return _round_sale_price_decimal(base)
    multiplier = Decimal("1") + (pct / Decimal("100"))
    return _round_sale_price_decimal(base * multiplier)


def _is_pubg_game(game_id: str | None, game_name: str | None = None) -> bool:
    text = f"{_norm(game_id)} {_norm(game_name)}".strip()
    if not text:
        return False
    return any(key in text for key in ("pubg", "pubgm", "new state", "newstate"))


def _resolve_game_sale_price_decimal(
    *,
    game_id: str | None,
    provider_price: Any,
    markup_percent: Any,
    game_name: str | None = None,
) -> Decimal:
    base = _money_decimal(provider_price)
    marked = _apply_markup_decimal(base, markup_percent)
    return marked


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


_SIM_COUNTRY_INLINE_PREFIX = "simcountry"
_SIM_COUNTRY_TOKEN_PREFIX = "__simtopup_country__:"
_ISO3166_TAB = (Path(getattr(_pytz, "__file__", "")).resolve().parent / "zoneinfo" / "iso3166.tab") if _pytz else None
_ISO3166_FALLBACK = {
    "AE": "United Arab Emirates",
    "BH": "Bahrain",
    "CA": "Canada",
    "CY": "Cyprus",
    "DE": "Germany",
    "DZ": "Algeria",
    "EG": "Egypt",
    "FR": "France",
    "GB": "United Kingdom",
    "GR": "Greece",
    "ID": "Indonesia",
    "IN": "India",
    "IT": "Italy",
    "IQ": "Iraq",
    "JP": "Japan",
    "JO": "Jordan",
    "KR": "South Korea",
    "KW": "Kuwait",
    "LB": "Lebanon",
    "MA": "Morocco",
    "MY": "Malaysia",
    "OM": "Oman",
    "PS": "Palestine",
    "QA": "Qatar",
    "SA": "Saudi Arabia",
    "SG": "Singapore",
    "SY": "Syria",
    "TH": "Thailand",
    "TN": "Tunisia",
    "TR": "Turkey",
    "UA": "Ukraine",
    "US": "United States",
    "VN": "Vietnam",
    "YE": "Yemen",
}
_PHONE_PREFIX_COUNTRY_MAP: list[tuple[str, str]] = [
    ("+971", "AE"),
    ("+966", "SA"),
    ("+965", "KW"),
    ("+964", "IQ"),
    ("+963", "SY"),
    ("+962", "JO"),
    ("+961", "LB"),
    ("+968", "OM"),
    ("+967", "YE"),
    ("+974", "QA"),
    ("+973", "BH"),
    ("+970", "PS"),
    ("+90", "TR"),
    ("+380", "UA"),
    ("+357", "CY"),
    ("+216", "TN"),
    ("+212", "MA"),
    ("+213", "DZ"),
    ("+20", "EG"),
    ("+91", "IN"),
    ("+62", "ID"),
    ("+60", "MY"),
    ("+66", "TH"),
    ("+65", "SG"),
    ("+82", "KR"),
    ("+81", "JP"),
    ("+44", "GB"),
    ("+49", "DE"),
    ("+33", "FR"),
    ("+39", "IT"),
    ("+30", "GR"),
    ("+1", "US"),
]
_SIM_TOPUP_CACHE: dict[str, Any] = {
    "countries_balance": {"expires_at": 0.0, "rows": []},
    "countries_data": {"expires_at": 0.0, "rows": []},
    "brands": {},
}


def _sim_text(lang: str, en_text: str, ar_text: str) -> str:
    return ar_text if str(lang or "en").lower().startswith("ar") else en_text


def _sim_allowed_subtypes(section: str) -> set[str]:
    if str(section or "").strip().lower() == "data":
        return {"mobile bundle", "mobile data"}
    return {"mobile top up"}


def _sim_subtype(section: str) -> str:
    return "Mobile Bundle" if str(section or "").strip().lower() == "data" else "Mobile Top Up"


def _sim_row_matches_section(row: dict[str, Any], section: str) -> bool:
    allowed = _sim_allowed_subtypes(section)
    subtypes = [str(item or "").strip().lower() for item in list(row.get("subTypes") or [])]
    if not subtypes:
        return False
    return any(item in allowed for item in subtypes)


def _sim_country_display_name(country_code: str) -> str:
    code = str(country_code or "").strip().upper()
    if len(code) != 2:
        return code
    try:
        if _ISO3166_TAB and _ISO3166_TAB.exists():
            for raw_line in _ISO3166_TAB.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].strip().upper() == code:
                    return parts[1].strip()
    except Exception:
        pass
    return _ISO3166_FALLBACK.get(code, code)


def _sim_country_token(country_code: str) -> str:
    code = str(country_code or "").strip().upper()
    return f"{_SIM_COUNTRY_TOKEN_PREFIX}{code}"


def _sim_country_from_phone(phone: str) -> str:
    raw = str(phone or "").strip()
    for prefix, code in _PHONE_PREFIX_COUNTRY_MAP:
        if raw.startswith(prefix):
            return code
    return ""


def _sim_offer_price_usd(row: dict[str, Any]) -> Decimal:
    price = dict(row.get("price") or {})
    fixed = _to_decimal(price.get("fixed") or 0)
    divisor = _to_decimal(price.get("currencyDivisor") or 1)
    if divisor <= 0:
        divisor = Decimal("1")
    return (fixed / divisor).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _sim_offer_send_label(row: dict[str, Any], *, lang: str) -> str:
    send = dict(row.get("send") or {})
    fixed = _to_decimal(send.get("fixed") or 0)
    divisor = _to_decimal(send.get("currencyDivisor") or 1)
    if divisor <= 0:
        divisor = Decimal("1")
    send_value = (fixed / divisor).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    currency = str(send.get("currency") or "").strip().upper()
    if currency and send_value > 0:
        return _sim_text(lang, f"Value: {send_value} {currency}", f"القيمة: {send_value} {currency}")
    data_gb = _to_float(row.get("dataGB") or 0)
    days = _to_int(row.get("durationDays") or 0)
    if data_gb > 0:
        return _sim_text(lang, f"Data: {data_gb:g} GB", f"الداتا: {data_gb:g} GB")
    if days > 0:
        return _sim_text(lang, f"Duration: {days} days", f"المدة: {days} يوم")
    return _sim_text(lang, "Offer", "العرض")


def _sim_offer_label(row: dict[str, Any], *, lang: str) -> str:
    title = _sim_offer_send_label(row, lang=lang)
    price_usd = _money_decimal(row.get("_sale_price_usd") or _sim_offer_price_usd(row))
    return f"{title} | {format_usd(float(price_usd))}"


def _sim_offer_summary_text(row: dict[str, Any], *, lang: str) -> str:
    lines = [
        _sim_text(lang, "SIM TopUp Summary", "ملخص شحن الشريحة"),
        "",
        f"{_sim_text(lang, 'Country', 'الدولة')}: {_sim_country_display_name(str(row.get('country') or ''))}",
        f"{_sim_text(lang, 'Operator', 'المشغل')}: {str(row.get('brandName') or row.get('brand') or '-').strip()}",
        f"{_sim_text(lang, 'Type', 'النوع')}: {_sim_text(lang, 'Balance', 'رصيد') if str(row.get('_section_kind') or '').lower() == 'balance' else _sim_text(lang, 'Data', 'داتا')}",
        _sim_offer_send_label(row, lang=lang),
        f"{t(lang, 'price_label')}: {format_usd(float(_money_decimal(row.get('_sale_price_usd') or _sim_offer_price_usd(row))))}",
    ]
    return "\n".join(lines)


def _sim_prepare_offers(rows: list[dict[str, Any]], *, section: str, markup_percent: float) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["_section_kind"] = str(section or "").strip().lower()
        item["_cost_price_usd"] = float(_sim_offer_price_usd(item))
        item["_sale_price_usd"] = float(_apply_markup_decimal(item["_cost_price_usd"], markup_percent))
        prepared.append(item)
    prepared.sort(key=lambda row: (_money_decimal(row.get("_sale_price_usd") or 0), _norm(str(row.get("brandName") or row.get("brand") or ""))))
    return prepared


async def _sim_fetch_country_codes(section: str) -> list[str]:
    bucket = "countries_data" if str(section).lower() == "data" else "countries_balance"
    cached = dict(_SIM_TOPUP_CACHE.get(bucket) or {})
    if float(cached.get("expires_at") or 0.0) > asyncio.get_event_loop().time():
        return list(cached.get("rows") or [])

    client = ZenditClient()
    if not client.configured():
        return []

    codes: set[str] = set()
    limit = 1024
    offset = 0
    total = None
    while total is None or offset < int(total or 0):
        status, payload = await client.list_topup_offers(limit=limit, offset=offset)
        if status != 200 or not isinstance(payload, dict):
            break
        rows = [row for row in list(payload.get("list") or []) if isinstance(row, dict) and _sim_row_matches_section(row, section)]
        total = int(payload.get("total") or 0)
        if not rows:
            offset += limit
            continue
        for row in rows:
            code = str(row.get("country") or "").strip().upper()
            if len(code) == 2:
                codes.add(code)
        offset += limit

    ordered = sorted(codes)
    _SIM_TOPUP_CACHE[bucket] = {"expires_at": asyncio.get_event_loop().time() + 1800.0, "rows": ordered}
    return ordered


async def _sim_search_countries(section: str, query: str, limit: int = 20) -> list[dict[str, str]]:
    q = _norm(query)
    rows = []
    codes: set[str] = set()
    if str(section).strip().lower() == "all":
        codes.update(await _sim_fetch_country_codes("balance"))
        codes.update(await _sim_fetch_country_codes("data"))
    else:
        codes.update(await _sim_fetch_country_codes(section))
    for code in codes:
        name = _sim_country_display_name(code)
        hay = _norm(f"{code} {name}")
        if q and q not in hay:
            continue
        rows.append({"code": code, "name": name})
    if not q:
        rows.sort(key=lambda item: item["name"])
    else:
        rows.sort(key=lambda item: (0 if _norm(item["name"]).startswith(q) or _norm(item["code"]).startswith(q) else 1, item["name"]))
    return rows[:limit]


async def _sim_country_matches(query: str, *, limit: int = 8) -> list[dict[str, str]]:
    q = _norm(query)
    if not q:
        return []
    rows = await _sim_search_countries("all", q, limit=limit)
    if rows:
        return rows
    direct_code = str(query or "").strip().upper()
    if len(direct_code) == 2:
        return [{"code": direct_code, "name": _sim_country_display_name(direct_code)}]
    return []


async def _sim_country_brands(country_code: str, section: str) -> list[dict[str, str]]:
    cache_key = f"{section}:{str(country_code or '').upper()}"
    cached = dict((_SIM_TOPUP_CACHE.get("brands") or {}).get(cache_key) or {})
    if float(cached.get("expires_at") or 0.0) > asyncio.get_event_loop().time():
        return list(cached.get("rows") or [])

    client = ZenditClient()
    if not client.configured():
        return []
    brands: dict[str, str] = {}
    limit = 1024
    offset = 0
    total = None
    while total is None or offset < int(total or 0):
        status, payload = await client.list_topup_offers(
            limit=limit,
            offset=offset,
            country=str(country_code or "").upper(),
        )
        if status != 200 or not isinstance(payload, dict):
            break
        rows = [row for row in list(payload.get("list") or []) if isinstance(row, dict) and _sim_row_matches_section(row, section)]
        total = int(payload.get("total") or 0)
        if not rows:
            offset += limit
            continue
        for row in rows:
            key = str(row.get("brand") or "").strip()
            label = str(row.get("brandName") or row.get("brand") or "").strip()
            if key and label:
                brands[key] = label
        offset += limit

    ordered = [{"brand": key, "name": brands[key]} for key in sorted(brands, key=lambda item: _norm(brands[item]))]
    _SIM_TOPUP_CACHE.setdefault("brands", {})[cache_key] = {
        "expires_at": asyncio.get_event_loop().time() + 1800.0,
        "rows": ordered,
    }
    return ordered


async def _sim_search_brands(country_code: str, section: str, query: str, limit: int = 12) -> list[dict[str, str]]:
    q = _norm(query)
    rows = []
    for row in await _sim_country_brands(country_code, section):
        hay = _norm(f"{row.get('brand')} {row.get('name')}")
        if q and q not in hay and fuzz.partial_ratio(q, hay) < 70:
            continue
        rows.append(row)
    return rows[:limit]


async def _sim_fetch_offers(country_code: str, section: str, brand: str | None = None) -> list[dict[str, Any]]:
    client = ZenditClient()
    if not client.configured():
        return []
    status, payload = await client.list_topup_offers(
        limit=200,
        offset=0,
        country=str(country_code or "").upper(),
        brand=brand or None,
    )
    if status != 200 or not isinstance(payload, dict):
        return []
    rows = [row for row in list(payload.get("list") or []) if isinstance(row, dict) and _sim_row_matches_section(row, section)]
    filtered = [row for row in rows if str(row.get("priceType") or "FIXED").strip().upper() == "FIXED"]
    filtered.sort(key=lambda row: (_sim_offer_price_usd(row), _norm(str(row.get("brandName") or row.get("brand")))))
    return filtered


def _sim_country_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_sim_text(lang, "🌍 Choose Country", "🌍 اختر دولة"), switch_inline_query_current_chat=f"{_SIM_COUNTRY_INLINE_PREFIX} ")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="simtopup:back:phone")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")],
        ]
    )


def _sim_phone_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="simtopup:back:physical")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")],
        ]
    )


def _sim_brand_search_keyboard(lang: str, rows: list[dict[str, str]]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=str(row.get("name") or row.get("brand") or "-"), callback_data=f"simtopup:brand:{row.get('brand') or ''}")] for row in rows[:10]]
    buttons.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="simtopup:back:country")])
    buttons.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _sim_success_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")]]
    )


async def _sim_store_message_id(state: FSMContext, message_id: int | None) -> None:
    if isinstance(message_id, int) and message_id > 0:
        await state.update_data(simtopup_message_id=message_id)


async def _sim_edit_anchor(
    *,
    message: types.Message,
    state: FSMContext,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    data = await state.get_data()
    message_id = int(data.get("simtopup_message_id") or 0)
    if message_id > 0:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
        except TelegramBadRequest as exc:
            lowered = str(exc).lower()
            if "message is not modified" in lowered:
                return
            if "message can't be edited" not in lowered:
                raise
        except Exception:
            pass
    sent = await message.answer(text, reply_markup=reply_markup)
    await _sim_store_message_id(state, getattr(sent, "message_id", None))


async def _sim_render_hub(target: types.Message | types.CallbackQuery, state: FSMContext, lang: str) -> None:
    text = _sim_text(
        lang,
        "SIM TopUp\n\nChoose the recharge type.",
        "SIM TopUp\n\nاختر نوع الشحن.",
    )
    kb = _sim_topup_hub_keyboard(lang)
    if isinstance(target, types.CallbackQuery) and target.message:
        await _safe_edit_message(target.message, text, reply_markup=kb)
        await _sim_store_message_id(state, getattr(target.message, "message_id", None))
        return
    if isinstance(target, types.Message):
        sent = await target.answer(text, reply_markup=kb)
        await _sim_store_message_id(state, getattr(sent, "message_id", None))


async def _sim_render_physical_kind(target: types.Message | types.CallbackQuery, state: FSMContext, lang: str) -> None:
    text = _sim_text(
        lang,
        "Physical SIM\n\nChoose what you want to recharge.",
        "Physical SIM\n\nاختر ما الذي تريد شحنه.",
    )
    kb = _sim_physical_kind_keyboard(lang)
    if isinstance(target, types.CallbackQuery) and target.message:
        await _safe_edit_message(target.message, text, reply_markup=kb)
        await _sim_store_message_id(state, getattr(target.message, "message_id", None))
        return
    if isinstance(target, types.Message):
        sent = await target.answer(text, reply_markup=kb)
        await _sim_store_message_id(state, getattr(sent, "message_id", None))


async def _sim_render_phone_prompt(*, message: types.Message | None = None, callback: types.CallbackQuery | None = None, state: FSMContext, lang: str, section: str) -> None:
    label = _sim_text(lang, "Balance", "رصيد") if str(section).lower() == "balance" else _sim_text(lang, "Data", "داتا")
    text = _sim_text(
        lang,
        f"Physical SIM - {label}\n\nSend the phone number in international format.\nExample: +447700900000",
        f"شريحة فعلية - {label}\n\nأرسل رقم الهاتف بصيغة دولية.\nمثال: +447700900000",
    )
    if callback and callback.message:
        await _safe_edit_message(callback.message, text, reply_markup=_sim_phone_keyboard(lang))
        await _sim_store_message_id(state, getattr(callback.message, "message_id", None))
    elif message:
        await _sim_edit_anchor(message=message, state=state, text=text, reply_markup=_sim_phone_keyboard(lang))


async def _sim_render_country_prompt(*, message: types.Message | None = None, callback: types.CallbackQuery | None = None, state: FSMContext, lang: str, note: str | None = None) -> None:
    text = _sim_text(
        lang,
        "Choose the SIM country.\nYou can use the button below or send the country name/code directly.",
        "اختر دولة الشريحة.\nيمكنك استخدام الزر أدناه أو إرسال اسم الدولة/رمزها مباشرة.",
    )
    if note:
        text += f"\n\n{note}"
    kb = _sim_country_keyboard(lang)
    if callback and callback.message:
        await _safe_edit_message(callback.message, text, reply_markup=kb)
        await _sim_store_message_id(state, getattr(callback.message, "message_id", None))
    elif message:
        await _sim_edit_anchor(message=message, state=state, text=text, reply_markup=kb)


async def _sim_render_brand_prompt(*, message: types.Message | None = None, callback: types.CallbackQuery | None = None, state: FSMContext, lang: str, country_code: str, section: str, note: str | None = None) -> None:
    brands = await _sim_country_brands(country_code, section)
    country_name = _sim_country_display_name(country_code)
    if not brands:
        direct_offers = await _sim_fetch_offers(country_code, section, brand=None)
        if direct_offers:
            prepared = _sim_prepare_offers(direct_offers, section=section, markup_percent=_resolve_physical_sim_markup_percent(section))
            await state.set_state(SimTopupFlow.choosing_offer)
            await state.update_data(sim_brand_key="", sim_brand_name=_sim_text(lang, "All operators", "كل المشغلين"), sim_offers=prepared, sim_selected_offer=None)
            await _sim_render_offers(message=message, callback=callback, state=state, lang=lang, offers=prepared)
            return
        text = _sim_text(
            lang,
            f"No operators were found for {country_name}. Choose another country.",
            f"لم نجد مشغلين لـ {country_name}. اختر دولة أخرى.",
        )
        if callback and callback.message:
            await _safe_edit_message(callback.message, text, reply_markup=_sim_country_keyboard(lang))
        elif message:
            await _sim_edit_anchor(message=message, state=state, text=text, reply_markup=_sim_country_keyboard(lang))
        await state.set_state(SimTopupFlow.choosing_country)
        return
    text = _sim_text(
        lang,
        f"Country: {country_name}\n\nChoose the operator, or send its name.",
        f"الدولة: {country_name}\n\nاختر المشغل أو أرسل اسمه.",
    )
    if note:
        text += f"\n\n{note}"
    kb = _sim_brand_search_keyboard(lang, brands)
    if callback and callback.message:
        await _safe_edit_message(callback.message, text, reply_markup=kb)
        await _sim_store_message_id(state, getattr(callback.message, "message_id", None))
    elif message:
        await _sim_edit_anchor(message=message, state=state, text=text, reply_markup=kb)
    await state.set_state(SimTopupFlow.waiting_brand_search)


async def _sim_render_offers(*, callback: types.CallbackQuery | None = None, message: types.Message | None = None, state: FSMContext, lang: str, offers: list[dict[str, Any]]) -> None:
    data = await state.get_data()
    country_code = str(data.get("sim_country_code") or "").upper()
    brand_name = str(data.get("sim_brand_name") or data.get("sim_brand_key") or "").strip()
    section = str(data.get("sim_section_kind") or "").strip().lower()
    kind_label = _sim_text(lang, "Balance", "رصيد") if section == "balance" else _sim_text(lang, "Data", "داتا")
    text = _sim_text(
        lang,
        f"Physical SIM - {kind_label}\nCountry: {_sim_country_display_name(country_code)}\nOperator: {brand_name}\n\nChoose the offer.",
        f"شريحة فعلية - {kind_label}\nالدولة: {_sim_country_display_name(country_code)}\nالمشغل: {brand_name}\n\nاختر العرض.",
    )
    kb = _sim_offer_keyboard(lang, offers)
    if callback and callback.message:
        await _safe_edit_message(callback.message, text, reply_markup=kb)
        await _sim_store_message_id(state, getattr(callback.message, "message_id", None))
    elif message:
        await _sim_edit_anchor(message=message, state=state, text=text, reply_markup=kb)


def _sim_topup_hub_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_esim"), callback_data="simtopup:esim")],
            [InlineKeyboardButton(text=_sim_text(lang, "📱 Physical SIM", "📱 Physical SIM"), callback_data="simtopup:physical")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:menu")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")],
        ]
    )


def _sim_physical_kind_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_sim_text(lang, "💳 Balance", "💳 رصيد"), callback_data="simtopup:physical:balance")],
            [InlineKeyboardButton(text=_sim_text(lang, "📦 Data", "📦 داتا"), callback_data="simtopup:physical:data")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="simtopup:back:hub")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")],
        ]
    )


def _sim_brand_keyboard(lang: str, rows: list[dict[str, str]]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=str(row.get("name") or row.get("brand") or "-"), callback_data=f"simtopup:brand:{row.get('brand') or ''}")] for row in rows]
    buttons.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="simtopup:back:country")])
    buttons.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _sim_offer_keyboard(lang: str, offers: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=_sim_offer_label(row, lang=lang), callback_data=f"simtopup:offer:{index}")] for index, row in enumerate(offers[:20])]
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="simtopup:back:brand")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sim_summary_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data="simtopup:buy")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="simtopup:back:offers")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")],
        ]
    )


async def _edit_callback_target(
    callback: types.CallbackQuery,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
            return True
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return True
            if "message can't be edited" not in str(exc).lower():
                raise
            sent = await callback.message.answer(text, reply_markup=reply_markup)
            callback.message = sent
            return True
    inline_message_id = str(getattr(callback, "inline_message_id", "") or "").strip()
    if inline_message_id:
        try:
            await callback.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return True
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return True
            raise
    return False


async def _safe_edit_message(
    message: types.Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except TelegramBadRequest as exc:
        lowered = str(exc).lower()
        if "message is not modified" in lowered:
            return True
        if "message can't be edited" in lowered:
            await message.answer(text, reply_markup=reply_markup)
            return True
        raise


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


def _is_mobile_topups_trigger(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    exact = {
        t("en", "btn_mobile_topups"),
        t("ar", "btn_mobile_topups"),
        "mobile top-up",
        "mobile topups",
        "airtime",
        "/topup",
    }
    return raw in exact or lowered in exact


def _is_sim_topup_trigger(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    exact = {
        t("en", "btn_sim_topup"),
        t("ar", "btn_sim_topup"),
        "sim topup",
        "sim top-up",
        "/simtopup",
    }
    return raw in exact or lowered in exact


def _is_esim_trigger(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    exact = {
        t("en", "btn_esim"),
        t("ar", "btn_esim"),
        "esim",
        "e-sim",
        "/esim",
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


async def _digital_products_menu_text(lang: str) -> str:
    return f"{t(lang, 'store_top_games_title')}\n\n{t(lang, 'store_search_pick_hint')}"


def _coming_soon_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="back_to_main_menu")]
        ]
    )


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


def _gift_categories_for_ui(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    provider_categories: list[dict[str, Any]] = []
    if bool((snapshot or {}).get("enabled")):
        provider_categories = _prepare_gift_categories(list((snapshot or {}).get("gift_categories") or []))
    provider_categories = [
        cat
        for cat in provider_categories
        if not is_lona_managed_category_name(str(cat.get("clean_name") or cat.get("name") or ""))
    ]
    return lona_categories() + provider_categories


def _percent_label(value: Any) -> str:
    pct = _to_decimal(value).normalize()
    text = format(pct, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"


def _lona_warranty_line(lang: str, months: int = 2) -> str:
    if str(lang or "").lower().startswith("ar"):
        return f"الكفالة: {months} شهر"
    return f"Warranty: {months} months"


def _lona_quote_summary_text(lang: str, quote: dict[str, Any]) -> str:
    face = float(_to_decimal(quote.get("face_value") or 0))
    price = float(_to_decimal(quote.get("price") or 0))
    rate = _percent_label(quote.get("rate_percent") or 0)
    warranty_months = int(quote.get("warranty_months") or 2)
    if str(lang or "").lower().startswith("ar"):
        return "\n".join(
            [
                str(quote.get("product_name") or quote.get("category_name") or "-"),
                "",
                f"قيمة البطاقة: {format_usd(face)}",
                f"النسبة: {rate}",
                f"السعر النهائي: {format_usd(price)}",
                _lona_warranty_line(lang, warranty_months),
                "",
                "هل تريد تأكيد الشراء؟",
            ]
        )
    return "\n".join(
        [
            str(quote.get("product_name") or quote.get("category_name") or "-"),
            "",
            f"Card value: {format_usd(face)}",
            f"Rate: {rate}",
            f"Final price: {format_usd(price)}",
            _lona_warranty_line(lang, warranty_months),
            "",
            "Confirm purchase?",
        ]
    )


def _lona_amount_prompt_text(lang: str, product: dict[str, Any]) -> str:
    meta = dict(product.get("manual_card") or {})
    rate = _percent_label(meta.get("rate_percent") or 0)
    kind = str(meta.get("kind") or "")
    name = str(product.get("name") or "-")
    warranty = _lona_warranty_line(lang, int(meta.get("warranty_months") or 2))
    if str(lang or "").lower().startswith("ar"):
        if kind == "mixed":
            rule = "المكسر يقبل القيم غير الموجودة كفئة جاهزة وغير المضاعفة للعدد 5."
        else:
            rule = "أرسل قيمة البطاقة المطلوبة ليتم حساب السعر حسب النسبة."
        return f"{name}\n\nالنسبة: {rate}\n{warranty}\n\n{rule}\n\nأرسل قيمة البطاقة الآن، أو /cancel."
    if kind == "mixed":
        rule = "Mixed accepts values that are not listed as direct options and are not divisible by 5."
    else:
        rule = "Send the card value and the bot will calculate the final price from the rate."
    return f"{name}\n\nRate: {rate}\n{warranty}\n\n{rule}\n\nSend the card value now, or /cancel."


def _lona_manual_confirm_kb(lang: str, *, back_to: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data="gst:giftmanualconfirm")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data=back_to)],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:giftparam:cancel")],
        ]
    )


async def _resolve_user_reseller(user_id: int, bot_id: int) -> int | None:
    if await is_main_bot(bot_id) or await is_digital_products_bot(bot_id):
        return int(user_id)
    reseller_id = await get_user_reseller_for_bot(user_id, bot_id)
    if reseller_id:
        return int(reseller_id)
    inferred = await get_store_owner_scope_for_bot(bot_id)
    if inferred:
        await set_user_reseller_for_bot(user_id, bot_id, int(inferred))
        return int(inferred)
    return None


async def _resolve_usd_to_syp_rate(bot_id: int) -> float:
    try:
        reseller_id = await get_store_owner_scope_for_bot(int(bot_id))
        if reseller_id:
            rate = float(await get_exchange_rate(int(reseller_id)))
            if rate > 0:
                return rate
    except Exception:
        pass
    return 118.0


async def _resolve_digital_products_markup_percent() -> float:
    try:
        return float(await get_digital_products_markup_percent(0.0))
    except Exception:
        return 0.0


def _resolve_esim_markup_percent() -> float:
    return 0.0


def _resolve_physical_sim_markup_percent(section: str) -> float:
    return 0.0


def _apply_markup_to_esim_offer(offer: dict[str, Any], *, markup_percent: float) -> dict[str, Any]:
    clone = dict(offer or {})
    base_offer_price = float(_money_decimal(clone.get("price_usd") or 0.0))
    clone["_cost_price_usd"] = base_offer_price
    clone["price_usd"] = float(_apply_markup_decimal(base_offer_price, markup_percent))
    parts: list[dict[str, Any]] = []
    for part in list(clone.get("parts") or []):
        part_clone = dict(part or {})
        plan = dict(part_clone.get("plan") or {})
        plan_cost = float(_money_decimal(plan.get("price_usd") or 0.0))
        plan["_cost_price_usd"] = plan_cost
        plan["price_usd"] = float(_apply_markup_decimal(plan_cost, markup_percent))
        part_clone["plan"] = plan
        parts.append(part_clone)
    if parts:
        clone["parts"] = parts
    return clone


def _fmt_dual_price(usd: float, usd_to_syp_rate: float) -> str:
    return format_usd(_to_float(usd))


def _store_price_line(lang: str, price: float, usd_to_syp_rate: float) -> str:
    return f"{t(lang, 'price_label')}: {_fmt_dual_price(price, usd_to_syp_rate)}"


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
    return t("en", "provider_request_failed")


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
        if isinstance(nested, list) and nested:
            first = nested[0]
            if isinstance(first, dict):
                for key in ("status", "order_status", "state"):
                    raw = str(first.get(key) or "").strip().lower()
                    if raw:
                        return raw
        if isinstance(nested, dict):
            for key in ("status", "order_status", "state"):
                raw = str(nested.get(key) or "").strip().lower()
                if raw:
                    return raw
            for wrapper in ("order", "result"):
                child = nested.get(wrapper)
                if isinstance(child, dict):
                    for key in ("status", "order_status", "state"):
                        raw = str(child.get(key) or "").strip().lower()
                        if raw:
                            return raw
        for key in ("status", "order_status", "state"):
            raw = str(payload.get(key) or "").strip().lower()
            if raw:
                return raw
        for wrapper in ("order", "result"):
            child = payload.get(wrapper)
            if isinstance(child, dict):
                for key in ("status", "order_status", "state"):
                    raw = str(child.get(key) or "").strip().lower()
                    if raw:
                        return raw
    return ""


def _provider_status_is_success(payload: Any) -> bool:
    status = _extract_provider_status(payload)
    return status in {
        "success",
        "successful",
        "ok",
        "accept",
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
        "reject",
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
            if _provider_status_is_success(last_resp):
                delivery_resp = await client.get_order_delivery(external_order_id)
                if isinstance(last_resp, dict) and isinstance(delivery_resp, dict):
                    last_resp = {**last_resp, "delivery_response": delivery_resp}
            return last_resp
        if attempt < attempts - 1:
            await asyncio.sleep(max(0.0, float(delay_sec)))
    return last_resp


async def _poll_za3em_order_status(
    client: Za3emClient,
    external_order_id: str,
    *,
    by_uuid: bool = False,
    attempts: int = 5,
    delay_sec: float = 3.0,
) -> dict[str, Any] | None:
    ref = str(external_order_id or "").strip()
    if not ref:
        return None
    last_resp: dict[str, Any] | None = None
    for attempt in range(max(1, int(attempts))):
        last_resp = await client.check_orders([ref], by_uuid=bool(by_uuid))
        if _provider_status_is_success(last_resp) or _provider_status_is_failure(last_resp):
            return last_resp
        if attempt < attempts - 1:
            await asyncio.sleep(max(0.0, float(delay_sec)))
    return last_resp


async def _poll_provider_order_status(
    *,
    provider: str,
    external_order_id: str,
) -> dict[str, Any] | None:
    p = str(provider or "").strip().lower()
    if not str(external_order_id or "").strip():
        return None
    if not digital_provider_enabled(p):
        return None
    if p == "za3em":
        client = Za3emClient()
        return await _poll_za3em_order_status(client, external_order_id, by_uuid=False)
    client = G2BulkClient()
    return await _poll_g2bulk_order_status(client, external_order_id)


def _provider_offers_for_row(
    row: dict[str, Any],
    *,
    fallback_provider: str,
    fallback_ref_id: str,
    fallback_price: float,
) -> list[dict[str, Any]]:
    return extract_provider_offers(
        row,
        fallback_provider=fallback_provider,
        fallback_ref_id=fallback_ref_id,
        fallback_price=fallback_price,
    )


def _gift_category_name_from_snapshot(snapshot: dict[str, Any], cat_id: str) -> str:
    for row in list(snapshot.get("gift_categories") or []):
        if str(row.get("id") or "").strip() == str(cat_id or "").strip():
            return str(row.get("clean_name") or row.get("name") or "").strip()
    return ""


def _prepare_gift_offers_for_fulfillment(
    offers: list[dict[str, Any]],
    *,
    category_name: str,
    product_name: str,
) -> list[dict[str, Any]]:
    manual_info = manual_feature_info(category_name, product_name)
    prepared = [dict(row) for row in list(offers or []) if isinstance(row, dict)]
    if not manual_info:
        return prepared
    for row in prepared:
        row["fulfillment_mode"] = MANUAL_TOPUP_MODE
        row["manual_requires_input"] = True
        row["manual_params"] = ["player_id"]
        row["manual_family_key"] = str(manual_info.get("family_key") or "")
        row["manual_region"] = str(manual_info.get("region") or "Global")
    return prepared


async def _create_provider_gift_order(
    *,
    provider: str,
    ref_id: str,
    quantity: int = 1,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = str(provider or "").strip().lower()
    if not digital_provider_enabled(p):
        return {"status": 0, "data": {"status": "ERROR", "msg": "PROVIDER_DISABLED"}}
    if p == "za3em":
        client = Za3emClient()
        return await client.create_order(
            product_id=ref_id,
            quantity=max(1, int(quantity or 1)),
            order_uuid=uuid4().hex,
            extra_params=extra_params or None,
        )
    client = G2BulkClient()
    return await client.create_voucher_order(product_id=ref_id, quantity=max(1, int(quantity or 1)))


def _gift_offer_needs_input(offer: dict[str, Any]) -> bool:
    if str(offer.get("fulfillment_mode") or "") == MANUAL_TOPUP_MODE:
        return bool(offer.get("manual_requires_input", True))
    provider = str(offer.get("provider") or "").strip().lower()
    if provider != "za3em":
        return False
    return bool(offer.get("za3em_requires_input"))


def _gift_offer_params(offer: dict[str, Any]) -> list[str]:
    manual_params = offer.get("manual_params")
    if isinstance(manual_params, list):
        return [str(item).strip() for item in manual_params if str(item).strip()]
    raw = offer.get("za3em_params")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _gift_offer_qty_bounds(offer: dict[str, Any]) -> tuple[int, int]:
    qty_min = max(1, _to_int(offer.get("za3em_qty_min") or 1))
    qty_max = max(qty_min, _to_int(offer.get("za3em_qty_max") or qty_min))
    return qty_min, qty_max


def _gift_unit_cost_decimal(*, offer: dict[str, Any] | None, fallback_price: Any) -> Decimal:
    base = _to_decimal((offer or {}).get("price") if isinstance(offer, dict) else 0)
    if base <= 0:
        base = _to_decimal(fallback_price)
    if base < 0:
        base = Decimal("0")
    return base


def _gift_compute_prices(
    *,
    offer: dict[str, Any] | None,
    fallback_price: Any,
    quantity: int,
    markup_percent: Any,
) -> tuple[float, float, float]:
    qty = max(1, int(quantity or 1))
    unit_cost = _gift_unit_cost_decimal(offer=offer, fallback_price=fallback_price)
    cost_dec = (unit_cost * Decimal(str(qty))).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    sale_dec = _apply_markup_decimal(cost_dec, markup_percent)
    return float(unit_cost), float(cost_dec), float(sale_dec)


def _gift_param_cancel_keyboard(lang: str, *, back_to: str = "gst:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:giftparam:cancel")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data=back_to)],
        ]
    )


def _gift_qty_prompt_text(lang: str, qty_min: int, qty_max: int) -> str:
    if str(lang or "").lower().startswith("ar"):
        return f"أدخل الكمية المطلوبة ({qty_min}-{qty_max})"
    return f"Enter quantity ({qty_min}-{qty_max})"


def _gift_param_prompt_text(lang: str, key: str) -> str:
    label = str(key or "").replace("_", " ").strip().title() or "Value"
    if str(lang or "").lower().startswith("ar"):
        return f"أرسل قيمة الحقل المطلوب: {label}"
    return f"Send required field value: {label}"


def _gift_prefill_summary_lines(*, lang: str, quantity: int, extra_params: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    params = {
        str(key).strip(): str(value).strip()
        for key, value in dict(extra_params or {}).items()
        if str(key).strip() and str(value).strip()
    }
    if int(quantity or 1) <= 1 and not params:
        return lines
    is_ar = str(lang or "").lower().startswith("ar")
    lines.append("تفاصيل الطلب:" if is_ar else "Order details:")
    lines.append(f"- {'الكمية' if is_ar else 'Quantity'}: {max(1, int(quantity or 1))}")
    for key, value in params.items():
        label = str(key).replace("_", " ").strip().title() or key
        lines.append(f"- {label}: {value}")
    return lines


async def _execute_manual_gift_topup_purchase(
    *,
    bot: Any,
    user_id: int,
    lang: str,
    reseller_id: int,
    selected: dict[str, Any],
    product_id: str,
    available_offers: list[dict[str, Any]],
    sale_price: float,
    cost_price: float,
    quantity: int = 1,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    available_offers = [
        dict(row)
        for row in list(available_offers or [])
        if isinstance(row, dict) and bool(row.get("available")) and digital_provider_enabled(str(row.get("provider") or ""))
    ]
    if not available_offers:
        return {"kind": "provider_failed", "text": t(lang, "store_out_of_stock")}

    first_offer = available_offers[0]
    provider_code = str(first_offer.get("provider") or "g2bulk").strip().lower() or "g2bulk"
    service_ref_id = f"{provider_code}:manual_topup:{str(first_offer.get('ref_id') or product_id)}"
    order, err = await _core_charge(
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        service_ref_id=service_ref_id,
        sale_price=float(sale_price),
        cost_price=float(cost_price),
    )
    if not order or err:
        return {"kind": "charge_error", "alert": err or t(lang, "purchase_failed_plain")}

    provider_resp: dict[str, Any] | None = None
    chosen_offer: dict[str, Any] | None = None
    failures: list[str] = []
    for offer in available_offers:
        offer_price = float(_money_decimal(offer.get("price") or 0.0))
        if offer_price <= 0:
            continue
        if offer_price > (float(cost_price) + 0.000001):
            continue
        attempt = await _create_provider_gift_order(
            provider=str(offer.get("provider") or "g2bulk"),
            ref_id=str(offer.get("ref_id") or product_id),
            quantity=max(1, int(quantity or 1)),
            extra_params=None,
        )
        if _provider_ok(attempt):
            provider_resp = attempt
            chosen_offer = dict(offer)
            break
        failures.append(_extract_provider_error(attempt.get("data") or attempt))

    if not provider_resp or not chosen_offer:
        await _core_refund(
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            order=order,
            sale_price=float(sale_price),
            cost_price=float(cost_price),
        )
        error_text = failures[0] if failures else t(lang, "provider_request_failed")
        await update_order_details(order["_id"], {"provider_response": provider_resp or {}, "provider_error": error_text, "provider_offers_attempted": available_offers})
        await _notify_owner_stock_issue(
            bot=bot,
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            item_name=str(selected.get("name") or f"Product {product_id}"),
            provider_error=error_text,
        )
        return {"kind": "provider_failed", "text": t(lang, "store_out_of_stock_admin_notified")}

    provider_code = str(chosen_offer.get("provider") or "g2bulk")
    provider_data = provider_resp.get("data")
    external_order_id = _extract_external_order_id(provider_data)
    voucher_lines = _extract_voucher_lines(provider_data)
    player_data = {
        str(key).strip(): str(value).strip()
        for key, value in dict(extra_params or {}).items()
        if str(key).strip() and str(value).strip()
    }
    item_name = str(selected.get("name") or f"Product {product_id}")
    await update_order_details(
        order["_id"],
        {
            "provider_code": provider_code,
            "provider_order_id": external_order_id,
            "provider_response": provider_resp,
            "delivery_lines_private": voucher_lines,
            "provider_offers_attempted": available_offers,
            "provider_request_quantity": max(1, int(quantity or 1)),
            "provider_request_extra_params": player_data,
            "fulfillment_mode": MANUAL_TOPUP_MODE,
            "manual_fulfillment_required": True,
            "manual_fulfillment_status": "pending",
            "manual_item_name": item_name,
            "number_mode": "digital_products",
        },
    )
    await _notify_owner_manual_topup(
        bot=bot,
        order=order,
        item_name=item_name,
        provider_code=provider_code,
        external_order_id=external_order_id,
        player_data=player_data,
        delivery_lines=voucher_lines,
    )
    player_id_value = next(
        (
            value
            for key, value in player_data.items()
            if str(key or "").strip().lower() in {"player_id", "playerid", "id", "uid"}
        ),
        next(iter(player_data.values()), ""),
    )
    family_label = str(chosen_offer.get("manual_family_key") or "").replace("_", " ").strip().title() or item_name
    return {
        "kind": "pending",
        "text": _digital_game_order_summary_text(
            lang,
            order_id=str(order.get("_id") or ""),
            game_name=family_label,
            package_name=item_name,
            player_id=str(player_id_value or ""),
            price=float(sale_price),
            status="PENDING",
        ),
    }


async def _execute_gift_purchase(
    *,
    bot: Any,
    user_id: int,
    lang: str,
    reseller_id: int,
    selected: dict[str, Any],
    product_id: str,
    available_offers: list[dict[str, Any]],
    sale_price: float,
    cost_price: float,
    quantity: int = 1,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    available_offers = [
        dict(row)
        for row in list(available_offers or [])
        if isinstance(row, dict) and bool(row.get("available")) and digital_provider_enabled(str(row.get("provider") or ""))
    ]
    if not available_offers:
        return {"kind": "provider_failed", "text": t(lang, "store_out_of_stock")}
    if any(str(row.get("fulfillment_mode") or "") == MANUAL_TOPUP_MODE for row in available_offers):
        return await _execute_manual_gift_topup_purchase(
            bot=bot,
            user_id=int(user_id),
            lang=lang,
            reseller_id=int(reseller_id),
            selected=selected,
            product_id=product_id,
            available_offers=available_offers,
            sale_price=float(sale_price),
            cost_price=float(cost_price),
            quantity=int(quantity or 1),
            extra_params=dict(extra_params or {}),
        )
    order, err = await _core_charge(
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        service_ref_id=f"{str((available_offers[0] if available_offers else {}).get('provider') or 'g2bulk')}:{'gift'}:{str((available_offers[0] if available_offers else {}).get('ref_id') or product_id)}",
        sale_price=float(sale_price),
        cost_price=float(cost_price),
    )
    if not order or err:
        return {"kind": "charge_error", "alert": err or t(lang, "purchase_failed_plain")}

    provider_resp: dict[str, Any] | None = None
    chosen_offer: dict[str, Any] | None = None
    failures: list[str] = []
    for offer in available_offers:
        offer_price = float(_money_decimal(offer.get("price") or 0.0))
        if offer_price <= 0:
            continue
        # Do not auto-fallback to a higher-cost provider than the charged wholesale amount.
        if offer_price > (cost_price + 0.000001):
            continue
        attempt = await _create_provider_gift_order(
            provider=str(offer.get("provider") or "g2bulk"),
            ref_id=str(offer.get("ref_id") or product_id),
            quantity=max(1, int(quantity or 1)),
            extra_params=extra_params if str(offer.get("provider") or "").strip().lower() == "za3em" else None,
        )
        if _provider_ok(attempt):
            provider_resp = attempt
            chosen_offer = dict(offer)
            break
        failures.append(_extract_provider_error(attempt.get("data") or attempt))

    if not provider_resp or not chosen_offer:
        await _core_refund(
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            order=order,
            sale_price=float(sale_price),
            cost_price=float(cost_price),
        )
        error_text = failures[0] if failures else t(lang, "provider_request_failed")
        await update_order_details(order["_id"], {"provider_response": provider_resp or {}, "provider_error": error_text, "provider_offers_attempted": available_offers})
        await _notify_owner_stock_issue(
            bot=bot,
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            item_name=str(selected.get("name") or f"Product {product_id}"),
            provider_error=error_text,
        )
        return {"kind": "provider_failed", "text": t(lang, "store_out_of_stock_admin_notified")}

    order_id_str = str(order.get("_id"))
    provider_code = str(chosen_offer.get("provider") or "g2bulk")
    provider_data = provider_resp.get("data")
    external_order_id = _extract_external_order_id(provider_data)
    voucher_lines = _extract_voucher_lines(provider_data)

    await update_order_details(
        order["_id"],
        {
            "provider_code": provider_code,
            "provider_order_id": external_order_id,
            "provider_response": provider_resp,
            "delivery_lines": voucher_lines,
            "provider_offers_attempted": available_offers,
            "provider_request_quantity": max(1, int(quantity or 1)),
            "provider_request_extra_params": dict(extra_params or {}),
            "number_mode": "digital_products",
        },
    )

    if not voucher_lines:
        status_resp = await _poll_provider_order_status(provider=provider_code, external_order_id=external_order_id) if external_order_id else None
        if status_resp is not None:
            voucher_lines = _extract_voucher_lines(status_resp)
            await update_order_details(
                order["_id"],
                {
                    "provider_status_response": status_resp,
                    "provider_status": _extract_provider_status(status_resp),
                    "delivery_lines": voucher_lines,
                },
            )
        if status_resp is not None and _provider_status_is_failure(status_resp):
            await _core_refund(
                user_id=int(user_id),
                reseller_id=int(reseller_id),
                order=order,
                sale_price=float(sale_price),
                cost_price=float(cost_price),
            )
            error_text = _extract_provider_error(status_resp.get("data") if isinstance(status_resp, dict) else status_resp)
            await update_order_details(order["_id"], {"provider_error": error_text})
            return {"kind": "provider_failed_refunded", "text": t(lang, "store_topup_provider_failed_refunded")}

        await update_order_details(
            order["_id"],
            {
                "provider_manual_review_required": True,
                "provider_error": "voucher_lines_missing_or_pending",
            },
        )
        return {"kind": "pending", "text": t(lang, "store_topup_pending_followup")}

    await update_order_status(order["_id"], "success")

    usd_to_syp_rate = await _resolve_usd_to_syp_rate(bot.id)
    debit_line = f"{t(lang, 'store_debited_label')}: {_fmt_dual_price(float(sale_price), usd_to_syp_rate)}"
    balance = await get_user_wallet_balance(user_id, int(reseller_id))
    balance_line = f"{t(lang, 'store_balance_label')}: {format_usd(float(balance or 0))}"
    body = [t(lang, "purchase_complete_plain"), debit_line, balance_line, f"{t(lang, 'store_order_label')}: {order_id_str}"]
    if external_order_id:
        body.append(f"{t(lang, 'store_provider_ref_label')}: {external_order_id}")
    if voucher_lines:
        body.append("")
        body.append(f"{t(lang, 'delivery_plain')}:")
        body.extend([f"- {line}" for line in voucher_lines])
    return {
        "kind": "success",
        "text": "\n".join(body),
    }


async def _execute_lona_card_purchase(
    *,
    bot: Any,
    user_id: int,
    lang: str,
    reseller_id: int,
    quote: dict[str, Any],
) -> dict[str, Any]:
    sale_price = float(_to_decimal(quote.get("price") or 0))
    if sale_price <= 0:
        return {"kind": "charge_error", "alert": t(lang, "store_invalid_product")}
    face_value = float(_to_decimal(quote.get("face_value") or 0))
    service_ref_id = (
        f"lona_card:{str(quote.get('category_id') or '')}:"
        f"{str(quote.get('product_id') or '')}:{face_value:.2f}"
    )
    order, err = await _core_charge(
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        service_ref_id=service_ref_id,
        sale_price=float(sale_price),
        cost_price=float(sale_price),
    )
    if not order or err:
        return {"kind": "charge_error", "alert": err or t(lang, "purchase_failed_plain")}

    item_name = str(quote.get("product_name") or quote.get("category_name") or "LONA Card")
    rate = _percent_label(quote.get("rate_percent") or 0)
    warranty_months = int(quote.get("warranty_months") or 2)
    order_id = str(order.get("_id") or "")
    await update_order_details(
        order["_id"],
        {
            "provider_code": LONA_CARD_PROVIDER,
            "fulfillment_mode": MANUAL_TOPUP_MODE,
            "manual_fulfillment_required": True,
            "manual_fulfillment_status": "pending",
            "manual_item_name": item_name,
            "manual_card": {
                "category_id": str(quote.get("category_id") or ""),
                "product_id": str(quote.get("product_id") or ""),
                "category_name": str(quote.get("category_name") or ""),
                "product_name": item_name,
                "face_value": face_value,
                "rate_percent": float(_to_decimal(quote.get("rate_percent") or 0)),
                "sale_price": sale_price,
                "warranty_months": warranty_months,
                "source": LONA_CARD_PROVIDER,
            },
            "number_mode": "digital_products",
        },
    )
    await _notify_owner_manual_topup(
        bot=bot,
        order=order,
        item_name=item_name,
        provider_code=LONA_CARD_PROVIDER,
        external_order_id="",
        player_data={
            "card_value": format_usd(face_value),
            "rate": rate,
            "charged": format_usd(sale_price),
            "warranty": f"{warranty_months} months",
        },
        delivery_lines=[],
    )
    if str(lang or "").lower().startswith("ar"):
        text = "\n".join(
            [
                "✅ تم تثبيت طلب البطاقة.",
                "",
                f"رقم الطلب: {order_id}",
                f"البطاقة: {item_name}",
                f"قيمة البطاقة: {format_usd(face_value)}",
                f"النسبة: {rate}",
                f"السعر المخصوم: {format_usd(sale_price)}",
                _lona_warranty_line(lang, warranty_months),
                "",
                "سيتم تسليم الكود بعد المراجعة اليدوية.",
            ]
        )
    else:
        text = "\n".join(
            [
                "✅ Card order created.",
                "",
                f"Order: {order_id}",
                f"Card: {item_name}",
                f"Card value: {format_usd(face_value)}",
                f"Rate: {rate}",
                f"Debited: {format_usd(sale_price)}",
                _lona_warranty_line(lang, warranty_months),
                "",
                "The code will be delivered after manual review.",
            ]
        )
    return {"kind": "pending", "text": text}


async def _create_provider_game_order(
    *,
    provider: str,
    ref_id: str,
    game_id: str,
    player_id: str,
    server_id: str | None,
    catalogue_name: str,
) -> dict[str, Any]:
    p = str(provider or "").strip().lower()
    if not digital_provider_enabled(p):
        return {"status": 0, "data": {"status": "ERROR", "msg": "PROVIDER_DISABLED"}}
    if p == "za3em":
        client = Za3emClient()
        return await client.create_order(
            product_id=ref_id,
            quantity=1,
            order_uuid=uuid4().hex,
            player_id=player_id,
            server_id=server_id or None,
        )
    client = G2BulkClient()
    return await client.create_topup_order(
        product_id=ref_id,
        player_id=player_id,
        server_id=server_id or None,
        quantity=1,
        game_code=game_id,
        catalogue_name=catalogue_name,
    )


def _extract_external_order_id(payload: Any) -> str:
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            for row in list(payload.get("data") or []):
                if not isinstance(row, dict):
                    continue
                raw = str(row.get("order_id") or row.get("id") or "").strip()
                if raw:
                    return raw
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
                payload.get("delivery_items"),
                payload.get("cards"),
                payload.get("vouchers"),
                payload.get("codes"),
                payload.get("data"),
                payload.get("delivery_response"),
            ]
        )
    for item in candidates:
        if isinstance(item, str) and item.strip():
            lines.append(item.strip())
        elif isinstance(item, dict):
            if isinstance(item.get("data"), dict):
                candidates.append(item.get("data"))
            for nested_key in ("delivery_items", "cards", "vouchers", "codes"):
                if nested_key in item:
                    candidates.append(item.get(nested_key))
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
    return finance_error_public_text("en", code)


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
        service_type="core_digital_products",
        service_ref_id=str(service_ref_id),
        retail_amount=float(sale_price),
        wholesale_amount=float(cost_price),
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


async def _owner_notification_target() -> tuple[int | None, int | None]:
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
    return target_chat_id, target_thread_id


async def _notify_owner_stock_issue(
    *,
    bot: types.Bot,
    user_id: int,
    reseller_id: int,
    item_name: str,
    provider_error: str,
) -> None:
    target_chat_id, target_thread_id = await _owner_notification_target()
    if target_chat_id is None:
        return
    try:
        await bot.send_message(
            chat_id=int(target_chat_id),
            message_thread_id=int(target_thread_id) if target_thread_id is not None else None,
            text=t("en", "store_stock_issue_alert").format(
                user_id=int(user_id),
                reseller_id=int(reseller_id),
                item_name=item_name,
                provider_error=provider_error[:300],
            ),
        )
    except Exception:
        pass


def _manual_pending_text(lang: str) -> str:
    if str(lang or "").lower().startswith("ar"):
        return "تم استلام طلبك وهو قيد التنفيذ اليدوي.\nسنرسل لك إشعاراً عند اكتمال الشحن."
    return "Your order was received and is pending manual fulfillment.\nYou will be notified when it is completed."


def _manual_done_text(lang: str, *, item_name: str, order_id: str) -> str:
    if str(lang or "").lower().startswith("ar"):
        return f"تم تنفيذ طلبك بنجاح.\nالخدمة: {item_name}\nرقم الطلب: {order_id}"
    return f"Your order has been completed.\nItem: {item_name}\nOrder: {order_id}"


def _digital_game_order_summary_text(
    lang: str,
    *,
    order_id: str,
    game_name: str,
    package_name: str,
    player_id: str,
    price: float,
    status: str,
) -> str:
    status_text = str(status or "PENDING").strip().upper()
    order_ref = str(order_id or "-").strip()
    if order_ref and not order_ref.startswith("#"):
        order_ref = f"#{order_ref}"
    if str(lang or "").lower().startswith("ar"):
        lines = [
            "✅ تم إنشاء الطلب بنجاح!",
            "",
            f"🆔 رقم الطلب: {order_ref}",
            f"🎮 اللعبة: {game_name or '-'}",
            f"📦 الباقة: {package_name or '-'}",
            f"👤 Player ID: {player_id or '-'}",
        ]
        lines.extend(
            [
                f"💰 السعر: {format_usd(float(price or 0.0))}",
                f"📊 الحالة: {status_text}",
                "",
                "⏳ طلبك قيد المعالجة." if status_text == "PENDING" else "✅ تم تنفيذ طلبك.",
                "🙏 شكراً لك!",
            ]
        )
        return "\n".join(lines)

    lines = [
        "✅ Order Created Successfully!",
        "",
        f"🆔 Order ID: {order_ref}",
        f"🎮 Game: {game_name or '-'}",
        f"📦 Package: {package_name or '-'}",
        f"👤 Player ID: {player_id or '-'}",
    ]
    lines.extend(
        [
            f"💰 Price: {format_usd(float(price or 0.0))}",
            f"📊 Status: {status_text}",
            "",
            "⏳ Your order is being processed." if status_text == "PENDING" else "✅ Your order has been completed.",
            "🙏 Thank you!",
        ]
    )
    return "\n".join(lines)


def _digital_game_prefill_confirm_text(
    lang: str,
    *,
    game_name: str,
    package_name: str,
    player_id: str,
    server_id: str,
    requires_server: bool,
    price: float,
    usd_to_syp_rate: float,
) -> str:
    if str(lang or "").lower().startswith("ar"):
        lines = [
            f"🎮 {game_name or '-'}",
            f"📦 {package_name or '-'}",
            f"💰 {_store_price_line(lang, price, usd_to_syp_rate)}",
        ]
        if player_id:
            lines.append(f"👤 Player ID: {player_id}")
        if requires_server and server_id:
            lines.append(f"🖥️ Server ID: {server_id}")
        lines.extend(["", "هل تريد تأكيد الشراء؟"])
        return "\n".join(lines)

    lines = [
        f"🎮 {game_name or '-'}",
        f"📦 {package_name or '-'}",
        f"💰 {_store_price_line(lang, price, usd_to_syp_rate)}",
    ]
    if player_id:
        lines.append(f"👤 Player ID: {player_id}")
    if requires_server and server_id:
        lines.append(f"🖥️ Server ID: {server_id}")
    lines.extend(["", "Confirm this purchase?"])
    return "\n".join(lines)


def _manual_refund_text(lang: str, *, item_name: str, order_id: str) -> str:
    if str(lang or "").lower().startswith("ar"):
        return f"تعذر تنفيذ طلبك وتمت إعادة المبلغ إلى رصيدك.\nالخدمة: {item_name}\nرقم الطلب: {order_id}"
    return f"Your order could not be fulfilled and was refunded.\nItem: {item_name}\nOrder: {order_id}"


async def _notify_owner_manual_topup(
    *,
    bot: types.Bot,
    order: dict[str, Any],
    item_name: str,
    provider_code: str,
    external_order_id: str,
    player_data: dict[str, Any],
    delivery_lines: list[str],
) -> bool:
    text, markup = _manual_topup_notification_payload(
        order=order,
        item_name=item_name,
        provider_code=provider_code,
        external_order_id=external_order_id,
        player_data=player_data,
        delivery_lines=delivery_lines,
    )
    target_chat_id, target_thread_id = await _owner_notification_target()
    if target_chat_id is None:
        return False
    try:
        await bot.send_message(
            chat_id=int(target_chat_id),
            message_thread_id=int(target_thread_id) if target_thread_id is not None else None,
            text=text,
            reply_markup=markup,
        )
        return True
    except Exception:
        return False


def _manual_topup_notification_payload(
    *,
    order: dict[str, Any],
    item_name: str,
    provider_code: str,
    external_order_id: str,
    player_data: dict[str, Any],
    delivery_lines: list[str],
) -> tuple[str, InlineKeyboardMarkup]:
    order_id = str(order.get("_id") or "")
    user_id = int(order.get("user_id") or 0)
    reseller_id = int(order.get("reseller_id") or 0)
    params = [f"- {str(key).replace('_', ' ').title()}: {value}" for key, value in dict(player_data or {}).items() if str(value).strip()]
    vouchers = [f"- {line}" for line in list(delivery_lines or []) if str(line).strip()]
    lines = [
        "Manual digital top-up pending",
        f"Order: {order_id}",
        f"User: {user_id}",
        f"Reseller: {reseller_id}",
        f"Item: {item_name}",
        f"Provider: {provider_code or '-'}",
    ]
    if external_order_id:
        lines.append(f"Provider order: {external_order_id}")
    if params:
        lines.append("")
        lines.append("Customer data:")
        lines.extend(params)
    if vouchers:
        lines.append("")
        lines.append("Private voucher/code:")
        lines.extend(vouchers[:10])
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="تم الشحن", callback_data=f"dpm:done:{order_id}"),
                InlineKeyboardButton(text="استرجاع", callback_data=f"dpm:refund:{order_id}"),
            ]
        ]
    )
    return "\n".join(lines), markup


async def _notify_owner_pending_game_topup(
    *,
    bot: types.Bot,
    order: dict[str, Any],
    item_name: str,
    provider_code: str,
    external_order_id: str,
    game_name: str,
    player_id: str,
    server_id: str,
    reason: str,
) -> bool:
    player_data = {
        "game": game_name,
        "package": item_name,
        "player_id": player_id,
        "server_id": server_id,
        "reason": reason,
    }
    await update_order_details(
        order["_id"],
        {
            "provider_manual_review_required": True,
            "provider_error": reason,
            "fulfillment_mode": MANUAL_TOPUP_MODE,
            "manual_fulfillment_required": True,
            "manual_fulfillment_status": "pending",
            "manual_item_name": item_name,
            "number_mode": "digital_products",
        },
    )
    return await _notify_owner_manual_topup(
        bot=bot,
        order=order,
        item_name=item_name,
        provider_code=provider_code,
        external_order_id=external_order_id,
        player_data=player_data,
        delivery_lines=[],
    )


def _order_query_id(value: str) -> Any:
    raw = str(value or "").strip()
    if ObjectId.is_valid(raw):
        return ObjectId(raw)
    return raw


async def _find_order_for_owner_action(value: str) -> dict[str, Any] | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    primary_id = _order_query_id(raw)
    order = await db.orders.find_one({"_id": primary_id})
    if order:
        return order
    if primary_id != raw:
        return await db.orders.find_one({"_id": raw})
    return None


def _owner_action_allowed(user_id: int) -> bool:
    try:
        return int(user_id) == int(getattr(settings, "owner_id", 0) or 0)
    except Exception:
        return False


@router.callback_query(lambda c: c.data and c.data.startswith("dpm:done:"))
async def complete_manual_digital_topup(callback: types.CallbackQuery):
    if not _owner_action_allowed(int(callback.from_user.id)):
        return await callback.answer("Unauthorized", show_alert=True)
    order_id = str(callback.data or "").split(":", 2)[-1].strip()
    order = await _find_order_for_owner_action(order_id)
    if not order or str(order.get("fulfillment_mode") or "") != MANUAL_TOPUP_MODE:
        return await callback.answer("Order not found", show_alert=True)
    if str(order.get("status") or "") in {"success", "done"}:
        return await callback.answer("Already completed", show_alert=True)
    if str(order.get("status") or "") == "refunded":
        return await callback.answer("Already refunded", show_alert=True)

    await update_order_details(
        order["_id"],
        {
            "manual_fulfillment_status": "completed",
            "manual_fulfilled_by": int(callback.from_user.id),
            "manual_fulfilled_at": datetime.now(UTC),
        },
    )
    await update_order_status(order["_id"], "success")
    user = await get_user(int(order.get("user_id") or 0))
    lang = (user or {}).get("language", "en")
    item_name = str(order.get("manual_item_name") or order.get("service_ref_id") or "-")
    try:
        await callback.bot.send_message(
            chat_id=int(order.get("user_id")),
            text=_manual_done_text(lang, item_name=item_name, order_id=str(order.get("_id"))),
        )
    except Exception:
        pass
    if callback.message:
        try:
            await callback.message.edit_text(f"{callback.message.text or ''}\n\nStatus: completed")
        except Exception:
            pass
    await callback.answer("Completed")


@router.callback_query(lambda c: c.data and c.data.startswith("dpm:refund:"))
async def refund_manual_digital_topup(callback: types.CallbackQuery):
    if not _owner_action_allowed(int(callback.from_user.id)):
        return await callback.answer("Unauthorized", show_alert=True)
    order_id = str(callback.data or "").split(":", 2)[-1].strip()
    order = await _find_order_for_owner_action(order_id)
    if not order or str(order.get("fulfillment_mode") or "") != MANUAL_TOPUP_MODE:
        return await callback.answer("Order not found", show_alert=True)
    if str(order.get("status") or "") == "refunded":
        return await callback.answer("Already refunded", show_alert=True)
    if str(order.get("status") or "") in {"success", "done"}:
        return await callback.answer("Already completed", show_alert=True)

    sale_price, cost_price = extract_order_amounts(order)
    await _core_refund(
        user_id=int(order.get("user_id") or 0),
        reseller_id=int(order.get("reseller_id") or 0),
        order=order,
        sale_price=float(sale_price),
        cost_price=float(cost_price),
    )
    await update_order_details(
        order["_id"],
        {
            "manual_fulfillment_status": "refunded",
            "manual_refunded_by": int(callback.from_user.id),
            "manual_refunded_at": datetime.now(UTC),
        },
    )
    user = await get_user(int(order.get("user_id") or 0))
    lang = (user or {}).get("language", "en")
    item_name = str(order.get("manual_item_name") or order.get("service_ref_id") or "-")
    try:
        await callback.bot.send_message(
            chat_id=int(order.get("user_id")),
            text=_manual_refund_text(lang, item_name=item_name, order_id=str(order.get("_id"))),
        )
    except Exception:
        pass
    if callback.message:
        try:
            await callback.message.edit_text(f"{callback.message.text or ''}\n\nStatus: refunded")
        except Exception:
            pass
    await callback.answer("Refunded")


@router.message(lambda msg: bool(msg.text) and str(msg.text).strip().startswith("/recover_digital_order"))
async def recover_manual_digital_order(message: types.Message):
    if not _owner_action_allowed(int(message.from_user.id)):
        return await message.answer("Unauthorized")
    parts = str(message.text or "").strip().split(maxsplit=2)
    if len(parts) < 2:
        return await message.answer("Usage: /recover_digital_order <order_id> [item name]")

    order_id = parts[1].strip()
    item_name_override = parts[2].strip() if len(parts) >= 3 else ""
    order = await _find_order_for_owner_action(order_id)
    if not order:
        return await message.answer("Order not found.")
    if str(order.get("service_type") or "") != "core_digital_products" and str(order.get("number_mode") or "") != "digital_products":
        return await message.answer("This is not a digital products order.")
    if str(order.get("status") or "").strip().lower() in {"success", "done", "refunded", "failed", "cancelled"}:
        return await message.answer(f"Order is already {order.get('status')}.")

    provider_code = str(order.get("provider_code") or "").strip() or str(order.get("service_ref_id") or "provider").split(":", 1)[0]
    external_order_id = str(order.get("provider_order_id") or "").strip()
    game_id = str(order.get("game_id") or "").strip()
    try:
        display_game_name = _find_game_name(game_id, await get_catalog_snapshot(force=False)) if game_id else ""
    except Exception:
        display_game_name = ""
    item_name = item_name_override or str(order.get("manual_item_name") or order.get("service_ref_id") or "Digital product")
    player_id = str(order.get("player_id") or "").strip()
    server_id = str(order.get("server_id") or "").strip()
    status_resp = await _poll_provider_order_status(provider=provider_code, external_order_id=external_order_id) if external_order_id else None
    provider_status = _extract_provider_status(status_resp)
    if status_resp is not None:
        await update_order_details(
            order["_id"],
            {
                "provider_status_response": status_resp,
                "provider_status": provider_status,
                "provider_recovery_checked_at": datetime.now(UTC),
            },
        )
    if status_resp is not None and _provider_status_is_success(status_resp):
        delivery_lines = _extract_voucher_lines(status_resp)
        await update_order_status(order["_id"], "success")
        await update_order_details(
            order["_id"],
            {
                "provider_manual_review_required": False,
                "manual_fulfillment_required": False,
                "manual_fulfillment_status": "provider_completed",
                "provider_recovery_outcome": "success",
                "delivery_lines": delivery_lines,
            },
        )
        user = await get_user(int(order.get("user_id") or 0))
        lang = (user or {}).get("language", "en")
        if delivery_lines:
            user_body = [
                t(lang, "purchase_complete_plain"),
                f"{t(lang, 'store_order_label')}: {order.get('_id')}",
                f"{t(lang, 'store_provider_ref_label')}: {external_order_id}",
                "",
                f"{t(lang, 'delivery_plain')}:",
                *[f"- {line}" for line in delivery_lines],
            ]
            try:
                await message.bot.send_message(chat_id=int(order.get("user_id") or 0), text="\n".join(user_body))
            except Exception:
                pass
        else:
            try:
                await message.bot.send_message(
                    chat_id=int(order.get("user_id") or 0),
                    text=_digital_game_order_summary_text(
                        lang,
                        order_id=str(order.get("_id") or ""),
                        game_name=display_game_name or game_id or "Digital product",
                        package_name=item_name,
                        player_id=player_id,
                        price=float(_money_decimal(order.get("retail_amount") or order.get("sale_price") or 0)),
                        status="SUCCESS",
                    ),
                )
            except Exception:
                pass
        return await message.answer(
            "Provider order is already completed.\n"
            f"Order: {order_id}\n"
            f"Provider: {provider_code or '-'}\n"
            f"Provider order: {external_order_id or '-'}\n"
            f"Provider status: {provider_status or '-'}\n"
            f"Delivery items: {len(delivery_lines)}"
        )
    if status_resp is not None and _provider_status_is_failure(status_resp):
        return await message.answer(
            "Provider order is failed/cancelled. Use the refund action from order tools or refund manually after review.\n"
            f"Order: {order_id}\n"
            f"Provider: {provider_code or '-'}\n"
            f"Provider order: {external_order_id or '-'}\n"
            f"Provider status: {provider_status or '-'}"
        )
    sent = await _notify_owner_pending_game_topup(
        bot=message.bot,
        order=order,
        item_name=item_name,
        provider_code=provider_code,
        external_order_id=external_order_id,
        game_name=display_game_name or game_id or "Digital product",
        player_id=player_id,
        server_id=server_id,
        reason="Owner recovered missing manual fulfillment notification.",
    )
    if not sent:
        text, markup = _manual_topup_notification_payload(
            order=order,
            item_name=item_name,
            provider_code=provider_code,
            external_order_id=external_order_id,
            player_data={
                "game": display_game_name or game_id or "Digital product",
                "package": item_name,
                "player_id": player_id,
                "server_id": server_id,
                "reason": "Owner recovered missing manual fulfillment notification.",
            },
            delivery_lines=[],
        )
        await message.answer("Owner notification target failed. Recovery card is shown here instead.")
        await message.answer(text, reply_markup=markup)
        return
    await message.answer(
        "Recovery notification sent.\n"
        f"Order: {order_id}\n"
        f"Provider order: {external_order_id or '-'}"
    )


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


async def _increment_usage(name: str | None) -> None:
    key = _norm(name)
    if not key:
        return
    usage = _load_usage()
    usage[key] = int(usage.get(key, 0) or 0) + 1
    _save_usage(usage)
    try:
        await increment_service_usage(service_name=key, category="digital_products")
    except Exception:
        pass


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


def _build_game_rows(games: list[dict[str, Any]], *, limit: int | None = None) -> list[list[InlineKeyboardButton]]:
    ranked = _rank_games(list(games or []))
    if isinstance(limit, int) and limit > 0:
        ranked = ranked[:limit]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for game in ranked:
        gid = str(game.get("id") or "").strip()
        if not gid:
            continue
        row.append(InlineKeyboardButton(text=str(game.get("name") or "-")[:28], callback_data=f"gst:game:{gid}"))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def _is_numeric_topup_name(raw_name: str) -> bool:
    compact = raw_name.replace(",", "").replace("+", " ").strip()
    if not compact:
        return False
    if re.fullmatch(r"[\d\s]+", compact):
        return True
    return bool(re.match(r"^\d+(\s+[A-Za-z]+.*)?$", compact))


def _find_game_name(game_id: str, snapshot: dict[str, Any] | None = None) -> str:
    games = list((snapshot or {}).get("games") or [])
    for game in games:
        if str(game.get("id") or "").strip() == str(game_id).strip():
            return str(game.get("name") or game_id or "-").strip()
    return str(game_id or "-").strip()


def _game_title(lang: str, game_name: str, section_title: str | None = None) -> str:
    if section_title:
        return t(lang, "store_game_section_title").format(game=game_name, section=section_title)
    return t(lang, "store_game_title").format(game=game_name)


def _normalize_game_item_name(name: str) -> str:
    text = " ".join(str(name or "").strip().split())
    text = text.replace("Activation Pass Bundle", "Bundle")
    text = text.replace("Activation Pass", "Pass")
    text = text.replace("Monthly Advanced Battle Pass", "Advanced Battle Pass")
    text = text.replace("Monthly Premium Battle Pass", "Premium Battle Pass")
    text = text.replace("Premium Spiritual Jade", "Jade")
    text = text.replace("Prime Plus", "Prime+")
    text = text.replace("First Purchase Pack", "First Purchase")
    text = text.replace("Weekly Deal Pack", "Weekly Deal")
    text = text.replace("Value Pack", "Value")
    return text


def _display_game_item_name(item: dict[str, Any], *, group_key: str) -> str:
    raw_name = str(item.get("clean_name") or item.get("name") or "-").strip()
    name = _normalize_game_item_name(raw_name)
    if group_key == "topup":
        compact = name.replace(",", "").strip()
        if re.fullmatch(r"\d+", compact):
            return compact
        match = re.match(r"^(\d+)\s*([A-Za-z].*)$", name)
        if match:
            unit = match.group(2).strip()
            if len(unit) > 10:
                unit = unit.split()[0]
            return f"{match.group(1)} {unit}".strip()
    return name


def _sort_game_group_items(items: list[dict[str, Any]], *, group_key: str) -> list[dict[str, Any]]:
    def _key(item: dict[str, Any]) -> tuple[Any, ...]:
        raw_name = str(item.get("clean_name") or item.get("name") or "").strip()
        display_name = _display_game_item_name(item, group_key=group_key)
        if group_key == "topup":
            digits = re.findall(r"\d+", raw_name.replace(",", ""))
            if digits:
                return (0, int(digits[0]), _natural_sort_key(display_name))
        return (1, _natural_sort_key(display_name))

    return sorted(list(items or []), key=_key)


def _classify_game_item_group(game_id: str, item: dict[str, Any]) -> str:
    name = str(item.get("clean_name") or item.get("name") or "").strip()
    lowered = _norm(name)
    if not lowered:
        return "specials"
    override = _GAME_GROUP_OVERRIDES.get(game_id) or {}
    for group_key, keywords in override.items():
        if keywords and any(keyword in lowered for keyword in keywords):
            return group_key
    if any(hint in lowered for hint in _GAME_PASS_HINTS):
        return "passes"
    if any(hint in lowered for hint in _GAME_SPECIAL_HINTS):
        return "specials"
    if _is_numeric_topup_name(name) or any(hint in lowered for hint in _GAME_TOPUP_HINTS):
        return "topup"
    # Keep classification scoped to the current game only.
    if game_id in {"pubgm", "mlbb", "mla", "mlbb_br", "mlbb_exclusive", "hok"}:
        return "topup"
    return "specials"


def _group_game_items(game_id: str, items: list[dict[str, Any]], lang: str) -> list[tuple[str, str, list[dict[str, Any]]]]:
    buckets: dict[str, list[dict[str, Any]]] = {"topup": [], "passes": [], "specials": []}
    for item in items:
        buckets[_classify_game_item_group(game_id, item)].append(item)
    ordered: list[tuple[str, str, list[dict[str, Any]]]] = []
    labels = {
        "topup": t(lang, "store_game_group_topup"),
        "passes": t(lang, "store_game_group_passes"),
        "specials": t(lang, "store_game_group_specials"),
    }
    for key in ("topup", "passes", "specials"):
        grouped_items = buckets.get(key) or []
        if grouped_items:
            ordered.append((key, labels[key], _sort_game_group_items(grouped_items, group_key=key)))
    return ordered


async def _render_game_group_list(
    callback: types.CallbackQuery,
    *,
    game_id: str,
    game_name: str,
    items: list[dict[str, Any]],
    lang: str,
) -> bool:
    grouped = _group_game_items(game_id, items, lang)
    if len(grouped) <= 1:
        return False
    rows: list[list[InlineKeyboardButton]] = []
    for key, label, grouped_items in grouped:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{label} ({len(grouped_items)})",
                    callback_data=f"gst:gamegroup:{game_id}:{key}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:gameroot")])
    return await _edit_callback_target(
        callback,
        _game_title(lang, game_name, t(lang, "store_game_groups_title")),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _render_game_group_items(
    callback: types.CallbackQuery,
    *,
    game_id: str,
    game_name: str,
    group_key: str,
    items: list[dict[str, Any]],
    lang: str,
    back_callback: str,
) -> bool:
    usd_to_syp_rate = await _resolve_usd_to_syp_rate(callback.bot.id)
    markup_percent = await _resolve_digital_products_markup_percent()
    rows = _product_grid(
        items[:60],
        callback_prefix=f"gst:gameitem:{game_id}:{group_key}",
        game_id=game_id,
        game_name=game_name,
        columns=2,
        usd_to_syp_rate=usd_to_syp_rate,
        markup_percent=markup_percent,
        group_key=group_key,
    )
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data=back_callback)])
    return await _edit_callback_target(
        callback,
        _game_title(lang, game_name, t(lang, f"store_game_group_{group_key}")),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


def _product_grid(
    items: list[dict[str, Any]],
    *,
    callback_prefix: str,
    game_id: str | None = None,
    game_name: str | None = None,
    group_key: str = "topup",
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
        price = float(
            _resolve_game_sale_price_decimal(
                game_id=game_id,
                game_name=game_name,
                provider_price=item.get("price"),
                markup_percent=markup_percent,
            )
        )
        name = _display_game_item_name(item, group_key=group_key)
        text = f"{name[:18]} | {_fmt_dual_price(price, usd_to_syp_rate)}" if price > 0 else name[:28]
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
        manual_card = dict(item.get("manual_card") or {}) if bool(item.get("lona_manual")) else {}
        if manual_card:
            rate = _percent_label(manual_card.get("rate_percent") or 0)
            if str(manual_card.get("kind") or "") == "fixed":
                price = float(_to_decimal(item.get("price") or 0))
                label = f"{raw_name} | {rate} | {_fmt_dual_price(price, usd_to_syp_rate)}"[:62]
            else:
                label = f"{raw_name} | {rate}"[:62]
        else:
            price = float(_apply_markup_decimal(item.get("price"), markup_percent))
            label = f"{raw_name} | {_store_price_line('en', price, usd_to_syp_rate)}"[:62]
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


_ESIM_INLINE_PREFIX = "esim_country"
_ESIM_PICK_PREFIX = "__esim_country__::"


def _esim_text(lang: str, en: str, ar: str) -> str:
    return ar if str(lang).lower().startswith("ar") else en


def _esim_country_pick_token(country: str) -> str:
    return f"{_ESIM_PICK_PREFIX}{country}"


def _parse_esim_country_pick(text: str | None) -> str | None:
    raw = str(text or "").strip()
    if not raw.startswith(_ESIM_PICK_PREFIX):
        return None
    country = raw[len(_ESIM_PICK_PREFIX) :].strip()
    return country or None


def _esim_countries_text(lang: str, countries: list[str]) -> str:
    if countries:
        joined = "، ".join(countries) if str(lang).lower().startswith("ar") else ", ".join(countries)
        return _esim_text(lang, f"Current route: {joined}", f"رحلتك الحالية: {joined}")
    return _esim_text(lang, "No countries selected yet.", "لم يتم اختيار أي دولة بعد.")


def _esim_mode_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_esim_text(lang, "One Country", "اختيار دولة واحدة"), callback_data="esim:mode:single")],
            [InlineKeyboardButton(text=_esim_text(lang, "Multiple Countries", "اختيار دول متعددة"), callback_data="esim:mode:multi")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")],
        ]
    )


def _esim_route_keyboard(lang: str, countries: list[str], *, mode: str = "multi") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    max_count = 5 if mode == "multi" else 1
    if len(countries) < max_count:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_esim_text(lang, "🌍 Choose Another Country", "🌍 اختر دولة أخرى") if countries else _esim_text(lang, "🌍 Choose Country", "🌍 اختر دولة"),
                    switch_inline_query_current_chat=f"{_ESIM_INLINE_PREFIX} ",
                )
            ]
        )
    for country in countries:
        rows.append(
            [
                InlineKeyboardButton(
                    text=country,
                    callback_data="esim:noop",
                ),
                InlineKeyboardButton(
                    text=_esim_text(lang, "✖️ Remove", "✖️ إزالة"),
                    callback_data=f"esim:remove:{country_slug(country)}",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text=_esim_text(lang, "✅ Done", "✅ انتهى اختيار الدول"), callback_data="esim:done"),
            InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu"),
        ]
    )
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="esim:back:mode")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _esim_single_country_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_esim_text(lang, "🌍 Choose More Countries", "🌍 اختيار دول أخرى"), callback_data="esim:single:add_more"),
            ],
            [
                InlineKeyboardButton(text=_esim_text(lang, "➡️ Continue With This Country", "➡️ استمرار بهذه الدولة فقط"), callback_data="esim:single:continue"),
            ],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")],
        ]
    )


def _esim_days_keyboard(lang: str, days: list[int], *, back_callback: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for day in days:
        row.append(InlineKeyboardButton(text=_esim_text(lang, f"{day} Days", f"{day} يوم"), callback_data=f"esim:days:{day}"))
        if len(row) >= 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data=back_callback)])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _esim_usage_keyboard(lang: str, *, back_callback: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_esim_text(lang, "Less than 5 GB", "أقل من 5 GB"), callback_data="esim:usage:low")],
        [InlineKeyboardButton(text=_esim_text(lang, "5 to 10 GB", "من 5 إلى 10 GB"), callback_data="esim:usage:mid")],
        [InlineKeyboardButton(text=_esim_text(lang, "More than 10 GB", "أكثر من 10 GB"), callback_data="esim:usage:high")],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data=back_callback)],
        [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _esim_package_keyboard(lang: str, offers: list[dict[str, Any]], *, back_callback: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, row in enumerate(offers):
        rows.append([InlineKeyboardButton(text=esim_offer_button_label(row, lang=lang), callback_data=f"esim:pkg:{index}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data=back_callback)])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _esim_summary_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data="esim:buy")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="esim:back:usage")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="gst:menu")],
        ]
    )


async def _esim_render_offer_summary(
    *,
    callback: types.CallbackQuery,
    state: FSMContext,
    lang: str,
    offer: dict[str, Any],
) -> None:
    data = await state.get_data()
    selected = list(data.get("esim_selected_countries") or [])
    usage_key = str(data.get("esim_usage_key") or "low")
    summary_lines = [
        _esim_text(lang, "Recommended eSIM", "أفضل باقة مقترحة"),
        "",
        _esim_countries_text(lang, selected),
        _esim_text(lang, f"Duration: {int(data.get('esim_selected_days') or 0)} days", f"المدة: {int(data.get('esim_selected_days') or 0)} يوم"),
        _esim_text(lang, f"Usage: {esim_usage_label(usage_key, lang=lang)}", f"حجم الاستخدام: {esim_usage_label(usage_key, lang=lang)}"),
        "",
        esim_offer_summary(offer, lang=lang),
    ]
    kb = _esim_summary_keyboard(lang)
    if callback.message:
        await _safe_edit_message(callback.message, "\n".join(summary_lines), reply_markup=kb)


def _esim_price_to_units(price_usd: float) -> int:
    return int(round(float(price_usd or 0.0) * 10000))


def _esim_service_ref(offer: dict[str, Any]) -> str:
    refs: list[str] = []
    for part in offer.get("parts") or []:
        plan = dict(part.get("plan") or {})
        ref = str(plan.get("slug") or plan.get("package_code") or plan.get("code") or part.get("country") or part.get("region_name") or "").strip()
        if ref:
            refs.append(ref)
    return "esim:" + "|".join(refs)


def _esim_package_info_list(offer: dict[str, Any], *, days: int) -> list[dict[str, Any]]:
    package_info_list: list[dict[str, Any]] = []
    for part in offer.get("parts") or []:
        plan = dict(part.get("plan") or {})
        row: dict[str, Any] = {"count": 1}
        package_code = str(plan.get("package_code") or plan.get("code") or "").strip()
        slug = str(plan.get("slug") or "").strip()
        if package_code:
            row["packageCode"] = package_code
        elif slug:
            row["packageCode"] = slug
        else:
            continue
        row["price"] = _esim_price_to_units(float(plan.get("_cost_price_usd") or plan.get("price_usd") or 0.0))
        if int(plan.get("data_type_code") or 0) in {2, 3, 4}:
            row["periodNum"] = int(days)
        package_info_list.append(row)
    return package_info_list


async def _esim_query_profiles_wait(
    client: EsimAccessClient,
    *,
    order_no: str,
    attempts: int = 6,
    delay_sec: float = 5.0,
) -> dict[str, Any] | None:
    last_resp: dict[str, Any] | None = None
    for attempt in range(max(1, int(attempts))):
        last_resp = await client.query_profiles(order_no=order_no, page_num=1, page_size=50)
        if bool(last_resp.get("success")):
            return last_resp
        error_code = str(last_resp.get("errorCode") or "").strip()
        if error_code != "200010":
            return last_resp
        if attempt < attempts - 1:
            await asyncio.sleep(max(0.0, float(delay_sec)))
    return last_resp


def _esim_extract_profiles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    obj = payload.get("obj")
    if isinstance(obj, dict):
        value = obj.get("esimList")
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _esim_delivery_text(
    *,
    lang: str,
    profiles: list[dict[str, Any]],
    sale_price: float,
    balance: float,
    order_id: str,
    order_no: str,
) -> str:
    lines = [
        t(lang, "purchase_complete_plain"),
        f"{t(lang, 'store_debited_label')}: {format_usd(float(sale_price or 0.0))}",
        f"{t(lang, 'store_balance_label')}: {format_usd(float(balance or 0.0))}",
        f"{t(lang, 'store_order_label')}: {order_id}",
    ]
    if order_no:
        lines.append(f"{t(lang, 'store_provider_ref_label')}: {order_no}")
    for index, profile in enumerate(profiles, start=1):
        lines.extend(
            [
                "",
                _esim_text(lang, f"eSIM #{index}", f"eSIM #{index}"),
                f"ICCID: {str(profile.get('iccid') or '-').strip()}",
                f"QR: {str(profile.get('qrCodeUrl') or '-').strip()}",
                f"AC: {str(profile.get('ac') or '-').strip()}",
            ]
        )
    return "\n".join(lines)


async def _esim_store_route_message_id(state: FSMContext, message_id: int | None) -> None:
    if isinstance(message_id, int) and message_id > 0:
        await state.update_data(esim_route_message_id=message_id)


async def _esim_render_route_screen(
    *,
    target: types.Message | types.CallbackQuery,
    state: FSMContext,
    lang: str,
    note: str | None = None,
) -> None:
    data = await state.get_data()
    countries = list(data.get("esim_selected_countries") or [])
    mode = str(data.get("esim_selection_mode") or "multi")
    text = _esim_text(
        lang,
        "eSIM Route\n\nChoose the countries you will pass through.",
        "eSIM الرحلة\n\nاختر الدول التي ستمر بها.",
    )
    text += f"\n\n{_esim_countries_text(lang, countries)}"
    if note:
        text += f"\n\n{note}"
    kb = _esim_route_keyboard(lang, countries, mode=mode)
    if isinstance(target, types.CallbackQuery):
        if target.message:
            await _safe_edit_message(target.message, text, reply_markup=kb)
    else:
        sent = await target.answer(text, reply_markup=kb)
        await _esim_store_route_message_id(state, getattr(sent, "message_id", None))


async def _esim_edit_route_message(
    *,
    message: types.Message,
    state: FSMContext,
    lang: str,
    note: str | None = None,
) -> None:
    data = await state.get_data()
    route_message_id = int(data.get("esim_route_message_id") or 0)
    countries = list(data.get("esim_selected_countries") or [])
    mode = str(data.get("esim_selection_mode") or "multi")
    text = _esim_text(
        lang,
        "eSIM Route\n\nChoose the countries you will pass through.",
        "eSIM الرحلة\n\nاختر الدول التي ستمر بها.",
    )
    text += f"\n\n{_esim_countries_text(lang, countries)}"
    if note:
        text += f"\n\n{note}"
    kb = _esim_route_keyboard(lang, countries, mode=mode)
    if route_message_id > 0:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=route_message_id,
                text=text,
                reply_markup=kb,
            )
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
        except Exception:
            pass
    sent = await message.answer(text, reply_markup=kb)
    await _esim_store_route_message_id(state, getattr(sent, "message_id", None))


def _esim_days_prompt_text(lang: str, countries: list[str]) -> str:
    chosen = "، ".join(countries) if str(lang).lower().startswith("ar") else ", ".join(countries)
    return _esim_text(
        lang,
        f"Selected countries: {chosen}\n\nChoose the trip duration.",
        f"الدول المختارة: {chosen}\n\nاختر مدة الرحلة.",
    )


def _esim_usage_prompt_text(lang: str, countries: list[str], days: int) -> str:
    chosen = "، ".join(countries) if str(lang).lower().startswith("ar") else ", ".join(countries)
    return _esim_text(
        lang,
        f"Selected countries: {chosen}\nDuration: {days} days\n\nChoose the expected data usage.",
        f"الدول المختارة: {chosen}\nالمدة: {days} يوم\n\nاختر حجم الاستخدام المتوقع.",
    )


def _esim_mode_text(lang: str) -> str:
    return _esim_text(
        lang,
        "eSIM\n\nChoose how you want to search:\n- One country\n- Multiple countries",
        "eSIM\n\nاختر طريقة البحث:\n- اختيار دولة واحدة\n- اختيار دول متعددة",
    )


@router.message(lambda m: _is_giftcards_trigger(m.text))
async def open_giftcards_section(message: types.Message, state):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    await _hide_reply_keyboard(message, lang)

    # Primary source: G2Bulk API catalogue.
    snapshot = await get_catalog_snapshot(force=False)
    categories = _gift_categories_for_ui(snapshot)
    if categories:
        rows = _build_gift_categories_rows(categories[:60])
        rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:menu")])
        await message.answer(
            f"{t(lang, 'store_gift_title')}\n\n{t(lang, 'store_search_pick_hint')}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return

    # ID-INFO fallback is archived.
    return await message.answer(t(lang, "store_no_gift_categories"), reply_markup=ReplyKeyboardRemove())


@router.message(lambda m: _is_mobile_topups_trigger(m.text) or _is_sim_topup_trigger(m.text))
async def open_mobile_topups_section(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    await state.clear()
    await state.set_state(SimTopupFlow.choosing_topup_kind)
    await state.update_data(
        sim_section_kind="",
        sim_phone="",
        sim_country_code="",
        sim_brand_key="",
        sim_brand_name="",
        sim_offers=[],
        sim_selected_offer=None,
    )
    await _hide_reply_keyboard(message, lang)
    await _sim_render_hub(message, state, lang)


@router.callback_query(lambda c: c.data == "simtopup:back:hub")
async def sim_topup_back_to_hub(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await state.set_state(SimTopupFlow.choosing_topup_kind)
    await _sim_render_hub(callback, state, lang)
    await callback.answer()


@router.callback_query(lambda c: c.data == "simtopup:esim")
async def sim_topup_open_esim(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    await state.clear()
    await state.set_state(EsimRouteFlow.choosing_mode)
    await state.update_data(
        esim_selected_countries=[],
        esim_selected_mode="",
        esim_selection_mode="",
        esim_selected_days=0,
        esim_candidate_plans=[],
        esim_usage_key="",
        esim_filtered_offers=[],
        esim_recommended_offer=None,
    )
    if callback.message:
        await _safe_edit_message(callback.message, _esim_mode_text(lang), reply_markup=_esim_mode_keyboard(lang))
        await _esim_store_route_message_id(state, getattr(callback.message, "message_id", None))
    await callback.answer()


@router.callback_query(lambda c: c.data == "simtopup:physical")
async def sim_topup_open_physical(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    await state.set_state(SimTopupFlow.choosing_physical_kind)
    await _sim_render_physical_kind(callback, state, lang)
    await callback.answer()


@router.callback_query(lambda c: c.data == "simtopup:back:physical")
async def sim_topup_back_to_physical(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await state.set_state(SimTopupFlow.choosing_physical_kind)
    await _sim_render_physical_kind(callback, state, lang)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("simtopup:physical:"))
async def sim_topup_choose_physical_kind(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    section = str(callback.data or "").split(":")[-1].strip().lower()
    if section not in {"balance", "data"}:
        await callback.answer()
        return
    await state.set_state(SimTopupFlow.waiting_phone)
    await state.update_data(sim_section_kind=section, sim_phone="", sim_country_code="", sim_brand_key="", sim_brand_name="", sim_offers=[], sim_selected_offer=None)
    await _sim_render_phone_prompt(callback=callback, state=state, lang=lang, section=section)
    await callback.answer()


@router.message(SimTopupFlow.waiting_phone)
async def sim_topup_collect_phone(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    raw_phone = str(message.text or "").strip()
    phone = re.sub(r"[^\d+]", "", raw_phone)
    if not phone or not phone.startswith("+") or len(re.sub(r"\D", "", phone)) < 7:
        return await _sim_edit_anchor(
            message=message,
            state=state,
            text=_sim_text(lang, "Send a valid phone number in international format.\nExample: +447700900000", "أرسل رقمًا صحيحًا بصيغة دولية.\nمثال: +447700900000"),
            reply_markup=_sim_phone_keyboard(lang),
        )
    await state.update_data(sim_phone=phone, sim_country_code="", sim_brand_key="", sim_brand_name="", sim_offers=[], sim_selected_offer=None)
    try:
        await message.delete()
    except Exception:
        pass

    client = ZenditClient()
    prefix_country_code = _sim_country_from_phone(phone)
    country_code = prefix_country_code
    brand_key = ""
    brand_name = ""
    if client.configured():
        status, payload = await client.msisdn_lookup(phone)
        if status == 200 and isinstance(payload, dict):
            lookup = dict(payload.get("result") or payload.get("data") or payload)
            lookup_country_code = str(lookup.get("country") or lookup.get("countryCode") or lookup.get("iso2") or "").strip().upper()
            if not country_code and lookup_country_code:
                country_code = lookup_country_code
            brand_key = str(lookup.get("brand") or lookup.get("operatorCode") or lookup.get("operatorId") or "").strip()
            brand_name = str(lookup.get("brandName") or lookup.get("operatorName") or lookup.get("brand") or "").strip()
    if len(country_code) == 2:
        await state.update_data(sim_country_code=country_code)
        if brand_key:
            offers = await _sim_fetch_offers(country_code, str((await state.get_data()).get("sim_section_kind") or ""), brand=brand_key)
            markup_percent = _resolve_physical_sim_markup_percent(str((await state.get_data()).get("sim_section_kind") or ""))
            prepared = _sim_prepare_offers(offers, section=str((await state.get_data()).get("sim_section_kind") or ""), markup_percent=markup_percent)
            if prepared:
                await state.set_state(SimTopupFlow.choosing_offer)
                await state.update_data(sim_brand_key=brand_key, sim_brand_name=brand_name or brand_key, sim_offers=prepared)
                await _sim_render_offers(message=message, state=state, lang=lang, offers=prepared)
                return
        direct_offers = await _sim_fetch_offers(country_code, str((await state.get_data()).get("sim_section_kind") or ""), brand=None)
        if direct_offers:
            markup_percent = _resolve_physical_sim_markup_percent(str((await state.get_data()).get("sim_section_kind") or ""))
            prepared = _sim_prepare_offers(direct_offers, section=str((await state.get_data()).get("sim_section_kind") or ""), markup_percent=markup_percent)
            await state.set_state(SimTopupFlow.choosing_offer)
            await state.update_data(sim_brand_key="", sim_brand_name=_sim_text(lang, "All operators", "كل المشغلين"), sim_offers=prepared, sim_selected_offer=None)
            await _sim_render_offers(message=message, state=state, lang=lang, offers=prepared)
            return
        brands = await _sim_country_brands(country_code, str((await state.get_data()).get("sim_section_kind") or ""))
        if not brands:
            await state.set_state(SimTopupFlow.choosing_country)
            await _sim_render_country_prompt(
                message=message,
                state=state,
                lang=lang,
                note=_sim_text(
                    lang,
                    f"Detected country: {_sim_country_display_name(country_code)}. This provider does not seem to have available offers for it right now. Choose another country if needed.",
                    f"تم التعرف على الدولة: {_sim_country_display_name(country_code)}. يبدو أن هذا المزود لا يملك عروضًا متاحة لها حاليًا. اختر دولة أخرى عند الحاجة.",
                ),
            )
            return
        await _sim_render_brand_prompt(message=message, state=state, lang=lang, country_code=country_code, section=str((await state.get_data()).get("sim_section_kind") or ""))
        return

    await state.set_state(SimTopupFlow.choosing_country)
    await _sim_render_country_prompt(message=message, state=state, lang=lang)


@router.inline_query(lambda iq: (iq.query or "").strip().lower().startswith(_SIM_COUNTRY_INLINE_PREFIX))
async def inline_sim_country_search(iq: types.InlineQuery):
    query = re.sub(rf"^\s*{_SIM_COUNTRY_INLINE_PREFIX}\s*", "", str(iq.query or "").strip(), flags=re.IGNORECASE)
    rows = await _sim_search_countries("all", query, limit=20)
    results: list[types.InlineQueryResultArticle] = []
    for row in rows:
        code = str(row.get("code") or "").strip().upper()
        name = str(row.get("name") or code).strip()
        if not code:
            continue
        results.append(
            types.InlineQueryResultArticle(
                id=f"simtopup_country_{code}",
                title=name,
                description=code,
                input_message_content=types.InputTextMessageContent(message_text=_sim_country_token(code)),
            )
        )
    await iq.answer(results, cache_time=5, is_personal=True)


@router.message(SimTopupFlow.choosing_country)
async def sim_topup_pick_country(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    raw = str(message.text or "").strip()
    code = ""
    if raw.startswith(_SIM_COUNTRY_TOKEN_PREFIX):
        code = raw[len(_SIM_COUNTRY_TOKEN_PREFIX):].strip().upper()
    else:
        matches = await _sim_country_matches(raw, limit=6)
        if len(matches) == 1:
            code = str(matches[0].get("code") or "").strip().upper()
        elif len(matches) > 1:
            lines = [_sim_text(lang, "Multiple countries matched. Send one of these names/codes:", "وجدت أكثر من دولة مطابقة. أرسل أحد هذه الأسماء/الرموز:")]
            lines.extend([f"- {row.get('name')} ({row.get('code')})" for row in matches])
            await _sim_edit_anchor(message=message, state=state, text="\n".join(lines), reply_markup=_sim_country_keyboard(lang))
            try:
                await message.delete()
            except Exception:
                pass
            return
    if len(code) != 2:
        await _sim_edit_anchor(
            message=message,
            state=state,
            text=_sim_text(lang, "Country not recognized. Send the country name/code or use the button below.", "لم أتعرف على الدولة. أرسل اسم الدولة/رمزها أو استخدم الزر أدناه."),
            reply_markup=_sim_country_keyboard(lang),
        )
        try:
            await message.delete()
        except Exception:
            pass
        return
    try:
        await message.delete()
    except Exception:
        pass
    data = await state.get_data()
    section = str(data.get("sim_section_kind") or "").strip().lower()
    await state.update_data(sim_country_code=code, sim_brand_key="", sim_brand_name="", sim_offers=[], sim_selected_offer=None)
    await _sim_render_brand_prompt(message=message, state=state, lang=lang, country_code=code, section=section)


@router.callback_query(lambda c: c.data == "simtopup:back:phone")
async def sim_topup_back_to_phone(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    section = str((await state.get_data()).get("sim_section_kind") or "").strip().lower()
    await state.set_state(SimTopupFlow.waiting_phone)
    await _sim_render_phone_prompt(callback=callback, state=state, lang=lang, section=section)
    await callback.answer()


@router.callback_query(lambda c: c.data == "simtopup:back:country")
async def sim_topup_back_to_country(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await state.set_state(SimTopupFlow.choosing_country)
    await _sim_render_country_prompt(callback=callback, state=state, lang=lang)
    await callback.answer()


@router.message(SimTopupFlow.waiting_brand_search)
async def sim_topup_search_brand(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    query = str(message.text or "").strip()
    data = await state.get_data()
    country_code = str(data.get("sim_country_code") or "").strip().upper()
    section = str(data.get("sim_section_kind") or "").strip().lower()
    rows = await _sim_search_brands(country_code, section, query, limit=12)
    try:
        await message.delete()
    except Exception:
        pass
    if not rows:
        await _sim_render_brand_prompt(message=message, state=state, lang=lang, country_code=country_code, section=section, note=_sim_text(lang, "No matching operator was found. Try another name.", "لم نجد مشغلًا مطابقًا. جرّب اسمًا آخر."))
        return
    await _sim_edit_anchor(
        message=message,
        state=state,
        text=_sim_text(lang, f"Country: {_sim_country_display_name(country_code)}\n\nChoose the operator.", f"الدولة: {_sim_country_display_name(country_code)}\n\nاختر المشغل."),
        reply_markup=_sim_brand_keyboard(lang, rows),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("simtopup:brand:"))
async def sim_topup_choose_brand(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    brand_key = str(callback.data or "").split(":", 2)[-1].strip()
    data = await state.get_data()
    country_code = str(data.get("sim_country_code") or "").strip().upper()
    section = str(data.get("sim_section_kind") or "").strip().lower()
    brands = await _sim_country_brands(country_code, section)
    brand_name = next((str(row.get("name") or brand_key) for row in brands if str(row.get("brand") or "").strip() == brand_key), brand_key)
    offers = await _sim_fetch_offers(country_code, section, brand=brand_key)
    markup_percent = _resolve_physical_sim_markup_percent(section)
    prepared = _sim_prepare_offers(offers, section=section, markup_percent=markup_percent)
    if not prepared:
        await callback.answer(_sim_text(lang, "No fixed offers were found for this operator.", "لا توجد عروض ثابتة لهذا المشغل."), show_alert=True)
        return
    await state.set_state(SimTopupFlow.choosing_offer)
    await state.update_data(sim_brand_key=brand_key, sim_brand_name=brand_name, sim_offers=prepared, sim_selected_offer=None)
    await _sim_render_offers(callback=callback, state=state, lang=lang, offers=prepared)
    await callback.answer()


@router.callback_query(lambda c: c.data == "simtopup:back:brand")
async def sim_topup_back_to_brand(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    country_code = str(data.get("sim_country_code") or "").strip().upper()
    section = str(data.get("sim_section_kind") or "").strip().lower()
    await _sim_render_brand_prompt(callback=callback, state=state, lang=lang, country_code=country_code, section=section)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("simtopup:offer:"))
async def sim_topup_choose_offer(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    index = int(str(callback.data or "").split(":")[-1].strip() or 0)
    offers = list((await state.get_data()).get("sim_offers") or [])
    if index < 0 or index >= len(offers):
        await callback.answer(_sim_text(lang, "Offer not found.", "العرض غير موجود."), show_alert=True)
        return
    offer = dict(offers[index])
    await state.set_state(SimTopupFlow.confirming_purchase)
    await state.update_data(sim_selected_offer=offer)
    if callback.message:
        await _safe_edit_message(callback.message, _sim_offer_summary_text(offer, lang=lang), reply_markup=_sim_summary_keyboard(lang))
    await callback.answer()


@router.callback_query(lambda c: c.data == "simtopup:back:offers")
async def sim_topup_back_to_offers(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    offers = list((await state.get_data()).get("sim_offers") or [])
    await state.set_state(SimTopupFlow.choosing_offer)
    await _sim_render_offers(callback=callback, state=state, lang=lang, offers=offers)
    await callback.answer()


@router.callback_query(lambda c: c.data == "simtopup:buy")
async def sim_topup_buy(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    data = await state.get_data()
    offer = dict(data.get("sim_selected_offer") or {})
    if not offer:
        return await callback.answer(_sim_text(lang, "No offer selected.", "لا يوجد عرض محدد."), show_alert=True)
    client = ZenditClient()
    if not client.configured():
        return await callback.answer(_sim_text(lang, "Zendit is not configured yet.", "Zendit غير مضبوط بعد."), show_alert=True)
    reseller_id = await _resolve_user_reseller(callback.from_user.id, callback.bot.id)
    if not reseller_id:
        return await callback.answer(t(lang, "store_reseller_not_linked"), show_alert=True)
    phone = str(data.get("sim_phone") or "").strip()
    offer_id = str(offer.get("offerId") or offer.get("id") or "").strip()
    if not phone or not offer_id:
        return await callback.answer(_sim_text(lang, "Missing top-up data.", "بيانات الشحن ناقصة."), show_alert=True)

    cost_price = float(_money_decimal(offer.get("_cost_price_usd") or _sim_offer_price_usd(offer)))
    sale_price = float(_money_decimal(offer.get("_sale_price_usd") or _apply_markup_decimal(cost_price, _resolve_physical_sim_markup_percent(str(data.get("sim_section_kind") or "")))))
    order, err = await _core_charge(
        user_id=int(callback.from_user.id),
        reseller_id=int(reseller_id),
        service_ref_id=f"zendit:{offer_id}",
        sale_price=sale_price,
        cost_price=cost_price,
    )
    if not order or err:
        return await callback.answer(err or t(lang, "purchase_failed_plain"), show_alert=True)

    await callback.answer(t(lang, "processing_order"), show_alert=False)
    transaction_id = f"zendit-{uuid4().hex}"
    status, payload = await client.purchase_topup(
        offer_id=offer_id,
        recipient_phone_number=phone,
        transaction_id=transaction_id,
    )
    await update_order_details(
        order["_id"],
        {
            "provider_code": "zendit",
            "provider_order_id": transaction_id,
            "provider_response": payload,
            "number_mode": "digital_products",
            "delivery_type": "sim_topup",
            "sim_phone": phone,
            "sim_country_code": str(data.get("sim_country_code") or ""),
            "sim_brand_name": str(data.get("sim_brand_name") or ""),
            "sim_section_kind": str(data.get("sim_section_kind") or ""),
        },
    )
    if status not in {200, 201}:
        await _core_refund(
            user_id=int(callback.from_user.id),
            reseller_id=int(reseller_id),
            order=order,
            sale_price=sale_price,
            cost_price=cost_price,
        )
        error_text = _extract_provider_error(payload)
        await update_order_details(order["_id"], {"provider_error": error_text})
        return await callback.answer(
            _sim_text(lang, "Top-up failed and the amount was refunded.", "فشل الشحن وتمت إعادة المبلغ."),
            show_alert=True,
        )

    tx_status, tx_payload = await client.get_topup_transaction(transaction_id)
    await update_order_details(order["_id"], {"provider_status_response": tx_payload, "provider_http_status": tx_status})
    provider_state = _norm(str((tx_payload or {}).get("status") or (tx_payload or {}).get("state") or ""))
    if provider_state in {"failed", "rejected", "cancelled", "canceled"}:
        await _core_refund(
            user_id=int(callback.from_user.id),
            reseller_id=int(reseller_id),
            order=order,
            sale_price=sale_price,
            cost_price=cost_price,
        )
        return await callback.answer(
            _sim_text(lang, "Top-up failed and the amount was refunded.", "فشل الشحن وتمت إعادة المبلغ."),
            show_alert=True,
        )

    await update_order_status(order["_id"], "success" if provider_state in {"complete", "completed", "success", "successful"} else "paid")
    balance = await get_user_wallet_balance(callback.from_user.id, int(reseller_id))
    lines = [
        t(lang, "purchase_complete_plain"),
        f"{_sim_text(lang, 'Phone', 'الرقم')}: {phone}",
        f"{_sim_text(lang, 'Operator', 'المشغل')}: {str(data.get('sim_brand_name') or data.get('sim_brand_key') or '-').strip()}",
        _sim_offer_send_label(offer, lang=lang),
        f"{t(lang, 'price_label')}: {format_usd(float(_money_decimal(sale_price)))}",
        f"{t(lang, 'store_order_label')}: {order.get('_id')}",
        f"{t(lang, 'store_provider_ref_label')}: {transaction_id}",
        f"{t(lang, 'store_balance_label')}: {format_usd(float(balance or 0.0))}",
    ]
    if callback.message:
        await _safe_edit_message(callback.message, "\n".join(lines), reply_markup=_sim_success_keyboard(lang))
    await callback.answer()


@router.message(lambda m: _is_esim_trigger(m.text))
async def open_esim_section(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    await state.clear()
    await state.set_state(EsimRouteFlow.choosing_mode)
    await state.update_data(
        esim_selected_countries=[],
        esim_selected_mode="",
        esim_selection_mode="",
        esim_selected_days=0,
        esim_candidate_plans=[],
        esim_usage_key="",
        esim_filtered_offers=[],
        esim_recommended_offer=None,
    )
    await _hide_reply_keyboard(message, lang)
    sent = await message.answer(_esim_mode_text(lang), reply_markup=_esim_mode_keyboard(lang))
    await _esim_store_route_message_id(state, getattr(sent, "message_id", None))


@router.inline_query(lambda iq: (iq.query or "").strip().lower().startswith(_ESIM_INLINE_PREFIX))
async def inline_esim_country_search(iq: types.InlineQuery):
    user_id = int(getattr(iq.from_user, "id", 0) or 0)
    if user_id <= 0:
        return await iq.answer([], cache_time=5, is_personal=True)
    query = re.sub(rf"^\s*{_ESIM_INLINE_PREFIX}\s*", "", str(iq.query or "").strip(), flags=re.IGNORECASE)
    countries = await esim_search_countries_live(query, limit=20)
    results: list[types.InlineQueryResultArticle] = []
    for country in countries:
        results.append(
            types.InlineQueryResultArticle(
                id=f"esim_country_{country_slug(country)}",
                title=country,
                description=_esim_text("en", "Add this country to your route", "أضف هذه الدولة إلى الرحلة"),
                input_message_content=types.InputTextMessageContent(message_text=_esim_country_pick_token(country)),
            )
        )
    await iq.answer(results, cache_time=5, is_personal=True)


@router.message(EsimRouteFlow.choosing_countries)
async def handle_esim_country_pick(message: types.Message, state: FSMContext):
    country = _parse_esim_country_pick(message.text)
    if not country:
        return
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    selected = list(data.get("esim_selected_countries") or [])
    mode = str(data.get("esim_selection_mode") or "multi")
    if country == "Syria":
        try:
            await message.delete()
        except Exception:
            pass
        await _esim_edit_route_message(message=message, state=state, lang=lang)
        return
    max_count = 1 if mode == "single" else 5
    if country not in selected and len(selected) < max_count:
        selected.append(country)
        await state.update_data(esim_selected_countries=selected)
    try:
        await message.delete()
    except Exception:
        pass
    if mode == "single" and selected:
        plans = await single_country_plans_live(selected[0])
        if not plans:
            await _esim_edit_route_message(
                message=message,
                state=state,
                lang=lang,
                note=_esim_text(lang, "No eSIM plans found for this country yet.", "لا توجد باقات eSIM لهذه الدولة حاليًا."),
            )
            return
        days = esim_available_days(plans)
        await state.set_state(EsimRouteFlow.choosing_days)
        await state.update_data(esim_selected_mode="single", esim_selected_days=0, esim_usage_key="", esim_filtered_offers=[])
        route_message_id = int((await state.get_data()).get("esim_route_message_id") or 0)
        text = _esim_text(
            lang,
            f"Country: {selected[0]}\n\nChoose duration.",
            f"الدولة: {selected[0]}\n\nاختر المدة.",
        )
        if route_message_id > 0:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=route_message_id,
                    text=text,
                    reply_markup=_esim_days_keyboard(lang, days, back_callback="esim:back:route"),
                )
                return
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc).lower():
                    return
            except Exception:
                pass
        sent = await message.answer(text, reply_markup=_esim_days_keyboard(lang, days, back_callback="esim:back:route"))
        await _esim_store_route_message_id(state, getattr(sent, "message_id", None))
        return
    await _esim_edit_route_message(message=message, state=state, lang=lang)


@router.callback_query(lambda c: c.data and c.data.startswith("esim:remove:"))
async def remove_esim_country(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    slug = str(callback.data or "").split(":", 2)[-1].strip()
    data = await state.get_data()
    selected = [name for name in list(data.get("esim_selected_countries") or []) if country_slug(name) != slug]
    await state.update_data(esim_selected_countries=selected)
    await state.set_state(EsimRouteFlow.choosing_countries)
    await _esim_render_route_screen(target=callback, state=state, lang=lang)
    await callback.answer()


@router.callback_query(lambda c: c.data == "esim:noop")
async def esim_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("esim:mode:"))
async def esim_choose_mode(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    mode = str(callback.data or "").split(":")[-1].strip().lower()
    if mode not in {"single", "multi"}:
        await callback.answer()
        return
    await state.set_state(EsimRouteFlow.choosing_countries)
    await state.update_data(esim_selection_mode=mode, esim_selected_countries=[])
    await _esim_render_route_screen(target=callback, state=state, lang=lang)
    await callback.answer()


@router.callback_query(lambda c: c.data == "esim:back:mode")
async def esim_back_to_mode(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await state.set_state(EsimRouteFlow.choosing_mode)
    await state.update_data(
        esim_selection_mode="",
        esim_selected_mode="",
        esim_selected_countries=[],
        esim_selected_days=0,
        esim_usage_key="",
        esim_filtered_offers=[],
        esim_recommended_offer=None,
    )
    if callback.message:
        await _safe_edit_message(callback.message, _esim_mode_text(lang), reply_markup=_esim_mode_keyboard(lang))
    await callback.answer()


@router.callback_query(lambda c: c.data == "esim:single:add_more")
async def esim_single_add_more(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await state.set_state(EsimRouteFlow.choosing_countries)
    await _esim_render_route_screen(target=callback, state=state, lang=lang)
    await callback.answer()


@router.callback_query(lambda c: c.data == "esim:back:route")
async def esim_back_to_route(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await state.set_state(EsimRouteFlow.choosing_countries)
    await state.update_data(esim_selected_days=0, esim_usage_key="", esim_filtered_offers=[], esim_recommended_offer=None)
    await _esim_render_route_screen(target=callback, state=state, lang=lang)
    await callback.answer()


@router.callback_query(lambda c: c.data == "esim:done")
async def esim_finish_country_selection(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    selected = [name for name in list(data.get("esim_selected_countries") or []) if name != "Syria"]
    await state.update_data(esim_selected_countries=selected)
    if not selected:
        await _esim_render_route_screen(
            target=callback,
            state=state,
            lang=lang,
            note=_esim_text(lang, "Choose at least one country first.", "اختر دولة واحدة على الأقل أولًا."),
        )
        await callback.answer()
        return
    if len(selected) == 1:
        await state.set_state(EsimRouteFlow.single_country_prompt)
        text = _esim_text(
            lang,
            f"You selected one country only: {selected[0]}\n\nYou can add more countries to cover the whole route, or continue with this country only.",
            f"اخترت دولة واحدة فقط: {selected[0]}\n\nيمكنك إضافة دول أخرى لتغطية كامل الرحلة، أو الاستمرار بهذه الدولة فقط.",
        )
        if callback.message:
            await _safe_edit_message(callback.message, text, reply_markup=_esim_single_country_keyboard(lang))
        await callback.answer()
        return

    days = await route_available_days_live(selected)
    if not days:
        await _esim_render_route_screen(
            target=callback,
            state=state,
            lang=lang,
            note=_esim_text(lang, "No route plans were found for the selected countries yet.", "لم نجد باقات رحلة لهذه الدول حتى الآن."),
        )
        await callback.answer()
        return
    await state.set_state(EsimRouteFlow.choosing_days)
    await state.update_data(esim_selected_mode="route", esim_selected_days=0, esim_usage_key="", esim_filtered_offers=[])
    if callback.message:
        await _safe_edit_message(
            callback.message,
            _esim_days_prompt_text(lang, selected),
            reply_markup=_esim_days_keyboard(lang, days, back_callback="esim:back:route"),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "esim:single:continue")
async def esim_continue_single_country(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    selected = list(data.get("esim_selected_countries") or [])
    country = selected[0] if selected else ""
    plans = await single_country_plans_live(country)
    if not plans:
        await callback.answer(_esim_text(lang, "No eSIM plans found for this country yet.", "لا توجد باقات eSIM لهذه الدولة حاليًا."), show_alert=True)
        return
    days = esim_available_days(plans)
    await state.set_state(EsimRouteFlow.choosing_days)
    await state.update_data(esim_selected_mode="single", esim_selected_days=0, esim_usage_key="", esim_filtered_offers=[])
    text = _esim_text(
        lang,
        f"Country: {country}\n\nChoose duration.",
        f"الدولة: {country}\n\nاختر المدة.",
    )
    if callback.message:
        await _safe_edit_message(callback.message, text, reply_markup=_esim_days_keyboard(lang, days, back_callback="esim:back:route"))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("esim:days:"))
async def esim_choose_days(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    days = int(str(callback.data or "").split(":")[-1].strip() or 0)
    data = await state.get_data()
    selected = list(data.get("esim_selected_countries") or [])
    await state.set_state(EsimRouteFlow.choosing_usage)
    await state.update_data(esim_selected_days=days, esim_usage_key="", esim_filtered_offers=[])
    header = _esim_usage_prompt_text(lang, selected, days)
    if callback.message:
        await _safe_edit_message(
            callback.message,
            header,
            reply_markup=_esim_usage_keyboard(lang, back_callback="esim:back:days"),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "esim:back:days")
async def esim_back_to_days(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    selected = list(data.get("esim_selected_countries") or [])
    mode = str(data.get("esim_selected_mode") or "route")
    if mode == "single":
        country = selected[0] if selected else ""
        days = esim_available_days(await single_country_plans_live(country))
        text = _esim_text(lang, f"Country: {country}\n\nChoose duration.", f"الدولة: {country}\n\nاختر المدة.")
    else:
        days = await route_available_days_live(selected)
        text = _esim_days_prompt_text(lang, selected)
    await state.set_state(EsimRouteFlow.choosing_days)
    await state.update_data(esim_usage_key="", esim_filtered_offers=[], esim_recommended_offer=None)
    if callback.message:
        await _safe_edit_message(
            callback.message,
            text,
            reply_markup=_esim_days_keyboard(lang, days, back_callback="esim:back:route"),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("esim:usage:"))
async def esim_choose_usage(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    usage_key = str(callback.data or "").split(":")[-1].strip().lower()
    data = await state.get_data()
    selected = list(data.get("esim_selected_countries") or [])
    days = int(data.get("esim_selected_days") or 0)
    mode = str(data.get("esim_selected_mode") or "route")
    if mode == "single":
        country = selected[0] if selected else ""
        offers = await build_single_country_offers_live(country, days=days, usage_key=usage_key)
    else:
        offers = await build_route_offers_live(selected, days=days, usage_key=usage_key)
    markup_percent = _resolve_esim_markup_percent()
    offers = [_apply_markup_to_esim_offer(row, markup_percent=markup_percent) for row in offers]
    if not offers:
        await callback.answer(
            _esim_text(lang, "No offers matched this duration and usage.", "لا توجد عروض تطابق هذه المدة وحجم الاستخدام."),
            show_alert=True,
        )
        return
    await state.set_state(EsimRouteFlow.choosing_package)
    recommended = choose_recommended_offer(offers, absolute_threshold_usd=1.0)
    if not recommended:
        await callback.answer(
            _esim_text(lang, "No recommended offer was found.", "لم نجد عرضًا مناسبًا."),
            show_alert=True,
        )
        return
    await state.update_data(esim_usage_key=usage_key, esim_filtered_offers=offers, esim_recommended_offer=recommended)
    await _esim_render_offer_summary(callback=callback, state=state, lang=lang, offer=recommended)
    await callback.answer()


@router.callback_query(lambda c: c.data == "esim:back:usage")
async def esim_back_to_usage(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()
    selected = list(data.get("esim_selected_countries") or [])
    days = int(data.get("esim_selected_days") or 0)
    await state.set_state(EsimRouteFlow.choosing_usage)
    if callback.message:
        await _safe_edit_message(
            callback.message,
            _esim_usage_prompt_text(lang, selected, days),
            reply_markup=_esim_usage_keyboard(lang, back_callback="esim:back:days"),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("esim:pkg:"))
async def esim_choose_package(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    index = int(str(callback.data or "").split(":")[-1].strip() or 0)
    data = await state.get_data()
    offers = list(data.get("esim_filtered_offers") or [])
    if index < 0 or index >= len(offers):
        await callback.answer(_esim_text(lang, "Package not found.", "الباقة غير موجودة."), show_alert=True)
        return
    offer = offers[index]
    selected = list(data.get("esim_selected_countries") or [])
    summary_lines = [
        _esim_text(lang, "eSIM Summary", "ملخص باقة eSIM"),
        "",
        _esim_countries_text(lang, selected),
        _esim_text(lang, f"Duration: {int(data.get('esim_selected_days') or 0)} days", f"المدة: {int(data.get('esim_selected_days') or 0)} يوم"),
        _esim_text(lang, f"Usage: {esim_usage_label(str(data.get('esim_usage_key') or 'low'), lang=lang)}", f"حجم الاستخدام: {esim_usage_label(str(data.get('esim_usage_key') or 'low'), lang=lang)}"),
    ]
    summary_lines.extend(["", esim_offer_summary(offer, lang=lang), "", _esim_text(lang, "Direct purchase will be connected in the next step.", "الشراء المباشر سيتم ربطه في الخطوة التالية.")])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="esim:back:usage")],
            [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")],
        ]
    )
    if callback.message:
        await _safe_edit_message(callback.message, "\n".join(summary_lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data == "esim:buy")
async def esim_buy_recommended_offer(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    data = await state.get_data()
    offer = dict(data.get("esim_recommended_offer") or {})
    if not offer:
        return await callback.answer(_esim_text(lang, "No offer selected.", "لا يوجد عرض محدد."), show_alert=True)
    if not settings.esim_access_code or not settings.esim_access_secret_key:
        return await callback.answer(_esim_text(lang, "eSIM provider is not configured yet.", "مزود eSIM غير مضبوط بعد."), show_alert=True)
    reseller_id = await _resolve_user_reseller(callback.from_user.id, callback.bot.id)
    if not reseller_id:
        return await callback.answer(t(lang, "store_reseller_not_linked"), show_alert=True)

    cost_price = float(_money_decimal(offer.get("_cost_price_usd") or offer.get("price_usd") or 0.0))
    sale_price = float(_money_decimal(offer.get("price_usd") or _apply_markup_decimal(cost_price, _resolve_esim_markup_percent())))
    order, err = await _core_charge(
        user_id=int(callback.from_user.id),
        reseller_id=int(reseller_id),
        service_ref_id=_esim_service_ref(offer),
        sale_price=sale_price,
        cost_price=cost_price,
    )
    if not order or err:
        return await callback.answer(err or t(lang, "purchase_failed_plain"), show_alert=True)

    client = EsimAccessClient()
    package_info_list = _esim_package_info_list(offer, days=int(data.get("esim_selected_days") or 0))
    if not package_info_list:
        await _core_refund(
            user_id=int(callback.from_user.id),
            reseller_id=int(reseller_id),
            order=order,
            sale_price=sale_price,
            cost_price=cost_price,
        )
        return await callback.answer(_esim_text(lang, "Invalid eSIM package data.", "بيانات باقة eSIM غير صالحة."), show_alert=True)

    provider_resp = await client.order_profiles(
        transaction_id=f"esim-{uuid4().hex}",
        amount=_esim_price_to_units(cost_price),
        package_info_list=package_info_list,
    )
    if not bool(provider_resp.get("success")):
        await _core_refund(
            user_id=int(callback.from_user.id),
            reseller_id=int(reseller_id),
            order=order,
            sale_price=sale_price,
            cost_price=cost_price,
        )
        await update_order_details(order["_id"], {"provider_response": provider_resp, "provider_error": str(provider_resp.get('errorMessage') or 'esim_order_failed')})
        return await callback.answer(
            _esim_text(lang, "eSIM purchase failed. The amount was refunded.", "فشل شراء eSIM وتمت إعادة المبلغ."),
            show_alert=True,
        )

    order_no = str(((provider_resp.get("obj") or {}) if isinstance(provider_resp.get("obj"), dict) else {}).get("orderNo") or "").strip()
    await update_order_details(
        order["_id"],
        {
            "provider_code": "esim_access",
            "provider_order_id": order_no,
            "provider_response": provider_resp,
            "number_mode": "digital_products",
            "delivery_type": "esim",
        },
    )

    query_resp = await _esim_query_profiles_wait(client, order_no=order_no) if order_no else None
    profiles = _esim_extract_profiles(query_resp or {})
    if not profiles:
        await update_order_details(order["_id"], {"provider_status_response": query_resp, "provider_manual_review_required": True})
        await update_order_status(order["_id"], "paid")
        if callback.message:
            await _safe_edit_message(
                callback.message,
                _esim_text(
                    lang,
                    "Your eSIM order was created and is being prepared. We will deliver it shortly.",
                    "تم إنشاء طلب eSIM وهو قيد التجهيز. سيتم تسليمه بعد قليل.",
                ),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")]]
                ),
            )
        await callback.answer()
        return

    await update_order_details(order["_id"], {"provider_status_response": query_resp, "delivery_profiles": profiles})
    await update_order_status(order["_id"], "success")
    balance = await get_user_wallet_balance(callback.from_user.id, int(reseller_id))
    delivery_text = _esim_delivery_text(
        lang=lang,
        profiles=profiles,
        sale_price=sale_price,
        balance=float(balance or 0.0),
        order_id=str(order.get("_id")),
        order_no=order_no,
    )
    if callback.message:
        await _safe_edit_message(
            callback.message,
            delivery_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")]]
            ),
        )
    await callback.answer()


@router.message(lambda m: _is_store_trigger(m.text))
async def open_store_hub(message: types.Message):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    await _hide_reply_keyboard(message, lang)
    rows = [
        [
            InlineKeyboardButton(text=t(lang, "store_btn_giftcards"), callback_data="gst:hub:gift", style="primary"),
            InlineKeyboardButton(text=t(lang, "store_btn_games"), callback_data="gst:hub:games", style="success"),
        ],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:menu", style="danger")],
    ]
    await message.answer(
        f"{t(lang, 'store_hub_title')}\n\n{t(lang, 'store_hub_hint')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.message(lambda m: bool(getattr(m, "web_app_data", None)))
async def digital_products_web_app_selection(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    try:
        payload_raw = str(getattr(message.web_app_data, "data", "") or "")
        payload = json.loads(payload_raw)
    except Exception:
        return await message.answer(t(lang, "invalid_order_info"))
    token = str((payload or {}).get("digital_selection_token") or "").strip()
    if not token:
        return await message.answer(t(lang, "invalid_order_info"))
    selection = await consume_selection(token, int(message.from_user.id))
    if not selection:
        return await message.answer(t(lang, "store_session_expired"))

    kind = str(selection.get("kind") or "").strip().lower()
    snapshot = await get_catalog_snapshot(force=False)
    markup_percent = await _resolve_digital_products_markup_percent()
    if kind == "gift":
        cat_id = str(selection.get("category_id") or "").strip()
        product_id = str(selection.get("product_id") or "").strip()
        quantity = max(1, _to_int(selection.get("quantity") or 1))
        extra_params = selection.get("extra_params") if isinstance(selection.get("extra_params"), dict) else {}
        quoted_price_usd = float(_round_sale_price_decimal(selection.get("quoted_price_usd") or 0.0))
        selected: dict[str, Any] | None = None
        for item in ((snapshot.get("products_by_category") or {}).get(cat_id) or []):
            if str(item.get("id") or "").strip() == product_id:
                selected = item
                break
        if not selected:
            return await message.answer(t(lang, "store_product_not_found"))
        offers = _provider_offers_for_row(
            selected,
            fallback_provider="g2bulk",
            fallback_ref_id=product_id,
            fallback_price=float(_money_decimal(selected.get("price"))),
        )
        category_name = _gift_category_name_from_snapshot(snapshot, cat_id)
        offers = _prepare_gift_offers_for_fulfillment(
            offers,
            category_name=category_name,
            product_name=str(selected.get("name") or ""),
        )
        available_offers = [row for row in offers if bool(row.get("available"))]
        primary_offer = dict(available_offers[0]) if available_offers else dict(offers[0] if offers else {})
        unit_cost_price, _cost_price, sale_price = _gift_compute_prices(
            offer=primary_offer,
            fallback_price=selected.get("price"),
            quantity=quantity,
            markup_percent=markup_percent,
        )
        price = sale_price
        stock = max(int(selected.get("stock") or 0), 1 if any(bool(row.get("available")) for row in offers) else 0)
        details_lines = _gift_prefill_summary_lines(
            lang=lang,
            quantity=quantity,
            extra_params=dict(extra_params),
        )
        details_block = ("\n".join(details_lines) + "\n\n") if details_lines else ""
        text = (
            f"{str(selected.get('name') or '-')}\n\n"
            f"{_store_price_line(lang, price, await _resolve_usd_to_syp_rate((await message.bot.get_me()).id))}\n"
            f"{t(lang, 'store_stock_label')}: {stock}\n\n"
            f"{details_block}"
            f"{t(lang, 'confirm_purchase_question')}"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data=f"gst:giftconfirm:{cat_id}:{product_id}")],
                [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")],
            ]
        )
        await state.update_data(
            gift_prefill={
                "cat_id": cat_id,
                "product_id": product_id,
                "quantity": int(quantity),
                "extra_params": dict(extra_params),
                "quoted_price_usd": float(quoted_price_usd),
                "unit_cost_price": float(unit_cost_price),
                "markup_percent": float(_to_float(markup_percent)),
            }
        )
        return await message.answer(text, reply_markup=kb)

    if kind == "game":
        game_id = str(selection.get("game_id") or "").strip()
        item_id = str(selection.get("item_id") or "").strip()
        group_key = str(selection.get("group_key") or "topup").strip() or "topup"
        player_id = str(selection.get("player_id") or "").strip()
        server_id = str(selection.get("server_id") or "").strip()
        game_name = _find_game_name(game_id, snapshot)
        items = await get_game_topups(game_id, force=True)
        selected = None
        for item in items:
            if str(item.get("id") or "").strip() == item_id:
                selected = item
                break
        if not selected:
            return await message.answer(t(lang, "store_topup_package_not_found"))
        price = float(
            _resolve_game_sale_price_decimal(
                game_id=game_id,
                game_name=game_name,
                provider_price=selected.get("price"),
                markup_percent=markup_percent,
            )
        )
        name = _display_game_item_name(selected, group_key=group_key)
        usd_to_syp_rate = await _resolve_usd_to_syp_rate((await message.bot.get_me()).id)
        text = _digital_game_prefill_confirm_text(
            lang,
            game_name=game_name,
            package_name=name,
            player_id=player_id,
            server_id=server_id,
            requires_server=bool(selected.get("requires_server")),
            price=price,
            usd_to_syp_rate=usd_to_syp_rate,
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data=f"gst:buygame:{game_id}:{group_key}:{item_id}")],
                [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")],
            ]
        )
        await state.update_data(
            game_prefill={
                "game_id": game_id,
                "item_id": item_id,
                "player_id": player_id,
                "server_id": server_id,
            }
        )
        return await message.answer(text, reply_markup=kb)

    if kind == "simtopup":
        section = str(selection.get("section") or "").strip().lower()
        if section not in {"balance", "data"}:
            return await message.answer(t(lang, "invalid_order_info"))
        phone = str(selection.get("phone") or "").strip()
        country_code = str(selection.get("country_code") or "").strip().upper()
        brand_key = str(selection.get("brand_key") or "").strip()
        brand_name = str(selection.get("brand_name") or brand_key or "").strip()
        offer = dict(selection.get("offer") or {})
        offer_id = str(offer.get("offerId") or offer.get("id") or "").strip()
        if phone and len(country_code) == 2 and offer_id:
            offer["_section_kind"] = section
            offer["country"] = str(offer.get("country") or country_code).strip().upper()
            offer["brand"] = str(offer.get("brand") or brand_key or "").strip()
            offer["brandName"] = str(offer.get("brandName") or brand_name or offer.get("brand") or "").strip()
            if float(_money_decimal(offer.get("_cost_price_usd") or 0)) <= 0:
                offer["_cost_price_usd"] = float(_money_decimal(_sim_offer_price_usd(offer)))
            if float(_money_decimal(offer.get("_sale_price_usd") or 0)) <= 0:
                offer["_sale_price_usd"] = float(_money_decimal(offer.get("_cost_price_usd") or 0))
            await state.clear()
            await state.set_state(SimTopupFlow.confirming_purchase)
            await state.update_data(
                sim_section_kind=section,
                sim_phone=phone,
                sim_country_code=country_code,
                sim_brand_key=offer.get("brand") or brand_key,
                sim_brand_name=offer.get("brandName") or brand_name or offer.get("brand") or "",
                sim_offers=[offer],
                sim_selected_offer=offer,
            )
            await _hide_reply_keyboard(message, lang)
            return await message.answer(_sim_offer_summary_text(offer, lang=lang), reply_markup=_sim_summary_keyboard(lang))
        await state.clear()
        await state.set_state(SimTopupFlow.waiting_phone)
        await state.update_data(
            sim_section_kind=section,
            sim_phone="",
            sim_country_code="",
            sim_brand_key="",
            sim_brand_name="",
            sim_offers=[],
            sim_selected_offer=None,
        )
        await _hide_reply_keyboard(message, lang)
        await _sim_render_phone_prompt(message=message, state=state, lang=lang, section=section)
        return

    if kind == "esim":
        selected_countries = [str(row).strip() for row in list(selection.get("selected_countries") or []) if str(row).strip()]
        selected_days = _to_int(selection.get("selected_days") or 0)
        usage_key = str(selection.get("usage_key") or "").strip().lower()
        offer = dict(selection.get("offer") or {})
        if selected_countries and selected_days > 0 and usage_key in {"low", "mid", "high"} and offer:
            if float(_money_decimal(offer.get("_cost_price_usd") or 0)) <= 0:
                offer["_cost_price_usd"] = float(_money_decimal(offer.get("price_usd") or 0.0))
            if float(_money_decimal(offer.get("price_usd") or 0)) <= 0:
                offer["price_usd"] = float(_money_decimal(offer.get("_cost_price_usd") or 0.0))
            await state.clear()
            await state.set_state(EsimRouteFlow.confirming_purchase)
            await state.update_data(
                esim_selected_countries=selected_countries,
                esim_selected_mode=str(selection.get("selected_mode") or "single"),
                esim_selection_mode=str(selection.get("selected_mode") or "single"),
                esim_selected_days=selected_days,
                esim_candidate_plans=[],
                esim_usage_key=usage_key,
                esim_filtered_offers=[offer],
                esim_recommended_offer=offer,
            )
            summary_lines = [
                _esim_text(lang, "Recommended eSIM", "أفضل باقة مقترحة"),
                "",
                _esim_countries_text(lang, selected_countries),
                _esim_text(lang, f"Duration: {selected_days} days", f"المدة: {selected_days} يوم"),
                _esim_text(lang, f"Usage: {esim_usage_label(usage_key, lang=lang)}", f"حجم الاستخدام: {esim_usage_label(usage_key, lang=lang)}"),
                "",
                esim_offer_summary(offer, lang=lang),
            ]
            await _hide_reply_keyboard(message, lang)
            return await message.answer("\n".join(summary_lines), reply_markup=_esim_summary_keyboard(lang))
        await state.clear()
        await state.set_state(EsimRouteFlow.choosing_mode)
        await state.update_data(
            esim_selected_countries=[],
            esim_selected_mode="",
            esim_selection_mode="",
            esim_selected_days=0,
            esim_candidate_plans=[],
            esim_usage_key="",
            esim_filtered_offers=[],
            esim_recommended_offer=None,
        )
        await _hide_reply_keyboard(message, lang)
        sent = await message.answer(_esim_mode_text(lang), reply_markup=_esim_mode_keyboard(lang))
        await _esim_store_route_message_id(state, getattr(sent, "message_id", None))
        return

    if kind == "numbers_services":
        service_key = str(selection.get("service_key") or "").strip()
        service_label = str(selection.get("service_label") or service_key or "").strip()
        await state.clear()
        await state.update_data(
            lang=lang,
            num_type="temp",
            service=service_key,
            numbers_ignore_provider_balance=True,
            numbers_preselected_service_label=service_label,
            numbers_preselected_service=bool(service_key),
        )
        await _hide_reply_keyboard(message, lang)
        if service_key:
            await render_preselected_temp_service_countries(
                message,
                state,
                lang=lang,
                service_key=service_key,
                service_label=service_label,
            )
            return
        await message.answer(
            _compose_numbers_screen(t(lang, "choose_number_type"), trailing_lines=[t(lang, "temp_numbers_type_note")]),
            reply_markup=number_type_kb(lang),
        )
        await state.set_state(NumberFlow.num_type)
        return

    return await message.answer(t(lang, "invalid_order_info"))


@router.message(lambda m: _is_games_trigger(m.text))
async def open_games_section(message: types.Message, state):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    await _hide_reply_keyboard(message, lang)

    # Primary source: G2Bulk games API.
    snapshot = await get_catalog_snapshot(force=False)
    if bool(snapshot.get("enabled")):
        games = list(snapshot.get("games") or [])
        if not games:
            return await message.answer(t(lang, "store_no_game_categories"), reply_markup=ReplyKeyboardRemove())
        kb_rows = _build_game_rows(games, limit=5)
        kb_rows.append([InlineKeyboardButton(text=t(lang, "store_more_games"), switch_inline_query_current_chat="game ")])
        kb_rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:menu")])
        await message.answer(
            await _digital_products_menu_text(lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        )
        return

    # ID-INFO fallback is archived.
    return await message.answer(t(lang, "store_no_game_categories"), reply_markup=ReplyKeyboardRemove())


@router.callback_query(lambda c: c.data == "gst:hub:gift")
async def open_store_hub_gift(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    snapshot = await get_catalog_snapshot(force=False)
    categories = _gift_categories_for_ui(snapshot)
    if categories:
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
    if not await guard_core_service_callback(callback, lang):
        return
    snapshot = await get_catalog_snapshot(force=False)
    if bool(snapshot.get("enabled")):
        games = list(snapshot.get("games") or [])
        if not games:
            await callback.answer(t(lang, "store_no_game_categories"), show_alert=True)
            return
        kb_rows = _build_game_rows(games, limit=5)
        kb_rows.append([InlineKeyboardButton(text=t(lang, "store_more_games"), switch_inline_query_current_chat="game ")])
        kb_rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:menu", style="danger")])
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
        [InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:menu", style="danger")],
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
    user = await get_user(user_id)
    lang = (user or {}).get("language", "en")

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
            await _increment_usage(str(top[0].get("name") or ""))

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
                    description=t(lang, "store_inline_game_description"),
                    input_message_content=types.InputTextMessageContent(
                        message_text=(
                            f"{t(lang, 'store_game_pick_prefix')} {name}\n"
                            f"{t(lang, 'store_inline_game_selected_hint')}"
                        )
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text=t(lang, "store_open_game_packages"), callback_data=f"gst:game:{gid}")]
                        ]
                    ),
                )
            )
        return await iq.answer(results, cache_time=10, is_personal=True)

    # ID-INFO legacy fallback is archived.
    return await iq.answer([], cache_time=10, is_personal=True)


@router.callback_query(lambda c: c.data and c.data.startswith("gst:giftcat:"))
async def open_g2bulk_gift_category(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    await state.clear()
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
        return await callback.answer(t(lang, "store_category_not_found"), show_alert=True)
    snapshot = await get_catalog_snapshot(force=False)
    if is_lona_category_id(cat_id):
        products = lona_products_for_category(cat_id)
    else:
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
    markup_percent = await _resolve_digital_products_markup_percent()
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
            rows.append([InlineKeyboardButton(text=t(lang, "next_plain"), callback_data=f"gst:giftcat:{cat_id}:1")])
        else:
            rows.append([InlineKeyboardButton(text=t(lang, "prev_plain"), callback_data=f"gst:giftcat:{cat_id}:0")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:giftroot")])
    await callback.message.edit_text(t(lang, "store_gift_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:giftroot")
async def open_g2bulk_gift_root(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    await state.clear()
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    snapshot = await get_catalog_snapshot(force=False)
    categories = _gift_categories_for_ui(snapshot)
    if not categories:
        return await callback.answer(t(lang, "store_no_gift_categories"), show_alert=True)
    rows = _build_gift_categories_rows(categories[:60])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:menu")])
    await callback.message.edit_text(t(lang, "store_gift_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("gst:giftitem:"))
async def open_g2bulk_gift_item(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    parts = str(callback.data or "").split(":")
    if len(parts) < 4:
        return await callback.answer(t(lang, "store_invalid_product"), show_alert=True)
    cat_id = str(parts[2]).strip()
    product_id = str(parts[3]).strip()
    snapshot = await get_catalog_snapshot(force=False)
    if is_lona_category_id(cat_id):
        found = find_lona_product(cat_id, product_id)
    else:
        found: dict[str, Any] | None = None
        for item in ((snapshot.get("products_by_category") or {}).get(cat_id) or []):
            if str(item.get("id") or "").strip() == product_id:
                found = item
                break
    if not found:
        return await callback.answer(t(lang, "store_product_not_found"), show_alert=True)
    await state.clear()
    usd_to_syp_rate = await _resolve_usd_to_syp_rate(callback.bot.id)
    name = str(found.get("name") or "-")
    if bool(found.get("lona_manual")):
        manual_card = dict(found.get("manual_card") or {})
        kind = str(manual_card.get("kind") or "")
        if kind != "fixed":
            await state.clear()
            await state.set_state(GiftStoreFlow.waiting_lona_amount)
            await state.update_data(
                lona_card_pending={
                    "cat_id": cat_id,
                    "product_id": product_id,
                    "back_to": f"gst:giftitem:{cat_id}:{product_id}",
                }
            )
            await callback.message.edit_text(
                _lona_amount_prompt_text(lang, found),
                reply_markup=_gift_param_cancel_keyboard(lang, back_to=f"gst:giftcat:{cat_id}:0"),
            )
            await callback.answer()
            return
        quote = quote_lona_product(cat_id, product_id)
        if not quote:
            return await callback.answer(t(lang, "store_invalid_product"), show_alert=True)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data=f"gst:giftconfirm:{cat_id}:{product_id}")],
                [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"gst:giftcat:{cat_id}:0")],
            ]
        )
        await callback.message.edit_text(_lona_quote_summary_text(lang, quote), reply_markup=kb)
        await callback.answer()
        return
    markup_percent = await _resolve_digital_products_markup_percent()
    price = float(_apply_markup_decimal(found.get("price"), markup_percent))
    offers = _provider_offers_for_row(
        found,
        fallback_provider="g2bulk",
        fallback_ref_id=product_id,
        fallback_price=float(_money_decimal(found.get("price"))),
    )
    stock = max(int(found.get("stock") or 0), 1 if any(bool(row.get("available")) for row in offers) else 0)
    text = (
        f"{name}\n\n"
        f"{_store_price_line(lang, price, usd_to_syp_rate)}\n"
        f"{t(lang, 'store_stock_label')}: {stock}\n\n"
        f"{t(lang, 'confirm_purchase_question')}"
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
    if not await guard_core_service_callback(callback, lang):
        return
    snapshot = await get_catalog_snapshot(force=False)
    game_id = str(callback.data.split(":", 2)[2]).strip()
    game_name = _find_game_name(game_id, snapshot)
    items = await get_game_topups(game_id, force=True)
    if not items:
        return await callback.answer(t(lang, "store_no_game_categories"), show_alert=True)
    grouped = _group_game_items(game_id, items, lang)
    if len(grouped) > 1:
        if not await _render_game_group_list(callback, game_id=game_id, game_name=game_name, items=items, lang=lang):
            await callback.answer()
            return
        await callback.answer()
        return
    group_key = grouped[0][0] if grouped else "topup"
    if not await _render_game_group_items(
        callback,
        game_id=game_id,
        game_name=game_name,
        group_key=group_key,
        items=items,
        lang=lang,
        back_callback="gst:gameroot",
    ):
        await callback.answer()
        return
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("gst:gamegroup:"))
async def open_g2bulk_game_group(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    parts = str(callback.data or "").split(":")
    if len(parts) < 4:
        return await callback.answer(t(lang, "store_invalid_package"), show_alert=True)
    game_id = str(parts[2]).strip()
    group_key = str(parts[3]).strip()
    snapshot = await get_catalog_snapshot(force=False)
    game_name = _find_game_name(game_id, snapshot)
    items = await get_game_topups(game_id, force=True)
    if not items:
        return await callback.answer(t(lang, "store_no_game_categories"), show_alert=True)
    grouped = {key: grouped_items for key, _label, grouped_items in _group_game_items(game_id, items, lang)}
    selected_items = grouped.get(group_key) or []
    if not selected_items:
        return await callback.answer(t(lang, "store_no_game_categories"), show_alert=True)
    if not await _render_game_group_items(
        callback,
        game_id=game_id,
        game_name=game_name,
        group_key=group_key,
        items=selected_items,
        lang=lang,
        back_callback=f"gst:game:{game_id}",
    ):
        await callback.answer()
        return
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:gameroot")
async def open_g2bulk_games_root(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    snapshot = await get_catalog_snapshot(force=False)
    games = list(snapshot.get("games") or [])
    if not games:
        return await callback.answer(t(lang, "store_no_game_categories"), show_alert=True)
    kb_rows = _build_game_rows(games, limit=5)
    kb_rows.append([InlineKeyboardButton(text=t(lang, "store_more_games"), switch_inline_query_current_chat="game ")])
    kb_rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:menu")])
    if not await _edit_callback_target(
        callback,
        await _digital_products_menu_text(lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    ):
        await callback.answer()
        return
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:menu")
async def digital_products_back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if not callback.message:
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await callback.message.answer(
        t(lang, "main_menu"),
        reply_markup=await menu_for_current_bot(lang, (await callback.bot.get_me()).id),
    )
    await callback.answer()




@router.callback_query(lambda c: c.data and c.data.startswith("gst:gameitem:"))
async def open_g2bulk_game_item(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    parts = str(callback.data or "").split(":")
    if len(parts) < 4:
        return await callback.answer(t(lang, "store_invalid_package"), show_alert=True)
    game_id = str(parts[2]).strip()
    snapshot = await get_catalog_snapshot(force=False)
    game_name = _find_game_name(game_id, snapshot)
    group_key = "topup"
    item_id = ""
    if len(parts) >= 5:
        group_key = str(parts[3]).strip() or "topup"
        item_id = str(parts[4]).strip()
    else:
        item_id = str(parts[3]).strip()
    items = await get_game_topups(game_id, force=True)
    grouped_count = len(_group_game_items(game_id, items, lang))
    found: dict[str, Any] | None = None
    for item in items:
        if str(item.get("id") or "").strip() == item_id:
            found = item
            break
    if not found:
        return await callback.answer(t(lang, "store_topup_package_not_found"), show_alert=True)
    usd_to_syp_rate = await _resolve_usd_to_syp_rate(callback.bot.id)
    name = _display_game_item_name(found, group_key=group_key)
    markup_percent = await _resolve_digital_products_markup_percent()
    price = float(
        _resolve_game_sale_price_decimal(
            game_id=game_id,
            game_name=game_name,
            provider_price=found.get("price"),
            markup_percent=markup_percent,
        )
    )
    text = _digital_game_prefill_confirm_text(
        lang,
        game_name=game_name,
        package_name=name,
        player_id="",
        server_id="",
        requires_server=bool(found.get("requires_server")),
        price=price,
        usd_to_syp_rate=usd_to_syp_rate,
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data=f"gst:buygame:{game_id}:{group_key}:{item_id}")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data=(f"gst:gamegroup:{game_id}:{group_key}" if grouped_count > 1 else f"gst:game:{game_id}"))],
        ]
    )
    if not await _edit_callback_target(callback, text, reply_markup=kb):
        await callback.answer()
        return
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("gst:giftconfirm:"))
async def confirm_g2bulk_gift_purchase(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    parts = str(callback.data or "").split(":")
    if len(parts) < 4:
        return await callback.answer(t(lang, "store_invalid_product"), show_alert=True)
    cat_id = str(parts[2]).strip()
    product_id = str(parts[3]).strip()

    snapshot = await get_catalog_snapshot(force=False)
    if is_lona_category_id(cat_id):
        selected = find_lona_product(cat_id, product_id)
        if not selected:
            return await callback.answer(t(lang, "store_product_not_found"), show_alert=True)
        quote = quote_lona_product(cat_id, product_id)
        if not quote:
            return await callback.answer(
                "افتح هذا الخيار وأرسل قيمة البطاقة أولاً."
                if str(lang or "").lower().startswith("ar")
                else "Open this item and enter the card value first.",
                show_alert=True,
            )
        reseller_id = await _resolve_user_reseller(callback.from_user.id, callback.bot.id)
        if not reseller_id:
            return await callback.answer(t(lang, "store_reseller_not_linked"), show_alert=True)
        await callback.answer(t(lang, "processing_order"), show_alert=False)
        result = await _execute_lona_card_purchase(
            bot=callback.bot,
            user_id=int(callback.from_user.id),
            lang=lang,
            reseller_id=int(reseller_id),
            quote=quote,
        )
        kind = str(result.get("kind") or "")
        if kind == "charge_error":
            return await callback.answer(str(result.get("alert") or t(lang, "purchase_failed_plain")), show_alert=True)
        if callback.message:
            await callback.message.edit_text(
                str(result.get("text") or t(lang, "purchase_failed_plain")),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")]
                    ]
                ),
            )
        return

    selected: dict[str, Any] | None = None
    for item in ((snapshot.get("products_by_category") or {}).get(cat_id) or []):
        if str(item.get("id") or "").strip() == product_id:
            selected = item
            break
    if not selected:
        return await callback.answer(t(lang, "store_product_not_found"), show_alert=True)

    reseller_id = await _resolve_user_reseller(callback.from_user.id, callback.bot.id)
    if not reseller_id:
        return await callback.answer(t(lang, "store_reseller_not_linked"), show_alert=True)

    offers = _provider_offers_for_row(
        selected,
        fallback_provider="g2bulk",
        fallback_ref_id=product_id,
        fallback_price=float(_money_decimal(selected.get("price"))),
    )
    category_name = _gift_category_name_from_snapshot(snapshot, cat_id)
    offers = _prepare_gift_offers_for_fulfillment(
        offers,
        category_name=category_name,
        product_name=str(selected.get("name") or ""),
    )
    available_offers = [row for row in offers if bool(row.get("available"))]
    if not available_offers:
        return await callback.answer(t(lang, "store_out_of_stock"), show_alert=True)
    primary_offer = dict(available_offers[0])

    markup_percent = await _resolve_digital_products_markup_percent()
    state_data = await state.get_data()
    prefill = dict(state_data.get("gift_prefill") or {})
    prefill_matches = (
        str(prefill.get("cat_id") or "").strip() == cat_id
        and str(prefill.get("product_id") or "").strip() == product_id
    )
    prefill_quantity = max(1, _to_int(prefill.get("quantity") or 1)) if prefill_matches else 1
    prefill_extra = dict(prefill.get("extra_params") or {}) if prefill_matches else {}
    unit_cost_price, cost_price, sale_price = _gift_compute_prices(
        offer=primary_offer,
        fallback_price=selected.get("price"),
        quantity=prefill_quantity if prefill_matches else 1,
        markup_percent=markup_percent,
    )

    if _gift_offer_needs_input(primary_offer):
        qty_min, qty_max = _gift_offer_qty_bounds(primary_offer)
        params = _gift_offer_params(primary_offer)
        quantity = min(max(prefill_quantity, qty_min), qty_max)
        _unit_cost_price_q, cost_price_q, sale_price_q = _gift_compute_prices(
            offer=primary_offer,
            fallback_price=selected.get("price"),
            quantity=quantity,
            markup_percent=markup_percent,
        )
        normalized_extra = {
            str(key).strip(): value
            for key, value in prefill_extra.items()
            if str(key).strip() and str(value).strip()
        }
        missing = [key for key in params if not str(normalized_extra.get(key, "")).strip()]
        if prefill_matches and not missing:
            await state.update_data(gift_prefill={})
            await callback.answer(t(lang, "processing_order"), show_alert=False)
            result = await _execute_gift_purchase(
                bot=callback.bot,
                user_id=int(callback.from_user.id),
                lang=lang,
                reseller_id=int(reseller_id),
                selected=selected,
                product_id=product_id,
                available_offers=available_offers,
                sale_price=float(sale_price_q),
                cost_price=float(cost_price_q),
                quantity=int(quantity),
                extra_params=normalized_extra,
            )
            kind = str(result.get("kind") or "")
            if kind == "charge_error":
                return await callback.answer(str(result.get("alert") or t(lang, "purchase_failed_plain")), show_alert=True)
            if callback.message:
                await callback.message.edit_text(
                    str(result.get("text") or t(lang, "purchase_failed_plain")),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")]
                        ]
                    ) if kind == "success" else None,
                )
            return
        pending = {
            "cat_id": cat_id,
            "product_id": product_id,
            "reseller_id": int(reseller_id),
            "selected_name": str(selected.get("name") or ""),
            "offers": available_offers,
            "cost_price": float(cost_price_q),
            "sale_price": float(sale_price_q),
            "unit_cost_price": float(unit_cost_price),
            "markup_percent": float(_to_float(markup_percent)),
            "qty_min": int(qty_min),
            "qty_max": int(qty_max),
            "quantity": int(quantity),
            "params": params,
            "param_index": int(params.index(missing[0])) if missing else 0,
            "extra_params": normalized_extra,
        }
        await state.update_data(gift_pending=pending)
        if qty_max > 1 and not prefill_matches:
            await state.set_state(GiftStoreFlow.waiting_quantity)
            prompt = _gift_qty_prompt_text(lang, qty_min, qty_max)
            await callback.message.edit_text(prompt, reply_markup=_gift_param_cancel_keyboard(lang, back_to=f"gst:giftitem:{cat_id}:{product_id}"))
            await callback.answer()
            return
        if missing:
            await state.set_state(GiftStoreFlow.waiting_param)
            key = missing[0]
            prompt = _gift_param_prompt_text(lang, key)
            await callback.message.edit_text(prompt, reply_markup=_gift_param_cancel_keyboard(lang, back_to=f"gst:giftitem:{cat_id}:{product_id}"))
            await callback.answer()
            return

    await callback.answer(t(lang, "processing_order"), show_alert=False)
    result = await _execute_gift_purchase(
        bot=callback.bot,
        user_id=int(callback.from_user.id),
        lang=lang,
        reseller_id=int(reseller_id),
        selected=selected,
        product_id=product_id,
        available_offers=available_offers,
        sale_price=float(sale_price),
        cost_price=float(cost_price),
    )
    kind = str(result.get("kind") or "")
    if kind == "charge_error":
        return await callback.answer(str(result.get("alert") or t(lang, "purchase_failed_plain")), show_alert=True)
    if callback.message:
        await callback.message.edit_text(
            str(result.get("text") or t(lang, "purchase_failed_plain")),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")]
                ]
            ) if kind == "success" else None,
        )


@router.callback_query(lambda c: c.data == "gst:giftparam:cancel")
async def cancel_gift_param_flow(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            t(lang, "purchase_cancelled_plain"),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")]
                ]
            ),
        )
    await callback.answer()


@router.message(GiftStoreFlow.waiting_lona_amount)
async def collect_lona_card_amount(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    raw = str(message.text or "").strip()
    if raw.lower() in {"/cancel", "cancel"}:
        await state.clear()
        return await message.answer(t(lang, "purchase_cancelled_plain"))
    data = await state.get_data()
    pending = dict(data.get("lona_card_pending") or {})
    cat_id = str(pending.get("cat_id") or "").strip()
    product_id = str(pending.get("product_id") or "").strip()
    product = find_lona_product(cat_id, product_id)
    if not product:
        await state.clear()
        return await message.answer(t(lang, "store_product_not_found"))
    amount = parse_face_value(raw)
    if amount is None:
        return await message.answer(
            lona_validation_message("invalid_amount", category_id=cat_id, product_id=product_id, lang=lang),
            reply_markup=_gift_param_cancel_keyboard(lang, back_to=f"gst:giftitem:{cat_id}:{product_id}"),
        )
    ok, reason = validate_lona_amount(cat_id, product_id, amount)
    if not ok:
        return await message.answer(
            lona_validation_message(reason, category_id=cat_id, product_id=product_id, lang=lang),
            reply_markup=_gift_param_cancel_keyboard(lang, back_to=f"gst:giftitem:{cat_id}:{product_id}"),
        )
    quote = quote_lona_product(cat_id, product_id, amount)
    if not quote:
        return await message.answer(t(lang, "store_invalid_product"))
    await state.update_data(lona_card_quote=quote)
    await message.answer(
        _lona_quote_summary_text(lang, quote),
        reply_markup=_lona_manual_confirm_kb(lang, back_to=f"gst:giftitem:{cat_id}:{product_id}"),
    )


@router.callback_query(lambda c: c.data == "gst:giftmanualconfirm")
async def confirm_lona_card_amount_purchase(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    data = await state.get_data()
    quote = dict(data.get("lona_card_quote") or {})
    if not quote:
        return await callback.answer(t(lang, "store_invalid_product"), show_alert=True)
    reseller_id = await _resolve_user_reseller(callback.from_user.id, callback.bot.id)
    if not reseller_id:
        return await callback.answer(t(lang, "store_reseller_not_linked"), show_alert=True)
    await state.clear()
    await callback.answer(t(lang, "processing_order"), show_alert=False)
    result = await _execute_lona_card_purchase(
        bot=callback.bot,
        user_id=int(callback.from_user.id),
        lang=lang,
        reseller_id=int(reseller_id),
        quote=quote,
    )
    kind = str(result.get("kind") or "")
    if kind == "charge_error":
        return await callback.answer(str(result.get("alert") or t(lang, "purchase_failed_plain")), show_alert=True)
    if callback.message:
        await callback.message.edit_text(
            str(result.get("text") or t(lang, "purchase_failed_plain")),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")]
                ]
            ),
        )


@router.message(GiftStoreFlow.waiting_quantity)
async def collect_gift_quantity(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    data = await state.get_data()
    pending = dict(data.get("gift_pending") or {})
    if not pending:
        await state.clear()
        await message.answer(t(lang, "store_invalid_product"))
        return
    raw = str(message.text or "").strip()
    try:
        qty = int(raw)
    except Exception:
        qty = 0
    qty_min = max(1, _to_int(pending.get("qty_min") or 1))
    qty_max = max(qty_min, _to_int(pending.get("qty_max") or qty_min))
    if qty < qty_min or qty > qty_max:
        await message.answer(_gift_qty_prompt_text(lang, qty_min, qty_max), reply_markup=_gift_param_cancel_keyboard(lang))
        return
    pending["quantity"] = int(qty)
    markup_percent = _to_decimal(pending.get("markup_percent") or 0.0)
    if markup_percent <= 0:
        markup_percent = _to_decimal(await _resolve_digital_products_markup_percent())
    unit_cost_raw = _to_decimal(pending.get("unit_cost_price") or 0.0)
    if unit_cost_raw <= 0:
        unit_cost_raw = _to_decimal(pending.get("cost_price") or 0.0)
    cost_price_dec = (unit_cost_raw * Decimal(str(int(qty)))).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    sale_price_dec = _apply_markup_decimal(cost_price_dec, markup_percent)
    pending["cost_price"] = float(cost_price_dec)
    pending["sale_price"] = float(sale_price_dec)
    params = [str(item).strip() for item in list(pending.get("params") or []) if str(item).strip()]
    pending["params"] = params
    pending["param_index"] = int(pending.get("param_index") or 0)
    await state.update_data(gift_pending=pending)
    if params:
        await state.set_state(GiftStoreFlow.waiting_param)
        await message.answer(_gift_param_prompt_text(lang, params[0]), reply_markup=_gift_param_cancel_keyboard(lang))
        return
    await state.clear()
    reseller_id = _to_int(pending.get("reseller_id"))
    if reseller_id <= 0:
        await message.answer(t(lang, "store_reseller_not_linked"))
        return
    await message.answer(t(lang, "processing_order"))
    result = await _execute_gift_purchase(
        bot=message.bot,
        user_id=int(message.from_user.id),
        lang=lang,
        reseller_id=int(reseller_id),
        selected={"name": str(pending.get("selected_name") or "")},
        product_id=str(pending.get("product_id") or ""),
        available_offers=list(pending.get("offers") or []),
        sale_price=float(_to_float(pending.get("sale_price"))),
        cost_price=float(_to_float(pending.get("cost_price"))),
        quantity=int(pending.get("quantity") or 1),
        extra_params=dict(pending.get("extra_params") or {}),
    )
    kind = str(result.get("kind") or "")
    await message.answer(str(result.get("alert") or result.get("text") or t(lang, "purchase_failed_plain")))
    if kind != "success":
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=await menu_for_current_bot(lang, (await message.bot.get_me()).id),
        )


@router.message(GiftStoreFlow.waiting_param)
async def collect_gift_required_param(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    data = await state.get_data()
    pending = dict(data.get("gift_pending") or {})
    if not pending:
        await state.clear()
        await message.answer(t(lang, "store_invalid_product"))
        return
    params = [str(item).strip() for item in list(pending.get("params") or []) if str(item).strip()]
    index = _to_int(pending.get("param_index") or 0)
    if index >= len(params):
        index = 0
    value = str(message.text or "").strip()
    if not value:
        if params:
            await message.answer(_gift_param_prompt_text(lang, params[index]), reply_markup=_gift_param_cancel_keyboard(lang))
        else:
            await message.answer(t(lang, "store_invalid_product"))
        return
    extra_params = dict(pending.get("extra_params") or {})
    if params:
        extra_params[params[index]] = value
    pending["extra_params"] = extra_params
    index += 1
    if index < len(params):
        pending["param_index"] = index
        await state.update_data(gift_pending=pending)
        await message.answer(_gift_param_prompt_text(lang, params[index]), reply_markup=_gift_param_cancel_keyboard(lang))
        return
    await state.clear()
    reseller_id = _to_int(pending.get("reseller_id"))
    if reseller_id <= 0:
        await message.answer(t(lang, "store_reseller_not_linked"))
        return
    await message.answer(t(lang, "processing_order"))
    result = await _execute_gift_purchase(
        bot=message.bot,
        user_id=int(message.from_user.id),
        lang=lang,
        reseller_id=int(reseller_id),
        selected={"name": str(pending.get("selected_name") or "")},
        product_id=str(pending.get("product_id") or ""),
        available_offers=list(pending.get("offers") or []),
        sale_price=float(_to_float(pending.get("sale_price"))),
        cost_price=float(_to_float(pending.get("cost_price"))),
        quantity=int(pending.get("quantity") or 1),
        extra_params=extra_params,
    )
    kind = str(result.get("kind") or "")
    await message.answer(str(result.get("alert") or result.get("text") or t(lang, "purchase_failed_plain")))
    if kind != "success":
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=await menu_for_current_bot(lang, (await message.bot.get_me()).id),
        )


@router.callback_query(lambda c: c.data and c.data.startswith("gst:buygame:"))
async def start_g2bulk_game_checkout(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_callback(callback, lang):
        return
    parts = str(callback.data or "").split(":")
    if len(parts) < 4:
        return await callback.answer(t(lang, "store_invalid_package"), show_alert=True)
    game_id = str(parts[2]).strip()
    group_key = "topup"
    item_id = ""
    if len(parts) >= 5:
        group_key = str(parts[3]).strip() or "topup"
        item_id = str(parts[4]).strip()
    else:
        item_id = str(parts[3]).strip()
    items = await get_game_topups(game_id, force=True)
    snapshot = await get_catalog_snapshot(force=False)
    game_name = _find_game_name(game_id, snapshot)
    grouped_count = len(_group_game_items(game_id, items, lang))
    selected: dict[str, Any] | None = None
    for item in items:
        if str(item.get("id") or "").strip() == item_id:
            selected = item
            break
    if not selected:
        return await callback.answer(t(lang, "store_topup_package_not_found"), show_alert=True)

    markup_percent = await _resolve_digital_products_markup_percent()
    provider_price = _money_decimal(selected.get("price"))
    sale_price = _resolve_game_sale_price_decimal(
        game_id=game_id,
        game_name=game_name,
        provider_price=provider_price,
        markup_percent=markup_percent,
    )
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
            "provider_offers": _provider_offers_for_row(
                selected,
                fallback_provider="g2bulk",
                fallback_ref_id=item_id,
                fallback_price=float(provider_price),
            ),
        }
    )
    state_data = await state.get_data()
    game_prefill = dict(state_data.get("game_prefill") or {})
    prefill_matches = (
        str(game_prefill.get("game_id") or "").strip() == game_id
        and str(game_prefill.get("item_id") or "").strip() == item_id
    )
    player_id_prefill = str(game_prefill.get("player_id") or "").strip() if prefill_matches else ""
    server_id_prefill = str(game_prefill.get("server_id") or "").strip() if prefill_matches else ""
    if player_id_prefill:
        if not callback.message:
            await state.clear()
            return await callback.answer(t(lang, "store_session_expired"), show_alert=True)
        data = await state.get_data()
        pending = dict(data.get("gst_pending_buy") or {})
        pending["player_id"] = player_id_prefill
        await state.clear()
        await callback.answer(t(lang, "processing_order"), show_alert=False)
        await _execute_g2bulk_game_purchase(callback.message, pending, server_id=server_id_prefill)
        return

    await state.set_state(GameStoreFlow.waiting_topup_player)
    if not await _edit_callback_target(
        callback,
        f"{_game_title(lang, game_name)}\n\n{t(lang, 'store_send_player_id')}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "back"), callback_data=(f"gst:gamegroup:{game_id}:{group_key}" if grouped_count > 1 else f"gst:game:{game_id}"))],
                [InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="gst:buycancel")],
            ]
        ),
    ):
        await callback.answer()
        return
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:buycancel")
async def cancel_g2bulk_buy_flow(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await callback.message.edit_text(
        t(lang, "cancelled_plain"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "back"), callback_data="gst:gameroot")],
                [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="gst:menu")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "gst:noop")
async def store_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.message(GameStoreFlow.waiting_topup_player)
async def g2bulk_collect_player_id(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    player_id = str(message.text or "").strip()
    if not player_id:
        return await message.answer(t(lang, "store_player_id_empty"))
    data = await state.get_data()
    pending = dict(data.get("gst_pending_buy") or {})
    if not pending:
        await state.clear()
        return await message.answer(t(lang, "store_session_expired"))
    pending["player_id"] = player_id
    await state.update_data(gst_pending_buy=pending)

    if bool(pending.get("requires_server")):
        await state.set_state(GameStoreFlow.waiting_topup_server)
        return await message.answer(t(lang, "store_send_server_id"))

    await state.clear()
    await _execute_g2bulk_game_purchase(message, pending, server_id="")


@router.message(GameStoreFlow.waiting_topup_server)
async def g2bulk_collect_server_id(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if not await guard_core_service_message(message, lang):
        return
    server_id = str(message.text or "").strip()
    if not server_id:
        return await message.answer(t(lang, "store_server_id_empty"))
    data = await state.get_data()
    pending = dict(data.get("gst_pending_buy") or {})
    if not pending:
        await state.clear()
        return await message.answer(t(lang, "store_session_expired"))
    await state.clear()
    await _execute_g2bulk_game_purchase(message, pending, server_id=server_id)


async def _execute_g2bulk_game_purchase(message: types.Message, pending: dict[str, Any], *, server_id: str) -> None:
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    reseller_id = await _resolve_user_reseller(message.from_user.id, (await message.bot.get_me()).id)
    if not reseller_id:
        return await message.answer(t(lang, "store_reseller_not_linked"))

    game_id = str(pending.get("game_id") or "").strip()
    item_id = str(pending.get("item_id") or "").strip()
    player_id = str(pending.get("player_id") or "").strip()
    name = str(pending.get("name") or "-")
    offers = [row for row in list(pending.get("provider_offers") or []) if isinstance(row, dict)]
    if not offers:
        offers = [{"provider": "g2bulk", "ref_id": item_id, "price": float(_money_decimal(pending.get("provider_price", pending.get("sale_price", 0)))), "available": True}]
    offers = [row for row in offers if digital_provider_enabled(str(row.get("provider") or ""))]
    offers.sort(key=lambda row: (0 if bool(row.get("available")) else 1, float(_money_decimal(row.get("price") or 0.0)) if float(_money_decimal(row.get("price") or 0.0)) > 0 else 9999999))
    available_offers = [row for row in offers if bool(row.get("available"))]
    if not available_offers:
        return await message.answer(t(lang, "store_out_of_stock"))

    primary_offer = dict(available_offers[0])
    cost_price = float(_money_decimal(primary_offer.get("price") or pending.get("provider_price", pending.get("sale_price", 0))))
    sale_price = float(_money_decimal(pending.get("sale_price", cost_price)))
    service_ref_id = f"{str(primary_offer.get('provider') or 'g2bulk')}:{'topup'}:{str(primary_offer.get('ref_id') or item_id)}"

    order, err = await _core_charge(
        user_id=int(message.from_user.id),
        reseller_id=int(reseller_id),
        service_ref_id=service_ref_id,
        sale_price=sale_price,
        cost_price=cost_price,
    )
    if not order or err:
        return await message.answer(err or t(lang, "purchase_failed_plain"))

    await message.answer(t(lang, "processing_order"), reply_markup=ReplyKeyboardRemove())
    provider_resp: dict[str, Any] | None = None
    chosen_offer: dict[str, Any] | None = None
    failures: list[str] = []
    for offer in available_offers:
        offer_price = float(_money_decimal(offer.get("price") or 0.0))
        if offer_price <= 0:
            continue
        if offer_price > (cost_price + 0.000001):
            continue
        attempt = await _create_provider_game_order(
            provider=str(offer.get("provider") or "g2bulk"),
            ref_id=str(offer.get("ref_id") or item_id),
            game_id=game_id,
            player_id=player_id,
            server_id=server_id or None,
            catalogue_name=str(pending.get("catalogue_name") or name or "").strip(),
        )
        if _provider_ok(attempt):
            provider_resp = attempt
            chosen_offer = dict(offer)
            break
        failures.append(_extract_provider_error(attempt.get("data") or attempt))
    if not provider_resp or not chosen_offer:
        await _core_refund(
            user_id=int(message.from_user.id),
            reseller_id=int(reseller_id),
            order=order,
            sale_price=sale_price,
            cost_price=cost_price,
        )
        error_text = failures[0] if failures else t(lang, "provider_request_failed")
        await update_order_details(order["_id"], {"provider_response": provider_resp or {}, "provider_error": error_text, "provider_offers_attempted": available_offers})
        await _notify_owner_stock_issue(
            bot=message.bot,
            user_id=int(message.from_user.id),
            reseller_id=int(reseller_id),
            item_name=name,
            provider_error=error_text,
        )
        await message.answer(
            t(lang, "store_out_of_stock_admin_notified")
        )
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=await menu_for_current_bot(lang, (await message.bot.get_me()).id),
        )
        return

    provider_code = str(chosen_offer.get("provider") or "g2bulk")
    provider_data = provider_resp.get("data")
    external_order_id = _extract_external_order_id(provider_data)
    snapshot = await get_catalog_snapshot(force=False)
    display_game_name = _find_game_name(game_id, snapshot)
    details_payload = {
        "provider_code": provider_code,
        "provider_order_id": external_order_id,
        "provider_response": provider_resp,
        "game_id": game_id,
        "player_id": player_id,
        "server_id": server_id,
        "provider_offers_attempted": available_offers,
        "number_mode": "digital_products",
    }
    await update_order_details(
        order["_id"],
        details_payload,
    )

    if not external_order_id:
        await _notify_owner_pending_game_topup(
            bot=message.bot,
            item_name=name,
            order=order,
            provider_code=provider_code,
            external_order_id="",
            game_name=display_game_name,
            player_id=player_id,
            server_id=server_id,
            reason="MISSING_PROVIDER_ORDER_ID",
        )
        await message.answer(
            _digital_game_order_summary_text(
                lang,
                order_id=str(order.get("_id") or ""),
                game_name=display_game_name,
                package_name=name,
                player_id=player_id,
                price=sale_price,
                status="PENDING",
            )
        )
        return

    status_resp = await _poll_provider_order_status(provider=provider_code, external_order_id=external_order_id)
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
            t(lang, "store_topup_provider_failed_refunded")
        )
        return

    if not (status_resp is not None and _provider_status_is_success(status_resp)):
        await _notify_owner_pending_game_topup(
            bot=message.bot,
            item_name=name,
            order=order,
            provider_code=provider_code,
            external_order_id=external_order_id,
            game_name=display_game_name,
            player_id=player_id,
            server_id=server_id,
            reason="Provider confirmation stayed pending after automatic polling.",
        )
        await message.answer(
            _digital_game_order_summary_text(
                lang,
                order_id=str(order.get("_id") or ""),
                game_name=display_game_name,
                package_name=name,
                player_id=player_id,
                price=sale_price,
                status="PENDING",
            )
        )
        return

    await update_order_status(order["_id"], "success")

    await message.answer(
        _digital_game_order_summary_text(
            lang,
            order_id=str(order.get("_id") or ""),
            game_name=display_game_name,
            package_name=name,
            player_id=player_id,
            price=sale_price,
            status="SUCCESS",
        )
    )

