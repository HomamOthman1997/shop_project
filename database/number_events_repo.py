from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from .mongo import db


_BOT_EVENT_SOURCES = {
    "auto_cancel_refund_guard_success",
    "auto_cancel_refund_global_guard_success",
    "auto_protection_triggered",
    "auto_refund_retry_success",
    "guard_sms_detected",
    "manual_refresh_no_sms",
    "manual_voice_check_no_call",
    "wait_timeout",
    "wait_timeout_auto_refunded",
}
_CUSTOMER_EVENT_SOURCES = {
    "alternate_provider_suggested",
    "replacement_requested",
    "second_code_attempted",
    "second_code_requested",
}
_PROVIDER_EVENT_SOURCES = {
    "call_received",
    "code_received",
    "code_received_recovery",
    "provider_buy_failed",
    "provider_buy_started",
    "provider_buy_success",
    "provider_cancel_failed",
    "provider_rent_failed",
    "provider_rent_started",
    "provider_rent_success",
    "refresh_code_received",
    "rental_sms_received",
    "second_code_provider_rejected",
    "second_code_provider_success",
    "voice_call_received",
}
_FINANCIAL_EVENT_SOURCES = {
    "cancelled_refunded",
    "refund_failed",
    "refund_success",
    "wallet_charged",
}

_POSITIVE_PROVIDER_SIGNALS = {
    "call_received",
    "code_received",
    "code_received_recovery",
    "guard_sms_detected",
    "provider_buy_success",
    "provider_rent_success",
    "refresh_code_received",
    "rental_sms_received",
    "second_code_provider_success",
    "voice_call_received",
}
_NEGATIVE_PROVIDER_SIGNALS = {
    "provider_buy_failed",
    "provider_cancel_failed",
    "provider_rent_failed",
    "rental_finish_failed",
    "rental_renew_failed",
    "rental_wake_failed",
    "refund_failed",
    "second_code_charge_failed",
    "second_code_not_allowed",
    "second_code_provider_rejected",
    "wait_timeout",
    "wait_timeout_auto_refunded",
}
_PROTECTION_PROVIDER_SIGNALS = {
    "auto_cancel_refund_guard_success",
    "auto_cancel_refund_global_guard_success",
    "auto_protection_triggered",
    "auto_refund_retry_success",
    "cancelled_refunded",
    "refund_success",
}
_ATTEMPT_PROVIDER_SIGNALS = {
    "purchase_success",
    "provider_buy_started",
    "provider_rent_started",
    "wallet_charged",
}


async def bootstrap_number_events_indexes() -> None:
    await db.number_order_events.create_index([("created_at", -1)], background=True)
    await db.number_order_events.create_index([("order_id", 1), ("created_at", -1)], background=True)
    await db.number_order_events.create_index([("number_mode", 1), ("created_at", -1)], background=True)
    await db.number_order_events.create_index([("provider", 1), ("service_id", 1), ("created_at", -1)], background=True)
    await db.number_order_events.create_index([("event", 1), ("created_at", -1)], background=True)
    await db.number_order_events.create_index([("user_id", 1), ("created_at", -1)], background=True)
    await db.number_order_events.create_index([("reseller_id", 1), ("created_at", -1)], background=True)
    await db.number_order_events.create_index([("provider_signal", 1), ("created_at", -1)], background=True)
    await db.number_order_events.create_index([("signal_source", 1), ("created_at", -1)], background=True)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_order_id(value: Any) -> Any:
    return value


def classify_number_event_source(event: str, payload: dict[str, Any] | None = None) -> str:
    event_name = str(event or "").strip().lower()
    payload = payload or {}
    explicit = str(payload.get("source") or "").strip().lower()
    if explicit in {"bot", "customer", "provider", "support", "system", "financial"}:
        return explicit
    if explicit in {"miniapp", "numbers_miniapp", "numbers_api", "telegram", "api"}:
        return "customer"
    if explicit.startswith("auto_"):
        return "bot"
    if event_name in _BOT_EVENT_SOURCES:
        return "bot"
    if event_name in _CUSTOMER_EVENT_SOURCES:
        return "customer"
    if event_name in _PROVIDER_EVENT_SOURCES:
        return "provider"
    if event_name in _FINANCIAL_EVENT_SOURCES:
        return "financial"
    return "system"


