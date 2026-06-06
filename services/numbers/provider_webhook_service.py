from __future__ import annotations

from typing import Any

from database.provider_webhook_repo import (
    get_provider_webhook_event,
    mark_provider_webhook_event_replayed,
    record_provider_webhook_event,
    serialize_provider_webhook_event,
)
from database.orders_repo import get_number_order_by_provider_order, get_order, get_temp_order_by_provider_order, update_order_details
from services.numbers.order_service import public_order_payload
from services.numbers.miniapp_live import publish_number_order_update
from services.numbers.provider_webhook_normalizer import normalize_provider_sms_webhook
from services.numbers.shared.events import _log_rental_event, _log_temp_event
from services.numbers.shared.temp_order import _extract_new_sms_code, _safe_code_text, _seconds_between, _utc_now
from services.platform.webhooks import enqueue_event_for_user

_CLOSED_STATUSES = {"cancelled", "failed", "refunded", "expired"}


async def apply_provider_temp_sms_webhook(
    *,
    provider_code: str,
    provider_order_id: str,
    code: str,
    full_sms: str = "",
    raw_event: dict[str, Any] | None = None,
    record_audit: bool = True,
) -> dict[str, Any]:
    order = await get_temp_order_by_provider_order(provider_code, provider_order_id)
    if not isinstance(order, dict):
        order = await get_number_order_by_provider_order(provider_code, provider_order_id)
    if not isinstance(order, dict):
        if record_audit:
            await _record_provider_event(
                provider_code=provider_code,
                provider_order_id=provider_order_id,
                raw_event=raw_event,
                status="unmatched",
                reason="order_not_found",
            )
        return {"ok": False, "reason": "order_not_found"}

    if str(order.get("status") or "").strip().lower() in _CLOSED_STATUSES:
        if record_audit:
            await _record_provider_event(
                provider_code=provider_code,
                provider_order_id=provider_order_id,
                raw_event=raw_event,
                status="ignored",
                reason="order_closed",
                order_id=order.get("_id"),
            )
        return {"ok": True, "reason": "order_closed", "order": public_order_payload(order)}

    clean_code = _safe_code_text(code)
    if not clean_code and full_sms:
        clean_code = _safe_code_text(_extract_new_sms_code([str(full_sms)], set()) or "")
    if not clean_code:
        if record_audit:
            await _record_provider_event(
                provider_code=provider_code,
                provider_order_id=provider_order_id,
                raw_event=raw_event,
                status="ignored",
                reason="missing_code",
                order_id=order.get("_id"),
            )
        return {"ok": False, "reason": "missing_code", "order": public_order_payload(order)}

    mode = str(order.get("number_mode") or "temp").strip().lower()
    existing_codes = _existing_order_codes(order)
    if clean_code in set(existing_codes):
        if record_audit:
            await _record_provider_event(
                provider_code=provider_code,
                provider_order_id=provider_order_id,
                raw_event=raw_event,
                status="duplicate",
                reason="duplicate_code",
                order_id=order.get("_id"),
            )
        return {"ok": True, "reason": "duplicate_code", "order": public_order_payload(order)}

    now = _utc_now()
    patch = _sms_patch_for_order(order, code=clean_code, full_sms=full_sms, now=now, provider_code=provider_code, raw_event=raw_event)

    await update_order_details(order["_id"], patch)
    if mode == "rental":
        await _log_rental_event(
            order_id=order["_id"],
            user_id=int(order.get("user_id") or 0),
            provider=str(provider_code or "").strip().lower(),
            service_id=str(order.get("service_id") or ""),
            event="code_received",
            payload={
                "code_len": len(clean_code),
                "seconds_since_purchase": _seconds_between(now, order.get("created_at")),
                "source": f"{str(provider_code or '').strip().lower()}_provider_webhook",
            },
        )
    else:
        await _log_temp_event(
            order,
            "code_received",
            {
                "code_len": len(clean_code),
                "seconds_since_purchase": _seconds_between(now, order.get("created_at")),
                "source": f"{str(provider_code or '').strip().lower()}_provider_webhook",
            },
        )
    refreshed = await get_order(order["_id"]) or {**order, **patch}
    payload = {"ok": True, "reason": "code_received", "order": public_order_payload(refreshed)}
    await enqueue_event_for_user(
        user_id=int(refreshed.get("user_id") or order.get("user_id") or 0),
        reseller_id=int(refreshed.get("reseller_id") or order.get("reseller_id") or order.get("user_id") or 0),
        event_type="numbers.order.sms",
        data={"order": payload["order"]},
    )
    await publish_number_order_update(
        user_id=int(refreshed.get("user_id") or order.get("user_id") or 0),
        order_id=refreshed.get("_id") or order.get("_id"),
        reason="provider_webhook_code_received",
    )
    if record_audit:
        await _record_provider_event(
            provider_code=provider_code,
            provider_order_id=provider_order_id,
            raw_event=raw_event,
            status="processed",
            reason="code_received",
            order_id=refreshed.get("_id") or order.get("_id"),
        )
    return payload


