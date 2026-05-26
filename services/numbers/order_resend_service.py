from __future__ import annotations

from datetime import datetime
from typing import Any

from database.orders_repo import create_order, extract_order_amounts, get_order, update_order_details, update_order_status
from services.numbers.manager import PROVIDERS
from services.numbers.order_charge_service import charge_order_or_raise
from services.numbers.order_refresh_service import refresh_number_order
from services.numbers.order_service import NumbersOrderError, public_order_payload
from services.numbers.shared.events import _log_temp_event
from services.numbers.shared.provider_io import provider_resend
from services.numbers.shared.temp_order import _coerce_utc_datetime, _order_reuse_warranty_sec, _seconds_between, _seconds_left_until
from services.numbers.shared.temp_refund import order_provider_code, order_provider_order_id
from services.numbers.shared.temp_second_code import request_second_code_for_order
from services.platform.webhooks import enqueue_event_for_user
from utils.financial_manager import FinancialManager


def _temp_resend_available(order: dict[str, Any]) -> bool:
    if str((order or {}).get("number_mode") or "").strip().lower() != "temp":
        return False
    if str((order or {}).get("status") or "").strip().lower() != "success":
        return False
    if str((order or {}).get("provisioning_state") or "").strip().lower() != "provisioned":
        return False
    if not str((order or {}).get("provider_order_id") or "").strip():
        return False
    number = str((order or {}).get("provider_number") or "").strip()
    if not number or number == "?":
        return False
    reuse_until = _coerce_utc_datetime((order or {}).get("temp_reuse_warranty_until"))
    return True if not reuse_until else _seconds_left_until(reuse_until) > 0


def _second_code_price(order: dict[str, Any]) -> tuple[float, float]:
    sale_price, cost_price = extract_order_amounts(order)
    return round(max(0.0, float(sale_price)) / 2.0, 4), round(max(0.0, float(cost_price)) / 2.0, 4)


def _second_code_log_payload(order: dict[str, Any], *, now: datetime, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": order_provider_code(order),
        "provider_order_id": order_provider_order_id(order),
        "seconds_since_purchase": _seconds_between(now, order.get("created_at")),
        "seconds_since_first_code": _seconds_between(now, order.get("temp_first_sms_at")),
        "seconds_since_last_sms": _seconds_between(now, order.get("temp_last_sms_at")),
        "seconds_since_previous_second_code": _seconds_between(now, order.get("temp_second_code_last_at")),
        "resend_retention_expires_at": (
            _coerce_utc_datetime(order.get("temp_reuse_warranty_until")).isoformat()
            if _coerce_utc_datetime(order.get("temp_reuse_warranty_until"))
            else None
        ),
        "resend_guarantee_seconds": _order_reuse_warranty_sec(order),
        "codes_count_before": int(order.get("temp_codes_count") or len(order.get("temp_codes") or []) or 0),
        "source": "numbers_api",
    }
    if extra:
        payload.update(extra)
    return payload


async def request_number_order_resend(
    order: dict[str, Any],
    *,
    user_id: int,
    reseller_id: int,
) -> dict[str, Any]:
    if not isinstance(order, dict) or not order.get("_id"):
        raise NumbersOrderError("order_not_found", "Order was not found.", status=404)
    if str(order.get("number_mode") or "temp").strip().lower() != "temp":
        raise NumbersOrderError("unsupported_order_mode", "This order mode does not support resend.", status=409)

    result = await request_second_code_for_order(
        order_id=order["_id"],
        order=order,
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        providers=PROVIDERS,
        provider_resend_fn=provider_resend,
        financial_manager=FinancialManager,
        create_order_fn=create_order,
        update_order_details_fn=update_order_details,
        update_order_status_fn=update_order_status,
        get_order_fn=get_order,
        log_temp_event_fn=_log_temp_event,
        temp_resend_available_fn=_temp_resend_available,
        second_code_price_fn=_second_code_price,
        second_code_log_payload_fn=_second_code_log_payload,
        source="numbers_api",
        telegram_bot_id=None,
        refresh_order_fn=lambda item: _refresh_after_resend(item),
        charge_order_fn=lambda **kwargs: charge_order_or_raise(lang="en", **kwargs),
    )
    if not result.get("ok"):
        code = str(result.get("code") or "resend_failed")
        status = 402 if code == "finance_error" else 409
        if code in {"order_not_found", "invalid_mode"}:
            status = 404 if code == "order_not_found" else 400
        raise NumbersOrderError(code, _resend_error_message(code), status=status)

    refreshed = result.get("order") if isinstance(result.get("order"), dict) else await get_order(order["_id"]) or order
    payload = {
        "ok": True,
        "message": "Resend was requested. Waiting for the provider webhook.",
        "order": public_order_payload(refreshed),
        "second_order_id": str(result.get("second_order_id") or ""),
    }
    await enqueue_event_for_user(
        user_id=int(refreshed.get("user_id") or user_id),
        reseller_id=int(refreshed.get("reseller_id") or reseller_id or user_id),
        event_type="numbers.order.resend_requested",
        data={"order": payload["order"], "second_order_id": payload["second_order_id"]},
    )
    return payload


async def _refresh_after_resend(order: dict[str, Any]) -> dict[str, Any]:
    await refresh_number_order(order)
    return await get_order(order.get("_id")) or order


def _resend_error_message(code: str) -> str:
    if code == "finance_error":
        return "Could not charge the resend request."
    if code == "second_code_provider_failed":
        return "Provider could not request another SMS right now."
    if code == "second_code_unavailable":
        return "Resend is not available for this order."
    return "Could not request resend for this order."
