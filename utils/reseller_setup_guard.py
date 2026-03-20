from __future__ import annotations

from typing import Any

from database.reseller_settings_repo import get_payment_methods, get_recharge_routing
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
    configured_methods = [m for m in methods if not _is_placeholder_target(m.get("target"))]
    has_payment_method = bool(configured_methods)

    routing = await get_recharge_routing(rid)
    has_private_group = bool(isinstance(routing, dict) and routing.get("chat_id") is not None)

    return {
        "ready": bool(has_payment_method and has_private_group),
        "has_payment_method": has_payment_method,
        "has_private_group": has_private_group,
        "configured_methods_count": len(configured_methods),
        "total_methods_count": len(methods or []),
    }


def render_reseller_setup_notice(lang: str, status: dict[str, Any]) -> str:
    ok = "✅"
    no = "❌"
    mark_pay = ok if bool(status.get("has_payment_method")) else no
    mark_group = ok if bool(status.get("has_private_group")) else no

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

    return (
        f"{t(lang, 'reseller_setup_required_title')}\n\n"
        f"{t(lang, 'reseller_setup_required_intro')}\n\n"
        f"{mark_pay} {t(lang, 'reseller_setup_check_payment')}\n"
        f"{mark_group} {t(lang, 'reseller_setup_check_group')}\n\n"
        f"{t(lang, 'reseller_setup_action')}\n\n"
        f"{setup_steps}"
    )
