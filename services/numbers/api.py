from __future__ import annotations

from datetime import datetime

from aiohttp import web

from database.financial_ledger import get_user_wallet_balance
from database.orders_repo import list_user_recent_temp_and_voice_orders, list_user_rental_orders
from database.user_repo import get_user
from services.numbers.api_payloads import TEMP_QUOTE_PROVIDER_CODES, normalize_temp_quote_rows, numbers_bootstrap_payload
from services.numbers.manager import get_all_prices
from services.numbers.order_service import NumbersOrderError, create_temp_order_from_quote, public_order_payload
from services.numbers.service_map import get_service_display_name, resolve_canonical_service_key
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


async def health(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "status": "healthy",
            "service": "numbers-api",
            "version": "v1",
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def catalog_bootstrap(_request: web.Request) -> web.Response:
    return web.json_response(numbers_bootstrap_payload(), headers=dict(_NO_STORE_HEADERS))


def _format_money(value: float) -> str:
    return f"${float(value or 0):.2f}"


def _iso_datetime(value) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


async def account(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:account:read")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:account:read", limit=60)

    user_doc = await get_user(auth.user_id)
    if not isinstance(user_doc, dict):
        user_doc = {}
    balance = await get_user_wallet_balance(auth.user_id, auth.reseller_id)
    language = str(user_doc.get("language") or "en").strip().lower()

    return web.json_response(
        {
            "ok": True,
            "user": {
                "id": auth.user_id,
                "username": str(user_doc.get("username") or ""),
                "language": "ar" if language.startswith("ar") else "en",
                "joined_at": _iso_datetime(user_doc.get("created_at")),
            },
            "reseller": {"id": auth.reseller_id},
            "wallet": {
                "balance": float(balance),
                "currency": "USD",
                "balance_label": _format_money(balance),
            },
        },
        headers=_response_headers(rate_limit),
    )


async def quotes(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:quotes")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:quotes", limit=120)

    mode = str(request.query.get("mode") or "temp").strip().lower()
    service = resolve_canonical_service_key(str(request.query.get("service") or ""))
    country = str(request.query.get("country") or "none").strip() or "none"
    state = str(request.query.get("state") or "none").strip() or "none"

    if mode != "temp":
        return _json_error("Unsupported mode.", status=400, code="unsupported_mode", rate_limit=rate_limit)
    if not service:
        return _json_error("Missing service.", status=400, code="missing_service", rate_limit=rate_limit)
    if country != "1":
        state = "none"

    raw = await get_all_prices(
        service,
        country,
        state,
        ignore_balance=True,
        with_success_rates=False,
        provider_codes=TEMP_QUOTE_PROVIDER_CODES,
    )
    return web.json_response(
        {
            "ok": True,
            "mode": "temp",
            "service": {"key": service, "label": get_service_display_name(service) or service},
            "country": country,
            "state": state,
            "providers": normalize_temp_quote_rows(raw, service=service, country=country, state=state),
        },
        headers=_response_headers(rate_limit),
    )


def _parse_limit(request: web.Request, *, default: int = 20, maximum: int = 50) -> int:
    try:
        value = int(str(request.query.get("limit") or default))
    except Exception:
        value = default
    return max(1, min(value, maximum))


async def list_orders(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:read")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:read", limit=90)
    mode = str(request.query.get("mode") or "all").strip().lower()
    limit = _parse_limit(request)

    if mode not in {"all", "temp", "voice", "rental"}:
        return _json_error("Unsupported mode.", status=400, code="unsupported_mode", rate_limit=rate_limit)

    rows = []
    if mode in {"all", "temp", "voice"}:
        rows.extend(await list_user_recent_temp_and_voice_orders(auth.user_id, limit=limit))
    if mode in {"all", "rental"}:
        rows.extend(await list_user_rental_orders(auth.user_id, limit=limit))

    if mode == "temp":
        rows = [row for row in rows if str(row.get("number_mode") or "") == "temp"]
    elif mode == "voice":
        rows = [row for row in rows if str(row.get("number_mode") or "") == "voice"]

    rows.sort(key=lambda row: row.get("created_at") or datetime.min, reverse=True)
    rows = rows[:limit]

    return web.json_response(
        {
            "ok": True,
            "mode": mode,
            "orders": [public_order_payload(row) for row in rows],
        },
        headers=_response_headers(rate_limit),
    )


def _response_headers(rate_limit: ApiRateLimitDecision | None = None) -> dict[str, str]:
    headers = dict(_NO_STORE_HEADERS)
    if rate_limit is not None:
        headers.update(rate_limit_headers(rate_limit))
    return headers


def _json_error(
    message: str,
    *,
    status: int,
    code: str,
    rate_limit: ApiRateLimitDecision | None = None,
) -> web.Response:
    headers = _response_headers(rate_limit)
    if rate_limit is not None and status == 429:
        headers["Retry-After"] = str(retry_after_seconds(rate_limit))
    return web.json_response({"ok": False, "code": code, "message": message}, status=status, headers=headers)


async def _check_rate_limit(auth: ApiAuthContext, *, bucket: str, limit: int) -> ApiRateLimitDecision:
    try:
        return await check_api_rate_limit(auth, bucket=bucket, limit=limit)
    except ApiRateLimitExceeded as exc:
        raise web.HTTPTooManyRequests(
            text="rate limit exceeded",
            headers={
                **_response_headers(exc.decision),
                "Retry-After": str(retry_after_seconds(exc.decision)),
            },
        ) from exc


async def create_order(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:create")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:create", limit=30)

    try:
        body = await request.json()
    except Exception:
        body = {}

    quote_token = str((body or {}).get("quote_token") or "").strip()
    if not quote_token:
        return _json_error("Missing quote token.", status=400, code="missing_quote", rate_limit=rate_limit)

    idempotency_key = str(request.headers.get("Idempotency-Key") or (body or {}).get("idempotency_key") or "").strip()
    try:
        result = await create_temp_order_from_quote(
            user_id=auth.user_id,
            reseller_id=auth.reseller_id,
            quote_token=quote_token,
            idempotency_key=idempotency_key,
            lang=str((body or {}).get("language") or "en"),
        )
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


def register_numbers_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/numbers/health", health)
    app.router.add_get("/api/v1/numbers/catalog/bootstrap", catalog_bootstrap)
    app.router.add_get("/api/v1/numbers/account", account)
    app.router.add_get("/api/v1/numbers/quotes", quotes)
    app.router.add_get("/api/v1/numbers/orders", list_orders)
    app.router.add_post("/api/v1/numbers/orders", create_order)
