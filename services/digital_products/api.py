from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bson import ObjectId

from config import settings
from database.financial_ledger import create_order_v3, get_user_wallet_balance, list_user_wallet_entries
from database.mongo import db
from database.orders_repo import extract_order_amounts, update_order_details, update_order_status
from database.user_repo import get_user
from services.digital_products.catalog_service import digital_provider_enabled, extract_provider_offers, get_catalog_snapshot, get_game_topups
from services.digital_products.manual_fulfillment import submit_manual_auto_api, submit_manual_future
from services.digital_products.product_watchlist import (
    ProductProviderSource,
    ProductWatchlistItem,
    active_product_provider_sources,
    active_product_watchlist,
    load_product_provider_sources,
    provider_sources_by_package,
    validate_product_provider_sources,
    validate_product_watchlist,
)
from services.platform.api_auth import ApiAuthContext, has_api_key_credentials, require_api_auth
from services.platform.api_rate_limits import (
    ApiRateLimitDecision,
    ApiRateLimitExceeded,
    check_api_rate_limit,
    rate_limit_headers,
    retry_after_seconds,
)
from services.platform.telegram_webapp_auth import configured_bot_tokens, require_telegram_webapp_auth, telegram_init_data_from_request
from services.platform.website_auth import require_website_purchase_ready
from utils.financial_manager import FinancialManager

logger = logging.getLogger("digital_api")

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
_QUOTE_TTL_SEC = 1800
_TWOPLACES = Decimal("0.01")
_PRODUCT_CATEGORY_LABELS = {
    "games": {"en": "Games", "ar": "الألعاب"},
    "chat_apps": {"en": "Chat Apps", "ar": "تطبيقات الدردشة"},
    "gift_cards": {"en": "Gift Cards", "ar": "بطاقات الهدايا"},
    "subscriptions": {"en": "Subscriptions", "ar": "الاشتراكات"},
    "software": {"en": "Software", "ar": "البرامج"},
    "software_tools": {"en": "Software Tools", "ar": "أدوات السوفتوير"},
    "iptv": {"en": "IPTV", "ar": "IPTV"},
    "syrian_services": {"en": "Syrian Services", "ar": "خدمات سورية"},
    "services": {"en": "Services", "ar": "خدمات"},
}

_DIGITAL_USER_SCOPES = (
    "digital:account:read",
    "digital:catalog",
    "digital:orders:create",
    "digital:orders:read",
)


class DigitalApiError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class DigitalQuoteError(ValueError):
    pass


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _money_label(value: Any) -> str:
    return f"${float(_money(value)):.2f}"


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _response_headers(rate_limit: ApiRateLimitDecision | None = None) -> dict[str, str]:
    headers = dict(_NO_STORE_HEADERS)
    if rate_limit is not None:
        headers.update(rate_limit_headers(rate_limit))
    return headers


def _input_field(field_id: str, label_en: str, label_ar: str, *, kind: str = "text", required: bool = True) -> dict[str, Any]:
    return {
        "id": field_id,
        "label": {"en": label_en, "ar": label_ar},
        "type": kind,
        "required": bool(required),
    }


def _product_input_fields(item: ProductWatchlistItem) -> list[dict[str, Any]]:
    key = item.product_key
    category = item.category
    unit = item.unit_kind
    if category == "syrian_services":
        if unit == "balance":
            return [
                _input_field("phone_number", "Phone number", "رقم الهاتف"),
                _input_field("amount", "Amount", "المبلغ", kind="number"),
            ]
        if unit == "bill":
            return [
                _input_field("subscriber_id", "Subscriber or bill number", "رقم المشترك أو الفاتورة"),
                _input_field("amount", "Amount", "المبلغ", kind="number", required=False),
                _input_field("notes", "Notes", "ملاحظات", required=False),
            ]
        if unit == "transfer":
            return [
                _input_field("receiver", "Receiver", "المستلم"),
                _input_field("amount", "Amount", "المبلغ", kind="number"),
                _input_field("notes", "Notes", "ملاحظات", required=False),
            ]
        if unit == "ride":
            return [
                _input_field("phone_number", "Phone number", "رقم الهاتف"),
                _input_field("trip_details", "Trip details", "تفاصيل الرحلة"),
            ]
        return [_input_field("details", "Request details", "تفاصيل الطلب")]
    if key.endswith("_via_apple"):
        return [
            _input_field("apple_region", "Apple ID region", "دولة حساب Apple"),
            _input_field("target_app", "Target app", "التطبيق المطلوب", required=False),
            _input_field("notes", "Notes", "ملاحظات", required=False),
        ]
    if category in {"subscriptions", "software", "software_tools", "iptv"}:
        return [
            _input_field("account", "Account email or username", "الحساب أو البريد"),
            _input_field("duration", "Duration", "المدة", required=False),
            _input_field("notes", "Notes", "ملاحظات", required=False),
        ]
    if category == "chat_apps":
        return [
            _input_field("account_id", "Account ID or username", "معرف الحساب أو اليوزر"),
            _input_field("notes", "Notes", "ملاحظات", required=False),
        ]
    if category == "gift_cards":
        return [
            _input_field("region", "Region", "الدولة", required=False),
            _input_field("notes", "Notes", "ملاحظات", required=False),
        ]
    return [_input_field("details", "Request details", "تفاصيل الطلب")]


def _required_field_ids(fields: list[dict[str, Any]]) -> list[str]:
    return [str(field.get("id") or "").strip() for field in fields if bool(field.get("required")) and str(field.get("id") or "").strip()]


