from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import web

from config import settings
from database.cardex_repo import create_pricing_rule, deactivate_pricing_rule, get_or_create_cardex_user, list_active_pricing_rules
from services.cards_bot.handlers import _fmt_rate
from services.cards_bot.service import parse_decimal, quote_card_submission, submit_card
from services.cards_bot.service import get_wallet_snapshot, list_cards_for_user

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "webapp" / "cardex"
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _verify_cardex_init_data(init_data: str) -> dict[str, Any]:
    raw = str(init_data or "").strip()
    if not raw:
        raise web.HTTPUnauthorized(text="missing initData")
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = str(pairs.pop("hash", "") or "")
    if not received_hash:
        raise web.HTTPUnauthorized(text="missing hash")
    token = str(getattr(settings, "bot_card_ex_token", "") or "").strip()
    if not token:
        raise web.HTTPUnauthorized(text="cardex bot token not configured")
    check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    calculated = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise web.HTTPUnauthorized(text="bad initData")
    user = json.loads(pairs.get("user") or "{}")
    user_id = int(user.get("id") or 0)
    if user_id <= 0:
        raise web.HTTPUnauthorized(text="missing user")
    return {"user_id": user_id, "user": user}


def _cardex_admin_ids() -> set[int]:
    raw = str(getattr(settings, "cardex_admin_ids", "") or "")
    ids: set[int] = set()
    for part in raw.split(","):
        with_id = part.strip()
        if not with_id:
            continue
        try:
            ids.add(int(with_id))
        except Exception:
            continue
    owner_id = int(getattr(settings, "owner_id", 0) or 0)
    if owner_id > 0:
        ids.add(owner_id)
    return ids


def _auth(request: web.Request, *, require_admin: bool = False) -> dict[str, Any]:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    auth = _verify_cardex_init_data(init_data)
    if require_admin and int(auth["user_id"]) not in _cardex_admin_ids():
        raise web.HTTPForbidden(text="admin only")
    return auth


def _pricing_label(row: dict[str, Any]) -> str:
    label = str(row.get("denomination_label") or "").strip()
    if not label and row.get("range_min") is not None and row.get("range_max") is not None:
        label = f"{_fmt_rate(row.get('range_min'))} --> {_fmt_rate(row.get('range_max'))}"
    if not label:
        values = row.get("denominations")
        if isinstance(values, list) and values:
            label = "-".join(_fmt_rate(item) for item in values)
    if not label:
        label = _fmt_rate(row.get("denomination"))
    return label


def _rule_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("_id") or ""),
        "brand": str(row.get("brand") or "").upper(),
        "currency": str(row.get("currency") or "USD").upper(),
        "region": str(row.get("region") or "GLOBAL").upper(),
        "label": _pricing_label(row),
        "customer_rate": _fmt_rate(row.get("customer_buy_rate_percent")),
        "trader_rate": _fmt_rate(row.get("trader_rate_percent")),
        "note": str(row.get("public_note") or ""),
        "range_min": row.get("range_min"),
        "range_max": row.get("range_max"),
        "denominations": list(row.get("denominations") or []),
    }


def _money(value: Any) -> float:
    try:
        return float(Decimal(str(value or 0)).quantize(Decimal("0.01")))
    except Exception:
        return 0.0


def _card_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("_id") or ""),
        "brand": str(row.get("brand") or "").upper(),
        "denomination": _fmt_rate(row.get("denomination")),
        "currency": str(row.get("currency") or "USD").upper(),
        "region": str(row.get("region") or "GLOBAL").upper(),
        "status": str(row.get("status") or ""),
        "customer_value_usd": _money(row.get("customer_value_usd")),
        "customer_rate": _fmt_rate(row.get("customer_buy_rate_percent")),
        "created_at": str(row.get("created_at") or ""),
        "review_notes": str(row.get("review_notes") or ""),
    }


def _auth_full_name(user: dict[str, Any]) -> str | None:
    return " ".join(str(user.get(part) or "").strip() for part in ("first_name", "last_name")).strip() or None


async def _card_user_from_auth(auth: dict[str, Any]) -> dict[str, Any]:
    user = dict(auth.get("user") or {})
    return await get_or_create_cardex_user(
        telegram_user_id=int(auth["user_id"]),
        telegram_username=str(user.get("username") or "").strip() or None,
        full_name=_auth_full_name(user),
        owner_telegram_user_id=int(getattr(settings, "owner_id", 0) or 0),
    )


async def cardex_index(_request: web.Request) -> web.Response:
    return web.Response(text=(_STATIC / "index.html").read_text(encoding="utf-8"), content_type="text/html", headers=dict(_NO_STORE_HEADERS))


async def cardex_static(request: web.Request) -> web.Response:
    name = str(request.match_info.get("name") or "")
    path = (_STATIC / name).resolve()
    if _STATIC.resolve() not in path.parents or not path.exists() or not path.is_file():
        raise web.HTTPNotFound()
    content_types = {".css": "text/css", ".js": "application/javascript", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}
    return web.Response(body=path.read_bytes(), content_type=content_types.get(path.suffix.lower(), "application/octet-stream"), headers=dict(_NO_STORE_HEADERS))


async def cardex_prices(request: web.Request) -> web.Response:
    auth = _auth(request)
    rows = [_rule_payload(row) for row in await list_active_pricing_rules(limit=1000)]
    return web.json_response({"is_admin": int(auth["user_id"]) in _cardex_admin_ids(), "rules": rows}, headers=dict(_NO_STORE_HEADERS))


