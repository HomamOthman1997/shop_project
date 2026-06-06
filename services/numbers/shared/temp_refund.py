from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from database.orders_repo import extract_order_amounts

from .provider_io import normalize_provider_sms_result
from .temp_order import (
    _extract_new_sms_code,
    _is_retryable_provider_cancel,
    _safe_code_text,
    _seconds_between,
    _temp_order_has_received_code,
    _utc_now,
)


_PROVIDER_TERMINAL_REFUND_MARKERS = (
    "status_cancel",
    "access_cancel",
    "already refunded",
    "already_refunded",
    "refunded",
    "already cancelled",
    "already canceled",
    "already_cancelled",
    "already_canceled",
    "cancelled",
    "canceled",
)
_PROVIDER_TERMINAL_MISSING_MARKERS = (
    "provider_terminal_no_sms",
    "no_activation",
    "no activation",
    "activation not found",
    "request not found",
    "order not found",
    "not_found",
    "not found",
    "does not exist",
    "doesn't exist",
    "not exist",
    "invalid activation",
    "invalid order",
    "invalid id",
    "expired",
    "time out",
    "timed out",
    "deleted",
    "removed",
)
_PROVIDER_ACTIVE_WAIT_MARKERS = (
    "status_wait",
    "wait_sms",
    "waiting",
    "awaiting",
    "pending",
    "reserved",
    "no sms",
    "no_sms",
)
_PROVIDER_BLOCKING_FAILURE_MARKERS = (
    "auth_failed",
    "missing_api_key",
    "api key",
    "bad_key",
    "bad key",
    "unauthorized",
    "forbidden",
    "rate limit",
    "429",
    "timeout",
    "timed out",
    "request_error",
    "request failed",
    "connection",
    "network",
    "temporarily",
    "try again later",
    "server error",
    "internal server error",
)


def order_provider_code(order: dict[str, Any] | None) -> str:
    order = order or {}
    return str(order.get("provider") or order.get("provisioning_provider") or "").strip().lower()


def order_provider_order_id(order: dict[str, Any] | None) -> str:
    order = order or {}
    return str(
        order.get("provider_order_id")
        or order.get("provisioning_provider_order_id")
        or order.get("activation_id")
        or ""
    ).strip()


def provider_raw_is_empty(raw: Any) -> bool:
    if raw is None:
        return True
    if isinstance(raw, str):
        return not raw.strip()
    if isinstance(raw, (list, tuple, set, dict)):
        return len(raw) == 0
    return False


def provider_status_text(raw: Any) -> str:
    if raw is None:
        return ""
    try:
        if isinstance(raw, (dict, list, tuple, set)):
            return json.dumps(raw, ensure_ascii=False, default=str).lower()
    except Exception:
        pass
    return str(raw).lower()


def provider_terminal_refund_reason(
    raw: Any,
    *,
    allow_missing: bool = False,
    allow_empty: bool = False,
) -> str:
    if allow_empty and provider_raw_is_empty(raw):
        return "provider_empty_response"
    text = provider_status_text(raw)
    if not text:
        return ""
    if any(marker in text for marker in _PROVIDER_ACTIVE_WAIT_MARKERS):
        return ""
    if any(marker in text for marker in _PROVIDER_TERMINAL_REFUND_MARKERS):
        return "provider_already_refunded"
    if allow_missing and any(marker in text for marker in _PROVIDER_TERMINAL_MISSING_MARKERS):
        return "provider_missing_or_expired"
    return ""


def provider_failure_should_retry(raw: Any) -> bool:
    if _is_retryable_provider_cancel(raw):
        return True
    text = provider_status_text(raw)
    return bool(text and any(marker in text for marker in _PROVIDER_BLOCKING_FAILURE_MARKERS))


def temp_refund_result_retryable(result: dict[str, Any]) -> bool:
    reason = str((result or {}).get("reason") or "").strip().lower()
    if reason == "financial_refund_failed":
        return True
    return reason == "provider_cancel_failed" and bool((result or {}).get("retryable"))


