from __future__ import annotations

from typing import Any

from database.reseller_settings_repo import get_exchange_routing, get_payment_methods, get_recharge_routing
from utils.translations import t


def _is_placeholder_target(value: str | None) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return True
    upper = raw.upper()
    if upper.startswith("SET_"):
        return True
    if "YOUR_" in upper:
        return True
    return False


async def get_reseller_setup_status(reseller_id: int) -> dict[str, Any]:
    rid = int(reseller_id)
    methods = await get_payment_methods(rid)
    enabled_methods = [m for m in methods if bool(m.get("enabled", True))]
    configured_enabled_methods = [m for m in enabled_methods if not _is_placeholder_target(m.get("target"))]
    has_configured_payment_method = bool(configured_enabled_methods)
    payment_methods_ready = has_configured_payment_method
    unconfigured_enabled_methods_count = max(0, len(enabled_methods) - len(configured_enabled_methods))

    payment_routing = await get_recharge_routing(rid)
    exchange_routing = await get_exchange_routing(rid)
    payment_routing_ok = bool(isinstance(payment_routing, dict) and payment_routing.get("chat_id") is not None)
    exchange_routing_ok = bool(isinstance(exchange_routing, dict) and exchange_routing.get("chat_id") is not None)
    topics_enabled = bool(
        (isinstance(payment_routing, dict) and payment_routing.get("message_thread_id") is not None)
        or (isinstance(exchange_routing, dict) and exchange_routing.get("message_thread_id") is not None)
    )
    has_private_group = payment_routing_ok

    return {
        "ready": bool(payment_methods_ready),
        "has_payment_method": payment_methods_ready,
        "has_configured_payment_method": has_configured_payment_method,
        "payment_methods_ready": payment_methods_ready,
        "payment_delivery_ready": True,
        "has_private_group": has_private_group,
        "payment_routing_ok": payment_routing_ok,
        "exchange_routing_ok": exchange_routing_ok,
        "group_ready": has_private_group,
        "topics_enabled": topics_enabled,
        "configured_methods_count": len(configured_enabled_methods),
        "enabled_methods_count": len(enabled_methods),
        "unconfigured_enabled_methods_count": unconfigured_enabled_methods_count,
        "total_methods_count": len(methods or []),
    }


def render_reseller_setup_notice(lang: str, status: dict[str, Any]) -> str:
    ok = "✅"
    no = "❌"
    mark_pay = ok if bool(status.get("payment_methods_ready")) else no
    mark_group = ok if bool(status.get("payment_delivery_ready", True)) else no

    is_ar = str(lang or "").lower().startswith("ar")
    payment_delivery_label = (
        "استلام طلبات الدفع"
        if is_ar
        else "Payment request delivery"
    )
    payment_delivery_mode = (
        ("توبيك/غروب" if bool(status.get("payment_routing_ok")) else "رسائل خاصة")
        if is_ar
        else ("Topic/Group" if bool(status.get("payment_routing_ok")) else "DM fallback")
    )
    if is_ar:
        setup_steps = (
            "الحد الأدنى للتشغيل:\n"
            "1) افتح الإعدادات > وسائل الدفع.\n"
            "2) اختر وسيلة واحدة تريد استقبال الأموال عليها.\n"
            "3) اكتب الرقم أو عنوان المحفظة في Payment Address/Target.\n"
            "4) عطّل الوسائل التي لا تريد استخدامها الآن، أو اتركها وعدّلها لاحقًا.\n\n"
            "الغروب والتوبيكات اختيارية. إذا لم تربط غروب، تصل طلبات الشحن إلى رسائلك الخاصة."
        )
    else:
        setup_steps = (
            "Minimum setup:\n"
            "1) Open Settings > Payment Methods.\n"
            "2) Pick one method you want to receive money on.\n"
            "3) Set its Payment Address/Target to your real number or wallet.\n"
            "4) Disable unused methods now, or leave them for later.\n\n"
            "Groups and topics are optional. Without a group, recharge requests go to your DM."
        )

    details: list[str] = []
    if not bool(status.get("has_configured_payment_method")):
        details.append(t(lang, "reseller_setup_missing_payment_method"))
    elif not bool(status.get("payment_methods_ready")):
        details.append(
            t(lang, "reseller_setup_disable_unused_methods").format(
                enabled_count=int(status.get("enabled_methods_count", 0) or 0),
                configured_count=int(status.get("configured_methods_count", 0) or 0),
            )
        )
    if int(status.get("unconfigured_enabled_methods_count", 0) or 0) > 0:
        if is_ar:
            details.append("بعض وسائل الدفع المفعّلة ما زالت بدون رقم/محفظة. البوت يعمل إذا توجد وسيلة واحدة جاهزة، لكن الأفضل تعطيل غير المستخدم.")
        else:
            details.append("Some enabled payment methods still have placeholder targets. The bot can run with one ready method, but disabling unused methods is cleaner.")

    notice = (
        f"{t(lang, 'reseller_setup_required_title')}\n\n"
        f"{t(lang, 'reseller_setup_required_intro')}\n\n"
        f"{mark_pay} {t(lang, 'reseller_setup_check_payment')}\n"
        f"{mark_group} {payment_delivery_label} ({payment_delivery_mode})\n\n"
        f"{t(lang, 'reseller_setup_action')}\n\n"
        f"{setup_steps}"
    )
    if details:
        notice = f"{notice}\n\n" + "\n".join(f"• {line}" for line in details)
    return notice
