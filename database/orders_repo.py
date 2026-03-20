from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .mongo import db


_TWOPLACES = Decimal("0.01")


def _to_money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _to_float(value) -> float:
    try:
        return float(_to_money(value))
    except Exception:
        return 0.0


def extract_order_amounts(order: dict) -> tuple[float, float]:
    """Compatibility adapter for legacy and v3 order schemas.

    Returns:
        (retail/sale_price, wholesale/cost_price)
    """
    if not order:
        return 0.0, 0.0

    sale_price = _to_float(order.get("retail_amount", order.get("selling_price", 0)))
    cost_price = _to_float(order.get("wholesale_amount", order.get("base_price", 0)))
    return sale_price, cost_price


async def create_order(user_id: int, reseller_id: int, service_id: str, selling_price: float, base_price: float):
    """Create a core order with dual-schema fields.

    This keeps old consumers working while standardizing to v3 fields.
    """
    sale = float(_to_money(selling_price))
    cost = float(_to_money(base_price))
    now = datetime.now(UTC)
    order = {
        "user_id": int(user_id),
        "reseller_id": int(reseller_id),
        "status": "pending",
        "created_at": now,
        "completed_at": None,
        # v3 canonical fields
        "service_type": "core",
        "service_ref_id": str(service_id),
        "retail_amount": sale,
        "wholesale_amount": cost,
        "owner_fee_amount": 0.0,
        "reseller_profit_amount": 0.0,
        # legacy compatibility fields
        "service_id": str(service_id),
        "selling_price": sale,
        "base_price": cost,
    }
    result = await db.orders.insert_one(order)
    order["_id"] = result.inserted_id
    return order


async def update_order_status(order_id, status: str):
    payload = {"status": status}
    if status in {"done", "failed", "refunded", "cancelled", "success", "expired"}:
        payload["completed_at"] = datetime.now(UTC)
    await db.orders.update_one({"_id": order_id}, {"$set": payload})


async def update_order_details(order_id, data: dict):
    await db.orders.update_one({"_id": order_id}, {"$set": data})


async def get_order(order_id):
    return await db.orders.find_one({"_id": order_id})


async def list_user_rental_orders(user_id: int, limit: int = 20):
    cursor = (
        db.orders.find(
            {
                "user_id": int(user_id),
                "number_mode": "rental",
                "status": {"$in": ["success", "done", "pending", "paid"]},
            }
        )
        .sort("created_at", -1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def get_latest_user_rental_order(
    user_id: int,
    *,
    statuses: list[str] | tuple[str, ...] | None = None,
):
    active_statuses = list(statuses or ["success", "done", "pending", "paid"])
    return await db.orders.find_one(
        {
            "user_id": int(user_id),
            "number_mode": "rental",
            "status": {"$in": active_statuses},
        },
        sort=[("created_at", -1)],
    )


async def list_open_rental_orders_without_sms(limit: int = 200):
    cursor = (
        db.orders.find(
            {
                "number_mode": "rental",
                "status": {"$in": ["success", "done", "pending", "paid"]},
                "$and": [
                    {
                        "$or": [
                            {"rental_sms_received_at": {"$exists": False}},
                            {"rental_sms_received_at": None},
                        ]
                    },
                    {
                        "$or": [
                            {"rental_sms_count": {"$exists": False}},
                            {"rental_sms_count": 0},
                        ]
                    },
                ],
            }
        )
        .sort([("rental_safe_cutoff_at", 1), ("created_at", 1)])
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def list_user_open_rental_orders_without_sms(user_id: int, limit: int = 50):
    cursor = (
        db.orders.find(
            {
                "user_id": int(user_id),
                "number_mode": "rental",
                "status": {"$in": ["success", "done", "pending", "paid"]},
                "$and": [
                    {
                        "$or": [
                            {"rental_sms_received_at": {"$exists": False}},
                            {"rental_sms_received_at": None},
                        ]
                    },
                    {
                        "$or": [
                            {"rental_sms_count": {"$exists": False}},
                            {"rental_sms_count": 0},
                        ]
                    },
                ],
            }
        )
        .sort([("rental_safe_cutoff_at", 1), ("created_at", 1)])
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def list_open_temp_orders_for_recovery(limit: int = 200):
    cursor = (
        db.orders.find(
            {
                "number_mode": "temp",
                "status": {"$in": ["success", "pending", "paid"]},
                "provider_order_id": {"$exists": True, "$nin": [None, ""]},
                "temp_wait_chat_id": {"$exists": True, "$ne": None},
                "temp_wait_message_id": {"$exists": True, "$ne": None},
                "temp_wait_state": {"$in": ["waiting", "code_received", "refund_pending"]},
            }
        )
        .sort("created_at", 1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def list_user_open_temp_orders(user_id: int, limit: int = 20):
    cursor = (
        db.orders.find(
            {
                "user_id": int(user_id),
                "number_mode": "temp",
                "status": {"$in": ["success", "pending", "paid"]},
                "provider_order_id": {"$exists": True, "$nin": [None, ""]},
                "temp_wait_state": {"$in": ["waiting", "code_received", "refund_pending"]},
            }
        )
        .sort("created_at", 1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def list_paid_number_orders_missing_provider(limit: int = 200):
    cursor = (
        db.orders.find(
            {
                "number_mode": {"$in": ["temp", "rental"]},
                "status": "paid",
                "$or": [
                    {"provider_order_id": {"$exists": False}},
                    {"provider_order_id": None},
                    {"provider_order_id": ""},
                ],
            }
        )
        .sort("created_at", 1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def list_user_proxy_orders(user_id: int, limit: int = 20):
    cursor = (
        db.orders.find(
            {
                "user_id": int(user_id),
                "$or": [
                    {"service_id": {"$regex": r"^proxy:"}},
                    {"service_ref_id": {"$regex": r"^proxy:"}},
                ],
                "status": {"$in": ["success", "done", "pending", "paid"]},
            }
        )
        .sort("created_at", -1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))
