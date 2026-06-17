"""Website eSIM purchase — charge the wallet, provision via EsimAccess, deliver QR.

Ported from the proven bot flow (handlers/store_sections.py `esim:buy`) onto the
website's own financial primitives so customers can buy eSIMs on phantom-app.net.

Fail-safe by design: returns a clear error when the provider isn't configured,
and **refunds** on any provisioning failure. When the provider accepts the order
but the profile isn't ready yet, the order is left "paid" + flagged for manual
delivery (the same behaviour as the bot).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from config import settings
from database.financial_ledger import create_order_v3
from database.notifications_repo import notify_customer
from database.orders_repo import update_order_details, update_order_status
from services.digital_products.esim_access_client import EsimAccessClient
from utils.financial_manager import FinancialManager

logger = logging.getLogger("esim_web")


def _money(value: Any) -> float:
    return round(float(value or 0.0) + 1e-9, 4)


def esim_price_to_units(price_usd: float) -> int:
    return int(round(float(price_usd or 0.0) * 10000))


def esim_provider_configured() -> bool:
    return bool(getattr(settings, "esim_access_code", "") and getattr(settings, "esim_access_secret_key", ""))


def esim_service_ref(offer: dict[str, Any]) -> str:
    refs: list[str] = []
    for part in offer.get("parts") or []:
        plan = dict(part.get("plan") or {})
        ref = str(plan.get("slug") or plan.get("package_code") or plan.get("code") or part.get("country") or part.get("region_name") or "").strip()
        if ref:
            refs.append(ref)
    return "esim:" + "|".join(refs)


def esim_package_info_list(offer: dict[str, Any], *, days: int) -> list[dict[str, Any]]:
    package_info_list: list[dict[str, Any]] = []
    for part in offer.get("parts") or []:
        plan = dict(part.get("plan") or {})
        package_code = str(plan.get("package_code") or plan.get("code") or plan.get("slug") or "").strip()
        if not package_code:
            continue
        row: dict[str, Any] = {"count": 1, "packageCode": package_code}
        row["price"] = esim_price_to_units(float(plan.get("_cost_price_usd") or plan.get("price_usd") or 0.0))
        if int(plan.get("data_type_code") or 0) in {2, 3, 4}:
            row["periodNum"] = int(days)
        package_info_list.append(row)
    return package_info_list


def esim_extract_profiles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    obj = payload.get("obj")
    if isinstance(obj, dict):
        value = obj.get("esimList")
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


async def esim_query_profiles_wait(
    client: EsimAccessClient, *, order_no: str, attempts: int = 6, delay_sec: float = 5.0
) -> dict[str, Any] | None:
    last_resp: dict[str, Any] | None = None
    for attempt in range(max(1, int(attempts))):
        last_resp = await client.query_profiles(order_no=order_no, page_num=1, page_size=50)
        if bool(last_resp.get("success")):
            return last_resp
        if str(last_resp.get("errorCode") or "").strip() != "200010":  # 200010 = still preparing
            return last_resp
        if attempt < attempts - 1:
            await asyncio.sleep(max(0.0, float(delay_sec)))
    return last_resp


def _public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "iccid": str(profile.get("iccid") or "").strip(),
        "qr": str(profile.get("qrCodeUrl") or "").strip(),
        "ac": str(profile.get("ac") or "").strip(),
    }


async def purchase_esim_offer(
    *, user_id: int, reseller_id: int, offer: dict[str, Any], days: int
) -> dict[str, Any]:
    """Charge → provision → deliver. Returns {ok, status|code, order_id, profiles?}."""
    if not esim_provider_configured():
        return {"ok": False, "code": "esim_not_configured", "message": "eSIM provider is not configured yet."}
    cost_price = _money(offer.get("_cost_price_usd") or offer.get("price_usd") or 0.0)
    sale_price = _money(offer.get("price_usd") or 0.0)
    if sale_price <= 0:
        return {"ok": False, "code": "invalid_offer", "message": "Invalid eSIM offer price."}
    package_info_list = esim_package_info_list(offer, days=int(days))
    if not package_info_list:
        return {"ok": False, "code": "invalid_offer", "message": "Invalid eSIM package data."}

    order = await create_order_v3(
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        service_type="core_digital_products",
        service_ref_id=esim_service_ref(offer),
        retail_amount=sale_price,
        wholesale_amount=cost_price,
        reseller_profit_amount=0.0,
        status="pending",
    )
    order_id = order.get("_id")
    ok, reason = await FinancialManager.process_core_purchase(
        user_id=int(user_id), order_id=order_id, sale_price=sale_price, cost_price=cost_price, reseller_id=int(reseller_id)
    )
    if not ok:
        await update_order_status(order_id, "failed")
        return {"ok": False, "code": "charge_failed", "message": str(reason or "purchase_failed")}
    await update_order_status(order_id, "paid")

    client = EsimAccessClient()
    try:
        provider_resp = await client.order_profiles(
            transaction_id=f"esim-{uuid4().hex}",
            amount=esim_price_to_units(cost_price),
            package_info_list=package_info_list,
        )
    except Exception as exc:  # noqa: BLE001 - any provider error -> refund below
        logger.warning("esim order_profiles raised: %s", exc)
        provider_resp = {"success": False, "errorMessage": str(exc)[:200]}

    if not bool(provider_resp.get("success")):
        await FinancialManager.refund_core_purchase(
            user_id=int(user_id), order_id=order_id, sale_price=sale_price, cost_price=cost_price, reseller_id=int(reseller_id)
        )
        await update_order_status(order_id, "refunded")
        await update_order_details(order_id, {"provider_response": provider_resp, "provider_error": str(provider_resp.get("errorMessage") or "esim_order_failed")})
        return {"ok": False, "code": "provider_failed", "message": "eSIM purchase failed and the amount was refunded.", "order_id": str(order_id)}

    obj = provider_resp.get("obj") if isinstance(provider_resp.get("obj"), dict) else {}
    order_no = str((obj or {}).get("orderNo") or "").strip()
    await update_order_details(
        order_id,
        {
            "provider_code": "esim_access",
            "provider_order_id": order_no,
            "provider_response": provider_resp,
            "number_mode": "digital_products",
            "delivery_type": "esim",
            "manual_item_name": esim_service_ref(offer),
        },
    )

    query_resp = await esim_query_profiles_wait(client, order_no=order_no) if order_no else None
    profiles = esim_extract_profiles(query_resp or {})
    if not profiles:
        await update_order_details(order_id, {"provider_status_response": query_resp, "provider_manual_review_required": True})
        await update_order_status(order_id, "paid")
        await notify_customer(int(user_id), kind="order", title="طلب eSIM قيد التجهيز", body="سيتم تسليم الشريحة بعد قليل.", link="/app/orders", meta={"order_id": str(order_id)})
        return {"ok": True, "status": "preparing", "order_id": str(order_id), "profiles": []}

    await update_order_details(order_id, {"provider_status_response": query_resp, "delivery_profiles": profiles})
    await update_order_status(order_id, "success")
    await notify_customer(int(user_id), kind="order", title="eSIM جاهزة ✅", body="تم تسليم شريحتك بنجاح.", link="/app/orders", meta={"order_id": str(order_id)})
    return {"ok": True, "status": "delivered", "order_id": str(order_id), "profiles": [_public_profile(p) for p in profiles]}
