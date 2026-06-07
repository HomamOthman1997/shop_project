from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
import re
from typing import Any

from aiohttp import web
from bson import ObjectId
from pymongo import ReturnDocument

from database.api_keys_repo import create_api_key, revoke_api_key, serialize_api_key_doc
from database.bot_logs_repo import bind_bot_logs_target, get_bot_logs_target
from database.digital_products_config_repo import (
    get_digital_products_markup_percent,
    set_digital_products_markup_percent,
)
from database.digital_provider_sources_repo import (
    approve_provider_source,
    disable_provider_source,
    list_price_watch_runs,
    list_provider_sources,
)
from database.financial_ledger import (
    credit_reseller_main_wallet,
    get_reseller_wallet_balance,
    list_user_wallet_entries,
    scan_financial_anomalies,
)
from database.mongo import db
from database.numbers_config_repo import get_numbers_markup_percent, set_numbers_markup_percent
from database.owner_payment_settings_repo import (
    get_owner_exchange_rate,
    get_owner_payment_methods,
    set_owner_exchange_rate,
    update_owner_payment_method,
)
from database.orders_repo import list_api_temp_refund_support_reviews, resolve_api_temp_refund_support_review
from database.provider_balance_alert_repo import (
    bind_provider_balance_alert_target,
    get_provider_balance_alert_settings,
    set_provider_balance_alert_enabled,
    set_provider_balance_alert_threshold,
)
from database.provider_webhook_repo import list_provider_webhook_events
from database.recharge_repo import update_recharge_request
from database.support_tickets_repo import (
    get_support_ticket,
    mark_support_ticket_bug_triage,
    mark_support_ticket_solved,
)
from database.support_topics_repo import bind_support_target, get_all_support_targets
from database.webhooks_repo import create_webhook, revoke_webhook, serialize_webhook_doc
from services.digital_products.api import _order_payload, execute_manual_order_action
from services.numbers.api import _refund_review_payload
from services.numbers.provider_readiness import provider_readiness_rows
from services.numbers.provider_webhook_service import replay_provider_webhook_event
from services.digital_products.bittopup_scraper import run_bittopup_price_watch
from services.platform.api_auth import ApiAuthContext
from services.platform.api_keys_api import _ALLOWED_CUSTOMER_SCOPES
from services.platform.telegram_delivery import send_owner_broadcast, send_ticket_message
from services.platform.webhooks_api import ALLOWED_WEBHOOK_EVENTS, _valid_https_url
from services.platform.website_auth import require_website_owner
from services.subscriptions.bot_subscription_service import (
    activate_bot_subscription,
    set_bot_subscription_plan,
    sync_bot_subscription,
)
from handlers.owner_requests import review_bot_creation_request
from config import settings


_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _management_sections() -> list[dict[str, Any]]:
    return [
        {
            "key": "operations",
            "title": "Operations",
            "items": [
                {"key": "digital_orders", "title": "Digital manual orders", "status": "available", "endpoint": "/api/v1/digital/admin/orders"},
                {"key": "numbers_refunds", "title": "Numbers refund reviews", "status": "available", "endpoint": "/api/v1/numbers/ops/refund-reviews"},
                {"key": "provider_readiness", "title": "Provider readiness", "status": "available", "endpoint": "/api/v1/owner/provider-readiness"},
                {"key": "provider_webhooks", "title": "Provider webhook audit", "status": "available", "endpoint": "/api/v1/owner/provider-webhook-events"},
                {"key": "recharge_reviews", "title": "User and reseller topup reviews", "status": "available", "endpoint": "/api/v1/owner/recharge-reviews"},
                {"key": "identity_reviews", "title": "Identity verification reviews", "status": "available", "endpoint": "/api/v1/owner/identity-reviews"},
            ],
        },
        {
            "key": "finance",
            "title": "Finance and pricing",
            "items": [
                {"key": "payment_methods", "title": "Owner payment methods", "status": "available", "endpoint": "/api/v1/owner/settings"},
                {"key": "exchange_rate", "title": "Owner exchange rate", "status": "available", "endpoint": "/api/v1/owner/settings"},
                {"key": "numbers_margin", "title": "Numbers margin", "status": "available", "endpoint": "/api/v1/owner/settings"},
                {"key": "digital_margin", "title": "Digital products margin", "status": "available", "endpoint": "/api/v1/owner/settings"},
                {"key": "reseller_deposits", "title": "Reseller deposits and subscriptions", "status": "available", "endpoint": "/api/v1/owner/reseller-deposits"},
            ],
        },
        {
            "key": "catalog",
            "title": "Catalog and fulfillment",
            "items": [
                {"key": "digital_sources", "title": "Digital provider sources", "status": "available", "endpoint": "/api/v1/digital/source-diagnostics"},
                {"key": "bittopup_watch", "title": "BitTopup price watch", "status": "available", "endpoint": "/api/v1/owner/digital-provider-sources"},
                {"key": "cardex_admin", "title": "Card exchange admin queue", "status": "miniapp", "endpoint": "/mini/cardex"},
            ],
        },
        {
            "key": "system",
            "title": "System and communication",
            "items": [
                {"key": "support_inbox", "title": "Support inbox", "status": "available", "endpoint": "/api/v1/owner/support-tickets"},
                {"key": "support_routing", "title": "Support topics and routing", "status": "available", "endpoint": "/api/v1/owner/routing-targets/{target_key}"},
                {"key": "logs_routing", "title": "Logs and alert routing", "status": "available", "endpoint": "/api/v1/owner/routing-targets/{target_key}"},
                {"key": "provider_alerts", "title": "Provider balance alerts", "status": "available", "endpoint": "/api/v1/owner/settings"},
                {"key": "broadcast", "title": "Broadcast", "status": "available", "endpoint": "/api/v1/owner/broadcast"},
                {"key": "api_keys", "title": "API key management", "status": "available", "endpoint": "/api/v1/owner/api-keys"},
                {"key": "webhooks", "title": "Customer webhook management", "status": "available", "endpoint": "/api/v1/owner/webhooks"},
                {"key": "bot_subscriptions", "title": "Bot subscriptions", "status": "available", "endpoint": "/api/v1/owner/bots"},
            ],
        },
    ]


async def _count(collection: str, query: dict[str, Any]) -> int:
    return int(await db[collection].count_documents(query) or 0)


async def _system_setting(doc_id: str) -> dict[str, Any] | None:
    return await db.system_settings.find_one({"_id": str(doc_id)})


async def _recharge_request(request_id: ObjectId) -> dict[str, Any] | None:
    return await db.recharge_requests.find_one({"_id": request_id})


