"""Shared provider I/O helpers for temporary Numbers orders."""

from typing import Any


async def fetch_provider_sms(providers: dict[str, Any], provider_code: str, provider_order_id: str) -> dict:
    prov = providers.get(str(provider_code or "").lower())
    if not prov:
        return {"success": False, "messages": [], "raw": "provider_not_found"}
    if not hasattr(prov, "get_sms"):
        return {"success": False, "messages": [], "raw": "get_sms_not_supported"}
    try:
        return await prov.get_sms(provider_order_id)
    except Exception as exc:
        return {"success": False, "messages": [], "raw": str(exc)}


async def provider_resend(providers: dict[str, Any], provider_code: str, provider_order_id: str) -> dict:
    prov = providers.get(str(provider_code or "").lower())
    if not prov:
        return {"success": False}
    if str(provider_code or "").lower() == "smspool":
        return {"success": True, "order_id": provider_order_id}
    if hasattr(prov, "resend"):
        try:
            res = await prov.resend(provider_order_id)
            if isinstance(res, dict):
                ok = bool(res.get("success"))
                if not ok:
                    return {"success": False}
                out = {"success": True, "order_id": str(res.get("order_id") or provider_order_id)}
                number = str(res.get("number") or "").strip()
                if number:
                    out["number"] = number
                return out
            if bool(res):
                return {"success": True, "order_id": provider_order_id}
            return {"success": False}
        except Exception:
            return {"success": False}
    return {"success": False}
