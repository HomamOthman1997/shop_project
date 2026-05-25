from __future__ import annotations

from typing import Any

from database.orders_repo import get_order, update_order_details
from services.numbers.manager import PROVIDERS
from services.numbers.order_service import NumbersOrderError, public_order_payload
from services.numbers.shared.events import _log_temp_event
from services.numbers.shared.provider_io import fetch_provider_sms
from services.numbers.shared.temp_order import _extract_new_sms_code, _safe_code_text, _seconds_between, _utc_now
from services.numbers.shared.temp_refund import order_provider_code, order_provider_order_id


_CLOSED_STATUSES = {"cancelled", "failed", "refunded", "expired"}


async def refresh_number_order(order: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(order, dict) or not order.get("_id"):
        raise NumbersOrderError("order_not_found", "Order was not found.", status=404)

    mode = str(order.get("number_mode") or "temp").strip().lower()
    if mode != "temp":
        raise NumbersOrderError("unsupported_order_mode", "This order mode does not support refresh yet.", status=409)

    current = await get_order(order["_id"]) or order
    if str(current.get("status") or "").strip().lower() in _CLOSED_STATUSES:
        return {"ok": True, "order": public_order_payload(current)}

    if _has_received_code(current):
        return {"ok": True, "order": public_order_payload(current)}

    provider = order_provider_code(current)
    provider_order_id = order_provider_order_id(current)
    if not provider or not provider_order_id:
        raise NumbersOrderError("order_not_refreshable", "This order cannot be refreshed.", status=409)

    sms_data = await fetch_provider_sms(PROVIDERS, provider, provider_order_id)
    existing_codes = [str(code) for code in (current.get("temp_codes") or []) if str(code or "").strip()]
    code = _extract_new_sms_code(sms_data.get("messages") or [], set(existing_codes))
    now = _utc_now()

    if code:
        clean_code = _safe_code_text(code)
        updated_codes = [*existing_codes, clean_code]
        patch: dict[str, Any] = {
            "temp_wait_state": "code_received",
            "temp_last_refresh_at": now,
            "temp_last_sms_at": now,
            "temp_last_code": clean_code,
            "temp_codes": updated_codes,
            "temp_codes_count": len(updated_codes),
        }
        if not current.get("temp_first_sms_at"):
            patch["temp_first_sms_at"] = now
            seconds_to_first_sms = _seconds_between(now, current.get("created_at"))
            if seconds_to_first_sms is not None:
                patch["temp_seconds_to_first_sms"] = seconds_to_first_sms
        await update_order_details(current["_id"], patch)
        await _log_temp_event(
            current,
            "code_received",
            {
                "code_len": len(clean_code),
                "seconds_since_purchase": _seconds_between(now, current.get("created_at")),
                "source": "numbers_api_refresh",
            },
        )
        refreshed = await get_order(current["_id"]) or {**current, **patch}
        return {"ok": True, "order": public_order_payload(refreshed)}

    await update_order_details(current["_id"], {"temp_last_refresh_at": now})
    refreshed = await get_order(current["_id"]) or {**current, "temp_last_refresh_at": now}
    return {"ok": True, "order": public_order_payload(refreshed), "message": "No SMS yet."}


def _has_received_code(order: dict[str, Any]) -> bool:
    if str(order.get("temp_last_code") or "").strip():
        return True
    for code in order.get("temp_codes") or []:
        if str(code or "").strip():
            return True
    return False
