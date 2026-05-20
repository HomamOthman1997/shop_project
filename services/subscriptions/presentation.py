from __future__ import annotations

from datetime import UTC, datetime

from aiogram import types

from .bot_subscription_service import get_subscription_plan_options
from utils.bot_menu_context import main_bot_url
from utils.user_money import format_usd


def format_subscription_dt(value) -> str:
    if not isinstance(value, datetime):
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def subscription_status_label(lang: str, status: str) -> str:
    normalized = str(status or "").strip().lower()
    if str(lang or "").lower().startswith("ar"):
        return {
            "trial_active": "شهر تجريبي",
            "active": "نشط",
            "grace_period": "مهلة دفع",
            "payment_required": "بانتظار الدفع",
            "suspended": "موقوف",
        }.get(normalized, normalized or "-")
    return {
        "trial_active": "Trial month",
        "active": "Active",
        "grace_period": "Grace period",
        "payment_required": "Awaiting payment",
        "suspended": "Suspended",
    }.get(normalized, normalized or "-")


def subscription_summary_lines(lang: str, subscription: dict) -> list[str]:
    is_ar = str(lang or "").lower().startswith("ar")
    status = str(subscription.get("status") or "").strip().lower()
    renewal_price = float(subscription.get("renewal_charge_usd") or subscription.get("monthly_price_usd") or 10.0)
    trial_price = float(subscription.get("trial_price_usd") or 1.0)
    plan_months = int(subscription.get("renewal_plan_months") or 1)
    discount = float(subscription.get("renewal_discount_percent") or 0.0)
    plan_label = f"{plan_months} شهر" if is_ar else f"{plan_months} month(s)"
    lines = [
        f"{'خطة الاشتراك' if is_ar else 'Subscription plan'}: {plan_label}",
        f"{'تجديد الخطة' if is_ar else 'Plan renewal'}: {format_usd(renewal_price)}",
        f"{'سعر الشهر التجريبي' if is_ar else 'Trial month price'}: {format_usd(trial_price)}",
        f"{'الخصم' if is_ar else 'Discount'}: {discount:.0f}%",
        f"{'الحالة' if is_ar else 'Status'}: {subscription_status_label(lang, status)}",
    ]
    if status == "trial_active":
        lines.append(
            f"{'ينتهي الشهر التجريبي' if is_ar else 'Trial month ends'}: {format_subscription_dt(subscription.get('trial_ends_at'))}"
        )
    elif status == "active":
        lines.append(
            f"{'ينتهي الاشتراك' if is_ar else 'Subscription ends'}: {format_subscription_dt(subscription.get('subscription_ends_at'))}"
        )
    elif status == "grace_period":
        lines.append(
            f"{'تنتهي المهلة' if is_ar else 'Grace ends'}: {format_subscription_dt(subscription.get('grace_ends_at'))}"
        )
    elif status == "payment_required":
        lines.append(
            f"{'أول دفعة مطلوبة' if is_ar else 'Initial payment required'}: {format_usd(trial_price)}"
            if bool(subscription.get("trial_available"))
            else f"{'الدفعة المطلوبة' if is_ar else 'Required payment'}: {format_usd(renewal_price)}"
        )
    return lines


def reseller_subscription_kb(subscription: dict, lang: str = "en") -> types.InlineKeyboardMarkup:
    is_ar = str(lang or "").lower().startswith("ar")
    status = str(subscription.get("status") or "").strip().lower()
    current_plan = int(subscription.get("renewal_plan_months") or 1)
    rows: list[list[types.InlineKeyboardButton]] = []

    if status in {"payment_required", "suspended", "grace_period"}:
        trial_available = bool(subscription.get("trial_available"))
        amount = float(
            subscription.get("trial_price_usd")
            if trial_available
            else subscription.get("renewal_charge_usd") or subscription.get("monthly_price_usd") or 0.0
        )
        label = (
            f"تفعيل الشهر التجريبي - {format_usd(amount)}"
            if is_ar and trial_available
            else f"تفعيل الاشتراك - {format_usd(amount)}"
            if is_ar
            else f"Activate Trial - {format_usd(amount)}"
            if trial_available
            else f"Activate Subscription - {format_usd(amount)}"
        )
        rows.append([types.InlineKeyboardButton(text=label, callback_data="rs_sub:activate")])

    main_url = main_bot_url("hub")
    if main_url:
        main_label = "فتح مركز CyberZone للشحن" if is_ar else "Open CyberZone Hub to Top Up"
        rows.append([types.InlineKeyboardButton(text=main_label, url=main_url)])

    plan_buttons: list[types.InlineKeyboardButton] = []
    for option in get_subscription_plan_options():
        months = int(option["months"])
        price = float(option["price_usd"])
        discount = float(option["discount_percent"])
        marker = "* " if months == current_plan else ""
        label = f"{marker}{months}M - {format_usd(price)}"
        if discount > 0:
            label += f" (-{discount:.0f}%)"
        plan_buttons.append(types.InlineKeyboardButton(text=label, callback_data=f"rs_sub:plan:{months}"))
    rows.append(plan_buttons[:2])
    rows.append([plan_buttons[2]])
    rows.append([types.InlineKeyboardButton(text="رجوع" if is_ar else "Back", callback_data="rsmenu:menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)
