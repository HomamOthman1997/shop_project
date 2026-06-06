from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import web

from config import settings
from database.cardex_repo import create_pricing_rule, deactivate_pricing_rule, get_or_create_cardex_user, list_active_pricing_rules
from services.cards_bot.handlers import _fmt_rate
from services.cards_bot.lona_pricebook import merge_lona_cardex_rules
from services.cards_bot.service import (
    accept_card,
    create_trader,
    create_trader_batch,
    create_withdrawal,
    get_missing_pricing,
    get_wallet_snapshot,
    list_cards_for_review,
    list_cards_for_daily_export,
    list_cards_for_user,
    list_audit_logs,
    list_missing_pricing,
    list_open_withdrawals,
    list_traders,
    list_withdrawals_for_user,
    parse_decimal,
    post_trader_payment,
    quote_card_submission,
    reject_card,
    submit_card,
    trader_statement,
    update_withdrawal_status,
)
from services.platform.website_auth import require_website_auth
from database.website_auth_repo import find_website_account_by_id

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "webapp" / "cardex"
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _cardex_init_tokens() -> list[str]:
    tokens: list[str] = []
    for key in ("bot_card_ex_token", "bot_main_token", "bot_digital_products_token"):
        token = str(getattr(settings, key, "") or "").strip()
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _verify_cardex_init_data(init_data: str) -> dict[str, Any]:
    raw = str(init_data or "").strip()
    if not raw:
        raise web.HTTPUnauthorized(text="missing initData")
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = str(pairs.pop("hash", "") or "")
    if not received_hash:
        raise web.HTTPUnauthorized(text="missing hash")
    check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    tokens = _cardex_init_tokens()
    if not tokens:
        raise web.HTTPUnauthorized(text="cardex bot token not configured")
    verified = False
    for token in tokens:
        secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
        calculated = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(calculated, received_hash):
            verified = True
            break
    if not verified:
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


async def _auth(request: web.Request, *, require_admin: bool = False) -> dict[str, Any]:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if str(init_data or "").strip():
        auth = _verify_cardex_init_data(init_data)
        if require_admin and int(auth["user_id"]) not in _cardex_admin_ids():
            raise web.HTTPForbidden(text="admin only")
        return auth
    if require_admin:
        raise web.HTTPForbidden(text="admin only")
    website = await require_website_auth(request)
    account = await find_website_account_by_id(website.account_id) or {}
    if str(account.get("identity_status") or "") != "approved":
        raise web.HTTPForbidden(text="identity verification required")
    return {"user_id": website.customer_id, "user": {"id": website.customer_id}, "source": "website"}


async def _optional_auth(request: web.Request) -> dict[str, Any] | None:
    try:
        return await _auth(request)
    except (web.HTTPUnauthorized, web.HTTPForbidden):
        return None


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


def _rule_payload(row: dict[str, Any], *, include_private: bool = False) -> dict[str, Any]:
    payload = {
        "id": str(row.get("_id") or ""),
        "brand": str(row.get("brand") or "").upper(),
        "currency": str(row.get("currency") or "USD").upper(),
        "region": str(row.get("region") or "GLOBAL").upper(),
        "label": _pricing_label(row),
        "customer_rate": _fmt_rate(row.get("customer_buy_rate_percent")),
        "note": str(row.get("public_note") or ""),
        "range_min": row.get("range_min"),
        "range_max": row.get("range_max"),
        "denominations": list(row.get("denominations") or []),
        "requires_custom_value": bool(row.get("requires_custom_value")),
        "readonly": bool(row.get("readonly")),
        "price_kind": str(row.get("lona_kind") or ""),
    }
    if include_private:
        payload["trader_rate"] = _fmt_rate(row.get("trader_rate_percent"))
    return payload


def _quote_payload(quote: dict[str, Any], *, include_private: bool = False) -> dict[str, Any]:
    rule = quote.get("rule")
    payload = {
        "configured": bool(quote.get("configured")),
        "rule": _rule_payload(rule, include_private=include_private) if isinstance(rule, dict) else None,
        "customer_buy_rate_percent": _fmt_rate(quote.get("customer_buy_rate_percent")),
        "customer_value_usd": _money(quote.get("customer_value_usd")),
        "public_note": str(quote.get("public_note") or ""),
    }
    if include_private:
        payload["trader_rate_percent"] = _fmt_rate(quote.get("trader_rate_percent"))
        payload["trader_value_usd"] = _money(quote.get("trader_value_usd"))
    return payload


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