def _public_watchlist_item(item: ProductWatchlistItem) -> dict[str, Any]:
    return {
        "id": item.product_key,
        "category": item.category,
        "priority": item.priority,
        "name": item.display_name,
        "region_policy": item.region_policy,
        "default_duration": item.default_duration,
        "unit_kind": item.unit_kind,
        "preferred_provider": item.preferred_provider,
        "sourcing_policy": item.sourcing_policy,
        "has_g2bulk_hint": bool(item.g2bulk_hint),
        "has_bittopup_source": bool(item.bittopup_slug),
        "has_g2g_query": bool(item.g2g_search_query),
        "input_fields": _product_input_fields(item),
        "api_actions": {
            "quotes": {
                "enabled": True,
                "endpoint": f"/api/v1/digital/quotes?kind=product&product_id={item.product_key}",
                "method": "GET",
                "scope": "digital:catalog",
            }
        },
        "public_note": item.public_note,
    }


def _watchlist_category_counts(items: list[ProductWatchlistItem]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.category] = counts.get(item.category, 0) + 1
    return [
        {
            "id": key,
            "label": dict(_PRODUCT_CATEGORY_LABELS.get(key) or {"en": key.replace("_", " ").title(), "ar": key.replace("_", " ")}),
            "count": counts[key],
        }
        for key in sorted(counts)
    ]


def _provider_source_diagnostics(items: list[ProductWatchlistItem], sources: list[ProductProviderSource]) -> dict[str, Any]:
    watchlist_issues = validate_product_watchlist(items)
    source_issues = validate_product_provider_sources(
        sources,
        known_product_keys={item.product_key for item in items},
    )
    issues = [*watchlist_issues, *source_issues]
    issue_counts: dict[str, int] = {}
    for issue in issues:
        code = str(issue.get("code") or "unknown")
        issue_counts[code] = issue_counts.get(code, 0) + 1
    return {
        "products_count": len(items),
        "sources_count": len(sources),
        "issues_count": len(issues),
        "watchlist_issues_count": len(watchlist_issues),
        "source_issues_count": len(source_issues),
        "issue_counts": dict(sorted(issue_counts.items())),
        "status": "ok" if not issues else "needs_review",
    }


def _provider_source_diagnostics_detail(items: list[ProductWatchlistItem], sources: list[ProductProviderSource]) -> dict[str, Any]:
    watchlist_issues = validate_product_watchlist(items)
    source_issues = validate_product_provider_sources(
        sources,
        known_product_keys={item.product_key for item in items},
    )
    summary = _provider_source_diagnostics(items, sources)
    return {
        **summary,
        "watchlist_issues": watchlist_issues[:100],
        "source_issues": source_issues[:100],
        "truncated": len(watchlist_issues) > 100 or len(source_issues) > 100,
    }


def _json_error(message: str, *, status: int, code: str, rate_limit: ApiRateLimitDecision | None = None) -> web.Response:
    headers = _response_headers(rate_limit)
    if status == 429 and rate_limit is not None:
        headers["Retry-After"] = str(retry_after_seconds(rate_limit))
    return web.json_response({"ok": False, "code": code, "message": message}, status=status, headers=headers)


async def _check_rate_limit(auth: ApiAuthContext, *, bucket: str, limit: int, window_seconds: int = 60) -> ApiRateLimitDecision:
    try:
        return await check_api_rate_limit(auth, bucket=bucket, limit=limit, window_seconds=window_seconds)
    except ApiRateLimitExceeded as exc:
        raise web.HTTPTooManyRequests(
            text="rate limit exceeded",
            headers={**_response_headers(exc.decision), "Retry-After": str(retry_after_seconds(exc.decision))},
        ) from exc


def _digital_init_tokens() -> tuple[str, ...]:
    return configured_bot_tokens(
        getattr(settings, "bot_digital_products_token", ""),
        getattr(settings, "bot_main_token", ""),
    )


async def require_digital_user_auth(request: web.Request, required_scope: str) -> ApiAuthContext:
    if has_api_key_credentials(request) or not telegram_init_data_from_request(request):
        return await require_api_auth(request, required_scope)
    if required_scope not in _DIGITAL_USER_SCOPES:
        raise web.HTTPForbidden(text="api key required")
    telegram_auth = require_telegram_webapp_auth(request, bot_tokens=_digital_init_tokens())
    user_id = int(telegram_auth["user_id"])
    return ApiAuthContext(
        key_id=f"telegram:{user_id}",
        user_id=user_id,
        reseller_id=user_id,
        scopes=_DIGITAL_USER_SCOPES,
        name="telegram-miniapp",
    )