async def cardex_wallet(request: web.Request) -> web.Response:
    auth = _auth(request)
    card_user = await _card_user_from_auth(auth)
    wallet = await get_wallet_snapshot(str(card_user.get("_id")))
    return web.json_response(
        {
            "wallet": {
                "available_usd": _money(wallet.get("available_usd")),
                "pending_usd": _money(wallet.get("pending_usd")),
                "locked_usd": _money(wallet.get("locked_usd")),
            }
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def cardex_my_cards(request: web.Request) -> web.Response:
    auth = _auth(request)
    card_user = await _card_user_from_auth(auth)
    rows = await list_cards_for_user(str(card_user.get("_id")), limit=50)
    return web.json_response({"cards": [_card_payload(row) for row in rows]}, headers=dict(_NO_STORE_HEADERS))


def _parse_values(raw: str) -> tuple[list[Decimal], str, Decimal | None, Decimal | None]:
    text = str(raw or "").strip()
    for sep in ("-->", "->", "=>"):
        if sep in text:
            left, _, right = text.partition(sep)
            start = parse_decimal(left)
            end = parse_decimal(right)
            if start > end:
                start, end = end, start
            return [start], f"{_fmt_rate(start)} --> {_fmt_rate(end)}", start, end
    parts = [part.strip() for part in text.replace(",", "-").replace("/", "-").split("-") if part.strip()]
    values = sorted({parse_decimal(part) for part in parts})
    if not values:
        raise ValueError("missing values")
    return values, "-".join(_fmt_rate(value) for value in values), None, None


async def cardex_price_create(request: web.Request) -> web.Response:
    auth = _auth(request, require_admin=True)
    body = await request.json()
    try:
        values, label, range_min, range_max = _parse_values(str(body.get("values") or ""))
        customer_rate = parse_decimal(str(body.get("customer_rate") or ""))
        trader_rate = parse_decimal(str(body.get("trader_rate") or body.get("customer_rate") or ""))
    except (ValueError, InvalidOperation):
        raise web.HTTPBadRequest(text="invalid pricing values")
    row = await create_pricing_rule(
        actor_user_id=str(auth["user_id"]),
        brand=str(body.get("brand") or ""),
        denomination=values[0],
        currency=str(body.get("currency") or "USD"),
        region=str(body.get("region") or "GLOBAL"),
        customer_buy_rate_percent=customer_rate,
        trader_rate_percent=trader_rate,
        public_note=str(body.get("note") or "").strip() or None,
        denominations=values,
        denomination_label=label,
        range_min=range_min,
        range_max=range_max,
    )
    return web.json_response({"rule": _rule_payload(row)}, headers=dict(_NO_STORE_HEADERS))


async def cardex_price_delete(request: web.Request) -> web.Response:
    auth = _auth(request, require_admin=True)
    rule_id = str(request.match_info.get("rule_id") or "").strip()
    deleted = await deactivate_pricing_rule(actor_user_id=str(auth["user_id"]), pricing_rule_id=rule_id)
    if not deleted:
        raise web.HTTPNotFound(text="pricing not found")
    return web.json_response({"ok": True}, headers=dict(_NO_STORE_HEADERS))


async def cardex_quote_submission(request: web.Request) -> web.Response:
    _auth(request)
    body = await request.json()
    try:
        denomination = parse_decimal(str(body.get("denomination") or ""))
    except ValueError:
        raise web.HTTPBadRequest(text="invalid denomination")
    quote = await quote_card_submission(
        brand=str(body.get("brand") or ""),
        denomination=denomination,
        currency=str(body.get("currency") or "USD"),
        region=str(body.get("region") or "GLOBAL"),
    )
    return web.json_response({"quote": quote}, headers=dict(_NO_STORE_HEADERS))


async def cardex_submit_card(request: web.Request) -> web.Response:
    auth = _auth(request)
    card_user = await _card_user_from_auth(auth)
    body = await request.json()
    code = str(body.get("code") or "").strip()
    pin = str(body.get("pin") or "").strip() or None
    if len(code) < 3:
        raise web.HTTPBadRequest(text="card code is too short")
    try:
        denomination = parse_decimal(str(body.get("denomination") or ""))
    except ValueError:
        raise web.HTTPBadRequest(text="invalid denomination")
    card, missing = await submit_card(
        actor_user_id=str(card_user.get("_id")),
        brand=str(body.get("brand") or ""),
        denomination=denomination,
        currency=str(body.get("currency") or "USD"),
        region=str(body.get("region") or "GLOBAL"),
        code=code,
        pin=pin,
    )
    if missing:
        return web.json_response({"ok": False, "missing_pricing": True, "missing_id": str(missing.get("_id") or "")}, headers=dict(_NO_STORE_HEADERS))
    quote = await quote_card_submission(
        brand=str(body.get("brand") or ""),
        denomination=denomination,
        currency=str(body.get("currency") or "USD"),
        region=str(body.get("region") or "GLOBAL"),
    )
    return web.json_response(
        {
            "ok": True,
            "card_id": str((card or {}).get("_id") or ""),
            "status": str((card or {}).get("status") or ""),
            "quote": quote,
        },
        headers=dict(_NO_STORE_HEADERS),
    )


def register_cardex_routes(app: web.Application) -> None:
    app.router.add_get("/mini/cardex", cardex_index)
    app.router.add_get("/mini/cardex/static/{name}", cardex_static)
    app.router.add_get("/mini/cardex/api/prices", cardex_prices)
    app.router.add_get("/mini/cardex/api/wallet", cardex_wallet)
    app.router.add_get("/mini/cardex/api/cards", cardex_my_cards)
    app.router.add_post("/mini/cardex/api/prices", cardex_price_create)
    app.router.add_delete("/mini/cardex/api/prices/{rule_id}", cardex_price_delete)
    app.router.add_post("/mini/cardex/api/quote", cardex_quote_submission)
    app.router.add_post("/mini/cardex/api/submit", cardex_submit_card)
