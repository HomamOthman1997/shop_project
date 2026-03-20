from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Any, Optional
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import ConfigurationError, InvalidOperation, OperationFailure

from database.mongo import client, db
from config import OWNER_ID, settings
from database.reseller_settings_repo import get_reseller_rates

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
    if "settlement" in normalized:
        return "settlement", ["settlement"]
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
    await db.orders.create_index([("reseller_id", 1), ("created_at", -1)], background=True)
    await db.settlements.create_index([("reseller_id", 1), ("cycle_key", 1)], unique=True, background=True)
    await db.settlements.create_index(
        [("payment_status", 1), ("payment_due_at", 1), ("services_locked", 1)],
        background=True,
    )
    await db.settlements.create_index([("reseller_id", 1), ("payment_status", 1)], background=True)
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


async def get_reseller_wallet_balance(reseller_id: int, wallet_type: str = "main") -> float:
    mapped = "reseller_main" if wallet_type == "main" else "reseller_earnings"
    return await _get_wallet_balance("reseller", reseller_id, mapped, reseller_id)


async def get_owner_wallet_balance(owner_id: int = OWNER_ID, wallet_type: str = "owner_fees") -> float:
    # Owner fees may be tracked per reseller context (wallet_key includes reseller_id),
    # so aggregate all owner wallets of the same type for accurate global balance.
    rows = await db.wallets.aggregate(
        [
            {
                "$match": {
                    "owner_type": "owner",
                    "owner_id": int(owner_id),
                    "wallet_type": wallet_type,
                }
            },
            {"$group": {"_id": None, "balance": {"$sum": "$balance"}}},
        ]
    ).to_list(1)
    if rows:
        return _money(rows[0].get("balance", 0))
    return 0.0


