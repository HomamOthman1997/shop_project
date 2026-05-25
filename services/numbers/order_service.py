from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database.mongo import db
from database.orders_repo import create_order, extract_order_amounts, get_order, update_order_details, update_order_status
from services.numbers.api_payloads import QuoteTokenError, temp_provider_offer_is_buyable, verify_quote_token
from services.numbers.manager import buy_number_from_provider, get_all_prices
from services.numbers.provider_delivery import provider_sms_delivery_strategy
from services.numbers.shared.events import _log_number_event_from_order, _log_temp_event
from services.numbers.shared.temp_order import (
    TEMP_WAIT_TIMEOUT_SEC,
    _coerce_utc_datetime,
    _extract_provider_wait_timeout_sec,
    _poll_interval_for_provider,
    _provider_default_reuse_warranty_sec,
    _seconds_left_until,
    _temp_elapsed_sec,
    _utc_now,
)
from services.platform.webhooks import enqueue_event_for_user
from utils.core_service_guard import finance_error_public_text
from utils.financial_manager import FinancialManager
from utils.provider_alias import provider_public_id


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
    code = _order_last_code(order)
    codes = _order_codes(order)
    return {
        "id": str(order_id or ""),
        "status": str(order.get("status") or ""),
        "public_status": public_status,
        "mode": mode,
        "service": str(order.get("temp_service_key") or order.get("service_id") or "").replace(":rental", ""),
        "country": str(order.get("temp_country") or order.get("rental_country") or "none"),
        "state": str(order.get("temp_state") or order.get("rental_state_code") or "none"),
        "provider_id": str(order.get("provider_public_id") or provider_public_id(provider_code)),
        "provider": provider_code,
        "sms_delivery": str(order.get("provider_sms_delivery") or provider_sms_delivery_strategy(provider_code)),
        "number": str(order.get("provider_number") or ""),
        "selling_price": float(sale_price),
        "wait_state": str(order.get("temp_wait_state") or ""),
        "code": code,
        "codes": codes,
        "messages": _order_messages(order),
        "elapsed_sec": int(_temp_elapsed_sec(order)),
        "timeout_sec": int(_order_timeout_sec(order)),
        "seconds_left": seconds_left,
        "can_refresh": public_status in {"waiting", "code_received", "refund_pending"},
        "can_resend": can_resend,
        "resend_price": float(round(max(0.0, float(sale_price)) / 2.0, 4)) if can_resend else 0.0,
        "second_code_count": int(order.get("temp_second_code_count") or 0),
        "refund": _refund_payload(order, public_status=public_status),
    }


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
    if mode == "rental" and (int(order.get("rental_sms_count") or 0) > 0 or order.get("rental_sms_received_at")):
        return "code_received"
    if _order_has_received_code(order) and not _second_code_waiting(order):
        return "code_received"
    return "waiting"


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
    wait_state = str(order.get("temp_wait_state") or "").strip().lower()
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
        "reason": str(
            order.get("temp_refund_reason")
            or order.get("temp_refund_source")
            or order.get("temp_provider_terminal_reason")
            or order.get("rental_refund_reason")
            or wait_state
            or ""
        ),
        "refunded_at": refunded_at.isoformat() if isinstance(refunded_at, datetime) else None,
    }


async def _idempotency_get(user_id: int, key: str) -> dict[str, Any] | None:
    if not key:
        return None
    row = await db.numbers_api_idempotency_keys.find_one(
        {"user_id": int(user_id), "key": key, "operation": "create_temp_order"}
    )
    response = row.get("response") if isinstance(row, dict) else None
    return response if isinstance(response, dict) else None


