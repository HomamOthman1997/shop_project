from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from config import settings
from database.orders_repo import (
    extract_order_amounts,
    get_order,
    list_open_rental_orders_without_sms,
    update_order_details,
    update_order_status,
)
from services.numbers.manager import PROVIDERS, finish_rental_from_provider, get_rental_info_from_provider, get_rental_sms_from_provider
from services.numbers.provider_delivery import provider_sms_polling_enabled
from services.numbers.shared.events import _log_number_event_from_order, _log_rental_event
from services.numbers.shared.rental_policy import (
    HERO_RENTAL_CANCEL_WINDOW_SEC,
    RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC,
    _is_within_hero_rental_cancel_window as _policy_is_within_hero_rental_cancel_window,
    _rental_deadline_at as _policy_rental_deadline_at,
    _rental_no_sms_yet,
    _rental_protection_policy as _policy_rental_protection_policy,
    _rental_safe_cutoff_at as _policy_rental_safe_cutoff_at,
)
from services.numbers.shared.temp_order import _coerce_utc_datetime, _seconds_left_until, _to_utc_datetime, _utc_now
from utils.financial_manager import FinancialManager
from utils.provider_alias import provider_public_id
from utils.translations import t

logger = logging.getLogger("numbers_rental_protection")

RENTAL_OWNER_ALERT_WINDOW_SEC = 180


def rental_protection_policy(provider_code: str | None) -> dict[str, Any]:
    return _policy_rental_protection_policy(
        provider_code,
        rental_watch_poll_sec=getattr(settings, "numbers_rental_watch_poll_sec", 30),
        rental_guard_fallback_sync_window_sec=getattr(
            settings,
            "numbers_rental_guard_fallback_sync_window_sec",
            RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC,
        ),
        rental_safe_cutoff_sec=getattr(settings, "numbers_rental_safe_cutoff_sec", 60),
        hero_cancel_window_sec=getattr(settings, "numbers_hero_rental_cancel_window_sec", HERO_RENTAL_CANCEL_WINDOW_SEC),
        smspool_refund_window_sec=getattr(settings, "numbers_smspool_rental_refund_window_sec", None),
        textverified_refund_window_sec=getattr(settings, "numbers_textverified_rental_refund_window_sec", None),
    )


def is_within_hero_rental_cancel_window(order: dict | None) -> bool:
    return _policy_is_within_hero_rental_cancel_window(
        order,
        hero_cancel_window_sec=getattr(
            settings,
            "numbers_hero_rental_cancel_window_sec",
            HERO_RENTAL_CANCEL_WINDOW_SEC,
        ),
    )


def rental_deadline_at(order: dict | None) -> datetime | None:
    normalized = dict(order or {})
    normalized.setdefault("rental_protection_policy", rental_protection_policy(normalized.get("provider")))
    return _policy_rental_deadline_at(normalized)


def rental_safe_cutoff_at(order: dict | None) -> datetime | None:
    normalized = dict(order or {})
    normalized.setdefault("rental_protection_policy", rental_protection_policy(normalized.get("provider")))
    return _policy_rental_safe_cutoff_at(normalized)


def _source_payload(payload: dict[str, Any], event_source: str | None) -> dict[str, Any]:
    if event_source:
        payload = dict(payload)
        payload["source"] = event_source
    return payload


def _default_close_failed_alert_text(order_id: Any, provider_label: str, user_id: Any, reason: str) -> str:
    return t("en", "rental_close_failed_alert_text").format(
        order_id=order_id,
        provider=provider_label,
        user_id=user_id,
        reason=reason,
    )


def _default_near_cutoff_alert_text(order_id: Any, provider_label: str, user_id: Any, deadline: str, seconds_left: int) -> str:
    return t("en", "rental_near_cutoff_alert_text").format(
        order_id=order_id,
        provider=provider_label,
        user_id=user_id,
        deadline=deadline,
        seconds_left=seconds_left,
    )


