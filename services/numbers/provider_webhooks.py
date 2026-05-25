from __future__ import annotations

import hmac
from typing import Any

from aiohttp import web

from config import settings
from services.numbers.provider_webhook_normalizer import normalize_provider_sms_webhook
from services.numbers.provider_webhook_service import apply_provider_temp_sms_webhook

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _configured_provider_webhook_token() -> str:
    return str(
        getattr(settings, "numbers_provider_webhook_token", None)
        or getattr(settings, "provider_webhook_token", None)
        or ""
    ).strip()


def _request_token(request: web.Request) -> str:
    return str(request.query.get("token") or request.headers.get("X-Provider-Webhook-Token") or "").strip()


def _provider_webhook_authorized(request: web.Request) -> bool:
    expected = _configured_provider_webhook_token()
    if not expected:
        return False
    return hmac.compare_digest(_request_token(request), expected)


async def _handle_provider_sms_webhook(request: web.Request, provider_code: str) -> web.Response:
    if not _provider_webhook_authorized(request):
        return web.json_response(
            {"ok": False, "code": "unauthorized_provider_webhook"},
            status=401,
            headers=dict(_NO_STORE_HEADERS),
        )
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    normalized = normalize_provider_sms_webhook(provider_code, payload if isinstance(payload, dict) else {})
    if normalized.ignored:
        return web.json_response({"ok": True, "ignored": True, "reason": normalized.ignored_reason}, headers=dict(_NO_STORE_HEADERS))

    result = await apply_provider_temp_sms_webhook(
        provider_code=normalized.provider_code,
        provider_order_id=normalized.provider_order_id,
        code=normalized.code,
        full_sms=normalized.full_sms,
        raw_event=normalized.raw_event,
    )
    status = 200 if result.get("ok") else 404 if result.get("reason") == "order_not_found" else 400
    return web.json_response(result, status=status, headers=dict(_NO_STORE_HEADERS))


async def smsready_webhook(request: web.Request) -> web.Response:
    return await _handle_provider_sms_webhook(request, "smsready")


async def pvadeals_webhook(request: web.Request) -> web.Response:
    return await _handle_provider_sms_webhook(request, "pvadeals")


async def generic_provider_webhook(request: web.Request) -> web.Response:
    provider = str(request.match_info.get("provider") or "").strip().lower()
    if not provider:
        return web.json_response({"ok": False, "code": "missing_provider"}, status=400, headers=dict(_NO_STORE_HEADERS))
    return await _handle_provider_sms_webhook(request, provider)


def register_provider_webhook_routes(app: web.Application) -> None:
    app.router.add_post("/api/v1/provider-webhooks/smsready", smsready_webhook)
    app.router.add_post("/api/v1/provider-webhooks/pvadeals", pvadeals_webhook)
    app.router.add_post("/api/v1/provider-webhooks/{provider}", generic_provider_webhook)
