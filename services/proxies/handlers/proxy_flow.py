from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove
from bson import ObjectId

from database.mongo import db
from database.orders_repo import (
    create_order,
    get_order,
    list_user_proxy_orders,
    update_order_details,
    update_order_status,
)
from database.user_repo import get_user
from services.proxies.catalog_cache import (
    encode_token,
    decode_token,
    filter_offers,
    get_offers_cache,
    get_offers_cache_timestamp,
    set_offers_cache,
)
from services.proxies.keyboards.proxy_kb import (
    proxy_entry_kb,
    proxy_offer_duration_kb,
    proxy_password_input_kb,
    proxy_my_orders_kb,
    proxy_offer_actions_kb,
    proxy_offers_kb,
    proxy_order_actions_kb,
    proxy_search_kb,
    proxy_type_kb,
)
from services.proxies.manager import (
    PROXY_PROVIDERS,
    get_proxy_catalog,
    proxy_change_check_price,
    proxy_change_only_cooldown_minutes,
    reconfigure_proxy_order,
    refresh_proxy_order,
    reserve_available_4g_username,
    rent_proxy_offer,
    verify_proxy_offer_delivery,
)
from services.proxies.states.proxy_states import ProxyFlow
from utils.financial_manager import FinancialManager
from utils.bot_menu_context import menu_for_current_bot
from utils.core_service_guard import finance_error_public_text
from utils.provider_alias import provider_generic_error, provider_public_id
from utils.translations import t

router = Router()
logger = logging.getLogger("proxy_flow")

_PROXY_DURATION_ORDER = {
    "1 Day": 0,
    "1 Week": 1,
    "1 Month": 2,
    "2 Week": 3,
    "12 Hour": 4,
    "2 Hour": 5,
    "3 Hour": 6,
    "3 Day": 7,
}


def _rotation_sort_key(label: str) -> tuple[int, str]:
    text = str(label or "").strip().lower()
    if text.startswith("rotation ") and text.endswith("m"):
        raw = text[len("rotation ") : -1].strip()
        try:
            return (int(raw), text)
        except Exception:
            pass
    return (10_000, text)


def _btn_values(key: str) -> set[str]:
    return {t("en", key), t("ar", key)}


def _is_btn(text: str | None, key: str) -> bool:
    return (text or "").strip() in _btn_values(key)


async def _resolve_user_reseller(user_id: int, bot_id: int) -> int:
    _ = bot_id
    return user_id


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


async def _loading_text_animator(
    bot,
    *,
    chat_id: int,
    message_id: int,
    base_text: str,
    stop_event: asyncio.Event,
    max_dots: int = 10,
    interval_sec: float = 1.0,
) -> None:
    dots = 1
    while not stop_event.is_set():
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{base_text}{'.' * dots}",
                reply_markup=None,
            )
        except TelegramBadRequest:
            return
        except Exception:
            return
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
            return
        except asyncio.TimeoutError:
            dots = 1 if dots >= max_dots else dots + 1


def _start_loading_text_animator(
    bot,
    *,
    chat_id: int,
    message_id: int,
    base_text: str,
) -> tuple[asyncio.Event, asyncio.Task]:
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        _loading_text_animator(
            bot,
            chat_id=chat_id,
            message_id=message_id,
            base_text=base_text.rstrip(". "),
            stop_event=stop_event,
        )
    )
    return stop_event, task


async def _stop_loading_text_animator(stop_event: asyncio.Event | None, task: asyncio.Task | None) -> None:
    if stop_event is not None:
        stop_event.set()
    if task is None:
        return
    try:
        await task
    except Exception:
        pass


def _proxy_filters_text(lang: str, country: str | None, state: str | None, city: str | None) -> str:
    c = country or t(lang, "any_plain")
    s = state or t(lang, "any_plain")
    ci = city or t(lang, "any_plain")
    return t(lang, "proxy_filters_line").format(country=c, state=s, city=ci)


def _location_mode(data: dict) -> str | None:
    country = data.get("proxy_country")
    if not country:
        return None
    offers = data.get("proxy_catalog") or get_offers_cache()
    scoped = filter_offers(offers, country=country)
    locations = {
        _offer_location_value(row)
        for row in scoped
        if _offer_location_value(row)
    }
    if locations:
        return "location"
    return None


def _offer_location_value(offer: dict) -> str:
    state = str(offer.get("state") or "").strip()
    city = str(offer.get("city") or "").strip()
    if state and state.lower() != "any":
        return state
    if city and city.lower() != "any":
        return city
    return ""


def _filter_proxy_offers(data: dict) -> list[dict]:
    offers = data.get("proxy_catalog") or get_offers_cache()
    mode = _location_mode(data)
    scoped = filter_offers(
        offers,
        country=data.get("proxy_country"),
    )
    selected_location = str(data.get("proxy_location") or "").strip()
    if not selected_location:
        return scoped
    lowered = selected_location.lower()
    return [
        row for row in scoped
        if _offer_location_value(row).lower() == lowered
    ]


def _state_required(data: dict) -> bool:
    return False


def _city_required(data: dict) -> bool:
    return False


def _available_proxy_providers(data: dict) -> list[str]:
    mode = _location_mode(data)
    offers = filter_offers(
        data.get("proxy_catalog") or get_offers_cache(),
        country=data.get("proxy_country"),
        state=data.get("proxy_state") if mode == "state" else None,
        city=data.get("proxy_city") if mode == "city" else None,
    )
    values = sorted(
        {
            str(row.get("carrier") or row.get("provider") or "").strip()
            for row in offers
            if str(row.get("carrier") or row.get("provider") or "").strip()
        },
        key=lambda label: str(label).lower(),
    )
    return values


def _available_proxy_protocols(data: dict) -> list[str]:
    _ = data
    return []


def _available_proxy_protocol_options(data: dict, lang: str) -> list[tuple[str, str]]:
    _ = data, lang
    return []


