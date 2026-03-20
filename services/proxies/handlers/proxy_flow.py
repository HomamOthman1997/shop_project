from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove
from bson import ObjectId

from database.bots_repo import get_reseller_id_for_bot
from database.mongo import db
from database.orders_repo import (
    create_order,
    get_order,
    list_user_proxy_orders,
    update_order_details,
    update_order_status,
)
from database.user_repo import get_user, get_user_reseller_for_bot, set_user_reseller_for_bot
from keyboards.main_menu_kb import main_menu
from keyboards.reseller_main_menu import reseller_main_menu
from services.proxies.catalog_cache import (
    decode_token,
    filter_offers,
    get_offers_cache,
    set_offers_cache,
)
from services.proxies.keyboards.proxy_kb import (
    proxy_my_orders_kb,
    proxy_offer_actions_kb,
    proxy_offers_kb,
    proxy_order_actions_kb,
    proxy_search_kb,
    proxy_type_kb,
)
from services.proxies.manager import (
    get_proxy_catalog,
    proxy_change_check_price,
    proxy_change_only_cooldown_minutes,
    refresh_proxy_order,
    rent_proxy_offer,
    verify_proxy_offer_delivery,
)
from services.proxies.states.proxy_states import ProxyFlow
from utils.financial_manager import FinancialManager
from utils.permissions import is_reseller
from utils.provider_alias import provider_generic_error, provider_public_id
from utils.translations import t

router = Router()
logger = logging.getLogger("proxy_flow")


def _btn_values(key: str) -> set[str]:
    return {t("en", key), t("ar", key)}


def _is_btn(text: str | None, key: str) -> bool:
    return (text or "").strip() in _btn_values(key)


async def _resolve_user_reseller(user_id: int, bot_id: int) -> int:
    reseller_id = await get_user_reseller_for_bot(user_id, bot_id)
    if reseller_id:
        return reseller_id
    inferred = await get_reseller_id_for_bot(bot_id)
    if inferred:
        await set_user_reseller_for_bot(user_id, bot_id, inferred)
        return inferred
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


def _proxy_filters_text(lang: str, country: str | None, state: str | None, city: str | None) -> str:
    c = country or "Any"
    s = state or "Any"
    ci = city or "Any"
    return t(lang, "proxy_filters_line").format(country=c, state=s, city=ci)


def _proxy_type_label(lang: str, proxy_type: str | None) -> str:
    category = str(proxy_type or "").strip().lower()
    if category == "consumptive":
        return t(lang, "proxy_type_consumptive")
    return t(lang, "proxy_type_unlimited")


def _normalize_proxy_category(value: str | None) -> str:
    category = str(value or "").strip().lower()
    if category in {"unlimited", "consumptive"}:
        return category
    return ""


def _category_provider_match(offer: dict, category: str) -> bool:
    provider = str(offer.get("provider") or "").strip().lower()
    billing_type = str(offer.get("billing_type") or "").strip().lower()
    if category == "unlimited":
        return provider == "4g"
    if category == "consumptive":
        if provider != "9proxy":
            return False
        # Guard against accidental IP/unlimited rows from 9Proxy.
        return billing_type in {"bandwidth", "consumable"} or "gb" in str(offer.get("title") or "").lower()
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


def _order_detail_text(lang: str, order: dict) -> str:
    provider = provider_public_id(order.get("provider"))
    endpoint = str(order.get("proxy_endpoint") or "-")
    username = str(order.get("proxy_username") or "-")
    password = str(order.get("proxy_password") or "-")
    expires = str(order.get("proxy_expires_at") or "-")
    location = order.get("proxy_location") if isinstance(order.get("proxy_location"), dict) else {}
    country = str(location.get("country") or "Any")
    state = str(location.get("state") or "Any")
    city = str(location.get("city") or "Any")
    quality = order.get("proxy_last_quality") if isinstance(order.get("proxy_last_quality"), dict) else {}
    quality_decision = str(quality.get("decision") or "-")
    quality_reason = str(quality.get("reason") or "-")
    return (
        f"{t(lang, 'proxy_order_details')}\n\n"
        f"Provider: {provider}\n"
        f"Endpoint: {endpoint}\n"
        f"Username: {username}\n"
        f"Password: {password}\n"
        f"Expires: {expires}\n"
        f"Location: {country} / {state} / {city}\n"
        f"Quality: {quality_decision} ({quality_reason})"
    )


async def _refresh_catalog_in_state(state: FSMContext):
    data = await state.get_data()
    category = _normalize_proxy_category(data.get("proxy_category"))
    all_offers = await get_proxy_catalog()
    scoped = _apply_proxy_category(all_offers, category)
    set_offers_cache(scoped)
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
    type_msg_id = (await state.get_data()).get("proxy_type_msg")
    if type_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=int(type_msg_id),
                text=text,
                reply_markup=proxy_type_kb(lang),
            )
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
        except Exception:
            pass
    sent = await message.answer(text, reply_markup=proxy_type_kb(lang))
    await state.update_data(proxy_type_msg=sent.message_id)