def classify_number_provider_signal(event: str) -> str:
    event_name = str(event or "").strip().lower()
    if event_name in _POSITIVE_PROVIDER_SIGNALS:
        return "success"
    if event_name in _NEGATIVE_PROVIDER_SIGNALS:
        return "failure"
    if event_name in _PROTECTION_PROVIDER_SIGNALS:
        return "protection"
    if event_name in _ATTEMPT_PROVIDER_SIGNALS:
        return "attempt"
    return "neutral"


def _provider_signal_weight(signal: str) -> int:
    signal = str(signal or "").strip().lower()
    if signal == "success":
        return 1
    if signal == "failure":
        return -1
    return 0


async def log_number_order_event(
    *,
    order_id: Any,
    user_id: int,
    reseller_id: int | None,
    provider: str,
    service_id: str,
    number_mode: str,
    event: str,
    status_before: str | None = None,
    status_after: str | None = None,
    sale_price: float | None = None,
    cost_price: float | None = None,
    provider_order_id: str | None = None,
    provider_number: str | None = None,
    country: str | None = None,
    state: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_name = str(event or "").strip().lower()
    provider_signal = classify_number_provider_signal(event_name)
    signal_source = classify_number_event_source(event_name, payload)
    doc = {
        "order_id": _as_order_id(order_id),
        "user_id": int(user_id),
        "reseller_id": int(reseller_id) if reseller_id is not None else None,
        "provider": str(provider or "").strip().lower(),
        "service_id": str(service_id or "").strip(),
        "number_mode": str(number_mode or "").strip().lower(),
        "event": event_name,
        "signal_source": signal_source,
        "provider_signal": provider_signal,
        "provider_signal_weight": _provider_signal_weight(provider_signal),
        "status_before": str(status_before or "").strip().lower() or None,
        "status_after": str(status_after or "").strip().lower() or None,
        "sale_price": float(sale_price or 0),
        "cost_price": float(cost_price or 0),
        "provider_order_id": str(provider_order_id or "").strip() or None,
        "provider_number": str(provider_number or "").strip() or None,
        "country": str(country or "").strip() or None,
        "state": str(state or "").strip() or None,
        "payload": dict(payload or {}),
        "created_at": _utc_now(),
    }
    await db.number_order_events.insert_one(doc)
    return doc


async def list_number_order_events(*, since: datetime, until: datetime | None = None, limit: int = 10000) -> list[dict[str, Any]]:
    match: dict[str, Any] = {"created_at": {"$gte": since}}
    if until:
        match["created_at"]["$lte"] = until
    cursor = db.number_order_events.find(match).sort("created_at", 1).limit(int(limit))
    return await cursor.to_list(length=int(limit))


async def list_number_order_events_for_order(order_id: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    if order_id is None:
        return []
    safe_limit = max(1, min(50, int(limit or 12)))
    cursor = db.number_order_events.find({"order_id": _as_order_id(order_id)}).sort("created_at", -1).limit(safe_limit)
    rows = await cursor.to_list(length=safe_limit)
    rows.reverse()
    return rows


def build_numbers_report_from_events(events: list[dict[str, Any]], *, since: datetime, until: datetime) -> dict[str, Any]:
    total_events = len(events)
    order_latest: dict[Any, dict[str, Any]] = {}
    order_event_names: defaultdict[Any, set[str]] = defaultdict(set)
    event_counts: Counter[str] = Counter()
    provider_service_stats: dict[tuple[str, str, str], dict[str, Any]] = {}
    provider_failures: Counter[tuple[str, str, str]] = Counter()
    no_code_cases: Counter[tuple[str, str, str]] = Counter()
    second_code_cases: Counter[tuple[str, str, str]] = Counter()
    second_code_failures: Counter[tuple[str, str, str]] = Counter()
    protection_saved: Counter[tuple[str, str, str]] = Counter()
    total_seconds_to_first_sms: defaultdict[tuple[str, str, str], list[int]] = defaultdict(list)
    total_seconds_to_second_code: defaultdict[tuple[str, str, str], list[int]] = defaultdict(list)
    suspicious_users: Counter[int] = Counter()
    provider_monitor: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

    for event in events:
        event_name = str(event.get("event") or "").strip().lower()
        payload_obj = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        signal_source = str(event.get("signal_source") or "").strip().lower() or classify_number_event_source(
            event_name,
            payload_obj,
        )
        provider_signal = str(event.get("provider_signal") or "").strip().lower() or classify_number_provider_signal(event_name)
        event_counts[event_name] += 1
        order_id = event.get("order_id")
        if order_id is not None:
            order_latest[order_id] = event
            order_event_names[order_id].add(event_name)

        provider = str(event.get("provider") or "").strip().lower() or "-"
        service_id = str(event.get("service_id") or "").strip() or "-"
        mode = str(event.get("number_mode") or "").strip().lower() or "-"
        country = str(event.get("country") or payload_obj.get("country") or "").strip() or "-"
        state = str(event.get("state") or payload_obj.get("state") or "").strip() or "-"
        key = (mode, provider, service_id)
        monitor_key = (mode, provider, service_id, country, state)
        monitor_row = provider_monitor.setdefault(
            monitor_key,
            {
                "number_mode": mode,
                "provider": provider,
                "service_id": service_id,
                "country": country,
                "state": state,
                "orders": set(),
                "events": 0,
                "attempt_signals": 0,
                "success_signals": 0,
                "failure_signals": 0,
                "protection_signals": 0,
                "neutral_signals": 0,
                "bot_signals": 0,
                "customer_signals": 0,
                "provider_signals": 0,
                "financial_signals": 0,
                "system_signals": 0,
            },
        )
        monitor_row["events"] += 1
        if order_id is not None:
            monitor_row["orders"].add(order_id)
        signal_key = f"{provider_signal}_signals"
        if signal_key in monitor_row:
            monitor_row[signal_key] += 1
        source_key = f"{signal_source}_signals"
        if source_key in monitor_row:
            monitor_row[source_key] += 1
        else:
            monitor_row["system_signals"] += 1
        bucket = provider_service_stats.setdefault(
            key,
            {
                "number_mode": mode,
                "provider": provider,
                "service_id": service_id,
                "purchase_attempts": 0,
                "provider_success": 0,
                "codes_received": 0,
                "refunds": 0,
                "provider_failures": 0,
                "second_code_attempts": 0,
                "second_code_requests": 0,
                "second_code_failures": 0,
                "avg_seconds_to_second_code": None,
                "protection_saved": 0,
                "avg_seconds_to_first_sms": None,
            },
        )
        if event_name in {"wallet_charged", "purchase_success"}:
            bucket["purchase_attempts"] += 1
        if event_name in {"provider_buy_success", "provider_rent_success", "purchase_success"}:
            bucket["provider_success"] += 1
        if event_name in {"code_received", "refresh_code_received", "code_received_recovery", "guard_sms_detected"}:
            bucket["codes_received"] += 1
        if event_name in {"refund_success", "cancelled_refunded"}:
            bucket["refunds"] += 1
        if event_name in {"provider_buy_failed", "provider_rent_failed"}:
            bucket["provider_failures"] += 1
            provider_failures[key] += 1
        if event_name == "second_code_attempted":
            bucket["second_code_attempts"] += 1
        if event_name == "second_code_requested":
            bucket["second_code_requests"] += 1
            second_code_cases[key] += 1
        if event_name in {"second_code_provider_rejected", "second_code_not_allowed", "second_code_charge_failed"}:
            bucket["second_code_failures"] += 1
            second_code_failures[key] += 1
        if event_name in {
            "auto_cancel_refund_guard_success",
            "auto_cancel_refund_global_guard_success",
            "wait_timeout_auto_refunded",
            "auto_refund_retry_success",
            "auto_protection_triggered",
        }:
            bucket["protection_saved"] += 1
            protection_saved[key] += 1
        seconds_to_first_sms = event.get("payload", {}).get("seconds_since_purchase")
        try:
            if seconds_to_first_sms is not None:
                total_seconds_to_first_sms[key].append(int(seconds_to_first_sms))
        except Exception:
            pass
        seconds_to_second_code = event.get("payload", {}).get("seconds_since_first_code")
        try:
            if event_name == "second_code_requested" and seconds_to_second_code is not None:
                total_seconds_to_second_code[key].append(int(seconds_to_second_code))
        except Exception:
            pass
        if event_name in {"wait_timeout", "wait_timeout_auto_refunded", "cancelled_refunded"}:
            no_code_cases[key] += 1
            try:
                suspicious_users[int(event.get("user_id") or 0)] += 1
            except Exception:
                pass

    orders_summary = {
        "total_orders_seen": len(order_latest),
        "temp_orders": 0,
        "rental_orders": 0,
        "successful_orders": 0,
        "refunded_orders": 0,
        "failed_orders": 0,
        "open_orders": 0,
    }
    for latest in order_latest.values():
        mode = str(latest.get("number_mode") or "").strip().lower()
        status_after = str(latest.get("status_after") or latest.get("status_before") or "").strip().lower()
        if mode == "temp":
            orders_summary["temp_orders"] += 1
        elif mode == "rental":
            orders_summary["rental_orders"] += 1
        if status_after in {"success", "done"}:
            orders_summary["successful_orders"] += 1
        elif status_after in {"refunded", "cancelled"}:
            orders_summary["refunded_orders"] += 1
        elif status_after in {"failed", "expired"}:
            orders_summary["failed_orders"] += 1
        else:
            orders_summary["open_orders"] += 1

    provider_rows = []
    for key, row in provider_service_stats.items():
        sms_times = total_seconds_to_first_sms.get(key) or []
        if sms_times:
            row["avg_seconds_to_first_sms"] = round(sum(sms_times) / len(sms_times), 2)
        second_code_times = total_seconds_to_second_code.get(key) or []
        if second_code_times:
            row["avg_seconds_to_second_code"] = round(sum(second_code_times) / len(second_code_times), 2)
        provider_rows.append(row)

    monitor_rows = []
    for row in provider_monitor.values():
        attempts = int(row.get("attempt_signals") or 0)
        successes = int(row.get("success_signals") or 0)
        failures = int(row.get("failure_signals") or 0)
        scored = successes + failures
        score = round((successes / scored) * 100.0, 2) if scored > 0 else None
        confidence = "none"
        if attempts >= 20 or scored >= 20:
            confidence = "high"
        elif attempts >= 5 or scored >= 5:
            confidence = "medium"
        elif attempts > 0 or scored > 0:
            confidence = "low"
        out = {k: v for k, v in row.items() if k != "orders"}
        out["orders"] = len(row.get("orders") or set())
        out["monitor_score"] = score
        out["confidence"] = confidence
        monitor_rows.append(out)

    def _top_counter_rows(counter: Counter[tuple[str, str, str]], *, label: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for (mode, provider, service_id), count in counter.most_common(10):
            rows.append(
                {
                    "label": label,
                    "number_mode": mode,
                    "provider": provider,
                    "service_id": service_id,
                    "count": int(count),
                }
            )
        return rows

    suspicious_rows = [
        {"user_id": int(user_id), "no_code_events": int(count)}
        for user_id, count in suspicious_users.most_common(10)
        if int(user_id) > 0
    ]

    return {
        "window": {
            "since": since.isoformat(),
            "until": until.isoformat(),
        },
        "totals": {
            "events": total_events,
            **orders_summary,
        },
        "event_counts": dict(sorted(event_counts.items())),
        "provider_service_summary": sorted(
            provider_rows,
            key=lambda item: (
                -int(item.get("purchase_attempts") or 0),
                -int(item.get("codes_received") or 0),
                str(item.get("provider") or ""),
                str(item.get("service_id") or ""),
            ),
        ),
        "provider_monitor_summary": sorted(
            monitor_rows,
            key=lambda item: (
                str(item.get("confidence") or "") != "high",
                -(int(item.get("failure_signals") or 0) + int(item.get("protection_signals") or 0)),
                -(int(item.get("success_signals") or 0)),
                str(item.get("provider") or ""),
                str(item.get("service_id") or ""),
            ),
        ),
        "top_provider_failures": _top_counter_rows(provider_failures, label="provider_failures"),
        "top_no_code_cases": _top_counter_rows(no_code_cases, label="no_code_cases"),
        "top_second_code_usage": _top_counter_rows(second_code_cases, label="second_code_usage"),
        "top_second_code_failures": _top_counter_rows(second_code_failures, label="second_code_failures"),
        "top_protection_saved": _top_counter_rows(protection_saved, label="protection_saved"),
        "suspicious_users": suspicious_rows,
    }


async def build_numbers_report(*, days: int = 7, until: datetime | None = None, limit: int = 10000) -> dict[str, Any]:
    end_dt = until or _utc_now()
    start_dt = end_dt - timedelta(days=max(1, int(days or 7)))
    events = await list_number_order_events(since=start_dt, until=end_dt, limit=limit)
    return build_numbers_report_from_events(events, since=start_dt, until=end_dt)
