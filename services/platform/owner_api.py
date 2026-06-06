from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from database.mongo import db
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
                {"key": "payment_methods", "title": "Owner payment methods", "status": "telegram_only"},
                {"key": "exchange_rate", "title": "Owner exchange rate", "status": "telegram_only"},
                {"key": "numbers_margin", "title": "Numbers margin", "status": "telegram_only"},
                {"key": "digital_margin", "title": "Digital products margin", "status": "telegram_only"},
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
                {"key": "support_routing", "title": "Support topics and routing", "status": "telegram_only"},
                {"key": "logs_routing", "title": "Logs and alert routing", "status": "telegram_only"},
                {"key": "provider_alerts", "title": "Provider balance alerts", "status": "telegram_only"},
                {"key": "broadcast", "title": "Broadcast", "status": "telegram_only"},
                {"key": "api_keys", "title": "API key management", "status": "available", "endpoint": "/api/v1/api-keys"},
                {"key": "webhooks", "title": "Customer webhook management", "status": "available", "endpoint": "/api/v1/webhooks"},
            ],
        },
    ]


async def _count(collection: str, query: dict[str, Any]) -> int:
    return int(await db[collection].count_documents(query) or 0)


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


def register_owner_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/owner/dashboard", owner_dashboard)
    app.router.add_get("/api/v1/owner/queues", owner_queues)