async def sync_rental_sms_snapshot(
    order_id: Any,
    order: dict | None,
    *,
    provider_sms_polling_enabled_fn: Callable[[], bool] = provider_sms_polling_enabled,
    get_rental_sms_from_provider_fn: Callable[[str, str], Awaitable[dict[str, Any]]] = get_rental_sms_from_provider,
    update_order_details_fn: Callable[[Any, dict[str, Any]], Awaitable[Any]] = update_order_details,
    log_rental_event_fn: Callable[..., Awaitable[Any]] = _log_rental_event,
    utc_now_fn: Callable[[], datetime] = _utc_now,
    sms_detected_event: str = "guard_sms_detected",
    event_source: str | None = None,
    logger_obj: logging.Logger = logger,
) -> dict[str, Any]:
    order = order or {}
    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    stored_messages = [str(item) for item in (order.get("rental_sms_messages") or []) if str(item or "").strip()]
    if not provider_sms_polling_enabled_fn():
        return {
            "success": True,
            "messages": stored_messages,
            "has_sms": bool(stored_messages),
            "raw": "provider_sms_polling_disabled_waiting_for_webhook",
            "polling_disabled": True,
        }
    if not provider or not provider_order_id:
        return {"success": False, "messages": [], "has_sms": False, "reason": "provider_order_missing"}

    try:
        sms_data = await get_rental_sms_from_provider_fn(provider, provider_order_id)
    except Exception as exc:
        return {"success": False, "messages": [], "has_sms": False, "raw": str(exc)}

    messages = [str(item) for item in (sms_data.get("messages") or []) if str(item or "").strip()]
    has_sms = bool(messages)
    if has_sms:
        now = utc_now_fn()
        try:
            await update_order_details_fn(
                order_id,
                {
                    "rental_sms_received_at": now,
                    "rental_sms_count": len(messages),
                    "rental_last_sms_sync_at": now,
                    "rental_sms_messages": messages[:20],
                },
            )
        except Exception:
            logger_obj.exception("failed to persist rental sms snapshot: order=%s", order_id)
        with suppress(Exception):
            await log_rental_event_fn(
                order_id=order_id,
                user_id=int(order.get("user_id") or 0),
                provider=provider,
                service_id=str(order.get("service_id") or ""),
                event=sms_detected_event,
                payload=_source_payload({"messages_count": len(messages)}, event_source),
            )
    elif sms_data.get("success"):
        with suppress(Exception):
            await update_order_details_fn(order_id, {"rental_last_sms_sync_at": utc_now_fn()})
    return {"success": bool(sms_data.get("success")), "messages": messages, "has_sms": has_sms, "raw": sms_data.get("raw")}