def _quick_country_options(data: dict) -> list[tuple[str, str]]:
    counts: dict[str, int] = {}
    for row in data.get("proxy_catalog") or get_offers_cache():
        country = str(row.get("country") or "").strip()
        if not country or country.lower() == "any":
            continue
        counts[country] = counts.get(country, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    return [(country, f"proxy:quick_country:{encode_token(country)}") for country, _count in ranked]


def _quick_location_options(data: dict) -> list[tuple[str, str]]:
    country = str(data.get("proxy_country") or "").strip()
    if not country:
        return []
    offers = filter_offers(data.get("proxy_catalog") or get_offers_cache(), country=country)
    counts: dict[str, int] = {}
    for row in offers:
        location = _offer_location_value(row)
        if not location:
            continue
        counts[location] = counts.get(location, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    country_token = encode_token(country)
    return [(location, f"proxy:quick_state:{country_token}:{encode_token(location)}") for location, _count in ranked]


def _available_proxy_provider_options(data: dict) -> list[tuple[str, str]]:
    mode = _location_mode(data)
    offers = filter_offers(
        data.get("proxy_catalog") or get_offers_cache(),
        country=data.get("proxy_country"),
        state=data.get("proxy_state") if mode == "state" else None,
        city=data.get("proxy_city") if mode == "city" else None,
    )
    values = sorted(
        {
            str(row.get("carrier") or row.get("provider") or "").strip()
            for row in offers
            if str(row.get("carrier") or row.get("provider") or "").strip()
        },
        key=lambda label: str(label).lower(),
    )
    return [(carrier, carrier) for carrier in values]


def _available_proxy_periods(data: dict) -> list[str]:
    mode = _location_mode(data)
    offers = filter_offers(
        data.get("proxy_catalog") or get_offers_cache(),
        country=data.get("proxy_country"),
        state=data.get("proxy_state") if mode == "state" else None,
        city=data.get("proxy_city") if mode == "city" else None,
        carrier=data.get("proxy_provider"),
    )
    return sorted(
        {
            str(row.get("period") or "").strip()
            for row in offers
            if str(row.get("period") or "").strip()
        },
        key=_rotation_sort_key,
    )


def _available_proxy_period_options(data: dict) -> list[tuple[str, str]]:
    mode = _location_mode(data)
    offers = filter_offers(
        data.get("proxy_catalog") or get_offers_cache(),
        country=data.get("proxy_country"),
        state=data.get("proxy_state") if mode == "state" else None,
        city=data.get("proxy_city") if mode == "city" else None,
        carrier=data.get("proxy_provider"),
    )
    best_prices: dict[str, float] = {}
    best_loads: dict[str, int | None] = {}
    for row in offers:
        period = str(row.get("period") or "").strip()
        if not period:
            continue
        price = float(row.get("price") or 0.0)
        current = best_prices.get(period)
        if current is None or (price > 0 and price < current):
            best_prices[period] = price
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        try:
            usage = int(raw.get("usage"))
        except Exception:
            usage = -1
        load_value: int | None = usage if usage >= 0 else None
        current_load = best_loads.get(period)
        if current_load is None:
            best_loads[period] = load_value
        elif load_value is not None and load_value < current_load:
            best_loads[period] = load_value
    return [
        (period, period)
        for period, price in sorted(best_prices.items(), key=lambda item: _rotation_sort_key(item[0]))
    ]


def _duration_option_map(data: dict) -> dict[str, tuple[str, float]]:
    mode = _location_mode(data)
    offers = filter_offers(
        data.get("proxy_catalog") or get_offers_cache(),
        country=data.get("proxy_country"),
        state=data.get("proxy_state") if mode == "state" else None,
        city=data.get("proxy_city") if mode == "city" else None,
        carrier=data.get("proxy_provider"),
        period=data.get("proxy_period"),
    )
    options: dict[str, tuple[str, float]] = {}
    for row in offers:
        for item in (row.get("raw") or {}).get("duration_options", []):
            value = str(item.get("value") or "").strip()
            label = str(item.get("label") or "").strip()
            try:
                base_price = float(item.get("price") or 0.0)
            except Exception:
                base_price = 0.0
            if not value or not label or base_price <= 0:
                continue
            current_base = float(row.get("base_price") or 0.0)
            current_sale = float(row.get("price") or current_base or 0.0)
            markup_ratio = (current_sale / current_base) if current_base > 0 else 1.0
            price = round(base_price * markup_ratio, 4)
            current = options.get(value)
            if current is None or price < current[1]:
                options[value] = (label, price)
    return options


def _available_proxy_durations(data: dict) -> list[str]:
    options = _duration_option_map(data)
    return [value for value, _payload in sorted(options.items(), key=lambda item: (_PROXY_DURATION_ORDER.get(item[1][0], 1000), float(item[0])))]


def _available_proxy_duration_options(data: dict) -> list[tuple[str, str]]:
    options = _duration_option_map(data)
    return [
        (f"{label} - {price:.2f}$", value)
        for value, (label, price) in sorted(options.items(), key=lambda item: float(item[0]))
    ]


def _offers_with_duration_price(data: dict, offers: list[dict]) -> list[dict]:
    duration_value = str(data.get("proxy_duration_value") or "").strip()
    if not duration_value:
        return [dict(row) for row in offers]
    out: list[dict] = []
    for row in offers:
        item = dict(row)
        raw = dict(item.get("raw") or {})
        for duration in raw.get("duration_options", []):
            value = str(duration.get("value") or "").strip()
            if value != duration_value:
                continue
            try:
                base_price = float(duration.get("price") or 0.0)
            except Exception:
                base_price = 0.0
            if base_price > 0:
                current_base = float(item.get("base_price") or 0.0)
                current_sale = float(item.get("price") or current_base or 0.0)
                markup_ratio = (current_sale / current_base) if current_base > 0 else 1.0
                item["base_price"] = round(base_price, 4)
                item["price"] = round(base_price * markup_ratio, 4)
                item["duration_label"] = str(duration.get("label") or duration_value)
                item["duration_value"] = duration_value
            break
        out.append(item)
    return out


def _single_offer_with_duration_price(data: dict, offer: dict) -> dict:
    priced = _offers_with_duration_price(data, [offer])
    return priced[0] if priced else dict(offer)


def _dedupe_proxy_offers(offers: list[dict]) -> list[dict]:
    unique: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for offer in offers:
        raw = offer.get("raw") if isinstance(offer.get("raw"), dict) else {}
        key = (
            str(_offer_location_value(offer) or "").strip().lower(),
            str(offer.get("carrier") or "").strip().lower(),
            str(offer.get("period") or raw.get("button_label") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(offer)
    return unique


def _proxy_offer_heading(lang: str) -> str:
    return "تفاصيل عرض البروكسي" if str(lang).lower().startswith("ar") else "Proxy Offer Details"


def _proxy_duration_hint(lang: str) -> str:
    return "اختر مدة الشراء. السعر ظاهر على كل خيار." if str(lang).lower().startswith("ar") else "Choose rental duration. Price is shown on each option."


def _proxy_service_disabled_text(lang: str) -> str:
    if str(lang).lower().startswith("ar"):
        return "خدمة البروكسي متوقفة حالياً بشكل مؤقت.\n\nرجاء المحاولة لاحقاً."
    return "Proxy service is temporarily disabled right now.\n\nPlease try again later."

def _proxy_password_prompt_text(lang: str, username: str) -> str:
    if str(lang).lower().startswith("ar"):
        return f"اسم المستخدم الجاهز: {username}\n\nأرسل كلمة مرور البروكسي الآن."
    return f"Reserved username: {username}\n\nSend the proxy password now."


def _valid_proxy_password(password: str) -> bool:
    value = str(password or "").strip()
    if len(value) < 4 or len(value) > 32:
        return False
    if any(ch.isspace() for ch in value):
        return False
    return True


def _proxy_offer_text(lang: str, offer: dict, protocol: str | None, *, include_duration: bool = False, duration_label: str | None = None, include_prices: bool = False) -> str:
    carrier = str(offer.get("carrier") or "").strip() or str(offer.get("state") or "").strip() or "-"
    country = str(offer.get("country") or "-").strip()
    state = str(offer.get("state") or "Any").strip()
    city = str(offer.get("city") or "Any").strip()
    location = state if city in {"", "Any", state} else city if state in {"", "Any"} else f"{state} / {city}"
    period = str(offer.get("period") or "-").strip()
    lines: list[str]
    if str(lang).lower().startswith("ar"):
        lines = [
            _proxy_offer_heading(lang),
            "",
            f"المزوّد: {carrier}",
            f"الدولة: {country}",
            f"الولاية/المدينة: {location}",
            f"الروتيشن: {period}",
        ]
        if include_duration:
            lines.append(f"مدة الشراء: {str(duration_label or '-').strip()}")
        if include_prices:
            base_price = float(offer.get('base_price') or 0.0)
            sale_price = float(offer.get('price') or 0.0)
            if base_price > 0 and abs(base_price - sale_price) > 0.0001:
                lines.append(f"السعر الأساسي: {base_price:.2f}$")
            lines.append(f"السعر: {sale_price:.2f}$")
    else:
        lines = [
            _proxy_offer_heading(lang),
            "",
            f"Carrier: {carrier}",
            f"Country: {country}",
            f"State/City: {location}",
            f"Rotation: {period}",
        ]
        if include_duration:
            lines.append(f"Duration: {str(duration_label or '-').strip()}")
        if include_prices:
            base_price = float(offer.get('base_price') or 0.0)
            sale_price = float(offer.get('price') or 0.0)
            if base_price > 0 and abs(base_price - sale_price) > 0.0001:
                lines.append(f"Base price: {base_price:.2f}$")
            lines.append(f"Price: {sale_price:.2f}$")
    return "\n".join(lines).strip()


def _proxy_selection_ready(data: dict) -> bool:
    if not data.get("proxy_country"):
        return False
    if _location_mode(data) and not data.get("proxy_location"):
        return False
    return True


def _proxy_selection_text(lang: str, data: dict) -> str:
    country = data.get("proxy_country") or t(lang, "not_selected_plain")
    location = data.get("proxy_location") or t(lang, "not_needed_plain")
    duration = str(data.get("proxy_duration_label") or t(lang, "not_selected_plain"))
    if str(lang).lower().startswith("ar"):
        return "\n".join(
            [
                f"الدولة: {country}",
                f"الولاية/المدينة: {location}",
                f"البروتوكول: {protocol}",
                f"المزود: {provider}",
                f"المدة: {duration}",
            ]
        )
    return "\n".join(
        [
            f"Country: {country}",
            f"State/City: {location}",
            f"Protocol: {protocol}",
            f"Provider: {provider}",
            f"Duration: {duration}",
        ]
    )


def _proxy_type_label(lang: str, proxy_type: str | None) -> str:
    category = str(proxy_type or "").strip().lower()
    if category == "consumptive":
        return t(lang, "proxy_type_consumptive")
    return t(lang, "proxy_type_unlimited")


def _proxy_selection_text(lang: str, data: dict) -> str:
    country = data.get("proxy_country") or t(lang, "not_selected_plain")
    location = data.get("proxy_location") or t(lang, "not_needed_plain")
    duration = str(data.get("proxy_duration_label") or t(lang, "not_selected_plain"))
    if str(lang).lower().startswith("ar"):
        return "\n".join(
            [
                f"الدولة: {country}",
                f"الولاية/المدينة: {location}",
                f"المدة: {duration}",
            ]
        )
    return "\n".join(
        [
            f"Country: {country}",
            f"State/City: {location}",
            f"Duration: {duration}",
        ]
    )


def _normalize_proxy_category(value: str | None) -> str:
    category = str(value or "").strip().lower()
    if category in {"unlimited", "consumptive"}:
        return category
    return ""


def _enabled_proxy_categories() -> list[str]:
    categories: list[str] = []
    if "4g" in PROXY_PROVIDERS or "cyberyozh" in PROXY_PROVIDERS:
        categories.append("unlimited")
    if "9proxy" in PROXY_PROVIDERS:
        categories.append("consumptive")
    return categories


def _category_provider_match(offer: dict, category: str) -> bool:
    provider = str(offer.get("provider") or "").strip().lower()
    billing_type = str(offer.get("billing_type") or "").strip().lower()
    title = str(offer.get("title") or "").strip().lower()
    raw = offer.get("raw") if isinstance(offer.get("raw"), dict) else {}
    if category == "unlimited":
        if provider == "4g":
            return "golden package" in title
        if provider == "cyberyozh":
            return str(raw.get("proxy_category") or "").strip().lower() == "residential_static"
        return False
    if category == "consumptive":
        if provider != "9proxy":
            return False
        # Guard against accidental IP/unlimited rows from 9Proxy.
        return billing_type in {"bandwidth", "consumable"} or "gb" in title
    return True


def _apply_proxy_category(offers: list[dict], category: str) -> list[dict]:
    if not category:
        return list(offers or [])
    return [o for o in (offers or []) if isinstance(o, dict) and _category_provider_match(o, category)]


async def _offer_usage_counts(offers: list[dict]) -> dict[str, int]:
    service_ids: list[str] = []
    for row in offers or []:
        provider = str(row.get("provider") or "").strip().lower()
        offer_id = str(row.get("offer_id") or "").strip()
        if not provider or not offer_id:
            continue
        service_ids.append(f"proxy:{provider}:{offer_id}")
    service_ids = sorted(set(service_ids))
    if not service_ids:
        return {}

    pipeline = [
        {"$match": {"service_id": {"$in": service_ids}, "status": "success"}},
        {"$group": {"_id": "$service_id", "count": {"$sum": 1}}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(length=None)
    counts: dict[str, int] = {sid: 0 for sid in service_ids}
    for row in rows:
        sid = str(row.get("_id") or "")
        counts[sid] = int(row.get("count") or 0)
    return counts


async def _sort_offers_by_low_usage(offers: list[dict]) -> list[dict]:
    if not offers:
        return []
    usage_map = await _offer_usage_counts(offers)
    enriched: list[dict] = []
    for row in offers:
        item = dict(row)
        sid = f"proxy:{str(item.get('provider') or '').lower()}:{str(item.get('offer_id') or '')}"
        item["usage_count"] = int(usage_map.get(sid, 0))
        enriched.append(item)
    enriched.sort(
        key=lambda x: (
            int(x.get("usage_count") or 0),
            float(x.get("price") or 0.0),
            str(x.get("provider") or ""),
            str(x.get("title") or ""),
        )
    )
    return enriched


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except Exception:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    return None


def _append_proxy_history(order: dict, event: dict) -> list[dict]:
    history = list(order.get("proxy_change_history") or [])
    history.append(event)
    return history[-40:]


def _proxy_order_can_reconfigure(order: dict | None) -> bool:
    if not isinstance(order, dict):
        return False
    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or order.get("proxy_provider_order_id") or "").strip()
    return provider == "4g" and bool(provider_order_id)


def _package_id_from_offer_id(value: str | None) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    left = raw.split(":", 1)[0]
    try:
        return int(left)
    except Exception:
        return 0


def _filter_reconfigure_catalog(data: dict, offers: list[dict]) -> list[dict]:
    package_id = int(data.get("proxy_manage_package_id") or 0)
    provider = str(data.get("proxy_manage_provider") or "").strip().lower()
    if not package_id or not provider:
        return offers

    filtered: list[dict] = []
    for offer in offers:
        if str(offer.get("provider") or "").strip().lower() != provider:
            continue
        offer_package_id = _package_id_from_offer_id(offer.get("offer_id"))
        if offer_package_id != package_id:
            continue
        filtered.append(offer)
    return filtered


def _proxy_manage_reconfigure_mode(data: dict) -> bool:
    return bool(str(data.get("proxy_manage_order_id") or "").strip())


def _order_detail_text(lang: str, order: dict) -> str:
    provider = provider_public_id(order.get("provider"))
    endpoint = str(order.get("proxy_endpoint") or "-")
    http_endpoint = str(order.get("proxy_http_endpoint") or "").strip()
    socks5_endpoint = str(order.get("proxy_socks5_endpoint") or "").strip()
    username = str(order.get("proxy_username") or "-")
    password = str(order.get("proxy_password") or "-")
    expires = str(order.get("proxy_expires_at") or "-")
    location = order.get("proxy_location") if isinstance(order.get("proxy_location"), dict) else {}
    country = str(location.get("country") or t(lang, "any_plain"))
    state = str(location.get("state") or t(lang, "any_plain"))
    city = str(location.get("city") or t(lang, "any_plain"))
    quality = order.get("proxy_last_quality") if isinstance(order.get("proxy_last_quality"), dict) else {}
    quality_decision = str(quality.get("decision") or "-")
    quality_reason = str(quality.get("reason") or "-")
    endpoint_lines: list[str] = []
    if http_endpoint or socks5_endpoint:
        if str(lang).lower().startswith("ar"):
            if http_endpoint:
                endpoint_lines.append(f"HTTP: {http_endpoint}")
            if socks5_endpoint:
                endpoint_lines.append(f"SOCKS5: {socks5_endpoint}")
        else:
            if http_endpoint:
                endpoint_lines.append(f"HTTP: {http_endpoint}")
            if socks5_endpoint:
                endpoint_lines.append(f"SOCKS5: {socks5_endpoint}")
    else:
        endpoint_lines.append(t(lang, "proxy_endpoint_line").format(endpoint=endpoint))
    endpoint_block = "\n".join(endpoint_lines)
    return (
        f"{t(lang, 'proxy_order_details')}\n\n"
        f"{t(lang, 'proxy_provider_line').format(provider=provider)}\n"
        f"{endpoint_block}\n"
        f"{t(lang, 'proxy_username_line').format(username=username)}\n"
        f"{t(lang, 'proxy_password_line').format(password=password)}\n"
        f"{t(lang, 'proxy_expires_line').format(expires=expires)}\n"
        f"{t(lang, 'proxy_location_line').format(country=country, state=state, city=city)}\n"
        f"{t(lang, 'proxy_quality_line').format(decision=quality_decision, reason=quality_reason)}"
    )


def _quality_reason_text(lang: str, reason: str | None) -> str:
    code = str(reason or "").strip().lower()
    if code in {"missing_host", "invalid_host", "invalid_port"}:
        return t(lang, "proxy_quality_reason_invalid_endpoint")
    if code in {"localhost_host", "local_suffix_host", "non_global_ip"}:
        return t(lang, "proxy_quality_reason_private_network")
    if code in {"ip_unresolved", "gray_after_ipqs"}:
        return t(lang, "proxy_quality_reason_unresolved")
    if code in {"global_ip_needs_reputation", "global_ip_passed_placeholder"}:
        return t(lang, "proxy_quality_reason_reputation_pending")
    return str(reason or "quality_gate_failed")


def _provider_error_text(lang: str, payload: dict | None) -> str:
    raw = payload if isinstance(payload, dict) else {}
    code = str(raw.get("title") or raw.get("error") or "").strip().upper()
    details = str(raw.get("details") or raw.get("message") or "").strip()
    details_upper = details.upper()
    temporary_public_error = (
        "Provider is temporarily unavailable. Please try again after 30 minutes."
        if lang == "en"
        else "المزوّد غير متاح حاليا. حاول مرة أخرى بعد 30 دقيقة."
    )
    if code in {"AUTH_FAILED", "PERMISSION_DENIED", "INVALID_API_KEY", "UNAUTHORIZED", "FORBIDDEN"}:
        return "Authorization rejected by provider" if lang == "en" else "تم رفض صلاحية المزود (Authorization)"
    if code in {
        "INSUFFICIENT_BALANCE",
        "INSUFFICIENT_FUNDS",
        "BALANCE_LOW",
        "BALANCE_EXHAUSTED",
        "OUT_OF_STOCK",
        "TEMPORARY_FAILURE",
        "TEMPORARILY_UNAVAILABLE",
    }:
        return temporary_public_error
    if code in {"NOT_CONFIGURED", "UNKNOWN_PROVIDER"}:
        return "Provider unavailable" if lang == "en" else "المزود غير متاح حالياً"
    if code in {"QUALITY_FAIL", "QUALITY_GATE_FAILED"}:
        return "Proxy quality check failed" if lang == "en" else "فشل فحص جودة البروكسي"
    if any(
        marker in details_upper
        for marker in (
            "YOUR BALANCE IS INSUFFICIENT",
            "INSUFFICIENT BALANCE",
            "INSUFFICIENT_FUNDS",
            "PROVIDER_BALANCE_LOW",
            "BALANCE_LOW",
            "BALANCE IS INSUFFICIENT",
            "BALANCE TOO LOW",
            "LOW BALANCE",
            "OUT OF STOCK",
            "TEMPORARILY UNAVAILABLE",
            "API:",
            "TRY AGAIN LATER",
        )
    ):
        return temporary_public_error
    if code in {"REQUEST_ERROR", "TIMEOUT", "NETWORK_ERROR", "REFRESH_FAILED", "RECONFIGURE_FAILED"}:
        return "Provider request failed" if lang == "en" else "فشل الاتصال بمزود البروكسي"
    if details and "PROVIDER_BALANCE_LOW" not in details_upper:
        return details[:120]
    return provider_generic_error(lang)

async def _refresh_catalog_in_state(state: FSMContext):
    data = await state.get_data()
    category = _normalize_proxy_category(data.get("proxy_category"))
    all_offers = await get_proxy_catalog()
    category_scoped = _apply_proxy_category(all_offers, category)
    scoped = _filter_reconfigure_catalog(data, category_scoped)
    set_offers_cache(category_scoped)
    await state.update_data(proxy_catalog_all=all_offers, proxy_catalog=scoped, proxy_filtered=scoped)
    return scoped


async def _state_lang(state: FSMContext, user_id: int) -> tuple[dict, str]:
    data = await state.get_data()
    lang = str(data.get("proxy_lang") or "").strip()
    if lang:
        return data, lang
    user = await get_user(user_id)
    lang = (user or {}).get("language", "en")
    await state.update_data(proxy_lang=lang)
    data["proxy_lang"] = lang
    return data, lang


async def _render_proxy_type_menu(message: types.Message, state: FSMContext, lang: str):
    text = f"{t(lang, 'proxy_type_title')}\n\n{t(lang, 'proxy_type_hint')}"
    enabled_categories = _enabled_proxy_categories()
    type_msg_id = (await state.get_data()).get("proxy_type_msg")
    if type_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=int(type_msg_id),
                text=text,
                reply_markup=proxy_type_kb(
                    lang,
                    show_unlimited="unlimited" in enabled_categories,
                    show_consumptive="consumptive" in enabled_categories,
                ),
            )
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
        except Exception:
            pass
    sent = await message.answer(
        text,
        reply_markup=proxy_type_kb(
            lang,
            show_unlimited="unlimited" in enabled_categories,
            show_consumptive="consumptive" in enabled_categories,
        ),
    )
    await state.update_data(proxy_type_msg=sent.message_id)


async def _render_proxy_entry_menu(message: types.Message, state: FSMContext, lang: str):
    text = f"{t(lang, 'proxy_panel_title')}\n\n{t(lang, 'proxy_entry_hint')}"
    panel_msg_id = (await state.get_data()).get("proxy_panel_msg")
    if panel_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=int(panel_msg_id),
                text=text,
                reply_markup=proxy_entry_kb(lang),
            )
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
        except Exception:
            pass
    sent = await message.answer(text, reply_markup=proxy_entry_kb(lang))
    await state.update_data(proxy_panel_msg=sent.message_id)


async def _render_proxy_panel(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("proxy_lang", "en")
    category = _normalize_proxy_category(data.get("proxy_category"))
    if not category:
        await state.update_data(proxy_panel_msg=message.message_id if message.message_id else None)
        await _render_proxy_entry_menu(message, state, lang)
        return
    country = data.get("proxy_country")
    state_name = data.get("proxy_state")
    city_name = data.get("proxy_city")
    selected_location = data.get("proxy_location")
    filtered = _filter_proxy_offers(data)
    filtered = await _sort_offers_by_low_usage(filtered)
    filtered = _dedupe_proxy_offers(filtered)
    await state.update_data(proxy_filtered=filtered)
    require_state = _state_required(data)
    require_city = _city_required(data)
    location_ready = country and (not _location_mode(data) or bool(selected_location))
    if not country:
        hint = t(lang, "proxy_step_country")
    elif _location_mode(data) and not selected_location:
        hint = t(lang, "proxy_step_location")
    else:
        hint = t(lang, "proxy_step_list")
    if _proxy_manage_reconfigure_mode(data):
        text = f"{t(lang, 'proxy_panel_title')}\n\n{t(lang, 'proxy_reconfigure_hint')}\n\n{hint}"
    else:
        text = f"{t(lang, 'proxy_panel_title')}\n\n{hint}"
    if location_ready:
        text = (
            f"{t(lang, 'proxy_offers_title')}\n\n"
            f"{t(lang, 'proxy_least_used_hint')}\n"
            f"{_proxy_filters_text(lang, country, state_name, city_name)}"
        )
        kb = proxy_offers_kb(filtered, lang)
    else:
        kb = proxy_search_kb(
            lang,
            country=country,
            state=state_name,
            city=city_name,
            require_state=require_state,
            require_city=require_city,
            can_list=_proxy_selection_ready(data),
            quick_country_options=_quick_country_options(data),
            quick_location_options=_quick_location_options(data),
        )

    panel_msg_id = data.get("proxy_panel_msg")
    if panel_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=int(panel_msg_id),
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
    await state.update_data(proxy_panel_msg=sent.message_id)


async def _load_user_proxy_order(raw_id: str, user_id: int) -> tuple[ObjectId | None, dict | None]:
    try:
        order_oid = ObjectId(raw_id)
    except Exception:
        return None, None
    order = await get_order(order_oid)
    if not order or int(order.get("user_id") or 0) != int(user_id):
        return None, None
    return order_oid, order


@router.callback_query(lambda c: (not PROXY_PROVIDERS) and c.data and str(c.data).startswith("proxy:"))
async def proxy_disabled_callback_guard(callback: types.CallbackQuery, state: FSMContext):
    _data, lang = await _state_lang(state, int(callback.from_user.id))
    await state.clear()
    if callback.message:
        await _safe_edit_text(callback.message, _proxy_service_disabled_text(lang))
    await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)


@router.message(lambda m: (not PROXY_PROVIDERS) and m.text and str(m.text).startswith("/proxy_"))
async def proxy_disabled_command_guard(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    await state.clear()
    bot_id = (await message.bot.get_me()).id
    await message.answer(_proxy_service_disabled_text(lang), reply_markup=await menu_for_current_bot(lang, bot_id))


@router.message(lambda msg: _is_btn(msg.text, "btn_proxies"))
async def open_proxy_menu(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    try:
        await message.answer(t(lang, "keyboard_cleanup_placeholder"), reply_markup=ReplyKeyboardRemove())
    except Exception:
        pass

    if not PROXY_PROVIDERS:
        await state.clear()
        bot_id = (await message.bot.get_me()).id
        await message.answer(_proxy_service_disabled_text(lang), reply_markup=await menu_for_current_bot(lang, bot_id))
        return

    await state.clear()
    await state.update_data(
        proxy_lang=lang,
        proxy_category=None,
        proxy_catalog_all=[],
        proxy_catalog=[],
        proxy_country=None,
        proxy_state=None,
        proxy_city=None,
        proxy_location=None,
        proxy_provider=None,
        proxy_period=None,
        proxy_filtered=[],
        proxy_type_msg=None,
        proxy_panel_msg=None,
    )
    await _render_proxy_entry_menu(message, state, lang)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:buy")
async def proxy_buy_menu(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    await state.update_data(
        proxy_category=_normalize_proxy_category(data.get("proxy_category")),
        proxy_country=None,
        proxy_state=None,
        proxy_city=None,
        proxy_location=None,
        proxy_protocol=None,
        proxy_provider=None,
        proxy_period=None,
        proxy_duration_value=None,
        proxy_duration_label=None,
        proxy_filtered=[],
        proxy_panel_msg=callback.message.message_id,
        proxy_type_msg=callback.message.message_id,
    )
    await _render_proxy_type_menu(callback.message, state, lang)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:type_menu")
async def proxy_type_menu(callback: types.CallbackQuery, state: FSMContext):
    return await proxy_buy_menu(callback, state)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:type:"))
async def proxy_select_type(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    _data, lang = await _state_lang(state, int(callback.from_user.id))
    category = _normalize_proxy_category(callback.data.split(":", 2)[2])
    if category not in set(_enabled_proxy_categories()):
        return await callback.answer(t(lang, "proxy_invalid_type"), show_alert=True)

    await state.update_data(
        proxy_category=category,
        proxy_country=None,
        proxy_state=None,
        proxy_city=None,
        proxy_location=None,
        proxy_protocol=None,
        proxy_provider=None,
        proxy_period=None,
        proxy_duration_value=None,
        proxy_duration_label=None,
    )
    await _safe_edit_text(callback.message, t(lang, "proxy_loading"))
    loading_stop = None
    loading_task = None
    if callback.message:
        loading_stop, loading_task = _start_loading_text_animator(
            callback.message.bot,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            base_text=t(lang, "proxy_loading"),
        )
    try:
        offers = await _refresh_catalog_in_state(state)
    finally:
        await _stop_loading_text_animator(loading_stop, loading_task)
    if not offers:
        await _safe_edit_text(
            callback.message,
            f"{t(lang, 'proxy_no_catalog')}\n\n{t(lang, 'proxy_type_selected').format(proxy_type=_proxy_type_label(lang, category))}",
            reply_markup=proxy_search_kb(lang),
        )
        await state.update_data(proxy_panel_msg=callback.message.message_id, proxy_type_msg=callback.message.message_id)
        await state.set_state(ProxyFlow.menu)
        return

    await state.update_data(proxy_panel_msg=callback.message.message_id, proxy_type_msg=callback.message.message_id)
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.message(F.text.startswith("/proxy_country_"))
async def select_proxy_country(message: types.Message, state: FSMContext):
    token = message.text.replace("/proxy_country_", "", 1).strip()
    country = decode_token(token)
    await state.update_data(
        proxy_country=country or None,
        proxy_state=None,
        proxy_city=None,
        proxy_location=None,
        proxy_protocol=None,
        proxy_provider=None,
        proxy_period=None,
        proxy_duration_value=None,
        proxy_duration_label=None,
    )
    try:
        await message.delete()
    except Exception:
        pass
    await _render_proxy_panel(message, state)
    await state.set_state(ProxyFlow.menu)


@router.message(F.text.startswith("/proxy_state_"))
async def select_proxy_state(message: types.Message, state: FSMContext):
    payload = message.text.replace("/proxy_state_", "", 1).strip()
    parts = payload.split("~", 1)
    if len(parts) != 2:
        return
    country = decode_token(parts[0])
    location_name = decode_token(parts[1])
    data = await state.get_data()
    catalog = data.get("proxy_catalog") or get_offers_cache()
    country_offers = filter_offers(catalog, country=country or None)

    state_values = {
        str(row.get("state") or "").strip()
        for row in country_offers
        if str(row.get("state") or "").strip() and str(row.get("state") or "").strip().lower() != "any"
    }
    city_values = {
        str(row.get("city") or "").strip()
        for row in country_offers
        if str(row.get("city") or "").strip() and str(row.get("city") or "").strip().lower() != "any"
    }

    selected_state = None
    selected_city = None
    if location_name:
        lowered = location_name.lower()
        for value in state_values:
            if value.lower() == lowered:
                selected_state = value
                break
        if selected_state is None:
            for value in city_values:
                if value.lower() == lowered:
                    selected_city = value
                    break

    await state.update_data(
        proxy_country=country or None,
        proxy_state=selected_state,
        proxy_city=selected_city,
        proxy_location=location_name or None,
        proxy_protocol=None,
        proxy_provider=None,
        proxy_period=None,
        proxy_duration_value=None,
        proxy_duration_label=None,
    )
    try:
        await message.delete()
    except Exception:
        pass
    await _render_proxy_panel(message, state)
    await state.set_state(ProxyFlow.menu)


@router.message(F.text.startswith("/proxy_city_"))
async def select_proxy_city(message: types.Message, state: FSMContext):
    payload = message.text.replace("/proxy_city_", "", 1).strip()
    parts = payload.split("~")
    if len(parts) not in {2, 3}:
        return
    country = decode_token(parts[0])
    if len(parts) == 3:
        state_name = decode_token(parts[1])
        city = decode_token(parts[2])
    else:
        state_name = None
        city = decode_token(parts[1])
    await state.update_data(
        proxy_country=country or None,
        proxy_state=state_name or None,
        proxy_city=city or None,
        proxy_location=city or state_name or None,
        proxy_protocol=None,
        proxy_provider=None,
        proxy_period=None,
        proxy_duration_value=None,
        proxy_duration_label=None,
    )
    try:
        await message.delete()
    except Exception:
        pass
    await _render_proxy_panel(message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:quick_country:"))
async def proxy_quick_country(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    token = callback.data.split(":", 2)[2]
    country = decode_token(token)
    await state.update_data(
        proxy_country=country or None,
        proxy_state=None,
        proxy_city=None,
        proxy_location=None,
        proxy_protocol=None,
        proxy_provider=None,
        proxy_period=None,
        proxy_duration_value=None,
        proxy_duration_label=None,
    )
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:quick_state:"))
async def proxy_quick_state(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    parts = callback.data.split(":", 3)
    if len(parts) != 4:
        return
    country = decode_token(parts[2])
    state_name = decode_token(parts[3])
    await state.update_data(
        proxy_country=country or None,
        proxy_state=state_name or None,
        proxy_city=None,
        proxy_location=state_name or None,
        proxy_protocol=None,
        proxy_provider=None,
        proxy_period=None,
        proxy_duration_value=None,
        proxy_duration_label=None,
    )
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:quick_city:"))
async def proxy_quick_city(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    parts = callback.data.split(":", 3)
    if len(parts) != 4:
        return
    country = decode_token(parts[2])
    city = decode_token(parts[3])
    await state.update_data(
        proxy_country=country or None,
        proxy_state=None,
        proxy_city=city or None,
        proxy_location=city or None,
        proxy_protocol=None,
        proxy_provider=None,
        proxy_period=None,
        proxy_duration_value=None,
        proxy_duration_label=None,
    )
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:refresh_catalog")
async def proxy_refresh_catalog(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    category = _normalize_proxy_category(data.get("proxy_category"))
    if not category:
        await state.update_data(proxy_panel_msg=callback.message.message_id)
        await _render_proxy_entry_menu(callback.message, state, lang)
        await state.set_state(ProxyFlow.menu)
        return
    await _safe_edit_text(callback.message, t(lang, "proxy_loading"))
    loading_stop = None
    loading_task = None
    if callback.message:
        loading_stop, loading_task = _start_loading_text_animator(
            callback.message.bot,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            base_text=t(lang, "proxy_loading"),
        )
    try:
        offers = await _refresh_catalog_in_state(state)
    finally:
        await _stop_loading_text_animator(loading_stop, loading_task)
    if not offers:
        await _safe_edit_text(
            callback.message,
            t(lang, "proxy_no_catalog"),
            reply_markup=proxy_entry_kb(lang),
        )
        await state.set_state(ProxyFlow.menu)
        return
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:search")
async def proxy_back_to_search(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    category = _normalize_proxy_category(data.get("proxy_category"))
    if not category:
        await state.update_data(proxy_panel_msg=callback.message.message_id)
        await _render_proxy_entry_menu(callback.message, state, lang)
        await state.set_state(ProxyFlow.menu)
        return
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:set_provider:"))
async def proxy_set_provider(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    token = callback.data.split(":", 2)[2]
    provider_code = decode_token(token).strip()
    providers = _available_proxy_providers(data)
    if provider_code not in providers:
        return await callback.answer(t(lang, "proxy_invalid_selection"), show_alert=True)
    await state.update_data(proxy_provider=provider_code, proxy_period=None, proxy_duration_value=None, proxy_duration_label=None)
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:set_protocol:"))
async def proxy_set_protocol(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    token = callback.data.split(":", 2)[2]
    protocol = decode_token(token).strip().lower()
    protocols = _available_proxy_protocols(data)
    if protocol not in protocols:
        return await callback.answer(t(lang, "proxy_invalid_selection"), show_alert=True)
    await state.update_data(proxy_protocol=protocol, proxy_provider=None, proxy_period=None, proxy_duration_value=None, proxy_duration_label=None)
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:set_period:"))
async def proxy_set_period(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    token = callback.data.split(":", 2)[2]
    period = decode_token(token).strip()
    periods = _available_proxy_periods(data)
    if period not in periods:
        return await callback.answer(t(lang, "proxy_invalid_selection"), show_alert=True)
    await state.update_data(proxy_period=period, proxy_duration_value=None, proxy_duration_label=None)
    updated = await state.get_data()
    filtered = _filter_proxy_offers(updated)
    filtered = await _sort_offers_by_low_usage(filtered)
    await state.update_data(proxy_filtered=filtered)

    if not filtered:
        await _safe_edit_text(
            callback.message,
            t(lang, "proxy_no_filtered_offers"),
            reply_markup=proxy_search_kb(
                lang,
                country=updated.get("proxy_country"),
                state=updated.get("proxy_state"),
                city=updated.get("proxy_city"),
                protocol=updated.get("proxy_protocol"),
                provider=updated.get("proxy_provider"),
                period=updated.get("proxy_period"),
                duration=None,
                require_state=_state_required(updated),
                require_city=_city_required(updated),
                can_list=False,
                protocol_options=_available_proxy_protocol_options(updated, lang),
                provider_options=_available_proxy_provider_options(updated),
                period_options=_available_proxy_period_options(updated),
                duration_options=[],
                quick_country_options=_quick_country_options(updated),
                quick_location_options=_quick_location_options(updated),
            ),
        )
        await state.set_state(ProxyFlow.menu)
        return

    text = (
        f"{t(lang, 'proxy_offers_title')}\n\n"
        f"{t(lang, 'proxy_least_used_hint')}\n"
        f"{_proxy_selection_text(lang, updated)}"
    )
    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=proxy_offers_kb(filtered, lang, protocol=updated.get("proxy_protocol")),
    )
    await state.set_state(ProxyFlow.offers)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:set_duration:"))
async def proxy_set_duration(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    token = callback.data.split(":", 2)[2]
    duration_value = decode_token(token).strip()
    options = _duration_option_map(data)
    selected = options.get(duration_value)
    if not selected:
        return await callback.answer(t(lang, "proxy_invalid_selection"), show_alert=True)
    await state.update_data(proxy_duration_value=duration_value, proxy_duration_label=selected[0])
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:list")
async def proxy_list_offers(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    category = _normalize_proxy_category(data.get("proxy_category"))
    if not category:
        await state.update_data(proxy_panel_msg=callback.message.message_id)
        await _render_proxy_entry_menu(callback.message, state, lang)
        await state.set_state(ProxyFlow.menu)
        return

    if not _proxy_selection_ready(data):
        return await callback.answer(t(lang, "proxy_complete_filters_first"), show_alert=True)
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.offers)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:offer:"))
async def proxy_offer_details(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    filtered = data.get("proxy_filtered") or []
    try:
        idx = int(callback.data.split(":", 2)[2])
    except Exception:
        return await callback.answer(t(lang, "proxy_invalid_selection"), show_alert=True)
    if idx < 0 or idx >= len(filtered):
        return await callback.answer(t(lang, "proxy_invalid_selection"), show_alert=True)

    offer = filtered[idx]
    await state.update_data(proxy_selected_offer=offer, proxy_duration_value=None, proxy_duration_label=None)
    if _proxy_manage_reconfigure_mode(data):
        text = _proxy_offer_text(
            lang,
            offer,
            data.get("proxy_protocol"),
            include_duration=False,
            include_prices=True,
        )
        await _safe_edit_text(
            callback.message,
            text,
            reply_markup=proxy_offer_actions_kb(
                lang,
                confirm_callback="proxy:reconfigure:confirm",
                confirm_text_key="proxy_apply_changes",
            ),
        )
        await state.set_state(ProxyFlow.offers)
        return
    text = _proxy_offer_text(
        lang,
        offer,
        data.get("proxy_protocol"),
        include_duration=False,
        include_prices=False,
    ) + "\n\n" + _proxy_duration_hint(lang)
    await _safe_edit_text(callback.message, text, reply_markup=proxy_offer_duration_kb(_available_proxy_duration_options(data), lang))
    await state.set_state(ProxyFlow.offers)
    return
    base_price = float(offer.get("base_price") or 0.0)
    sale_price = float(offer.get("price") or 0.0)
    success_rate = float(offer.get("success_rate") or 100.0)
    usage_count = int(offer.get("usage_count") or 0)
    billing = str(offer.get("billing_type") or "").strip().lower()
    if str(lang or "").lower().startswith("ar"):
        quality_note = "ملاحظة: سيتم تنفيذ فحص جودة تلقائي قبل تأكيد الطلب."
        billing_note = "نوع الفوترة: استهلاكي (Bandwidth)." if billing == "bandwidth" else "نوع الفوترة: فترة ثابتة."
    else:
        quality_note = "Note: an automatic quality check runs before order confirmation."
        billing_note = "Billing mode: consumptive (bandwidth)." if billing == "bandwidth" else "Billing mode: fixed period."
    text = (
        f"{t(lang, 'proxy_offer_details')}\n\n"
        f"{t(lang, 'proxy_provider_line').format(provider=provider_public_id(offer.get('provider')))}\n"
        f"{t(lang, 'proxy_title_line').format(title=offer.get('title'))}\n"
        f"{t(lang, 'proxy_country_line').format(country=offer.get('country'))}\n"
        f"{t(lang, 'proxy_state_line').format(state=offer.get('state'))}\n"
        f"{t(lang, 'proxy_city_line').format(city=offer.get('city'))}\n"
        f"{t(lang, 'proxy_period_line').format(period=offer.get('period'))}\n"
        f"{t(lang, 'proxy_duration_line').format(duration=str(offer.get('duration_label') or data.get('proxy_duration_label') or '-'))}\n"
        f"{t(lang, 'proxy_billing_line').format(billing=offer.get('billing_type'))}\n"
        f"{t(lang, 'proxy_usage_count')}: {usage_count}\n"
        f"{t(lang, 'success_rate_short')}: {int(success_rate) if success_rate.is_integer() else f'{success_rate:.1f}'}%\n"
        f"{t(lang, 'proxy_price_line').format(price=sale_price)}\n\n"
        f"{billing_note}\n"
        f"{quality_note}"
    )
    await _safe_edit_text(callback.message, text, reply_markup=proxy_offer_actions_kb(lang))
    await state.set_state(ProxyFlow.offers)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:offer_duration:"))
async def proxy_offer_set_duration(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    base_offer = data.get("proxy_selected_offer") or {}
    if not base_offer:
        return await callback.answer(t(lang, "proxy_invalid_selection"), show_alert=True)
    token = callback.data.split(":", 2)[2]
    duration_value = decode_token(token).strip()
    options = _duration_option_map(data)
    selected = options.get(duration_value)
    if not selected:
        return await callback.answer(t(lang, "proxy_invalid_selection"), show_alert=True)
    await state.update_data(proxy_duration_value=duration_value, proxy_duration_label=selected[0])
    priced_data = await state.get_data()
    offer = _single_offer_with_duration_price(priced_data, base_offer)
    await state.update_data(proxy_selected_offer=offer)
    text = _proxy_offer_text(
        lang,
        offer,
        data.get("proxy_protocol"),
        include_duration=True,
        duration_label=selected[0],
        include_prices=True,
    )
    await _safe_edit_text(callback.message, text, reply_markup=proxy_offer_actions_kb(lang))
    await state.set_state(ProxyFlow.offers)


async def _execute_proxy_purchase(message: types.Message, state: FSMContext, *, user_id: int, lang: str, offer: dict) -> None:
    if not PROXY_PROVIDERS:
        bot_id = (await message.bot.get_me()).id
        await message.answer(_proxy_service_disabled_text(lang), reply_markup=await menu_for_current_bot(lang, bot_id))
        await state.clear()
        return

    bot_id = (await message.bot.get_me()).id
    reseller_id = await _resolve_user_reseller(user_id, bot_id)
    sale_price = float(offer.get("price") or 0.0)
    base_price = float(offer.get("base_price") if offer.get("base_price") is not None else sale_price)
    if sale_price <= 0 or base_price < 0:
        await message.answer(t(lang, "proxy_invalid_price"))
        return

    order = await create_order(
        user_id=user_id,
        reseller_id=reseller_id,
        service_id=f"proxy:{offer.get('provider')}:{offer.get('offer_id')}",
        selling_price=sale_price,
        base_price=base_price,
    )
    order_id = order["_id"]

    ok, msg = await FinancialManager.process_core_purchase(
        user_id=user_id,
        order_id=str(order_id),
        sale_price=sale_price,
        cost_price=base_price,
        reseller_id=reseller_id,
    )
    if not ok:
        await update_order_status(order_id, "failed")
        await message.answer(finance_error_public_text(lang, str(msg)))
        return

    processing = await message.answer(t(lang, "proxy_processing"))
    refunded = False
    try:
        result = await rent_proxy_offer(offer)
        if not result.get("success"):
            logger.warning(
                "proxy rent provider failure user_id=%s provider=%s offer_id=%s raw=%s",
                user_id,
                offer.get("provider"),
                offer.get("offer_id"),
                result.get("raw"),
            )
            await FinancialManager.refund_core_purchase(
                user_id=user_id,
                order_id=str(order_id),
                sale_price=sale_price,
                cost_price=base_price,
                reseller_id=reseller_id,
            )
            refunded = True
            await update_order_status(order_id, "failed")
            await _safe_edit_text(
                processing,
                t(lang, "proxy_rent_failed").format(error=_provider_error_text(lang, result.get("raw")))
            )
            return

        endpoint = str(result.get("endpoint") or "")
        http_endpoint = str(result.get("http_endpoint") or "").strip()
        socks5_endpoint = str(result.get("socks5_endpoint") or "").strip()
        quality = await verify_proxy_offer_delivery(http_endpoint or endpoint)
        if not quality.get("allowed"):
            quality_reason = str(quality.get("reason") or "quality_gate_failed")
            logger.warning(
                "proxy quality gate blocked user_id=%s order_id=%s provider=%s endpoint=%s decision=%s reason=%s",
                user_id,
                order_id,
                offer.get("provider"),
                http_endpoint or endpoint,
                quality.get("decision"),
                quality_reason,
            )
            await FinancialManager.refund_core_purchase(
                user_id=user_id,
                order_id=str(order_id),
                sale_price=sale_price,
                cost_price=base_price,
                reseller_id=reseller_id,
            )
            refunded = True
            await update_order_details(
                order_id,
                {
                    "provider": offer.get("provider"),
                    "provider_order_id": result.get("order_id"),
                    "proxy_endpoint": endpoint,
                    "proxy_http_endpoint": http_endpoint or None,
                    "proxy_socks5_endpoint": socks5_endpoint or None,
                    "proxy_quality_attempts": [quality],
                    "proxy_last_quality": quality,
                },
            )
            await update_order_status(order_id, "failed")
            await _safe_edit_text(
                processing,
                t(lang, "proxy_quality_failed").format(reason=_quality_reason_text(lang, quality_reason)),
            )
            return
    except Exception as exc:
        if not refunded:
            await FinancialManager.refund_core_purchase(
                user_id=user_id,
                order_id=str(order_id),
                sale_price=sale_price,
                cost_price=base_price,
                reseller_id=reseller_id,
            )
        await update_order_status(order_id, "failed")
        logger.exception("Proxy rent failed for user %s order %s: %s", user_id, order_id, exc)
        await _safe_edit_text(
            processing,
            t(lang, "proxy_rent_failed").format(error=_provider_error_text(lang, {"title": "REQUEST_ERROR", "details": str(exc)}))
        )
        return

    await update_order_details(
        order_id,
        {
            "provider": offer.get("provider"),
            "provider_order_id": result.get("order_id"),
            "proxy_provider_order_id": result.get("order_id"),
            "proxy_provider_start_port": result.get("start_port"),
            "proxy_start_port": result.get("start_port"),
            "proxy_endpoint": endpoint or "-",
            "proxy_http_endpoint": http_endpoint or None,
            "proxy_socks5_endpoint": socks5_endpoint or None,
            "proxy_username": result.get("username") or offer.get("username"),
            "proxy_password": result.get("password") or offer.get("password"),
            "proxy_expires_at": result.get("expires_at"),
            "proxy_location": {
                "country": offer.get("country"),
                "state": offer.get("state"),
                "city": offer.get("city"),
            },
            "proxy_offer_snapshot": {
                "provider": offer.get("provider"),
                "offer_id": offer.get("offer_id"),
                "title": offer.get("title"),
                "country": offer.get("country"),
                "state": offer.get("state"),
                "city": offer.get("city"),
                "period": offer.get("period"),
                "duration_value": offer.get("duration_value"),
                "duration_label": offer.get("duration_label"),
                "billing_type": offer.get("billing_type"),
            },
            "proxy_quality_attempts": [quality],
            "proxy_last_quality": quality,
            "proxy_first_check_free_used": False,
            "proxy_change_check_count": 0,
            "proxy_change_history": [],
        },
    )
    await update_order_status(order_id, "success")

    if str(lang).lower().startswith("ar"):
        lines = [
            "✅ تم شراء البروكسي بنجاح",
            "",
            f"🌐 المزوّد: {provider_public_id(offer.get('provider'))}",
            f"🧾 رقم الطلب: {result.get('order_id') or '-'}",
        ]
        if http_endpoint:
            lines.append(f"◽️ HTTP: {http_endpoint}")
        if socks5_endpoint:
            lines.append(f"◽️ SOCKS5: {socks5_endpoint}")
        if not http_endpoint and not socks5_endpoint:
            lines.append(f"🔌 العنوان: {endpoint or '-'}")
        lines.extend(
            [
                f"👤 اسم المستخدم: {result.get('username') or offer.get('username') or '-'}",
                f"🔐 كلمة المرور: {result.get('password') or offer.get('password') or '-'}",
                f"⏳ تاريخ الانتهاء: {result.get('expires_at') or '-'}",
            ]
        )
        text = "\n".join(lines)
    else:
        lines = [
            "✅ Proxy Purchase Completed",
            "",
            f"🌐 Provider: {provider_public_id(offer.get('provider'))}",
            f"🧾 Order: {result.get('order_id') or '-'}",
        ]
        if http_endpoint:
            lines.append(f"◽️ HTTP: {http_endpoint}")
        if socks5_endpoint:
            lines.append(f"◽️ SOCKS5: {socks5_endpoint}")
        if not http_endpoint and not socks5_endpoint:
            lines.append(f"🔌 Endpoint: {endpoint or '-'}")
        lines.extend(
            [
                f"👤 Username: {result.get('username') or offer.get('username') or '-'}",
                f"🔐 Password: {result.get('password') or offer.get('password') or '-'}",
                f"⏳ Expires: {result.get('expires_at') or '-'}",
            ]
        )
        text = "\n".join(lines)
    if str(quality.get("decision") or "").lower().startswith("gray"):
        text = f"{text}\n\n{t(lang, 'proxy_quality_gray_note')}"

    await _safe_edit_text(
        processing,
        text,
        reply_markup=proxy_order_actions_kb(str(order_id), lang, can_reconfigure=str(offer.get("provider") or "").strip().lower() == "4g"),
    )
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:rent:confirm")
async def proxy_rent_confirm(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    offer = data.get("proxy_selected_offer") or {}
    if not offer:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    provider_code = str(offer.get("provider") or "").lower()
    if provider_code == "4g":
        username = await reserve_available_4g_username()
        if not username:
            return await callback.answer("No available username could be reserved right now.", show_alert=True)
        offer["username"] = username
        await state.update_data(
            proxy_selected_offer=offer,
            proxy_custom_username=username,
            proxy_custom_password=None,
        )
        await _safe_edit_text(
            callback.message,
            _proxy_password_prompt_text(lang, username),
            reply_markup=proxy_password_input_kb(lang),
        )
        await state.set_state(ProxyFlow.waiting_password)
        return
    await _execute_proxy_purchase(callback.message, state, user_id=int(callback.from_user.id), lang=lang, offer=offer)


@router.callback_query(F.data == "proxy:reconfigure:confirm")
async def proxy_reconfigure_confirm(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    raw_order_id = str(data.get("proxy_manage_order_id") or "").strip()
    offer = data.get("proxy_selected_offer") or {}
    if not raw_order_id or not offer:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    order_oid, order = await _load_user_proxy_order(raw_order_id, callback.from_user.id)
    if not order_oid or not order:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    if not _proxy_order_can_reconfigure(order):
        return await callback.answer(t(lang, "proxy_reconfigure_unavailable"), show_alert=True)

    await _safe_edit_text(callback.message, t(lang, "proxy_reconfigure_loading"))
    refreshed = await reconfigure_proxy_order(order, offer, with_check=True)
    if not refreshed.get("success"):
        logger.warning(
            "proxy reconfigure failed user_id=%s order_id=%s provider=%s raw=%s quality=%s",
            callback.from_user.id,
            order_oid,
            order.get("provider"),
            refreshed.get("raw"),
            refreshed.get("quality"),
        )
        return await _safe_edit_text(
            callback.message,
            t(lang, "proxy_change_failed").format(error=_provider_error_text(lang, refreshed.get("raw"))),
            reply_markup=proxy_order_actions_kb(str(order_oid), lang, can_reconfigure=True),
        )

    now = _now_utc()
    event = {
        "type": "reconfigure",
        "ts": now,
        "success": True,
        "charged": 0.0,
        "quality": refreshed.get("quality"),
        "protocol": offer.get("protocol"),
        "country": offer.get("country"),
        "state": offer.get("state"),
        "city": offer.get("city"),
    }
    history = _append_proxy_history(order, event)
    await update_order_details(
        order_oid,
        {
            "proxy_provider_order_id": refreshed.get("order_id") or order.get("proxy_provider_order_id"),
            "provider_order_id": refreshed.get("order_id") or order.get("provider_order_id"),
            "proxy_endpoint": refreshed.get("endpoint") or order.get("proxy_endpoint"),
            "proxy_http_endpoint": refreshed.get("http_endpoint") or order.get("proxy_http_endpoint"),
            "proxy_socks5_endpoint": refreshed.get("socks5_endpoint") or order.get("proxy_socks5_endpoint"),
            "proxy_username": refreshed.get("username") or order.get("proxy_username"),
            "proxy_password": refreshed.get("password") or order.get("proxy_password"),
            "proxy_expires_at": refreshed.get("expires_at") or order.get("proxy_expires_at"),
            "proxy_location": {
                "country": offer.get("country"),
                "state": offer.get("state"),
                "city": offer.get("city"),
            },
            "proxy_offer_snapshot": {
                "provider": offer.get("provider"),
                "offer_id": offer.get("offer_id"),
                "title": offer.get("title"),
                "country": offer.get("country"),
                "state": offer.get("state"),
                "city": offer.get("city"),
                "period": offer.get("period"),
                "duration_value": offer.get("duration_value"),
                "duration_label": offer.get("duration_label"),
                "billing_type": offer.get("billing_type"),
            },
            "proxy_last_quality": refreshed.get("quality") or order.get("proxy_last_quality"),
            "proxy_change_history": history,
        },
    )
    await state.update_data(
        proxy_manage_order_id=None,
        proxy_manage_provider=None,
        proxy_manage_package_id=None,
        proxy_selected_offer=None,
        proxy_duration_value=None,
        proxy_duration_label=None,
    )
    latest = await get_order(order_oid)
    await _safe_edit_text(
        callback.message,
        f"{t(lang, 'proxy_reconfigure_success')}\n\n{_order_detail_text(lang, latest or order)}",
        reply_markup=proxy_order_actions_kb(str(order_oid), lang, can_reconfigure=True),
    )


@router.callback_query(F.data == "proxy:password_back")
async def proxy_password_back(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    await state.update_data(proxy_custom_username=None, proxy_custom_password=None)
    text = _proxy_offer_text(
        lang,
        data.get("proxy_selected_offer") or {},
        data.get("proxy_protocol"),
        include_duration=False,
        include_prices=False,
    ) + "\n\n" + _proxy_duration_hint(lang)
    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=proxy_offer_duration_kb(_available_proxy_duration_options(data), lang),
    )
    await state.set_state(ProxyFlow.offers)


@router.message(ProxyFlow.waiting_password)
async def proxy_receive_password(message: types.Message, state: FSMContext):
    data, lang = await _state_lang(state, int(message.from_user.id))
    offer = dict(data.get("proxy_selected_offer") or {})
    username = str(data.get("proxy_custom_username") or "").strip()
    password = str(message.text or "").strip()
    if not offer or not username:
        await state.set_state(ProxyFlow.menu)
        await message.answer(t(lang, "invalid_order_info"))
        return
    if not _valid_proxy_password(password):
        if str(lang).lower().startswith("ar"):
            await message.answer("كلمة المرور غير صالحة. يجب أن تكون بين 4 و32 حرفًا وبدون مسافات.")
        else:
            await message.answer("Invalid password. Use 4-32 characters without spaces.")
        return
    offer["username"] = username
    offer["password"] = password
    await state.update_data(proxy_selected_offer=offer, proxy_custom_password=password)
    await _execute_proxy_purchase(message, state, user_id=int(message.from_user.id), lang=lang, offer=offer)


@router.callback_query(F.data == "proxy:my_orders")
async def proxy_my_orders(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    if not PROXY_PROVIDERS:
        return await callback.answer(_proxy_service_disabled_text(lang), show_alert=True)
    rows = await list_user_proxy_orders(callback.from_user.id, limit=20)
    if not rows:
        await _safe_edit_text(
            callback.message,
            t(lang, "proxy_my_orders_empty"),
            reply_markup=proxy_entry_kb(lang) if not data.get("proxy_category") else proxy_search_kb(
                lang,
                country=data.get("proxy_country"),
                state=data.get("proxy_state"),
                city=data.get("proxy_city"),
                protocol=data.get("proxy_protocol"),
                provider=data.get("proxy_provider"),
                period=data.get("proxy_period"),
                duration=data.get("proxy_duration_value"),
                require_state=_state_required(data),
                require_city=_city_required(data),
                can_list=_proxy_selection_ready(data),
                protocol_options=_available_proxy_protocol_options(data, lang),
                provider_options=_available_proxy_provider_options(data),
                period_options=_available_proxy_period_options(data),
                duration_options=_available_proxy_duration_options(data),
                quick_country_options=_quick_country_options(data),
                quick_location_options=_quick_location_options(data),
            ),
        )
        return
    text = t(lang, "proxy_my_orders_title").format(total=len(rows))
    await _safe_edit_text(callback.message, text, reply_markup=proxy_my_orders_kb(rows, lang))


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:order:open:"))
async def proxy_open_order(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    _data, lang = await _state_lang(state, int(callback.from_user.id))
    raw_id = callback.data.split(":", 3)[3]
    _oid, order = await _load_user_proxy_order(raw_id, callback.from_user.id)
    if not order:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    await _safe_edit_text(
        callback.message,
        _order_detail_text(lang, order),
        reply_markup=proxy_order_actions_kb(raw_id, lang, can_reconfigure=_proxy_order_can_reconfigure(order)),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:order:reconfigure:"))
async def proxy_order_reconfigure_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    _data, lang = await _state_lang(state, int(callback.from_user.id))
    raw_id = callback.data.split(":", 3)[3]
    order_oid, order = await _load_user_proxy_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    if not _proxy_order_can_reconfigure(order):
        return await callback.answer(t(lang, "proxy_reconfigure_unavailable"), show_alert=True)

    snapshot = order.get("proxy_offer_snapshot") if isinstance(order.get("proxy_offer_snapshot"), dict) else {}
    billing_type = str(snapshot.get("billing_type") or "").strip().lower()
    category = "consumptive" if billing_type == "bandwidth" else "unlimited"
    package_id = _package_id_from_offer_id(snapshot.get("offer_id"))

    await state.update_data(
        proxy_manage_order_id=str(order_oid),
        proxy_manage_provider="4g",
        proxy_manage_package_id=package_id,
        proxy_category=category,
        proxy_country=None,
        proxy_state=None,
        proxy_city=None,
        proxy_protocol=None,
        proxy_provider=None,
        proxy_period=None,
        proxy_duration_value=None,
        proxy_duration_label=None,
        proxy_selected_offer=None,
        proxy_filtered=[],
        proxy_panel_msg=callback.message.message_id,
        proxy_type_msg=callback.message.message_id,
    )
    await _safe_edit_text(callback.message, t(lang, "proxy_reconfigure_loading"))
    offers = await _refresh_catalog_in_state(state)
    if not offers:
        return await _safe_edit_text(
            callback.message,
            t(lang, "proxy_reconfigure_unavailable"),
            reply_markup=proxy_order_actions_kb(str(order_oid), lang, can_reconfigure=True),
        )
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:order:change:"))
async def proxy_order_change_only(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    _data, lang = await _state_lang(state, int(callback.from_user.id))
    raw_id = callback.data.split(":", 3)[3]
    order_oid, order = await _load_user_proxy_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    cooldown_minutes = proxy_change_only_cooldown_minutes()
    last_change = _parse_dt(order.get("proxy_change_only_last_at"))
    now = _now_utc()
    if last_change:
        next_allowed = last_change + timedelta(minutes=cooldown_minutes)
        if now < next_allowed:
            remaining = int((next_allowed - now).total_seconds())
            mins = max(1, remaining // 60)
            return await callback.answer(
                t(lang, "proxy_change_cooldown").format(minutes=mins),
                show_alert=True,
            )

    await _safe_edit_text(callback.message, t(lang, "proxy_change_processing"))
    refreshed = await refresh_proxy_order(order, with_check=False, max_attempts=1)
    if not refreshed.get("success"):
        logger.warning(
            "proxy change-only failed user_id=%s order_id=%s provider=%s raw=%s",
            callback.from_user.id,
            order_oid,
            order.get("provider"),
            refreshed.get("raw"),
        )
        return await _safe_edit_text(
            callback.message,
            t(lang, "proxy_change_failed").format(error=_provider_error_text(lang, refreshed.get("raw"))),
            reply_markup=proxy_order_actions_kb(str(order_oid), lang, can_reconfigure=_proxy_order_can_reconfigure(order)),
        )

    event = {
        "type": "change_only",
        "ts": now,
        "success": True,
        "charged": 0.0,
        "attempts": int(refreshed.get("attempts") or 1),
    }
    history = _append_proxy_history(order, event)
    await update_order_details(
        order_oid,
        {
            "proxy_provider_order_id": refreshed.get("order_id") or order.get("proxy_provider_order_id"),
            "provider_order_id": refreshed.get("order_id") or order.get("provider_order_id"),
            "proxy_provider_start_port": refreshed.get("start_port") or order.get("proxy_provider_start_port"),
            "proxy_start_port": refreshed.get("start_port") or order.get("proxy_start_port"),
            "proxy_endpoint": refreshed.get("endpoint") or order.get("proxy_endpoint"),
            "proxy_http_endpoint": refreshed.get("http_endpoint") or order.get("proxy_http_endpoint"),
            "proxy_socks5_endpoint": refreshed.get("socks5_endpoint") or order.get("proxy_socks5_endpoint"),
            "proxy_username": refreshed.get("username") or order.get("proxy_username"),
            "proxy_password": refreshed.get("password") or order.get("proxy_password"),
            "proxy_expires_at": refreshed.get("expires_at") or order.get("proxy_expires_at"),
            "proxy_change_only_last_at": now,
            "proxy_change_history": history,
        },
    )
    latest = await get_order(order_oid)
    await _safe_edit_text(
        callback.message,
        f"{t(lang, 'proxy_change_success')}\n\n{_order_detail_text(lang, latest or order)}",
        reply_markup=proxy_order_actions_kb(str(order_oid), lang, can_reconfigure=_proxy_order_can_reconfigure(latest or order)),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:order:check:"))
async def proxy_order_change_check(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    _data, lang = await _state_lang(state, int(callback.from_user.id))
    raw_id = callback.data.split(":", 3)[3]
    order_oid, order = await _load_user_proxy_order(raw_id, callback.from_user.id)
    if not order_oid or not order:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    user_id = int(callback.from_user.id)
    bot_id = (await callback.message.bot.get_me()).id
    reseller_id = await _resolve_user_reseller(user_id, bot_id)

    charged = 0.0
    charge_order_id = None
    first_free = not bool(order.get("proxy_first_check_free_used"))
    charge_price = proxy_change_check_price()

    if not first_free and charge_price > 0:
        charge_order = await create_order(
            user_id=user_id,
            reseller_id=reseller_id,
            service_id=f"proxyop:change_check:{order.get('provider')}:{order_oid}",
            selling_price=charge_price,
            base_price=charge_price,
        )
        charge_order_id = charge_order["_id"]
        ok, msg = await FinancialManager.process_core_purchase(
            user_id=user_id,
            order_id=str(charge_order_id),
            sale_price=charge_price,
            cost_price=charge_price,
            reseller_id=reseller_id,
        )
        if not ok:
            await update_order_status(charge_order_id, "failed")
            return await callback.answer(finance_error_public_text(lang, str(msg)), show_alert=True)
        charged = charge_price

    await _safe_edit_text(callback.message, t(lang, "proxy_change_processing"))
    refreshed = await refresh_proxy_order(order, with_check=True, max_attempts=2)
    if not refreshed.get("success"):
        logger.warning(
            "proxy change+check failed user_id=%s order_id=%s provider=%s raw=%s quality=%s attempts=%s",
            user_id,
            order_oid,
            order.get("provider"),
            refreshed.get("raw"),
            refreshed.get("quality"),
            refreshed.get("attempts"),
        )
        if charged > 0 and charge_order_id is not None:
            await FinancialManager.refund_core_purchase(
                user_id=user_id,
                order_id=str(charge_order_id),
                sale_price=charged,
                cost_price=charged,
                reseller_id=reseller_id,
            )
            await update_order_status(charge_order_id, "failed")
        event = {
            "type": "change_check",
            "ts": _now_utc(),
            "success": False,
            "charged": 0.0,
            "attempts": int(refreshed.get("attempts") or 1),
            "quality": refreshed.get("quality"),
        }
        history = _append_proxy_history(order, event)
        await update_order_details(
            order_oid,
            {
                "proxy_change_history": history,
                "proxy_last_quality": refreshed.get("quality"),
            },
        )
        error_payload = refreshed.get("raw")
        return await _safe_edit_text(
            callback.message,
            t(lang, "proxy_change_failed").format(error=_provider_error_text(lang, refreshed.get("raw"))),
            reply_markup=proxy_order_actions_kb(str(order_oid), lang, can_reconfigure=_proxy_order_can_reconfigure(order)),
        )

    if charged > 0 and charge_order_id is not None:
        await update_order_status(charge_order_id, "success")
        await update_order_details(
            charge_order_id,
            {
                "parent_order_id": str(order_oid),
                "provider": order.get("provider"),
                "operation_type": "proxy_change_check",
            },
        )

    now = _now_utc()
    event = {
        "type": "change_check",
        "ts": now,
        "success": True,
        "charged": charged,
        "attempts": int(refreshed.get("attempts") or 1),
        "quality": refreshed.get("quality"),
        "first_free": first_free,
    }
    history = _append_proxy_history(order, event)
    updates = {
        "proxy_provider_order_id": refreshed.get("order_id") or order.get("proxy_provider_order_id"),
        "provider_order_id": refreshed.get("order_id") or order.get("provider_order_id"),
        "proxy_provider_start_port": refreshed.get("start_port") or order.get("proxy_provider_start_port"),
        "proxy_start_port": refreshed.get("start_port") or order.get("proxy_start_port"),
        "proxy_endpoint": refreshed.get("endpoint") or order.get("proxy_endpoint"),
        "proxy_http_endpoint": refreshed.get("http_endpoint") or order.get("proxy_http_endpoint"),
        "proxy_socks5_endpoint": refreshed.get("socks5_endpoint") or order.get("proxy_socks5_endpoint"),
        "proxy_username": refreshed.get("username") or order.get("proxy_username"),
        "proxy_password": refreshed.get("password") or order.get("proxy_password"),
        "proxy_expires_at": refreshed.get("expires_at") or order.get("proxy_expires_at"),
        "proxy_last_quality": refreshed.get("quality"),
        "proxy_change_history": history,
        "proxy_change_check_count": int(order.get("proxy_change_check_count") or 0) + 1,
    }
    if first_free:
        updates["proxy_first_check_free_used"] = True
    await update_order_details(order_oid, updates)

    latest = await get_order(order_oid)
    charge_line = t(lang, "proxy_change_free_applied") if first_free else t(lang, "proxy_change_charged").format(price=charged)
    await _safe_edit_text(
        callback.message,
        f"{t(lang, 'proxy_change_success')}\n{charge_line}\n\n{_order_detail_text(lang, latest or order)}",
        reply_markup=proxy_order_actions_kb(str(order_oid), lang, can_reconfigure=_proxy_order_can_reconfigure(latest or order)),
    )


@router.callback_query(F.data == "proxy:back_main")
async def proxy_back_main(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await state.clear()
    if not callback.message:
        await callback.answer()
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    bot_id = (await callback.bot.get_me()).id
    await callback.message.answer(t(lang, "main_menu"), reply_markup=await menu_for_current_bot(lang, bot_id))
    await callback.answer()


@router.callback_query(F.data == "proxy:back_step")
async def proxy_back_step(callback: types.CallbackQuery, state: FSMContext):
    data, _lang = await _state_lang(state, int(callback.from_user.id))
    if not callback.message:
        await callback.answer()
        return

    updates: dict[str, object | None] = {}
    if data.get("proxy_selected_offer"):
        await state.update_data(proxy_selected_offer=None)
        await callback.answer()
        await _render_proxy_panel(callback.message, state)
        await state.set_state(ProxyFlow.menu)
        return
    if data.get("proxy_location"):
        updates.update(proxy_location=None, proxy_state=None, proxy_city=None, proxy_duration_value=None, proxy_duration_label=None, proxy_selected_offer=None, proxy_filtered=[])
    elif data.get("proxy_country"):
        updates.update(proxy_country=None, proxy_location=None, proxy_state=None, proxy_city=None, proxy_duration_value=None, proxy_duration_label=None, proxy_selected_offer=None, proxy_filtered=[])
    else:
        await callback.answer()
        await proxy_back_main(callback, state)
        return

    await state.update_data(**updates)
    await callback.answer()
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)
