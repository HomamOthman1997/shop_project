from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
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
from services.platform.api_auth import ApiAuthContext, require_api_auth
from services.platform.api_rate_limits import (
    ApiRateLimitDecision,
    ApiRateLimitExceeded,
    check_api_rate_limit,
    rate_limit_headers,
    retry_after_seconds,
)
from utils.financial_manager import FinancialManager

logger = logging.getLogger("digital_api")

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
_QUOTE_TTL_SEC = 1800
_TWOPLACES = Decimal("0.01")


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
        "game_id": str(order.get("game_id") or ""),
        "game_name": str(order.get("manual_game_name") or order.get("game_name") or ""),
        "player_id": str(order.get("player_id") or ""),
        "server_id": str(order.get("server_id") or ""),
        "price": float(sale_price),
        "price_label": _money_label(sale_price),
        "cost_price": float(cost_price),
        "provider": str(order.get("provider_code") or ""),
        "provider_order_id": str(order.get("provider_order_id") or ""),
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
    auth = await require_api_auth(request, "digital:account:read")
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
    auth = await require_api_auth(request, "digital:catalog")
    rate_limit = await _check_rate_limit(auth, bucket="digital:catalog", limit=120)
    snapshot = await get_catalog_snapshot(force=str(request.query.get("force") or "").lower() in {"1", "true", "yes"})
    return web.json_response(
        {
            "ok": True,
            "games": [{"id": str(row.get("id") or ""), "name": str(row.get("name") or ""), "image_url": str(row.get("image_url") or "")} for row in list(snapshot.get("games") or [])],
            "gift_categories": [
                {"id": str(row.get("id") or ""), "name": str(row.get("clean_name") or row.get("name") or ""), "count": int(row.get("count") or 0)}
                for row in list(snapshot.get("gift_categories") or [])
            ],
            "providers": dict(snapshot.get("providers") or {}),
            "actions": {"quotes": {"endpoint": "/api/v1/digital/quotes", "method": "GET", "scope": "digital:catalog"}},
        },
        headers=_response_headers(rate_limit),
    )


async def quotes(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "digital:catalog")
    rate_limit = await _check_rate_limit(auth, bucket="digital:quotes", limit=120)
    kind = str(request.query.get("kind") or "game").strip().lower()
    if kind != "game":
        return _json_error("Only game quotes are available in this API version.", status=400, code="unsupported_kind", rate_limit=rate_limit)
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
    auth = await require_api_auth(request, "digital:orders:read")
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
    auth = await require_api_auth(request, "digital:orders:read")
    rate_limit = await _check_rate_limit(auth, bucket="digital:orders:read", limit=90)
    order = await _find_api_order(str(request.match_info.get("order_id") or ""), auth)
    if not order:
        return _json_error("Order not found.", status=404, code="order_not_found", rate_limit=rate_limit)
    return web.json_response({"ok": True, "order": _order_payload(order)}, headers=_response_headers(rate_limit))


async def create_order(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "digital:orders:create")
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
    if str(quote.get("kind") or "") != "game":
        return _json_error("Unsupported quote kind.", status=400, code="unsupported_quote", rate_limit=rate_limit)
    player_id = str((body or {}).get("player_id") or "").strip()
    server_id = str((body or {}).get("server_id") or "").strip()
    if not player_id:
        return _json_error("Missing player_id.", status=400, code="missing_player_id", rate_limit=rate_limit)
    if bool(quote.get("requires_server")) and not server_id:
        return _json_error("Missing server_id.", status=400, code="missing_server_id", rate_limit=rate_limit)

    selected_offer = dict((quote.get("provider_offers") or [{}])[0] or {})
    provider_code = str(selected_offer.get("provider") or quote.get("provider") or "g2bulk")
    provider_ref_id = str(selected_offer.get("ref_id") or quote.get("provider_ref_id") or quote.get("item_id") or "")
    sale_price = float(_money(quote.get("sale_price") or 0))
    cost_price = float(_money(quote.get("cost_price") or sale_price))
    service_ref_id = f"{provider_code}:topup:{provider_ref_id}"
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
        "digital_kind": "game",
        "number_mode": "digital_products",
        "fulfillment_mode": "manual_topup",
        "manual_fulfillment_required": True,
        "manual_fulfillment_status": "pending",
        "manual_item_name": str(quote.get("item_name") or quote.get("item_id") or "Digital product"),
        "manual_game_name": str(quote.get("game_name") or quote.get("game_id") or "Digital product"),
        "game_id": str(quote.get("game_id") or ""),
        "player_id": player_id,
        "server_id": server_id,
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
        player_data={
            "Game": str(quote.get("game_name") or quote.get("game_id") or ""),
            "Package": str(quote.get("item_name") or quote.get("item_id") or ""),
            "Player Id": player_id,
            "Server Id": server_id,
        },
        offers=offers,
    )
    await update_order_details(order["_id"], {"owner_notification_sent": bool(notified), "owner_notification_source": "digital_api"})
    order["owner_notification_sent"] = bool(notified)
    return web.json_response({"ok": True, "order": _order_payload(order)}, headers=_response_headers(rate_limit))


def register_digital_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/digital/health", health)
    app.router.add_get("/api/v1/digital/account", account)
    app.router.add_get("/api/v1/digital/catalog", catalog)
    app.router.add_get("/api/v1/digital/quotes", quotes)
    app.router.add_get("/api/v1/digital/orders", list_orders)
    app.router.add_get("/api/v1/digital/orders/{order_id}", order_detail)
    app.router.add_post("/api/v1/digital/orders", create_order)
