"""Shared rental protection helpers for Numbers orders."""

from datetime import UTC, datetime
from typing import Any

from services.numbers.shared.temp_order import _to_utc_datetime, _utc_now

HERO_RENTAL_CANCEL_WINDOW_SEC = 1200
RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC = 1800


def _rental_no_sms_yet(order: dict | None) -> bool:
    order = order or {}
    if order.get("rental_sms_received_at"):
        return False
    count = int(order.get("rental_sms_count") or 0)
    if count > 0:
        return False
    return True


def _is_within_hero_rental_cancel_window(
    order: dict | None,
    *,
    hero_cancel_window_sec: int | float = HERO_RENTAL_CANCEL_WINDOW_SEC,
) -> bool:
    order = order or {}
    start_dt = _to_utc_datetime(order.get("rental_started_at")) or _to_utc_datetime(order.get("created_at"))
    if not start_dt:
        return False
    now = _utc_now()
    return (now - start_dt).total_seconds() <= float(hero_cancel_window_sec or HERO_RENTAL_CANCEL_WINDOW_SEC)


def _rental_protection_policy(
    provider_code: str | None,
    *,
    rental_watch_poll_sec: int | float = 30,
    rental_guard_fallback_sync_window_sec: int | float = RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC,
    rental_safe_cutoff_sec: int | float = 60,
    hero_cancel_window_sec: int | float = HERO_RENTAL_CANCEL_WINDOW_SEC,
    smspool_refund_window_sec: Any = None,
    textverified_refund_window_sec: Any = None,
) -> dict[str, Any]:
    code = str(provider_code or "").strip().lower()
    poll_sec = max(20, int(rental_watch_poll_sec or 30))
    fallback_sync_window = max(300, int(rental_guard_fallback_sync_window_sec or RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC))
    policy = {
        "provider": code,
        "close_method": "finish",
        "refund_deadline_sec": None,
        "safe_cutoff_sec": max(30, int(rental_safe_cutoff_sec or 60)),
        "watch_poll_sec": poll_sec,
        "fallback_sync_window_sec": fallback_sync_window,
    }
    if code == "herosms":
        policy["close_method"] = "cancel"
        policy["refund_deadline_sec"] = max(60, int(hero_cancel_window_sec or HERO_RENTAL_CANCEL_WINDOW_SEC))
    elif code == "smspool":
        deadline = smspool_refund_window_sec
        if deadline not in (None, ""):
            try:
                policy["refund_deadline_sec"] = max(60, int(deadline))
            except (TypeError, ValueError):
                policy["refund_deadline_sec"] = None
    elif code == "textverified":
        deadline = textverified_refund_window_sec
        if deadline not in (None, ""):
            try:
                policy["refund_deadline_sec"] = max(60, int(deadline))
            except (TypeError, ValueError):
                policy["refund_deadline_sec"] = None
    return policy


def _rental_deadline_at(order: dict | None) -> datetime | None:
    order = order or {}
    explicit = _to_utc_datetime(order.get("rental_refund_deadline_at"))
    if explicit:
        return explicit
    start_dt = _to_utc_datetime(order.get("rental_started_at")) or _to_utc_datetime(order.get("created_at"))
    if not start_dt:
        return None
    deadline_sec = (order.get("rental_protection_policy") or {}).get("refund_deadline_sec")
    if not deadline_sec:
        return None
    return datetime.fromtimestamp(start_dt.timestamp() + int(deadline_sec), tz=UTC)


def _rental_safe_cutoff_at(order: dict | None) -> datetime | None:
    order = order or {}
    explicit = _to_utc_datetime(order.get("rental_safe_cutoff_at"))
    if explicit:
        return explicit
    deadline_at = _rental_deadline_at(order)
    if not deadline_at:
        return None
    safe_cutoff_sec = int((order.get("rental_protection_policy") or {}).get("safe_cutoff_sec") or 60)
    return datetime.fromtimestamp(deadline_at.timestamp() - max(30, safe_cutoff_sec), tz=UTC)
