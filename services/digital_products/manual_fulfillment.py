from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from database.orders_repo import update_order_details
from services.digital_products.catalog_service import digital_provider_enabled
from services.digital_products.fulfillment_rules import MANUAL_TOPUP_MODE
from services.digital_products.g2bulk_client import G2BulkClient
from services.digital_products.mangerr_client import MangerrClient
from services.digital_products.smart_routing import ROUTE_AUTO_API, ROUTE_FUTURE, ROUTE_MANUAL_REVIEW
from services.digital_products.za3em_client import Za3emClient

_TWOPLACES = Decimal("0.01")


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def provider_ok(resp: dict[str, Any]) -> bool:
    status = int(resp.get("status") or 0)
    data = resp.get("data")
    if status < 200 or status >= 300:
        return False
    if isinstance(data, dict):
        success = data.get("success")
        if success in {False, 0, "0", "false", "False"}:
            return False
        if str(data.get("status") or "").strip().lower() in {"error", "failed", "fail"}:
            return False
        if any(str(data.get(k) or "").strip() for k in ("error", "error_message", "error_msg")):
            return False
    return True


def extract_provider_error(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("error", "message", "msg", "error_message", "error_msg"):
            raw = str(payload.get(key) or "").strip()
            if raw:
                return raw[:200]
        nested = payload.get("data")
        if isinstance(nested, dict):
            for key in ("error", "message", "msg", "error_message", "error_msg"):
                raw = str(nested.get(key) or "").strip()
                if raw:
                    return raw[:200]
    if isinstance(payload, str) and payload.strip():
        return payload.strip()[:200]
    return "Provider request failed."


def extract_external_order_id(payload: Any) -> str:
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            for row in list(payload.get("data") or []):
                if not isinstance(row, dict):
                    continue
                raw = str(row.get("order_id") or row.get("id") or "").strip()
                if raw:
                    return raw
        for key in ("order_id", "id", "invoice_id", "reference", "ref"):
            raw = str(payload.get(key) or "").strip()
            if raw:
                return raw
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("order_id", "id", "invoice_id", "reference", "ref"):
                raw = str(data.get(key) or "").strip()
                if raw:
                    return raw
    return ""


def extract_voucher_lines(payload: Any) -> list[str]:
    lines: list[str] = []
    candidates: list[Any] = []
    if isinstance(payload, dict):
        candidates.extend(
            [
                payload.get("code"),
                payload.get("pin"),
                payload.get("voucher"),
                payload.get("voucher_code"),
                payload.get("delivery_items"),
                payload.get("cards"),
                payload.get("vouchers"),
                payload.get("codes"),
                payload.get("data"),
                payload.get("delivery_response"),
            ]
        )
    for item in candidates:
        if isinstance(item, str) and item.strip():
            lines.append(item.strip())
        elif isinstance(item, dict):
            if isinstance(item.get("data"), dict):
                candidates.append(item.get("data"))
            for nested_key in ("delivery_items", "cards", "vouchers", "codes"):
                if nested_key in item:
                    candidates.append(item.get(nested_key))
            for key in ("code", "pin", "voucher", "serial", "account", "password"):
                raw = str(item.get(key) or "").strip()
                if raw:
                    lines.append(f"{key.title()}: {raw}")
        elif isinstance(item, list):
            for row in item:
                if isinstance(row, str) and row.strip():
                    lines.append(row.strip())
                elif isinstance(row, dict):
                    parts: list[str] = []
                    for key in ("code", "pin", "voucher", "serial", "account", "password"):
                        raw = str(row.get(key) or "").strip()
                        if raw:
                            parts.append(f"{key.title()}: {raw}")
                    if parts:
                        lines.append(" | ".join(parts))
    unique: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        unique.append(line)
    return unique[:5]


def _available_attempted_offers(order: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in list((order or {}).get("provider_offers_attempted") or [])
        if isinstance(row, dict)
        and bool(row.get("available", True))
        and digital_provider_enabled(str(row.get("provider") or ""))
    ]


def select_auto_api_offer(order: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in _available_attempted_offers(order):
        if str(row.get("fulfillment_mode") or "").strip() == MANUAL_TOPUP_MODE:
            continue
        if str(row.get("source_url") or "").strip():
            continue
        if str(row.get("ref_id") or row.get("provider_ref_id") or "").strip():
            candidates.append(row)
    candidates.sort(key=lambda item: float(_money(item.get("price") or 0)) if _money(item.get("price") or 0) > 0 else 9999999)
    return dict(candidates[0]) if candidates else {}


def select_future_offer(order: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in _available_attempted_offers(order):
        provider = str(row.get("provider") or "").strip().lower()
        source = str(row.get("source") or "").strip().lower()
        source_name = str(row.get("source_product_name") or "").strip().lower()
        if provider != "g2bulk":
            continue
        if source != "future" and "future" not in source_name:
            continue
        if str(row.get("ref_id") or row.get("provider_ref_id") or "").strip():
            candidates.append(row)
    candidates.sort(key=lambda item: float(_money(item.get("price") or 0)) if _money(item.get("price") or 0) > 0 else 9999999)
    return dict(candidates[0]) if candidates else {}


async def create_provider_game_order(
    *,
    provider: str,
    ref_id: str,
    game_id: str,
    player_id: str,
    server_id: str | None,
    catalogue_name: str,
) -> dict[str, Any]:
    p = str(provider or "").strip().lower()
    if not digital_provider_enabled(p):
        return {"status": 0, "data": {"status": "ERROR", "msg": "PROVIDER_DISABLED"}}
    if p == "za3em":
        client = Za3emClient()
        return await client.create_order(
            product_id=ref_id,
            quantity=1,
            order_uuid=uuid4().hex,
            player_id=player_id,
            server_id=server_id or None,
        )
    if p == "mangerr":
        extra_params: dict[str, Any] = {}
        if str(server_id or "").strip():
            extra_params["serverId"] = str(server_id).strip()
        client = MangerrClient()
        return await client.create_order(
            product_id=ref_id,
            quantity=1,
            order_uuid=uuid4().hex,
            player_id=player_id,
            extra_params=extra_params,
        )
    client = G2BulkClient()
    return await client.create_topup_order(
        product_id=ref_id,
        player_id=player_id,
        server_id=server_id or None,
        quantity=1,
        game_code=game_id,
        catalogue_name=catalogue_name,
    )


async def create_provider_gift_order(*, provider: str, ref_id: str, quantity: int = 1) -> dict[str, Any]:
    p = str(provider or "").strip().lower()
    if not digital_provider_enabled(p):
        return {"status": 0, "data": {"status": "ERROR", "msg": "PROVIDER_DISABLED"}}
    if p == "za3em":
        client = Za3emClient()
        return await client.create_order(product_id=ref_id, quantity=max(1, int(quantity or 1)), order_uuid=uuid4().hex)
    client = G2BulkClient()
    return await client.create_voucher_order(product_id=ref_id, quantity=max(1, int(quantity or 1)))


def _order_sale_amount(order: dict[str, Any]) -> Decimal:
    for key in ("retail_amount", "sale_price", "amount"):
        amount = _money((order or {}).get(key))
        if amount > 0:
            return amount
    return Decimal("0.00")


def _candidate_cost(candidate: dict[str, Any]) -> Decimal:
    return _money((candidate or {}).get("cost_price") or (candidate or {}).get("price") or 0)


def _routing_attempt_row(candidate: dict[str, Any], *, status: str, response: Any = None, error: str = "") -> dict[str, Any]:
    row = {
        "provider": str((candidate or {}).get("provider") or "").strip().lower(),
        "route": str((candidate or {}).get("route") or "").strip(),
        "ref_id": str((candidate or {}).get("ref_id") or (candidate or {}).get("provider_ref_id") or "").strip(),
        "cost_price": float(_candidate_cost(candidate)),
        "compare_key": str((candidate or {}).get("compare_key") or "").strip(),
        "status": status,
        "attempted_at": datetime.now(UTC),
    }
    if error:
        row["error"] = str(error)[:300]
    if response is not None:
        row["provider_response"] = response
    return row


async def execute_smart_game_routing(order: dict[str, Any], *, actor_id: int) -> dict[str, Any]:
    candidates = [
        dict(row)
        for row in list((order or {}).get("routing_candidates") or [])
        if isinstance(row, dict)
    ]
    sale_price = _order_sale_amount(order)
    attempts: list[dict[str, Any]] = []
    last_error = ""
    if not candidates:
        last_error = "No smart routing candidates."

    for candidate in candidates:
        provider = str(candidate.get("provider") or "").strip().lower()
        route = str(candidate.get("route") or "").strip().lower()
        ref_id = str(candidate.get("ref_id") or candidate.get("provider_ref_id") or "").strip()
        cost_price = _candidate_cost(candidate)
        if not provider or not ref_id or route not in {ROUTE_AUTO_API, ROUTE_FUTURE}:
            last_error = "Invalid routing candidate."
            attempts.append(_routing_attempt_row(candidate, status="skipped_invalid", error=last_error))
            continue
        if cost_price <= 0:
            last_error = "Invalid candidate cost."
            attempts.append(_routing_attempt_row(candidate, status="skipped_invalid_cost", error=last_error))
            continue
        if sale_price > 0 and cost_price > sale_price:
            last_error = "Candidate cost exceeds sale price."
            attempts.append(_routing_attempt_row(candidate, status="skipped_unprofitable", error=last_error))
            continue

        now = datetime.now(UTC)
        await update_order_details(
            order["_id"],
            {
                "manual_execution_route": route,
                "manual_fulfillment_status": f"{route}_submitting",
                "manual_route_updated_by": int(actor_id),
                "manual_route_updated_at": now,
                "selected_routing_candidate": candidate,
                "selected_provider_offer": candidate,
                "provider_code": provider,
                "provider_ref_id": ref_id,
                "routing_attempts": attempts,
            },
        )

        if route == ROUTE_FUTURE:
            attempt = await create_provider_gift_order(provider=provider, ref_id=ref_id, quantity=max(1, int(candidate.get("quantity") or 1)))
        else:
            game_id = str(candidate.get("game_id") or order.get("game_id") or "").strip()
            player_id = str(order.get("player_id") or "").strip()
            server_id = str(order.get("server_id") or "").strip()
            catalogue_name = str(candidate.get("catalogue_name") or order.get("manual_item_name") or order.get("service_ref_id") or "Digital top-up")
            if not (game_id and player_id):
                last_error = "Missing API execution data."
                attempts.append(_routing_attempt_row(candidate, status="failed", error=last_error))
                continue
            attempt = await create_provider_game_order(
                provider=provider,
                ref_id=ref_id,
                game_id=game_id,
                player_id=player_id,
                server_id=server_id or None,
                catalogue_name=catalogue_name,
            )

        provider_data = attempt.get("data") if isinstance(attempt, dict) else attempt
        ok = provider_ok(attempt if isinstance(attempt, dict) else {})
        external_order_id = extract_external_order_id(provider_data)
        voucher_lines = extract_voucher_lines(provider_data) if route == ROUTE_FUTURE else []
        attempts.append(_routing_attempt_row(candidate, status="success" if ok else "failed", response=attempt, error="" if ok else extract_provider_error(provider_data)))
        if not ok:
            last_error = extract_provider_error(provider_data)
            continue

        patch: dict[str, Any] = {
            "provider_response": attempt,
            "provider_order_id": external_order_id,
            "manual_execution_route": route,
            "manual_fulfillment_status": "processing",
            "manual_route_updated_by": int(actor_id),
            "manual_route_updated_at": datetime.now(UTC),
            "selected_routing_candidate": candidate,
            "selected_provider_offer": candidate,
            "provider_code": provider,
            "provider_ref_id": ref_id,
            "routing_attempts": attempts,
        }
        if voucher_lines:
            patch["delivery_lines_private"] = voucher_lines
        await update_order_details(order["_id"], patch)
        return {
            "ok": True,
            "code": "smart_route_submitted",
            "route": route,
            "provider_order_id": external_order_id,
            "delivery_lines_private": voucher_lines,
            "provider_response": attempt,
            "patch": patch,
            "offer": candidate,
            "attempts": attempts,
        }

    patch = {
        "manual_execution_route": ROUTE_MANUAL_REVIEW,
        "manual_fulfillment_status": "pending",
        "manual_route_updated_by": int(actor_id),
        "manual_route_updated_at": datetime.now(UTC),
        "provider_response": {"status": "manual_review", "source": "smart_routing", "reason": last_error or "No profitable route succeeded."},
        "provider_error": last_error or "No profitable route succeeded.",
        "routing_attempts": attempts,
    }
    await update_order_details(order["_id"], patch)
    return {
        "ok": False,
        "code": "smart_route_manual_review",
        "route": ROUTE_MANUAL_REVIEW,
        "message": last_error or "No profitable route succeeded.",
        "patch": patch,
        "attempts": attempts,
    }


async def submit_manual_auto_api(order: dict[str, Any], *, actor_id: int) -> dict[str, Any]:
    offer = select_auto_api_offer(order)
    if not offer:
        return {"ok": False, "code": "no_auto_api_option", "message": "No Auto API option for this order."}

    provider = str(offer.get("provider") or order.get("provider_code") or "g2bulk").strip().lower()
    ref_id = str(offer.get("ref_id") or offer.get("provider_ref_id") or order.get("provider_ref_id") or "").strip()
    game_id = str(order.get("game_id") or "").strip()
    player_id = str(order.get("player_id") or "").strip()
    server_id = str(order.get("server_id") or "").strip()
    item_name = str(order.get("manual_item_name") or order.get("service_ref_id") or "Digital top-up")
    if not (provider and ref_id and game_id and player_id):
        return {"ok": False, "code": "missing_api_execution_data", "message": "Order is missing API execution data."}

    now = datetime.now(UTC)
    await update_order_details(
        order["_id"],
        {
            "manual_execution_route": "auto_api",
            "manual_fulfillment_status": "auto_api_submitting",
            "manual_route_updated_by": int(actor_id),
            "manual_route_updated_at": now,
            "selected_provider_offer": offer,
            "provider_code": provider,
            "provider_ref_id": ref_id,
        },
    )
    attempt = await create_provider_game_order(
        provider=provider,
        ref_id=ref_id,
        game_id=game_id,
        player_id=player_id,
        server_id=server_id or None,
        catalogue_name=item_name,
    )
    provider_data = attempt.get("data") if isinstance(attempt, dict) else attempt
    external_order_id = extract_external_order_id(provider_data)
    ok = provider_ok(attempt)
    patch: dict[str, Any] = {
        "provider_response": attempt,
        "provider_order_id": external_order_id,
        "manual_execution_route": "auto_api",
        "manual_fulfillment_status": "processing" if ok else "auto_api_failed",
        "manual_route_updated_by": int(actor_id),
        "manual_route_updated_at": datetime.now(UTC),
        "selected_provider_offer": offer,
        "provider_code": provider,
        "provider_ref_id": ref_id,
    }
    if not ok:
        patch["provider_error"] = extract_provider_error(provider_data)
    await update_order_details(order["_id"], patch)
    return {
        "ok": ok,
        "code": "auto_api_submitted" if ok else "auto_api_failed",
        "provider_order_id": external_order_id,
        "provider_response": attempt,
        "patch": patch,
        "offer": offer,
    }


async def submit_manual_future(order: dict[str, Any], *, actor_id: int) -> dict[str, Any]:
    offer = select_future_offer(order)
    if not offer:
        return {"ok": False, "code": "no_future_option", "message": "No Future option for this order."}
    ref_id = str(offer.get("ref_id") or offer.get("provider_ref_id") or "").strip()
    if not ref_id:
        return {"ok": False, "code": "missing_future_ref", "message": "Future option is missing provider ref."}

    now = datetime.now(UTC)
    await update_order_details(
        order["_id"],
        {
            "manual_execution_route": "future",
            "manual_fulfillment_status": "future_submitting",
            "manual_route_updated_by": int(actor_id),
            "manual_route_updated_at": now,
            "selected_provider_offer": offer,
            "provider_code": "g2bulk",
            "provider_ref_id": ref_id,
        },
    )
    attempt = await create_provider_gift_order(provider="g2bulk", ref_id=ref_id, quantity=1)
    provider_data = attempt.get("data") if isinstance(attempt, dict) else attempt
    external_order_id = extract_external_order_id(provider_data)
    voucher_lines = extract_voucher_lines(provider_data)
    ok = provider_ok(attempt)
    patch: dict[str, Any] = {
        "provider_response": attempt,
        "provider_order_id": external_order_id,
        "delivery_lines_private": voucher_lines,
        "manual_execution_route": "future",
        "manual_fulfillment_status": "processing" if ok else "future_failed",
        "manual_route_updated_by": int(actor_id),
        "manual_route_updated_at": datetime.now(UTC),
        "selected_provider_offer": offer,
        "provider_code": "g2bulk",
        "provider_ref_id": ref_id,
    }
    if not ok:
        patch["provider_error"] = extract_provider_error(provider_data)
    await update_order_details(order["_id"], patch)
    return {
        "ok": ok,
        "code": "future_submitted" if ok else "future_failed",
        "provider_order_id": external_order_id,
        "delivery_lines_private": voucher_lines,
        "provider_response": attempt,
        "patch": patch,
        "offer": offer,
    }
