from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from bson import ObjectId

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


async def get_user_number_order(order_id: str, user_id: int, reseller_id: int | None = None):
    try:
        oid = ObjectId(str(order_id))
    except Exception:
        return None
    query = {
        "_id": oid,
        "user_id": int(user_id),
        "number_mode": {"$in": ["temp", "voice", "rental"]},
    }
    if reseller_id is not None:
        query["reseller_id"] = int(reseller_id)
    return await db.orders.find_one(query)


async def get_temp_order_by_provider_order(provider_code: str, provider_order_id: str):
    provider = str(provider_code or "").strip().lower()
    external_id = str(provider_order_id or "").strip()
    if not provider or not external_id:
        return None
    return await db.orders.find_one(
        {
            "number_mode": "temp",
            "$or": [
                {"provider": provider},
                {"provisioning_provider": provider},
            ],
            "provider_order_id": external_id,
        }
    )


async def get_number_order_by_provider_order(provider_code: str, provider_order_id: str):
    provider = str(provider_code or "").strip().lower()
    external_id = str(provider_order_id or "").strip()
    if not provider or not external_id:
        return None
    return await db.orders.find_one(
        {
            "number_mode": {"$in": ["temp", "voice", "rental"]},
            "$or": [
                {"provider": provider},
                {"provisioning_provider": provider},
            ],
            "provider_order_id": external_id,
        }
    )


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


async def list_api_temp_orders_for_auto_refund(limit: int = 200):
    cursor = (
        db.orders.find(
            {
                "source": "numbers_api",
                "number_mode": "temp",
                "status": {"$in": ["success", "pending", "paid"]},
                "provider_order_id": {"$exists": True, "$nin": [None, ""]},
                "temp_wait_state": {"$in": ["waiting", "refund_pending"]},
                "$or": [
                    {"temp_codes_count": {"$exists": False}},
                    {"temp_codes_count": 0},
                    {"temp_last_code": {"$exists": False}},
                    {"temp_last_code": ""},
                    {"temp_last_code": None},
                ],
            }
        )
        .sort("created_at", 1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def list_api_temp_refund_support_reviews(
    *,
    limit: int = 100,
    offset: int = 0,
    reseller_id: int | None = None,
    include_resolved: bool = False,
):
    query = {
        "number_mode": "temp",
        "temp_refund_support_review_required": True,
    }
    if reseller_id is not None:
        query["reseller_id"] = int(reseller_id)
    if not include_resolved:
        query["temp_refund_support_review_status"] = {"$ne": "resolved"}
    cursor = db.orders.find(query).sort([("temp_refund_support_review_at", 1), ("created_at", 1)])
    if int(offset) > 0:
        cursor = cursor.skip(int(offset))
    cursor = cursor.limit(max(1, int(limit)))
    return await cursor.to_list(length=max(1, int(limit)))


async def resolve_api_temp_refund_support_review(
    *,
    order_id: str,
    actor_user_id: int,
    resolution: str,
    notes: str = "",
    reseller_id: int | None = None,
) -> dict | None:
    try:
        oid = ObjectId(str(order_id))
    except Exception:
        return None
    query = {
        "_id": oid,
        "number_mode": "temp",
        "temp_refund_support_review_required": True,
    }
    if reseller_id is not None:
        query["reseller_id"] = int(reseller_id)
    patch = {
        "temp_refund_support_review_status": "resolved",
        "temp_refund_support_review_resolved_at": datetime.now(UTC),
        "temp_refund_support_review_resolved_by": int(actor_user_id),
        "temp_refund_support_review_resolution": str(resolution or "").strip(),
        "temp_refund_support_review_notes": str(notes or "").strip(),
    }
    result = await db.orders.update_one(query, {"$set": patch})
    if not bool(result.matched_count):
        return None
    return await db.orders.find_one({"_id": oid})


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


async def list_user_open_temp_and_voice_orders(user_id: int, limit: int = 20):
    temp_cutoff = datetime.now(UTC) - timedelta(days=5)
    cursor = (
        db.orders.find(
            {
                "user_id": int(user_id),
                "number_mode": {"$in": ["temp", "voice"]},
                "status": "success",
                "provisioning_state": "provisioned",
                "provider_order_id": {"$exists": True, "$nin": [None, ""]},
                "provider_number": {"$exists": True, "$nin": [None, "", "?"]},
                "temp_wait_state": {"$in": ["waiting", "waiting_for_call", "code_received", "call_received", "refund_pending"]},
                "$or": [
                    {"number_mode": "voice"},
                    {"number_mode": "temp", "created_at": {"$gte": temp_cutoff}},
                ],
            }
        )
        .sort("created_at", -1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def list_user_recent_temp_and_voice_orders(user_id: int, limit: int = 20, days: int = 5):
    temp_cutoff = datetime.now(UTC) - timedelta(days=max(1, int(days or 5)))
    cursor = (
        db.orders.find(
            {
                "user_id": int(user_id),
                "number_mode": {"$in": ["temp", "voice"]},
                "status": {"$in": ["success", "pending", "paid", "cancelled", "failed", "refunded", "expired"]},
                "created_at": {"$gte": temp_cutoff},
                "$or": [
                    {"provider_order_id": {"$exists": True, "$nin": [None, ""]}},
                    {"provider": {"$exists": True, "$nin": [None, ""]}},
                    {"provisioning_provider": {"$exists": True, "$nin": [None, ""]}},
                ],
            }
        )
        .sort("created_at", -1)
        .limit(int(limit))
    )
    return await cursor.to_list(length=int(limit))


async def list_user_number_orders_for_miniapp(user_id: int, limit: int = 120):
    safe_limit = max(1, min(int(limit or 120), 250))
    cursor = (
        db.orders.find(
            {
                "user_id": int(user_id),
                "number_mode": {"$in": ["temp", "voice", "rental"]},
                "$nor": [
                    {"service_id": {"$regex": r":second_code$"}},
                    {"service_ref_id": {"$regex": r":second_code$"}},
                    {"temp_second_code_source_order_id": {"$exists": True, "$nin": [None, ""]}},
                ],
                "$or": [
                    {"provider_order_id": {"$exists": True, "$nin": [None, ""]}},
                    {"provider": {"$exists": True, "$nin": [None, ""]}},
                    {"provisioning_provider": {"$exists": True, "$nin": [None, ""]}},
                    {"provider_number": {"$exists": True, "$nin": [None, "", "?"]}},
                ],
            }
        )
        .sort("created_at", -1)
        .limit(safe_limit)
    )
    return await cursor.to_list(length=safe_limit)


async def list_paid_number_orders_missing_provider(limit: int = 200):
    cursor = (
        db.orders.find(
            {
                "number_mode": {"$in": ["temp", "voice", "rental"]},
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