def _admin_card_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = _card_payload(row)
    payload.update(
        {
            "code": str(row.get("code") or ""),
            "pin": str(row.get("pin") or ""),
            "seller_user_id": str(row.get("seller_user_id") or ""),
            "trader_value_usd": _money(row.get("trader_value_usd")),
            "trader_rate": _fmt_rate(row.get("trader_rate_percent")),
        }
    )
    return payload


def _batch_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("_id") or ""),
        "trader_id": str(row.get("trader_id") or ""),
        "status": str(row.get("status") or ""),
        "total_count": int(row.get("total_count") or 0),
        "total_expected_from_trader_usd": _money(row.get("total_expected_from_trader_usd")),
        "gross_profit_usd": _money(row.get("gross_profit_usd")),
        "notes": str(row.get("notes") or ""),
    }


def _withdrawal_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("_id") or ""),
        "amount_usd": _money(row.get("requested_usd_amount")),
        "payout_currency": str(row.get("payout_currency") or "USD").upper(),
        "status": str(row.get("status") or ""),
        "notes": str(row.get("notes") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _missing_pricing_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("_id") or ""),
        "brand": str(row.get("brand") or "").upper(),
        "denomination": _fmt_rate(row.get("denomination")),
        "currency": str(row.get("currency") or "USD").upper(),
        "region": str(row.get("region") or "GLOBAL").upper(),
        "seen_count": int(row.get("seen_count") or 0),
        "created_by_user_id": str(row.get("created_by_user_id") or ""),
        "last_seen_at": str(row.get("last_seen_at") or ""),
    }


def _trader_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("_id") or ""),
        "name": str(row.get("name") or ""),
        "status": str(row.get("status") or ""),
        "default_currency": str(row.get("default_currency") or "USD").upper(),
        "notes": str(row.get("notes") or ""),
        "created_at": str(row.get("created_at") or ""),
    }


def _trader_statement_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("_id") or ""),
        "entry_type": str(row.get("entry_type") or ""),
        "debit_usd": _money(row.get("debit_usd")),
        "credit_usd": _money(row.get("credit_usd")),
        "running_balance_usd": _money(row.get("running_balance_usd")),
        "reference_type": str(row.get("reference_type") or ""),
        "reference_id": str(row.get("reference_id") or ""),
        "description": str(row.get("description") or ""),
        "created_at": str(row.get("created_at") or ""),
    }


def _audit_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("_id") or ""),
        "actor_user_id": str(row.get("actor_user_id") or ""),
        "action": str(row.get("action") or ""),
        "entity_type": str(row.get("entity_type") or ""),
        "entity_id": str(row.get("entity_id") or ""),
        "created_at": str(row.get("created_at") or ""),
    }


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(key) or "UNKNOWN").upper().strip() or "UNKNOWN"
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def _today_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _card_export_filename(brand: str, day: datetime) -> str:
    safe_brand = re.sub(r"[^A-Za-z0-9_-]+", "_", str(brand or "cards").strip().upper()).strip("_") or "CARDS"
    return f"cardex_{day.strftime('%Y-%m-%d')}_{safe_brand}.txt"


def _card_export_line(row: dict[str, Any]) -> str:
    return " | ".join(
        [
            str(row.get("code") or "").strip(),
            str(row.get("pin") or "").strip() or "-",
            f"{_fmt_rate(row.get('denomination'))} {row.get('currency')}",
            str(row.get("region") or "GLOBAL"),
            str(row.get("status") or "-"),
            str(row.get("_id") or "-"),
        ]
    )


