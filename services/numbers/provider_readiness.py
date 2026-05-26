from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from config import settings


@dataclass(frozen=True)
class ProviderReadiness:
    provider: str
    status: str
    quote_enabled: bool
    purchase_enabled: bool
    auto_refund_enabled: bool
    webhook_documented: bool
    webhook_verified: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "quote_enabled": self.quote_enabled,
            "purchase_enabled": self.purchase_enabled,
            "auto_refund_enabled": self.auto_refund_enabled,
            "webhook_documented": self.webhook_documented,
            "webhook_verified": self.webhook_verified,
            "reason": self.reason,
        }


_POLICY: dict[str, ProviderReadiness] = {
    "textverified": ProviderReadiness(
        provider="textverified",
        status="webhook_pending",
        quote_enabled=True,
        purchase_enabled=True,
        auto_refund_enabled=True,
        webhook_documented=True,
        webhook_verified=False,
        reason="Live order/cancel path verified; waiting for one provider-generated SMS webhook.",
    ),
    "telabot": ProviderReadiness(
        provider="telabot",
        status="webhook_pending",
        quote_enabled=True,
        purchase_enabled=True,
        auto_refund_enabled=True,
        webhook_documented=True,
        webhook_verified=False,
        reason="Live order/reject path verified; waiting for one provider-generated SMS webhook.",
    ),
    "pvadeals": ProviderReadiness(
        provider="pvadeals",
        status="webhook_pending",
        quote_enabled=True,
        purchase_enabled=True,
        auto_refund_enabled=True,
        webhook_documented=True,
        webhook_verified=False,
        reason="Live order and provider flag/cancel path verified; refund settlement still needs observation.",
    ),
    "herosms": ProviderReadiness(
        provider="herosms",
        status="webhook_pending",
        quote_enabled=True,
        purchase_enabled=True,
        auto_refund_enabled=True,
        webhook_documented=True,
        webhook_verified=False,
        reason="Webhook documented and route-compatible; last live buy attempt returned provider_no_stock.",
    ),
    "smsready": ProviderReadiness(
        provider="smsready",
        status="disabled",
        quote_enabled=False,
        purchase_enabled=False,
        auto_refund_enabled=False,
        webhook_documented=True,
        webhook_verified=False,
        reason="Local live checks could not connect to api.sms-ready.com; retry from production network before enabling.",
    ),
    "nonvoip": ProviderReadiness(
        provider="nonvoip",
        status="refund_risk",
        quote_enabled=True,
        purchase_enabled=True,
        auto_refund_enabled=False,
        webhook_documented=True,
        webhook_verified=False,
        reason="Live order worked, but immediate refund returned Not sufficient; no-code refunds need support/manual review.",
    ),
    "nonvoip_s6": ProviderReadiness(
        provider="nonvoip_s6",
        status="refund_risk",
        quote_enabled=False,
        purchase_enabled=False,
        auto_refund_enabled=False,
        webhook_documented=True,
        webhook_verified=False,
        reason="Alias lane for nonvoip remains hidden until the primary lane is fully production-trusted.",
    ),
    "pvapins": ProviderReadiness(
        provider="pvapins",
        status="polling_required",
        quote_enabled=True,
        purchase_enabled=True,
        auto_refund_enabled=True,
        webhook_documented=False,
        webhook_verified=False,
        reason="Confirmed polling-only by account/docs; enabled as an explicit provider polling exception.",
    ),
    "vaksms": ProviderReadiness(
        provider="vaksms",
        status="polling_required",
        quote_enabled=True,
        purchase_enabled=True,
        auto_refund_enabled=True,
        webhook_documented=False,
        webhook_verified=False,
        reason="Confirmed polling-only by account/docs; enabled as an explicit provider polling exception.",
    ),
    "smspool": ProviderReadiness(
        provider="smspool",
        status="polling_required",
        quote_enabled=True,
        purchase_enabled=True,
        auto_refund_enabled=True,
        webhook_documented=False,
        webhook_verified=False,
        reason="Confirmed polling-only by account/docs; enabled as an explicit provider polling exception.",
    ),
}

_DEFAULT = ProviderReadiness(
    provider="",
    status="disabled",
    quote_enabled=False,
    purchase_enabled=False,
    auto_refund_enabled=False,
    webhook_documented=False,
    webhook_verified=False,
    reason="Provider is not registered in readiness policy.",
)


def provider_readiness(provider_code: str) -> ProviderReadiness:
    code = str(provider_code or "").strip().lower()
    if not code:
        return _DEFAULT
    base = _POLICY.get(code, ProviderReadiness(**{**_DEFAULT.to_dict(), "provider": code}))
    override = _override_for_provider(code)
    if not override:
        return base
    data = base.to_dict()
    allowed = set(data.keys()) - {"provider"}
    for key, value in override.items():
        if key in allowed:
            data[key] = _coerce_override_value(key, value)
    data["provider"] = code
    return ProviderReadiness(**data)


def provider_quote_enabled(provider_code: str, *, mode: str = "temp") -> bool:
    readiness = provider_readiness(provider_code)
    if str(mode or "").strip().lower() == "voice":
        return readiness.purchase_enabled
    return readiness.quote_enabled


def provider_purchase_enabled(provider_code: str, *, mode: str = "temp") -> bool:
    return provider_readiness(provider_code).purchase_enabled


def readiness_block_payload(provider_code: str, *, mode: str = "temp") -> dict[str, Any]:
    readiness = provider_readiness(provider_code)
    return {
        "success": False,
        "price": 0.0,
        "base_price": 0.0,
        "options": [],
        "api_service_name": "",
        "available_for_buy": False,
        "testing_visible": True,
        "provider_readiness": readiness.to_dict(),
        "provider_reason": f"provider_{readiness.status}",
        "provider_reason_message": readiness.reason,
        "mode": str(mode or "temp"),
    }


def provider_readiness_rows() -> list[dict[str, Any]]:
    codes = set(_POLICY.keys()) | set(_readiness_overrides().keys())
    return [provider_readiness(code).to_dict() for code in sorted(codes)]


def _readiness_overrides() -> dict[str, dict[str, Any]]:
    raw = str(getattr(settings, "numbers_provider_readiness_overrides", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for provider, value in parsed.items():
        code = str(provider or "").strip().lower()
        if code and isinstance(value, dict):
            out[code] = value
    return out


def _override_for_provider(provider_code: str) -> dict[str, Any]:
    return _readiness_overrides().get(str(provider_code or "").strip().lower(), {})


def _coerce_override_value(key: str, value: Any) -> Any:
    if key in {"quote_enabled", "purchase_enabled", "auto_refund_enabled", "webhook_documented", "webhook_verified"}:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
    return str(value or "").strip()
