from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database.orders_repo import update_order_details, update_order_status
from services.numbers.manager import buy_number_from_provider, rent_number_from_provider
from services.numbers.order_rental_protection_service import rental_protection_policy
from services.numbers.provider_delivery import provider_sms_delivery_strategy
from services.numbers.shared.events import _log_number_event_from_order, _log_rental_event, _log_temp_event
from services.numbers.shared.temp_order import (
    _coerce_utc_datetime,
    _extract_provider_wait_timeout_sec,
    _poll_interval_for_provider,
    _provider_temp_wait_timeout_sec,
    _resolve_reuse_warranty_sec,
    _utc_now,
)
from utils.financial_manager import FinancialManager


class ProviderProvisioningError(Exception):
    def __init__(self, message: str, *, refund_ok: bool = False, raw: Any = None) -> None:
        super().__init__(message)
        self.refund_ok = refund_ok
        self.raw = raw


async def provision_charged_temp_order(
    *,
    order: dict[str, Any],
    order_id: Any,
    user_id: int,
    reseller_id: int,
    provider_code: str,
    api_service: str,
    country: str | None,
    state: str | None,
    service_name: str,
    final_price: float,
    cost_price: float,
    number_mode: str = "temp",
    source: str = "numbers_api",
    telegram_wait: dict[str, Any] | None = None,
    purchase_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await update_order_details(
        order_id,
        {
            "provisioning_state": "charged_pending_provider",
            "provisioning_charged_at": _utc_now(),
        },
    )
    await _log_number_event_from_order(order, "wallet_charged", status_after="paid", number_mode=number_mode)

    options = {
        "reuse_mode": True,
        "_audit_requested_service": str((purchase_options or {}).get("_audit_requested_service") or service_name or ""),
        "source": source,
    }
    options.update({k: v for k, v in (purchase_options or {}).items() if v is not None})
    if number_mode == "voice":
        options["capability"] = "voice"

    await _log_number_event_from_order(
        {**order, "provider": provider_code, "status": "paid"},
        "provider_buy_started",
        payload={"api_service": str(api_service), "source": source},
        status_after="paid",
        number_mode=number_mode,
    )

    buy_res = await buy_number_from_provider(
        provider_code=provider_code,
        api_service_name=api_service,
        country=None if country in (None, "none") else country,
        state=None if state in (None, "none") else state,
        dry_run=False,
        purchase_options=options,
    )
    if not buy_res or not buy_res.get("success"):
        refund_ok, _refund_msg = await FinancialManager.refund_core_purchase(
            int(user_id),
            order_id,
            final_price,
            cost_price,
            reseller_id=int(reseller_id),
        )
        await update_order_status(order_id, "refunded" if refund_ok else "failed")
        await update_order_details(
            order_id,
            {
                "provisioning_state": "provider_failed_refunded" if refund_ok else "provider_failed_refund_error",
                "provisioning_failure_at": _utc_now(),
            },
        )
        raw = buy_res.get("raw") if buy_res else "provider_no_response"
        await _log_number_event_from_order(
            {**order, "provider": provider_code, "status": "paid"},
            "provider_buy_failed",
            payload={"raw": raw, "source": source},
            status_after="refunded" if refund_ok else "failed",
            number_mode=number_mode,
        )
        await _log_number_event_from_order(
            {**order, "provider": provider_code, "status": "paid"},
            "refund_success" if refund_ok else "refund_failed",
            payload={"source": "provider_buy_failed"},
            status_after="refunded" if refund_ok else "failed",
            number_mode=number_mode,
        )
        if buy_res and isinstance(buy_res, dict) and isinstance(buy_res.get("normalized_error"), dict):
            raw = (buy_res.get("normalized_error") or {}).get("message") or raw
        raise ProviderProvisioningError(str(raw or "provider_error"), refund_ok=bool(refund_ok), raw=raw)

    provider_order_id = buy_res.get("order_id")
    number = buy_res.get("number")
    provider_pool = str(buy_res.get("pool") or "").strip() or None
    interval_sec = _poll_interval_for_provider(str(provider_code))
    provider_timeout_sec = _extract_provider_wait_timeout_sec(buy_res)
    wait_timeout_sec = _provider_temp_wait_timeout_sec(provider_code, provider_timeout_sec)
    now = _utc_now()
    reuse_warranty_sec = _resolve_reuse_warranty_sec(provider_code, buy_res)
    reuse_until = datetime.fromtimestamp(now.timestamp() + int(reuse_warranty_sec), tz=UTC)

    patch = {
        "provider_order_id": provider_order_id,
        "provider": provider_code,
        "provider_sms_delivery": provider_sms_delivery_strategy(provider_code),
        "provider_number": number,
        "provider_pool": provider_pool,
        "number_mode": number_mode,
        "voice_enabled": number_mode == "voice",
        "temp_api_service": str(api_service),
        "temp_country": None if country in (None, "none") else country,
        "temp_state": None if state in (None, "none") else state,
        "temp_service_key": str(service_name),
        "temp_reuse_warranty_until": reuse_until,
        "temp_reuse_warranty_sec": reuse_warranty_sec,
        "temp_wait_interval_sec": interval_sec,
        "temp_wait_timeout_sec": wait_timeout_sec,
        "temp_last_refresh_at": None,
        "temp_replace_enabled": False,
        "temp_codes": [],
        "temp_codes_count": 0,
        "temp_wait_state": "waiting_for_call" if number_mode == "voice" else "waiting",
        "temp_wait_started_at": now,
        "provisioning_state": "provisioned",
        "provisioned_at": now,
    }
    if telegram_wait:
        patch.update(
            {
                "temp_wait_chat_id": telegram_wait.get("chat_id"),
                "temp_wait_message_id": telegram_wait.get("message_id"),
                "temp_wait_bot_id": telegram_wait.get("bot_id"),
            }
        )

    await update_order_details(order_id, patch)
    await update_order_status(order_id, "success")
    await _log_number_event_from_order(
        {
            **order,
            "_id": order_id,
            "provider": provider_code,
            "provider_order_id": provider_order_id,
            "provider_number": number,
            "temp_country": None if country in (None, "none") else country,
            "temp_state": None if state in (None, "none") else state,
            "status": "paid",
        },
        "provider_buy_success",
        payload={"provider_pool": provider_pool, "source": source},
        status_after="success",
        number_mode=number_mode,
    )
    await _log_temp_event(
        {
            "_id": order_id,
            "user_id": int(user_id),
            "provider": provider_code,
            "service_id": service_name,
        },
        "purchase_success",
        {
            "resend_enabled": True,
            "sale_price": final_price,
            "base_price": cost_price,
            "provider_order_id": str(provider_order_id),
            "provider_pool": provider_pool,
            "source": source,
        },
    )
    return {
        "order_id": order_id,
        "provider_order_id": provider_order_id,
        "number": number,
        "provider_pool": provider_pool,
        "interval_sec": interval_sec,
        "provider_timeout_sec": wait_timeout_sec,
        "reuse_warranty_sec": reuse_warranty_sec,
        "raw": buy_res,
    }


async def provision_charged_rental_order(
    *,
    order: dict[str, Any],
    order_id: Any,
    user_id: int,
    reseller_id: int,
    provider_code: str,
    api_service: str,
    country: str,
    service_name: str,
    duration: int,
    duration_label: str,
    country_name: str,
    final_price: float,
    cost_price: float,
    option_meta: dict[str, Any] | None = None,
    is_renewable: bool = False,
    billing_cycle_label: str = "-",
    telegram_bot_id: int | None = None,
    source: str = "numbers_api",
) -> dict[str, Any]:
    await update_order_details(
        order_id,
        {
            "provisioning_state": "charged_pending_provider",
            "provisioning_charged_at": _utc_now(),
        },
    )
    await _log_number_event_from_order(order, "wallet_charged", status_after="paid", number_mode="rental")
    await _log_number_event_from_order(
        {**order, "provider": provider_code, "status": "paid"},
        "provider_rent_started",
        payload={"api_service": str(api_service), "duration_hours": int(duration), "source": source},
        status_after="paid",
        number_mode="rental",
    )

    rent_res = await rent_number_from_provider(
        provider_code=provider_code,
        api_service_name=str(api_service),
        country=country,
        duration=duration,
        option_meta=option_meta or {},
    )
    if not rent_res or not rent_res.get("success"):
        refund_ok, _refund_msg = await FinancialManager.refund_core_purchase(
            int(user_id),
            order_id,
            final_price,
            cost_price,
            reseller_id=int(reseller_id),
        )
        await update_order_status(order_id, "refunded" if refund_ok else "failed")
        await update_order_details(
            order_id,
            {
                "provisioning_state": "provider_failed_refunded" if refund_ok else "provider_failed_refund_error",
                "provisioning_failure_at": _utc_now(),
            },
        )
        raw = rent_res.get("raw") if rent_res else "provider_no_response"
        await _log_number_event_from_order(
            {**order, "provider": provider_code, "status": "paid"},
            "provider_rent_failed",
            payload={"raw": raw, "source": source},
            status_after="refunded" if refund_ok else "failed",
            number_mode="rental",
        )
        await _log_number_event_from_order(
            {**order, "provider": provider_code, "status": "paid"},
            "refund_success" if refund_ok else "refund_failed",
            payload={"source": "provider_rent_failed"},
            status_after="refunded" if refund_ok else "failed",
            number_mode="rental",
        )
        raise ProviderProvisioningError(str(raw or "provider_error"), refund_ok=bool(refund_ok), raw=raw)

    provider_order_id = str(rent_res.get("order_id"))
    number = str(rent_res.get("number"))
    policy = rental_protection_policy(provider_code)
    rental_started_at = _utc_now()
    rental_deadline_at = None
    rental_safe_cutoff_at = None
    provider_refund_deadline_at = _coerce_utc_datetime(rent_res.get("refund_refundable_until"))
    provider_can_refund = rent_res.get("refund_can_refund")
    if provider_refund_deadline_at and provider_can_refund is not False:
        rental_deadline_at = provider_refund_deadline_at
        rental_safe_cutoff_at = datetime.fromtimestamp(
            rental_deadline_at.timestamp() - max(30, int(policy.get("safe_cutoff_sec") or 60)),
            tz=UTC,
        )
    elif policy.get("refund_deadline_sec"):
        rental_deadline_at = datetime.fromtimestamp(
            rental_started_at.timestamp() + int(policy["refund_deadline_sec"]),
            tz=UTC,
        )
        rental_safe_cutoff_at = datetime.fromtimestamp(
            rental_deadline_at.timestamp() - max(30, int(policy.get("safe_cutoff_sec") or 60)),
            tz=UTC,
        )

    patch = {
        "provider_order_id": provider_order_id,
        "provider": provider_code,
        "provider_sms_delivery": provider_sms_delivery_strategy(provider_code),
        "provider_number": number,
        "number_mode": "rental",
        "rental_started_at": rental_started_at,
        "rental_duration_hours": duration,
        "rental_duration_label": duration_label,
        "rental_country": country,
        "rental_country_name": country_name,
        "rental_cost": rent_res.get("price"),
        "rental_end_date": rent_res.get("end_date"),
        "rental_is_renewable": bool(is_renewable),
        "rental_billing_cycle_label": billing_cycle_label if is_renewable else "-",
        "rental_billing_cycle_id": rent_res.get("billing_cycle_id"),
        "rental_state_code": str((option_meta or {}).get("state_code") or "none"),
        "rental_refund_deadline_at": rental_deadline_at,
        "rental_safe_cutoff_at": rental_safe_cutoff_at,
        "provisioning_state": "provisioned",
        "provisioned_at": _utc_now(),
        "rental_protection_policy": {
            "provider": provider_code,
            "close_method": policy.get("close_method"),
            "refund_deadline_sec": policy.get("refund_deadline_sec"),
            "safe_cutoff_sec": policy.get("safe_cutoff_sec"),
            "provider_can_refund": provider_can_refund,
            "provider_refund_deadline_at": provider_refund_deadline_at,
        },
    }
    if telegram_bot_id is not None:
        patch["telegram_bot_id"] = int(telegram_bot_id)
    await update_order_details(order_id, patch)
    await update_order_status(order_id, "success")
    await _log_number_event_from_order(
        {
            **order,
            "_id": order_id,
            "provider": provider_code,
            "provider_order_id": provider_order_id,
            "provider_number": number,
            "rental_country": country,
            "rental_state_code": str((option_meta or {}).get("state_code") or "none"),
            "status": "paid",
        },
        "provider_rent_success",
        payload={"duration_hours": int(duration), "source": source},
        status_after="success",
        number_mode="rental",
    )
    await _log_rental_event(
        order_id=order_id,
        user_id=int(user_id),
        provider=provider_code,
        service_id=f"{service_name}:rental",
        event="purchase_success",
        payload={"duration_hours": int(duration), "provider_order_id": provider_order_id, "source": source},
    )
    return {
        "order_id": order_id,
        "provider_order_id": provider_order_id,
        "number": number,
        "rental_deadline_at": rental_deadline_at,
        "rental_safe_cutoff_at": rental_safe_cutoff_at,
        "raw": rent_res,
    }