def _export_files_payload(rows: list[dict[str, Any]], *, day: datetime) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        brand = str(row.get("brand") or "UNKNOWN").upper().strip() or "UNKNOWN"
        grouped.setdefault(brand, []).append(row)

    files: list[dict[str, Any]] = []
    for brand in sorted(grouped):
        brand_rows = grouped[brand]
        lines = [
            "Card-EX daily export",
            f"Date: {day.strftime('%Y-%m-%d')}",
            f"Brand: {brand}",
            f"Count: {len(brand_rows)}",
            "",
            "CODE | PIN | VALUE | REGION | STATUS | REF",
        ]
        lines.extend(_card_export_line(row) for row in brand_rows)
        files.append(
            {
                "filename": _card_export_filename(brand, day),
                "brand": brand,
                "count": len(brand_rows),
                "content": "\n".join(lines) + "\n",
            }
        )
    return files


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
    auth = await _optional_auth(request)
    is_admin = bool(auth and int(auth["user_id"]) in _cardex_admin_ids())
    rows = [
        _rule_payload(row, include_private=is_admin)
        for row in merge_lona_cardex_rules(await list_active_pricing_rules(limit=1000))
    ]
    return web.json_response({"is_admin": is_admin, "rules": rows}, headers=dict(_NO_STORE_HEADERS))


async def cardex_wallet(request: web.Request) -> web.Response:
    auth = await _auth(request)
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
    auth = await _auth(request)
    card_user = await _card_user_from_auth(auth)
    rows = await list_cards_for_user(str(card_user.get("_id")), limit=50)
    return web.json_response({"cards": [_card_payload(row) for row in rows]}, headers=dict(_NO_STORE_HEADERS))


async def cardex_withdrawals(request: web.Request) -> web.Response:
    auth = await _auth(request)
    card_user = await _card_user_from_auth(auth)
    rows = await list_withdrawals_for_user(str(card_user.get("_id")), limit=50)
    return web.json_response({"withdrawals": [_withdrawal_payload(row) for row in rows]}, headers=dict(_NO_STORE_HEADERS))


async def cardex_admin_queue(request: web.Request) -> web.Response:
    await _auth(request, require_admin=True)
    cards = await list_cards_for_review(limit=50)
    today_since, today_until = _today_window()
    today_cards = await list_cards_for_daily_export(since=today_since, until=today_until, limit=2000)
    batchable_cards = await list_cards_for_daily_export(
        since=datetime(2020, 1, 1, tzinfo=timezone.utc),
        until=datetime.now(timezone.utc) + timedelta(days=1),
        limit=200,
    )
    batchable_cards = [
        row
        for row in batchable_cards
        if str(row.get("status") or "") in {"customer_pending_credit", "customer_available_credit"}
    ][:50]
    withdrawals = await list_open_withdrawals(limit=50)
    missing = await list_missing_pricing(limit=50)
    traders = await list_traders(limit=50)
    audit_logs = await list_audit_logs(limit=20)
    return web.json_response(
        {
            "today_report": {
                "date": today_since.strftime("%Y-%m-%d"),
                "cards_total": len(today_cards),
                "pending_reviews": len(cards),
                "missing_pricing": len(missing),
                "open_withdrawals": len(withdrawals),
                "by_status": _count_by(today_cards, "status"),
                "by_brand": _count_by(today_cards, "brand"),
                "customer_value_usd": _money(sum(Decimal(str(row.get("customer_value_usd") or 0)) for row in today_cards)),
                "trader_value_usd": _money(sum(Decimal(str(row.get("trader_value_usd") or 0)) for row in today_cards)),
            },
            "today_exports": _export_files_payload(today_cards, day=today_since),
            "cards": [_admin_card_payload(row) for row in cards],
            "batchable_cards": [_admin_card_payload(row) for row in batchable_cards],
            "withdrawals": [_withdrawal_payload(row) for row in withdrawals],
            "missing_pricing": [_missing_pricing_payload(row) for row in missing],
            "traders": [_trader_payload(row) for row in traders],
            "audit_logs": [_audit_payload(row) for row in audit_logs],
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def cardex_admin_card_action(request: web.Request) -> web.Response:
    auth = await _auth(request, require_admin=True)
    card_id = str(request.match_info.get("card_id") or "").strip()
    body = await request.json()
    action = str(body.get("action") or "").strip().lower()
    notes = str(body.get("notes") or "").strip() or None
    try:
        if action == "accept":
            row = await accept_card(card_id, actor_user_id=str(auth["user_id"]), notes=notes)
        elif action == "reject":
            row = await reject_card(card_id, actor_user_id=str(auth["user_id"]), notes=notes)
        else:
            raise web.HTTPBadRequest(text="unsupported card action")
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc) or "card action failed")
    return web.json_response({"card": _admin_card_payload(row)}, headers=dict(_NO_STORE_HEADERS))


