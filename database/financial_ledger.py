from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Any, Optional
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import ConfigurationError, InvalidOperation, OperationFailure

from database.mongo import client, db
from config import settings

logger = logging.getLogger("financial_ledger")


TWOPLACES = Decimal("0.01")


def _log_financial_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    payload = ", ".join(f"{key}={fields[key]!r}" for key in sorted(fields))
    logger.log(level, "financial_event=%s%s", event, f" | {payload}" if payload else "")


def _classify_ledger_reason(reason: str) -> tuple[str, list[str]]:
    normalized = str(reason or "").strip().lower()
    if normalized.startswith("purchase_core_"):
        return "core_purchase", ["core", "purchase"]
    if normalized.startswith("refund_core_"):
        return "core_refund", ["core", "refund"]
    if normalized.startswith("purchase_custom_"):
        return "custom_purchase", ["custom", "purchase"]
    if normalized.startswith("refund_custom_"):
        return "custom_refund", ["custom", "refund"]
    if normalized == "recharge_request_accepted":
        return "recharge_credit", ["recharge", "credit"]
    if "deposit" in normalized or "topup" in normalized:
        return "manual_credit", ["manual", "credit"]
    if "adjust" in normalized:
        return "manual_adjustment", ["manual", "adjustment"]
    return "other", ["other"]


def _profit_policy_enabled() -> bool:
    return bool(getattr(settings, "profit_policy_enabled", True))


