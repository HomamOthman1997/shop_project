from __future__ import annotations

from typing import Any

from config import settings

WEBHOOK_SMS_PROVIDERS: frozenset[str] = frozenset(
    {
        "herosms",
        "pvadeals",
        "pvapins",
        "nonvoip",
        "nonvoip_s6",
        "smsready",
        "smspool",
        "telabot",
        "textverified",
        "vaksms",
    }
)


def provider_sms_delivery_strategy(provider_code: str | None) -> str:
    provider = str(provider_code or "").strip().lower()
    return "webhook" if provider in WEBHOOK_SMS_PROVIDERS else "polling"


def order_uses_provider_sms_webhook(order: dict[str, Any] | None) -> bool:
    order = order or {}
    explicit = str(order.get("provider_sms_delivery") or "").strip().lower()
    if explicit:
        return explicit == "webhook"
    provider = str(order.get("provider") or order.get("provisioning_provider") or "").strip().lower()
    return provider_sms_delivery_strategy(provider) == "webhook"


def provider_sms_polling_enabled() -> bool:
    return bool(getattr(settings, "numbers_provider_sms_polling_enabled", False))
