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
    payment_methods_ready = bool(enabled_methods) and len(configured_enabled_methods) == len(enabled_methods)

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
        "ready": bool(payment_methods_ready and payment_routing_ok),
        "has_payment_method": payment_methods_ready,
        "has_configured_payment_method": has_configured_payment_method,
        "payment_methods_ready": payment_methods_ready,
        "has_private_group": has_private_group,
        "payment_routing_ok": payment_routing_ok,
        "exchange_routing_ok": exchange_routing_ok,
        "group_ready": has_private_group,
        "topics_enabled": topics_enabled,
        "configured_methods_count": len(configured_enabled_methods),
        "enabled_methods_count": len(enabled_methods),
        "total_methods_count": len(methods or []),
    }


def render_reseller_setup_notice(lang: str, status: dict[str, Any]) -> str:
    ok = "✅"
    no = "❌"
    mark_pay = ok if bool(status.get("payment_methods_ready")) else no
    mark_group = ok if bool(status.get("payment_routing_ok")) else no

    is_ar = str(lang or "").lower().startswith("ar")
    if is_ar:
        setup_steps = (
            "خطوات إعداد الغروب:\n"
            "1) أنشئ غروب خاص للدفعات.\n"
            "2) فعّل Topics من إعدادات الغروب.\n"
            "3) أضف البوت كأدمن بصلاحيات:\n"
            "   • إرسال الرسائل\n"
            "   • إدارة المواضيع (Manage Topics)\n"
            "4) من إعدادات الريسيلر استخدم Auto Setup Topics\n"
            "   أو اربط Payment Topic يدويًا."
        )
    else:
        setup_steps = (
            "Group setup steps:\n"
            "1) Create a private payment group.\n"
            "2) Enable Topics in group settings.\n"
            "3) Add the bot as admin with permissions:\n"
            "   • Send messages\n"
            "   • Manage Topics\n"
            "4) From Reseller Settings use Auto Setup Topics\n"
            "   or bind Payment Topic manually."
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
    if not bool(status.get("payment_routing_ok")):
        details.append(t(lang, "reseller_setup_missing_payment_routing"))

    notice = (
        f"{t(lang, 'reseller_setup_required_title')}\n\n"
        f"{t(lang, 'reseller_setup_required_intro')}\n\n"
        f"{mark_pay} {t(lang, 'reseller_setup_check_payment')}\n"
        f"{mark_group} {t(lang, 'reseller_setup_check_group')}\n\n"
        f"{t(lang, 'reseller_setup_action')}\n\n"
        f"{setup_steps}"
    )
    if details:
        notice = f"{notice}\n\n" + "\n".join(f"• {line}" for line in details)
    return notice