async def credit_owner_wallet(
    owner_id: int,
    amount: float,
    reason: str,
    *,
    actor_id: int,
    order_id=None,
    reseller_id: Optional[int] = None,
):
    return await _run_in_transaction(
        lambda session: _apply_wallet_delta(
            owner_type="owner",
            owner_id=int(owner_id),
            wallet_type="owner_fees",
            reseller_id=reseller_id,
            amount=amount,
            reason=reason,
            actor_type="system",
            actor_id=actor_id,
            order_id=order_id,
            session=session,
        )
    )


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
    owner_fee_amount: float = 0.0,
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
        "owner_fee_amount": _money(owner_fee_amount),
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
    rates = await get_reseller_rates(reseller_id)
    commission_rate = _money_decimal(rates.get("core_commission", 0.05))
    if not _profit_policy_enabled():
        commission_rate = Decimal("0")
    commission = _money(sale_amount * commission_rate)

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

        reseller_main = _money_decimal(
            await _get_wallet_balance("reseller", reseller_id, "reseller_main", reseller_id, session=session)
        )
        if reseller_main < cost_amount:
            _log_financial_event(
                "core_purchase_rejected",
                level=logging.WARNING,
                reason="INSUFFICIENT_RESELLER_MAIN",
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
                reseller_main=float(reseller_main),
                cost_price=float(cost_amount),
            )
            return False, "INSUFFICIENT_RESELLER_MAIN", {}

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
        reseller_main_tx = await _apply_wallet_delta(
            owner_type="reseller",
            owner_id=reseller_id,
            reseller_id=reseller_id,
            wallet_type="reseller_main",
            amount=-cost_amount,
            reason="purchase_core_main_debit",
            actor_type="system",
            actor_id=actor_id,
            order_id=order_id,
            cycle_key=cycle,
            session=session,
        )
        earnings_tx = None
        if commission != 0:
            earnings_tx = await _apply_wallet_delta(
                owner_type="reseller",
                owner_id=reseller_id,
                reseller_id=reseller_id,
                wallet_type="reseller_earnings",
                amount=commission,
                reason="purchase_core_commission_credit",
                actor_type="system",
                actor_id=actor_id,
                order_id=order_id,
                cycle_key=cycle,
                metadata={"commission_rate": float(commission_rate)},
                session=session,
            )
        await mark_order_status(order_id, "paid", session=session)
        tx_ids = [user_tx["_id"], reseller_main_tx["_id"]]
        if earnings_tx and earnings_tx.get("_id") is not None:
            tx_ids.append(earnings_tx["_id"])
        return True, "OK", {
            "reseller_id": reseller_id,
            "commission": commission,
            "tx_ids": tx_ids,
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
                commission=float(commission),
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
    rates = await get_reseller_rates(reseller_id)
    commission_rate = _money_decimal(rates.get("core_commission", 0.05))
    if not _profit_policy_enabled():
        commission_rate = Decimal("0")
    commission = _money(sale_amount * commission_rate)

    async def _txn(session):
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
        await _apply_wallet_delta(
            owner_type="reseller",
            owner_id=reseller_id,
            reseller_id=reseller_id,
            wallet_type="reseller_main",
            amount=cost_amount,
            reason="refund_core_main_credit",
            actor_type="system",
            actor_id=actor_id,
            order_id=order_id,
            cycle_key=cycle,
            session=session,
        )
        if commission != 0:
            await _apply_wallet_delta(
                owner_type="reseller",
                owner_id=reseller_id,
                reseller_id=reseller_id,
                wallet_type="reseller_earnings",
                amount=-commission,
                reason="refund_core_commission_debit",
                actor_type="system",
                actor_id=actor_id,
                order_id=order_id,
                cycle_key=cycle,
                session=session,
            )
        await mark_order_status(order_id, "refunded", session=session)
        return True, "OK", {"reseller_id": reseller_id, "commission": commission}

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
                commission=float(commission),
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
    rates = await get_reseller_rates(reseller_id)
    owner_fee_rate = _money_decimal(rates.get("owner_fee", 0.10))
    if not _profit_policy_enabled():
        owner_fee_rate = Decimal("0")
    owner_fee = _money(price_amount * owner_fee_rate)
    net_profit = _money(price_amount - Decimal(str(owner_fee)))

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
                metadata={"owner_fee": owner_fee, "owner_fee_rate": float(owner_fee_rate)},
                session=session,
            )
        if owner_fee != 0:
            await _apply_wallet_delta(
                owner_type="owner",
                owner_id=int(OWNER_ID),
                reseller_id=reseller_id,
                wallet_type="owner_fees",
                amount=owner_fee,
                reason="purchase_custom_owner_fee_credit",
                actor_type="system",
                actor_id=actor_id,
                order_id=order_id,
                cycle_key=cycle,
                metadata={"owner_fee_rate": float(owner_fee_rate)},
                session=session,
            )
        await mark_order_status(order_id, "paid", session=session)
        return True, "OK", {"reseller_id": reseller_id, "owner_fee": owner_fee, "net_profit": net_profit}

    try:
        result = await _run_in_transaction(_txn)
        if result[0]:
            _log_financial_event(
                "custom_purchase_committed",
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
                price=float(price_amount),
                owner_fee=float(owner_fee),
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
    rates = await get_reseller_rates(reseller_id)
    owner_fee_rate = _money_decimal(rates.get("owner_fee", 0.10))
    if not _profit_policy_enabled():
        owner_fee_rate = Decimal("0")
    owner_fee = _money(price_amount * owner_fee_rate)
    net_profit = _money(price_amount - Decimal(str(owner_fee)))

    async def _txn(session):
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
                metadata={"owner_fee": owner_fee, "owner_fee_rate": float(owner_fee_rate)},
                session=session,
            )
        if owner_fee != 0:
            await _apply_wallet_delta(
                owner_type="owner",
                owner_id=int(OWNER_ID),
                reseller_id=reseller_id,
                wallet_type="owner_fees",
                amount=-owner_fee,
                reason="refund_custom_owner_fee_debit",
                actor_type="system",
                actor_id=actor_id,
                order_id=order_id,
                cycle_key=cycle,
                metadata={"owner_fee_rate": float(owner_fee_rate)},
                session=session,
            )
        await mark_order_status(order_id, "refunded", session=session)
        return True, "OK", {"reseller_id": reseller_id, "owner_fee": owner_fee, "net_profit": net_profit}

    try:
        result = await _run_in_transaction(_txn)
        if result[0]:
            _log_financial_event(
                "custom_refund_committed",
                user_id=user_id,
                reseller_id=reseller_id,
                order_id=order_id,
                price=float(price_amount),
                owner_fee=float(owner_fee),
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


async def confirm_monthly_settlement(
    *,
    reseller_id: int,
    cycle_key: str,
    owner_id: int,
) -> dict:
    start = datetime.strptime(f"{cycle_key}-01", "%Y-%m-%d").replace(tzinfo=UTC)
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(start.year, start.month + 1, 1, tzinfo=UTC)

    base_match = {
        "owner_type": "reseller",
        "owner_id": reseller_id,
        "wallet_type": "reseller_earnings",
        "created_at": {"$gte": start, "$lt": end},
    }
    agg = await db.ledger_entries.aggregate(
        [
            {"$match": base_match},
            {
                "$group": {
                    "_id": None,
                    "earnings": {"$sum": "$amount"},
                    "core_commissions": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$reason", "purchase_core_commission_credit"]},
                                "$amount",
                                0,
                            ]
                        }
                    },
                    "custom_profit": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$reason", "purchase_custom_profit_credit"]},
                                "$amount",
                                0,
                            ]
                        }
                    },
                    "owner_fees": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$reason", "purchase_custom_profit_credit"]},
                                {"$ifNull": ["$metadata.owner_fee", 0]},
                                0,
                            ]
                        }
                    },
                }
            },
        ]
    ).to_list(1)
    owner_fee_agg = await db.ledger_entries.aggregate(
        [
            {
                "$match": {
                    "owner_type": "owner",
                    "owner_id": int(OWNER_ID),
                    "wallet_type": "owner_fees",
                    "reseller_id": reseller_id,
                    "created_at": {"$gte": start, "$lt": end},
                }
            },
            {"$group": {"_id": None, "owner_fees": {"$sum": "$amount"}}},
        ]
    ).to_list(1)
    owner_fees_total = _money(owner_fee_agg[0].get("owner_fees", 0) if owner_fee_agg else 0)

    stats = agg[0] if agg else {}
    earnings_total = _money(stats.get("earnings", 0))

    async def _txn(session):
        current = await _get_wallet_balance("reseller", reseller_id, "reseller_earnings", reseller_id, session=session)
        reset_tx = None
        if current > 0:
            reset_tx = await _apply_wallet_delta(
                owner_type="reseller",
                owner_id=reseller_id,
                reseller_id=reseller_id,
                wallet_type="reseller_earnings",
                amount=-current,
                reason="monthly_settlement_reset",
                actor_type="owner",
                actor_id=owner_id,
                cycle_key=cycle_key,
                session=session,
            )
        doc = {
            "reseller_id": reseller_id,
            "cycle_key": cycle_key,
            "opening_earnings": current,
            "core_commissions": _money(stats.get("core_commissions", 0)),
            "custom_profit": _money(stats.get("custom_profit", 0)),
            "owner_fees": owner_fees_total,
            "net_due": earnings_total,
            "status": "confirmed",
            "confirmed_by_owner_id": owner_id,
            "confirmed_at": datetime.now(UTC),
            "closing_anchor_tx_uuid": (reset_tx or {}).get("tx_uuid"),
            "wallet_snapshot": {
                "reseller_earnings_before_reset": float(current),
                "owner_fees_for_cycle": float(owner_fees_total),
            },
        }
        await db.settlements.update_one(
            {"reseller_id": reseller_id, "cycle_key": cycle_key},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.now(UTC)}},
            upsert=True,
            session=session,
        )
        return doc

    doc = await _run_in_transaction(_txn)
    _log_financial_event(
        "settlement_confirmed",
        reseller_id=reseller_id,
        cycle_key=cycle_key,
        owner_id=owner_id,
        net_due=float(doc.get("net_due", 0)),
        opening_earnings=float(doc.get("opening_earnings", 0)),
        owner_fees=float(doc.get("owner_fees", 0)),
    )
    return doc