async def cardex_admin_withdrawal_action(request: web.Request) -> web.Response:
    auth = await _auth(request, require_admin=True)
    withdrawal_id = str(request.match_info.get("withdrawal_id") or "").strip()
    body = await request.json()
    action = str(body.get("action") or "").strip().lower()
    status_by_action = {"approve": "approved", "reject": "rejected", "paid": "paid"}
    status = status_by_action.get(action)
    if not status:
        raise web.HTTPBadRequest(text="unsupported withdrawal action")
    try:
        row = await update_withdrawal_status(
            withdrawal_id,
            status=status,
            actor_user_id=str(auth["user_id"]),
            reason=str(body.get("notes") or "").strip() or None,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc) or "withdrawal action failed")
    return web.json_response({"withdrawal": _withdrawal_payload(row)}, headers=dict(_NO_STORE_HEADERS))


async def cardex_admin_missing_pricing_action(request: web.Request) -> web.Response:
    auth = await _auth(request, require_admin=True)
    missing_id = str(request.match_info.get("missing_id") or "").strip()
    row = await get_missing_pricing(missing_id)
    if not row:
        raise web.HTTPNotFound(text="missing pricing row not found")
    body = await request.json()
    try:
        customer_rate = parse_decimal(str(body.get("customer_rate") or ""))
        trader_rate = parse_decimal(str(body.get("trader_rate") or body.get("customer_rate") or ""))
    except ValueError:
        raise web.HTTPBadRequest(text="invalid pricing rate")
    created = await create_pricing_rule(
        actor_user_id=str(auth["user_id"]),
        brand=str(row.get("brand") or ""),
        denomination=parse_decimal(str(row.get("denomination") or "")),
        currency=str(row.get("currency") or "USD"),
        region=str(row.get("region") or "GLOBAL"),
        customer_buy_rate_percent=customer_rate,
        trader_rate_percent=trader_rate,
        public_note=str(body.get("note") or "").strip() or None,
    )
    return web.json_response({"rule": _rule_payload(created, include_private=True)}, headers=dict(_NO_STORE_HEADERS))


async def cardex_admin_create_trader(request: web.Request) -> web.Response:
    auth = await _auth(request, require_admin=True)
    body = await request.json()
    try:
        row = await create_trader(
            actor_user_id=str(auth["user_id"]),
            name=str(body.get("name") or "").strip(),
            notes=str(body.get("notes") or "").strip() or None,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc) or "trader creation failed")
    return web.json_response({"trader": _trader_payload(row)}, headers=dict(_NO_STORE_HEADERS))


async def cardex_admin_trader_statement(request: web.Request) -> web.Response:
    await _auth(request, require_admin=True)
    trader_id = str(request.match_info.get("trader_id") or "").strip()
    rows = await trader_statement(trader_id, limit=50)
    return web.json_response({"statement": [_trader_statement_payload(row) for row in rows]}, headers=dict(_NO_STORE_HEADERS))


async def cardex_admin_trader_payment(request: web.Request) -> web.Response:
    auth = await _auth(request, require_admin=True)
    trader_id = str(request.match_info.get("trader_id") or "").strip()
    body = await request.json()
    try:
        row = await post_trader_payment(
            actor_user_id=str(auth["user_id"]),
            trader_id=trader_id,
            amount_usd=parse_decimal(str(body.get("amount_usd") or "")),
            method=str(body.get("method") or "").strip() or None,
            reference_no=str(body.get("reference_no") or "").strip() or None,
            notes=str(body.get("notes") or "").strip() or None,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc) or "payment failed")
    return web.json_response({"payment": {"id": str(row.get("_id") or ""), "amount_usd": _money(row.get("amount_usd"))}}, headers=dict(_NO_STORE_HEADERS))


async def cardex_admin_trader_batch(request: web.Request) -> web.Response:
    auth = await _auth(request, require_admin=True)
    trader_id = str(request.match_info.get("trader_id") or "").strip()
    body = await request.json()
    raw_card_ids = body.get("card_ids") or []
    if isinstance(raw_card_ids, str):
        card_ids = [part.strip() for part in raw_card_ids.replace("\n", ",").split(",") if part.strip()]
    else:
        card_ids = [str(part).strip() for part in raw_card_ids if str(part).strip()]
    try:
        row = await create_trader_batch(
            actor_user_id=str(auth["user_id"]),
            trader_id=trader_id,
            card_ids=card_ids,
            notes=str(body.get("notes") or "").strip() or None,
            mark_sent=bool(body.get("mark_sent", True)),
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc) or "batch creation failed")
    return web.json_response({"batch": _batch_payload(row)}, headers=dict(_NO_STORE_HEADERS))


