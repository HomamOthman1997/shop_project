from __future__ import annotations

from datetime import datetime
from typing import Any

from database.mongo import db
from database.orders_repo import create_order, extract_order_amounts, get_order, update_order_details, update_order_status
from services.numbers.api_payloads import (
    QuoteTokenError,
    HIDDEN_TEMP_PROVIDER_CODES,
    RENTAL_QUOTE_PROVIDER_CODES,
    TEMP_QUOTE_PROVIDER_CODES,
    VOICE_GENERIC_SERVICE,
    VOICE_QUOTE_PROVIDER_CODES,
    make_quote_token,
    money_label,
    rental_duration_label,
    rental_option_candidates,
    rental_option_is_buyable,
    rental_option_match_key,
    rental_state_code_for_quote,
    temp_provider_offer_is_buyable,
    verify_quote_token,
    voice_provider_offer_is_buyable,
)
from services.numbers.manager import get_all_prices, get_all_rental_prices, get_all_voice_prices
from services.numbers.order_purchase_service import ProviderProvisioningError, provision_charged_rental_order, provision_charged_temp_order
from services.numbers.order_charge_service import charge_order_or_raise
from services.numbers.order_lifecycle_service import (
    OrderChargeError,
    UnexpectedProvisioningError,
    execute_order_provisioning_transaction,
)
from services.numbers.order_rental_protection_service import schedule_rental_refund_guard
from services.numbers.provider_delivery import provider_sms_delivery_strategy
from services.numbers.provider_readiness import provider_purchase_enabled, provider_readiness
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.shared.events import _log_number_event_from_order, _log_temp_event
from services.numbers.shared.temp_order import (
    TEMP_WAIT_TIMEOUT_SEC,
    _coerce_utc_datetime,
    _seconds_left_until,
    _temp_elapsed_sec,
    _temp_order_has_received_code,
    _utc_now,
)
from services.numbers.shared.temp_replacement import pick_retry_provider, temp_replacement_fields
from services.platform.webhooks import enqueue_event_for_user
from utils.provider_alias import provider_code_from_public_id, provider_display_name, provider_public_id


class NumbersOrderError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def public_order_payload(order: dict[str, Any] | None) -> dict[str, Any]:
    order = order or {}
    order_id = order.get("_id")
    mode = str(order.get("number_mode") or "temp").strip().lower() or "temp"
    public_status = _public_order_status(order)
    sale_price, _cost_price = extract_order_amounts(order)
    seconds_left = max(0, int(_order_timeout_sec(order)) - int(_temp_elapsed_sec(order)))
    can_resend = _order_resend_available(order, public_status=public_status)
    provider_code = str(order.get("provider") or order.get("provisioning_provider") or "").strip().lower()
    provider_id = str(order.get("provider_public_id") or provider_public_id(provider_code))
    sms_delivery = str(order.get("provider_sms_delivery") or provider_sms_delivery_strategy(provider_code))
    code = _order_last_code(order)
    codes = _order_codes(order)
    recording_available = bool(mode == "voice" and str(order.get("voice_recording_uri") or "").strip())
    calls_count = _voice_calls_count(order) if mode == "voice" else 0
    active_rental = _active_rental_order(order, public_status=public_status)
    replace_available = _temp_like_replace_available(order)
    alternate_provider_code = str(order.get("temp_alternate_provider") or "").strip().lower()
    alternate_provider_available = bool(
        mode == "temp"
        and replace_available
        and order.get("temp_alternate_enabled")
        and alternate_provider_code
        and alternate_provider_code != provider_code
    )
    payload = {
        "id": str(order_id or ""),
        "status": str(order.get("status") or ""),
        "public_status": public_status,
        "mode": mode,
        "service": str(order.get("temp_service_key") or order.get("service_id") or "").replace(":rental", ""),
        "country": str(order.get("temp_country") or order.get("rental_country") or "none"),
        "state": str(order.get("temp_state") or order.get("rental_state_code") or "none"),
        "provider_id": provider_id,
        "provider": provider_display_name(provider_code),
        "sms_delivery": sms_delivery,
        "number": str(order.get("provider_number") or ""),
        "selling_price": float(sale_price),
        "wait_state": str(order.get("temp_wait_state") or ""),
        "code": code,
        "codes": codes,
        "messages": _order_messages(order),
        "elapsed_sec": int(_temp_elapsed_sec(order)),
        "timeout_sec": int(_order_timeout_sec(order)),
        "seconds_left": seconds_left,
        "can_refresh": public_status in {"waiting", "code_received", "refund_pending", "waiting_for_recording"},
        "can_resend": can_resend,
        "can_replace": bool(replace_available),
        "can_alternate_provider": bool(alternate_provider_available),
        "alternate_provider_id": provider_public_id(alternate_provider_code) if alternate_provider_available else "",
        "alternate_provider": provider_display_name(alternate_provider_code) if alternate_provider_available else "",
        "alternate_provider_price_label": money_label(order.get("temp_alternate_price")) if alternate_provider_available else "",
        "resend_price": float(round(max(0.0, float(sale_price)) / 2.0, 4)) if can_resend else 0.0,
        "second_code_count": int(order.get("temp_second_code_count") or 0),
        "calls_count": calls_count,
        "recording_available": recording_available,
        "recording_url": f"/api/v1/numbers/orders/{order_id}/recording" if recording_available and order_id else "",
        "duration_label": str(order.get("rental_duration_label") or "") if mode == "rental" else "",
        "end_date": str(order.get("rental_end_date") or "") if mode == "rental" else "",
        "notes": str(order.get("rental_notes") or "") if mode == "rental" else "",
        "tags": [str(item) for item in (order.get("rental_tags") or []) if str(item or "").strip()] if mode == "rental" else [],
        "can_finish": bool(active_rental),
        "can_renew": bool(active_rental and order.get("rental_is_renewable")),
        "can_wake": bool(active_rental),
        "can_notes": bool(active_rental),
        "refund": _refund_payload(order, public_status=public_status),
        "customer_state": _customer_state_payload(
            order,
            public_status=public_status,
            mode=mode,
            sms_delivery=sms_delivery,
            provider_id=provider_id,
            code=code,
            seconds_left=seconds_left,
            can_resend=can_resend,
            can_replace=replace_available,
            can_alternate_provider=alternate_provider_available,
        ),
    }
    payload["api_actions"] = _api_order_actions(payload)
    return payload


