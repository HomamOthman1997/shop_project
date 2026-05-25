from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from aiohttp import web

from database.webhooks_repo import create_webhook, list_webhooks, revoke_webhook, serialize_webhook_doc
from services.platform.api_auth import ApiAuthContext, require_api_auth
from services.platform.api_rate_limits import (
    ApiRateLimitDecision,
    ApiRateLimitExceeded,
    check_api_rate_limit,
    rate_limit_headers,
    retry_after_seconds,
)


_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

ALLOWED_WEBHOOK_EVENTS = {
    "numbers.order.created",
    "numbers.order.resend_requested",
    "numbers.order.sms",
    "numbers.order.refunded",
}


def _response_headers(rate_limit: ApiRateLimitDecision | None = None) -> dict[str, str]:
    headers = dict(_NO_STORE_HEADERS)
    if rate_limit is not None:
        headers.update(rate_limit_headers(rate_limit))
    return headers


def _json_error(message: str, *, status: int, code: str, rate_limit: ApiRateLimitDecision | None = None) -> web.Response:
    headers = _response_headers(rate_limit)
    if status == 429 and rate_limit is not None:
        headers["Retry-After"] = str(retry_after_seconds(rate_limit))
    return web.json_response({"ok": False, "code": code, "message": message}, status=status, headers=headers)


def _is_super_key(auth: ApiAuthContext) -> bool:
    return "*" in set(auth.scopes)


async def _check_webhook_rate_limit(auth: ApiAuthContext) -> ApiRateLimitDecision:
    try:
        return await check_api_rate_limit(auth, bucket="webhooks:manage", limit=30)
    except ApiRateLimitExceeded as exc:
        raise web.HTTPTooManyRequests(
            text="rate limit exceeded",
            headers={**_response_headers(exc.decision), "Retry-After": str(retry_after_seconds(exc.decision))},
        ) from exc


async def list_webhook_endpoints(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "webhooks:manage")
    rate_limit = await _check_webhook_rate_limit(auth)
    rows = await list_webhooks(reseller_id=auth.reseller_id)
    return web.json_response({"ok": True, "webhooks": rows}, headers=_response_headers(rate_limit))


async def create_webhook_endpoint(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "webhooks:manage")
    rate_limit = await _check_webhook_rate_limit(auth)
    try:
        body = await request.json()
    except Exception:
        body = {}

    url = str((body or {}).get("url") or "").strip()
    if not _valid_https_url(url):
        return _json_error("A valid HTTPS webhook URL is required.", status=400, code="invalid_webhook_url", rate_limit=rate_limit)

    events = _clean_events((body or {}).get("events") or [])
    if not events:
        return _json_error("At least one valid webhook event is required.", status=400, code="missing_webhook_events", rate_limit=rate_limit)

    user_id = auth.user_id
    reseller_id = auth.reseller_id
    if _is_super_key(auth):
        user_id = _int_or_default((body or {}).get("user_id"), user_id)
        reseller_id = _int_or_default((body or {}).get("reseller_id"), reseller_id)

    secret, doc = await create_webhook(user_id=user_id, reseller_id=reseller_id, url=url, events=events)
    return web.json_response(
        {"ok": True, "webhook": serialize_webhook_doc(doc), "secret": secret},
        headers=_response_headers(rate_limit),
    )


async def revoke_webhook_endpoint(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "webhooks:manage")
    rate_limit = await _check_webhook_rate_limit(auth)
    webhook_id = str(request.match_info.get("webhook_id") or "").strip()
    ok = await revoke_webhook(webhook_id=webhook_id, reseller_id=None if _is_super_key(auth) else auth.reseller_id)
    if not ok:
        return _json_error("Webhook was not found.", status=404, code="webhook_not_found", rate_limit=rate_limit)
    return web.json_response({"ok": True, "id": webhook_id, "status": "revoked"}, headers=_response_headers(rate_limit))


def register_webhook_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/webhooks", list_webhook_endpoints)
    app.router.add_post("/api/v1/webhooks", create_webhook_endpoint)
    app.router.add_post("/api/v1/webhooks/{webhook_id}/revoke", revoke_webhook_endpoint)


def _clean_events(values: Any) -> list[str]:
    events = sorted({str(value).strip() for value in (values or []) if str(value).strip()})
    return [event for event in events if event in ALLOWED_WEBHOOK_EVENTS]


def _valid_https_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _int_or_default(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return int(default)
    return parsed if parsed > 0 else int(default)
