from __future__ import annotations

from typing import Any, Awaitable, Callable

from services.numbers.manager import get_calls_from_provider
from services.numbers.order_recording_service import voice_recording_uri_from_calls
from services.numbers.order_service import NumbersOrderError


VoiceCallsFetcher = Callable[[str, str, str], Awaitable[dict[str, Any]]]


def _provider_fields(order: dict[str, Any]) -> tuple[str, str]:
    provider = str(order.get("provider") or order.get("provisioning_provider") or "").strip().lower()
    provider_order_id = str(order.get("provider_order_id") or "").strip()
    if not provider or not provider_order_id:
        raise NumbersOrderError("provider_order_missing", "This voice order is missing provider reservation data.", status=409)
    return provider, provider_order_id


async def voice_call_recording_state(
    order: dict[str, Any] | None,
    *,
    fetch_calls: VoiceCallsFetcher = get_calls_from_provider,
) -> dict[str, Any]:
    order = order if isinstance(order, dict) else {}
    if str(order.get("number_mode") or "").strip().lower() != "voice":
        raise NumbersOrderError("invalid_mode", "This action is only for call numbers.", status=400)

    provider, provider_order_id = _provider_fields(order)
    calls_data = await fetch_calls(provider, provider_order_id, str(order.get("provider_number") or ""))
    calls = calls_data.get("calls") if isinstance(calls_data, dict) else []
    if not isinstance(calls, list):
        calls = []

    return {
        "calls": calls,
        "recording_uri": voice_recording_uri_from_calls(calls),
        "raw": calls_data if isinstance(calls_data, dict) else {},
    }