async def sync_rental_protection_snapshot(
    order_id: Any,
    order: dict | None,
    *,
    get_rental_info_from_provider_fn: Callable[[str, str], Awaitable[dict[str, Any]]] = get_rental_info_from_provider,
    update_order_details_fn: Callable[[Any, dict[str, Any]], Awaitable[Any]] = update_order_details,
    policy_fn: Callable[[str | None], dict[str, Any]] = rental_protection_policy,
    utc_now_fn: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    order = order or {}
    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        return {"success": False, "reason": "provider_order_missing"}

    try:
        info = await get_rental_info_from_provider_fn(provider, provider_order_id)
    except Exception as exc:
        return {"success": False, "reason": "provider_info_failed", "raw": str(exc)}

    refund_deadline_at = _coerce_utc_datetime(info.get("refund_refundable_until"))
    end_date = _coerce_utc_datetime(info.get("end_date"))
    provider_can_refund = info.get("refund_can_refund")
    patch: dict[str, Any] = {"rental_last_policy_sync_at": utc_now_fn()}
    if end_date:
        patch["rental_end_date"] = end_date
    if refund_deadline_at and provider_can_refund is not False:
        patch["rental_refund_deadline_at"] = refund_deadline_at
        patch["rental_safe_cutoff_at"] = datetime.fromtimestamp(
            refund_deadline_at.timestamp() - max(30, int(policy_fn(provider).get("safe_cutoff_sec") or 60)),
            tz=UTC,
        )
    protection_policy = dict(order.get("rental_protection_policy") or {})
    if provider_can_refund is not None:
        protection_policy["provider_can_refund"] = bool(provider_can_refund)
        patch["rental_provider_can_refund"] = bool(provider_can_refund)
    if refund_deadline_at:
        protection_policy["provider_refund_deadline_at"] = refund_deadline_at
    if protection_policy:
        patch["rental_protection_policy"] = protection_policy
    if len(patch) > 1:
        with suppress(Exception):
            await update_order_details_fn(order_id, patch)
    return {
        "success": bool(info.get("success")),
        "refund_deadline_at": refund_deadline_at,
        "provider_can_refund": provider_can_refund,
        "end_date": end_date,
        "raw": info.get("raw"),
    }


async def provider_close_rental(
    order: dict,
    *,
    providers: dict[str, Any] = PROVIDERS,
    finish_rental_from_provider_fn: Callable[[str, str], Awaitable[dict[str, Any]]] = finish_rental_from_provider,
    policy_fn: Callable[[str | None], dict[str, Any]] = rental_protection_policy,
    sleep_fn: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> dict[str, Any]:
    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        return {"success": False, "reason": "provider_order_missing"}

    policy = policy_fn(provider)
    close_method = str(policy.get("close_method") or "finish").strip().lower()
    last_raw: Any = None
    for attempt in range(1, 4):
        try:
            if close_method == "cancel":
                prov = providers.get(provider)
                if not prov or not hasattr(prov, "cancel"):
                    return {"success": False, "reason": "provider_cancel_not_supported"}
                close_res = await asyncio.wait_for(prov.cancel(provider_order_id), timeout=12.0)
            else:
                close_res = await asyncio.wait_for(
                    finish_rental_from_provider_fn(provider, provider_order_id),
                    timeout=12.0,
                )
        except Exception as exc:
            close_res = {"success": False, "raw": str(exc)}
        last_raw = (close_res or {}).get("raw")
        if bool((close_res or {}).get("success")):
            return {"success": True, "raw": last_raw}
        if attempt < 3:
            await sleep_fn(float(attempt))
    return {"success": False, "reason": "provider_close_failed", "raw": last_raw}


async def cancel_and_refund_rental_order(
    *,
    order_id: Any,
    order: dict,
    actor_user_id: int,
    reason: str,
    require_no_sms: bool = False,
    sync_rental_sms_snapshot_fn: Callable[[Any, dict], Awaitable[dict[str, Any]]] | None = None,
    provider_close_rental_fn: Callable[[dict], Awaitable[dict[str, Any]]] | None = None,
    update_order_details_fn: Callable[[Any, dict[str, Any]], Awaitable[Any]] = update_order_details,
    update_order_status_fn: Callable[[Any, str], Awaitable[Any]] = update_order_status,
    log_number_event_from_order_fn: Callable[..., Awaitable[Any]] = _log_number_event_from_order,
    log_rental_event_fn: Callable[..., Awaitable[Any]] = _log_rental_event,
    financial_manager_cls: Any = FinancialManager,
    extract_order_amounts_fn: Callable[[dict], tuple[float, float]] = extract_order_amounts,
    utc_now_fn: Callable[[], datetime] = _utc_now,
    event_source: str | None = None,
) -> dict[str, Any]:
    if not order_id or not order:
        return {"success": False, "reason": "order_not_found"}
    status = str(order.get("status") or "").lower()
    if status in {"cancelled", "failed", "refunded", "expired"}:
        return {"success": False, "reason": "already_closed"}
    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        return {"success": False, "reason": "provider_order_missing"}
    if sync_rental_sms_snapshot_fn is None:
        sync_rental_sms_snapshot_fn = sync_rental_sms_snapshot
    if provider_close_rental_fn is None:
        provider_close_rental_fn = provider_close_rental

    now = utc_now_fn()
    await log_number_event_from_order_fn(
        order,
        "cancel_requested",
        payload=_source_payload({"reason": str(reason or "cancelled")}, event_source),
        number_mode="rental",
    )
    with suppress(Exception):
        await update_order_details_fn(
            order_id,
            {
                "rental_last_close_attempt_at": now,
                "rental_last_close_reason": str(reason or "cancelled"),
            },
        )
    if require_no_sms:
        sms_snapshot = await sync_rental_sms_snapshot_fn(order_id, order)
        if sms_snapshot.get("has_sms"):
            return {
                "success": False,
                "reason": "sms_received",
                "messages": sms_snapshot.get("messages") or [],
            }

    close_res = await provider_close_rental_fn(order)
    if not close_res.get("success"):
        await log_number_event_from_order_fn(
            order,
            "provider_close_failed",
            payload=_source_payload(
                {
                    "raw": close_res.get("raw"),
                    "reason": str(close_res.get("reason") or "provider_close_failed"),
                },
                event_source,
            ),
            number_mode="rental",
        )
        with suppress(Exception):
            await update_order_details_fn(
                order_id,
                {
                    "rental_last_close_error_at": utc_now_fn(),
                    "rental_last_close_error": str(close_res.get("reason") or "provider_close_failed"),
                    "rental_last_close_raw": close_res.get("raw"),
                },
            )
        return {
            "success": False,
            "reason": str(close_res.get("reason") or "provider_close_failed"),
            "raw": close_res.get("raw"),
        }

    sale_price, cost_price = extract_order_amounts_fn(order)
    ok, msg = await financial_manager_cls.refund_core_purchase(
        int(actor_user_id),
        order_id,
        sale_price,
        cost_price,
        reseller_id=int(order.get("reseller_id") or actor_user_id),
    )
    if not ok:
        await log_number_event_from_order_fn(
            order,
            "refund_failed",
            payload=_source_payload({"raw": msg, "reason": str(reason or "cancelled")}, event_source),
            number_mode="rental",
        )
        with suppress(Exception):
            await update_order_details_fn(
                order_id,
                {
                    "rental_last_close_error_at": utc_now_fn(),
                    "rental_last_close_error": "financial_refund_failed",
                    "rental_last_close_raw": msg,
                },
            )
        return {"success": False, "reason": "financial_refund_failed", "raw": msg}

    await update_order_status_fn(order_id, "cancelled")
    await update_order_details_fn(
        order_id,
        {
            "rental_cancelled_at": now,
            "rental_refunded_at": now,
            "rental_cancel_reason": str(reason or "cancelled"),
            "rental_last_close_error_at": None,
            "rental_last_close_error": None,
            "rental_last_close_raw": close_res.get("raw"),
        },
    )
    await log_rental_event_fn(
        order_id=order_id,
        user_id=int(order.get("user_id") or 0),
        provider=provider,
        service_id=str(order.get("service_id") or ""),
        event="cancelled_refunded",
        payload=_source_payload({"reason": str(reason or "cancelled")}, event_source),
    )
    await log_number_event_from_order_fn(
        order,
        "refund_success",
        payload=_source_payload({"reason": str(reason or "cancelled")}, event_source),
        status_after="cancelled",
        number_mode="rental",
    )
    return {"success": True, "reason": "ok"}


async def refresh_rental_order(
    order: dict[str, Any],
    *,
    get_order_fn: Callable[[Any], Awaitable[dict | None]] = get_order,
    sync_rental_sms_snapshot_fn: Callable[[Any, dict], Awaitable[dict[str, Any]]] = sync_rental_sms_snapshot,
) -> dict[str, Any]:
    if not order or not order.get("_id"):
        return order
    if str(order.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
        return order
    await sync_rental_sms_snapshot_fn(order["_id"], order)
    return await get_order_fn(order["_id"]) or order


async def rental_refund_guard(
    *,
    order_id: Any,
    actor_user_id: int,
    get_order_fn: Callable[[Any], Awaitable[dict | None]] = get_order,
    sync_rental_sms_snapshot_fn: Callable[[Any, dict], Awaitable[dict[str, Any]]] = sync_rental_sms_snapshot,
    cancel_and_refund_rental_order_fn: Callable[..., Awaitable[dict[str, Any]]] = cancel_and_refund_rental_order,
    sync_rental_protection_snapshot_fn: Callable[[Any, dict], Awaitable[dict[str, Any]]] = sync_rental_protection_snapshot,
    log_number_event_from_order_fn: Callable[..., Awaitable[Any]] = _log_number_event_from_order,
    log_rental_event_fn: Callable[..., Awaitable[Any]] = _log_rental_event,
    policy_fn: Callable[[str | None], dict[str, Any]] = rental_protection_policy,
    no_sms_yet_fn: Callable[[dict | None], bool] = _rental_no_sms_yet,
    utc_now_fn: Callable[[], datetime] = _utc_now,
    sleep_fn: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    deadline_event_source: str = "rental_guard",
    auto_event_source: str = "rental_guard",
    cancel_reason_suffix: str = "guard_no_sms_timeout",
) -> None:
    order = await get_order_fn(order_id)
    if not order:
        return
    provider = str(order.get("provider") or "").strip().lower()
    policy = policy_fn(provider)
    deadline_sec = policy.get("refund_deadline_sec")
    poll_sec = max(20, int(policy.get("watch_poll_sec") or 30))
    fallback_sync_window_sec = max(300, int(policy.get("fallback_sync_window_sec") or RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC))

    if provider in {"textverified", "smspool"}:
        with suppress(Exception):
            await sync_rental_protection_snapshot_fn(order_id, order)
            order = await get_order_fn(order_id) or order

    start_dt = _to_utc_datetime(order.get("rental_started_at")) or _to_utc_datetime(order.get("created_at"))
    if not start_dt:
        return
    deadline_ts = start_dt.timestamp() + int(deadline_sec) if deadline_sec else None
    cutoff_ts = None
    if deadline_ts:
        cutoff_ts = deadline_ts - max(30, int(policy.get("safe_cutoff_sec") or 60))
    sync_until_ts = deadline_ts or (start_dt.timestamp() + fallback_sync_window_sec)

    if cutoff_ts:
        wait_sec = max(0, int(cutoff_ts - utc_now_fn().timestamp()))
        if wait_sec > 0:
            await sleep_fn(wait_sec)

    while utc_now_fn().timestamp() <= sync_until_ts:
        latest = await get_order_fn(order_id)
        if not latest:
            return
        if str(latest.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
            return
        if not no_sms_yet_fn(latest):
            return

        sms_snapshot = await sync_rental_sms_snapshot_fn(order_id, latest)
        if sms_snapshot.get("has_sms"):
            return

        now_ts = utc_now_fn().timestamp()
        if cutoff_ts and now_ts >= cutoff_ts:
            await log_number_event_from_order_fn(
                latest,
                "deadline_reached",
                payload={"source": deadline_event_source},
                number_mode="rental",
            )
            result = await cancel_and_refund_rental_order_fn(
                order_id=order_id,
                order=latest,
                actor_user_id=int(actor_user_id),
                reason=f"{provider}_{cancel_reason_suffix}",
                require_no_sms=True,
            )
            if result.get("success"):
                await log_number_event_from_order_fn(
                    latest,
                    "auto_protection_triggered",
                    payload={"source": auto_event_source},
                    status_after="cancelled",
                    number_mode="rental",
                )
                await log_rental_event_fn(
                    order_id=order_id,
                    user_id=int(latest.get("user_id") or 0),
                    provider=provider,
                    service_id=str(latest.get("service_id") or ""),
                    event="auto_cancel_refund_guard_success",
                    payload={},
                )
                return
            if result.get("reason") == "sms_received":
                return
            await sleep_fn(10)
            continue

        if not deadline_ts:
            await sleep_fn(poll_sec)
            continue

        next_wait = min(poll_sec, max(5, int(cutoff_ts - now_ts))) if cutoff_ts else poll_sec
        await sleep_fn(max(5, next_wait))


async def run_rental_protection_sweep(
    *,
    limit: int = 200,
    alert_threshold_sec: int | None = None,
    list_open_rental_orders_without_sms_fn: Callable[[int], Awaitable[list[dict]]] = list_open_rental_orders_without_sms,
    get_order_fn: Callable[[Any], Awaitable[dict | None]] = get_order,
    sync_rental_sms_snapshot_fn: Callable[[Any, dict], Awaitable[dict[str, Any]]] = sync_rental_sms_snapshot,
    cancel_and_refund_rental_order_fn: Callable[..., Awaitable[dict[str, Any]]] = cancel_and_refund_rental_order,
    sync_rental_protection_snapshot_fn: Callable[[Any, dict], Awaitable[dict[str, Any]]] = sync_rental_protection_snapshot,
    update_order_details_fn: Callable[[Any, dict[str, Any]], Awaitable[Any]] = update_order_details,
    log_number_event_from_order_fn: Callable[..., Awaitable[Any]] = _log_number_event_from_order,
    log_rental_event_fn: Callable[..., Awaitable[Any]] = _log_rental_event,
    no_sms_yet_fn: Callable[[dict | None], bool] = _rental_no_sms_yet,
    safe_cutoff_at_fn: Callable[[dict | None], datetime | None] = rental_safe_cutoff_at,
    deadline_at_fn: Callable[[dict | None], datetime | None] = rental_deadline_at,
    close_failed_alert_text_fn: Callable[[Any, str, Any, str], str] = _default_close_failed_alert_text,
    near_cutoff_alert_text_fn: Callable[[Any, str, Any, str, int], str] = _default_near_cutoff_alert_text,
    utc_now_fn: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    threshold_sec = max(
        60,
        int(
            alert_threshold_sec
            or getattr(settings, "numbers_rental_owner_alert_window_sec", RENTAL_OWNER_ALERT_WINDOW_SEC)
            or RENTAL_OWNER_ALERT_WINDOW_SEC
        ),
    )
    orders = await list_open_rental_orders_without_sms_fn(int(limit))
    stats = {
        "checked": 0,
        "synced_sms": 0,
        "auto_cancelled": 0,
        "close_failures": 0,
        "alerts": [],
    }
    now_dt = utc_now_fn()
    for order in orders:
        stats["checked"] += 1
        order_id = order.get("_id")
        if not order_id or not no_sms_yet_fn(order):
            continue

        sms_snapshot = await sync_rental_sms_snapshot_fn(order_id, order)
        if sms_snapshot.get("has_sms"):
            stats["synced_sms"] += 1
            continue

        latest = await get_order_fn(order_id)
        if not latest or not no_sms_yet_fn(latest):
            continue

        provider_code = str(latest.get("provider") or "").strip().lower()
        if provider_code in {"textverified", "smspool"}:
            await sync_rental_protection_snapshot_fn(order_id, latest)
            latest = await get_order_fn(order_id) or latest

        cutoff_at = safe_cutoff_at_fn(latest)
        deadline_at = deadline_at_fn(latest)
        provider_code = str(latest.get("provider") or "").strip().lower()
        provider_label = provider_public_id(provider_code)

        if cutoff_at and now_dt >= cutoff_at:
            await log_number_event_from_order_fn(
                latest,
                "deadline_reached",
                payload={"source": "rental_global_sweep"},
                number_mode="rental",
            )
            result = await cancel_and_refund_rental_order_fn(
                order_id=order_id,
                order=latest,
                actor_user_id=int(latest.get("user_id") or 0),
                reason=f"{provider_code}_global_guard_no_sms_timeout",
                require_no_sms=True,
            )
            if result.get("success"):
                stats["auto_cancelled"] += 1
                await log_number_event_from_order_fn(
                    latest,
                    "auto_protection_triggered",
                    payload={"source": "rental_global_sweep"},
                    status_after="cancelled",
                    number_mode="rental",
                )
                await log_rental_event_fn(
                    order_id=order_id,
                    user_id=int(latest.get("user_id") or 0),
                    provider=provider_code,
                    service_id=str(latest.get("service_id") or ""),
                    event="auto_cancel_refund_global_guard_success",
                    payload={},
                )
                continue
            if result.get("reason") == "sms_received":
                continue
            stats["close_failures"] += 1
            close_fail_alert_sent_at = _to_utc_datetime(latest.get("rental_close_failure_alert_sent_at"))
            if close_fail_alert_sent_at is None:
                alert_text = close_failed_alert_text_fn(
                    order_id=order_id,
                    provider_label=provider_label,
                    user_id=latest.get("user_id"),
                    reason=str(result.get("reason") or "provider_close_failed"),
                )
                stats["alerts"].append({"kind": "close_failed", "order_id": str(order_id), "text": alert_text})
                with suppress(Exception):
                    await update_order_details_fn(order_id, {"rental_close_failure_alert_sent_at": now_dt})
            continue

        if deadline_at:
            seconds_left = _seconds_left_until(deadline_at)
            alert_sent_at = _to_utc_datetime(latest.get("rental_cutoff_alert_sent_at"))
            if 0 < seconds_left <= threshold_sec and alert_sent_at is None:
                cutoff_txt = deadline_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                alert_text = near_cutoff_alert_text_fn(
                    order_id=order_id,
                    provider_label=provider_label,
                    user_id=latest.get("user_id"),
                    deadline=cutoff_txt,
                    seconds_left=seconds_left,
                )
                stats["alerts"].append({"kind": "near_cutoff", "order_id": str(order_id), "text": alert_text})
                with suppress(Exception):
                    await update_order_details_fn(order_id, {"rental_cutoff_alert_sent_at": now_dt})

    return stats


def schedule_rental_refund_guard(
    *,
    order_id: Any,
    actor_user_id: int,
    guard_fn: Callable[..., Awaitable[None]] = rental_refund_guard,
    logger_obj: logging.Logger = logger,
) -> bool:
    if not order_id:
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False

    task = loop.create_task(guard_fn(order_id=order_id, actor_user_id=int(actor_user_id)))

    def _consume_result(done_task: asyncio.Task) -> None:
        with suppress(asyncio.CancelledError):
            exc = done_task.exception()
            if exc is not None:
                logger_obj.error(
                    "rental refund guard failed: order=%s",
                    order_id,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

    task.add_done_callback(_consume_result)
    return True