def _existing_order_codes(order: dict[str, Any]) -> list[str]:
    mode = str(order.get("number_mode") or "temp").strip().lower()
    if mode == "rental":
        codes = [str(item) for item in (order.get("rental_codes") or []) if str(item or "").strip()]
        last_code = str(order.get("rental_last_code") or "").strip()
        return [*codes, *([last_code] if last_code and last_code not in codes else [])]
    codes = [str(item) for item in (order.get("temp_codes") or []) if str(item or "").strip()]
    last_code = str(order.get("temp_last_code") or "").strip()
    return [*codes, *([last_code] if last_code and last_code not in codes else [])]


def _sms_patch_for_order(
    order: dict[str, Any],
    *,
    code: str,
    full_sms: str,
    now: Any,
    provider_code: str,
    raw_event: dict[str, Any] | None,
) -> dict[str, Any]:
    mode = str(order.get("number_mode") or "temp").strip().lower()
    provider_webhook_patch = {
        "provider_webhook_last_at": now,
        "provider_webhook_last_provider": str(provider_code or "").strip().lower(),
        "provider_webhook_last_event": raw_event or {},
    }
    if mode == "rental":
        existing_messages = [str(item) for item in (order.get("rental_sms_messages") or []) if str(item or "").strip()]
        existing_codes = [str(item) for item in (order.get("rental_codes") or []) if str(item or "").strip()]
        message = str(full_sms or code).strip()
        messages = [*existing_messages, *([message] if message and message not in existing_messages else [])]
        codes = [*existing_codes, *([code] if code and code not in existing_codes else [])]
        return {
            **provider_webhook_patch,
            "rental_sms_received_at": order.get("rental_sms_received_at") or now,
            "rental_last_sms_at": now,
            "rental_last_code": code,
            "rental_codes": codes[:20],
            "rental_sms_messages": messages[:20],
            "rental_sms_count": len(messages),
            "rental_last_sms_text": message,
        }

    existing_codes = [str(item) for item in (order.get("temp_codes") or []) if str(item or "").strip()]
    updated_codes = [*existing_codes, *([code] if code and code not in existing_codes else [])]
    patch: dict[str, Any] = {
        **provider_webhook_patch,
        "temp_wait_state": "code_received",
        "temp_last_sms_at": now,
        "temp_last_code": code,
        "temp_codes": updated_codes,
        "temp_codes_count": len(updated_codes),
    }
    if full_sms:
        patch["temp_last_sms_text"] = str(full_sms)
    if not order.get("temp_first_sms_at"):
        patch["temp_first_sms_at"] = now
        seconds_to_first_sms = _seconds_between(now, order.get("created_at"))
        if seconds_to_first_sms is not None:
            patch["temp_seconds_to_first_sms"] = seconds_to_first_sms
    return patch


async def replay_provider_webhook_event(event_id: str) -> dict[str, Any]:
    doc = await get_provider_webhook_event(event_id)
    if not isinstance(doc, dict):
        return {"ok": False, "reason": "event_not_found"}
    provider = str(doc.get("provider") or "").strip().lower()
    payload = doc.get("payload") if isinstance(doc.get("payload"), dict) else {}
    normalized = normalize_provider_sms_webhook(provider, payload)
    if normalized.ignored:
        updated = await mark_provider_webhook_event_replayed(
            event_id=event_id,
            replay_status="ignored",
            replay_reason=normalized.ignored_reason,
        )
        return {
            "ok": True,
            "reason": normalized.ignored_reason,
            "event": serialize_provider_webhook_event(updated or doc),
        }

    result = await apply_provider_temp_sms_webhook(
        provider_code=normalized.provider_code,
        provider_order_id=normalized.provider_order_id,
        code=normalized.code,
        full_sms=normalized.full_sms,
        raw_event=normalized.raw_event,
        record_audit=False,
    )
    replay_status = "processed" if bool(result.get("ok")) else "failed"
    if str(result.get("reason") or "") == "duplicate_code":
        replay_status = "duplicate"
    updated = await mark_provider_webhook_event_replayed(
        event_id=event_id,
        replay_status=replay_status,
        replay_reason=str(result.get("reason") or ""),
        order_id=((result.get("order") or {}).get("id") if isinstance(result.get("order"), dict) else None),
    )
    return {
        "ok": bool(result.get("ok")),
        "reason": str(result.get("reason") or ""),
        "result": result,
        "event": serialize_provider_webhook_event(updated or doc),
    }


async def _record_provider_event(
    *,
    provider_code: str,
    provider_order_id: str,
    raw_event: dict[str, Any] | None,
    status: str,
    reason: str,
    order_id: Any = None,
) -> None:
    try:
        await record_provider_webhook_event(
            provider_code=provider_code,
            event_type=str((raw_event or {}).get("event") or ""),
            provider_order_id=provider_order_id,
            payload=raw_event or {},
            status=status,
            reason=reason,
            order_id=order_id,
        )
    except Exception:
        return
