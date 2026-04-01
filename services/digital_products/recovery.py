from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from database.mongo import db
from database.orders_repo import extract_order_amounts, update_order_details, update_order_status
from utils.financial_manager import FinancialManager

from .g2bulk_client import G2BulkClient


def _extract_provider_status(payload: Any) -> str:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("status", "order_status", "state"):
                value = str(data.get(key) or "").strip().lower()
                if value:
                    return value
        for key in ("status", "order_status", "state"):
            value = str(payload.get(key) or "").strip().lower()
            if value:
                return value
    return ""


def _provider_status_is_success(payload: Any) -> bool:
    return _extract_provider_status(payload) in {"success", "completed", "delivered", "done", "ok"}


def _provider_status_is_failure(payload: Any) -> bool:
    return _extract_provider_status(payload) in {"failed", "failure", "cancelled", "canceled", "rejected", "expired", "refund", "refunded"}


async def _poll_status(client: G2BulkClient, provider_order_id: str) -> dict[str, Any] | None:
    last_resp: dict[str, Any] | None = None
    for _ in range(2):
        resp = await client.get_order_status(provider_order_id)
        if isinstance(resp, dict):
            last_resp = resp
            if _provider_status_is_success(resp) or _provider_status_is_failure(resp):
                return resp
        await asyncio.sleep(1.0)
    return last_resp


async def run_digital_products_pending_recovery_sweep(*, limit: int = 80, pending_age_sec: int = 120) -> dict[str, int]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=max(30, int(pending_age_sec or 120)))
    rows = await db.orders.find(
        {
            "service_type": "core_digital_products",
            "status": "paid",
            "provider_code": "g2bulk",
            "provider_order_id": {"$exists": True, "$nin": [None, ""]},
            "created_at": {"$lte": cutoff},
            "$or": [
                {"provider_manual_review_required": True},
                {"provider_status": {"$exists": False}},
                {"provider_status": {"$in": ["", "pending", "processing", "queued", "unknown"]}},
            ],
        }
    ).sort("created_at", 1).limit(max(10, int(limit or 80))).to_list(None)

    stats = {
        "checked": 0,
        "marked_success": 0,
        "marked_refunded": 0,
        "pending": 0,
        "refund_failures": 0,
        "missing_order_id_refunded": 0,
    }
    if not rows:
        return stats

    client = G2BulkClient()
    for order in rows:
        stats["checked"] += 1
        oid = order.get("_id")
        provider_order_id = str(order.get("provider_order_id") or "").strip()
        if not provider_order_id:
            stats["pending"] += 1
            continue

        status_resp = await _poll_status(client, provider_order_id)
        provider_status = _extract_provider_status(status_resp)
        await update_order_details(
            oid,
            {
                "provider_status_response": status_resp,
                "provider_status": provider_status,
                "provider_recovery_checked_at": now,
            },
        )

        if status_resp is not None and _provider_status_is_success(status_resp):
            await update_order_status(oid, "success")
            await update_order_details(
                oid,
                {
                    "provider_manual_review_required": False,
                    "provider_recovery_outcome": "success",
                },
            )
            stats["marked_success"] += 1
            continue

        if status_resp is not None and _provider_status_is_failure(status_resp):
            sale_price, cost_price = extract_order_amounts(order)
            ok, _ = await FinancialManager.refund_core_purchase(
                user_id=int(order.get("user_id") or 0),
                order_id=oid,
                sale_price=float(sale_price),
                cost_price=float(cost_price),
                reseller_id=int(order.get("reseller_id") or 0),
            )
            if ok:
                await update_order_status(oid, "refunded")
                await update_order_details(
                    oid,
                    {
                        "provider_manual_review_required": False,
                        "provider_recovery_outcome": "refunded_after_provider_failure",
                    },
                )
                stats["marked_refunded"] += 1
            else:
                stats["refund_failures"] += 1
                await update_order_details(
                    oid,
                    {
                        "provider_recovery_outcome": "refund_failed_after_provider_failure",
                    },
                )
            continue

        stats["pending"] += 1

    stale_rows = await db.orders.find(
        {
            "service_type": "core_digital_products",
            "status": "paid",
            "provider_code": "g2bulk",
            "provider_manual_review_required": True,
            "$or": [
                {"provider_order_id": {"$exists": False}},
                {"provider_order_id": None},
                {"provider_order_id": ""},
            ],
            "created_at": {"$lte": now - timedelta(minutes=20)},
        }
    ).sort("created_at", 1).limit(max(5, int(limit or 80))).to_list(None)
    for order in stale_rows:
        stats["checked"] += 1
        sale_price, cost_price = extract_order_amounts(order)
        ok, _ = await FinancialManager.refund_core_purchase(
            user_id=int(order.get("user_id") or 0),
            order_id=order.get("_id"),
            sale_price=float(sale_price),
            cost_price=float(cost_price),
            reseller_id=int(order.get("reseller_id") or 0),
        )
        if ok:
            await update_order_status(order.get("_id"), "refunded")
            await update_order_details(
                order.get("_id"),
                {
                    "provider_recovery_outcome": "refunded_missing_provider_order_id_timeout",
                    "provider_manual_review_required": False,
                },
            )
            stats["marked_refunded"] += 1
            stats["missing_order_id_refunded"] += 1
        else:
            stats["refund_failures"] += 1

    return stats
