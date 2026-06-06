from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from aiohttp import web
from bson import ObjectId
from pymongo import ReturnDocument

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
from database.recharge_repo import update_recharge_request
from database.support_tickets_repo import (
    get_support_ticket,
    mark_support_ticket_bug_triage,
    mark_support_ticket_solved,
)
from database.support_topics_repo import get_all_support_targets
from services.digital_products.api import _order_payload, execute_manual_order_action
from services.numbers.api import _refund_review_payload
from services.platform.api_auth import ApiAuthContext
from services.platform.telegram_delivery import send_ticket_message
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
                {"key": "support_inbox", "title": "Support inbox", "status": "available", "endpoint": "/api/v1/owner/support-tickets"},
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
    app.router.add_get("/api/v1/owner/digital/orders", owner_digital_orders)
    app.router.add_post("/api/v1/owner/digital/orders/{order_id}/action", owner_digital_order_action)
    app.router.add_get("/api/v1/owner/numbers/refund-reviews", owner_numbers_refund_reviews)
    app.router.add_post("/api/v1/owner/numbers/refund-reviews/{order_id}/resolve", owner_resolve_numbers_refund_review)
    app.router.add_get("/api/v1/owner/settings", owner_settings)
    app.router.add_put("/api/v1/owner/settings", owner_update_settings)
    app.router.add_patch("/api/v1/owner/payment-methods/{method_code}", owner_update_payment_method)
    app.router.add_get("/api/v1/owner/recharge-reviews", owner_recharge_reviews)
    app.router.add_post("/api/v1/owner/recharge-reviews/{request_id}/action", owner_recharge_review_action)
    app.router.add_get("/api/v1/owner/identity-reviews", owner_identity_reviews)
    app.router.add_post("/api/v1/owner/identity-reviews/{review_id}/action", owner_identity_review_action)
    app.router.add_get("/api/v1/owner/support-tickets", owner_support_tickets)
    app.router.add_post("/api/v1/owner/support-tickets/{ticket_id}/action", owner_support_ticket_action)