def _api_order_action(
    *,
    enabled: bool,
    endpoint: str,
    method: str = "POST",
    scope: str = "",
    reason: str = "",
    requires_idempotency_key: bool = False,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "endpoint": str(endpoint or ""),
        "method": str(method or "POST").upper(),
        "scope": str(scope or ""),
        "reason": "" if enabled else str(reason or ""),
        "requires_idempotency_key": bool(requires_idempotency_key),
    }


def _api_order_actions(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    order_id = str((payload or {}).get("id") or "").strip()
    base = f"/api/v1/numbers/orders/{order_id}" if order_id else ""
    mode = str((payload or {}).get("mode") or "temp").strip().lower() or "temp"
    missing_order_reason = "missing_order_id" if not order_id else ""
    active_rental = mode == "rental" and bool(
        payload.get("can_finish") or payload.get("can_renew") or payload.get("can_wake") or payload.get("can_notes")
    )

    actions = {
        "refresh": _api_order_action(
            enabled=bool(order_id and payload.get("can_refresh")),
            endpoint=f"{base}/refresh" if base else "",
            scope="numbers:orders:refresh",
            reason=missing_order_reason or "not_refreshable",
        ),
        "resend": _api_order_action(
            enabled=bool(order_id and payload.get("can_resend")),
            endpoint=f"{base}/resend" if base else "",
            scope="numbers:orders:resend",
            reason=missing_order_reason or "resend_unavailable",
            requires_idempotency_key=True,
        ),
        "replace": _api_order_action(
            enabled=bool(order_id and payload.get("can_replace")),
            endpoint=f"{base}/replace" if base else "",
            scope="numbers:orders:replace",
            reason=missing_order_reason or "replacement_unavailable",
            requires_idempotency_key=True,
        ),
        "alternate_provider": _api_order_action(
            enabled=bool(order_id and payload.get("can_alternate_provider")),
            endpoint=f"{base}/alternate" if base else "",
            scope="numbers:orders:replace",
            reason=missing_order_reason or "alternate_unavailable",
            requires_idempotency_key=True,
        ),
        "download_recording": _api_order_action(
            enabled=bool(order_id and mode == "voice" and payload.get("recording_available")),
            endpoint=f"{base}/recording" if base else "",
            method="GET",
            scope="numbers:orders:read",
            reason=missing_order_reason or "recording_not_ready",
        ),
        "rental_sms": _api_order_action(
            enabled=bool(order_id and active_rental),
            endpoint=f"{base}/rental/sms" if base else "",
            scope="numbers:orders:rental",
            reason=missing_order_reason or "not_active_rental",
        ),
        "rental_finish": _api_order_action(
            enabled=bool(order_id and mode == "rental" and payload.get("can_finish")),
            endpoint=f"{base}/rental/finish" if base else "",
            scope="numbers:orders:rental",
            reason=missing_order_reason or "finish_unavailable",
        ),
        "rental_renew": _api_order_action(
            enabled=bool(order_id and mode == "rental" and payload.get("can_renew")),
            endpoint=f"{base}/rental/renew" if base else "",
            scope="numbers:orders:rental",
            reason=missing_order_reason or "renew_unavailable",
            requires_idempotency_key=True,
        ),
        "rental_wake": _api_order_action(
            enabled=bool(order_id and mode == "rental" and payload.get("can_wake")),
            endpoint=f"{base}/rental/wake" if base else "",
            scope="numbers:orders:rental",
            reason=missing_order_reason or "wake_unavailable",
        ),
        "rental_notes": _api_order_action(
            enabled=bool(order_id and mode == "rental" and payload.get("can_notes")),
            endpoint=f"{base}/rental/notes" if base else "",
            scope="numbers:orders:rental",
            reason=missing_order_reason or "notes_unavailable",
        ),
    }
    return actions


def _public_order_status(order: dict[str, Any]) -> str:
    status = str(order.get("status") or "").strip().lower()
    wait_state = str(order.get("temp_wait_state") or "").strip().lower()
    mode = str(order.get("number_mode") or "temp").strip().lower()
    if status in {"cancelled", "refunded"} or wait_state in {"refunded", "auto_refunded"}:
        return "refunded"
    if status in {"failed", "expired"}:
        return status
    if wait_state == "refund_pending":
        return "refund_pending"
    if mode == "voice":
        if str(order.get("voice_recording_uri") or "").strip() or wait_state == "call_received":
            return "call_received"
        if wait_state == "waiting_for_recording" or _voice_calls_count(order) > 0:
            return "waiting_for_recording"
    if mode == "rental" and (int(order.get("rental_sms_count") or 0) > 0 or order.get("rental_sms_received_at")):
        return "code_received"
    if _order_has_received_code(order) and not _second_code_waiting(order):
        return "code_received"
    return "waiting"


def _voice_calls_count(order: dict[str, Any]) -> int:
    try:
        return int(order.get("voice_calls_count") or len(order.get("voice_calls") or []) or 0)
    except Exception:
        return 0


def _active_rental_order(order: dict[str, Any], *, public_status: str) -> bool:
    if str(order.get("number_mode") or "temp").strip().lower() != "rental":
        return False
    if str(order.get("status") or "").strip().lower() in {"cancelled", "failed", "refunded", "expired"}:
        return False
    if order.get("rental_finished_at"):
        return False
    if public_status not in {"waiting", "code_received"}:
        return False
    return bool(str(order.get("provider_order_id") or "").strip())


def _temp_like_replace_available(order: dict[str, Any]) -> bool:
    mode = str((order or {}).get("number_mode") or "").strip().lower()
    if mode not in {"temp", "voice"}:
        return False
    status = str((order or {}).get("status") or "").strip().lower()
    wait_state = str((order or {}).get("temp_wait_state") or "").strip().lower()
    closed = status in {"cancelled", "refunded", "failed", "expired"} or wait_state in {"refunded", "auto_refunded"}
    if not closed:
        return False
    if mode == "voice":
        return not bool((order or {}).get("voice_recording_uri") or wait_state == "call_received")
    return not _temp_order_has_received_code(order)


def _order_has_received_code(order: dict[str, Any]) -> bool:
    if str(order.get("number_mode") or "temp").strip().lower() == "rental":
        if str(order.get("rental_last_code") or "").strip():
            return True
        if any(str(code or "").strip() for code in (order.get("rental_codes") or [])):
            return True
        return any(str(message or "").strip() for message in (order.get("rental_sms_messages") or []))
    if str(order.get("temp_last_code") or "").strip():
        return True
    return any(str(code or "").strip() for code in (order.get("temp_codes") or []))


def _order_last_code(order: dict[str, Any]) -> str:
    if str(order.get("number_mode") or "temp").strip().lower() == "rental":
        codes = _order_codes(order)
        return str(order.get("rental_last_code") or (codes[-1] if codes else "") or "")
    return str(order.get("temp_last_code") or "")


def _order_codes(order: dict[str, Any]) -> list[str]:
    if str(order.get("number_mode") or "temp").strip().lower() == "rental":
        codes = [str(code) for code in (order.get("rental_codes") or []) if str(code or "").strip()]
        if codes:
            return codes
        return [str(item) for item in (order.get("rental_sms_messages") or []) if str(item or "").strip()]
    return [str(code) for code in (order.get("temp_codes") or []) if str(code or "").strip()]


def _order_messages(order: dict[str, Any]) -> list[str]:
    if str(order.get("number_mode") or "temp").strip().lower() == "rental":
        return [str(item) for item in (order.get("rental_sms_messages") or []) if str(item or "").strip()]
    text = str(order.get("temp_last_sms_text") or "").strip()
    return [text] if text else []


def _second_code_waiting(order: dict[str, Any]) -> bool:
    if str(order.get("temp_wait_state") or "").strip().lower() != "waiting":
        return False
    second_requested_at = _coerce_utc_datetime(order.get("temp_second_code_last_at"))
    if not second_requested_at:
        return False
    last_sms_at = _coerce_utc_datetime(order.get("temp_last_sms_at"))
    return not last_sms_at or second_requested_at > last_sms_at


def _order_timeout_sec(order: dict[str, Any]) -> int:
    try:
        return max(1, int(order.get("temp_wait_timeout_sec") or TEMP_WAIT_TIMEOUT_SEC))
    except Exception:
        return TEMP_WAIT_TIMEOUT_SEC


def _order_resend_available(order: dict[str, Any], *, public_status: str) -> bool:
    if str(order.get("number_mode") or "temp").strip().lower() != "temp":
        return False
    if public_status != "code_received":
        return False
    if str(order.get("status") or "").strip().lower() != "success":
        return False
    if str(order.get("provisioning_state") or "").strip().lower() != "provisioned":
        return False
    if not str(order.get("provider_order_id") or "").strip():
        return False
    number = str(order.get("provider_number") or "").strip()
    if not number or number == "?":
        return False
    reuse_until = _coerce_utc_datetime(order.get("temp_reuse_warranty_until"))
    return True if not reuse_until else _seconds_left_until(reuse_until) > 0


def _refund_payload(order: dict[str, Any], *, public_status: str) -> dict[str, Any]:
    refunded = public_status == "refunded"
    pending = public_status == "refund_pending"
    refunded_at = (
        order.get("temp_refunded_at")
        or order.get("rental_refunded_at")
        or order.get("provider_refunded_at")
        or order.get("provisioning_failure_at")
    )
    return {
        "status": "refunded" if refunded else "pending" if pending else "none",
        "refunded": bool(refunded),
        "pending": bool(pending),
        "reason": public_refund_reason(public_status=public_status, refunded=refunded, pending=pending),
        "refunded_at": refunded_at.isoformat() if isinstance(refunded_at, datetime) else None,
    }


def public_refund_reason(*, public_status: str, refunded: bool = False, pending: bool = False) -> str:
    status = str(public_status or "").strip().lower()
    if refunded or status == "refunded":
        return "automatic_refund"
    if pending or status == "refund_pending":
        return "refund_pending"
    return ""


def _customer_state_payload(
    order: dict[str, Any],
    *,
    public_status: str,
    mode: str,
    sms_delivery: str,
    provider_id: str,
    code: str,
    seconds_left: int,
    can_resend: bool,
    can_replace: bool,
    can_alternate_provider: bool,
) -> dict[str, Any]:
    status = str(public_status or "waiting").strip().lower() or "waiting"
    mode = str(mode or "temp").strip().lower() or "temp"
    delivery = str(sms_delivery or "").strip().lower()
    support_review_open = str(order.get("temp_refund_support_review_status") or "").strip().lower() == "open"
    awaiting_webhook = bool(status == "waiting" and delivery == "webhook")

    key = status
    tone = "waiting"
    status_label_key = "waiting"
    receive_label_key = "waiting"
    message_key = "waitForSms"
    recommended_action_key = "refresh"

    if mode == "voice":
        status_label_key = "waitingCall"
        receive_label_key = "waitingCall"
        message_key = "waitForCall"
        recommended_action_key = "checkCall"
    elif mode == "rental":
        message_key = "waitForRentalSms"
        recommended_action_key = "rentalSms"

    if awaiting_webhook:
        key = "awaiting_provider_webhook" if mode != "voice" else "awaiting_call_webhook"
        message_key = "waitForWebhook" if mode != "voice" else "waitForCallWebhook"
    if status == "code_received":
        key = "code_received"
        tone = "success"
        status_label_key = "code"
        receive_label_key = "code"
        message_key = "codeReady"
        recommended_action_key = "copyCode"
    elif status == "call_received":
        key = "call_received"
        tone = "success"
        status_label_key = "callReceived"
        receive_label_key = "recording"
        message_key = "recordingReady"
        recommended_action_key = "playRecording"
    elif status == "waiting_for_recording":
        key = "waiting_for_recording"
        status_label_key = "recordingPending"
        receive_label_key = "recordingPending"
        message_key = "waitForRecording"
        recommended_action_key = "checkCall"
    elif status == "refund_pending":
        key = "support_review_pending" if support_review_open else "refund_pending"
        tone = "pending-refund"
        status_label_key = "refundPending"
        receive_label_key = "refundPending"
        message_key = "supportReviewQueued" if support_review_open else "autoRefundChecking"
        recommended_action_key = "openSupport" if support_review_open else "refresh"
    elif status == "refunded":
        key = "refunded"
        tone = "refunded"
        status_label_key = "refunded"
        receive_label_key = "refunded"
        message_key = "refundedToWallet"
        recommended_action_key = "none"
    elif status in {"failed", "expired"}:
        key = status
        tone = "danger"
        status_label_key = "expired" if status == "expired" else "failed"
        receive_label_key = status_label_key
        message_key = "orderClosedNoCode"
        recommended_action_key = "tryAnother" if can_replace or can_alternate_provider else "openSupport"

    return {
        "key": key,
        "tone": tone,
        "status_label_key": status_label_key,
        "receive_label_key": receive_label_key,
        "message_key": message_key,
        "recommended_action_key": recommended_action_key,
        "provider_reference": provider_id,
        "show_provider_identity": False,
        "awaiting_webhook": awaiting_webhook,
        "auto_refund_managed": bool(mode in {"temp", "voice"} and status in {"waiting", "refund_pending", "refunded", "failed", "expired"}),
        "manual_refund_available": False,
        "support_review_open": support_review_open,
        "can_copy_number": bool(str(order.get("provider_number") or "").strip()),
        "can_copy_code": bool(str(code or "").strip()),
        "can_request_second_code": bool(can_resend),
        "can_request_replacement": bool(can_replace),
        "can_request_alternate_provider": bool(can_alternate_provider),
        "seconds_left": max(0, int(seconds_left or 0)),
    }


async def _idempotency_get(user_id: int, key: str) -> dict[str, Any] | None:
    return await _idempotency_get_for_operation(user_id, key, operation="create_temp_order")


async def _idempotency_get_for_operation(user_id: int, key: str, *, operation: str) -> dict[str, Any] | None:
    if not key:
        return None
    row = await db.numbers_api_idempotency_keys.find_one(
        {"user_id": int(user_id), "key": key, "operation": str(operation or "create_temp_order")}
    )
    response = row.get("response") if isinstance(row, dict) else None
    return response if isinstance(response, dict) else None


async def _idempotency_save(user_id: int, key: str, response: dict[str, Any]) -> None:
    await _idempotency_save_for_operation(user_id, key, response, operation="create_temp_order")


async def _idempotency_save_for_operation(user_id: int, key: str, response: dict[str, Any], *, operation: str) -> None:
    if not key:
        return
    await db.numbers_api_idempotency_keys.update_one(
        {"user_id": int(user_id), "key": key, "operation": str(operation or "create_temp_order")},
        {
            "$set": {
                "user_id": int(user_id),
                "key": key,
                "operation": str(operation or "create_temp_order"),
                "response": response,
                "updated_at": _utc_now(),
            },
            "$setOnInsert": {"created_at": _utc_now()},
        },
        upsert=True,
    )


async def _resolve_temp_offer_from_quote(quote_token: str) -> dict[str, Any]:
    try:
        quote = verify_quote_token(quote_token)
    except QuoteTokenError as exc:
        raise NumbersOrderError(str(exc), "This quote is no longer valid.", status=400) from exc

    if str(quote.get("mode") or "temp").strip().lower() != "temp":
        raise NumbersOrderError("unsupported_quote_mode", "Only temporary-number quotes are supported by this endpoint.", status=400)

    service = str(quote.get("service") or "").strip()
    country = str(quote.get("country") or "none").strip() or "none"
    state = str(quote.get("state") or "none").strip() or "none"
    provider_code = str(quote.get("provider") or "").strip().lower()
    quote_provider_country = str(quote.get("provider_country") or "").strip()
    quote_provider_country_iso = str(quote.get("provider_country_iso") or "").strip().upper()
    if not provider_code:
        provider_code = provider_code_from_public_id(
            quote.get("provider_id"),
            allowed_codes=TEMP_QUOTE_PROVIDER_CODES,
        )
    if not service or not provider_code:
        raise NumbersOrderError("invalid_quote", "This quote is incomplete.", status=400)
    if not provider_purchase_enabled(provider_code, mode="temp"):
        readiness = provider_readiness(provider_code)
        raise NumbersOrderError(
            "provider_not_ready",
            readiness.reason or "This provider is not ready for production orders.",
            status=409,
        )

    pricing_country = _quote_pricing_country(
        provider_code=provider_code,
        country=country,
        provider_country=quote_provider_country,
        provider_country_iso=quote_provider_country_iso,
    )
    prices = await get_all_prices(
        service,
        pricing_country,
        state,
        ignore_balance=True,
        with_success_rates=False,
        provider_codes=(provider_code,),
    )
    info = prices.get(provider_code)
    if not isinstance(info, dict) or not temp_provider_offer_is_buyable(provider_code, info):
        raise NumbersOrderError("offer_unavailable", "This offer is no longer available.", status=409)

    return {
        "service": service,
        "country": country,
        "state": state,
        "provider_code": provider_code,
        "info": info,
    }


async def _resolve_rental_offer_from_quote(quote_token: str) -> dict[str, Any]:
    try:
        quote = verify_quote_token(quote_token)
    except QuoteTokenError as exc:
        raise NumbersOrderError(str(exc), "This quote is no longer valid.", status=400) from exc

    if str(quote.get("mode") or "").strip().lower() != "rental":
        raise NumbersOrderError("unsupported_quote_mode", "Only rental-number quotes are supported by this endpoint.", status=400)

    service = str(quote.get("service") or "").strip()
    country = str(quote.get("country") or "none").strip() or "none"
    provider_code = provider_code_from_public_id(
        quote.get("provider_id"),
        allowed_codes=RENTAL_QUOTE_PROVIDER_CODES,
    )
    match_key = tuple(str(part) for part in (quote.get("option_key") or []))
    if not service or not country or not provider_code or len(match_key) not in {6, 7}:
        raise NumbersOrderError("invalid_quote", "This quote is incomplete.", status=400)
    if not provider_purchase_enabled(provider_code, mode="rental"):
        readiness = provider_readiness(provider_code)
        raise NumbersOrderError(
            "provider_not_ready",
            readiness.reason or "This provider is not ready for production orders.",
            status=409,
        )

    state = rental_state_code_for_quote(str(quote.get("state") or match_key[4] or "none"))
    prices = await get_all_rental_prices(service, country, with_success_rates=False)
    provider_info = prices.get(provider_code)
    if not isinstance(provider_info, dict) or not str(provider_info.get("api_service_name") or "").strip():
        raise NumbersOrderError("provider_unavailable", "This provider is no longer available.", status=409)

    for option in rental_option_candidates(provider_code, provider_info, state=state):
        option_match_key = rental_option_match_key(option)
        if option_match_key != match_key and not (len(match_key) == 6 and option_match_key[:6] == match_key):
            continue
        if not rental_option_is_buyable(
            service=service,
            country=country,
            provider_code=provider_code,
            provider_info=provider_info,
            option=option,
        ):
            raise NumbersOrderError("provider_unavailable", "This provider is no longer available.", status=409)
        return {
            "service": service,
            "country": str(option.get("country") or option.get("provider_country") or country).strip() or country,
            "provider_code": provider_code,
            "provider_info": provider_info,
            "option": option,
        }

    raise NumbersOrderError("provider_price_changed", "This rental option is no longer available.", status=409)


async def _voice_quote_prices(service: str, country: str, state: str) -> dict[str, dict[str, Any]]:
    raw = await get_all_voice_prices(service, country, state, ignore_balance=True)
    if _has_voice_buyable_offer(raw):
        return raw
    if str(service or "").strip().lower() == VOICE_GENERIC_SERVICE:
        return raw

    fallback = await get_all_voice_prices(VOICE_GENERIC_SERVICE, "1", state, ignore_balance=True)
    patched: dict[str, dict[str, Any]] = {}
    for code, info in (fallback or {}).items():
        if not isinstance(info, dict):
            continue
        item = dict(info)
        item["voice_fallback_service"] = True
        item["voice_requested_service"] = str(service or "")
        patched[str(code or "").strip().lower()] = item
    return patched


def _has_voice_buyable_offer(raw: dict[str, dict[str, Any]] | None) -> bool:
    return any(
        voice_provider_offer_is_buyable(str(code or "").strip().lower(), info)
        for code, info in (raw or {}).items()
        if isinstance(info, dict)
    )


async def _resolve_voice_offer_from_quote(quote_token: str) -> dict[str, Any]:
    try:
        quote = verify_quote_token(quote_token)
    except QuoteTokenError as exc:
        raise NumbersOrderError(str(exc), "This quote is no longer valid.", status=400) from exc

    if str(quote.get("mode") or "").strip().lower() != "voice":
        raise NumbersOrderError("unsupported_quote_mode", "Only voice-number quotes are supported by this endpoint.", status=400)

    service = str(quote.get("service") or "").strip()
    provider_code = provider_code_from_public_id(
        quote.get("provider_id"),
        allowed_codes=VOICE_QUOTE_PROVIDER_CODES,
    )
    country = "1"
    state = str(quote.get("state") or "none").strip() or "none"
    if not service or not provider_code:
        raise NumbersOrderError("invalid_quote", "This quote is incomplete.", status=400)
    if not provider_purchase_enabled(provider_code, mode="voice"):
        readiness = provider_readiness(provider_code)
        raise NumbersOrderError(
            "provider_not_ready",
            readiness.reason or "This provider is not ready for production orders.",
            status=409,
        )

    prices = await _voice_quote_prices(service, country, state)
    info = prices.get(provider_code)
    if not isinstance(info, dict) or not voice_provider_offer_is_buyable(provider_code, info):
        raise NumbersOrderError("offer_unavailable", "This offer is no longer available.", status=409)

    return {
        "service": service,
        "country": country,
        "state": state,
        "provider_code": provider_code,
        "info": info,
    }


async def create_number_order_from_quote(
    *,
    user_id: int,
    reseller_id: int,
    quote_token: str,
    idempotency_key: str = "",
    lang: str = "en",
) -> dict[str, Any]:
    try:
        quote = verify_quote_token(quote_token)
    except QuoteTokenError as exc:
        raise NumbersOrderError(str(exc), "This quote is no longer valid.", status=400) from exc

    mode = str(quote.get("mode") or "temp").strip().lower() or "temp"
    if mode == "temp":
        return await create_temp_order_from_quote(
            user_id=user_id,
            reseller_id=reseller_id,
            quote_token=quote_token,
            idempotency_key=idempotency_key,
            lang=lang,
        )
    if mode == "rental":
        return await create_rental_order_from_quote(
            user_id=user_id,
            reseller_id=reseller_id,
            quote_token=quote_token,
            idempotency_key=idempotency_key,
            lang=lang,
        )
    if mode == "voice":
        return await create_voice_order_from_quote(
            user_id=user_id,
            reseller_id=reseller_id,
            quote_token=quote_token,
            idempotency_key=idempotency_key,
            lang=lang,
        )
    raise NumbersOrderError("unsupported_quote_mode", "This quote mode is not supported by the order endpoint.", status=400)


async def create_temp_order_from_quote(
    *,
    user_id: int,
    reseller_id: int,
    quote_token: str,
    idempotency_key: str = "",
    lang: str = "en",
    source_order_id: str | None = None,
    source_reason: str | None = None,
    idempotency_operation: str = "create_temp_order",
    source: str = "numbers_api",
    telegram_bot_id: int | None = None,
    telegram_wait: dict[str, Any] | None = None,
) -> dict[str, Any]:
    operation = str(idempotency_operation or "create_temp_order")
    cached = (
        await _idempotency_get(user_id, idempotency_key)
        if operation == "create_temp_order"
        else await _idempotency_get_for_operation(user_id, idempotency_key, operation=operation)
    )
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    offer = await _resolve_temp_offer_from_quote(quote_token)
    service = str(offer["service"])
    country = str(offer["country"])
    state = str(offer["state"])
    provider_code = str(offer["provider_code"])
    info = offer["info"] if isinstance(offer.get("info"), dict) else {}
    api_service = str(info.get("api_service_name") or "").strip()
    final_price = float(info.get("price") or 0.0)
    cost_price = float(info.get("base_price") or final_price)

    order = await create_order(
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        service_id=service,
        selling_price=final_price,
        base_price=cost_price,
    )
    order_id = order["_id"]
    await update_order_details(
        order_id,
        {
            "number_mode": "temp",
            "source": str(source or "numbers_api"),
            "api_version": "v1",
            "api_idempotency_key": str(idempotency_key or "") or None,
            "telegram_bot_id": telegram_bot_id,
            "provisioning_state": "awaiting_charge",
            "provisioning_provider": provider_code,
            "provisioning_service": api_service,
            "provisioning_country": None if country == "none" else country,
            "provisioning_state_code": None if state == "none" else state,
            "provisioning_created_at": _utc_now(),
            "temp_retry_source_order_id": str(source_order_id or "") or None,
            "temp_retry_reason": str(source_reason or "") or None,
        },
    )
    order.update({"number_mode": "temp", "provisioning_provider": provider_code})
    await _log_number_event_from_order(
        order,
        "order_created",
        payload={"source": str(source or "numbers_api"), "source_order_id": source_order_id, "source_reason": source_reason},
        number_mode="temp",
    )

    try:
        provider_country = str(info.get("provider_country") or country or "").strip()
        async def _provision() -> dict[str, Any]:
            return await provision_charged_temp_order(
                order=order,
                order_id=order_id,
                user_id=int(user_id),
                reseller_id=int(reseller_id),
                provider_code=provider_code,
                api_service=api_service,
                country=None if provider_country == "none" else provider_country,
                state=None if state == "none" else state,
                service_name=service,
                final_price=final_price,
                cost_price=cost_price,
                number_mode="temp",
                source=str(source or "numbers_api"),
                telegram_wait=telegram_wait,
                purchase_options={
                    "reuse_mode": True,
                    **({"provider_country": provider_country} if provider_country else {}),
                    "_audit_requested_service": service,
                    **({"retry_reason": str(source_reason)} if source_reason else {}),
                },
            )

        await execute_order_provisioning_transaction(
            order=order,
            order_id=order_id,
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            final_price=final_price,
            cost_price=cost_price,
            lang=lang,
            number_mode="temp",
            source="numbers_api",
            provision_fn=_provision,
            unexpected_failure_message="Provider could not reserve the number. Your balance was refunded.",
            charge_fn=charge_order_or_raise,
        )
        fresh_order = await get_order(order_id) or order
        response = {"ok": True, "order": public_order_payload(fresh_order)}
        await enqueue_event_for_user(
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            event_type="numbers.order.created",
            data={"order": response["order"]},
        )
        if operation == "create_temp_order":
            await _idempotency_save(user_id, idempotency_key, response)
        else:
            await _idempotency_save_for_operation(user_id, idempotency_key, response, operation=operation)
        return response
    except ProviderProvisioningError as exc:
        raise NumbersOrderError(
            "provider_failed",
            "Provider could not reserve the number. Your balance was refunded.",
            status=409,
        ) from exc
    except OrderChargeError as exc:
        raise NumbersOrderError(exc.code, exc.public_message, status=402) from exc
    except UnexpectedProvisioningError as exc:
        raise NumbersOrderError("provider_failed", exc.public_message, status=409) from exc
    except NumbersOrderError:
        raise


def _quote_pricing_country(
    *,
    provider_code: str,
    country: str,
    provider_country: str,
    provider_country_iso: str,
) -> str:
    if str(provider_code or "").strip().lower() == "herosms" and provider_country_iso:
        internal_code = _country_code_from_iso(provider_country_iso)
        if internal_code:
            return internal_code
    return provider_country or country


def _country_code_from_iso(iso: str) -> str:
    target = str(iso or "").strip().upper()
    if not target:
        return ""
    for row in COUNTRIES_LIST:
        if str(row.get("iso") or "").strip().upper() == target:
            return str(row.get("code") or "").strip()
    return ""

async def create_voice_order_from_quote(
    *,
    user_id: int,
    reseller_id: int,
    quote_token: str,
    idempotency_key: str = "",
    lang: str = "en",
    source_order_id: str | None = None,
    source_reason: str | None = None,
    idempotency_operation: str = "create_voice_order",
    source: str = "numbers_api",
    telegram_bot_id: int | None = None,
) -> dict[str, Any]:
    operation = str(idempotency_operation or "create_voice_order")
    cached = await _idempotency_get_for_operation(user_id, idempotency_key, operation=operation)
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    offer = await _resolve_voice_offer_from_quote(quote_token)
    service = str(offer["service"])
    country = str(offer["country"])
    state = str(offer["state"])
    provider_code = str(offer["provider_code"])
    info = offer["info"] if isinstance(offer.get("info"), dict) else {}
    api_service = str(info.get("api_service_name") or "").strip()
    final_price = float(info.get("price") or 0.0)
    cost_price = float(info.get("base_price") or final_price)

    if not service or not provider_code or not api_service or final_price <= 0:
        raise NumbersOrderError("invalid_quote", "This quote is incomplete.", status=400)

    order = await create_order(
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        service_id=service,
        selling_price=final_price,
        base_price=cost_price,
    )
    order_id = order["_id"]
    await update_order_details(
        order_id,
        {
            "number_mode": "voice",
            "source": str(source or "numbers_api"),
            "api_version": "v1",
            "api_idempotency_key": str(idempotency_key or "") or None,
            "telegram_bot_id": telegram_bot_id,
            "provisioning_state": "awaiting_charge",
            "provisioning_provider": provider_code,
            "provisioning_service": api_service,
            "provisioning_country": country,
            "provisioning_state_code": None if state == "none" else state,
            "provisioning_created_at": _utc_now(),
            "temp_retry_source_order_id": str(source_order_id or "") or None,
            "temp_retry_reason": str(source_reason or "") or None,
        },
    )
    order.update(
        {
            "number_mode": "voice",
            "provisioning_provider": provider_code,
            "provisioning_country": country,
            "provisioning_state_code": None if state == "none" else state,
        }
    )
    await _log_number_event_from_order(
        order,
        "order_created",
        payload={"source": str(source or "numbers_api"), "source_order_id": source_order_id, "source_reason": source_reason},
        number_mode="voice",
    )

    try:
        provider_country = str(info.get("provider_country") or country or "").strip()
        async def _provision() -> dict[str, Any]:
            return await provision_charged_temp_order(
                order=order,
                order_id=order_id,
                user_id=int(user_id),
                reseller_id=int(reseller_id),
                provider_code=provider_code,
                api_service=api_service,
                country=None if provider_country == "none" else provider_country,
                state=None if state == "none" else state,
                service_name=service,
                final_price=final_price,
                cost_price=cost_price,
                number_mode="voice",
                source=str(source or "numbers_api"),
                purchase_options={
                    "reuse_mode": True,
                    "_audit_requested_service": service,
                    "capability": "voice",
                    **({"retry_reason": str(source_reason)} if source_reason else {}),
                },
            )

        await execute_order_provisioning_transaction(
            order=order,
            order_id=order_id,
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            final_price=final_price,
            cost_price=cost_price,
            lang=lang,
            number_mode="voice",
            source="numbers_api",
            provision_fn=_provision,
            unexpected_failure_message="Provider could not reserve the call number. Your balance was refunded.",
            charge_fn=charge_order_or_raise,
        )
        fresh_order = await get_order(order_id) or order
        response = {"ok": True, "order": public_order_payload(fresh_order)}
        await enqueue_event_for_user(
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            event_type="numbers.order.created",
            data={"order": response["order"]},
        )
        await _idempotency_save_for_operation(user_id, idempotency_key, response, operation=operation)
        return response
    except ProviderProvisioningError as exc:
        raise NumbersOrderError(
            "provider_failed",
            "Provider could not reserve the call number. Your balance was refunded.",
            status=409,
        ) from exc
    except OrderChargeError as exc:
        raise NumbersOrderError(exc.code, exc.public_message, status=402) from exc
    except UnexpectedProvisioningError as exc:
        raise NumbersOrderError("provider_failed", exc.public_message, status=409) from exc
    except NumbersOrderError:
        raise


def _quoteable_temp_prices(prices: dict[str, Any], *, service: str, country: str, state: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for code, info in (prices or {}).items():
        provider_code = str(code or "").strip().lower()
        if not isinstance(info, dict):
            continue
        if not temp_provider_offer_is_buyable(provider_code, info):
            continue
        if provider_code not in TEMP_QUOTE_PROVIDER_CODES:
            continue
        if not service or not country:
            continue
        if country != "1" and state != "none":
            continue
        rows[provider_code] = info
    return rows


async def enable_alternate_provider_suggestion(
    *,
    order_id: Any,
    order: dict[str, Any],
    lang: str = "en",
    source: str = "numbers_api",
) -> dict[str, Any] | None:
    if str((order or {}).get("number_mode") or "").strip().lower() != "temp":
        return None
    if not _temp_like_replace_available(order):
        return None

    replacement = temp_replacement_fields(order)
    service = str(replacement.get("service") or "")
    current_provider = str(replacement.get("provider") or "").strip().lower()
    country = str(replacement.get("country") or "none")
    state = str(replacement.get("state") or "none")
    if not service:
        return None

    try:
        prices = await get_all_prices(
            service,
            country,
            state,
            ignore_balance=True,
            with_success_rates=False,
            provider_codes=TEMP_QUOTE_PROVIDER_CODES,
        )
    except Exception:
        return None

    picked = pick_retry_provider(
        _quoteable_temp_prices(prices, service=service, country=country, state=state),
        exclude_provider=current_provider,
        hidden_provider_codes=set(),
    )
    if not picked:
        return None

    provider_code, info = picked
    try:
        suggested_price = float(info.get("price") or 0.0)
    except Exception:
        suggested_price = 0.0
    try:
        suggested_base_price = float(info.get("base_price") or suggested_price)
    except Exception:
        suggested_base_price = suggested_price
    await update_order_details(
        order_id,
        {
            "temp_alternate_enabled": True,
            "temp_alternate_provider": provider_code,
            "temp_alternate_api_service": str(info.get("api_service_name") or ""),
            "temp_alternate_price": suggested_price,
            "temp_alternate_base_price": suggested_base_price,
            "temp_alternate_suggested_at": _utc_now(),
        },
    )
    await _log_temp_event(
        order,
        "alternate_provider_suggested",
        {
            "source": str(source or "numbers_api"),
            "provider": provider_code,
            "price": suggested_price,
            "message_language": lang,
        },
    )
    return {"provider": provider_code, "info": info, "price": suggested_price}


async def request_replacement_order(
    *,
    order: dict[str, Any],
    user_id: int,
    reseller_id: int,
    idempotency_key: str,
    lang: str = "en",
    alternate_provider: bool = False,
    source: str = "numbers_api",
    telegram_bot_id: int | None = None,
    telegram_wait: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not str(idempotency_key or "").strip():
        raise NumbersOrderError("missing_idempotency_key", "Idempotency-Key is required for replacement orders.", status=400)

    mode = str((order or {}).get("number_mode") or "").strip().lower()
    if mode not in {"temp", "voice"}:
        raise NumbersOrderError("invalid_mode", "This action is only for temporary or voice numbers.", status=400)
    if not _temp_like_replace_available(order):
        raise NumbersOrderError("replace_unavailable", "A replacement is not available for this order.", status=409)

    order_id = str((order or {}).get("_id") or "").strip()
    replacement = temp_replacement_fields(order)
    service = str(replacement.get("service") or "")
    current_provider = str(replacement.get("provider") or "").strip().lower()
    provider_code = current_provider
    country = str(replacement.get("country") or "none")
    state = str(replacement.get("state") or "none")

    if mode == "voice":
        if alternate_provider:
            raise NumbersOrderError("alternate_unavailable", "No alternate provider is available for this order.", status=409)
        country = "1"
    elif alternate_provider:
        provider_code = str((order or {}).get("temp_alternate_provider") or "").strip().lower()
        if not bool((order or {}).get("temp_alternate_enabled")) or not provider_code or provider_code == current_provider:
            suggestion = await enable_alternate_provider_suggestion(order_id=order_id, order=order, lang=lang, source=source)
            provider_code = str((suggestion or {}).get("provider") or "").strip().lower()
        if not provider_code or provider_code == current_provider:
            raise NumbersOrderError("alternate_unavailable", "No alternate provider is available for this order.", status=409)

    if not service or not provider_code:
        raise NumbersOrderError("replace_unavailable", "A replacement is not available for this order.", status=409)
    if mode == "temp" and provider_code in HIDDEN_TEMP_PROVIDER_CODES and not alternate_provider:
        raise NumbersOrderError("replace_unavailable", "A replacement is not available for this order.", status=409)

    if mode == "voice":
        prices = await _voice_quote_prices(service, country, state)
        info = prices.get(provider_code)
        if not isinstance(info, dict) or not voice_provider_offer_is_buyable(provider_code, info):
            raise NumbersOrderError("provider_unavailable", "This provider is not available right now.", status=409)
        quote_token = make_quote_token(
            {"mode": "voice", "service": service, "country": country, "state": state, "provider": provider_code}
        )
        result = await create_voice_order_from_quote(
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            quote_token=quote_token,
            idempotency_key=str(idempotency_key),
            lang=lang,
            source_order_id=order_id,
            source_reason="replace_request",
            idempotency_operation="replace_voice_order",
            source=source,
            telegram_bot_id=telegram_bot_id,
        )
    else:
        prices = await get_all_prices(
            service,
            country,
            state,
            ignore_balance=True,
            with_success_rates=False,
            provider_codes=TEMP_QUOTE_PROVIDER_CODES,
        )
        info = prices.get(provider_code)
        if not isinstance(info, dict) or not temp_provider_offer_is_buyable(provider_code, info):
            raise NumbersOrderError(
                "alternate_unavailable" if alternate_provider else "provider_unavailable",
                "No alternate provider is available for this order." if alternate_provider else "This provider is not available right now.",
                status=409,
            )
        quote_token = make_quote_token(
            {"mode": "temp", "service": service, "country": country, "state": state, "provider": provider_code}
        )
        result = await create_temp_order_from_quote(
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            quote_token=quote_token,
            idempotency_key=str(idempotency_key),
            lang=lang,
            source_order_id=order_id,
            source_reason="alternate_provider_request" if alternate_provider else "replace_request",
            idempotency_operation="alternate_provider_order" if alternate_provider else "replace_temp_order",
            source=source,
            telegram_bot_id=telegram_bot_id,
            telegram_wait=telegram_wait,
        )

    if result.get("ok"):
        await _log_temp_event(
            order,
            "replacement_requested",
            {
                "source": str(source or "numbers_api"),
                "replacement_order_id": str((result.get("order") or {}).get("id") or ""),
                "provider": provider_code,
                "alternate_provider": bool(alternate_provider),
            },
        )
    return result


async def create_rental_order_from_quote(
    *,
    user_id: int,
    reseller_id: int,
    quote_token: str,
    idempotency_key: str = "",
    lang: str = "en",
) -> dict[str, Any]:
    cached = await _idempotency_get_for_operation(user_id, idempotency_key, operation="create_rental_order")
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    offer = await _resolve_rental_offer_from_quote(quote_token)
    service = str(offer["service"])
    country = str(offer["country"])
    provider_code = str(offer["provider_code"])
    provider_info = offer["provider_info"] if isinstance(offer.get("provider_info"), dict) else {}
    selected = offer["option"] if isinstance(offer.get("option"), dict) else {}
    api_service = str(selected.get("api_service_name") or provider_info.get("api_service_name") or "").strip()
    try:
        duration = int(selected.get("duration") or 0)
    except Exception:
        duration = 0
    try:
        final_price = float(selected.get("price") or 0.0)
    except Exception:
        final_price = 0.0
    try:
        cost_price = float(selected.get("base_price", final_price) or final_price)
    except Exception:
        cost_price = final_price

    if not service or not provider_code or not api_service or not country or duration <= 0 or final_price <= 0:
        raise NumbersOrderError("invalid_quote", "This quote is incomplete.", status=400)

    order = await create_order(
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        service_id=f"{service}:rental",
        selling_price=final_price,
        base_price=cost_price,
    )
    order_id = order["_id"]
    state_code = str(selected.get("state_code") or "none")
    await update_order_details(
        order_id,
        {
            "number_mode": "rental",
            "source": "numbers_api",
            "api_version": "v1",
            "api_idempotency_key": str(idempotency_key or "") or None,
            "telegram_bot_id": None,
            "provisioning_state": "awaiting_charge",
            "provisioning_provider": provider_code,
            "provisioning_service": api_service,
            "provisioning_country": country,
            "provisioning_state_code": state_code,
            "provisioning_duration_hours": int(duration),
            "provisioning_created_at": _utc_now(),
        },
    )
    order.update(
        {
            "number_mode": "rental",
            "provisioning_provider": provider_code,
            "provisioning_country": country,
            "provisioning_state_code": state_code,
        }
    )
    await _log_number_event_from_order(
        order,
        "order_created",
        payload={"duration_hours": int(duration), "source": "numbers_api"},
        number_mode="rental",
    )

    try:
        option_meta = {
            key: selected.get(key)
            for key in (
                "rental_id",
                "duration_days",
                "country",
                "country_name",
                "country_label",
                "country_iso",
                "provider_country",
                "provider_country_iso",
                "provider_country_name",
                "tv_with_state",
                "state_code",
                "tv_duration_key",
                "tv_is_renewable",
                "provider_duration",
                "provider_app",
            )
            if selected.get(key) not in (None, "")
        }
        is_renewable = bool(selected.get("tv_is_renewable") or selected.get("renewable") or selected.get("is_renewable"))
        billing_cycle_label = str(selected.get("rental_billing_cycle_label") or "")
        if is_renewable and not billing_cycle_label:
            billing_cycle_label = "Auto renew"

        async def _provision() -> dict[str, Any]:
            return await provision_charged_rental_order(
                order=order,
                order_id=order_id,
                user_id=int(user_id),
                reseller_id=int(reseller_id),
                provider_code=provider_code,
                api_service=api_service,
                country=country,
                service_name=service,
                duration=duration,
                duration_label=rental_duration_label(selected),
                country_name=str(selected.get("country_name") or selected.get("provider_country_name") or selected.get("country_label") or ""),
                final_price=final_price,
                cost_price=cost_price,
                option_meta=option_meta,
                is_renewable=is_renewable,
                billing_cycle_label=billing_cycle_label if is_renewable else "-",
                source="numbers_api",
            )

        provisioned = await execute_order_provisioning_transaction(
            order=order,
            order_id=order_id,
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            final_price=final_price,
            cost_price=cost_price,
            lang=lang,
            number_mode="rental",
            source="numbers_api",
            provision_fn=_provision,
            unexpected_failure_message="Provider could not reserve the rental. Your balance was refunded.",
            charge_fn=charge_order_or_raise,
        )
        rental_safe_cutoff_at = provisioned.get("rental_safe_cutoff_at")
        if rental_safe_cutoff_at:
            schedule_rental_refund_guard(order_id=order_id, actor_user_id=int(user_id))
        fresh_order = await get_order(order_id) or order
        response = {"ok": True, "order": public_order_payload(fresh_order)}
        await enqueue_event_for_user(
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            event_type="numbers.order.created",
            data={"order": response["order"]},
        )
        await _idempotency_save_for_operation(user_id, idempotency_key, response, operation="create_rental_order")
        return response
    except ProviderProvisioningError as exc:
        raise NumbersOrderError(
            "provider_failed",
            "Provider could not reserve the rental. Your balance was refunded.",
            status=409,
        ) from exc
    except OrderChargeError as exc:
        raise NumbersOrderError(exc.code, exc.public_message, status=402) from exc
    except UnexpectedProvisioningError as exc:
        raise NumbersOrderError("provider_failed", exc.public_message, status=409) from exc
    except NumbersOrderError:
        raise