async def cardex_create_withdrawal(request: web.Request) -> web.Response:
    auth = await _auth(request)
    card_user = await _card_user_from_auth(auth)
    body = await request.json()
    try:
        amount = parse_decimal(str(body.get("amount_usd") or ""))
    except ValueError:
        raise web.HTTPBadRequest(text="invalid withdrawal amount")
    notes = str(body.get("notes") or "").strip()
    if len(notes) < 3:
        raise web.HTTPBadRequest(text="payout details are too short")
    try:
        row = await create_withdrawal(
            user_id=str(card_user.get("_id")),
            requested_usd_amount=amount,
            payout_currency=str(body.get("payout_currency") or "USD"),
            notes=notes,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc) or "withdrawal rejected")
    return web.json_response({"withdrawal": _withdrawal_payload(row)}, headers=dict(_NO_STORE_HEADERS))


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
    auth = await _auth(request, require_admin=True)
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
    return web.json_response({"rule": _rule_payload(row, include_private=True)}, headers=dict(_NO_STORE_HEADERS))


async def cardex_price_delete(request: web.Request) -> web.Response:
    auth = await _auth(request, require_admin=True)
    rule_id = str(request.match_info.get("rule_id") or "").strip()
    if rule_id.startswith("lona-cardex:"):
        return web.json_response({"ok": True, "readonly": True}, headers=dict(_NO_STORE_HEADERS))
    deleted = await deactivate_pricing_rule(actor_user_id=str(auth["user_id"]), pricing_rule_id=rule_id)
    if not deleted:
        raise web.HTTPNotFound(text="pricing not found")
    return web.json_response({"ok": True}, headers=dict(_NO_STORE_HEADERS))


async def cardex_quote_submission(request: web.Request) -> web.Response:
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
    return web.json_response({"quote": _quote_payload(quote)}, headers=dict(_NO_STORE_HEADERS))


async def cardex_submit_card(request: web.Request) -> web.Response:
    auth = await _auth(request)
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
            "quote": _quote_payload(quote),
        },
        headers=dict(_NO_STORE_HEADERS),
    )


def register_cardex_routes(app: web.Application) -> None:
    app.router.add_get("/mini/cardex", cardex_index)
    app.router.add_get("/mini/cardex/static/{name}", cardex_static)
    app.router.add_get("/mini/cardex/api/prices", cardex_prices)
    app.router.add_get("/mini/cardex/api/wallet", cardex_wallet)
    app.router.add_get("/mini/cardex/api/cards", cardex_my_cards)
    app.router.add_get("/mini/cardex/api/withdrawals", cardex_withdrawals)
    app.router.add_get("/mini/cardex/api/admin/queue", cardex_admin_queue)
    app.router.add_post("/mini/cardex/api/prices", cardex_price_create)
    app.router.add_delete("/mini/cardex/api/prices/{rule_id}", cardex_price_delete)
    app.router.add_post("/mini/cardex/api/quote", cardex_quote_submission)
    app.router.add_post("/mini/cardex/api/submit", cardex_submit_card)
    app.router.add_post("/mini/cardex/api/withdrawals", cardex_create_withdrawal)
    app.router.add_post("/mini/cardex/api/admin/cards/{card_id}", cardex_admin_card_action)
    app.router.add_post("/mini/cardex/api/admin/withdrawals/{withdrawal_id}", cardex_admin_withdrawal_action)
    app.router.add_post("/mini/cardex/api/admin/missing-pricing/{missing_id}", cardex_admin_missing_pricing_action)
    app.router.add_post("/mini/cardex/api/admin/traders", cardex_admin_create_trader)
    app.router.add_get("/mini/cardex/api/admin/traders/{trader_id}/statement", cardex_admin_trader_statement)
    app.router.add_post("/mini/cardex/api/admin/traders/{trader_id}/payments", cardex_admin_trader_payment)
    app.router.add_post("/mini/cardex/api/admin/traders/{trader_id}/batches", cardex_admin_trader_batch)
