"""Shared provider I/O helpers for temporary Numbers orders."""

from typing import Any

from services.numbers.provider_delivery import provider_sms_polling_enabled


def normalize_provider_sms_result(result: Any) -> dict:
    if not isinstance(result, dict):
        return {"success": False, "messages": [], "raw": result}
    normalized = dict(result)
    messages = normalized.get("messages")
    if messages in (None, ""):
        normalized["messages"] = []
    elif isinstance(messages, (list, tuple, set)):
        normalized["messages"] = [str(item) for item in messages if str(item or "").strip()]
    else:
        normalized["messages"] = [str(messages)]
    normalized["success"] = bool(normalized.get("success"))
    return normalized


async def fetch_provider_sms(
    providers: dict[str, Any],
    provider_code: str,
    provider_order_id: str,
    *,
    force: bool = False,
) -> dict:
    if not force and not provider_sms_polling_enabled(provider_code):
        return {
            "success": True,
            "messages": [],
            "raw": "provider_sms_polling_disabled_waiting_for_webhook",
            "polling_disabled": True,
        }
    prov = providers.get(str(provider_code or "").lower())
    if not prov:
        return {"success": False, "messages": [], "raw": "provider_not_found"}
    if not hasattr(prov, "get_sms"):
        return {"success": False, "messages": [], "raw": "get_sms_not_supported"}
    try:
        return normalize_provider_sms_result(await prov.get_sms(provider_order_id))
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