async def _idempotency_save(user_id: int, key: str, response: dict[str, Any]) -> None:
    if not key:
        return
    await db.numbers_api_idempotency_keys.update_one(
        {"user_id": int(user_id), "key": key, "operation": "create_temp_order"},
        {
            "$set": {
                "user_id": int(user_id),
                "key": key,
                "operation": "create_temp_order",
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
    if not service or not provider_code:
        raise NumbersOrderError("invalid_quote", "This quote is incomplete.", status=400)

    prices = await get_all_prices(
        service,
        country,
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


async def create_temp_order_from_quote(
    *,
    user_id: int,
    reseller_id: int,
    quote_token: str,
    idempotency_key: str = "",
    lang: str = "en",
) -> dict[str, Any]:
    cached = await _idempotency_get(user_id, idempotency_key)
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
            "source": "numbers_api",
            "api_version": "v1",
            "api_idempotency_key": str(idempotency_key or "") or None,
            "telegram_bot_id": None,
            "provisioning_state": "awaiting_charge",
            "provisioning_provider": provider_code,
            "provisioning_service": api_service,
            "provisioning_country": None if country == "none" else country,
            "provisioning_state_code": None if state == "none" else state,
            "provisioning_created_at": _utc_now(),
        },
    )
    order.update({"number_mode": "temp", "provisioning_provider": provider_code})
    await _log_number_event_from_order(order, "order_created", payload={"source": "numbers_api"}, number_mode="temp")

    ok, message = await FinancialManager.process_core_purchase(
        user_id=int(user_id),
        order_id=order_id,
        sale_price=final_price,
        cost_price=cost_price,
        reseller_id=int(reseller_id),
    )
    if not ok:
        await update_order_status(order_id, "failed")
        await _log_number_event_from_order(
            order,
            "wallet_charge_failed",
            payload={"message": str(message), "source": "numbers_api"},
            status_after="failed",
            number_mode="temp",
        )
        raise NumbersOrderError(str(message), finance_error_public_text(lang, str(message)), status=402)

    try:
        await update_order_details(
            order_id,
            {"provisioning_state": "charged_pending_provider", "provisioning_charged_at": _utc_now()},
        )
        await _log_number_event_from_order(order, "wallet_charged", status_after="paid", number_mode="temp")

        provider_country = str(info.get("provider_country") or country or "").strip()
        buy_res = await buy_number_from_provider(
            provider_code=provider_code,
            api_service_name=api_service,
            country=None if provider_country == "none" else provider_country,
            state=None if state == "none" else state,
            dry_run=False,
            purchase_options={"reuse_mode": True, "_audit_requested_service": service, "source": "numbers_api"},
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
            raise NumbersOrderError(
                "provider_failed",
                "Provider could not reserve the number. Your balance was refunded.",
                status=409,
            )

        now = datetime.now(UTC)
        provider_timeout_sec = _extract_provider_wait_timeout_sec(buy_res)
        if provider_timeout_sec:
            provider_timeout_sec = min(TEMP_WAIT_TIMEOUT_SEC, int(provider_timeout_sec))
        reuse_warranty_sec = _provider_default_reuse_warranty_sec(provider_code)
        reuse_until = datetime.fromtimestamp(now.timestamp() + int(reuse_warranty_sec), tz=UTC)
        await update_order_details(
            order_id,
            {
                "provider_order_id": str(buy_res.get("order_id") or "").strip(),
                "provider": provider_code,
                "provider_sms_delivery": provider_sms_delivery_strategy(provider_code),
                "provider_number": str(buy_res.get("number") or "").strip(),
                "provider_pool": str(buy_res.get("pool") or "").strip() or None,
                "number_mode": "temp",
                "temp_api_service": api_service,
                "temp_country": None if country == "none" else country,
                "temp_state": None if state == "none" else state,
                "temp_service_key": service,
                "temp_reuse_warranty_until": reuse_until,
                "temp_reuse_warranty_sec": reuse_warranty_sec,
                "temp_wait_interval_sec": _poll_interval_for_provider(provider_code),
                "temp_wait_timeout_sec": provider_timeout_sec if provider_timeout_sec else TEMP_WAIT_TIMEOUT_SEC,
                "temp_last_refresh_at": None,
                "temp_replace_enabled": False,
                "temp_codes": [],
                "temp_codes_count": 0,
                "temp_wait_state": "waiting",
                "temp_wait_started_at": now,
                "provisioning_state": "provisioned",
                "provisioned_at": now,
            },
        )
        await update_order_status(order_id, "success")
        await _log_temp_event(
            {
                "_id": order_id,
                "user_id": int(user_id),
                "provider": provider_code,
                "service_id": service,
                "temp_country": None if country == "none" else country,
                "temp_state": None if state == "none" else state,
                "temp_api_service": api_service,
            },
            "purchase_success",
            {
                "sale_price": final_price,
                "base_price": cost_price,
                "provider_order_id": str(buy_res.get("order_id") or "").strip(),
                "provider_pool": str(buy_res.get("pool") or "").strip() or None,
                "source": "numbers_api",
            },
        )
        fresh_order = await get_order(order_id) or order
        response = {"ok": True, "order": public_order_payload(fresh_order)}
        await enqueue_event_for_user(
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            event_type="numbers.order.created",
            data={"order": response["order"]},
        )
        await _idempotency_save(user_id, idempotency_key, response)
        return response
    except NumbersOrderError:
        raise
    except Exception as exc:
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
        raise NumbersOrderError(
            "provider_failed",
            "Provider could not reserve the number. Your balance was refunded.",
            status=409,
        ) from exc
