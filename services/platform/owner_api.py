from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from database.bot_logs_repo import get_bot_logs_target
from database.digital_products_config_repo import (
    get_digital_products_markup_percent,
    set_digital_products_markup_percent,
)
from database.mongo import db
from database.owner_payment_settings_repo import (
    get_owner_exchange_rate,
    get_owner_payment_methods,
    set_owner_exchange_rate,
    update_owner_payment_method,
)
from database.orders_repo import list_api_temp_refund_support_reviews, resolve_api_temp_refund_support_review
from database.provider_balance_alert_repo import (
    get_provider_balance_alert_settings,
    set_provider_balance_alert_enabled,
    set_provider_balance_alert_threshold,
)
from database.support_topics_repo import get_all_support_targets
from services.digital_products.api import _order_payload, execute_manual_order_action
from services.numbers.api import _refund_review_payload
from services.platform.api_auth import ApiAuthContext
from services.platform.website_auth import require_website_owner


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
                {"key": "provider_readiness", "title": "Provider readiness", "status": "available", "endpoint": "/api/v1/numbers/ops/provider-readiness"},
                {"key": "provider_webhooks", "title": "Provider webhook audit", "status": "available", "endpoint": "/api/v1/numbers/ops/provider-webhook-events"},
                {"key": "recharge_reviews", "title": "User and reseller topup reviews", "status": "read_only"},
                {"key": "identity_reviews", "title": "Identity verification reviews", "status": "read_only"},
            ],
        },
        {
            "key": "finance",
            "title": "Finance and pricing",
            "items": [
                {"key": "payment_methods", "title": "Owner payment methods", "status": "available", "endpoint": "/api/v1/owner/settings"},
                {"key": "exchange_rate", "title": "Owner exchange rate", "status": "available", "endpoint": "/api/v1/owner/settings"},
                {"key": "numbers_margin", "title": "Numbers margin", "status": "read_only"},
                {"key": "digital_margin", "title": "Digital products margin", "status": "available", "endpoint": "/api/v1/owner/settings"},
                {"key": "reseller_deposits", "title": "Reseller deposits and subscriptions", "status": "telegram_only"},
            ],
        },
        {
            "key": "catalog",
            "title": "Catalog and fulfillment",
            "items": [
                {"key": "digital_sources", "title": "Digital provider sources", "status": "available", "endpoint": "/api/v1/digital/source-diagnostics"},
                {"key": "bittopup_watch", "title": "BitTopup price watch", "status": "telegram_only"},
                {"key": "cardex_admin", "title": "Card exchange admin queue", "status": "miniapp", "endpoint": "/mini/cardex"},
            ],
        },
        {
            "key": "system",
            "title": "System and communication",
            "items": [
                {"key": "support_routing", "title": "Support topics and routing", "status": "read_only", "endpoint": "/api/v1/owner/settings"},
                {"key": "logs_routing", "title": "Logs and alert routing", "status": "read_only", "endpoint": "/api/v1/owner/settings"},
                {"key": "provider_alerts", "title": "Provider balance alerts", "status": "available", "endpoint": "/api/v1/owner/settings"},
                {"key": "broadcast", "title": "Broadcast", "status": "telegram_only"},
                {"key": "api_keys", "title": "API key management", "status": "available", "endpoint": "/api/v1/api-keys"},
                {"key": "webhooks", "title": "Customer webhook management", "status": "available", "endpoint": "/api/v1/webhooks"},
            ],
        },
    ]


async def _count(collection: str, query: dict[str, Any]) -> int:
    return int(await db[collection].count_documents(query) or 0)


async def _system_setting(doc_id: str) -> dict[str, Any] | None:
    return await db.system_settings.find_one({"_id": str(doc_id)})


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
        {"ok": True, "status": status_filter or "all", "orders": [_order_payload(row) for row in rows]},
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


async def owner_settings(request: web.Request) -> web.Response:
    await require_website_owner(request)
    methods, exchange_rate, digital_markup, alerts, support, logs, owner_target, topup_target = await asyncio.gather(
        get_owner_payment_methods(),
        get_owner_exchange_rate(),
        get_digital_products_markup_percent(),
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
                "numbers_markup_percent": 0.0,
                "numbers_markup_editable": False,
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


async def owner_update_settings(request: web.Request) -> web.Response:
    await require_website_owner(request)
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
    return await owner_settings(request)


async def owner_update_payment_method(request: web.Request) -> web.Response:
    await require_website_owner(request)
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
    return await owner_settings(request)


def register_owner_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/owner/dashboard", owner_dashboard)
    app.router.add_get("/api/v1/owner/queues", owner_queues)
    app.router.add_get("/api/v1/owner/digital/orders", owner_digital_orders)
    app.router.add_post("/api/v1/owner/digital/orders/{order_id}/action", owner_digital_order_action)
    app.router.add_get("/api/v1/owner/numbers/refund-reviews", owner_numbers_refund_reviews)
    app.router.add_post("/api/v1/owner/numbers/refund-reviews/{order_id}/resolve", owner_resolve_numbers_refund_review)
    app.router.add_get("/api/v1/owner/settings", owner_settings)
    app.router.add_put("/api/v1/owner/settings", owner_update_settings)
    app.router.add_patch("/api/v1/owner/payment-methods/{method_code}", owner_update_payment_method)