async def get_monthly_settlement_preview(*, reseller_id: int, cycle_key: str) -> dict:
    start = datetime.strptime(f"{cycle_key}-01", "%Y-%m-%d").replace(tzinfo=UTC)
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(start.year, start.month + 1, 1, tzinfo=UTC)

    reseller_agg = await db.ledger_entries.aggregate(
        [
            {
                "$match": {
                    "owner_type": "reseller",
                    "owner_id": int(reseller_id),
                    "wallet_type": "reseller_earnings",
                    "created_at": {"$gte": start, "$lt": end},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "earnings": {"$sum": "$amount"},
                    "core_commissions": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$reason", "purchase_core_commission_credit"]},
                                "$amount",
                                0,
                            ]
                        }
                    },
                    "custom_profit": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$reason", "purchase_custom_profit_credit"]},
                                "$amount",
                                0,
                            ]
                        }
                    },
                }
            },
        ]
    ).to_list(1)

    owner_fee_agg = await db.ledger_entries.aggregate(
        [
            {
                "$match": {
                    "owner_type": "owner",
                    "owner_id": int(OWNER_ID),
                    "wallet_type": "owner_fees",
                    "reseller_id": int(reseller_id),
                    "created_at": {"$gte": start, "$lt": end},
                }
            },
            {"$group": {"_id": None, "owner_fees": {"$sum": "$amount"}}},
        ]
    ).to_list(1)

    stats = reseller_agg[0] if reseller_agg else {}
    owner_fees_total = _money(owner_fee_agg[0].get("owner_fees", 0) if owner_fee_agg else 0)
    current_earnings_wallet = await _get_wallet_balance("reseller", int(reseller_id), "reseller_earnings", int(reseller_id))

    return {
        "reseller_id": int(reseller_id),
        "cycle_key": cycle_key,
        "period_start": start,
        "period_end": end,
        "core_commissions": _money(stats.get("core_commissions", 0)),
        "custom_profit": _money(stats.get("custom_profit", 0)),
        "owner_fees": owner_fees_total,
        "net_due": _money(stats.get("earnings", 0)),
        "current_earnings_wallet": _money(current_earnings_wallet),
    }