def _money_decimal(value: float | int | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _money(value: float | int | Decimal) -> float:
    return float(_money_decimal(value))


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _cycle_key(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(UTC)
    return f"{now.year}-{now.month:02d}"


def _wallet_key(owner_type: str, owner_id: int, wallet_type: str, reseller_id: Optional[int] = None) -> str:
    rid = reseller_id if reseller_id is not None else "none"
    return f"{owner_type}:{owner_id}:{wallet_type}:{rid}"


async def bootstrap_financial_indexes() -> None:
    # Immutable ledger + idempotency protections.
    await db.ledger_entries.create_index("tx_uuid", unique=True, background=True)
    await db.ledger_entries.create_index([("order_id", 1), ("reason", 1)], background=True)
    await db.ledger_entries.create_index(
        [("actor_id", 1), ("wallet_type", 1), ("created_at", -1)],
        background=True,
    )
    await db.ledger_entries.create_index(
        [("owner_type", 1), ("owner_id", 1), ("reseller_id", 1), ("wallet_type", 1), ("created_at", -1)],
        background=True,
    )
    await db.orders.create_index([("reseller_id", 1), ("created_at", -1)], background=True)
    await db.orders.create_index(
        [("user_id", 1), ("status", 1), ("number_mode", 1), ("created_at", -1)],
        background=True,
    )
    await db.orders.create_index(
        [("user_id", 1), ("number_mode", 1), ("temp_wait_state", 1), ("created_at", -1)],
        background=True,
        partialFilterExpression={"number_mode": "temp"},
    )
    await db.orders.create_index(
        [("number_mode", 1), ("provider", 1), ("provider_order_id", 1)],
        background=True,
        partialFilterExpression={"number_mode": "temp"},
    )
    await db.orders.create_index(
        [
            ("source", 1),
            ("number_mode", 1),
            ("reseller_id", 1),
            ("temp_refund_support_review_status", 1),
            ("temp_refund_support_review_at", 1),
        ],
        background=True,
        partialFilterExpression={"temp_refund_support_review_required": True},
    )
    await db.session_locks.create_index("lock_key", unique=True, background=True)
    await db.session_locks.create_index("expires_at", expireAfterSeconds=0, background=True)
    await db.wallets.create_index("wallet_key", unique=True, background=True)
    await db.wallets.create_index([("owner_type", 1), ("owner_id", 1), ("wallet_type", 1)], background=True)
    # Strong idempotency guard for recharge acceptance credit path.
    try:
        await db.ledger_entries.create_index(
            [
                ("reason", 1),
                ("direction", 1),
                ("order_id", 1),
                ("owner_type", 1),
                ("owner_id", 1),
                ("wallet_type", 1),
            ],
            unique=True,
            background=True,
            partialFilterExpression={
                "reason": "recharge_request_accepted",
                "direction": "credit",
                "order_id": {"$exists": True},
            },
        )
    except Exception as exc:
        logger.warning("could not create recharge idempotency index: %s", exc)


async def acquire_session_lock(lock_key: str, timeout_seconds: int = 10) -> bool:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=timeout_seconds)
    existing = await db.session_locks.find_one_and_update(
        {
            "lock_key": lock_key,
            "$or": [{"expires_at": {"$lte": now}}, {"expires_at": {"$exists": False}}],
        },
        {"$set": {"expires_at": expires_at, "created_at": now}},
        upsert=False,
        return_document=ReturnDocument.AFTER,
    )
    if existing:
        return True

    try:
        await db.session_locks.insert_one({"lock_key": lock_key, "expires_at": expires_at, "created_at": now})
        return True
    except Exception:
        return False


async def release_session_lock(lock_key: str) -> None:
    await db.session_locks.delete_one({"lock_key": lock_key})


async def _get_wallet_balance(
    owner_type: str,
    owner_id: int,
    wallet_type: str,
    reseller_id: Optional[int] = None,
    *,
    session=None,
) -> float:
    wallet = await db.wallets.find_one(
        {"wallet_key": _wallet_key(owner_type, owner_id, wallet_type, reseller_id)},
        session=session,
    )
    if wallet:
        return _money(wallet.get("balance", 0))

    return 0.0


async def _ledger_entry_exists(
    query: dict[str, Any],
    *,
    session=None,
) -> bool:
    found = await db.ledger_entries.find_one(query, {"_id": 1}, session=session)
    return bool(found)


async def _apply_wallet_delta(
    *,
    owner_type: str,
    owner_id: int,
    wallet_type: str,
    amount: float | int | Decimal,
    reason: str,
    actor_type: str,
    actor_id: int,
    reseller_id: Optional[int] = None,
    order_id: Any = None,
    cycle_key: Optional[str] = None,
    metadata: Optional[dict] = None,
    tx_uuid: Optional[str] = None,
    session=None,
) -> dict:
    amount_decimal = _money_decimal(amount)
    amount = _money(amount_decimal)
    if amount_decimal == 0:
        # No-op safety: avoid crashing purchase/refund flows when a computed
        # commission/fee rounds to zero.
        _log_financial_event(
            "wallet_delta_noop",
            owner_type=owner_type,
            owner_id=owner_id,
            reseller_id=reseller_id,
            wallet_type=wallet_type,
            reason=reason,
            order_id=order_id,
        )
        return {
            "_id": None,
            "tx_uuid": tx_uuid or str(uuid4()),
            "order_id": order_id,
            "owner_type": owner_type,
            "owner_id": owner_id,
            "reseller_id": reseller_id,
            "wallet_type": wallet_type,
            "direction": "noop",
            "amount": 0.0,
            "reason": reason,
            "balance_before": None,
            "balance_after": None,
            "cycle_key": cycle_key or _cycle_key(),
            "metadata": metadata or {},
            "category": _classify_ledger_reason(reason)[0],
            "tags": _classify_ledger_reason(reason)[1],
            "created_at": datetime.now(UTC),
            "noop": True,
        }

    cycle_key = cycle_key or _cycle_key()
    wallet_key = _wallet_key(owner_type, owner_id, wallet_type, reseller_id)
    now = datetime.now(UTC)
    baseline = _money_decimal(
        await _get_wallet_balance(owner_type, owner_id, wallet_type, reseller_id, session=session)
    )
    await db.wallets.update_one(
        {"wallet_key": wallet_key},
        {
            "$setOnInsert": {
                "wallet_key": wallet_key,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "wallet_type": wallet_type,
                "reseller_id": reseller_id,
                "balance": float(baseline),
                "created_at": now,
            }
        },
        upsert=True,
        session=session,
    )

    if amount < 0:
        updated = await db.wallets.find_one_and_update(
            {"wallet_key": wallet_key, "balance": {"$gte": abs(amount)}},
            {"$set": {"updated_at": now}, "$inc": {"balance": amount}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        if not updated:
            raise ValueError("INSUFFICIENT_BALANCE")
    else:
        updated = await db.wallets.find_one_and_update(
            {"wallet_key": wallet_key},
            {"$set": {"updated_at": now}, "$inc": {"balance": amount}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        if not updated:
            raise RuntimeError("WALLET_UPDATE_FAILED")

    after_decimal = _money_decimal(updated.get("balance", 0))
    before_decimal = _money_decimal(after_decimal - amount_decimal)

    category, tags = _classify_ledger_reason(reason)
    entry = {
        "tx_uuid": tx_uuid or str(uuid4()),
        "order_id": order_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "reseller_id": reseller_id,
        "wallet_type": wallet_type,
        "direction": "credit" if amount > 0 else "debit",
        "amount": amount,
        "reason": reason,
        "balance_before": float(before_decimal),
        "balance_after": float(after_decimal),
        "cycle_key": cycle_key,
        "metadata": metadata or {},
        "category": category,
        "tags": tags,
        "created_at": now,
    }
    res = await db.ledger_entries.insert_one(entry, session=session)
    entry["_id"] = res.inserted_id
    _log_financial_event(
        "wallet_delta_applied",
        tx_uuid=entry["tx_uuid"],
        owner_type=owner_type,
        owner_id=owner_id,
        reseller_id=reseller_id,
        wallet_type=wallet_type,
        reason=reason,
        direction=entry["direction"],
        amount=amount,
        order_id=order_id,
        balance_before=entry["balance_before"],
        balance_after=entry["balance_after"],
    )
    return entry


async def _run_in_transaction(coro):
    session = await client.start_session()
    def _is_transactions_not_supported(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            isinstance(exc, (ConfigurationError, InvalidOperation))
            or (isinstance(exc, OperationFailure) and "transaction" in text and "not supported" in text)
            or ("transaction numbers are only allowed on a replica set member or mongos" in text)
        )

    try:
        async with session.start_transaction():
            return await coro(session)
    except Exception as exc:
        if _is_transactions_not_supported(exc):
            _log_financial_event(
                "transaction_not_supported",
                level=logging.ERROR,
                error=str(exc),
            )
            raise RuntimeError("FINANCIAL_TRANSACTIONS_NOT_SUPPORTED") from exc
        _log_financial_event(
            "transaction_failed",
            level=logging.ERROR,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    finally:
        await session.end_session()


async def get_user_wallet_balance(user_id: int, reseller_id: int) -> float:
    return await _get_wallet_balance("user", user_id, "user", reseller_id)


async def list_user_wallet_entries(user_id: int, reseller_id: int, limit: int = 8) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 8), 500))
    cursor = (
        db.ledger_entries.find(
            {
                "owner_type": "user",
                "owner_id": int(user_id),
                "reseller_id": int(reseller_id),
                "wallet_type": "user",
            },
            {
                "_id": 1,
                "direction": 1,
                "amount": 1,
                "reason": 1,
                "category": 1,
                "balance_after": 1,
                "created_at": 1,
                "order_id": 1,
                "actor_type": 1,
                "actor_id": 1,
                "metadata": 1,
            },
        )
        .sort("created_at", -1)
        .limit(safe_limit)
    )
    return await cursor.to_list(length=safe_limit)


async def get_reseller_wallet_balance(reseller_id: int, wallet_type: str = "main") -> float:
    mapped = "reseller_main" if wallet_type == "main" else "reseller_earnings"
    return await _get_wallet_balance("reseller", reseller_id, mapped, reseller_id)


async def credit_user_wallet(user_id: int, reseller_id: int, amount: float, reason: str, *, actor_id: int, order_id=None):
    return await _run_in_transaction(
        lambda session: _apply_wallet_delta(
            owner_type="user",
            owner_id=user_id,
            wallet_type="user",
            reseller_id=reseller_id,
            amount=amount,
            reason=reason,
            actor_type="reseller",
            actor_id=actor_id,
            order_id=order_id,
            session=session,
        )
    )


async def credit_reseller_main_wallet(reseller_id: int, amount: float, reason: str, *, actor_id: int, order_id=None):
    return await _run_in_transaction(
        lambda session: _apply_wallet_delta(
            owner_type="reseller",
            owner_id=reseller_id,
            wallet_type="reseller_main",
            reseller_id=reseller_id,
            amount=amount,
            reason=reason,
            actor_type="owner",
            actor_id=actor_id,
            order_id=order_id,
            session=session,
        )
    )


async def credit_reseller_earnings_wallet(
    reseller_id: int,
    amount: float,
    reason: str,
    *,
    actor_id: int,
    order_id=None,
    metadata: Optional[dict] = None,
):
    return await _run_in_transaction(
        lambda session: _apply_wallet_delta(
            owner_type="reseller",
            owner_id=reseller_id,
            wallet_type="reseller_earnings",
            reseller_id=reseller_id,
            amount=amount,
            reason=reason,
            actor_type="reseller",
            actor_id=actor_id,
            order_id=order_id,
            metadata=metadata,
            session=session,
        )
    )


async def create_order_v3(
    *,
    user_id: int,
    reseller_id: int,
    service_type: str,
    service_ref_id: str,
    retail_amount: float,
    wholesale_amount: float = 0.0,
    reseller_profit_amount: float = 0.0,
    status: str = "pending",
) -> dict:
    now = datetime.now(UTC)
    order = {
        "user_id": user_id,
        "reseller_id": reseller_id,
        "service_type": service_type,
        "service_ref_id": service_ref_id,
        "status": status,
        "retail_amount": _money(retail_amount),
        "wholesale_amount": _money(wholesale_amount),
        "reseller_profit_amount": _money(reseller_profit_amount),
        "created_at": now,
        "completed_at": None,
    }
    res = await db.orders.insert_one(order)
    order["_id"] = res.inserted_id
    return order


async def mark_order_status(order_id: Any, status: str, *, session=None) -> None:
    payload = {"status": status}
    if status in {"done", "failed", "refunded", "cancelled", "success"}:
        payload["completed_at"] = datetime.now(UTC)
    await db.orders.update_one({"_id": order_id}, {"$set": payload}, session=session)


async def process_core_purchase(
    *,
    user_id: int,
    order_id: Any,
    sale_price: float,
    cost_price: float,
    actor_id: int,
    reseller_id: Optional[int] = None,
) -> tuple[bool, str, dict]:
    if reseller_id is None:
        return False, "RESELLER_REQUIRED", {}
    reseller_id = int(reseller_id)

    sale_amount = _money_decimal(sale_price)
    cost_amount = _money_decimal(cost_price)

    lock_key = f"user:{user_id}:reseller:{reseller_id}:buy"
    if not await acquire_session_lock(lock_key):
        _log_financial_event(
            "core_purchase_locked",
            level=logging.WARNING,
            user_id=user_id,
            reseller_id=reseller_id,
            order_id=order_id,
        )
        return False, "LOCKED", {}

    async def _txn(session):
        user_balance = _money_decimal(await _get_wallet_balance("user", user_id, "user", reseller_id, session=session))
        if user_balance < sale_amount:
            _log_financial_event(
                "core_purchase_rejected",
                level=logging.WARNING,
                reason="INSUFFICIENT_USER_BALANCE",
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
                user_balance=float(user_balance),
                sale_price=float(sale_amount),
            )
            return False, "INSUFFICIENT_USER_BALANCE", {}

        cycle = _cycle_key()
        user_tx = await _apply_wallet_delta(
            owner_type="user",
            owner_id=user_id,
            reseller_id=reseller_id,
            wallet_type="user",
            amount=-sale_amount,
            reason="purchase_core_user_debit",
            actor_type="user",
            actor_id=actor_id,
            order_id=order_id,
            cycle_key=cycle,
            session=session,
        )
        await mark_order_status(order_id, "paid", session=session)
        return True, "OK", {
            "reseller_id": reseller_id,
            "tx_ids": [user_tx["_id"]],
        }

    try:
        result = await _run_in_transaction(_txn)
        if result[0]:
            _log_financial_event(
                "core_purchase_committed",
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
                sale_price=float(sale_amount),
                cost_price=float(cost_amount),
                tx_ids=result[2].get("tx_ids"),
            )
        return result
    except RuntimeError as exc:
        _log_financial_event(
            "core_purchase_failed",
            level=logging.ERROR,
            user_id=user_id,
            reseller_id=reseller_id,
            order_id=order_id,
            error=str(exc),
        )
        return False, str(exc), {}
    finally:
        await release_session_lock(lock_key)


async def refund_core_purchase(
    *,
    user_id: int,
    order_id: Any,
    sale_price: float,
    cost_price: float,
    actor_id: int,
    reseller_id: Optional[int] = None,
) -> tuple[bool, str, dict]:
    if reseller_id is None:
        return False, "RESELLER_REQUIRED", {}
    reseller_id = int(reseller_id)

    sale_amount = _money_decimal(sale_price)
    cost_amount = _money_decimal(cost_price)
    lock_key = f"user:{user_id}:reseller:{reseller_id}:refund:{order_id}"
    if not await acquire_session_lock(lock_key):
        _log_financial_event(
            "core_refund_locked",
            level=logging.WARNING,
            user_id=user_id,
            reseller_id=reseller_id,
            order_id=order_id,
        )
        return False, "LOCKED", {}

    async def _txn(session):
        already_refunded = await _ledger_entry_exists(
            {
                "order_id": order_id,
                "reason": "refund_core_user_credit",
                "direction": "credit",
                "owner_type": "user",
                "owner_id": int(user_id),
                "reseller_id": int(reseller_id),
                "wallet_type": "user",
            },
            session=session,
        )
        if already_refunded:
            await mark_order_status(order_id, "refunded", session=session)
            _log_financial_event(
                "core_refund_already_applied",
                level=logging.WARNING,
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
            )
            return True, "ALREADY_REFUNDED", {"reseller_id": reseller_id, "idempotent": True}
        cycle = _cycle_key()
        await _apply_wallet_delta(
            owner_type="user",
            owner_id=user_id,
            reseller_id=reseller_id,
            wallet_type="user",
            amount=sale_amount,
            reason="refund_core_user_credit",
            actor_type="system",
            actor_id=actor_id,
            order_id=order_id,
            cycle_key=cycle,
            session=session,
        )
        await mark_order_status(order_id, "refunded", session=session)
        return True, "OK", {"reseller_id": reseller_id}

    try:
        result = await _run_in_transaction(_txn)
        if result[0]:
            _log_financial_event(
                "core_refund_committed",
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
                sale_price=float(sale_amount),
                cost_price=float(cost_amount),
            )
        return result
    except RuntimeError as exc:
        _log_financial_event(
            "core_refund_failed",
            level=logging.ERROR,
            user_id=user_id,
            reseller_id=reseller_id,
            order_id=order_id,
            error=str(exc),
        )
        return False, str(exc), {}
    finally:
        await release_session_lock(lock_key)


async def process_custom_purchase(
    *,
    user_id: int,
    order_id: Any,
    price: float,
    actor_id: int,
    reseller_id: Optional[int] = None,
) -> tuple[bool, str, dict]:
    if reseller_id is None:
        return False, "RESELLER_REQUIRED", {}
    reseller_id = int(reseller_id)

    price_amount = _money_decimal(price)
    net_profit = _money(price_amount if _profit_policy_enabled() else 0)

    lock_key = f"user:{user_id}:reseller:{reseller_id}:buy"
    if not await acquire_session_lock(lock_key):
        _log_financial_event(
            "custom_purchase_locked",
            level=logging.WARNING,
            user_id=user_id,
            reseller_id=reseller_id,
            order_id=order_id,
        )
        return False, "LOCKED", {}

    async def _txn(session):
        user_balance = _money_decimal(await _get_wallet_balance("user", user_id, "user", reseller_id, session=session))
        if user_balance < price_amount:
            _log_financial_event(
                "custom_purchase_rejected",
                level=logging.WARNING,
                reason="INSUFFICIENT_USER_BALANCE",
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
                user_balance=float(user_balance),
                price=float(price_amount),
            )
            return False, "INSUFFICIENT_USER_BALANCE", {}

        cycle = _cycle_key()
        await _apply_wallet_delta(
            owner_type="user",
            owner_id=user_id,
            reseller_id=reseller_id,
            wallet_type="user",
            amount=-float(price_amount),
            reason="purchase_custom_user_debit",
            actor_type="user",
            actor_id=actor_id,
            order_id=order_id,
            cycle_key=cycle,
            session=session,
        )
        if net_profit != 0:
            await _apply_wallet_delta(
                owner_type="reseller",
                owner_id=reseller_id,
                reseller_id=reseller_id,
                wallet_type="reseller_earnings",
                amount=net_profit,
                reason="purchase_custom_profit_credit",
                actor_type="system",
                actor_id=actor_id,
                order_id=order_id,
                cycle_key=cycle,
                session=session,
            )
        await mark_order_status(order_id, "paid", session=session)
        return True, "OK", {"reseller_id": reseller_id, "net_profit": net_profit}

    try:
        result = await _run_in_transaction(_txn)
        if result[0]:
            _log_financial_event(
                "custom_purchase_committed",
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
                price=float(price_amount),
                net_profit=float(net_profit),
            )
        return result
    except RuntimeError as exc:
        _log_financial_event(
            "custom_purchase_failed",
            level=logging.ERROR,
            user_id=user_id,
            reseller_id=reseller_id,
            order_id=order_id,
            error=str(exc),
        )
        return False, str(exc), {}
    finally:
        await release_session_lock(lock_key)


async def refund_custom_purchase(
    *,
    user_id: int,
    order_id: Any,
    price: float,
    actor_id: int,
    reseller_id: Optional[int] = None,
) -> tuple[bool, str, dict]:
    if reseller_id is None:
        return False, "RESELLER_REQUIRED", {}
    reseller_id = int(reseller_id)

    price_amount = _money_decimal(price)
    net_profit = _money(price_amount if _profit_policy_enabled() else 0)
    lock_key = f"user:{user_id}:reseller:{reseller_id}:refund:{order_id}"
    if not await acquire_session_lock(lock_key):
        _log_financial_event(
            "custom_refund_locked",
            level=logging.WARNING,
            user_id=user_id,
            reseller_id=reseller_id,
            order_id=order_id,
        )
        return False, "LOCKED", {}

    async def _txn(session):
        already_refunded = await _ledger_entry_exists(
            {
                "order_id": order_id,
                "reason": "refund_custom_user_credit",
                "direction": "credit",
                "owner_type": "user",
                "owner_id": int(user_id),
                "reseller_id": int(reseller_id),
                "wallet_type": "user",
            },
            session=session,
        )
        if already_refunded:
            await mark_order_status(order_id, "refunded", session=session)
            _log_financial_event(
                "custom_refund_already_applied",
                level=logging.WARNING,
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
            )
            return True, "ALREADY_REFUNDED", {"reseller_id": reseller_id, "net_profit": net_profit, "idempotent": True}
        cycle = _cycle_key()
        await _apply_wallet_delta(
            owner_type="user",
            owner_id=user_id,
            reseller_id=reseller_id,
            wallet_type="user",
            amount=float(price_amount),
            reason="refund_custom_user_credit",
            actor_type="system",
            actor_id=actor_id,
            order_id=order_id,
            cycle_key=cycle,
            session=session,
        )
        if net_profit != 0:
            await _apply_wallet_delta(
                owner_type="reseller",
                owner_id=reseller_id,
                reseller_id=reseller_id,
                wallet_type="reseller_earnings",
                amount=-net_profit,
                reason="refund_custom_profit_debit",
                actor_type="system",
                actor_id=actor_id,
                order_id=order_id,
                cycle_key=cycle,
                session=session,
            )
        await mark_order_status(order_id, "refunded", session=session)
        return True, "OK", {"reseller_id": reseller_id, "net_profit": net_profit}

    try:
        result = await _run_in_transaction(_txn)
        if result[0]:
            _log_financial_event(
                "custom_refund_committed",
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
                price=float(price_amount),
                net_profit=float(net_profit),
            )
        return result
    except RuntimeError as exc:
        _log_financial_event(
            "custom_refund_failed",
            level=logging.ERROR,
            user_id=user_id,
            reseller_id=reseller_id,
            order_id=order_id,
            error=str(exc),
        )
        return False, str(exc), {}
    finally:
        await release_session_lock(lock_key)


def _cycle_bounds(cycle_key: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(f"{cycle_key}-01", "%Y-%m-%d").replace(tzinfo=UTC)
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(start.year, start.month + 1, 1, tzinfo=UTC)
    return start, end


async def reconcile_recharge_requests_vs_ledger(*, reseller_id: int, cycle_key: str, max_rows: int = 20) -> dict:
    start, end = _cycle_bounds(cycle_key)
    reseller_id = int(reseller_id)
    max_rows = max(1, min(int(max_rows), 100))

    request_docs = await db.recharge_requests.find(
        {
            "reseller_id": reseller_id,
            "status": "accepted",
            "reviewed_at": {"$gte": start, "$lt": end},
        },
        {
            "_id": 1,
            "user_id": 1,
            "reseller_id": 1,
            "wallet_type": 1,
            "amount": 1,
            "approved_amount": 1,
            "reviewed_at": 1,
        },
    ).to_list(None)

    ledger_docs = await db.ledger_entries.find(
        {
            "reason": "recharge_request_accepted",
            "direction": "credit",
            "created_at": {"$gte": start, "$lt": end},
            "$or": [
                {
                    "owner_type": "user",
                    "reseller_id": reseller_id,
                    "wallet_type": "user",
                },
                {
                    "owner_type": "reseller",
                    "owner_id": reseller_id,
                    "wallet_type": "reseller_main",
                },
            ],
        },
        {
            "_id": 1,
            "order_id": 1,
            "owner_type": 1,
            "owner_id": 1,
            "reseller_id": 1,
            "wallet_type": 1,
            "amount": 1,
            "created_at": 1,
        },
    ).to_list(None)

    request_map = {str(r["_id"]): r for r in request_docs if r.get("_id") is not None}
    ledger_map = {}
    for led in ledger_docs:
        order_id = led.get("order_id")
        if order_id is None:
            continue
        ledger_map[str(order_id)] = led

    missing_ledger = []
    amount_mismatch = []
    target_mismatch = []

    for request_id, req in request_map.items():
        led = ledger_map.get(request_id)
        expected_amount = _money(req.get("approved_amount") if req.get("approved_amount") is not None else req.get("amount", 0))
        wallet_type = str(req.get("wallet_type") or "user").strip().lower()
        expected_owner_type = "reseller" if wallet_type in {"reseller_main", "main", "reseller"} else "user"
        expected_wallet_type = "reseller_main" if expected_owner_type == "reseller" else "user"

        if not led:
            missing_ledger.append(
                {
                    "request_id": request_id,
                    "expected_amount": expected_amount,
                    "expected_owner_type": expected_owner_type,
                }
            )
            continue

        ledger_amount = _money(led.get("amount", 0))
        if ledger_amount != expected_amount:
            amount_mismatch.append(
                {
                    "request_id": request_id,
                    "request_amount": expected_amount,
                    "ledger_amount": ledger_amount,
                }
            )

        if led.get("owner_type") != expected_owner_type or led.get("wallet_type") != expected_wallet_type:
            target_mismatch.append(
                {
                    "request_id": request_id,
                    "expected": f"{expected_owner_type}:{expected_wallet_type}",
                    "actual": f"{led.get('owner_type')}:{led.get('wallet_type')}",
                }
            )

    orphan_ledger = []
    for order_id, led in ledger_map.items():
        if order_id not in request_map:
            orphan_ledger.append(
                {
                    "order_id": order_id,
                    "ledger_amount": _money(led.get("amount", 0)),
                    "owner_type": led.get("owner_type"),
                    "wallet_type": led.get("wallet_type"),
                }
            )

    return {
        "reseller_id": reseller_id,
        "cycle_key": cycle_key,
        "accepted_requests": len(request_docs),
        "ledger_entries": len(ledger_docs),
        "missing_ledger_count": len(missing_ledger),
        "amount_mismatch_count": len(amount_mismatch),
        "target_mismatch_count": len(target_mismatch),
        "orphan_ledger_count": len(orphan_ledger),
        "missing_ledger": missing_ledger[:max_rows],
        "amount_mismatch": amount_mismatch[:max_rows],
        "target_mismatch": target_mismatch[:max_rows],
        "orphan_ledger": orphan_ledger[:max_rows],
    }


async def scan_financial_anomalies(*, days: int = 30, max_rows: int = 20) -> dict:
    now = datetime.now(UTC)
    days = max(1, int(days))
    max_rows = max(1, min(int(max_rows), 100))
    since = now - timedelta(days=days)

    negative_wallet_docs = await db.wallets.find(
        {"balance": {"$lt": 0}},
        {
            "_id": 0,
            "owner_type": 1,
            "owner_id": 1,
            "reseller_id": 1,
            "wallet_type": 1,
            "balance": 1,
        },
    ).limit(max_rows).to_list(length=max_rows)

    order_docs = await db.orders.find(
        {
            "created_at": {"$gte": since},
            "status": {"$in": ["paid", "success", "done", "refunded"]},
        },
        {
            "_id": 1,
            "user_id": 1,
            "reseller_id": 1,
            "status": 1,
            "service_type": 1,
            "created_at": 1,
        },
    ).to_list(None)
    order_ids = [doc["_id"] for doc in order_docs if doc.get("_id") is not None]
    order_lookup_ids = list(order_ids)
    order_lookup_ids.extend(str(order_id) for order_id in order_ids)
    order_ledger_ids = set()
    if order_ids:
        ledger_rows = await db.ledger_entries.find(
            {"order_id": {"$in": order_lookup_ids}},
            {"order_id": 1},
        ).to_list(None)
        order_ledger_ids = {str(row.get("order_id")) for row in ledger_rows if row.get("order_id") is not None}
    orders_missing_ledger = [
        {
            "order_id": str(doc.get("_id")),
            "status": doc.get("status"),
            "service_type": doc.get("service_type"),
            "user_id": doc.get("user_id"),
            "reseller_id": doc.get("reseller_id"),
        }
        for doc in order_docs
        if str(doc.get("_id")) not in order_ledger_ids
    ]

    recharge_docs = await db.recharge_requests.find(
        {
            "status": "accepted",
            "reviewed_at": {"$gte": since},
        },
        {
            "_id": 1,
            "user_id": 1,
            "reseller_id": 1,
            "wallet_type": 1,
            "amount": 1,
            "approved_amount": 1,
        },
    ).to_list(None)
    recharge_ids = [doc["_id"] for doc in recharge_docs if doc.get("_id") is not None]
    recharge_ledger_ids = set()
    if recharge_ids:
        recharge_ledger_rows = await db.ledger_entries.find(
            {
                "reason": "recharge_request_accepted",
                "direction": "credit",
                "order_id": {"$in": recharge_ids},
            },
            {"order_id": 1},
        ).to_list(None)
        recharge_ledger_ids = {
            row.get("order_id")
            for row in recharge_ledger_rows
            if row.get("order_id") is not None
        }
    accepted_recharges_without_ledger = [
        {
            "request_id": str(doc.get("_id")),
            "user_id": doc.get("user_id"),
            "reseller_id": doc.get("reseller_id"),
            "wallet_type": doc.get("wallet_type"),
            "amount": _money(doc.get("approved_amount") if doc.get("approved_amount") is not None else doc.get("amount", 0)),
        }
        for doc in recharge_docs
        if doc.get("_id") not in recharge_ledger_ids
    ]

    result = {
        "days": days,
        "since": since,
        "negative_wallets_count": len(negative_wallet_docs),
        "orders_missing_ledger_count": len(orders_missing_ledger),
        "accepted_recharges_without_ledger_count": len(accepted_recharges_without_ledger),
        "negative_wallets": negative_wallet_docs[:max_rows],
        "orders_missing_ledger": orders_missing_ledger[:max_rows],
        "accepted_recharges_without_ledger": accepted_recharges_without_ledger[:max_rows],
    }
    _log_financial_event(
        "financial_anomalies_scanned",
        days=days,
        negative_wallets=result["negative_wallets_count"],
        orders_missing_ledger=result["orders_missing_ledger_count"],
        accepted_recharges_without_ledger=result["accepted_recharges_without_ledger_count"],
    )
    return result


async def export_financial_audit_rows(*, days: int = 30, max_rows: int = 100) -> list[dict]:
    report = await scan_financial_anomalies(days=days, max_rows=max_rows)
    rows: list[dict] = []
    for row in report["negative_wallets"]:
        rows.append({"kind": "negative_wallet", **row})
    for row in report["orders_missing_ledger"]:
        rows.append({"kind": "order_missing_ledger", **row})
    for row in report["accepted_recharges_without_ledger"]:
        rows.append({"kind": "accepted_recharge_missing_ledger", **row})
    return rows




