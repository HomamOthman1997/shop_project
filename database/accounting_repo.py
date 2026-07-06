"""Profit & loss aggregation over the orders ledger. Revenue = what customers
paid (retail_amount), Cost = our provider/wholesale cost (wholesale_amount),
Profit = the difference. Only settled orders count."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from database.mongo import db

_SETTLED = ["success", "done", "completed"]


def _round2(value: object) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


async def profit_and_loss(*, start: datetime, end: datetime) -> dict:
    """Totals + per-service breakdown for settled orders in [start, end)."""
    orders = getattr(db, "orders", None)
    if orders is None or not hasattr(orders, "aggregate"):
        return {"revenue": 0.0, "cost": 0.0, "profit": 0.0, "orders": 0, "by_service": []}
    rows = await orders.aggregate(
        [
            {"$match": {"status": {"$in": _SETTLED}, "created_at": {"$gte": start, "$lt": end}}},
            {
                "$group": {
                    "_id": {"$ifNull": ["$service_type", "other"]},
                    "revenue": {"$sum": {"$ifNull": ["$retail_amount", 0]}},
                    "cost": {"$sum": {"$ifNull": ["$wholesale_amount", 0]}},
                    "orders": {"$sum": 1},
                }
            },
        ]
    ).to_list(None)
    by_service: list[dict] = []
    total_rev = total_cost = 0.0
    total_orders = 0
    for row in rows:
        revenue = _round2(row.get("revenue"))
        cost = _round2(row.get("cost"))
        orders_n = int(row.get("orders") or 0)
        by_service.append({
            "service": str(row.get("_id") or "other"),
            "revenue": revenue,
            "cost": cost,
            "profit": _round2(revenue - cost),
            "orders": orders_n,
        })
        total_rev += revenue
        total_cost += cost
        total_orders += orders_n
    by_service.sort(key=lambda item: item["revenue"], reverse=True)
    return {
        "revenue": _round2(total_rev),
        "cost": _round2(total_cost),
        "profit": _round2(total_rev - total_cost),
        "orders": total_orders,
        "by_service": by_service,
    }


async def profit_by_provider(*, start: datetime, end: datetime) -> list[dict]:
    """Revenue/cost/profit per fulfilling provider for settled orders in [start, end).
    Owner-only view — provider names are fine here (never shown to customers)."""
    orders = getattr(db, "orders", None)
    if orders is None or not hasattr(orders, "aggregate"):
        return []
    rows = await orders.aggregate(
        [
            {"$match": {"status": {"$in": _SETTLED}, "created_at": {"$gte": start, "$lt": end}}},
            {
                "$group": {
                    "_id": {"$ifNull": ["$provider_code", {"$ifNull": ["$provider", "unknown"]}]},
                    "revenue": {"$sum": {"$ifNull": ["$retail_amount", 0]}},
                    "cost": {"$sum": {"$ifNull": ["$wholesale_amount", 0]}},
                    "orders": {"$sum": 1},
                }
            },
        ]
    ).to_list(None)
    out: list[dict] = []
    for row in rows:
        revenue = _round2(row.get("revenue"))
        cost = _round2(row.get("cost"))
        out.append({
            "provider": str(row.get("_id") or "unknown"),
            "revenue": revenue,
            "cost": cost,
            "profit": _round2(revenue - cost),
            "orders": int(row.get("orders") or 0),
        })
    out.sort(key=lambda item: item["profit"], reverse=True)
    return out


async def capital_summary() -> dict:
    """How much prepaid float we currently hold, by wallet type. This is money
    owed back to customers/resellers (a liability), not revenue."""
    wallets = getattr(db, "wallets", None)
    if wallets is None or not hasattr(wallets, "aggregate"):
        return {"total_float": 0.0, "by_type": []}
    rows = await wallets.aggregate(
        [
            {
                "$group": {
                    "_id": {"$ifNull": ["$wallet_type", "unknown"]},
                    "balance": {"$sum": {"$ifNull": ["$balance", 0]}},
                    "wallets": {"$sum": 1},
                }
            },
        ]
    ).to_list(None)
    by_type: list[dict] = []
    total = 0.0
    for row in rows:
        balance = _round2(row.get("balance"))
        by_type.append({
            "wallet_type": str(row.get("_id") or "unknown"),
            "balance": balance,
            "wallets": int(row.get("wallets") or 0),
        })
        total += balance
    by_type.sort(key=lambda item: item["balance"], reverse=True)
    return {"total_float": _round2(total), "by_type": by_type}


async def monthly_profit_trend(*, months: int = 6, now: datetime | None = None) -> list[dict]:
    """Revenue/cost/profit per calendar month for the last `months` months."""
    orders = getattr(db, "orders", None)
    if orders is None or not hasattr(orders, "aggregate"):
        return []
    now = now or datetime.now(UTC)
    first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = first_this
    for _ in range(max(1, months) - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    rows = await orders.aggregate(
        [
            {"$match": {"status": {"$in": _SETTLED}, "created_at": {"$gte": start}}},
            {
                "$group": {
                    "_id": {"y": {"$year": "$created_at"}, "m": {"$month": "$created_at"}},
                    "revenue": {"$sum": {"$ifNull": ["$retail_amount", 0]}},
                    "cost": {"$sum": {"$ifNull": ["$wholesale_amount", 0]}},
                    "orders": {"$sum": 1},
                }
            },
        ]
    ).to_list(None)
    by_month = {
        f"{int(row['_id']['y']):04d}-{int(row['_id']['m']):02d}": row for row in rows if row.get("_id")
    }
    out: list[dict] = []
    cursor = start
    while cursor < first_this + timedelta(days=1) and len(out) < max(1, months):
        key = cursor.strftime("%Y-%m")
        row = by_month.get(key, {})
        revenue = _round2(row.get("revenue"))
        cost = _round2(row.get("cost"))
        out.append({
            "month": key,
            "revenue": revenue,
            "cost": cost,
            "profit": _round2(revenue - cost),
            "orders": int(row.get("orders") or 0),
        })
        # advance one month
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return out
