from __future__ import annotations

from typing import Any

from database.mongo import db
from database.orders_repo import get_order, update_order_details
from services.numbers.manager import finish_rental_from_provider, notes_tags_from_provider, renew_rental_from_provider, wake_rental_from_provider
from services.numbers.order_service import NumbersOrderError, public_order_payload
from services.numbers.shared.events import _log_number_event_from_order
from services.numbers.shared.temp_order import _utc_now


_CLOSED_STATUSES = {"cancelled", "failed", "refunded", "expired"}


def _order_id(order: dict[str, Any]) -> Any:
    return order.get("_id")


def _ensure_rental_order(order: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(order, dict) or not order.get("_id"):
        raise NumbersOrderError("order_not_found", "Order was not found.", status=404)
    if str(order.get("number_mode") or "").strip().lower() != "rental":
        raise NumbersOrderError("invalid_mode", "This action is only for rental orders.", status=400)
    return order


def _ensure_open_rental_order(order: dict[str, Any]) -> None:
    if str(order.get("status") or "").strip().lower() in _CLOSED_STATUSES:
        raise NumbersOrderError("order_closed", "This rental order is already closed.", status=409)


def _provider_fields(order: dict[str, Any]) -> tuple[str, str]:
    provider = str(order.get("provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        raise NumbersOrderError("provider_order_missing", "This rental order is missing provider reservation data.", status=409)
    return provider, provider_order_id


async def _idempotency_get(*, user_id: int, order_id: Any, key: str, operation: str) -> dict[str, Any] | None:
    if not key:
        return None
    row = await db.numbers_api_idempotency_keys.find_one(
        {
            "user_id": int(user_id),
            "order_id": str(order_id),
            "key": str(key),
            "operation": operation,
        }
    )
    response = row.get("response") if isinstance(row, dict) else None
    return response if isinstance(response, dict) else None


async def _idempotency_save(*, user_id: int, order_id: Any, key: str, operation: str, response: dict[str, Any]) -> None:
    if not key:
        return
    await db.numbers_api_idempotency_keys.update_one(
        {
            "user_id": int(user_id),
            "order_id": str(order_id),
            "key": str(key),
            "operation": operation,
        },
        {
            "$set": {
                "user_id": int(user_id),
                "order_id": str(order_id),
                "key": str(key),
                "operation": operation,
                "response": response,
                "updated_at": _utc_now(),
            },
            "$setOnInsert": {"created_at": _utc_now()},
        },
        upsert=True,
    )


async def rental_sms_state(order: dict[str, Any], *, source: str = "numbers_api") -> dict[str, Any]:
    order = _ensure_rental_order(order)
    now = _utc_now()
    source = str(source or "numbers_api").strip() or "numbers_api"
    patch = {"rental_last_sms_check_at": now, "rental_last_sms_check_source": source}
    if source == "numbers_api":
        patch.update({"api_last_rental_sms_check_at": now, "api_last_rental_sms_check_mode": "provider_webhook"})
    await update_order_details(_order_id(order), patch)
    refreshed = await get_order(_order_id(order)) or {**order, **patch}
    payload = public_order_payload(refreshed)
    return {
        "ok": True,
        "message": "Waiting for provider webhook." if not payload.get("messages") else "Rental SMS loaded.",
        "messages": payload.get("messages") or [],
        "order": payload,
    }


async def finish_rental_order(order: dict[str, Any], *, source: str = "numbers_api") -> dict[str, Any]:
    order = _ensure_rental_order(order)
    if order.get("rental_finished_at"):
        return {"ok": True, "idempotent_replay": True, "message": "Rental already finished.", "order": public_order_payload(order)}
    _ensure_open_rental_order(order)
    provider, provider_order_id = _provider_fields(order)

    try:
        finish_res = await finish_rental_from_provider(provider, provider_order_id)
        ok = bool((finish_res or {}).get("success"))
    except Exception:
        finish_res = {"success": False}
        ok = False

    if not ok:
        await _log_number_event_from_order(order, "rental_finish_failed", payload={"source": source}, number_mode="rental")
        raise NumbersOrderError("finish_failed", "Could not finish this rental right now.", status=409)

    patch = {"rental_finished_at": _utc_now(), "rental_finish_raw": (finish_res or {}).get("raw")}
    await update_order_details(_order_id(order), patch)
    await _log_number_event_from_order(
        order,
        "rental_finished",
        payload={"source": source},
        status_after=str(order.get("status") or "success"),
        number_mode="rental",
    )
    refreshed = await get_order(_order_id(order)) or {**order, **patch}
    return {"ok": True, "message": "Rental finished.", "order": public_order_payload(refreshed)}


async def renew_rental_order(*, order: dict[str, Any], user_id: int, idempotency_key: str, source: str = "numbers_api") -> dict[str, Any]:
    order = _ensure_rental_order(order)
    if not idempotency_key:
        raise NumbersOrderError("missing_idempotency_key", "Idempotency-Key is required for rental renewals.", status=400)
    cached = await _idempotency_get(
        user_id=int(user_id),
        order_id=_order_id(order),
        key=idempotency_key,
        operation="rental_renew",
    )
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    _ensure_open_rental_order(order)
    if not bool(order.get("rental_is_renewable")):
        raise NumbersOrderError("renew_not_supported", "Renew is not supported for this rental.", status=409)
    provider, provider_order_id = _provider_fields(order)

    try:
        renew_res = await renew_rental_from_provider(provider, provider_order_id)
        ok = bool((renew_res or {}).get("success"))
    except Exception:
        renew_res = {"success": False}
        ok = False

    if not ok:
        await _log_number_event_from_order(order, "rental_renew_failed", payload={"source": source}, number_mode="rental")
        raise NumbersOrderError("renew_failed", "Could not renew this rental right now.", status=409)

    patch = {"rental_last_renew_at": _utc_now(), "rental_last_renew_raw": (renew_res or {}).get("raw")}
    await update_order_details(_order_id(order), patch)
    await _log_number_event_from_order(
        order,
        "rental_renewed",
        payload={"source": source},
        number_mode="rental",
    )
    refreshed = await get_order(_order_id(order)) or {**order, **patch}
    response = {"ok": True, "message": "Rental renewed.", "order": public_order_payload(refreshed)}
    await _idempotency_save(
        user_id=int(user_id),
        order_id=_order_id(order),
        key=idempotency_key,
        operation="rental_renew",
        response=response,
    )
    return response


async def wake_rental_order(order: dict[str, Any], *, source: str = "numbers_api") -> dict[str, Any]:
    order = _ensure_rental_order(order)
    _ensure_open_rental_order(order)
    provider, provider_order_id = _provider_fields(order)

    try:
        wake_res = await wake_rental_from_provider(provider, provider_order_id)
        ok = bool((wake_res or {}).get("success"))
    except Exception:
        wake_res = {"success": False}
        ok = False

    if not ok:
        await _log_number_event_from_order(order, "rental_wake_failed", payload={"source": source}, number_mode="rental")
        raise NumbersOrderError("wake_failed", "Could not wake this rental right now.", status=409)

    patch = {"rental_last_wake_at": _utc_now(), "rental_last_wake_raw": (wake_res or {}).get("raw")}
    await update_order_details(_order_id(order), patch)
    await _log_number_event_from_order(
        order,
        "rental_wake_ok",
        payload={"source": source},
        number_mode="rental",
    )
    refreshed = await get_order(_order_id(order)) or {**order, **patch}
    return {"ok": True, "message": "Rental wake requested.", "order": public_order_payload(refreshed)}


async def rental_notes_state(order: dict[str, Any], *, source: str = "numbers_api") -> dict[str, Any]:
    order = _ensure_rental_order(order)
    _ensure_open_rental_order(order)
    provider, provider_order_id = _provider_fields(order)

    try:
        data = await notes_tags_from_provider(provider, provider_order_id)
    except Exception:
        data = {"success": False}
    if not bool((data or {}).get("success")):
        raise NumbersOrderError("notes_not_supported", "Notes and tags are not available for this rental.", status=409)

    notes = str((data or {}).get("notes") or "")
    tags = [str(item) for item in ((data or {}).get("tags") or []) if str(item or "").strip()]
    patch = {"rental_notes": notes, "rental_tags": tags[:20], "rental_notes_tags_fetched_at": _utc_now()}
    await update_order_details(_order_id(order), patch)
    await _log_number_event_from_order(
        order,
        "rental_notes_tags_fetched",
        payload={"source": source, "tags_count": len(tags), "has_notes": bool(notes)},
        number_mode="rental",
    )
    refreshed = await get_order(_order_id(order)) or {**order, **patch}
    return {
        "ok": True,
        "message": "Notes and tags loaded.",
        "notes": notes,
        "tags": tags[:20],
        "order": public_order_payload(refreshed),
    }