async def _recent(
    collection: str,
    query: dict[str, Any],
    *,
    projection: dict[str, int],
    limit: int = 8,
) -> list[dict[str, Any]]:
    cursor = db[collection].find(query, projection).sort("created_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


def _text(value: Any) -> str:
    return str(value or "")


async def _write_owner_audit(
    *,
    actor_id: int,
    actor_email: str,
    action: str,
    target_type: str = "",
    target_id: Any = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        await db.owner_admin_audit.insert_one(
            {
                "actor_id": int(actor_id),
                "actor_email": str(actor_email or ""),
                "action": str(action or ""),
                "target_type": str(target_type or ""),
                "target_id": _text(target_id),
                "metadata": metadata or {},
                "created_at": datetime.now(UTC),
            }
        )
    except Exception:
        logging.getLogger("owner.audit").exception("Could not write owner audit event: %s", action)


def _money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except Exception:
        return 0.0


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _public_account_payload(account: dict[str, Any] | None, user: dict[str, Any] | None = None) -> dict[str, Any]:
    account = account or {}
    user = user or {}
    customer_id = _safe_int(account.get("customer_id") or user.get("telegram_id")) or 0
    telegram_id = _safe_int(account.get("telegram_id"))
    return {
        "id": _text(account.get("_id")),
        "customer_id": customer_id,
        "email": _text(account.get("email")),
        "email_verified": bool(account.get("email_verified_at") or user.get("email_verified_at")),
        "email_verified_at": _iso_value(account.get("email_verified_at") or user.get("email_verified_at")),
        "telegram_id": telegram_id,
        "telegram_linked_at": _iso_value(account.get("telegram_linked_at")),
        "username": _text(user.get("username")),
        "identity_status": _text(account.get("identity_status") or "unsubmitted"),
        "status": _text(account.get("status") or "active"),
        "banned": bool(user.get("banned")),
        "created_at": _iso_value(account.get("created_at") or user.get("created_at")),
        "updated_at": _iso_value(account.get("updated_at")),
    }


async def _find_owner_user_subject(customer_id: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    account = await db.website_accounts.find_one({"customer_id": int(customer_id)})
    user_query: dict[str, Any] = {"telegram_id": int(customer_id)}
    if account and account.get("telegram_id"):
        user_query = {"telegram_id": {"$in": [int(customer_id), int(account["telegram_id"])]}}
    user = await db.users.find_one(user_query)
    return account, user


async def owner_users(request: web.Request) -> web.Response:
    await require_website_owner(request)
    q = str(request.query.get("q") or "").strip()
    limit = _limit(request, 50)
    query: dict[str, Any] = {}
    if q:
        escaped = re.escape(q)
        ors: list[dict[str, Any]] = [
            {"email": {"$regex": escaped, "$options": "i"}},
            {"email_normalized": {"$regex": escaped.lower(), "$options": "i"}},
        ]
        username_rows = await db.users.find(
            {"username": {"$regex": escaped, "$options": "i"}},
            {"telegram_id": 1},
        ).limit(20).to_list(length=20)
        username_ids = [int(row.get("telegram_id")) for row in username_rows if _safe_int(row.get("telegram_id")) is not None]
        if username_ids:
            ors.extend([{"customer_id": {"$in": username_ids}}, {"telegram_id": {"$in": username_ids}}])
        numeric = _safe_int(q)
        if numeric is not None:
            ors.extend([{"customer_id": numeric}, {"telegram_id": numeric}])
        query = {"$or": ors}
    accounts = await db.website_accounts.find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    customer_ids = [int(row.get("customer_id")) for row in accounts if _safe_int(row.get("customer_id")) is not None]
    telegram_ids = [int(row.get("telegram_id")) for row in accounts if _safe_int(row.get("telegram_id")) is not None]
    users_by_id: dict[int, dict[str, Any]] = {}
    if customer_ids or telegram_ids:
        user_rows = await db.users.find({"telegram_id": {"$in": list(set(customer_ids + telegram_ids))}}).to_list(length=None)
        users_by_id = {int(row.get("telegram_id")): row for row in user_rows if _safe_int(row.get("telegram_id")) is not None}
    rows = []
    for account in accounts:
        customer_id = _safe_int(account.get("customer_id")) or 0
        telegram_id = _safe_int(account.get("telegram_id"))
        user = users_by_id.get(customer_id) or (users_by_id.get(telegram_id) if telegram_id is not None else None) or {}
        payload = _public_account_payload(account, user)
        wallet = await db.wallets.find_one(
            {
                "owner_type": "user",
                "owner_id": int(customer_id),
                "reseller_id": int(customer_id),
                "wallet_type": "user",
            }
        )
        payload["balance"] = _money((wallet or {}).get("balance"))
        rows.append(payload)
    return web.json_response({"ok": True, "users": rows}, headers=dict(_NO_STORE_HEADERS))


async def owner_user_detail(request: web.Request) -> web.Response:
    await require_website_owner(request)
    customer_id = _safe_int(request.match_info.get("customer_id"))
    if customer_id is None:
        return web.json_response({"ok": False, "message": "Invalid customer id."}, status=400, headers=dict(_NO_STORE_HEADERS))
    account, user = await _find_owner_user_subject(customer_id)
    if not account and not user:
        return web.json_response({"ok": False, "message": "User was not found."}, status=404, headers=dict(_NO_STORE_HEADERS))
    wallet = await db.wallets.find_one(
        {"owner_type": "user", "owner_id": int(customer_id), "reseller_id": int(customer_id), "wallet_type": "user"}
    )
    entries = await list_user_wallet_entries(int(customer_id), int(customer_id), limit=12)
    order_rows = await db.orders.find({"user_id": int(customer_id)}).sort("created_at", -1).limit(12).to_list(length=12)
    recharge_rows = await db.recharge_requests.find({"user_id": int(customer_id)}).sort("created_at", -1).limit(8).to_list(length=8)
    return web.json_response(
        {
            "ok": True,
            "user": _public_account_payload(account, user),
            "wallet": {"balance": _money((wallet or {}).get("balance")), "wallet_key": _text((wallet or {}).get("wallet_key"))},
            "ledger": [
                {
                    "id": _text(row.get("_id")),
                    "direction": _text(row.get("direction")),
                    "amount": _money(row.get("amount")),
                    "reason": _text(row.get("reason")),
                    "balance_after": _money(row.get("balance_after")),
                    "order_id": _text(row.get("order_id")),
                    "created_at": _iso_value(row.get("created_at")),
                }
                for row in entries
            ],
            "orders": [
                {
                    "id": _text(row.get("_id")),
                    "status": _text(row.get("status")),
                    "service_type": _text(row.get("service_type") or row.get("number_mode")),
                    "title": _text(row.get("manual_item_name") or row.get("service_ref_id") or row.get("service_id")),
                    "amount": _money(row.get("retail_amount", row.get("selling_price", row.get("price")))),
                    "created_at": _iso_value(row.get("created_at")),
                }
                for row in order_rows
            ],
            "recharges": [
                {
                    "id": _text(row.get("_id")),
                    "status": _text(row.get("status")),
                    "method": _text(row.get("method")),
                    "amount": _money(row.get("approved_amount") if row.get("approved_amount") is not None else row.get("amount")),
                    "created_at": _iso_value(row.get("created_at")),
                }
                for row in recharge_rows
            ],
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def owner_user_action(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    customer_id = _safe_int(request.match_info.get("customer_id"))
    if customer_id is None:
        return web.json_response({"ok": False, "message": "Invalid customer id."}, status=400, headers=dict(_NO_STORE_HEADERS))
    payload = await request.json()
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"ban", "unban"}:
        return web.json_response({"ok": False, "message": "Unsupported user action."}, status=400, headers=dict(_NO_STORE_HEADERS))
    banned = action == "ban"
    now = datetime.now(UTC)
    result = await db.users.update_one(
        {"telegram_id": int(customer_id)},
        {
            "$set": {
                "banned": banned,
                "admin_updated_at": now,
                "admin_updated_by": int(owner.customer_id),
            }
        },
        upsert=False,
    )
    if not result.matched_count:
        return web.json_response({"ok": False, "message": "User was not found."}, status=404, headers=dict(_NO_STORE_HEADERS))
    await db.website_accounts.update_one(
        {"customer_id": int(customer_id)},
        {"$set": {"status": "banned" if banned else "active", "updated_at": now}},
    )
    await _write_owner_audit(
        actor_id=owner.customer_id,
        actor_email=owner.email,
        action=f"user.{action}",
        target_type="user",
        target_id=customer_id,
    )
    account, user = await _find_owner_user_subject(customer_id)
    return web.json_response({"ok": True, "user": _public_account_payload(account, user)}, headers=dict(_NO_STORE_HEADERS))


async def owner_finance_audit(request: web.Request) -> web.Response:
    await require_website_owner(request)
    try:
        days = max(1, min(365, int(request.query.get("days") or 30)))
    except Exception:
        days = 30
    report = await scan_financial_anomalies(days=days, max_rows=_limit(request, 30))
    return web.json_response({"ok": True, "audit": report}, headers=dict(_NO_STORE_HEADERS))


async def _mongo_health() -> dict[str, Any]:
    try:
        result = await db.command("ping")
        return {"status": "healthy" if int((result or {}).get("ok") or 0) == 1 else "degraded"}
    except Exception as exc:
        return {"status": "unavailable", "reason": str(exc)[:240]}


async def owner_system_status(request: web.Request) -> web.Response:
    await require_website_owner(request)
    mongo, logs, alerts, support, active_bots, inactive_bots, pending_orders, pending_recharges = await asyncio.gather(
        _mongo_health(),
        get_bot_logs_target(),
        get_provider_balance_alert_settings(),
        get_all_support_targets(),
        _count("bots", {"active": True}),
        _count("bots", {"active": {"$ne": True}}),
        _count("orders", {"status": {"$in": ["pending", "paid", "processing", "active", "waiting_code"]}}),
        _count("recharge_requests", {"status": {"$in": ["pending", "need_more_proof"]}}),
    )
    readiness = provider_readiness_rows()
    configured_providers = sum(1 for row in readiness if str(row.get("status") or "") == "ready")
    support_bound = sum(1 for row in support.values() if isinstance((row or {}).get("chat_id"), int))
    return web.json_response(
        {
            "ok": True,
            "system": {
                "mongo": mongo,
                "website_enabled": bool(settings.website_enabled),
                "bot_version": int(settings.bot_version),
                "active_bots": active_bots,
                "inactive_bots": inactive_bots,
                "pending_orders": pending_orders,
                "pending_recharges": pending_recharges,
                "provider_readiness": {"ready": configured_providers, "total": len(readiness)},
                "routing": {
                    "logs_bound": bool(logs),
                    "provider_alerts_bound": isinstance(alerts.get("chat_id"), int),
                    "provider_alerts_enabled": bool(alerts.get("enabled")),
                    "support_bound": support_bound,
                    "support_total": 4,
                },
            },
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def owner_system_test_log(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    target = await get_bot_logs_target()
    if not target:
        return web.json_response(
            {"ok": False, "code": "logs_target_missing", "message": "Configure the logs routing target first."},
            status=409,
            headers=dict(_NO_STORE_HEADERS),
        )
    logging.getLogger("owner.logs").error(
        "Owner test log emitted from website dashboard by %s (%s).",
        owner.email,
        owner.customer_id,
    )
    await _write_owner_audit(
        actor_id=owner.customer_id,
        actor_email=owner.email,
        action="system.test_log",
        target_type="routing",
        target_id="logs",
    )
    return web.json_response({"ok": True, "target": _routing_target(target)}, headers=dict(_NO_STORE_HEADERS))


async def owner_admin_audit(request: web.Request) -> web.Response:
    await require_website_owner(request)
    rows = await db.owner_admin_audit.find({}).sort("created_at", -1).limit(_limit(request, 50)).to_list(length=_limit(request, 50))
    return web.json_response(
        {
            "ok": True,
            "events": [
                {
                    "id": _text(row.get("_id")),
                    "actor_id": row.get("actor_id"),
                    "actor_email": _text(row.get("actor_email")),
                    "action": _text(row.get("action")),
                    "target_type": _text(row.get("target_type")),
                    "target_id": _text(row.get("target_id")),
                    "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
                    "created_at": _iso_value(row.get("created_at")),
                }
                for row in rows
            ],
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def owner_resellers(request: web.Request) -> web.Response:
    await require_website_owner(request)
    q = str(request.query.get("q") or "").strip()
    limit = _limit(request, 50)
    bot_query: dict[str, Any] = {}
    numeric = _safe_int(q) if q else None
    reseller_ids: set[int] = set()
    if q:
        escaped = re.escape(q)
        user_matches = await db.users.find(
            {"username": {"$regex": escaped, "$options": "i"}},
            {"telegram_id": 1},
        ).limit(30).to_list(length=30)
        user_ids = [int(row.get("telegram_id")) for row in user_matches if _safe_int(row.get("telegram_id")) is not None]
        bot_query = {
            "$or": [
                {"username": {"$regex": escaped, "$options": "i"}},
                {"bot_username": {"$regex": escaped, "$options": "i"}},
                {"reseller.bot_username": {"$regex": escaped, "$options": "i"}},
            ]
        }
        if user_ids:
            bot_query["$or"].append({"owner_id": {"$in": user_ids}})
            reseller_ids = set(user_ids)
        if numeric is not None:
            bot_query["$or"].extend([{"owner_id": numeric}, {"bot_id": numeric}])
            reseller_ids = {numeric}
    bots = await db.bots.find(bot_query, {"token": 0}).sort("created_at", -1).limit(200).to_list(length=200)
    reseller_ids.update(int(row.get("owner_id")) for row in bots if _safe_int(row.get("owner_id")) is not None)
    if not q:
        wallet_rows = await db.wallets.find({"owner_type": "reseller"}).limit(500).to_list(length=500)
        reseller_ids.update(int(row.get("owner_id")) for row in wallet_rows if _safe_int(row.get("owner_id")) is not None)
    reseller_ids = set(list(reseller_ids)[:limit])
    users = await db.users.find({"telegram_id": {"$in": list(reseller_ids)}}).to_list(length=None) if reseller_ids else []
    users_by_id = {int(row.get("telegram_id")): row for row in users if _safe_int(row.get("telegram_id")) is not None}
    bots_by_owner: dict[int, list[dict[str, Any]]] = {}
    for bot in bots:
        owner_id = _safe_int(bot.get("owner_id"))
        if owner_id in reseller_ids:
            bots_by_owner.setdefault(int(owner_id), []).append(bot)
    rows = []
    for reseller_id in sorted(reseller_ids):
        main_balance, earnings_balance = await asyncio.gather(
            get_reseller_wallet_balance(reseller_id, wallet_type="main"),
            get_reseller_wallet_balance(reseller_id, wallet_type="earnings"),
        )
        owner_bots = bots_by_owner.get(reseller_id, [])
        user = users_by_id.get(reseller_id) or {}
        rows.append(
            {
                "reseller_id": reseller_id,
                "username": _text(user.get("username")),
                "main_balance": _money(main_balance),
                "earnings_balance": _money(earnings_balance),
                "bots_count": len(owner_bots),
                "active_bots_count": sum(1 for bot in owner_bots if bool(bot.get("active"))),
                "bots": [_bot_payload(bot) for bot in owner_bots[:5]],
            }
        )
    return web.json_response({"ok": True, "resellers": rows}, headers=dict(_NO_STORE_HEADERS))


async def owner_reseller_detail(request: web.Request) -> web.Response:
    await require_website_owner(request)
    reseller_id = _safe_int(request.match_info.get("reseller_id"))
    if reseller_id is None:
        return web.json_response({"ok": False, "message": "Invalid reseller id."}, status=400, headers=dict(_NO_STORE_HEADERS))
    user, bots, wallets, ledger, recharges, orders = await asyncio.gather(
        db.users.find_one({"telegram_id": int(reseller_id)}),
        db.bots.find({"owner_id": int(reseller_id)}, {"token": 0}).sort("created_at", -1).limit(50).to_list(length=50),
        db.wallets.find({"owner_type": "reseller", "owner_id": int(reseller_id)}).to_list(length=None),
        db.ledger_entries.find({"owner_type": "reseller", "owner_id": int(reseller_id)}).sort("created_at", -1).limit(20).to_list(length=20),
        db.recharge_requests.find({"reseller_id": int(reseller_id)}).sort("created_at", -1).limit(15).to_list(length=15),
        db.orders.find({"reseller_id": int(reseller_id)}).sort("created_at", -1).limit(15).to_list(length=15),
    )
    if not user and not bots and not wallets:
        return web.json_response({"ok": False, "message": "Reseller was not found."}, status=404, headers=dict(_NO_STORE_HEADERS))
    return web.json_response(
        {
            "ok": True,
            "reseller": {
                "reseller_id": int(reseller_id),
                "username": _text((user or {}).get("username")),
                "banned": bool((user or {}).get("banned")),
                "wallets": [{"wallet_type": _text(row.get("wallet_type")), "balance": _money(row.get("balance"))} for row in wallets],
                "bots": [_bot_payload(row) for row in bots],
                "ledger": [
                    {
                        "id": _text(row.get("_id")),
                        "direction": _text(row.get("direction")),
                        "amount": _money(row.get("amount")),
                        "reason": _text(row.get("reason")),
                        "balance_after": _money(row.get("balance_after")),
                        "created_at": _iso_value(row.get("created_at")),
                    }
                    for row in ledger
                ],
                "recharges": [_recharge_payload(row) for row in recharges],
                "orders": [
                    {
                        "id": _text(row.get("_id")),
                        "status": _text(row.get("status")),
                        "service_type": _text(row.get("service_type") or row.get("number_mode")),
                        "user_id": row.get("user_id"),
                        "amount": _money(row.get("retail_amount", row.get("selling_price", row.get("price")))),
                        "created_at": _iso_value(row.get("created_at")),
                    }
                    for row in orders
                ],
            },
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def owner_dashboard(request: web.Request) -> web.Response:
    auth = await require_website_owner(request)
    metric_queries = {
        "website_accounts": ("website_accounts", {"status": "active"}),
        "verified_accounts": ("website_accounts", {"email_verified_at": {"$exists": True}}),
        "pending_identity": ("identity_verification_requests", {"status": "pending"}),
        "pending_user_topups": ("recharge_requests", {"status": "pending", "wallet_type": {"$nin": ["reseller_main", "main", "reseller"]}}),
        "pending_reseller_topups": ("recharge_requests", {"status": "pending", "wallet_type": {"$in": ["reseller_main", "main", "reseller"]}}),
        "open_support_tickets": ("support_tickets", {"status": {"$in": ["open", "awaiting_user", "awaiting_admin", "replied"]}}),
        "open_numbers_orders": ("orders", {"service_type": {"$in": ["temp", "rental"]}, "status": {"$in": ["pending", "paid", "active", "waiting_code"]}}),
        "pending_digital_orders": ("orders", {"fulfillment_mode": "manual_topup", "manual_fulfillment_status": "pending"}),
        "active_bots": ("bots", {"active": True}),
    }
    values = await asyncio.gather(*(_count(collection, query) for collection, query in metric_queries.values()))
    metrics = dict(zip(metric_queries, values))
    return web.json_response(
        {
            "ok": True,
            "owner": {"email": auth.email, "customer_id": auth.customer_id},
            "metrics": metrics,
            "sections": _management_sections(),
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def owner_queues(request: web.Request) -> web.Response:
    await require_website_owner(request)
    recharge_rows, identity_rows, digital_rows, support_rows = await asyncio.gather(
        _recent(
            "recharge_requests",
            {"status": {"$in": ["pending", "need_more_proof"]}},
            projection={"user_id": 1, "status": 1, "method": 1, "amount": 1, "paid_amount": 1, "created_at": 1},
        ),
        _recent(
            "identity_verification_requests",
            {"status": "pending"},
            projection={"account_id": 1, "full_name": 1, "country": 1, "id_type": 1, "status": 1, "created_at": 1},
        ),
        _recent(
            "orders",
            {"fulfillment_mode": "manual_topup", "manual_fulfillment_status": "pending"},
            projection={"user_id": 1, "status": 1, "manual_item_name": 1, "manual_game_name": 1, "price": 1, "created_at": 1},
        ),
        _recent(
            "support_tickets",
            {"status": {"$in": ["open", "awaiting_user", "awaiting_admin", "replied"]}},
            projection={"ticket_no": 1, "user_id": 1, "category": 1, "status": 1, "created_at": 1, "opened_at": 1},
        ),
    )
    return web.json_response(
        {
            "ok": True,
            "queues": {
                "recharge": [
                    {
                        "id": _text(row.get("_id")),
                        "user_id": int(row.get("user_id") or 0),
                        "status": _text(row.get("status")),
                        "title": _text(row.get("method") or "Recharge request"),
                        "detail": _text(row.get("paid_amount") or row.get("amount")),
                    }
                    for row in recharge_rows
                ],
                "identity": [
                    {
                        "id": _text(row.get("_id")),
                        "status": _text(row.get("status")),
                        "title": _text(row.get("full_name") or "Identity review"),
                        "detail": " / ".join(filter(None, [_text(row.get("country")), _text(row.get("id_type"))])),
                    }
                    for row in identity_rows
                ],
                "digital": [
                    {
                        "id": _text(row.get("_id")),
                        "user_id": int(row.get("user_id") or 0),
                        "status": _text(row.get("status") or "pending"),
                        "title": _text(row.get("manual_item_name") or row.get("manual_game_name") or "Digital order"),
                        "detail": _text(row.get("price")),
                    }
                    for row in digital_rows
                ],
                "support": [
                    {
                        "id": _text(row.get("_id")),
                        "user_id": int(row.get("user_id") or 0),
                        "status": _text(row.get("status")),
                        "title": f"Ticket #{int(row.get('ticket_no') or 0)}",
                        "detail": _text(row.get("category")),
                    }
                    for row in support_rows
                ],
            },
        },
        headers=dict(_NO_STORE_HEADERS),
    )


def _owner_digital_auth(*, customer_id: int) -> ApiAuthContext:
    return ApiAuthContext(
        key_id="website-owner",
        user_id=int(customer_id),
        reseller_id=int(customer_id),
        scopes=("*",),
        name="website-owner",
    )


def _iso_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return _text(value)


def _owner_digital_available_actions(order: dict[str, Any]) -> list[str]:
    status = str(order.get("status") or "").strip().lower()
    manual_status = str(order.get("manual_fulfillment_status") or "").strip().lower()
    if status in {"success", "done", "refunded", "failed", "cancelled"} or manual_status in {"completed", "refunded"}:
        return []
    return ["claim", "auto_api", "future", "complete", "refund"]


def _owner_digital_order_payload(order: dict[str, Any]) -> dict[str, Any]:
    order = dict(order or {})
    payload = _order_payload(order)
    payload["available_actions"] = _owner_digital_available_actions(order)
    payload["owner_details"] = {
        "user_id": _text(order.get("user_id")),
        "reseller_id": _text(order.get("reseller_id")),
        "source": _text(order.get("api_order_source") or order.get("source") or order.get("number_mode") or order.get("service_type")),
        "fulfillment_mode": _text(order.get("fulfillment_mode")),
        "fulfillment_status": _text(order.get("manual_fulfillment_status")),
        "execution_route": _text(order.get("manual_execution_route")),
        "route_updated_by": _text(order.get("manual_route_updated_by")),
        "route_updated_at": _iso_value(order.get("manual_route_updated_at")),
        "fulfilled_by": _text(order.get("manual_fulfilled_by")),
        "fulfilled_at": _iso_value(order.get("manual_fulfilled_at")),
        "refunded_by": _text(order.get("manual_refunded_by")),
        "refunded_at": _iso_value(order.get("manual_refunded_at")),
        "provider": _text(order.get("provider_code") or order.get("provider")),
        "provider_ref_id": _text(order.get("provider_ref_id") or order.get("service_ref_id")),
        "provider_order_id": _text(order.get("provider_order_id")),
        "created_at": _iso_value(order.get("created_at")),
        "completed_at": _iso_value(order.get("completed_at")),
        "updated_at": _iso_value(order.get("updated_at") or order.get("manual_route_updated_at")),
        "action_note": _text(order.get("manual_action_note")),
    }
    return payload


async def owner_digital_orders(request: web.Request) -> web.Response:
    await require_website_owner(request)
    try:
        limit = max(1, min(100, int(request.query.get("limit") or 30)))
    except Exception:
        limit = 30
    status_filter = str(request.query.get("status") or "pending").strip().lower()
    query: dict[str, Any] = {
        "fulfillment_mode": "manual_topup",
        "$or": [{"service_type": "core_digital_products"}, {"number_mode": "digital_products"}],
    }
    if status_filter not in {"", "all", "*"}:
        if status_filter == "completed":
            query["$and"] = [{"$or": [{"manual_fulfillment_status": "completed"}, {"status": {"$in": ["success", "done"]}}]}]
        elif status_filter == "refunded":
            query["$and"] = [{"$or": [{"manual_fulfillment_status": "refunded"}, {"status": "refunded"}]}]
        else:
            query["manual_fulfillment_status"] = status_filter
    rows = await db.orders.find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    return web.json_response(
        {"ok": True, "status": status_filter or "all", "orders": [_owner_digital_order_payload(row) for row in rows]},
        headers=dict(_NO_STORE_HEADERS),
    )


async def owner_digital_order_action(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    auth = _owner_digital_auth(customer_id=owner.customer_id)
    order_id = str(request.match_info.get("order_id") or "").strip()
    return await execute_manual_order_action(auth=auth, order_id=order_id, body=body)


async def owner_numbers_refund_reviews(request: web.Request) -> web.Response:
    await require_website_owner(request)
    include_resolved = str(request.query.get("include_resolved") or "").strip().lower() in {"1", "true", "yes"}
    try:
        limit = max(1, min(100, int(request.query.get("limit") or 30)))
    except Exception:
        limit = 30
    rows = await list_api_temp_refund_support_reviews(limit=limit, reseller_id=None, include_resolved=include_resolved)
    return web.json_response(
        {"ok": True, "reviews": [_refund_review_payload(row) for row in rows]},
        headers=dict(_NO_STORE_HEADERS),
    )


async def owner_resolve_numbers_refund_review(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    resolution = str((body or {}).get("resolution") or "").strip()
    if len(resolution) < 3:
        return web.json_response(
            {"ok": False, "code": "missing_resolution", "message": "Write a resolution before closing the review."},
            status=400,
            headers=dict(_NO_STORE_HEADERS),
        )
    order = await resolve_api_temp_refund_support_review(
        order_id=str(request.match_info.get("order_id") or "").strip(),
        actor_user_id=owner.customer_id,
        reseller_id=None,
        resolution=resolution,
        notes=str((body or {}).get("notes") or "").strip(),
    )
    if not isinstance(order, dict):
        return web.json_response(
            {"ok": False, "code": "review_not_found", "message": "Review was not found."},
            status=404,
            headers=dict(_NO_STORE_HEADERS),
        )
    return web.json_response({"ok": True, "review": _refund_review_payload(order)}, headers=dict(_NO_STORE_HEADERS))


def _routing_target(doc: dict[str, Any] | None) -> dict[str, Any]:
    row = doc or {}
    return {
        "bound": isinstance(row.get("chat_id"), int),
        "chat_id": row.get("chat_id") if isinstance(row.get("chat_id"), int) else None,
        "message_thread_id": row.get("message_thread_id") if isinstance(row.get("message_thread_id"), int) else None,
    }


def _parse_chat_target(body: dict[str, Any]) -> tuple[int, int | None]:
    chat_id = int((body or {}).get("chat_id") or 0)
    if chat_id == 0:
        raise ValueError("chat_id")
    raw_thread = (body or {}).get("message_thread_id")
    if raw_thread in {None, "", 0, "0"}:
        return chat_id, None
    thread_id = int(raw_thread)
    if thread_id < 0:
        raise ValueError("message_thread_id")
    return chat_id, thread_id


async def owner_settings(request: web.Request) -> web.Response:
    await require_website_owner(request)
    methods, exchange_rate, digital_markup, numbers_markup, alerts, support, logs, owner_target, topup_target = await asyncio.gather(
        get_owner_payment_methods(),
        get_owner_exchange_rate(),
        get_digital_products_markup_percent(),
        get_numbers_markup_percent(),
        get_provider_balance_alert_settings(),
        get_all_support_targets(),
        get_bot_logs_target(),
        _system_setting("owner_notifications"),
        _system_setting("owner_reseller_topups"),
    )
    return web.json_response(
        {
            "ok": True,
            "finance": {
                "exchange_rate": exchange_rate,
                "digital_markup_percent": digital_markup,
                "numbers_markup_percent": numbers_markup,
                "numbers_markup_editable": True,
                "payment_methods": methods,
            },
            "alerts": alerts,
            "routing": {
                "owner_notifications": _routing_target(owner_target),
                "reseller_topups": _routing_target(topup_target),
                "logs": _routing_target(logs),
                "provider_alerts": _routing_target(alerts),
                "support": {key: _routing_target(value) for key, value in support.items()},
            },
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def owner_update_routing_target(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
        chat_id, message_thread_id = _parse_chat_target(body or {})
    except Exception:
        return web.json_response(
            {"ok": False, "code": "invalid_routing_target", "message": "Provide a valid chat_id and optional message_thread_id."},
            status=400,
            headers=dict(_NO_STORE_HEADERS),
        )

    key = str(request.match_info.get("target_key") or "").strip().lower()
    now = datetime.now(UTC)
    if key == "owner_notifications":
        await db.system_settings.update_one(
            {"_id": "owner_notifications"},
            {"$set": {"chat_id": chat_id, "message_thread_id": message_thread_id, "updated_at": now}},
            upsert=True,
        )
    elif key in {"reseller_topups", "owner_reseller_topups"}:
        await db.system_settings.update_one(
            {"_id": "owner_reseller_topups"},
            {"$set": {"chat_id": chat_id, "message_thread_id": message_thread_id, "updated_at": now}},
            upsert=True,
        )
    elif key == "logs":
        await bind_bot_logs_target(chat_id=chat_id, message_thread_id=message_thread_id)
    elif key == "provider_alerts":
        await bind_provider_balance_alert_target(chat_id=chat_id, message_thread_id=message_thread_id)
    elif key.startswith("support_"):
        category = key.removeprefix("support_")
        if category not in {"proxies", "numbers", "services", "user_balance"}:
            return web.json_response({"ok": False, "message": "Unsupported routing target."}, status=400, headers=dict(_NO_STORE_HEADERS))
        await bind_support_target(category, chat_id=chat_id, message_thread_id=message_thread_id)
    else:
        return web.json_response({"ok": False, "message": "Unsupported routing target."}, status=400, headers=dict(_NO_STORE_HEADERS))
    await _write_owner_audit(
        actor_id=owner.customer_id,
        actor_email=owner.email,
        action="routing.update",
        target_type="routing",
        target_id=key,
        metadata={"chat_id": chat_id, "message_thread_id": message_thread_id},
    )
    return await owner_settings(request)


async def owner_update_settings(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    key = str((body or {}).get("key") or "").strip().lower()
    value = (body or {}).get("value")
    try:
        if key == "exchange_rate":
            parsed = float(value)
            if parsed <= 0 or parsed > 10_000_000:
                raise ValueError
            await set_owner_exchange_rate(parsed)
        elif key == "digital_markup_percent":
            parsed = float(value)
            if parsed < 0 or parsed > 500:
                raise ValueError
            await set_digital_products_markup_percent(parsed)
        elif key == "numbers_markup_percent":
            parsed = float(value)
            if parsed < 0 or parsed > 500:
                raise ValueError
            await set_numbers_markup_percent(parsed)
        elif key == "provider_alert_threshold":
            parsed = float(value)
            if parsed <= 0 or parsed > 10_000:
                raise ValueError
            await set_provider_balance_alert_threshold(parsed)
        elif key == "provider_alert_enabled":
            if not isinstance(value, bool):
                raise ValueError
            await set_provider_balance_alert_enabled(value)
        else:
            return web.json_response(
                {"ok": False, "code": "unsupported_setting", "message": "This setting cannot be changed here."},
                status=400,
                headers=dict(_NO_STORE_HEADERS),
            )
    except (TypeError, ValueError):
        return web.json_response(
            {"ok": False, "code": "invalid_setting_value", "message": "The supplied setting value is invalid."},
            status=400,
            headers=dict(_NO_STORE_HEADERS),
        )
    await _write_owner_audit(
        actor_id=owner.customer_id,
        actor_email=owner.email,
        action="settings.update",
        target_type="setting",
        target_id=key,
        metadata={"value": value},
    )
    return await owner_settings(request)


async def owner_update_payment_method(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    allowed = {"title", "target", "support", "instructions", "currency", "enabled"}
    updates = {key: value for key, value in (body or {}).items() if key in allowed}
    if not updates:
        return web.json_response(
            {"ok": False, "code": "missing_updates", "message": "No supported payment method fields were supplied."},
            status=400,
            headers=dict(_NO_STORE_HEADERS),
        )
    if "currency" in updates and str(updates["currency"]).upper() not in {"USD", "SYP"}:
        return web.json_response(
            {"ok": False, "code": "invalid_currency", "message": "Currency must be USD or SYP."},
            status=400,
            headers=dict(_NO_STORE_HEADERS),
        )
    if "enabled" in updates and not isinstance(updates["enabled"], bool):
        return web.json_response(
            {"ok": False, "code": "invalid_enabled", "message": "Enabled must be a boolean."},
            status=400,
            headers=dict(_NO_STORE_HEADERS),
        )
    for field in ("title", "target", "support", "instructions"):
        if field in updates:
            updates[field] = str(updates[field]).strip()
    updated = await update_owner_payment_method(str(request.match_info.get("method_code") or ""), **updates)
    if not updated:
        return web.json_response(
            {"ok": False, "code": "payment_method_not_found", "message": "Payment method was not found."},
            status=404,
            headers=dict(_NO_STORE_HEADERS),
        )
    await _write_owner_audit(
        actor_id=owner.customer_id,
        actor_email=owner.email,
        action="payment_method.update",
        target_type="payment_method",
        target_id=request.match_info.get("method_code"),
        metadata={"fields": sorted(updates)},
    )
    return await owner_settings(request)


def _limit(request: web.Request, default: int = 30) -> int:
    try:
        return max(1, min(100, int(request.query.get("limit") or default)))
    except Exception:
        return default


def _date_text(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _recharge_payload(row: dict[str, Any]) -> dict[str, Any]:
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    return {
        "id": _text(row.get("_id")),
        "status": _text(row.get("status")),
        "user_id": int(row.get("user_id") or 0),
        "reseller_id": int(row.get("reseller_id") or 0),
        "wallet_type": _text(row.get("wallet_type") or "user"),
        "method": _text(row.get("method")),
        "amount": float(row.get("amount") or 0),
        "approved_amount": float(row.get("approved_amount") or 0),
        "decision_note": _text(row.get("decision_note")),
        "details": details,
        "has_proof": bool(row.get("proof_file_id")),
        "created_at": _date_text(row.get("created_at")),
    }


async def owner_recharge_reviews(request: web.Request) -> web.Response:
    await require_website_owner(request)
    status = str(request.query.get("status") or "pending").strip().lower()
    query: dict[str, Any] = {}
    if status not in {"all", "*", ""}:
        query["status"] = status
    rows = await db.recharge_requests.find(query).sort("created_at", -1).limit(_limit(request)).to_list(length=_limit(request))
    return web.json_response({"ok": True, "reviews": [_recharge_payload(row) for row in rows]}, headers=dict(_NO_STORE_HEADERS))


async def owner_recharge_review_action(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        request_id = ObjectId(str(request.match_info.get("request_id") or ""))
    except Exception:
        return web.json_response({"ok": False, "message": "Invalid recharge request id."}, status=400, headers=dict(_NO_STORE_HEADERS))
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = str((body or {}).get("action") or "").strip().lower()
    note = str((body or {}).get("note") or "").strip()
    row = await _recharge_request(request_id)
    if not row:
        return web.json_response({"ok": False, "message": "Recharge request was not found."}, status=404, headers=dict(_NO_STORE_HEADERS))
    if action in {"accept", "reject"}:
        approved_amount = (body or {}).get("approved_amount") if action == "accept" else None
        try:
            amount = float(approved_amount) if approved_amount not in {None, ""} else None
        except Exception:
            return web.json_response({"ok": False, "message": "Approved amount is invalid."}, status=400, headers=dict(_NO_STORE_HEADERS))
        if amount is not None and amount <= 0:
            return web.json_response({"ok": False, "message": "Approved amount must be greater than zero."}, status=400, headers=dict(_NO_STORE_HEADERS))
        updated = await update_recharge_request(
            request_id,
            "accepted" if action == "accept" else "rejected",
            owner.customer_id,
            decision_note=note or f"website_owner_{action}",
            approved_amount=amount,
        )
    elif action == "need_more_proof":
        if len(note) < 5:
            return web.json_response({"ok": False, "message": "Write a clear proof request note."}, status=400, headers=dict(_NO_STORE_HEADERS))
        updated = await db.recharge_requests.find_one_and_update(
            {"_id": request_id, "status": "pending"},
            {"$set": {"status": "need_more_proof", "decision_note": f"need_more_proof: {note}", "reviewed_by": owner.customer_id, "proof_file_id": None, "proof_deleted_at": datetime.now(UTC), "updated_at": datetime.now(UTC)}},
            return_document=ReturnDocument.AFTER,
        )
    else:
        return web.json_response({"ok": False, "message": "Unsupported recharge action."}, status=400, headers=dict(_NO_STORE_HEADERS))
    if not updated:
        return web.json_response({"ok": False, "message": "Recharge request is no longer pending."}, status=409, headers=dict(_NO_STORE_HEADERS))
    current = await _recharge_request(request_id) or updated
    return web.json_response({"ok": True, "review": _recharge_payload(current)}, headers=dict(_NO_STORE_HEADERS))


def _identity_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _text(row.get("_id")),
        "account_id": _text(row.get("account_id")),
        "customer_id": int(row.get("customer_id") or 0),
        "status": _text(row.get("status")),
        "full_name": _text(row.get("full_name")),
        "birth_date": _text(row.get("birth_date")),
        "country": _text(row.get("country")),
        "id_type": _text(row.get("id_type")),
        "review_note": _text(row.get("review_note")),
        "created_at": _date_text(row.get("created_at")),
    }


async def owner_identity_reviews(request: web.Request) -> web.Response:
    await require_website_owner(request)
    status = str(request.query.get("status") or "pending").strip().lower()
    query: dict[str, Any] = {}
    if status not in {"all", "*", ""}:
        query["status"] = status
    rows = await db.identity_verification_requests.find(query).sort("created_at", -1).limit(_limit(request)).to_list(length=_limit(request))
    return web.json_response({"ok": True, "reviews": [_identity_payload(row) for row in rows]}, headers=dict(_NO_STORE_HEADERS))


async def owner_identity_review_action(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = str((body or {}).get("action") or "").strip().lower()
    if action not in {"approve", "reject"}:
        return web.json_response({"ok": False, "message": "Unsupported identity action."}, status=400, headers=dict(_NO_STORE_HEADERS))
    note = str((body or {}).get("note") or "").strip()
    if action == "reject" and len(note) < 3:
        return web.json_response({"ok": False, "message": "Write a rejection reason."}, status=400, headers=dict(_NO_STORE_HEADERS))
    now = datetime.now(UTC)
    review = await db.identity_verification_requests.find_one_and_update(
        {"_id": str(request.match_info.get("review_id") or ""), "status": "pending"},
        {"$set": {"status": "approved" if action == "approve" else "rejected", "review_note": note, "reviewed_by": owner.customer_id, "reviewed_at": now, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if not review:
        return web.json_response({"ok": False, "message": "Identity review is no longer pending."}, status=409, headers=dict(_NO_STORE_HEADERS))
    await db.website_accounts.update_one(
        {"_id": review.get("account_id")},
        {"$set": {"identity_status": review["status"], "identity_updated_at": now, "updated_at": now}},
    )
    return web.json_response({"ok": True, "review": _identity_payload(review)}, headers=dict(_NO_STORE_HEADERS))


def _support_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _text(row.get("_id")),
        "ticket_no": int(row.get("ticket_no") or 0),
        "status": _text(row.get("status")),
        "category": _text(row.get("category")),
        "user_id": int(row.get("user_id") or 0),
        "username": _text(row.get("username")),
        "full_name": _text(row.get("full_name")),
        "scope": _text(row.get("scope")),
        "payload_count": int(row.get("payload_count") or 0),
        "bug_triage": row.get("bug_triage") if isinstance(row.get("bug_triage"), dict) else {},
        "opened_at": _date_text(row.get("opened_at")),
    }


def _clean_owner_scopes(values: Any) -> list[str]:
    return sorted({str(value).strip() for value in (values or []) if str(value).strip() in _ALLOWED_CUSTOMER_SCOPES})


def _clean_owner_events(values: Any) -> list[str]:
    return sorted({str(value).strip() for value in (values or []) if str(value).strip() in ALLOWED_WEBHOOK_EVENTS})


async def owner_api_keys(request: web.Request) -> web.Response:
    await require_website_owner(request)
    query: dict[str, Any] = {}
    status = str(request.query.get("status") or "").strip().lower()
    if status and status not in {"all", "*"}:
        query["status"] = status
    try:
        reseller_id = int(request.query.get("reseller_id") or 0)
    except Exception:
        reseller_id = 0
    if reseller_id > 0:
        query["reseller_id"] = reseller_id
    cursor = db.api_keys.find(query).sort("created_at", -1).limit(_limit(request))
    rows = [serialize_api_key_doc(row) async for row in cursor]
    return web.json_response({"ok": True, "keys": rows, "scopes": sorted(_ALLOWED_CUSTOMER_SCOPES)}, headers=dict(_NO_STORE_HEADERS))


async def owner_create_api_key(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    scopes = _clean_owner_scopes((body or {}).get("scopes") or [])
    if not scopes:
        return web.json_response({"ok": False, "message": "Choose at least one API scope."}, status=400, headers=dict(_NO_STORE_HEADERS))
    try:
        user_id = int((body or {}).get("user_id") or owner.customer_id)
        reseller_id = int((body or {}).get("reseller_id") or user_id)
    except Exception:
        return web.json_response({"ok": False, "message": "Invalid user or reseller id."}, status=400, headers=dict(_NO_STORE_HEADERS))
    key, doc = await create_api_key(user_id=user_id, reseller_id=reseller_id, name=str((body or {}).get("name") or "").strip(), scopes=scopes)
    return web.json_response({"ok": True, "api_key": key, "key": serialize_api_key_doc(doc)}, headers=dict(_NO_STORE_HEADERS))


async def owner_revoke_api_key(request: web.Request) -> web.Response:
    await require_website_owner(request)
    key_id = str(request.match_info.get("key_id") or "").strip()
    ok = await revoke_api_key(key_id=key_id, reseller_id=None)
    if not ok:
        return web.json_response({"ok": False, "message": "API key was not found."}, status=404, headers=dict(_NO_STORE_HEADERS))
    return web.json_response({"ok": True, "id": key_id, "status": "revoked"}, headers=dict(_NO_STORE_HEADERS))


async def owner_webhooks(request: web.Request) -> web.Response:
    await require_website_owner(request)
    query: dict[str, Any] = {}
    status = str(request.query.get("status") or "").strip().lower()
    if status and status not in {"all", "*"}:
        query["status"] = status
    try:
        reseller_id = int(request.query.get("reseller_id") or 0)
    except Exception:
        reseller_id = 0
    if reseller_id > 0:
        query["reseller_id"] = reseller_id
    cursor = db.api_webhooks.find(query).sort("created_at", -1).limit(_limit(request))
    rows = [serialize_webhook_doc(row) async for row in cursor]
    return web.json_response({"ok": True, "webhooks": rows, "events": sorted(ALLOWED_WEBHOOK_EVENTS)}, headers=dict(_NO_STORE_HEADERS))


async def owner_create_webhook(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    url = str((body or {}).get("url") or "").strip()
    if not _valid_https_url(url):
        return web.json_response({"ok": False, "message": "Webhook URL must be HTTPS."}, status=400, headers=dict(_NO_STORE_HEADERS))
    events = _clean_owner_events((body or {}).get("events") or [])
    if not events:
        return web.json_response({"ok": False, "message": "Choose at least one webhook event."}, status=400, headers=dict(_NO_STORE_HEADERS))
    try:
        user_id = int((body or {}).get("user_id") or owner.customer_id)
        reseller_id = int((body or {}).get("reseller_id") or user_id)
    except Exception:
        return web.json_response({"ok": False, "message": "Invalid user or reseller id."}, status=400, headers=dict(_NO_STORE_HEADERS))
    secret, doc = await create_webhook(user_id=user_id, reseller_id=reseller_id, url=url, events=events)
    return web.json_response({"ok": True, "secret": secret, "webhook": serialize_webhook_doc(doc)}, headers=dict(_NO_STORE_HEADERS))


async def owner_revoke_webhook(request: web.Request) -> web.Response:
    await require_website_owner(request)
    webhook_id = str(request.match_info.get("webhook_id") or "").strip()
    ok = await revoke_webhook(webhook_id=webhook_id, reseller_id=None)
    if not ok:
        return web.json_response({"ok": False, "message": "Webhook was not found."}, status=404, headers=dict(_NO_STORE_HEADERS))
    return web.json_response({"ok": True, "id": webhook_id, "status": "revoked"}, headers=dict(_NO_STORE_HEADERS))


async def owner_provider_readiness(request: web.Request) -> web.Response:
    await require_website_owner(request)
    rows = provider_readiness_rows()
    return web.json_response({"ok": True, "providers": rows}, headers=dict(_NO_STORE_HEADERS))


async def owner_provider_webhook_events(request: web.Request) -> web.Response:
    await require_website_owner(request)
    rows = await list_provider_webhook_events(
        provider=str(request.query.get("provider") or "").strip(),
        status=str(request.query.get("status") or "").strip(),
        limit=_limit(request, default=50),
    )
    return web.json_response({"ok": True, "events": rows}, headers=dict(_NO_STORE_HEADERS))


async def owner_replay_provider_webhook_event(request: web.Request) -> web.Response:
    await require_website_owner(request)
    result = await replay_provider_webhook_event(str(request.match_info.get("event_id") or "").strip())
    status = 404 if not result.get("ok") and str(result.get("reason") or "") == "event_not_found" else 200
    return web.json_response(result, status=status, headers=dict(_NO_STORE_HEADERS))


def _provider_source_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("source_payload") if isinstance(row.get("source_payload"), dict) else {}
    return {
        "id": _text(row.get("source_token") or row.get("_id")),
        "source_key": _text(row.get("_id")),
        "provider": _text(row.get("provider")),
        "status": _text(row.get("price_status")),
        "reason": _text(row.get("review_reason")),
        "available": bool(row.get("available")),
        "compare_key": _text(row.get("compare_key")),
        "source_ref": _text(row.get("source_ref")),
        "source_url": _text(row.get("source_url")),
        "product_name": _text(row.get("source_product_name")),
        "denomination_name": _text(row.get("source_denomination_name")),
        "active_price": float(row.get("active_price") or 0),
        "observed_price": float(row.get("observed_price") or 0),
        "old_price_usd": payload.get("old_price_usd"),
        "discount_percent": payload.get("discount_percent"),
        "parse_confidence": float(row.get("parse_confidence") or 0),
        "last_seen_at": _date_text(row.get("last_seen_at")),
        "updated_at": _date_text(row.get("updated_at")),
    }


def _price_watch_run_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": _text(row.get("provider")),
        "status": _text(row.get("status")),
        "stats": row.get("stats") if isinstance(row.get("stats"), dict) else {},
        "errors": row.get("errors") if isinstance(row.get("errors"), list) else [],
        "started_at": _date_text(row.get("started_at")),
        "finished_at": _date_text(row.get("finished_at")),
        "created_at": _date_text(row.get("created_at")),
    }


async def owner_digital_provider_sources(request: web.Request) -> web.Response:
    await require_website_owner(request)
    provider = str(request.query.get("provider") or "bittopup").strip().lower()
    status = str(request.query.get("status") or "under_review").strip().lower()
    if status in {"all", "*"}:
        status = ""
    rows, runs = await asyncio.gather(
        list_provider_sources(provider=provider or None, status=status or None, limit=_limit(request, default=30)),
        list_price_watch_runs(provider=provider or None, limit=8),
    )
    return web.json_response(
        {
            "ok": True,
            "sources": [_provider_source_payload(row) for row in rows],
            "runs": [_price_watch_run_payload(row) for row in runs],
            "statuses": ["under_review", "unmapped", "active", "disabled", "all"],
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def owner_run_digital_provider_scan(request: web.Request) -> web.Response:
    await require_website_owner(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        max_pages = int((body or {}).get("max_pages") or 0)
    except Exception:
        max_pages = 0
    result = await run_bittopup_price_watch(max_pages=max_pages if max_pages > 0 else None)
    return web.json_response({"ok": True, "scan": result}, headers=dict(_NO_STORE_HEADERS))


async def owner_digital_provider_source_action(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = str((body or {}).get("action") or "").strip().lower()
    source_id = str(request.match_info.get("source_id") or "").strip()
    if action == "approve":
        row = await approve_provider_source(source_id, actor_id=owner.customer_id)
        if row and str(row.get("price_status") or "") != "active":
            return web.json_response(
                {"ok": False, "message": "Source cannot be approved until it has a price and compare key.", "source": _provider_source_payload(row)},
                status=409,
                headers=dict(_NO_STORE_HEADERS),
            )
    elif action == "disable":
        row = await disable_provider_source(source_id, actor_id=owner.customer_id)
    else:
        return web.json_response({"ok": False, "message": "Unsupported source action."}, status=400, headers=dict(_NO_STORE_HEADERS))
    if not row:
        return web.json_response({"ok": False, "message": "Provider source was not found."}, status=404, headers=dict(_NO_STORE_HEADERS))
    return web.json_response({"ok": True, "source": _provider_source_payload(row)}, headers=dict(_NO_STORE_HEADERS))


def _bot_payload(row: dict[str, Any]) -> dict[str, Any]:
    settings_doc = row.get("settings") if isinstance(row.get("settings"), dict) else {}
    reseller = row.get("reseller") if isinstance(row.get("reseller"), dict) else {}
    provisioning = row.get("provisioning") if isinstance(row.get("provisioning"), dict) else {}
    subscription = row.get("subscription") if isinstance(row.get("subscription"), dict) else {}
    return {
        "bot_id": int(row.get("bot_id") or 0),
        "owner_id": int(row.get("owner_id") or 0),
        "active": bool(row.get("active")),
        "status": _text(row.get("status") or provisioning.get("status") or ("active" if row.get("active") else "inactive")),
        "username": _text(row.get("username") or row.get("bot_username") or reseller.get("bot_username")),
        "subscription_channel": _text(settings_doc.get("subscription_channel")),
        "subscription": {
            "status": _text(subscription.get("status")),
            "renewal_plan_months": int(subscription.get("renewal_plan_months") or 1),
            "renewal_charge_usd": float(subscription.get("renewal_charge_usd") or 0),
            "renewal_discount_percent": float(subscription.get("renewal_discount_percent") or 0),
            "trial_ends_at": _date_text(subscription.get("trial_ends_at")),
            "subscription_ends_at": _date_text(subscription.get("subscription_ends_at")),
            "grace_ends_at": _date_text(subscription.get("grace_ends_at")),
        },
        "created_at": _date_text(row.get("created_at")),
    }


def _bot_creation_review_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    safe_payload = {key: value for key, value in payload.items() if key != "bot_token"}
    return {
        "id": _text(row.get("_id")),
        "status": _text(row.get("status")),
        "requester_id": int(row.get("requester_id") or 0),
        "requester_lang": _text(row.get("requester_lang") or "en"),
        "review_reasons": list(row.get("review_reasons") or []),
        "owner_notified": bool(row.get("owner_notified")),
        "notify_route": _text(row.get("owner_notify_route")),
        "payload": safe_payload,
        "created_at": _date_text(row.get("created_at")),
        "reviewed_at": _date_text(row.get("reviewed_at")),
        "reviewed_by": row.get("reviewed_by"),
    }


async def owner_bot_creation_reviews(request: web.Request) -> web.Response:
    await require_website_owner(request)
    status = str(request.query.get("status") or "pending").strip().lower()
    query: dict[str, Any] = {}
    if status not in {"all", "*", ""}:
        query["status"] = status
    rows = await db.bot_creation_requests.find(query, {"payload.bot_token": 0}).sort("created_at", -1).limit(_limit(request)).to_list(length=_limit(request))
    return web.json_response({"ok": True, "reviews": [_bot_creation_review_payload(row) for row in rows]}, headers=dict(_NO_STORE_HEADERS))


async def owner_bot_creation_review_action(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = str((body or {}).get("action") or "").strip().lower()
    reviewed, _status, message = await review_bot_creation_request(
        request_id=str(request.match_info.get("request_id") or ""),
        action=action,
        reviewer_id=int(owner.customer_id),
        reviewer_username=owner.email,
        source="website_owner_api",
        notify_requester=True,
    )
    if not reviewed:
        return web.json_response({"ok": False, "message": message}, status=404, headers=dict(_NO_STORE_HEADERS))
    await _write_owner_audit(
        actor_id=owner.customer_id,
        actor_email=owner.email,
        action=f"bot_creation_review.{action}",
        target_type="bot_creation_request",
        target_id=request.match_info.get("request_id"),
    )
    return web.json_response({"ok": True, "message": message, "review": _bot_creation_review_payload(reviewed)}, headers=dict(_NO_STORE_HEADERS))


async def owner_bots(request: web.Request) -> web.Response:
    await require_website_owner(request)
    query: dict[str, Any] = {}
    status = str(request.query.get("status") or "all").strip().lower()
    if status == "active":
        query["active"] = True
    elif status == "inactive":
        query["active"] = {"$ne": True}
    rows = await db.bots.find(query, {"token": 0}).sort("created_at", -1).limit(_limit(request, default=30)).to_list(length=_limit(request, default=30))
    return web.json_response({"ok": True, "bots": [_bot_payload(row) for row in rows]}, headers=dict(_NO_STORE_HEADERS))


async def owner_bot_subscription_action(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        bot_id = int(request.match_info.get("bot_id") or 0)
    except Exception:
        bot_id = 0
    if bot_id <= 0:
        return web.json_response({"ok": False, "message": "Invalid bot id."}, status=400, headers=dict(_NO_STORE_HEADERS))
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = str((body or {}).get("action") or "").strip().lower()
    try:
        months = int((body or {}).get("months") or 1)
    except Exception:
        months = 1
    if months not in {1, 6, 12}:
        return web.json_response({"ok": False, "message": "Months must be 1, 6, or 12."}, status=400, headers=dict(_NO_STORE_HEADERS))
    if action == "activate":
        subscription = await activate_bot_subscription(bot_id, months=months, note=str((body or {}).get("note") or "").strip() or None)
    elif action == "set_plan":
        subscription = await set_bot_subscription_plan(bot_id, months=months)
    elif action == "sync":
        subscription = await sync_bot_subscription(bot_id, collect_due=bool((body or {}).get("collect_due")))
    else:
        return web.json_response({"ok": False, "message": "Unsupported subscription action."}, status=400, headers=dict(_NO_STORE_HEADERS))
    if not subscription:
        return web.json_response({"ok": False, "message": "Bot was not found."}, status=404, headers=dict(_NO_STORE_HEADERS))
    await _write_owner_audit(
        actor_id=owner.customer_id,
        actor_email=owner.email,
        action=f"bot_subscription.{action}",
        target_type="bot",
        target_id=bot_id,
        metadata={"months": months},
    )
    row = await db.bots.find_one({"bot_id": bot_id}, {"token": 0}) or {"bot_id": bot_id, "subscription": subscription}
    return web.json_response({"ok": True, "bot": _bot_payload(row), "subscription": _bot_payload(row)["subscription"]}, headers=dict(_NO_STORE_HEADERS))


async def owner_reseller_deposit(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    try:
        body = await request.json()
        reseller_id = int((body or {}).get("reseller_id") or 0)
        amount = float((body or {}).get("amount") or 0)
    except Exception:
        return web.json_response({"ok": False, "message": "Provide a valid reseller_id and amount."}, status=400, headers=dict(_NO_STORE_HEADERS))
    if reseller_id <= 0 or amount <= 0 or amount > 10_000_000:
        return web.json_response({"ok": False, "message": "Provide a positive amount and valid reseller id."}, status=400, headers=dict(_NO_STORE_HEADERS))
    note = str((body or {}).get("note") or "").strip()[:300]
    entry = await credit_reseller_main_wallet(
        reseller_id=reseller_id,
        amount=amount,
        reason="owner_reseller_deposit",
        actor_id=owner.customer_id,
        order_id=f"owner-deposit:{owner.customer_id}:{reseller_id}:{datetime.now(UTC).timestamp()}",
    )
    await _write_owner_audit(
        actor_id=owner.customer_id,
        actor_email=owner.email,
        action="reseller.deposit",
        target_type="reseller",
        target_id=reseller_id,
        metadata={"amount": amount, "note": note},
    )
    if note:
        await db.ledger_entries.update_one({"_id": entry.get("_id")}, {"$set": {"owner_note": note}})
    return web.json_response(
        {"ok": True, "deposit": {"reseller_id": reseller_id, "amount": float(amount), "ledger_entry_id": _text(entry.get("_id"))}},
        headers=dict(_NO_STORE_HEADERS),
    )


async def owner_broadcast(request: web.Request) -> web.Response:
    await require_website_owner(request)
    try:
        body = await request.json()
        chat_id, message_thread_id = _parse_chat_target(body or {})
    except Exception:
        return web.json_response({"ok": False, "message": "Provide a valid broadcast chat target."}, status=400, headers=dict(_NO_STORE_HEADERS))
    text = "\n".join(line.rstrip() for line in str((body or {}).get("text") or "").strip().splitlines()).strip()
    if len(text) < 2 or len(text) > 3500:
        return web.json_response({"ok": False, "message": "Broadcast text must be between 2 and 3500 characters."}, status=400, headers=dict(_NO_STORE_HEADERS))
    delivered = await send_owner_broadcast(chat_id=chat_id, message_thread_id=message_thread_id, text=text)
    if not delivered:
        return web.json_response({"ok": False, "message": "Could not send broadcast with the configured main bot."}, status=502, headers=dict(_NO_STORE_HEADERS))
    return web.json_response({"ok": True, "broadcast": {"chat_id": chat_id, "message_thread_id": message_thread_id, "length": len(text)}}, headers=dict(_NO_STORE_HEADERS))


async def owner_support_tickets(request: web.Request) -> web.Response:
    await require_website_owner(request)
    status = str(request.query.get("status") or "open").strip().lower()
    query: dict[str, Any] = {}
    if status == "open":
        query["status"] = {"$in": ["open", "awaiting_user", "awaiting_admin", "replied"]}
    elif status not in {"all", "*", ""}:
        query["status"] = status
    rows = await db.support_tickets.find(query).sort("opened_at", -1).limit(_limit(request)).to_list(length=_limit(request))
    return web.json_response({"ok": True, "tickets": [_support_payload(row) for row in rows]}, headers=dict(_NO_STORE_HEADERS))


async def owner_support_ticket_action(request: web.Request) -> web.Response:
    owner = await require_website_owner(request)
    ticket_id = str(request.match_info.get("ticket_id") or "").strip()
    try:
        body = await request.json()
    except Exception:
        body = {}
    ticket = await get_support_ticket(ticket_id)
    if not ticket:
        return web.json_response({"ok": False, "message": "Support ticket was not found."}, status=404, headers=dict(_NO_STORE_HEADERS))
    action = str((body or {}).get("action") or "").strip().lower()
    if action == "solve":
        await mark_support_ticket_solved(ticket_id, actor_id=owner.customer_id)
        await send_ticket_message(ticket, "Your support ticket has been solved.")
    elif action == "reply":
        message = " ".join(str((body or {}).get("message") or "").strip().split())
        if len(message) < 2 or len(message) > 3500:
            return web.json_response({"ok": False, "message": "Write a support reply between 2 and 3500 characters."}, status=400, headers=dict(_NO_STORE_HEADERS))
        delivered = await send_ticket_message(ticket, message)
        if not delivered:
            return web.json_response({"ok": False, "message": "Could not deliver the reply through the ticket source bot."}, status=502, headers=dict(_NO_STORE_HEADERS))
        now = datetime.now(UTC)
        await db.support_ticket_messages.insert_one(
            {"ticket_id": ticket.get("_id"), "direction": "owner_to_user", "actor_id": owner.customer_id, "text": message, "created_at": now}
        )
        await db.support_tickets.update_one(
            {"_id": ticket.get("_id")},
            {"$set": {"status": "replied", "last_reply_by": owner.customer_id, "last_reply_at": now, "updated_at": now}, "$inc": {"payload_count": 1}},
        )
    elif action in {"bug_confirmed", "not_bug"}:
        await mark_support_ticket_bug_triage(ticket_id, actor_id=owner.customer_id, status="confirmed" if action == "bug_confirmed" else "not_bug")
    else:
        return web.json_response({"ok": False, "message": "Unsupported support action."}, status=400, headers=dict(_NO_STORE_HEADERS))
    current = await get_support_ticket(ticket_id) or ticket
    return web.json_response({"ok": True, "ticket": _support_payload(current)}, headers=dict(_NO_STORE_HEADERS))


def register_owner_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/owner/dashboard", owner_dashboard)
    app.router.add_get("/api/v1/owner/queues", owner_queues)
    app.router.add_get("/api/v1/owner/users", owner_users)
    app.router.add_get("/api/v1/owner/users/{customer_id}", owner_user_detail)
    app.router.add_post("/api/v1/owner/users/{customer_id}/action", owner_user_action)
    app.router.add_get("/api/v1/owner/finance/audit", owner_finance_audit)
    app.router.add_get("/api/v1/owner/system/status", owner_system_status)
    app.router.add_post("/api/v1/owner/system/test-log", owner_system_test_log)
    app.router.add_get("/api/v1/owner/audit", owner_admin_audit)
    app.router.add_get("/api/v1/owner/resellers", owner_resellers)
    app.router.add_get("/api/v1/owner/resellers/{reseller_id}", owner_reseller_detail)
    app.router.add_get("/api/v1/owner/digital/orders", owner_digital_orders)
    app.router.add_post("/api/v1/owner/digital/orders/{order_id}/action", owner_digital_order_action)
    app.router.add_get("/api/v1/owner/numbers/refund-reviews", owner_numbers_refund_reviews)
    app.router.add_post("/api/v1/owner/numbers/refund-reviews/{order_id}/resolve", owner_resolve_numbers_refund_review)
    app.router.add_get("/api/v1/owner/settings", owner_settings)
    app.router.add_put("/api/v1/owner/settings", owner_update_settings)
    app.router.add_post("/api/v1/owner/routing-targets/{target_key}", owner_update_routing_target)
    app.router.add_patch("/api/v1/owner/payment-methods/{method_code}", owner_update_payment_method)
    app.router.add_get("/api/v1/owner/recharge-reviews", owner_recharge_reviews)
    app.router.add_post("/api/v1/owner/recharge-reviews/{request_id}/action", owner_recharge_review_action)
    app.router.add_get("/api/v1/owner/identity-reviews", owner_identity_reviews)
    app.router.add_post("/api/v1/owner/identity-reviews/{review_id}/action", owner_identity_review_action)
    app.router.add_get("/api/v1/owner/support-tickets", owner_support_tickets)
    app.router.add_post("/api/v1/owner/support-tickets/{ticket_id}/action", owner_support_ticket_action)
    app.router.add_get("/api/v1/owner/api-keys", owner_api_keys)
    app.router.add_post("/api/v1/owner/api-keys", owner_create_api_key)
    app.router.add_post("/api/v1/owner/api-keys/{key_id}/revoke", owner_revoke_api_key)
    app.router.add_get("/api/v1/owner/webhooks", owner_webhooks)
    app.router.add_post("/api/v1/owner/webhooks", owner_create_webhook)
    app.router.add_post("/api/v1/owner/webhooks/{webhook_id}/revoke", owner_revoke_webhook)
    app.router.add_get("/api/v1/owner/provider-readiness", owner_provider_readiness)
    app.router.add_get("/api/v1/owner/provider-webhook-events", owner_provider_webhook_events)
    app.router.add_post("/api/v1/owner/provider-webhook-events/{event_id}/replay", owner_replay_provider_webhook_event)
    app.router.add_get("/api/v1/owner/digital-provider-sources", owner_digital_provider_sources)
    app.router.add_post("/api/v1/owner/digital-provider-sources/scan", owner_run_digital_provider_scan)
    app.router.add_post("/api/v1/owner/digital-provider-sources/{source_id}/action", owner_digital_provider_source_action)
    app.router.add_get("/api/v1/owner/bot-creation-reviews", owner_bot_creation_reviews)
    app.router.add_post("/api/v1/owner/bot-creation-reviews/{request_id}/action", owner_bot_creation_review_action)
    app.router.add_get("/api/v1/owner/bots", owner_bots)
    app.router.add_post("/api/v1/owner/bots/{bot_id}/subscription/action", owner_bot_subscription_action)
    app.router.add_post("/api/v1/owner/reseller-deposits", owner_reseller_deposit)
    app.router.add_post("/api/v1/owner/broadcast", owner_broadcast)
