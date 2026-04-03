from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4
from bson import ObjectId

from database.mongo import db

DEC6 = Decimal("0.000001")
DEFAULT_HOLD_HOURS = 24 * 7


def _now() -> datetime:
    return datetime.now(UTC)


def _money6(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(DEC6, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0").quantize(DEC6, rounding=ROUND_HALF_UP)


def _float6(value: Any) -> float:
    return float(_money6(value))


async def bootstrap_cardex_indexes() -> None:
    await db.cardex_users.create_index("telegram_user_id", unique=True)
    await db.cardex_wallets.create_index("user_id", unique=True)
    await db.cardex_cards.create_index([("seller_user_id", 1), ("created_at", -1)])
    await db.cardex_cards.create_index([("status", 1), ("created_at", -1)])
    await db.cardex_pricing_rules.create_index(
        [("brand", 1), ("denomination", 1), ("currency", 1), ("region", 1), ("active", 1)]
    )
    await db.cardex_missing_pricing.create_index(
        [("brand", 1), ("denomination", 1), ("currency", 1), ("region", 1), ("status", 1)]
    )
    await db.cardex_withdrawals.create_index([("user_id", 1), ("created_at", -1)])
    await db.cardex_withdrawals.create_index([("status", 1), ("created_at", -1)])
    await db.cardex_ledger.create_index([("user_id", 1), ("created_at", -1)])


async def get_or_create_cardex_user(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    full_name: str | None,
    owner_telegram_user_id: int | None,
) -> dict[str, Any]:
    user = await db.cardex_users.find_one({"telegram_user_id": int(telegram_user_id)})
    if user:
        updates: dict[str, Any] = {}
        if telegram_username and telegram_username != user.get("telegram_username"):
            updates["telegram_username"] = telegram_username
        if full_name and full_name != user.get("full_name"):
            updates["full_name"] = full_name
        if updates:
            updates["updated_at"] = _now()
            await db.cardex_users.update_one({"_id": user["_id"]}, {"$set": updates})
            user.update(updates)
        await ensure_cardex_wallet(str(user["_id"]))
        return user

    role = "owner" if owner_telegram_user_id and int(owner_telegram_user_id) == int(telegram_user_id) else "user"
    doc = {
        "telegram_user_id": int(telegram_user_id),
        "telegram_username": str(telegram_username or "").strip() or None,
        "full_name": str(full_name or "").strip() or None,
        "role": role,
        "status": "active",
        "created_at": _now(),
        "updated_at": _now(),
    }
    result = await db.cardex_users.insert_one(doc)
    doc["_id"] = result.inserted_id
    await ensure_cardex_wallet(str(doc["_id"]))
    return doc


async def ensure_cardex_wallet(user_id: str) -> dict[str, Any]:
    wallet = await db.cardex_wallets.find_one({"user_id": str(user_id)})
    if wallet:
        return wallet
    doc = {
        "user_id": str(user_id),
        "pending_usd": 0.0,
        "available_usd": 0.0,
        "locked_usd": 0.0,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.cardex_wallets.insert_one(doc)
    return doc


async def get_cardex_wallet(user_id: str) -> dict[str, Any]:
    wallet = await ensure_cardex_wallet(user_id)
    return wallet


async def list_top_card_brands(limit: int = 4) -> list[str]:
    pipeline = [
        {"$group": {"_id": "$brand", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": max(1, int(limit))},
    ]
    rows = [str(row.get("_id") or "").upper() async for row in db.cardex_cards.aggregate(pipeline)]
    defaults = ["AMAZON", "APPLE", "PAYPAL", "STEAM", "PLAYSTATION", "VISA"]
    for item in defaults:
        if item not in rows:
            rows.append(item)
        if len(rows) >= limit:
            break
    return rows[:limit]


async def search_card_brands(query: str | None, limit: int = 20) -> list[str]:
    q = str(query or "").strip().upper()
    brands: set[str] = set()
    cursor = db.cardex_pricing_rules.find(
        {"active": True, "brand": {"$regex": q, "$options": "i"}} if q else {"active": True},
        {"brand": 1},
    ).sort("brand", 1).limit(max(1, int(limit)))
    async for row in cursor:
        brand = str(row.get("brand") or "").upper().strip()
        if brand:
            brands.add(brand)
    defaults = ["AMAZON", "APPLE", "PAYPAL", "STEAM", "PLAYSTATION", "VISA", "WALMART", "UBER"]
    for item in defaults:
        if q and q not in item:
            continue
        brands.add(item)
    return sorted(brands)[:limit]


async def find_active_pricing_rule(brand: str, denomination: Decimal, currency: str, region: str | None) -> dict[str, Any] | None:
    return await db.cardex_pricing_rules.find_one(
        {
            "brand": str(brand).upper().strip(),
            "denomination": _float6(denomination),
            "currency": str(currency).upper().strip(),
            "region": (str(region or "").upper().strip() or "GLOBAL"),
            "active": True,
        },
        sort=[("updated_at", -1)],
    )


async def queue_missing_pricing(
    *,
    actor_user_id: str,
    brand: str,
    denomination: Decimal,
    currency: str,
    region: str | None,
) -> dict[str, Any]:
    region_value = str(region or "").upper().strip() or "GLOBAL"
    existing = await db.cardex_missing_pricing.find_one(
        {
            "brand": str(brand).upper().strip(),
            "denomination": _float6(denomination),
            "currency": str(currency).upper().strip(),
            "region": region_value,
            "status": "open",
        }
    )
    if existing:
        await db.cardex_missing_pricing.update_one(
            {"_id": existing["_id"]},
            {"$inc": {"seen_count": 1}, "$set": {"last_seen_at": _now()}},
        )
        existing["seen_count"] = int(existing.get("seen_count") or 0) + 1
        existing["last_seen_at"] = _now()
        return existing

    doc = {
        "brand": str(brand).upper().strip(),
        "denomination": _float6(denomination),
        "currency": str(currency).upper().strip(),
        "region": region_value,
        "status": "open",
        "seen_count": 1,
        "created_by_user_id": str(actor_user_id),
        "created_at": _now(),
        "last_seen_at": _now(),
    }
    result = await db.cardex_missing_pricing.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def create_pricing_rule(
    *,
    actor_user_id: str,
    brand: str,
    denomination: Decimal,
    currency: str,
    region: str | None,
    customer_buy_rate_percent: Decimal,
    trader_rate_percent: Decimal,
) -> dict[str, Any]:
    region_value = str(region or "").upper().strip() or "GLOBAL"
    await db.cardex_pricing_rules.update_many(
        {
            "brand": str(brand).upper().strip(),
            "denomination": _float6(denomination),
            "currency": str(currency).upper().strip(),
            "region": region_value,
            "active": True,
        },
        {"$set": {"active": False, "updated_at": _now()}},
    )
    doc = {
        "brand": str(brand).upper().strip(),
        "denomination": _float6(denomination),
        "currency": str(currency).upper().strip(),
        "region": region_value,
        "customer_buy_rate_percent": _float6(customer_buy_rate_percent),
        "trader_rate_percent": _float6(trader_rate_percent),
        "active": True,
        "created_by_user_id": str(actor_user_id),
        "created_at": _now(),
        "updated_at": _now(),
    }
    result = await db.cardex_pricing_rules.insert_one(doc)
    doc["_id"] = result.inserted_id
    await db.cardex_missing_pricing.update_many(
        {
            "brand": doc["brand"],
            "denomination": doc["denomination"],
            "currency": doc["currency"],
            "region": doc["region"],
            "status": "open",
        },
        {"$set": {"status": "resolved", "resolved_at": _now(), "resolved_by_user_id": str(actor_user_id)}},
    )
    return doc


async def create_card_submission(
    *,
    seller_user_id: str,
    brand: str,
    denomination: Decimal,
    currency: str,
    region: str | None,
    code: str,
    pin: str | None,
    pricing_rule: dict[str, Any] | None,
) -> dict[str, Any]:
    customer_rate = _money6((pricing_rule or {}).get("customer_buy_rate_percent"))
    trader_rate = _money6((pricing_rule or {}).get("trader_rate_percent"))
    face = _money6(denomination)
    customer_value = (face * customer_rate / Decimal("100")).quantize(DEC6, rounding=ROUND_HALF_UP)
    trader_value = (face * trader_rate / Decimal("100")).quantize(DEC6, rounding=ROUND_HALF_UP)
    doc = {
        "_id": str(uuid4()),
        "seller_user_id": str(seller_user_id),
        "brand": str(brand).upper().strip(),
        "denomination": _float6(face),
        "currency": str(currency).upper().strip(),
        "region": (str(region or "").upper().strip() or "GLOBAL"),
        "code": str(code).strip(),
        "pin": str(pin).strip() if pin else None,
        "status": "submitted",
        "customer_buy_rate_percent": _float6(customer_rate),
        "trader_rate_percent": _float6(trader_rate),
        "customer_value_usd": _float6(customer_value),
        "trader_value_usd": _float6(trader_value),
        "available_on": None,
        "review_notes": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.cardex_cards.insert_one(doc)
    return doc


async def list_cards_for_user(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return await db.cardex_cards.find({"seller_user_id": str(user_id)}).sort("created_at", -1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


async def list_cards_for_review(limit: int = 20) -> list[dict[str, Any]]:
    return await db.cardex_cards.find({"status": {"$in": ["submitted", "under_review"]}}).sort("created_at", 1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


async def get_card(card_id: str) -> dict[str, Any] | None:
    return await db.cardex_cards.find_one({"_id": str(card_id)})


async def post_ledger_entry(
    *,
    user_id: str,
    entry_type: str,
    amount_usd: Decimal,
    pending_delta_usd: Decimal = Decimal("0"),
    available_delta_usd: Decimal = Decimal("0"),
    locked_delta_usd: Decimal = Decimal("0"),
    reference_type: str = "",
    reference_id: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    doc = {
        "_id": str(uuid4()),
        "user_id": str(user_id),
        "entry_type": str(entry_type),
        "amount_usd": _float6(amount_usd),
        "pending_delta_usd": _float6(pending_delta_usd),
        "available_delta_usd": _float6(available_delta_usd),
        "locked_delta_usd": _float6(locked_delta_usd),
        "reference_type": str(reference_type or ""),
        "reference_id": str(reference_id) if reference_id else None,
        "description": str(description or "").strip() or None,
        "created_at": _now(),
    }
    await db.cardex_ledger.insert_one(doc)
    return doc


async def update_wallet_deltas(user_id: str, *, pending_delta: Decimal = Decimal("0"), available_delta: Decimal = Decimal("0"), locked_delta: Decimal = Decimal("0")) -> dict[str, Any]:
    wallet = await ensure_cardex_wallet(user_id)
    new_pending = _money6(wallet.get("pending_usd")) + _money6(pending_delta)
    new_available = _money6(wallet.get("available_usd")) + _money6(available_delta)
    new_locked = _money6(wallet.get("locked_usd")) + _money6(locked_delta)
    if new_pending < 0 or new_available < 0 or new_locked < 0:
        raise ValueError("Wallet invariant violation")
    updates = {
        "pending_usd": _float6(new_pending),
        "available_usd": _float6(new_available),
        "locked_usd": _float6(new_locked),
        "updated_at": _now(),
    }
    await db.cardex_wallets.update_one({"user_id": str(user_id)}, {"$set": updates}, upsert=True)
    wallet.update(updates)
    return wallet


async def accept_card(card_id: str, *, actor_user_id: str, hold_hours: int = DEFAULT_HOLD_HOURS, notes: str | None = None) -> dict[str, Any]:
    card = await get_card(card_id)
    if not card:
        raise ValueError("Card not found")
    if str(card.get("status")) not in {"submitted", "under_review"}:
        raise ValueError("Card cannot be accepted from current status")
    available_on = _now() + timedelta(hours=max(1, int(hold_hours)))
    await db.cardex_cards.update_one(
        {"_id": str(card_id)},
        {
            "$set": {
                "status": "customer_pending_credit",
                "reviewed_by_user_id": str(actor_user_id),
                "reviewed_at": _now(),
                "available_on": available_on,
                "review_notes": str(notes or "").strip() or None,
                "updated_at": _now(),
            }
        },
    )
    amount = _money6(card.get("customer_value_usd"))
    await update_wallet_deltas(str(card.get("seller_user_id")), pending_delta=amount)
    await post_ledger_entry(
        user_id=str(card.get("seller_user_id")),
        entry_type="card_credit_pending",
        amount_usd=amount,
        pending_delta_usd=amount,
        reference_type="card",
        reference_id=str(card_id),
        description="Card accepted and pending release",
    )
    card.update({"status": "customer_pending_credit", "available_on": available_on})
    return card


async def reject_card(card_id: str, *, actor_user_id: str, notes: str | None = None) -> dict[str, Any]:
    card = await get_card(card_id)
    if not card:
        raise ValueError("Card not found")
    if str(card.get("status")) not in {"submitted", "under_review"}:
        raise ValueError("Card cannot be rejected from current status")
    await db.cardex_cards.update_one(
        {"_id": str(card_id)},
        {
            "$set": {
                "status": "rejected",
                "reviewed_by_user_id": str(actor_user_id),
                "reviewed_at": _now(),
                "review_notes": str(notes or "").strip() or None,
                "updated_at": _now(),
            }
        },
    )
    card.update({"status": "rejected"})
    return card


async def release_due_cards(limit: int = 200) -> dict[str, int]:
    count = 0
    cursor = db.cardex_cards.find(
        {"status": "customer_pending_credit", "available_on": {"$lte": _now()}},
    ).limit(max(1, int(limit)))
    async for card in cursor:
        amount = _money6(card.get("customer_value_usd"))
        await db.cardex_cards.update_one(
            {"_id": str(card.get("_id"))},
            {"$set": {"status": "customer_available_credit", "updated_at": _now()}},
        )
        await update_wallet_deltas(str(card.get("seller_user_id")), pending_delta=-amount, available_delta=amount)
        await post_ledger_entry(
            user_id=str(card.get("seller_user_id")),
            entry_type="pending_release",
            amount_usd=amount,
            pending_delta_usd=-amount,
            available_delta_usd=amount,
            reference_type="card",
            reference_id=str(card.get("_id")),
            description="Pending card credit released",
        )
        count += 1
    return {"released": count}


async def create_withdrawal(*, user_id: str, requested_usd_amount: Decimal, payout_currency: str, notes: str | None = None) -> dict[str, Any]:
    amount = _money6(requested_usd_amount)
    if amount <= 0:
        raise ValueError("requested_usd_amount must be > 0")
    payout = str(payout_currency).upper().strip()
    if payout not in {"USD", "SYP"}:
        raise ValueError("payout_currency must be USD or SYP")
    wallet = await ensure_cardex_wallet(user_id)
    if _money6(wallet.get("available_usd")) < amount:
        raise ValueError("Insufficient available USD")
    doc = {
        "_id": str(uuid4()),
        "user_id": str(user_id),
        "requested_usd_amount": _float6(amount),
        "payout_currency": payout,
        "status": "requested",
        "notes": str(notes or "").strip() or None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.cardex_withdrawals.insert_one(doc)
    await update_wallet_deltas(str(user_id), available_delta=-amount, locked_delta=amount)
    await post_ledger_entry(
        user_id=str(user_id),
        entry_type="withdrawal_request_lock",
        amount_usd=amount,
        available_delta_usd=-amount,
        locked_delta_usd=amount,
        reference_type="withdrawal",
        reference_id=str(doc["_id"]),
        description="Withdrawal request lock created",
    )
    return doc


async def list_withdrawals_for_user(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return await db.cardex_withdrawals.find({"user_id": str(user_id)}).sort("created_at", -1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


async def list_open_withdrawals(limit: int = 20) -> list[dict[str, Any]]:
    return await db.cardex_withdrawals.find({"status": {"$in": ["requested", "under_review", "approved"]}}).sort("created_at", 1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


async def update_withdrawal_status(withdrawal_id: str, *, status: str, actor_user_id: str, reason: str | None = None) -> dict[str, Any]:
    row = await db.cardex_withdrawals.find_one({"_id": str(withdrawal_id)})
    if not row:
        raise ValueError("Withdrawal not found")
    current = str(row.get("status") or "")
    amount = _money6(row.get("requested_usd_amount"))
    if status == "approved":
        if current not in {"requested", "under_review"}:
            raise ValueError("Withdrawal cannot be approved from current status")
    elif status == "rejected":
        if current not in {"requested", "under_review", "approved"}:
            raise ValueError("Withdrawal cannot be rejected from current status")
        await update_wallet_deltas(str(row.get("user_id")), available_delta=amount, locked_delta=-amount)
        await post_ledger_entry(
            user_id=str(row.get("user_id")),
            entry_type="withdrawal_rejected_release",
            amount_usd=amount,
            available_delta_usd=amount,
            locked_delta_usd=-amount,
            reference_type="withdrawal",
            reference_id=str(withdrawal_id),
            description="Withdrawal rejected and lock released",
        )
    elif status == "paid":
        if current != "approved":
            raise ValueError("Withdrawal must be approved before marking paid")
        await update_wallet_deltas(str(row.get("user_id")), locked_delta=-amount)
        await post_ledger_entry(
            user_id=str(row.get("user_id")),
            entry_type="withdrawal_paid",
            amount_usd=amount,
            locked_delta_usd=-amount,
            reference_type="withdrawal",
            reference_id=str(withdrawal_id),
            description="Withdrawal marked paid",
        )
    else:
        raise ValueError("Unsupported withdrawal status")
    updates = {
        "status": status,
        "updated_at": _now(),
        "reviewed_by_user_id": str(actor_user_id),
    }
    if reason:
        updates["notes"] = reason
    if status == "approved":
        updates["approved_at"] = _now()
    elif status == "rejected":
        updates["rejected_at"] = _now()
    elif status == "paid":
        updates["paid_at"] = _now()
    await db.cardex_withdrawals.update_one({"_id": str(withdrawal_id)}, {"$set": updates})
    row.update(updates)
    return row


async def list_missing_pricing(limit: int = 20) -> list[dict[str, Any]]:
    return await db.cardex_missing_pricing.find({"status": "open"}).sort("last_seen_at", -1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


async def get_missing_pricing(missing_id: str) -> dict[str, Any] | None:
    try:
        oid = ObjectId(str(missing_id))
    except Exception:
        return None
    return await db.cardex_missing_pricing.find_one({"_id": oid})
