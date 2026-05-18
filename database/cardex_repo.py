from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

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


def _decimal_label(value: Any) -> str:
    text = format(Decimal(str(value)).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


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
    await db.cardex_ledger.create_index(
        "idempotency_key",
        unique=True,
        partialFilterExpression={"idempotency_key": {"$exists": True}},
    )
    await db.cardex_card_status_history.create_index([("card_id", 1), ("changed_at", -1)])
    await db.cardex_audit_logs.create_index([("created_at", -1)])
    await db.cardex_audit_logs.create_index([("actor_user_id", 1), ("created_at", -1)])
    await db.cardex_traders.create_index([("status", 1), ("created_at", -1)])
    await db.cardex_trader_batches.create_index([("trader_id", 1), ("created_at", -1)])
    await db.cardex_trader_ledger.create_index([("trader_id", 1), ("created_at", 1)])


async def write_audit_log(
    *,
    actor_user_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before_data: dict[str, Any] | None = None,
    after_data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc = {
        "_id": str(uuid4()),
        "actor_user_id": str(actor_user_id),
        "action": str(action),
        "entity_type": str(entity_type),
        "entity_id": str(entity_id) if entity_id is not None else None,
        "before_data": before_data,
        "after_data": after_data,
        "metadata": metadata or {},
        "created_at": _now(),
    }
    await db.cardex_audit_logs.insert_one(doc)
    return doc


async def list_audit_logs(limit: int = 50) -> list[dict[str, Any]]:
    return await db.cardex_audit_logs.find({}).sort("created_at", -1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


async def _record_card_status_history(
    *,
    card_id: str,
    from_status: str | None,
    to_status: str,
    actor_user_id: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await db.cardex_card_status_history.insert_one(
        {
            "_id": str(uuid4()),
            "card_id": str(card_id),
            "from_status": from_status,
            "to_status": str(to_status),
            "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
            "reason": str(reason or "").strip() or None,
            "metadata": metadata or {},
            "changed_at": _now(),
        }
    )


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
    user_id_s = str(user_id)
    wallet = await db.cardex_wallets.find_one({"user_id": user_id_s})
    if wallet:
        return wallet
    now = _now()
    return await db.cardex_wallets.find_one_and_update(
        {"user_id": user_id_s},
        {
            "$setOnInsert": {
                "user_id": user_id_s,
                "pending_usd": 0.0,
                "available_usd": 0.0,
                "locked_usd": 0.0,
                "created_at": now,
            },
            "$set": {"updated_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


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
    defaults = [
        "AMAZON",
        "APPLE",
        "MASTER SWAG",
        "NETENDU",
        "PAYPAL",
        "PLAYSTATION",
        "RAYZER",
        "RAZER",
        "STARBUCKS",
        "STEAM",
        "TARGET",
        "UBER",
        "VISA",
        "WALMART",
    ]
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
    defaults = [
        "AMAZON",
        "APPLE",
        "MASTER SWAG",
        "NETENDU",
        "PAYPAL",
        "PLAYSTATION",
        "RAYZER",
        "RAZER",
        "STARBUCKS",
        "STEAM",
        "TARGET",
        "UBER",
        "VISA",
        "WALMART",
    ]
    for item in defaults:
        if q and q not in item:
            continue
        brands.add(item)
    return sorted(brands)[:limit]


async def find_active_pricing_rule(brand: str, denomination: Decimal, currency: str, region: str | None) -> dict[str, Any] | None:
    common = {
        "brand": str(brand).upper().strip(),
        "currency": str(currency).upper().strip(),
        "region": (str(region or "").upper().strip() or "GLOBAL"),
        "active": True,
    }
    exact = await db.cardex_pricing_rules.find_one(
        {
            **common,
            "denomination": _float6(denomination),
        },
        sort=[("updated_at", -1)],
    )
    if exact:
        return exact
    return await db.cardex_pricing_rules.find_one(
        {
            **common,
            "denominations": _float6(denomination),
        },
        sort=[("updated_at", -1)],
    )


async def list_active_pricing_rules(limit: int = 200) -> list[dict[str, Any]]:
    return await db.cardex_pricing_rules.find({"active": True}).sort(
        [("brand", 1), ("denomination", 1), ("currency", 1), ("region", 1), ("updated_at", -1)]
    ).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


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
    public_note: str | None = None,
    denominations: list[Decimal] | None = None,
    denomination_label: str | None = None,
) -> dict[str, Any]:
    region_value = str(region or "").upper().strip() or "GLOBAL"
    denomination_values = sorted({_float6(item) for item in (denominations or [denomination])})
    primary_denomination = denomination_values[0] if denomination_values else _float6(denomination)
    label = str(denomination_label or "").strip() or "-".join(_decimal_label(item) for item in denomination_values)
    await db.cardex_pricing_rules.update_many(
        {
            "brand": str(brand).upper().strip(),
            "currency": str(currency).upper().strip(),
            "region": region_value,
            "active": True,
            "$or": [
                {"denomination": {"$in": denomination_values}},
                {"denominations": {"$in": denomination_values}},
                {"denomination_label": label},
            ],
        },
        {"$set": {"active": False, "updated_at": _now()}},
    )
    doc = {
        "brand": str(brand).upper().strip(),
        "denomination": primary_denomination,
        "denominations": denomination_values,
        "denomination_label": label,
        "currency": str(currency).upper().strip(),
        "region": region_value,
        "customer_buy_rate_percent": _float6(customer_buy_rate_percent),
        "trader_rate_percent": _float6(trader_rate_percent),
        "public_note": str(public_note or "").strip() or None,
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
            "denomination": {"$in": denomination_values},
            "currency": doc["currency"],
            "region": doc["region"],
            "status": "open",
        },
        {"$set": {"status": "resolved", "resolved_at": _now(), "resolved_by_user_id": str(actor_user_id)}},
    )
    await write_audit_log(
        actor_user_id=str(actor_user_id),
        action="pricing.manage",
        entity_type="cardex_pricing_rule",
        entity_id=str(doc["_id"]),
        after_data=doc,
    )
    return doc


async def deactivate_pricing_rule(*, actor_user_id: str, pricing_rule_id: str) -> dict[str, Any] | None:
    rule_id = str(pricing_rule_id).strip()
    candidates: list[Any] = [rule_id]
    with suppress(Exception):
        candidates.append(ObjectId(rule_id))
    before = await db.cardex_pricing_rules.find_one({"_id": {"$in": candidates}, "active": True})
    if not before:
        return None
    await db.cardex_pricing_rules.update_one(
        {"_id": before["_id"]},
        {"$set": {"active": False, "updated_at": _now(), "deleted_by_user_id": str(actor_user_id), "deleted_at": _now()}},
    )
    after = {**before, "active": False, "deleted_by_user_id": str(actor_user_id)}
    await write_audit_log(
        actor_user_id=str(actor_user_id),
        action="pricing.delete",
        entity_type="cardex_pricing_rule",
        entity_id=str(before.get("_id")),
        before_data=before,
        after_data=after,
    )
    return before


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
    await _record_card_status_history(
        card_id=str(doc["_id"]),
        from_status=None,
        to_status="submitted",
        actor_user_id=str(seller_user_id),
        reason="card_submitted",
    )
    return doc


async def list_cards_for_user(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return await db.cardex_cards.find({"seller_user_id": str(user_id)}).sort("created_at", -1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


async def list_cards_for_review(limit: int = 20) -> list[dict[str, Any]]:
    return await db.cardex_cards.find({"status": {"$in": ["submitted", "under_review"]}}).sort("created_at", 1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


async def list_cards_for_daily_export(*, since: datetime, until: datetime, limit: int = 1000) -> list[dict[str, Any]]:
    return await db.cardex_cards.find(
        {
            "created_at": {"$gte": since, "$lt": until},
            "status": {"$ne": "rejected"},
        }
    ).sort([("brand", 1), ("created_at", 1)]).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


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
    raise_on_duplicate: bool = False,
) -> dict[str, Any]:
    idempotency_key = None
    if reference_id and reference_type and entry_type:
        idempotency_key = f"{reference_type}:{reference_id}:{entry_type}"
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
    if idempotency_key:
        doc["idempotency_key"] = idempotency_key
    try:
        await db.cardex_ledger.insert_one(doc)
    except DuplicateKeyError:
        if raise_on_duplicate:
            raise
        existing = await db.cardex_ledger.find_one({"idempotency_key": idempotency_key})
        if existing:
            return existing
        raise
    return doc


async def update_wallet_deltas(user_id: str, *, pending_delta: Decimal = Decimal("0"), available_delta: Decimal = Decimal("0"), locked_delta: Decimal = Decimal("0")) -> dict[str, Any]:
    pending = _money6(pending_delta)
    available = _money6(available_delta)
    locked = _money6(locked_delta)
    if pending == 0 and available == 0 and locked == 0:
        return await ensure_cardex_wallet(user_id)

    await ensure_cardex_wallet(user_id)
    query: dict[str, Any] = {"user_id": str(user_id)}
    if pending < 0:
        query["pending_usd"] = {"$gte": _float6(abs(pending))}
    if available < 0:
        query["available_usd"] = {"$gte": _float6(abs(available))}
    if locked < 0:
        query["locked_usd"] = {"$gte": _float6(abs(locked))}

    inc: dict[str, float] = {}
    if pending != 0:
        inc["pending_usd"] = _float6(pending)
    if available != 0:
        inc["available_usd"] = _float6(available)
    if locked != 0:
        inc["locked_usd"] = _float6(locked)

    updated = await db.cardex_wallets.find_one_and_update(
        query,
        {"$inc": inc, "$set": {"updated_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise ValueError("Wallet invariant violation")
    return updated


async def _reverse_cardex_wallet_delta_for_ledger(entry: dict[str, Any]) -> None:
    await update_wallet_deltas(
        str(entry.get("user_id")),
        pending_delta=-_money6(entry.get("pending_delta_usd")),
        available_delta=-_money6(entry.get("available_delta_usd")),
        locked_delta=-_money6(entry.get("locked_delta_usd")),
    )


async def _apply_cardex_financial_event(
    *,
    user_id: str,
    entry_type: str,
    amount_usd: Decimal,
    pending_delta_usd: Decimal = Decimal("0"),
    available_delta_usd: Decimal = Decimal("0"),
    locked_delta_usd: Decimal = Decimal("0"),
    reference_type: str,
    reference_id: str,
    description: str,
) -> dict[str, Any]:
    existing = await db.cardex_ledger.find_one(
        {"idempotency_key": f"{reference_type}:{reference_id}:{entry_type}"}
    )
    if existing:
        return existing

    await update_wallet_deltas(
        user_id,
        pending_delta=pending_delta_usd,
        available_delta=available_delta_usd,
        locked_delta=locked_delta_usd,
    )
    try:
        return await post_ledger_entry(
            user_id=user_id,
            entry_type=entry_type,
            amount_usd=amount_usd,
            pending_delta_usd=pending_delta_usd,
            available_delta_usd=available_delta_usd,
            locked_delta_usd=locked_delta_usd,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            raise_on_duplicate=True,
        )
    except DuplicateKeyError:
        existing = await db.cardex_ledger.find_one(
            {"idempotency_key": f"{reference_type}:{reference_id}:{entry_type}"}
        )
        if existing:
            await _reverse_cardex_wallet_delta_for_ledger(existing)
            return existing
        raise


async def _claim_card_status(card_id: str, allowed_statuses: set[str], updates: dict[str, Any]) -> dict[str, Any]:
    before = await get_card(card_id)
    updated = await db.cardex_cards.find_one_and_update(
        {"_id": str(card_id), "status": {"$in": sorted(allowed_statuses)}},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if updated:
        from_status = str((before or {}).get("status") or "") or None
        to_status = str(updated.get("status") or "")
        if to_status and to_status != from_status:
            await _record_card_status_history(
                card_id=str(card_id),
                from_status=from_status,
                to_status=to_status,
                actor_user_id=str(updates.get("reviewed_by_user_id") or updates.get("actor_user_id") or ""),
                reason=str(updates.get("review_notes") or "").strip() or None,
            )
        return updated
    card = before or await get_card(card_id)
    if not card:
        raise ValueError("Card not found")
    raise ValueError("Card cannot be updated from current status")


async def _claim_withdrawal_status(withdrawal_id: str, allowed_statuses: set[str], updates: dict[str, Any]) -> dict[str, Any]:
    updated = await db.cardex_withdrawals.find_one_and_update(
        {"_id": str(withdrawal_id), "status": {"$in": sorted(allowed_statuses)}},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if updated:
        return updated
    row = await db.cardex_withdrawals.find_one({"_id": str(withdrawal_id)})
    if not row:
        raise ValueError("Withdrawal not found")
    raise ValueError("Withdrawal cannot be updated from current status")


async def accept_card(card_id: str, *, actor_user_id: str, hold_hours: int = DEFAULT_HOLD_HOURS, notes: str | None = None) -> dict[str, Any]:
    now = _now()
    available_on = _now() + timedelta(hours=max(1, int(hold_hours)))
    card = await _claim_card_status(
        card_id,
        {"submitted", "under_review"},
        {
            "status": "customer_pending_credit",
            "reviewed_by_user_id": str(actor_user_id),
            "reviewed_at": now,
            "available_on": available_on,
            "review_notes": str(notes or "").strip() or None,
            "updated_at": now,
        },
    )
    amount = _money6(card.get("customer_value_usd"))
    await _apply_cardex_financial_event(
        user_id=str(card.get("seller_user_id")),
        entry_type="card_credit_pending",
        amount_usd=amount,
        pending_delta_usd=amount,
        reference_type="card",
        reference_id=str(card_id),
        description="Card accepted and pending release",
    )
    await write_audit_log(
        actor_user_id=str(actor_user_id),
        action="cards.accept",
        entity_type="cardex_card",
        entity_id=str(card_id),
        after_data=card,
    )
    return card


async def reject_card(card_id: str, *, actor_user_id: str, notes: str | None = None) -> dict[str, Any]:
    card = await _claim_card_status(
        card_id,
        {"submitted", "under_review"},
        {
            "status": "rejected",
            "reviewed_by_user_id": str(actor_user_id),
            "reviewed_at": _now(),
            "review_notes": str(notes or "").strip() or None,
            "updated_at": _now(),
        },
    )
    await write_audit_log(
        actor_user_id=str(actor_user_id),
        action="cards.reject",
        entity_type="cardex_card",
        entity_id=str(card_id),
        after_data=card,
    )
    return card


async def release_due_cards(limit: int = 200) -> dict[str, int]:
    count = 0
    cursor = db.cardex_cards.find(
        {"status": "customer_pending_credit", "available_on": {"$lte": _now()}},
    ).limit(max(1, int(limit)))
    async for card in cursor:
        amount = _money6(card.get("customer_value_usd"))
        try:
            claimed = await _claim_card_status(
                str(card.get("_id")),
                {"customer_pending_credit"},
                {"status": "customer_available_credit", "updated_at": _now(), "actor_user_id": "system"},
            )
        except ValueError:
            continue
        await _apply_cardex_financial_event(
            user_id=str(card.get("seller_user_id")),
            entry_type="pending_release",
            amount_usd=amount,
            pending_delta_usd=-amount,
            available_delta_usd=amount,
            reference_type="card",
            reference_id=str(claimed.get("_id")),
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
    withdrawal_id = str(uuid4())
    await update_wallet_deltas(str(user_id), available_delta=-amount, locked_delta=amount)
    doc = {
        "_id": withdrawal_id,
        "user_id": str(user_id),
        "requested_usd_amount": _float6(amount),
        "payout_currency": payout,
        "status": "requested",
        "notes": str(notes or "").strip() or None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    try:
        await db.cardex_withdrawals.insert_one(doc)
        await post_ledger_entry(
            user_id=str(user_id),
            entry_type="withdrawal_request_lock",
            amount_usd=amount,
            available_delta_usd=-amount,
            locked_delta_usd=amount,
            reference_type="withdrawal",
            reference_id=withdrawal_id,
            description="Withdrawal request lock created",
            raise_on_duplicate=True,
        )
    except Exception:
        await update_wallet_deltas(str(user_id), available_delta=amount, locked_delta=-amount)
        with suppress(Exception):
            await db.cardex_withdrawals.update_one(
                {"_id": withdrawal_id, "status": "requested"},
                {"$set": {"status": "failed", "updated_at": _now()}},
            )
        raise
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
        row = await _claim_withdrawal_status(
            withdrawal_id,
            {"requested", "under_review"},
            {
                "status": status,
                "updated_at": _now(),
                "reviewed_by_user_id": str(actor_user_id),
                "notes": reason if reason else row.get("notes"),
                "approved_at": _now(),
            },
        )
        return row
    elif status == "rejected":
        row = await _claim_withdrawal_status(
            withdrawal_id,
            {"requested", "under_review", "approved"},
            {
                "status": status,
                "updated_at": _now(),
                "reviewed_by_user_id": str(actor_user_id),
                "notes": reason if reason else row.get("notes"),
                "rejected_at": _now(),
            },
        )
        await _apply_cardex_financial_event(
            user_id=str(row.get("user_id")),
            entry_type="withdrawal_rejected_release",
            amount_usd=amount,
            available_delta_usd=amount,
            locked_delta_usd=-amount,
            reference_type="withdrawal",
            reference_id=str(withdrawal_id),
            description="Withdrawal rejected and lock released",
        )
        await write_audit_log(
            actor_user_id=str(actor_user_id),
            action="withdrawals.reject",
            entity_type="cardex_withdrawal",
            entity_id=str(withdrawal_id),
            after_data=row,
        )
        return row
    elif status == "paid":
        row = await _claim_withdrawal_status(
            withdrawal_id,
            {"approved"},
            {
                "status": status,
                "updated_at": _now(),
                "reviewed_by_user_id": str(actor_user_id),
                "notes": reason if reason else row.get("notes"),
                "paid_at": _now(),
            },
        )
        await _apply_cardex_financial_event(
            user_id=str(row.get("user_id")),
            entry_type="withdrawal_paid",
            amount_usd=amount,
            locked_delta_usd=-amount,
            reference_type="withdrawal",
            reference_id=str(withdrawal_id),
            description="Withdrawal marked paid",
        )
        await write_audit_log(
            actor_user_id=str(actor_user_id),
            action="withdrawals.mark_paid",
            entity_type="cardex_withdrawal",
            entity_id=str(withdrawal_id),
            after_data=row,
        )
        return row
    else:
        raise ValueError("Unsupported withdrawal status")


async def create_trader(*, actor_user_id: str, name: str, notes: str | None = None) -> dict[str, Any]:
    name_s = str(name or "").strip()
    if not name_s:
        raise ValueError("Trader name is required")
    doc = {
        "_id": str(uuid4()),
        "name": name_s,
        "status": "active",
        "default_currency": "USD",
        "notes": str(notes or "").strip() or None,
        "created_by_user_id": str(actor_user_id),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.cardex_traders.insert_one(doc)
    await write_audit_log(
        actor_user_id=str(actor_user_id),
        action="traders.manage",
        entity_type="cardex_trader",
        entity_id=str(doc["_id"]),
        after_data=doc,
    )
    return doc


async def list_traders(limit: int = 50) -> list[dict[str, Any]]:
    return await db.cardex_traders.find({}).sort("created_at", -1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


async def create_trader_batch(
    *,
    actor_user_id: str,
    trader_id: str,
    card_ids: list[str],
    notes: str | None = None,
    mark_sent: bool = True,
) -> dict[str, Any]:
    clean_card_ids = [str(card_id).strip() for card_id in card_ids if str(card_id).strip()]
    if not clean_card_ids:
        raise ValueError("card_ids cannot be empty")
    trader = await db.cardex_traders.find_one({"_id": str(trader_id), "status": "active"})
    if not trader:
        raise ValueError("Trader not found")

    cards = await db.cardex_cards.find({"_id": {"$in": clean_card_ids}}).to_list(length=len(clean_card_ids))
    if len(cards) != len(clean_card_ids):
        raise ValueError("One or more cards were not found")
    allowed_statuses = {"customer_pending_credit", "customer_available_credit"}
    for card in cards:
        if str(card.get("status") or "") not in allowed_statuses:
            raise ValueError(f"Card {card.get('_id')} cannot be batched from current status")

    total_face = sum((_money6(card.get("denomination")) for card in cards), Decimal("0")).quantize(DEC6)
    total_customer = sum((_money6(card.get("customer_value_usd")) for card in cards), Decimal("0")).quantize(DEC6)
    total_expected = sum((_money6(card.get("trader_value_usd") or card.get("customer_value_usd")) for card in cards), Decimal("0")).quantize(DEC6)
    gross_profit = (total_expected - total_customer).quantize(DEC6)
    batch = {
        "_id": str(uuid4()),
        "trader_id": str(trader_id),
        "card_ids": clean_card_ids,
        "status": "sent" if mark_sent else "created",
        "sent_at": _now() if mark_sent else None,
        "total_face_value": _float6(total_face),
        "total_count": len(cards),
        "total_customer_cost_usd": _float6(total_customer),
        "total_expected_from_trader_usd": _float6(total_expected),
        "gross_profit_usd": _float6(gross_profit),
        "notes": str(notes or "").strip() or None,
        "created_by_user_id": str(actor_user_id),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.cardex_trader_batches.insert_one(batch)
    next_status = "sent_to_trader" if mark_sent else "batched_for_trader"
    for card in cards:
        before_status = str(card.get("status") or "")
        await db.cardex_cards.update_one(
            {"_id": str(card.get("_id")), "status": before_status},
            {"$set": {"status": next_status, "trader_batch_id": batch["_id"], "trader_id": str(trader_id), "updated_at": _now()}},
        )
        await _record_card_status_history(
            card_id=str(card.get("_id")),
            from_status=before_status,
            to_status=next_status,
            actor_user_id=str(actor_user_id),
            reason=f"trader_batch:{batch['_id']}",
            metadata={"trader_id": str(trader_id)},
        )
    if mark_sent:
        await db.cardex_trader_ledger.insert_one(
            {
                "_id": str(uuid4()),
                "trader_id": str(trader_id),
                "entry_type": "cards_sent",
                "debit_usd": _float6(total_expected),
                "credit_usd": 0.0,
                "reference_type": "batch",
                "reference_id": batch["_id"],
                "description": f"Cards batch sent #{batch['_id']}",
                "created_by_user_id": str(actor_user_id),
                "created_at": _now(),
            }
        )
    await write_audit_log(
        actor_user_id=str(actor_user_id),
        action="cards.batch.create",
        entity_type="cardex_trader_batch",
        entity_id=str(batch["_id"]),
        after_data=batch,
    )
    return batch


async def post_trader_payment(
    *,
    actor_user_id: str,
    trader_id: str,
    amount_usd: Decimal,
    method: str | None = None,
    reference_no: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    amount = _money6(amount_usd)
    if amount <= 0:
        raise ValueError("amount_usd must be > 0")
    trader = await db.cardex_traders.find_one({"_id": str(trader_id)})
    if not trader:
        raise ValueError("Trader not found")
    payment = {
        "_id": str(uuid4()),
        "trader_id": str(trader_id),
        "amount_usd": _float6(amount),
        "method": str(method or "").strip() or None,
        "reference_no": str(reference_no or "").strip() or None,
        "notes": str(notes or "").strip() or None,
        "recorded_by_user_id": str(actor_user_id),
        "received_at": _now(),
        "created_at": _now(),
    }
    await db.cardex_trader_payments.insert_one(payment)
    await db.cardex_trader_ledger.insert_one(
        {
            "_id": str(uuid4()),
            "trader_id": str(trader_id),
            "entry_type": "payment_received",
            "debit_usd": 0.0,
            "credit_usd": _float6(amount),
            "reference_type": "payment",
            "reference_id": payment["_id"],
            "description": f"Payment received #{payment['_id']}",
            "created_by_user_id": str(actor_user_id),
            "created_at": _now(),
        }
    )
    await write_audit_log(
        actor_user_id=str(actor_user_id),
        action="traders.post_payment",
        entity_type="cardex_trader_payment",
        entity_id=str(payment["_id"]),
        after_data=payment,
    )
    return payment


async def trader_statement(trader_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = await db.cardex_trader_ledger.find({"trader_id": str(trader_id)}).sort("created_at", 1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))
    balance = Decimal("0")
    result: list[dict[str, Any]] = []
    for row in rows:
        balance += _money6(row.get("debit_usd")) - _money6(row.get("credit_usd"))
        item = dict(row)
        item["running_balance_usd"] = _float6(balance)
        result.append(item)
    return result


async def list_missing_pricing(limit: int = 20) -> list[dict[str, Any]]:
    return await db.cardex_missing_pricing.find({"status": "open"}).sort("last_seen_at", -1).limit(max(1, int(limit))).to_list(length=max(1, int(limit)))


async def get_missing_pricing(missing_id: str) -> dict[str, Any] | None:
    try:
        oid = ObjectId(str(missing_id))
    except Exception:
        return None
    return await db.cardex_missing_pricing.find_one({"_id": oid})