def _quote_secret() -> bytes:
    seed = str(getattr(settings, "bot_digital_products_token", "") or getattr(settings, "bot_main_token", "") or "").strip()
    return hashlib.sha256(f"digital-api:{seed or 'digital-api-local'}".encode("utf-8")).digest()


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padded = str(value or "") + ("=" * (-len(str(value or "")) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def make_digital_quote_token(payload: dict[str, Any]) -> str:
    clean = dict(payload or {})
    clean["exp"] = int(time.time()) + _QUOTE_TTL_SEC
    body = _b64_encode(json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_quote_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_digital_quote_token(token: str) -> dict[str, Any]:
    raw = str(token or "").strip()
    if "." not in raw:
        raise DigitalQuoteError("invalid_quote")
    body, sig = raw.rsplit(".", 1)
    expected = hmac.new(_quote_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise DigitalQuoteError("bad_quote")
    try:
        payload = json.loads(_b64_decode(body).decode("utf-8"))
    except Exception as exc:
        raise DigitalQuoteError("bad_quote_payload") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise DigitalQuoteError("quote_expired")
    return payload


def _available_offers(row: dict[str, Any]) -> list[dict[str, Any]]:
    offers = extract_provider_offers(
        row,
        fallback_provider=str(row.get("best_provider") or "g2bulk"),
        fallback_ref_id=str(row.get("best_provider_ref_id") or row.get("id") or ""),
        fallback_price=float(_money(row.get("price") or 0)),
    )
    offers = [dict(item) for item in offers if bool(item.get("available", True)) and digital_provider_enabled(str(item.get("provider") or ""))]
    offers.sort(key=lambda item: float(_money(item.get("price") or 0)) if float(_money(item.get("price") or 0)) > 0 else 9999999)
    return offers


def _public_offer(row: dict[str, Any], *, game_id: str, game_name: str) -> dict[str, Any] | None:
    offers = _available_offers(row)
    if not offers:
        return None
    best = dict(offers[0])
    price = float(_money(best.get("price") or row.get("price") or 0))
    if price <= 0:
        return None
    item_id = str(row.get("id") or "").strip()
    token = make_digital_quote_token(
        {
            "kind": "game",
            "game_id": str(game_id),
            "game_name": str(game_name or game_id),
            "item_id": item_id,
            "item_name": str(row.get("name") or item_id),
            "catalogue_name": str(row.get("catalogue_name") or row.get("name") or item_id),
            "requires_server": bool(row.get("requires_server")),
            "sale_price": price,
            "cost_price": price,
            "provider": str(best.get("provider") or "g2bulk"),
            "provider_ref_id": str(best.get("ref_id") or item_id),
            "provider_offers": offers[:10],
        }
    )
    return {
        "id": item_id,
        "name": str(row.get("name") or item_id),
        "game_id": str(game_id),
        "game_name": str(game_name or game_id),
        "price": price,
        "price_label": _money_label(price),
        "provider": str(best.get("provider") or "g2bulk"),
        "requires_server": bool(row.get("requires_server")),
        "quote_token": token,
        "quote_ttl_sec": _QUOTE_TTL_SEC,
    }


def _product_source_offer(item: ProductWatchlistItem, source: ProductProviderSource) -> dict[str, Any]:
    return {
        "provider": source.provider,
        "ref_id": source.source_ref,
        "price": source.price_usd,
        "available": source.available,
        "fulfillment_mode": source.fulfillment_mode,
        "source_url": source.source_url,
        "source_product_name": item.display_name,
        "source_denomination_name": source.package_name,
    }


def _public_product_offer(item: ProductWatchlistItem, sources: list[ProductProviderSource]) -> dict[str, Any] | None:
    valid_sources = [
        source
        for source in sources
        if source.available and source.price_usd > 0 and source.package_key and source.source_ref
    ]
    if not valid_sources:
        return None
    valid_sources.sort(key=lambda row: row.price_usd)
    best = valid_sources[0]
    offers = [_product_source_offer(item, source) for source in valid_sources]
    quote = {
        "kind": "product",
        "product_id": item.product_key,
        "product_name": item.display_name,
        "item_id": best.package_key,
        "item_name": best.package_name,
        "duration": best.duration,
        "input_fields": _product_input_fields(item),
        "sale_price": best.price_usd,
        "cost_price": best.price_usd,
        "provider": best.provider,
        "provider_ref_id": best.source_ref,
        "fulfillment_mode": best.fulfillment_mode,
        "provider_offers": offers,
    }
    return {
        "id": best.package_key,
        "name": best.package_name,
        "duration": best.duration,
        "price": best.price_usd,
        "price_label": _money_label(best.price_usd),
        "fulfillment_mode": best.fulfillment_mode,
        "provider": best.provider,
        "providers_count": len(offers),
        "provider_offers": offers,
        "quote_token": make_digital_quote_token(quote),
        "public_note": best.public_note or item.public_note,
    }


def _fresh_product_quote_payload(product_id: str, package_id: str) -> dict[str, Any] | None:
    product_key = str(product_id or "").strip()
    package_key = str(package_id or "").strip()
    if not product_key or not package_key:
        return None
    watchlist = {item.product_key: item for item in active_product_watchlist()}
    item = watchlist.get(product_key)
    if not item:
        return None
    sources = [
        source
        for source in active_product_provider_sources()
        if source.product_key == product_key and source.package_key == package_key
    ]
    public_offer = _public_product_offer(item, sources)
    if not public_offer:
        return None
    token_payload = verify_digital_quote_token(str(public_offer.get("quote_token") or ""))
    token_payload["public_offer"] = {key: value for key, value in public_offer.items() if key != "quote_token"}
    return token_payload


def _order_payload(order: dict[str, Any] | None) -> dict[str, Any]:
    order = dict(order or {})
    sale_price, cost_price = extract_order_amounts(order)
    order_id = str(order.get("_id") or "")
    status = str(order.get("status") or "")
    manual_status = str(order.get("manual_fulfillment_status") or "")
    public_status = "completed" if status in {"success", "done"} else "refunded" if status == "refunded" else manual_status or status
    return {
        "id": order_id,
        "status": status,
        "public_status": public_status,
        "kind": str(order.get("digital_kind") or "game"),
        "item_name": str(order.get("manual_item_name") or order.get("service_ref_id") or ""),
        "product_id": str(order.get("product_id") or ""),
        "product_name": str(order.get("manual_product_name") or ""),
        "game_id": str(order.get("game_id") or ""),
        "game_name": str(order.get("manual_game_name") or order.get("game_name") or ""),
        "player_id": str(order.get("player_id") or ""),
        "server_id": str(order.get("server_id") or ""),
        "customer_data": dict(order.get("customer_data") or {}),
        "price": float(sale_price),
        "price_label": _money_label(sale_price),
        "cost_price": float(cost_price),
        "provider": str(order.get("provider_code") or ""),
        "provider_order_id": str(order.get("provider_order_id") or ""),
        "manual_fulfillment_status": manual_status,
        "owner_notification_sent": bool(order.get("owner_notification_sent")),
        "source": str(order.get("api_order_source") or order.get("number_mode") or ""),
        "created_at": _iso(order.get("created_at")),
        "completed_at": _iso(order.get("completed_at")),
        "api_actions": {
            "get": {
                "enabled": bool(order_id),
                "endpoint": f"/api/v1/digital/orders/{order_id}" if order_id else "",
                "method": "GET",
                "scope": "digital:orders:read",
            }
        },
    }


def _manual_status_text(lang: str, *, item_name: str, order_id: str, status: str) -> str:
    status_key = str(status or "").strip().lower()
    is_ar = str(lang or "").lower().startswith("ar")
    if status_key == "processing":
        if is_ar:
            return f"تم استلام طلبك وهو قيد المعالجة الآن.\nالخدمة: {item_name}\nرقم الطلب: {order_id}"
        return f"Your order is now processing.\nItem: {item_name}\nOrder: {order_id}"
    if status_key == "completed":
        if is_ar:
            return f"تم تنفيذ طلبك بنجاح.\nالخدمة: {item_name}\nرقم الطلب: {order_id}"
        return f"Your order has been completed.\nItem: {item_name}\nOrder: {order_id}"
    if status_key == "refunded":
        if is_ar:
            return f"تعذر تنفيذ طلبك وتمت إعادة المبلغ إلى رصيدك.\nالخدمة: {item_name}\nرقم الطلب: {order_id}"
        return f"Your order could not be fulfilled and was refunded.\nItem: {item_name}\nOrder: {order_id}"
    return ""


async def _notify_manual_order_user(order: dict[str, Any], *, status: str) -> bool:
    token = str(getattr(settings, "bot_digital_products_token", "") or getattr(settings, "bot_main_token", "") or "").strip()
    user_id = int((order or {}).get("user_id") or 0)
    if not token or user_id <= 0:
        return False
    user_doc = await get_user(user_id) or {}
    lang = str(user_doc.get("language") or "en")
    item_name = str((order or {}).get("manual_item_name") or (order or {}).get("service_ref_id") or "Digital product")
    text = _manual_status_text(lang, item_name=item_name, order_id=str((order or {}).get("_id") or ""), status=status)
    if not text:
        return False
    bot = Bot(token=token)
    try:
        await bot.send_message(chat_id=user_id, text=text)
        return True
    except Exception as exc:
        logger.warning("digital_api_user_notify_failed order=%s status=%s err=%s", order.get("_id"), status, exc)
        return False
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


def _order_query_id(value: str) -> Any:
    raw = str(value or "").strip()
    if ObjectId.is_valid(raw):
        return ObjectId(raw)
    return raw


async def _charge_digital_order(
    *,
    user_id: int,
    reseller_id: int,
    service_ref_id: str,
    sale_price: float,
    cost_price: float,
) -> tuple[dict[str, Any] | None, str | None]:
    order = await create_order_v3(
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        service_type="core_digital_products",
        service_ref_id=str(service_ref_id),
        retail_amount=float(_money(sale_price)),
        wholesale_amount=float(_money(cost_price)),
        reseller_profit_amount=0.0,
        status="pending",
    )
    ok, reason = await FinancialManager.process_core_purchase(
        user_id=int(user_id),
        order_id=order.get("_id"),
        sale_price=float(_money(sale_price)),
        cost_price=float(_money(cost_price)),
        reseller_id=int(reseller_id),
    )
    if not ok:
        await update_order_status(order.get("_id"), "failed")
        return None, str(reason or "purchase_failed")
    await update_order_status(order.get("_id"), "paid")
    return order, None


def _manual_execution_markup(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Auto API", callback_data=f"dpm:auto:{order_id}"),
                InlineKeyboardButton(text="Future", callback_data=f"dpm:future:{order_id}"),
            ],
            [InlineKeyboardButton(text="استلم", callback_data=f"dpm:claim:{order_id}")],
            [
                InlineKeyboardButton(text="إكمال وإبلاغ المستخدم", callback_data=f"dpm:done:{order_id}"),
                InlineKeyboardButton(text="استرجاع", callback_data=f"dpm:refund:{order_id}"),
            ],
        ]
    )


def _manual_execution_lines(offers: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for offer in offers:
        provider = str(offer.get("provider") or "-").strip() or "-"
        ref_id = str(offer.get("ref_id") or "").strip()
        source_url = str(offer.get("source_url") or "").strip()
        source = str(offer.get("source") or "").strip().lower()
        mode = str(offer.get("fulfillment_mode") or "").strip()
        source_name = str(offer.get("source_product_name") or offer.get("product_name") or "").strip()
        denom = str(offer.get("source_denomination_name") or offer.get("name") or "").strip()
        price = _money_label(offer.get("price") or 0)
        key = "|".join([provider, ref_id, source_url, price])
        if key in seen:
            continue
        seen.add(key)
        if provider.lower() == "bittopup" or source_url:
            label = "BitTopup manual" if provider.lower() == "bittopup" else f"{provider} manual"
        elif source == "future" or provider.lower() == "future":
            label = "G2Bulk Future"
        elif mode:
            label = f"{provider} manual"
        else:
            label = f"{provider} Auto API"
        parts = [label, price]
        if source_name or denom:
            parts.append(" / ".join(part for part in (source_name, denom) if part))
        if source_url:
            parts.append(source_url)
        rows.append("- " + " | ".join(parts))
    return rows[:8]


async def _notify_owner_manual_order(order: dict[str, Any], *, player_data: dict[str, str], offers: list[dict[str, Any]]) -> bool:
    token = str(getattr(settings, "bot_digital_products_token", "") or getattr(settings, "bot_main_token", "") or "").strip()
    owner_id = int(getattr(settings, "owner_id", 0) or 0)
    if not token or owner_id <= 0:
        return False
    order_id = str(order.get("_id") or "")
    lines = [
        "Manual digital top-up pending",
        f"Order: {order_id}",
        f"User: {int(order.get('user_id') or 0)}",
        f"Reseller: {int(order.get('reseller_id') or 0)}",
        f"Item: {str(order.get('manual_item_name') or '-')}",
        f"Provider: {str(order.get('provider_code') or '-')}",
        f"Provider cost: {_money_label(order.get('wholesale_amount') or 0)}",
        "",
        "Execution options:",
        *_manual_execution_lines(offers),
        "",
        "Customer data:",
        *[f"- {key}: {value}" for key, value in player_data.items() if str(value).strip()],
    ]
    bot = Bot(token=token)
    try:
        await bot.send_message(chat_id=owner_id, text="\n".join(lines), reply_markup=_manual_execution_markup(order_id))
        return True
    except Exception as exc:
        logger.warning("digital_api_owner_notify_failed order=%s err=%s", order_id, exc)
        return False
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "status": "healthy", "service": "digital-api", "version": "v1"}, headers=dict(_NO_STORE_HEADERS))


async def account(request: web.Request) -> web.Response:
    auth = await require_digital_user_auth(request, "digital:account:read")
    rate_limit = await _check_rate_limit(auth, bucket="digital:account:read", limit=60)
    user_doc = await get_user(auth.user_id) or {}
    balance = await get_user_wallet_balance(auth.user_id, auth.reseller_id)
    entries = await list_user_wallet_entries(auth.user_id, auth.reseller_id, limit=8)
    return web.json_response(
        {
            "ok": True,
            "user": {
                "id": auth.user_id,
                "username": str(user_doc.get("username") or ""),
                "language": "ar" if str(user_doc.get("language") or "en").lower().startswith("ar") else "en",
            },
            "reseller": {"id": auth.reseller_id},
            "wallet": {"balance": float(balance), "currency": "USD", "balance_label": _money_label(balance)},
            "recent_activity": [
                {
                    "id": str(row.get("_id") or ""),
                    "amount": float(_money(row.get("amount") or 0)),
                    "amount_label": _money_label(abs(float(_money(row.get("amount") or 0)))),
                    "direction": str(row.get("direction") or ""),
                    "reason": str(row.get("reason") or ""),
                    "created_at": _iso(row.get("created_at")),
                    "order_id": str(row.get("order_id") or ""),
                }
                for row in entries
            ],
        },
        headers=_response_headers(rate_limit),
    )


async def catalog(request: web.Request) -> web.Response:
    auth = await require_digital_user_auth(request, "digital:catalog")
    rate_limit = await _check_rate_limit(auth, bucket="digital:catalog", limit=120)
    try:
        snapshot = await asyncio.wait_for(
            get_catalog_snapshot(force=str(request.query.get("force") or "").lower() in {"1", "true", "yes"}),
            timeout=8.0,
        )
        snapshot_status = "ok"
    except Exception:
        snapshot = {"games": [], "gift_categories": [], "providers": {}}
        snapshot_status = "timeout"
    watchlist = active_product_watchlist()
    sources = active_product_provider_sources()
    all_sources = load_product_provider_sources()
    source_counts: dict[str, int] = {}
    for source in sources:
        source_counts[source.product_key] = source_counts.get(source.product_key, 0) + 1
    public_products = []
    for item in watchlist:
        payload = _public_watchlist_item(item)
        payload["sources_count"] = int(source_counts.get(item.product_key) or 0)
        payload["orderable"] = bool(source_counts.get(item.product_key))
        public_products.append(payload)
    return web.json_response(
        {
            "ok": True,
            "games": [{"id": str(row.get("id") or ""), "name": str(row.get("name") or ""), "image_url": str(row.get("image_url") or "")} for row in list(snapshot.get("games") or [])],
            "gift_categories": [
                {"id": str(row.get("id") or ""), "name": str(row.get("clean_name") or row.get("name") or ""), "count": int(row.get("count") or 0)}
                for row in list(snapshot.get("gift_categories") or [])
            ],
            "product_categories": _watchlist_category_counts(watchlist),
            "products": public_products,
            "source_diagnostics": _provider_source_diagnostics(watchlist, all_sources),
            "catalog_snapshot_status": snapshot_status,
            "providers": dict(snapshot.get("providers") or {}),
            "actions": {"quotes": {"endpoint": "/api/v1/digital/quotes", "method": "GET", "scope": "digital:catalog"}},
        },
        headers=_response_headers(rate_limit),
    )


async def source_diagnostics(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "digital:sources:read")
    rate_limit = await _check_rate_limit(auth, bucket="digital:sources:read", limit=60)
    watchlist = active_product_watchlist()
    sources = load_product_provider_sources()
    return web.json_response(
        {
            "ok": True,
            "diagnostics": _provider_source_diagnostics_detail(watchlist, sources),
        },
        headers=_response_headers(rate_limit),
    )


async def quotes(request: web.Request) -> web.Response:
    auth = await require_digital_user_auth(request, "digital:catalog")
    rate_limit = await _check_rate_limit(auth, bucket="digital:quotes", limit=120)
    kind = str(request.query.get("kind") or "game").strip().lower()
    if kind == "product":
        product_id = str(request.query.get("product_id") or "").strip()
        if not product_id:
            return _json_error("Missing product_id.", status=400, code="missing_product_id", rate_limit=rate_limit)
        watchlist = {item.product_key: item for item in active_product_watchlist()}
        item = watchlist.get(product_id)
        if not item:
            return _json_error("Product not found.", status=404, code="product_not_found", rate_limit=rate_limit)
        sources_by_package = provider_sources_by_package(
            source for source in active_product_provider_sources() if source.product_key == product_id
        )
        rows = [_public_product_offer(item, sources) for sources in sources_by_package.values()]
        offers = [row for row in rows if row]
        offers.sort(key=lambda row: float(_money(row.get("price") or 0)) if float(_money(row.get("price") or 0)) > 0 else 9999999)
        return web.json_response(
            {
                "ok": True,
                "kind": "product",
                "product": _public_watchlist_item(item),
                "quote_ttl_sec": _QUOTE_TTL_SEC,
                "offers": offers[:100],
            },
            headers=_response_headers(rate_limit),
        )
    if kind != "game":
        return _json_error("Only game and product quotes are available in this API version.", status=400, code="unsupported_kind", rate_limit=rate_limit)
    game_id = str(request.query.get("game_id") or "").strip()
    if not game_id:
        return _json_error("Missing game_id.", status=400, code="missing_game_id", rate_limit=rate_limit)
    snapshot = await get_catalog_snapshot(force=False)
    game_name = next((str(row.get("name") or "") for row in list(snapshot.get("games") or []) if str(row.get("id") or "") == game_id), game_id)
    q = str(request.query.get("q") or "").strip().lower()
    rows = await get_game_topups(game_id, force=str(request.query.get("force") or "").lower() in {"1", "true", "yes"})
    offers: list[dict[str, Any]] = []
    for row in rows:
        if q and q not in str(row.get("name") or "").lower():
            continue
        public = _public_offer(dict(row), game_id=game_id, game_name=game_name)
        if public:
            offers.append(public)
    return web.json_response(
        {"ok": True, "kind": "game", "game": {"id": game_id, "name": game_name}, "quote_ttl_sec": _QUOTE_TTL_SEC, "offers": offers[:100]},
        headers=_response_headers(rate_limit),
    )


async def _find_api_order(order_id: str, auth: ApiAuthContext) -> dict[str, Any] | None:
    return await db.orders.find_one(
        {
            "_id": _order_query_id(order_id),
            "user_id": int(auth.user_id),
            "reseller_id": int(auth.reseller_id),
            "$or": [{"service_type": "core_digital_products"}, {"number_mode": "digital_products"}],
        }
    )


async def _find_manageable_manual_order(order_id: str, auth: ApiAuthContext) -> dict[str, Any] | None:
    query: dict[str, Any] = {
        "_id": _order_query_id(order_id),
        "fulfillment_mode": "manual_topup",
        "$or": [{"service_type": "core_digital_products"}, {"number_mode": "digital_products"}],
    }
    if "*" not in set(auth.scopes):
        query["reseller_id"] = int(auth.reseller_id)
    return await db.orders.find_one(query)


async def _find_idempotent_order(idempotency_key: str, auth: ApiAuthContext) -> dict[str, Any] | None:
    key = str(idempotency_key or "").strip()
    if not key:
        return None
    return await db.orders.find_one(
        {
            "user_id": int(auth.user_id),
            "reseller_id": int(auth.reseller_id),
            "api_order_source": "digital_api",
            "api_idempotency_key": key,
            "$or": [{"service_type": "core_digital_products"}, {"number_mode": "digital_products"}],
        }
    )


async def list_orders(request: web.Request) -> web.Response:
    auth = await require_digital_user_auth(request, "digital:orders:read")
    rate_limit = await _check_rate_limit(auth, bucket="digital:orders:read", limit=90)
    try:
        limit = max(1, min(100, int(request.query.get("limit") or 30)))
    except Exception:
        limit = 30
    cursor = (
        db.orders.find(
            {
                "user_id": int(auth.user_id),
                "reseller_id": int(auth.reseller_id),
                "$or": [{"service_type": "core_digital_products"}, {"number_mode": "digital_products"}],
            }
        )
        .sort("created_at", -1)
        .limit(limit)
    )
    rows = await cursor.to_list(length=limit)
    return web.json_response({"ok": True, "orders": [_order_payload(row) for row in rows]}, headers=_response_headers(rate_limit))


async def order_detail(request: web.Request) -> web.Response:
    auth = await require_digital_user_auth(request, "digital:orders:read")
    rate_limit = await _check_rate_limit(auth, bucket="digital:orders:read", limit=90)
    order = await _find_api_order(str(request.match_info.get("order_id") or ""), auth)
    if not order:
        return _json_error("Order not found.", status=404, code="order_not_found", rate_limit=rate_limit)
    return web.json_response({"ok": True, "order": _order_payload(order)}, headers=_response_headers(rate_limit))


async def list_admin_manual_orders(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "digital:orders:manage")
    rate_limit = await _check_rate_limit(auth, bucket="digital:orders:manage:list", limit=60)
    try:
        limit = max(1, min(200, int(request.query.get("limit") or 50)))
    except Exception:
        limit = 50
    status_filter = str(request.query.get("status") or "pending").strip().lower()
    query: dict[str, Any] = {
        "fulfillment_mode": "manual_topup",
        "$or": [{"service_type": "core_digital_products"}, {"number_mode": "digital_products"}],
    }
    if "*" not in set(auth.scopes):
        query["reseller_id"] = int(auth.reseller_id)
    if status_filter not in {"", "all", "*"}:
        if status_filter in {"completed", "success", "done"}:
            query["$and"] = [
                {
                    "$or": [
                        {"manual_fulfillment_status": "completed"},
                        {"status": {"$in": ["success", "done"]}},
                    ]
                }
            ]
        elif status_filter in {"refunded"}:
            query["$and"] = [
                {
                    "$or": [
                        {"manual_fulfillment_status": "refunded"},
                        {"status": "refunded"},
                    ]
                }
            ]
        else:
            query["manual_fulfillment_status"] = status_filter
    cursor = db.orders.find(query).sort("created_at", -1).limit(limit)
    rows = await cursor.to_list(length=limit)
    return web.json_response(
        {
            "ok": True,
            "status": status_filter or "all",
            "orders": [_order_payload(row) for row in rows],
        },
        headers=_response_headers(rate_limit),
    )


async def manual_order_action(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "digital:orders:manage")
    rate_limit = await _check_rate_limit(auth, bucket="digital:orders:manage", limit=60)
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await execute_manual_order_action(
        auth=auth,
        order_id=str(request.match_info.get("order_id") or ""),
        body=body,
        rate_limit=rate_limit,
    )


async def execute_manual_order_action(
    *,
    auth: ApiAuthContext,
    order_id: str,
    body: dict[str, Any] | None,
    rate_limit: ApiRateLimitDecision | None = None,
) -> web.Response:
    action = str((body or {}).get("action") or "").strip().lower()
    if action not in {"claim", "auto_api", "future", "complete", "refund"}:
        return _json_error("Unsupported manual action.", status=400, code="unsupported_manual_action", rate_limit=rate_limit)

    order = await _find_manageable_manual_order(order_id, auth)
    if not order:
        return _json_error("Manual order not found.", status=404, code="order_not_found", rate_limit=rate_limit)

    current_status = str(order.get("status") or "").strip().lower()
    if action in {"auto_api", "future"}:
        if current_status in {"success", "done", "refunded", "failed", "cancelled"}:
            return _json_error("Order is already closed.", status=409, code="order_closed", rate_limit=rate_limit)
        result = (
            await submit_manual_auto_api(order, actor_id=int(auth.user_id))
            if action == "auto_api"
            else await submit_manual_future(order, actor_id=int(auth.user_id))
        )
        if not result.get("ok"):
            return _json_error(
                str(result.get("message") or "Provider execution failed."),
                status=409,
                code=str(result.get("code") or "provider_execution_failed"),
                rate_limit=rate_limit,
            )
        updated = {**order, **dict(result.get("patch") or {})}
        notified = await _notify_manual_order_user(updated, status="processing") if bool((body or {}).get("notify_user", True)) else False
        if notified:
            await update_order_details(order["_id"], {"manual_processing_notified_at": datetime.now(UTC)})
        return web.json_response(
            {
                "ok": True,
                "action": action,
                "notified": notified,
                "provider_order_id": str(result.get("provider_order_id") or ""),
                "delivery_lines_private": list(result.get("delivery_lines_private") or []),
                "order": _order_payload(updated),
            },
            headers=_response_headers(rate_limit),
        )

    if action == "claim":
        if current_status in {"success", "done", "refunded", "failed", "cancelled"}:
            return _json_error("Order is already closed.", status=409, code="order_closed", rate_limit=rate_limit)
        now = datetime.now(UTC)
        patch = {
            "manual_execution_route": str((body or {}).get("route") or "manual_claimed").strip() or "manual_claimed",
            "manual_fulfillment_status": "processing",
            "manual_route_updated_by": int(auth.user_id),
            "manual_route_updated_at": now,
            "manual_action_note": str((body or {}).get("note") or "").strip(),
        }
        await update_order_details(order["_id"], patch)
        updated = {**order, **patch}
        notified = await _notify_manual_order_user(updated, status="processing") if bool((body or {}).get("notify_user", True)) else False
        if notified:
            await update_order_details(order["_id"], {"manual_processing_notified_at": datetime.now(UTC)})
            updated["manual_processing_notified_at"] = datetime.now(UTC)
        return web.json_response({"ok": True, "action": action, "notified": notified, "order": _order_payload(updated)}, headers=_response_headers(rate_limit))

    if action == "complete":
        if current_status in {"success", "done"}:
            return _json_error("Order is already completed.", status=409, code="order_completed", rate_limit=rate_limit)
        if current_status == "refunded":
            return _json_error("Order is already refunded.", status=409, code="order_refunded", rate_limit=rate_limit)
        now = datetime.now(UTC)
        patch = {
            "manual_fulfillment_status": "completed",
            "manual_fulfilled_by": int(auth.user_id),
            "manual_fulfilled_at": now,
            "manual_action_note": str((body or {}).get("note") or "").strip(),
        }
        await update_order_details(order["_id"], patch)
        await update_order_status(order["_id"], "success")
        updated = {**order, **patch, "status": "success", "completed_at": now}
        notified = await _notify_manual_order_user(updated, status="completed") if bool((body or {}).get("notify_user", True)) else False
        if notified:
            await update_order_details(order["_id"], {"manual_completion_notified_at": datetime.now(UTC)})
        return web.json_response({"ok": True, "action": action, "notified": notified, "order": _order_payload(updated)}, headers=_response_headers(rate_limit))

    if current_status == "refunded":
        return _json_error("Order is already refunded.", status=409, code="order_refunded", rate_limit=rate_limit)
    if current_status in {"success", "done"}:
        return _json_error("Order is already completed.", status=409, code="order_completed", rate_limit=rate_limit)

    sale_price, cost_price = extract_order_amounts(order)
    ok, reason = await FinancialManager.refund_core_purchase(
        user_id=int(order.get("user_id") or 0),
        order_id=order["_id"],
        sale_price=float(sale_price),
        cost_price=float(cost_price),
        reseller_id=int(order.get("reseller_id") or 0),
    )
    if not ok:
        return _json_error(f"Refund failed: {reason}", status=409, code="refund_failed", rate_limit=rate_limit)
    now = datetime.now(UTC)
    patch = {
        "manual_fulfillment_status": "refunded",
        "manual_refunded_by": int(auth.user_id),
        "manual_refunded_at": now,
        "manual_action_note": str((body or {}).get("note") or "").strip(),
    }
    await update_order_details(order["_id"], patch)
    updated = {**order, **patch, "status": "refunded", "completed_at": now}
    notified = await _notify_manual_order_user(updated, status="refunded") if bool((body or {}).get("notify_user", True)) else False
    if notified:
        await update_order_details(order["_id"], {"manual_refund_notified_at": datetime.now(UTC)})
    return web.json_response({"ok": True, "action": action, "notified": notified, "order": _order_payload(updated)}, headers=_response_headers(rate_limit))


async def create_order(request: web.Request) -> web.Response:
    auth = await require_digital_user_auth(request, "digital:orders:create")
    await require_website_purchase_ready(request)
    rate_limit = await _check_rate_limit(auth, bucket="digital:orders:create", limit=30)
    try:
        body = await request.json()
    except Exception:
        body = {}
    idempotency_key = str(request.headers.get("Idempotency-Key") or (body or {}).get("idempotency_key") or "").strip()
    existing = await _find_idempotent_order(idempotency_key, auth)
    if existing:
        replay = _order_payload(existing)
        replay["idempotent_replay"] = True
        return web.json_response({"ok": True, "order": replay}, headers=_response_headers(rate_limit))

    quote_token = str((body or {}).get("quote_token") or "").strip()
    if not quote_token:
        return _json_error("Missing quote token.", status=400, code="missing_quote", rate_limit=rate_limit)
    try:
        quote = verify_digital_quote_token(quote_token)
    except DigitalQuoteError as exc:
        return _json_error(str(exc), status=400, code=str(exc), rate_limit=rate_limit)
    quote_kind = str(quote.get("kind") or "").strip().lower()
    if quote_kind not in {"game", "product"}:
        return _json_error("Unsupported quote kind.", status=400, code="unsupported_quote", rate_limit=rate_limit)
    player_id = str((body or {}).get("player_id") or "").strip()
    server_id = str((body or {}).get("server_id") or "").strip()
    customer_data = {
        str(key).strip(): str(value).strip()
        for key, value in dict((body or {}).get("customer_data") or {}).items()
        if str(key).strip() and str(value).strip()
    }
    if quote_kind == "product":
        quoted_sale_price = float(_money(quote.get("sale_price") or 0))
        fresh_quote = _fresh_product_quote_payload(
            str(quote.get("product_id") or ""),
            str(quote.get("item_id") or ""),
        )
        if not fresh_quote:
            return _json_error(
                "This product package is no longer available.",
                status=409,
                code="product_source_unavailable",
                rate_limit=rate_limit,
            )
        fresh_sale_price = float(_money(fresh_quote.get("sale_price") or 0))
        if quoted_sale_price > 0 and fresh_sale_price > 0 and fresh_sale_price != quoted_sale_price:
            return web.json_response(
                {
                    "ok": False,
                    "code": "quote_price_changed",
                    "message": "The price changed. Refresh quote before ordering.",
                    "current_price": fresh_sale_price,
                    "current_price_label": _money_label(fresh_sale_price),
                    "quote_ttl_sec": _QUOTE_TTL_SEC,
                },
                status=409,
                headers=_response_headers(rate_limit),
            )
        quote = fresh_quote
    if quote_kind == "game":
        if not player_id:
            return _json_error("Missing player_id.", status=400, code="missing_player_id", rate_limit=rate_limit)
        if bool(quote.get("requires_server")) and not server_id:
            return _json_error("Missing server_id.", status=400, code="missing_server_id", rate_limit=rate_limit)
        customer_data = {
            "Game": str(quote.get("game_name") or quote.get("game_id") or ""),
            "Package": str(quote.get("item_name") or quote.get("item_id") or ""),
            "Player Id": player_id,
            "Server Id": server_id,
        }
    elif not customer_data:
        return _json_error("Missing customer_data.", status=400, code="missing_customer_data", rate_limit=rate_limit)
    else:
        required_fields = _required_field_ids(list(quote.get("input_fields") or []))
        missing_fields = [field_id for field_id in required_fields if not str(customer_data.get(field_id) or "").strip()]
        if missing_fields:
            return _json_error(
                f"Missing customer_data fields: {', '.join(missing_fields)}.",
                status=400,
                code="missing_customer_data_fields",
                rate_limit=rate_limit,
            )

    selected_offer = dict((quote.get("provider_offers") or [{}])[0] or {})
    provider_code = str(selected_offer.get("provider") or quote.get("provider") or "g2bulk")
    provider_ref_id = str(selected_offer.get("ref_id") or quote.get("provider_ref_id") or quote.get("item_id") or "")
    sale_price = float(_money(quote.get("sale_price") or 0))
    cost_price = float(_money(quote.get("cost_price") or sale_price))
    service_ref_id = f"{provider_code}:{quote_kind}:{provider_ref_id}"
    order, err = await _charge_digital_order(
        user_id=auth.user_id,
        reseller_id=auth.reseller_id,
        service_ref_id=service_ref_id,
        sale_price=sale_price,
        cost_price=cost_price,
    )
    if not order or err:
        return _json_error("Insufficient balance.", status=402, code="insufficient_balance", rate_limit=rate_limit)

    offers = [dict(row) for row in list(quote.get("provider_offers") or []) if isinstance(row, dict)]
    details = {
        "digital_kind": quote_kind,
        "number_mode": "digital_products",
        "fulfillment_mode": "manual_topup",
        "manual_fulfillment_required": True,
        "manual_fulfillment_status": "pending",
        "manual_item_name": str(quote.get("item_name") or quote.get("item_id") or "Digital product"),
        "manual_game_name": str(quote.get("game_name") or quote.get("game_id") or "Digital product"),
        "manual_product_name": str(quote.get("product_name") or quote.get("product_id") or ""),
        "product_id": str(quote.get("product_id") or ""),
        "game_id": str(quote.get("game_id") or ""),
        "player_id": player_id,
        "server_id": server_id,
        "customer_data": customer_data,
        "provider_code": provider_code,
        "provider_ref_id": provider_ref_id,
        "provider_response": {"status": "manual_pending", "source": "digital_api"},
        "provider_offers_attempted": offers,
        "selected_provider_offer": selected_offer,
        "api_key_id": auth.key_id,
        "api_order_source": "digital_api",
        "api_idempotency_key": idempotency_key or None,
    }
    await update_order_details(order["_id"], details)
    order = {**order, **details}
    notified = await _notify_owner_manual_order(
        order,
        player_data=customer_data,
        offers=offers,
    )
    await update_order_details(order["_id"], {"owner_notification_sent": bool(notified), "owner_notification_source": "digital_api"})
    order["owner_notification_sent"] = bool(notified)
    return web.json_response({"ok": True, "order": _order_payload(order)}, headers=_response_headers(rate_limit))


def register_digital_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/digital/health", health)
    app.router.add_get("/api/v1/digital/account", account)
    app.router.add_get("/api/v1/digital/catalog", catalog)
    app.router.add_get("/api/v1/digital/source-diagnostics", source_diagnostics)
    app.router.add_get("/api/v1/digital/quotes", quotes)
    app.router.add_get("/api/v1/digital/orders", list_orders)
    app.router.add_get("/api/v1/digital/orders/{order_id}", order_detail)
    app.router.add_get("/api/v1/digital/admin/orders", list_admin_manual_orders)
    app.router.add_post("/api/v1/digital/orders", create_order)
    app.router.add_post("/api/v1/digital/orders/{order_id}/manual-action", manual_order_action)