def _cycle_bounds(cycle_key: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(f"{cycle_key}-01", "%Y-%m-%d").replace(tzinfo=UTC)
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(start.year, start.month + 1, 1, tzinfo=UTC)
    return start, end


async def generate_monthly_settlement_drafts(*, cycle_key: str) -> dict:
    start, end = _cycle_bounds(cycle_key)
    now = datetime.now(UTC)

    wallet_resellers = await db.wallets.distinct(
        "owner_id",
        {"owner_type": "reseller"},
    )
    earnings_resellers = await db.ledger_entries.distinct(
        "owner_id",
        {
            "owner_type": "reseller",
            "wallet_type": "reseller_earnings",
            "created_at": {"$gte": start, "$lt": end},
        },
    )
    owner_fees_resellers = await db.ledger_entries.distinct(
        "reseller_id",
        {
            "owner_type": "owner",
            "wallet_type": "owner_fees",
            "created_at": {"$gte": start, "$lt": end},
        },
    )

    reseller_ids = sorted(
        {
            int(x)
            for x in [*wallet_resellers, *earnings_resellers, *owner_fees_resellers]
            if x is not None
        }
    )
    stats = {"cycle_key": cycle_key, "total": len(reseller_ids), "drafted": 0, "skipped_confirmed": 0}

    for reseller_id in reseller_ids:
        existing = await db.settlements.find_one(
            {"reseller_id": reseller_id, "cycle_key": cycle_key},
            {"status": 1},
        )
        if existing and existing.get("status") == "confirmed":
            stats["skipped_confirmed"] += 1
            continue

        preview = await get_monthly_settlement_preview(reseller_id=reseller_id, cycle_key=cycle_key)
        bot_row = await db.bots.find_one(
            {"owner_id": reseller_id, "active": True},
            {"bot_id": 1},
        )
        payload = {
            "reseller_id": reseller_id,
            "cycle_key": cycle_key,
            "status": "draft",
            "core_commissions": _money(preview["core_commissions"]),
            "custom_profit": _money(preview["custom_profit"]),
            "owner_fees": _money(preview["owner_fees"]),
            "net_due": _money(preview["net_due"]),
            "opening_earnings": _money(preview["current_earnings_wallet"]),
            "period_start": start,
            "period_end": end,
            "draft_generated_at": now,
            "updated_at": now,
        }
        bot_id = bot_row.get("bot_id") if bot_row else None
        if bot_id is not None:
            payload["bot_id"] = int(bot_id)
        await db.settlements.update_one(
            {"reseller_id": reseller_id, "cycle_key": cycle_key},
            {"$set": payload, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        stats["drafted"] += 1

    _log_financial_event(
        "settlement_drafts_generated",
        cycle_key=cycle_key,
        total=stats["total"],
        drafted=stats["drafted"],
        skipped_confirmed=stats["skipped_confirmed"],
    )
    return stats


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
    order_ledger_ids = set()
    if order_ids:
        ledger_rows = await db.ledger_entries.find(
            {"order_id": {"$in": order_ids}},
            {"order_id": 1},
        ).to_list(None)
        order_ledger_ids = {row.get("order_id") for row in ledger_rows if row.get("order_id") is not None}
    orders_missing_ledger = [
        {
            "order_id": str(doc.get("_id")),
            "status": doc.get("status"),
            "service_type": doc.get("service_type"),
            "user_id": doc.get("user_id"),
            "reseller_id": doc.get("reseller_id"),
        }
        for doc in order_docs
        if doc.get("_id") not in order_ledger_ids
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

    settlement_docs = await db.settlements.find(
        {
            "services_locked": True,
            "payment_status": {"$in": ["pending", "overdue"]},
            "payment_due_at": {"$lte": now},
        },
        {
            "_id": 0,
            "reseller_id": 1,
            "cycle_key": 1,
            "net_due": 1,
            "payment_status": 1,
            "payment_due_at": 1,
        },
    ).limit(max_rows).to_list(length=max_rows)

    result = {
        "days": days,
        "since": since,
        "negative_wallets_count": len(negative_wallet_docs),
        "orders_missing_ledger_count": len(orders_missing_ledger),
        "accepted_recharges_without_ledger_count": len(accepted_recharges_without_ledger),
        "locked_overdue_settlements_count": len(settlement_docs),
        "negative_wallets": negative_wallet_docs[:max_rows],
        "orders_missing_ledger": orders_missing_ledger[:max_rows],
        "accepted_recharges_without_ledger": accepted_recharges_without_ledger[:max_rows],
        "locked_overdue_settlements": settlement_docs[:max_rows],
    }
    _log_financial_event(
        "financial_anomalies_scanned",
        days=days,
        negative_wallets=result["negative_wallets_count"],
        orders_missing_ledger=result["orders_missing_ledger_count"],
        accepted_recharges_without_ledger=result["accepted_recharges_without_ledger_count"],
        locked_overdue_settlements=result["locked_overdue_settlements_count"],
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
    for row in report["locked_overdue_settlements"]:
        rows.append({"kind": "locked_overdue_settlement", **row})
    return rows


def _add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=int(days))


async def enforce_settlement_payment_policies(*, cycle_key: str, grace_days: int = 4) -> dict:
    start, end = _cycle_bounds(cycle_key)
    due_at = _add_days(end, grace_days)
    now = datetime.now(UTC)

    await generate_monthly_settlement_drafts(cycle_key=cycle_key)
    settlements = await db.settlements.find(
        {"cycle_key": cycle_key},
        {
            "_id": 1,
            "reseller_id": 1,
            "cycle_key": 1,
            "net_due": 1,
            "payment_status": 1,
            "payment_due_at": 1,
            "payment_confirmed_at": 1,
            "services_locked": 1,
            "cycle_end_notice_sent_at": 1,
            "overdue_notice_sent_at": 1,
        },
    ).to_list(None)

    notices: list[dict] = []
    locked_now = 0

    for doc in settlements:
        reseller_id = int(doc.get("reseller_id") or 0)
        if reseller_id <= 0:
            continue

        net_due = _money(doc.get("net_due", 0))
        payment_status = str(doc.get("payment_status") or "pending").lower()
        is_paid = payment_status == "paid" or doc.get("payment_confirmed_at") is not None
        services_locked = bool(doc.get("services_locked"))
        payment_due_at = _as_utc(doc.get("payment_due_at")) or due_at
        updates = {
            "period_start": start,
            "period_end": end,
            "net_due": net_due,
            "payment_due_at": payment_due_at,
            "updated_at": now,
        }

        # No outstanding amount -> never lock this reseller for this cycle.
        if net_due <= 0:
            updates["payment_status"] = "paid"
            updates["services_locked"] = False
            if not doc.get("payment_auto_cleared_at"):
                updates["payment_auto_cleared_at"] = now
            await db.settlements.update_one({"_id": doc["_id"]}, {"$set": updates})
            continue

        if end <= now <= payment_due_at and not doc.get("cycle_end_notice_sent_at"):
            notices.append(
                {
                    "kind": "cycle_end",
                    "reseller_id": reseller_id,
                    "cycle_key": cycle_key,
                    "amount_due": net_due,
                    "payment_due_at": updates["payment_due_at"],
                    "grace_days": int(grace_days),
                }
            )
            updates["cycle_end_notice_sent_at"] = now

        if is_paid:
            if services_locked:
                updates["services_locked"] = False
            updates["payment_status"] = "paid"
            await db.settlements.update_one({"_id": doc["_id"]}, {"$set": updates})
            continue

        if now > payment_due_at:
            updates["payment_status"] = "overdue"
            updates["services_locked"] = True
            if not doc.get("overdue_notice_sent_at"):
                notices.append(
                    {
                        "kind": "overdue_lock",
                        "reseller_id": reseller_id,
                        "cycle_key": cycle_key,
                        "amount_due": net_due,
                        "payment_due_at": payment_due_at,
                        "grace_days": int(grace_days),
                    }
                )
                updates["overdue_notice_sent_at"] = now
            locked_now += 1
        else:
            updates["payment_status"] = "pending"
            updates["services_locked"] = False

        await db.settlements.update_one({"_id": doc["_id"]}, {"$set": updates})

    result = {"cycle_key": cycle_key, "count": len(settlements), "locked_now": locked_now, "notices": notices}
    _log_financial_event(
        "settlement_policy_checked",
        cycle_key=cycle_key,
        grace_days=grace_days,
        checked=result["count"],
        locked_now=locked_now,
        notices=len(notices),
    )
    return result


async def confirm_settlement_payment(
    *,
    reseller_id: int,
    cycle_key: str,
    owner_id: int,
    note: Optional[str] = None,
) -> dict:
    now = datetime.now(UTC)
    reseller_id = int(reseller_id)
    doc = await db.settlements.find_one({"reseller_id": reseller_id, "cycle_key": cycle_key})
    if not doc:
        await generate_monthly_settlement_drafts(cycle_key=cycle_key)
        doc = await db.settlements.find_one({"reseller_id": reseller_id, "cycle_key": cycle_key})
    if not doc:
        raise ValueError("SETTLEMENT_NOT_FOUND")

    await db.settlements.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "payment_status": "paid",
                "payment_confirmed_at": now,
                "payment_confirmed_by_owner_id": int(owner_id),
                "payment_note": (note or "").strip() or None,
                "services_locked": False,
                "updated_at": now,
            }
        },
    )
    updated = await db.settlements.find_one({"_id": doc["_id"]})
    _log_financial_event(
        "settlement_payment_confirmed",
        reseller_id=reseller_id,
        cycle_key=cycle_key,
        owner_id=owner_id,
        note=(note or "").strip() or None,
        net_due=float((updated or doc).get("net_due", 0)),
    )
    return updated or doc


async def get_reseller_financial_lock(reseller_id: int, bot_id: int | None = None) -> dict | None:
    reseller_id = int(reseller_id)
    now = datetime.now(UTC)
    query = {
        "reseller_id": reseller_id,
        "net_due": {"$gt": 0},
        "services_locked": True,
        "payment_status": {"$in": ["overdue", "pending"]},
        "payment_confirmed_at": {"$exists": False},
        "payment_due_at": {"$lte": now},
    }
    if bot_id is not None:
        query["bot_id"] = int(bot_id)
    lock = await db.settlements.find_one(query, sort=[("payment_due_at", 1)])
    if lock:
        _log_financial_event(
            "financial_lock_hit",
            level=logging.WARNING,
            reseller_id=reseller_id,
            bot_id=bot_id,
            cycle_key=lock.get("cycle_key"),
            net_due=float(lock.get("net_due", 0)),
        )
    return lock




