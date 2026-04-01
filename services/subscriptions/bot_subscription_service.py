from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from config import settings
from database.financial_ledger import (
    acquire_session_lock,
    credit_reseller_main_wallet,
    get_reseller_wallet_balance,
    release_session_lock,
)
from database.mongo import db

logger = logging.getLogger("bot_subscription")

_PLAN_DISCOUNT_BY_MONTHS = {
    1: 0.0,
    6: 0.10,
    12: 0.20,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _monthly_price() -> float:
    try:
        value = float(getattr(settings, "reseller_bot_monthly_price_usd", 10.0) or 10.0)
    except Exception:
        value = 10.0
    return value if value > 0 else 10.0


def _trial_price() -> float:
    try:
        value = float(getattr(settings, "reseller_bot_trial_price_usd", 1.0) or 1.0)
    except Exception:
        value = 1.0
    return value if value > 0 else 1.0


def _normalize_plan_months(value) -> int:
    try:
        months = int(value or 1)
    except Exception:
        months = 1
    return months if months in _PLAN_DISCOUNT_BY_MONTHS else 1


def _plan_discount_percent(months: int) -> float:
    return float(_PLAN_DISCOUNT_BY_MONTHS.get(_normalize_plan_months(months), 0.0))


def _plan_total_price(months: int) -> float:
    months = _normalize_plan_months(months)
    base = _monthly_price() * months
    total = base * (1.0 - _plan_discount_percent(months))
    return round(total, 2)


def _trial_days() -> int:
    try:
        value = int(getattr(settings, "reseller_bot_trial_days", 30) or 30)
    except Exception:
        value = 30
    return value if value > 0 else 30


def _grace_days() -> int:
    try:
        value = int(getattr(settings, "reseller_bot_grace_days", 3) or 3)
    except Exception:
        value = 3
    return value if value > 0 else 3


def _seed_plan_fields(subscription: dict) -> dict:
    sub = dict(subscription or {})
    months = _normalize_plan_months(sub.get("renewal_plan_months") or 1)
    sub["renewal_plan_months"] = months
    sub["renewal_charge_usd"] = _plan_total_price(months)
    sub["monthly_price_usd"] = _monthly_price()
    sub["trial_price_usd"] = float(sub.get("trial_price_usd") or _trial_price())
    sub["renewal_discount_percent"] = round(_plan_discount_percent(months) * 100.0, 2)
    return sub


def get_subscription_plan_options() -> list[dict]:
    return [
        {
            "months": months,
            "price_usd": _plan_total_price(months),
            "discount_percent": round(_plan_discount_percent(months) * 100.0, 2),
        }
        for months in (1, 6, 12)
    ]


async def _owner_has_trial_history(owner_id: int) -> bool:
    existing = await db.bots.find_one(
        {
            "owner_id": int(owner_id),
            "$or": [
                {"subscription.trial_granted": True},
                {"subscription.history.trial_granted": True},
            ],
        },
        {"_id": 1},
    )
    return existing is not None


def _build_trial_subscription(*, now: datetime) -> dict:
    return _seed_plan_fields(
        {
            "monthly_price_usd": _monthly_price(),
            "trial_price_usd": _trial_price(),
            "trial_granted": True,
            "status": "payment_required",
            "trial_available": True,
            "trial_started_at": None,
            "trial_ends_at": None,
            "subscription_started_at": None,
            "subscription_ends_at": None,
            "grace_ends_at": None,
            "history": {
                "trial_granted": True,
            },
            "payment_required_since": now,
        }
    )


def _build_payment_required_subscription(*, now: datetime) -> dict:
    return _seed_plan_fields(
        {
            "monthly_price_usd": _monthly_price(),
            "trial_price_usd": _trial_price(),
            "trial_granted": False,
            "status": "payment_required",
            "trial_available": False,
            "trial_started_at": None,
            "trial_ends_at": None,
            "subscription_started_at": None,
            "subscription_ends_at": None,
            "grace_ends_at": None,
            "history": {
                "trial_granted": False,
            },
            "payment_required_since": now,
        }
    )


def _subscription_charge_key(
    *,
    bot_id: int,
    trial_available: bool,
    status: str,
    plan_months: int,
    subscription_ends_at: datetime | None,
    trial_ends_at: datetime | None,
) -> str:
    if trial_available:
        return f"bot_subscription:{int(bot_id)}:trial:first"
    anchor = subscription_ends_at or trial_ends_at
    if anchor is not None:
        anchor_key = anchor.astimezone(UTC).strftime("%Y%m%d%H%M%S")
    elif status in {"payment_required", "suspended"}:
        anchor_key = "resume"
    else:
        anchor_key = "unknown"
    return f"bot_subscription:{int(bot_id)}:renew:{anchor_key}:m{int(plan_months)}"


async def _subscription_charge_already_applied(charge_key: str, owner_id: int) -> bool:
    found = await db.ledger_entries.find_one(
        {
            "order_id": str(charge_key),
            "owner_type": "reseller",
            "owner_id": int(owner_id),
            "wallet_type": "reseller_main",
            "direction": "debit",
        },
        {"_id": 1},
    )
    return bool(found)


async def build_initial_subscription_for_owner(owner_id: int, *, now: datetime | None = None) -> dict:
    created_at = _as_utc(now) or _utc_now()
    had_trial = await _owner_has_trial_history(int(owner_id))
    if had_trial:
        return _build_payment_required_subscription(now=created_at)
    return _build_trial_subscription(now=created_at)


def _normalize_subscription_state(subscription: dict | None, *, created_at: datetime | None) -> dict:
    now = _utc_now()
    sub = _seed_plan_fields(subscription or {})
    if "trial_granted" not in sub:
        sub["trial_granted"] = False
    if "trial_available" not in sub:
        sub["trial_available"] = bool(sub.get("trial_granted")) and _as_utc(sub.get("trial_started_at")) is None

    status = str(sub.get("status") or "").strip().lower()
    trial_started_at = _as_utc(sub.get("trial_started_at"))
    trial_ends_at = _as_utc(sub.get("trial_ends_at"))
    subscription_ends_at = _as_utc(sub.get("subscription_ends_at"))
    grace_ends_at = _as_utc(sub.get("grace_ends_at"))

    if bool(sub.get("trial_granted")) and trial_ends_at is None and trial_started_at is not None:
        trial_ends_at = trial_started_at + timedelta(days=_trial_days())
        sub["trial_started_at"] = trial_started_at
        sub["trial_ends_at"] = trial_ends_at
        grace_ends_at = trial_ends_at + timedelta(days=_grace_days())
        sub["grace_ends_at"] = grace_ends_at

    if status == "trial_active":
        if trial_ends_at and now < trial_ends_at:
            return sub
        status = "grace_period"

    if status == "active":
        if subscription_ends_at and now < subscription_ends_at:
            return sub
        status = "grace_period"
        if subscription_ends_at and grace_ends_at is None:
            grace_ends_at = subscription_ends_at + timedelta(days=_grace_days())
            sub["grace_ends_at"] = grace_ends_at

    if status == "grace_period":
        if grace_ends_at is None:
            anchor = subscription_ends_at or trial_ends_at or created_at or now
            grace_ends_at = anchor + timedelta(days=_grace_days())
            sub["grace_ends_at"] = grace_ends_at
        if now < grace_ends_at:
            sub["status"] = "grace_period"
            return sub
        status = "suspended"

    if not status:
        if bool(sub.get("trial_granted")) and trial_ends_at:
            status = "trial_active" if trial_ends_at and now < trial_ends_at else "grace_period"
        elif subscription_ends_at:
            status = "active" if now < subscription_ends_at else "grace_period"
        else:
            status = "payment_required"

    sub["status"] = status
    if status == "payment_required":
        sub["subscription_started_at"] = None
        sub["subscription_ends_at"] = None
    if status == "suspended" and grace_ends_at is not None:
        sub["grace_ends_at"] = grace_ends_at
    return sub


async def _attempt_subscription_auto_renew(bot: dict, subscription: dict, *, created_at: datetime) -> dict:
    now = _utc_now()
    sub = dict(subscription or {})
    status = str(sub.get("status") or "").strip().lower()
    if status not in {"grace_period", "payment_required", "suspended"}:
        return sub

    owner_id = int(bot.get("owner_id") or 0)
    if owner_id <= 0:
        return sub

    plan_months = _normalize_plan_months(sub.get("renewal_plan_months") or 1)
    trial_available = bool(sub.get("trial_available")) and bool(sub.get("trial_granted")) and _as_utc(sub.get("trial_started_at")) is None
    renewal_price = float(sub.get("renewal_charge_usd") or _plan_total_price(plan_months) or 10.0)
    charge_amount = float(sub.get("trial_price_usd") or _trial_price()) if trial_available else renewal_price
    if charge_amount <= 0:
        charge_amount = _trial_price() if trial_available else _plan_total_price(plan_months)

    current_balance = await get_reseller_wallet_balance(owner_id, wallet_type="main")
    if current_balance + 1e-9 < charge_amount:
        return sub

    grace_ends_at = _as_utc(sub.get("grace_ends_at"))
    subscription_ends_at = _as_utc(sub.get("subscription_ends_at"))
    trial_ends_at = _as_utc(sub.get("trial_ends_at"))
    bot_id = int(bot.get("bot_id") or 0)
    charge_key = _subscription_charge_key(
        bot_id=bot_id,
        trial_available=trial_available,
        status=status,
        plan_months=plan_months,
        subscription_ends_at=subscription_ends_at,
        trial_ends_at=trial_ends_at,
    )
    lock_key = f"bot_subscription:{bot_id}:charge"
    if not await acquire_session_lock(lock_key):
        logger.warning("bot subscription charge locked bot_id=%s owner_id=%s", bot_id, owner_id)
        return sub

    anchor = subscription_ends_at or trial_ends_at or created_at or now
    if grace_ends_at is not None and now > grace_ends_at:
        anchor = now
    elif anchor < now and status == "payment_required":
        anchor = now
    new_end = anchor + timedelta(days=30 * plan_months)

    debit_reason = "bot_subscription_trial_debit" if trial_available else "bot_subscription_auto_renewal_debit"

    try:
        if await _subscription_charge_already_applied(charge_key, owner_id):
            logger.warning(
                "bot subscription charge already applied bot_id=%s owner_id=%s charge_key=%s",
                bot_id,
                owner_id,
                charge_key,
            )
        else:
            await credit_reseller_main_wallet(
                reseller_id=owner_id,
                amount=-charge_amount,
                reason=debit_reason,
                actor_id=owner_id,
                order_id=charge_key,
            )
    except Exception as exc:
        logger.warning(
            "bot subscription auto-renew failed owner_id=%s bot_id=%s: %s",
            owner_id,
            bot_id,
            exc,
        )
        return sub
    finally:
        await release_session_lock(lock_key)

    updated = dict(sub)
    updated.pop("payment_required_since", None)
    updated["renewal_plan_months"] = plan_months
    updated["renewal_charge_usd"] = renewal_price
    updated["renewal_discount_percent"] = round(_plan_discount_percent(plan_months) * 100.0, 2)

    if trial_available:
        trial_start = now
        trial_end = trial_start + timedelta(days=_trial_days())
        updated["status"] = "trial_active"
        updated["trial_available"] = False
        updated["trial_started_at"] = trial_start
        updated["trial_ends_at"] = trial_end
        updated["subscription_started_at"] = None
        updated["subscription_ends_at"] = None
        updated["grace_ends_at"] = trial_end + timedelta(days=_grace_days())
    else:
        updated["status"] = "active"
        updated["trial_available"] = False
        updated["subscription_started_at"] = anchor
        updated["subscription_ends_at"] = new_end
        updated["grace_ends_at"] = new_end + timedelta(days=_grace_days())

    history = dict(updated.get("history") or {})
    if trial_available:
        history["trial_paid_at"] = now
        history["trial_paid_amount"] = charge_amount
        history["trial_paid_owner_id"] = owner_id
        history["trial_charge_key"] = charge_key
    else:
        history["last_auto_renew_at"] = now
        history["last_auto_renew_amount"] = charge_amount
        history["last_auto_renew_months"] = plan_months
        history["last_auto_renew_owner_id"] = owner_id
        history["last_auto_renew_charge_key"] = charge_key
    updated["history"] = history
    logger.info(
        "bot subscription charge collected bot_id=%s owner_id=%s amount=%.2f status=%s",
        int(bot.get("bot_id") or 0),
        owner_id,
        charge_amount,
        updated.get("status"),
    )
    return updated


async def sync_bot_subscription(bot_id: int, *, collect_due: bool = False) -> dict:
    bot = await db.bots.find_one({"bot_id": int(bot_id)})
    if not bot:
        return {}

    raw_subscription = bot.get("subscription") if isinstance(bot.get("subscription"), dict) else None
    created_at = _as_utc(bot.get("created_at")) or _utc_now()
    if raw_subscription is None:
        current = await build_initial_subscription_for_owner(int(bot.get("owner_id") or 0), now=created_at)
        current = _normalize_subscription_state(current, created_at=created_at)
    else:
        current = _normalize_subscription_state(raw_subscription, created_at=created_at)

    if collect_due:
        current = await _attempt_subscription_auto_renew(bot, current, created_at=created_at)

    if current != (bot.get("subscription") or {}):
        await db.bots.update_one({"bot_id": int(bot_id)}, {"$set": {"subscription": current}})
    return current


async def get_bot_subscription(bot_id: int) -> dict:
    return await sync_bot_subscription(int(bot_id), collect_due=False)


async def get_bot_subscription_status(bot_id: int) -> str:
    sub = await get_bot_subscription(int(bot_id))
    return str(sub.get("status") or "")


async def bot_subscription_is_blocked(bot_id: int) -> bool:
    status = await get_bot_subscription_status(int(bot_id))
    return status in {"payment_required", "suspended"}


async def activate_bot_subscription(bot_id: int, *, months: int = 1, note: str | None = None) -> dict:
    bot = await db.bots.find_one({"bot_id": int(bot_id)})
    if not bot:
        return {}

    sub = await get_bot_subscription(int(bot_id))
    now = _utc_now()
    months_int = _normalize_plan_months(months)
    current_end = _as_utc(sub.get("subscription_ends_at"))
    grace_ends_at = _as_utc(sub.get("grace_ends_at"))
    trial_ends_at = _as_utc(sub.get("trial_ends_at"))
    anchor = current_end or trial_ends_at or now
    if grace_ends_at is not None and now > grace_ends_at:
        anchor = now
    elif anchor < now and str(sub.get("status") or "").strip().lower() == "payment_required":
        anchor = now
    new_end = anchor + timedelta(days=30 * months_int)

    updated = dict(sub)
    updated["status"] = "active"
    updated["subscription_started_at"] = anchor
    updated["subscription_ends_at"] = new_end
    updated["grace_ends_at"] = new_end + timedelta(days=_grace_days())
    updated["renewal_plan_months"] = months_int
    updated["renewal_charge_usd"] = _plan_total_price(months_int)
    updated["renewal_discount_percent"] = round(_plan_discount_percent(months_int) * 100.0, 2)
    history = dict(updated.get("history") or {})
    history["last_activation_at"] = now
    history["last_activation_months"] = months_int
    history["last_activation_amount"] = updated["renewal_charge_usd"]
    if note:
        history["last_activation_note"] = str(note).strip()
    updated["history"] = history
    await db.bots.update_one({"bot_id": int(bot_id)}, {"$set": {"subscription": updated}})
    return updated


async def set_bot_subscription_plan(bot_id: int, *, months: int) -> dict:
    bot = await db.bots.find_one({"bot_id": int(bot_id)})
    if not bot:
        return {}

    sub = await get_bot_subscription(int(bot_id))
    months_int = _normalize_plan_months(months)
    updated = dict(sub)
    updated["renewal_plan_months"] = months_int
    updated["renewal_charge_usd"] = _plan_total_price(months_int)
    updated["renewal_discount_percent"] = round(_plan_discount_percent(months_int) * 100.0, 2)
    history = dict(updated.get("history") or {})
    history["last_plan_change_at"] = _utc_now()
    history["last_plan_months"] = months_int
    updated["history"] = history
    await db.bots.update_one({"bot_id": int(bot_id)}, {"$set": {"subscription": updated}})
    return await get_bot_subscription(int(bot_id))


async def run_bot_subscription_sweep(*, limit: int = 500) -> dict:
    scanned = 0
    renewed = 0
    status_changed = 0
    cursor = db.bots.find({"active": True}, {"bot_id": 1, "subscription": 1}).limit(max(1, int(limit)))
    async for row in cursor:
        try:
            bot_id = int(row.get("bot_id") or 0)
        except Exception:
            continue
        if bot_id <= 0:
            continue
        before = dict(row.get("subscription") or {})
        before_status = str(before.get("status") or "").strip().lower()
        before_end = _as_utc(before.get("subscription_ends_at"))
        after = await sync_bot_subscription(bot_id, collect_due=True)
        after_status = str(after.get("status") or "").strip().lower()
        after_end = _as_utc(after.get("subscription_ends_at"))
        scanned += 1
        if before_status != after_status:
            status_changed += 1
        if after_status == "active" and (before_status != "active" or before_end != after_end):
            renewed += 1
    return {
        "scanned": scanned,
        "renewed": renewed,
        "status_changed": status_changed,
    }


async def mark_bot_subscription_grace_notice(bot_id: int, *, sent_at: datetime | None = None) -> None:
    when = sent_at or _utc_now()
    await db.bots.update_one(
        {"bot_id": int(bot_id)},
        {"$set": {"subscription.history.last_grace_notice_at": when}},
    )


async def mark_bot_subscription_expiry_notice(bot_id: int, *, sent_at: datetime | None = None) -> None:
    when = sent_at or _utc_now()
    await db.bots.update_one(
        {"bot_id": int(bot_id)},
        {"$set": {"subscription.history.last_expiry_notice_at": when}},
    )
