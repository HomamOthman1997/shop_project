from __future__ import annotations

from typing import Any, Awaitable, Callable

from .temp_order import _utc_now
from .temp_refund import order_provider_code, order_provider_order_id


async def request_second_code_for_order(
    *,
    order_id: Any,
    order: dict[str, Any],
    user_id: int,
    reseller_id: int,
    providers: dict[str, Any],
    provider_resend_fn: Callable[[dict[str, Any], str, str], Awaitable[dict[str, Any]]],
    financial_manager: Any,
    create_order_fn: Callable[..., Awaitable[dict[str, Any]]],
    update_order_details_fn: Callable[[Any, dict[str, Any]], Awaitable[Any]],
    update_order_status_fn: Callable[[Any, str], Awaitable[Any]],
    get_order_fn: Callable[[Any], Awaitable[dict[str, Any] | None]],
    log_temp_event_fn: Callable[..., Awaitable[Any]],
    temp_resend_available_fn: Callable[[dict[str, Any]], bool],
    second_code_price_fn: Callable[[dict[str, Any]], tuple[float, float]],
    second_code_log_payload_fn: Callable[..., dict[str, Any]],
    source: str,
    telegram_bot_id: int | None = None,
    refresh_order_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    charge_order_fn: Callable[..., Awaitable[None]] | None = None,
) -> dict[str, Any]:
    if str((order or {}).get("number_mode") or "").strip().lower() != "temp":
        return {"ok": False, "code": "invalid_mode"}

    now = _utc_now()
    provider = order_provider_code(order)
    provider_order_id = order_provider_order_id(order)
    if not provider or not provider_order_id:
        return {"ok": False, "code": "order_not_found"}
    if not temp_resend_available_fn(order):
        await log_temp_event_fn(
            order,
            "second_code_not_allowed",
            second_code_log_payload_fn(order, now=now, extra={"reason": "retention_expired_or_invalid_order"}),
        )
        return {"ok": False, "code": "second_code_unavailable"}

    await log_temp_event_fn(order, "second_code_attempted", second_code_log_payload_fn(order, now=now))
    resend_result = await provider_resend_fn(providers, provider, provider_order_id)
    if not bool((resend_result or {}).get("success")):
        await log_temp_event_fn(
            order,
            "second_code_provider_rejected",
            second_code_log_payload_fn(
                order,
                now=now,
                extra={
                    "provider_error": str((resend_result or {}).get("raw") or ""),
                    "provider_response_status": str((resend_result or {}).get("status") or ""),
                },
            ),
        )
        return {"ok": False, "code": "second_code_provider_failed", "provider_response": resend_result}

    new_provider_order_id = str((resend_result or {}).get("order_id") or provider_order_id).strip() or provider_order_id
    new_provider_number = str((resend_result or {}).get("number") or order.get("provider_number") or "").strip()
    await log_temp_event_fn(
        order,
        "second_code_provider_success",
        second_code_log_payload_fn(
            order,
            now=now,
            extra={
                "new_provider_order_id": new_provider_order_id,
                "number_changed": bool(new_provider_number and new_provider_number != str(order.get("provider_number") or "")),
            },
        ),
    )

    extra_sale, extra_cost = second_code_price_fn(order)
    if extra_sale <= 0:
        await log_temp_event_fn(
            order,
            "second_code_not_allowed",
            second_code_log_payload_fn(order, now=now, extra={"reason": "missing_extra_price"}),
        )
        return {"ok": False, "code": "second_code_unavailable"}

    second_order = await create_order_fn(
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        service_id=f"{str(order.get('service_id') or order.get('temp_service_key') or 'temp')}:second_code",
        selling_price=extra_sale,
        base_price=extra_cost,
    )
    details = {
        "number_mode": "second_code_charge",
        "provisioning_state": "awaiting_charge",
        "provisioning_created_at": now,
        "temp_second_code_source_order_id": str(order_id),
        "source_order_id": str(order_id),
    }
    if source:
        details["source"] = source
    if telegram_bot_id is not None:
        details["telegram_bot_id"] = int(telegram_bot_id)
    await update_order_details_fn(second_order["_id"], details)

    finance_error: str | None = None
    if charge_order_fn is not None:
        try:
            await charge_order_fn(
                order={**second_order, "number_mode": "second_code_charge", "source_order_id": str(order_id)},
                order_id=second_order["_id"],
                user_id=int(user_id),
                reseller_id=int(reseller_id),
                final_price=extra_sale,
                cost_price=extra_cost,
                number_mode="second_code_charge",
                source=source,
            )
        except Exception as exc:
            finance_error = str(getattr(exc, "code", "") or getattr(exc, "public_message", "") or exc)
    else:
        ok, msg = await financial_manager.process_core_purchase(
            user_id=int(user_id),
            order_id=second_order["_id"],
            sale_price=extra_sale,
            cost_price=extra_cost,
            reseller_id=int(reseller_id),
        )
        if not ok:
            await update_order_status_fn(second_order["_id"], "failed")
            finance_error = str(msg)

    if finance_error:
        await log_temp_event_fn(
            order,
            "second_code_charge_failed",
            second_code_log_payload_fn(
                order,
                now=now,
                extra={"extra_sale": extra_sale, "extra_cost": extra_cost, "finance_error": finance_error},
            ),
        )
        return {"ok": False, "code": "finance_error", "finance_message": finance_error, "second_order_id": str(second_order["_id"])}

    charged_at = _utc_now()
    await update_order_status_fn(second_order["_id"], "success")
    await update_order_details_fn(
        second_order["_id"],
        {
            "provisioning_state": "provisioned",
            "provisioning_charged_at": charged_at,
            "provisioned_at": charged_at,
        },
    )
    await update_order_details_fn(
        order_id,
        {
            "temp_second_code_last_at": now,
            "temp_second_code_count": int(order.get("temp_second_code_count") or 0) + 1,
            "provider_order_id": new_provider_order_id,
            "provider_number": new_provider_number or str(order.get("provider_number") or ""),
            "temp_wait_state": "waiting",
            "temp_wait_started_at": now,
            "temp_last_refresh_at": None,
        },
    )
    await log_temp_event_fn(
        order,
        "second_code_requested",
        second_code_log_payload_fn(
            order,
            now=now,
            extra={
                "extra_sale": extra_sale,
                "extra_cost": extra_cost,
                "new_provider_order_id": new_provider_order_id,
                "second_order_id": str(second_order["_id"]),
            },
        ),
    )

    refreshed = await get_order_fn(order_id) or order
    if refresh_order_fn is not None:
        refreshed = await refresh_order_fn(refreshed)
    return {
        "ok": True,
        "order": refreshed,
        "extra_sale": extra_sale,
        "extra_cost": extra_cost,
        "provider": provider,
        "new_provider_order_id": new_provider_order_id,
        "new_provider_number": new_provider_number,
        "second_order_id": str(second_order["_id"]),
    }