async def _render_proxy_panel(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("proxy_lang", "en")
    category = _normalize_proxy_category(data.get("proxy_category"))
    if not category:
        await _safe_edit_text(
            message,
            f"{t(lang, 'proxy_type_title')}\n\n{t(lang, 'proxy_type_hint')}",
            reply_markup=proxy_type_kb(lang),
        )
        await state.update_data(proxy_type_msg=message.message_id if message.message_id else None, proxy_panel_msg=message.message_id if message.message_id else None)
        return
    country = data.get("proxy_country")
    state_name = data.get("proxy_state")
    city = data.get("proxy_city")
    offers = data.get("proxy_catalog") or get_offers_cache()
    filtered = filter_offers(offers, country=country, state=state_name, city=city)
    await state.update_data(proxy_filtered=filtered)
    text = (
        f"{t(lang, 'proxy_panel_title')}\n\n"
        f"{t(lang, 'proxy_type_selected').format(proxy_type=_proxy_type_label(lang, category))}\n"
        f"{_proxy_filters_text(lang, country, state_name, city)}\n"
        f"{t(lang, 'proxy_total_offers').format(total=len(filtered))}\n\n"
        f"{t(lang, 'proxy_panel_hint')}"
    )
    kb = proxy_search_kb(lang, country=country, state=state_name)

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


@router.message(lambda msg: _is_btn(msg.text, "btn_proxies"))
async def open_proxy_menu(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")

    await state.clear()
    set_offers_cache([])
    await state.update_data(
        proxy_lang=lang,
        proxy_category=None,
        proxy_catalog_all=[],
        proxy_catalog=[],
        proxy_country=None,
        proxy_state=None,
        proxy_city=None,
        proxy_filtered=[],
        proxy_type_msg=None,
        proxy_panel_msg=None,
    )
    await message.answer(t(lang, "proxy_loading"), reply_markup=ReplyKeyboardRemove())
    await _render_proxy_type_menu(message, state, lang)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:type_menu")
async def proxy_type_menu(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    await callback.message.edit_text(
        f"{t(lang, 'proxy_type_title')}\n\n{t(lang, 'proxy_type_hint')}",
        reply_markup=proxy_type_kb(lang),
    )
    await state.update_data(
        proxy_category=data.get("proxy_category"),
        proxy_country=None,
        proxy_state=None,
        proxy_city=None,
        proxy_filtered=[],
        proxy_panel_msg=callback.message.message_id,
        proxy_type_msg=callback.message.message_id,
    )
    await state.set_state(ProxyFlow.menu)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:type:"))
async def proxy_select_type(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    _data, lang = await _state_lang(state, int(callback.from_user.id))
    category = _normalize_proxy_category(callback.data.split(":", 2)[2])
    if category not in {"unlimited", "consumptive"}:
        return await callback.answer("Invalid type", show_alert=True)

    await state.update_data(
        proxy_category=category,
        proxy_country=None,
        proxy_state=None,
        proxy_city=None,
    )
    await _safe_edit_text(callback.message, t(lang, "proxy_loading"))
    offers = await _refresh_catalog_in_state(state)
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
    await state.update_data(proxy_country=country or None, proxy_state=None, proxy_city=None)
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
    state_name = decode_token(parts[1])
    await state.update_data(proxy_country=country or None, proxy_state=state_name or None, proxy_city=None)
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
    )
    try:
        await message.delete()
    except Exception:
        pass
    await _render_proxy_panel(message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:refresh_catalog")
async def proxy_refresh_catalog(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    category = _normalize_proxy_category(data.get("proxy_category"))
    if not category:
        await _safe_edit_text(
            callback.message,
            f"{t(lang, 'proxy_type_title')}\n\n{t(lang, 'proxy_type_hint')}",
            reply_markup=proxy_type_kb(lang),
        )
        await state.update_data(proxy_type_msg=callback.message.message_id, proxy_panel_msg=callback.message.message_id)
        await state.set_state(ProxyFlow.menu)
        return
    await _safe_edit_text(callback.message, t(lang, "proxy_loading"))
    offers = await _refresh_catalog_in_state(state)
    if not offers:
        await _safe_edit_text(
            callback.message,
            f"{t(lang, 'proxy_no_catalog')}\n\n{t(lang, 'proxy_type_selected').format(proxy_type=_proxy_type_label(lang, category))}",
            reply_markup=proxy_search_kb(lang),
        )
        await state.set_state(ProxyFlow.menu)
        return
    await _render_proxy_panel(callback.message, state)
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:search")
async def proxy_back_to_search(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    category = _normalize_proxy_category(data.get("proxy_category"))
    if not category:
        await _safe_edit_text(
            callback.message,
            f"{t(lang, 'proxy_type_title')}\n\n{t(lang, 'proxy_type_hint')}",
            reply_markup=proxy_type_kb(lang),
        )
        await state.update_data(proxy_type_msg=callback.message.message_id, proxy_panel_msg=callback.message.message_id)
        await state.set_state(ProxyFlow.menu)
        return
    country = data.get("proxy_country")
    state_name = data.get("proxy_state")
    city = data.get("proxy_city")
    filtered = data.get("proxy_filtered") or []

    text = (
        f"{t(lang, 'proxy_panel_title')}\n\n"
        f"{t(lang, 'proxy_type_selected').format(proxy_type=_proxy_type_label(lang, category))}\n"
        f"{_proxy_filters_text(lang, country, state_name, city)}\n"
        f"{t(lang, 'proxy_total_offers').format(total=len(filtered))}\n\n"
        f"{t(lang, 'proxy_panel_hint')}"
    )
    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=proxy_search_kb(lang, country=country, state=state_name),
    )
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:list")
async def proxy_list_offers(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    category = _normalize_proxy_category(data.get("proxy_category"))
    if not category:
        await _safe_edit_text(
            callback.message,
            f"{t(lang, 'proxy_type_title')}\n\n{t(lang, 'proxy_type_hint')}",
            reply_markup=proxy_type_kb(lang),
        )
        await state.update_data(proxy_type_msg=callback.message.message_id, proxy_panel_msg=callback.message.message_id)
        await state.set_state(ProxyFlow.menu)
        return

    offers = data.get("proxy_catalog") or get_offers_cache()
    filtered = filter_offers(
        offers,
        country=data.get("proxy_country"),
        state=data.get("proxy_state"),
        city=data.get("proxy_city"),
    )
    filtered = await _sort_offers_by_low_usage(filtered)
    await state.update_data(proxy_filtered=filtered)

    if not filtered:
        return await _safe_edit_text(
            callback.message,
            t(lang, "proxy_no_filtered_offers"),
            reply_markup=proxy_search_kb(lang, country=data.get("proxy_country"), state=data.get("proxy_state")),
        )

    text = (
        f"{t(lang, 'proxy_offers_title')}\n\n"
        f"{t(lang, 'proxy_type_selected').format(proxy_type=_proxy_type_label(lang, category))}\n"
        f"{t(lang, 'proxy_least_used_hint')}\n"
        f"{_proxy_filters_text(lang, data.get('proxy_country'), data.get('proxy_state'), data.get('proxy_city'))}\n"
        f"{t(lang, 'proxy_total_offers').format(total=len(filtered))}"
    )
    await _safe_edit_text(callback.message, text, reply_markup=proxy_offers_kb(filtered, lang))
    await state.set_state(ProxyFlow.offers)


@router.callback_query(lambda c: c.data and c.data.startswith("proxy:offer:"))
async def proxy_offer_details(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    filtered = data.get("proxy_filtered") or []
    try:
        idx = int(callback.data.split(":", 2)[2])
    except Exception:
        return await callback.answer("Invalid selection", show_alert=True)
    if idx < 0 or idx >= len(filtered):
        return await callback.answer("Invalid selection", show_alert=True)

    offer = filtered[idx]
    await state.update_data(proxy_selected_offer=offer)
    base_price = float(offer.get("base_price") or 0.0)
    sale_price = float(offer.get("price") or 0.0)
    success_rate = float(offer.get("success_rate") or 100.0)
    usage_count = int(offer.get("usage_count") or 0)
    text = (
        f"{t(lang, 'proxy_offer_details')}\n\n"
        f"Provider: {provider_public_id(offer.get('provider'))}\n"
        f"Title: {offer.get('title')}\n"
        f"Country: {offer.get('country')}\n"
        f"State: {offer.get('state')}\n"
        f"City: {offer.get('city')}\n"
        f"Period: {offer.get('period')}\n"
        f"Billing: {offer.get('billing_type')}\n"
        f"{t(lang, 'proxy_usage_count')}: {usage_count}\n"
        f"{t(lang, 'success_rate_short')}: {int(success_rate) if success_rate.is_integer() else f'{success_rate:.1f}'}%\n"
        f"Base: {base_price:.2f}$\n"
        f"Price: {sale_price:.2f}$"
    )
    await _safe_edit_text(callback.message, text, reply_markup=proxy_offer_actions_kb(lang))
    await state.set_state(ProxyFlow.offers)


@router.callback_query(F.data == "proxy:rent:confirm")
async def proxy_rent_confirm(callback: types.CallbackQuery, state: FSMContext):
    data, lang = await _state_lang(state, int(callback.from_user.id))
    offer = data.get("proxy_selected_offer") or {}
    if not offer:
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)

    user_id = int(callback.from_user.id)
    bot_id = (await callback.message.bot.get_me()).id
    reseller_id = await _resolve_user_reseller(user_id, bot_id)
    sale_price = float(offer.get("price") or 0.0)
    base_price = float(offer.get("base_price") if offer.get("base_price") is not None else sale_price)
    if sale_price <= 0 or base_price < 0:
        return await callback.answer(t(lang, "proxy_invalid_price"), show_alert=True)

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
        return await callback.answer(str(msg), show_alert=True)

    try:
        await _safe_edit_text(callback.message, t(lang, "proxy_processing"))
    except Exception as exc:
        logger.warning("Failed to edit proxy processing message for order %s: %s", order_id, exc)

    refunded = False
    try:
        result = await rent_proxy_offer(offer)
        if not result.get("success"):
            await FinancialManager.refund_core_purchase(
                user_id=user_id,
                order_id=str(order_id),
                sale_price=sale_price,
                cost_price=base_price,
                reseller_id=reseller_id,
            )
            refunded = True
            await update_order_status(order_id, "failed")
            return await _safe_edit_text(
                callback.message,
                t(lang, "proxy_rent_failed").format(error=provider_generic_error(lang))
            )

        endpoint = str(result.get("endpoint") or "")
        quality = await verify_proxy_offer_delivery(endpoint)
        if not quality.get("allowed"):
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
                    "proxy_quality_attempts": [quality],
                    "proxy_last_quality": quality,
                },
            )
            await update_order_status(order_id, "failed")
            return await _safe_edit_text(
                callback.message,
                t(lang, "proxy_quality_failed").format(reason=str(quality.get("reason") or "quality_gate_failed")),
            )
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
        return await _safe_edit_text(
            callback.message,
            t(lang, "proxy_rent_failed").format(error=provider_generic_error(lang))
        )

    await update_order_details(
        order_id,
        {
            "provider": offer.get("provider"),
            "provider_order_id": result.get("order_id"),
            "proxy_provider_order_id": result.get("order_id"),
            "proxy_provider_start_port": result.get("start_port"),
            "proxy_start_port": result.get("start_port"),
            "proxy_endpoint": endpoint or "-",
            "proxy_username": result.get("username"),
            "proxy_password": result.get("password"),
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

    text = t(lang, "proxy_purchase_complete").format(
        provider=provider_public_id(offer.get("provider")),
        order_id=result.get("order_id") or "-",
        endpoint=endpoint or "-",
        username=result.get("username") or "-",
        password=result.get("password") or "-",
        expires=result.get("expires_at") or "-",
    )
    if str(quality.get("decision") or "").lower().startswith("gray"):
        text = f"{text}\n\n{t(lang, 'proxy_quality_gray_note')}"

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=proxy_order_actions_kb(str(order_id), lang),
    )
    await state.set_state(ProxyFlow.menu)


@router.callback_query(F.data == "proxy:my_orders")
async def proxy_my_orders(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data, lang = await _state_lang(state, int(callback.from_user.id))
    rows = await list_user_proxy_orders(callback.from_user.id, limit=20)
    if not rows:
        await _safe_edit_text(
            callback.message,
            t(lang, "proxy_my_orders_empty"),
            reply_markup=proxy_search_kb(lang, country=data.get("proxy_country"), state=data.get("proxy_state")),
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
        reply_markup=proxy_order_actions_kb(raw_id, lang),
    )


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
        return await _safe_edit_text(
            callback.message,
            t(lang, "proxy_change_failed").format(error=provider_generic_error(lang)),
            reply_markup=proxy_order_actions_kb(str(order_oid), lang),
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
        reply_markup=proxy_order_actions_kb(str(order_oid), lang),
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
            return await callback.answer(str(msg), show_alert=True)
        charged = charge_price

    await _safe_edit_text(callback.message, t(lang, "proxy_change_processing"))
    refreshed = await refresh_proxy_order(order, with_check=True, max_attempts=2)
    if not refreshed.get("success"):
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
            t(lang, "proxy_change_failed").format(error=provider_generic_error(lang)),
            reply_markup=proxy_order_actions_kb(str(order_oid), lang),
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
        reply_markup=proxy_order_actions_kb(str(order_oid), lang),
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
    if await is_reseller(callback.from_user.id, bot_id=bot_id):
        await callback.message.answer(t(lang, "main_menu"), reply_markup=reseller_main_menu(lang))
    else:
        await callback.message.answer(t(lang, "main_menu"), reply_markup=main_menu(lang))
    await callback.answer()