async def finalize_temp_local_refund(
    *,
    order_id: Any,
    order: dict[str, Any],
    actor_user_id: int,
    reason: str,
    financial_manager: Any,
    update_order_status_fn: Callable[[Any, str], Awaitable[Any]],
    update_order_details_fn: Callable[[Any, dict[str, Any]], Awaitable[Any]],
    log_temp_event_fn: Callable[..., Awaitable[Any]],
    log_number_event_from_order_fn: Callable[..., Awaitable[Any]],
    provider_raw: Any = None,
    provider_terminal_reason: str = "",
    source: str = "",
    status_after: str = "cancelled",
    extra_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    number_mode = "voice" if str(order.get("number_mode") or "").strip().lower() == "voice" else "temp"
    sale_price, cost_price = extract_order_amounts(order)
    ok, msg = await financial_manager.refund_core_purchase(
        int(actor_user_id),
        order_id,
        sale_price,
        cost_price,
        reseller_id=int(order.get("reseller_id") or actor_user_id),
    )
    event_source_payload = {"source": source} if source else {}
    if not ok:
        await log_number_event_from_order_fn(
            order,
            "refund_failed",
            payload={
                "raw": msg,
                "reason": str(reason or "cancelled"),
                "provider_terminal_reason": str(provider_terminal_reason or ""),
                **event_source_payload,
            },
            number_mode=number_mode,
        )
        return {"success": False, "reason": "financial_refund_failed", "raw": msg}

    now = _utc_now()
    patch: dict[str, Any] = {
        "temp_cancelled_at": now,
        "temp_refunded_at": now,
        "temp_cancel_reason": str(reason or "cancelled"),
        "temp_wait_state": "refunded",
    }
    if provider_terminal_reason:
        patch["temp_provider_terminal_reason"] = str(provider_terminal_reason)
        patch["temp_provider_terminal_at"] = now
    if extra_patch:
        patch.update(extra_patch)
    await update_order_status_fn(order_id, status_after)
    await update_order_details_fn(order_id, patch)
    await log_temp_event_fn(
        order,
        "cancelled_refunded",
        {
            "sale_price": sale_price,
            "cost_price": cost_price,
            "reason": str(reason or "cancelled"),
            "provider_terminal_reason": str(provider_terminal_reason or ""),
            "provider_raw": provider_raw,
            **event_source_payload,
        },
    )
    await log_number_event_from_order_fn(
        order,
        "refund_success",
        payload={
            "reason": str(reason or "cancelled"),
            "provider_terminal_reason": str(provider_terminal_reason or ""),
            **event_source_payload,
        },
        status_after=status_after,
        number_mode=number_mode,
    )
    return {"success": True, "reason": "ok"}


async def cancel_and_refund_temp_order(
    *,
    order_id: Any,
    order: dict[str, Any],
    actor_user_id: int,
    reason: str,
    providers: dict[str, Any],
    financial_manager: Any,
    update_order_status_fn: Callable[[Any, str], Awaitable[Any]],
    update_order_details_fn: Callable[[Any, dict[str, Any]], Awaitable[Any]],
    log_temp_event_fn: Callable[..., Awaitable[Any]],
    log_number_event_from_order_fn: Callable[..., Awaitable[Any]],
    require_no_sms: bool = True,
    allow_provider_terminal_refund: bool = False,
    allow_empty_provider_refund: bool = False,
    source: str = "",
    final_status: str = "cancelled",
    extra_refund_patch: dict[str, Any] | None = None,
    sleep_fn: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> dict[str, Any]:
    if not order_id or not order:
        return {"success": False, "reason": "order_not_found"}

    status = str(order.get("status") or "").lower()
    if status in {"cancelled", "failed", "refunded", "expired"}:
        return {"success": False, "reason": "already_closed"}
    if order.get("temp_refunded_at") or order.get("temp_cancelled_at"):
        return {"success": False, "reason": "already_closed"}

    number_mode = "voice" if str(order.get("number_mode") or "").strip().lower() == "voice" else "temp"
    if require_no_sms and number_mode == "voice":
        if order.get("voice_recording_uri") or str(order.get("temp_wait_state") or "").strip().lower() == "call_received":
            return {"success": False, "reason": "call_received"}
    if require_no_sms and _temp_order_has_received_code(order):
        return {"success": False, "reason": "sms_received"}

    provider = order_provider_code(order)
    provider_order_id = order_provider_order_id(order)
    if not provider or not provider_order_id:
        return {"success": False, "reason": "provider_order_missing"}

    prov = providers.get(provider)
    if not prov or not hasattr(prov, "cancel"):
        return {"success": False, "reason": "provider_cancel_not_supported"}

    if require_no_sms and hasattr(prov, "get_sms"):
        try:
            sms_data = normalize_provider_sms_result(await asyncio.wait_for(prov.get_sms(provider_order_id), timeout=12.0))
        except Exception:
            sms_data = {"success": False, "messages": []}
        existing_codes = [str(code) for code in (order.get("temp_codes") or []) if str(code or "").strip()]
        code = _extract_new_sms_code(sms_data.get("messages") or [], set(existing_codes))
        if code:
            clean_code = _safe_code_text(code)
            now = _utc_now()
            patch: dict[str, Any] = {
                "temp_wait_state": "code_received",
                "temp_last_sms_at": now,
                "temp_last_code": clean_code,
                "temp_codes": [*existing_codes, clean_code],
                "temp_codes_count": len(existing_codes) + 1,
                "temp_last_refresh_at": now,
                "temp_last_refresh_mode": "provider_guard_before_cancel",
            }
            if not order.get("temp_first_sms_at"):
                patch["temp_first_sms_at"] = now
                seconds_to_first_sms = _seconds_between(now, order.get("created_at"))
                if seconds_to_first_sms is not None:
                    patch["temp_seconds_to_first_sms"] = seconds_to_first_sms
            await update_order_details_fn(order_id, patch)
            await log_temp_event_fn(
                order,
                "code_received_recovery",
                {"code_len": len(clean_code), "source": "provider_guard_before_cancel"},
            )
            return {"success": False, "reason": "sms_received", "provider_sms_recovered": True}

    event_source_payload = {"source": source} if source else {}
    await log_number_event_from_order_fn(
        order,
        "cancel_requested",
        payload={"reason": str(reason or "cancelled"), **event_source_payload},
        number_mode=number_mode,
    )

    cancel_res: dict[str, Any] = {"success": False, "raw": "cancel_not_attempted"}
    for attempt in range(1, 4):
        try:
            cancel_res = await asyncio.wait_for(prov.cancel(provider_order_id), timeout=12.0)
        except Exception as exc:
            cancel_res = {"success": False, "raw": str(exc)}
        if bool((cancel_res or {}).get("success")):
            break
        if attempt < 3:
            await sleep_fn(float(min(6, attempt * 2)))

    if not bool((cancel_res or {}).get("success")):
        terminal_reason = provider_terminal_refund_reason(
            (cancel_res or {}).get("raw"),
            allow_missing=bool(allow_provider_terminal_refund),
            allow_empty=bool(allow_empty_provider_refund),
        )
        if terminal_reason:
            await log_number_event_from_order_fn(
                order,
                "provider_already_closed",
                payload={
                    "raw": (cancel_res or {}).get("raw"),
                    "reason": str(reason or "cancelled"),
                    "provider_terminal_reason": terminal_reason,
                    **event_source_payload,
                },
                number_mode=number_mode,
            )
            return await finalize_temp_local_refund(
                order_id=order_id,
                order=order,
                actor_user_id=actor_user_id,
                reason=reason,
                financial_manager=financial_manager,
                update_order_status_fn=update_order_status_fn,
                update_order_details_fn=update_order_details_fn,
                log_temp_event_fn=log_temp_event_fn,
                log_number_event_from_order_fn=log_number_event_from_order_fn,
                provider_raw=(cancel_res or {}).get("raw"),
                provider_terminal_reason=terminal_reason,
                source=source,
                status_after=final_status,
                extra_patch=extra_refund_patch,
            )
        await log_number_event_from_order_fn(
            order,
            "provider_cancel_failed",
            payload={"raw": (cancel_res or {}).get("raw"), "reason": str(reason or "cancelled"), **event_source_payload},
            number_mode=number_mode,
        )
        return {
            "success": False,
            "reason": "provider_cancel_failed",
            "raw": (cancel_res or {}).get("raw"),
            "retryable": bool((cancel_res or {}).get("retryable")) or provider_failure_should_retry((cancel_res or {}).get("raw")),
        }

    return await finalize_temp_local_refund(
        order_id=order_id,
        order=order,
        actor_user_id=actor_user_id,
        reason=reason,
        financial_manager=financial_manager,
        update_order_status_fn=update_order_status_fn,
        update_order_details_fn=update_order_details_fn,
        log_temp_event_fn=log_temp_event_fn,
        log_number_event_from_order_fn=log_number_event_from_order_fn,
        provider_raw=(cancel_res or {}).get("raw"),
        provider_terminal_reason="provider_cancel_success",
        source=source,
        status_after=final_status,
        extra_patch=extra_refund_patch,
    )
