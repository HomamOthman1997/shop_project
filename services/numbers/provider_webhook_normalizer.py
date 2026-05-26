from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderSmsWebhook:
    provider_code: str
    event_type: str
    provider_order_id: str
    code: str
    full_sms: str
    raw_event: dict[str, Any]
    ignored_reason: str = ""

    @property
    def ignored(self) -> bool:
        return bool(self.ignored_reason)


def normalize_provider_sms_webhook(provider_code: str, payload: dict[str, Any] | None) -> ProviderSmsWebhook:
    provider = str(provider_code or "").strip().lower()
    raw = payload if isinstance(payload, dict) else {}
    if provider == "smsready":
        return _normalize_smsready(raw)
    if provider == "pvadeals":
        return _normalize_pvadeals(raw)
    if provider == "textverified":
        return _normalize_textverified(raw)
    return _normalize_generic(provider, raw)


def _normalize_smsready(payload: dict[str, Any]) -> ProviderSmsWebhook:
    event = str(payload.get("event") or "").strip()
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    ignored = "" if event == "new_sms" else "unsupported_event"
    return ProviderSmsWebhook(
        provider_code="smsready",
        event_type=event,
        provider_order_id=str(message.get("order_id") or "").strip(),
        code=str(message.get("code") or "").strip(),
        full_sms=str(message.get("full_sms") or "").strip(),
        raw_event=payload,
        ignored_reason=ignored,
    )


def _normalize_pvadeals(payload: dict[str, Any]) -> ProviderSmsWebhook:
    event = str(payload.get("event") or "").strip()
    ignored = "" if event == "sms_received" else "unsupported_event"
    return ProviderSmsWebhook(
        provider_code="pvadeals",
        event_type=event,
        provider_order_id=str(payload.get("requestId") or "").strip(),
        code=str(payload.get("code") or "").strip(),
        full_sms=str(payload.get("message") or "").strip(),
        raw_event=payload,
        ignored_reason=ignored,
    )


def _normalize_textverified(payload: dict[str, Any]) -> ProviderSmsWebhook:
    event = str(payload.get("event") or "").strip()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    ignored = "" if event == "v2.sms.received" else "unsupported_event"
    return ProviderSmsWebhook(
        provider_code="textverified",
        event_type=event,
        provider_order_id=str(data.get("reservationId") or data.get("reservation_id") or "").strip(),
        code=str(data.get("parsedCode") or data.get("parsed_code") or "").strip(),
        full_sms=str(data.get("smsContent") or data.get("sms_content") or "").strip(),
        raw_event=payload,
        ignored_reason=ignored,
    )


def _normalize_generic(provider_code: str, payload: dict[str, Any]) -> ProviderSmsWebhook:
    event = str(_first_value(payload, ("event", "type", "status", "action")) or "").strip()
    order_id = str(
        _first_value(
            payload,
            (
                "provider_order_id",
                "providerOrderId",
                "order_id",
                "orderId",
                "activation_id",
                "activationId",
                "request_id",
                "requestId",
                "reservation_id",
                "reservationId",
                "id",
                "message.order_id",
                "message.orderId",
                "message.id",
                "data.order_id",
                "data.orderId",
                "data.reservation_id",
                "data.reservationId",
                "data.id",
            ),
        )
        or ""
    ).strip()
    code = str(
        _first_value(
            payload,
            (
                "code",
                "sms_code",
                "smsCode",
                "otp",
                "pin",
                "parsed_code",
                "parsedCode",
                "message.code",
                "message.otp",
                "data.code",
                "data.otp",
                "data.parsed_code",
                "data.parsedCode",
            ),
        )
        or ""
    ).strip()
    full_sms = str(
        _first_value(
            payload,
            (
                "full_sms",
                "fullSms",
                "sms",
                "text",
                "smsContent",
                "message_text",
                "messageText",
                "message.full_sms",
                "message.text",
                "message.message",
                "message",
                "body",
                "content",
                "reply",
                "data.full_sms",
                "data.text",
                "data.message",
                "data.body",
                "data.content",
                "data.smsContent",
                "data.reply",
            ),
        )
        or ""
    ).strip()
    return ProviderSmsWebhook(
        provider_code=str(provider_code or "").strip().lower(),
        event_type=event,
        provider_order_id=order_id,
        code=code,
        full_sms=full_sms,
        raw_event=payload,
    )


def _first_value(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        current: Any = payload
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current.get(part)
        if current not in (None, ""):
            return current
    return None
