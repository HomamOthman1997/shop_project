from __future__ import annotations

from aiohttp import web

from services.numbers.api_payloads import TEMP_QUOTE_PROVIDER_CODES, normalize_temp_quote_rows, numbers_bootstrap_payload
from services.numbers.manager import get_all_prices
from services.numbers.order_service import NumbersOrderError, create_temp_order_from_quote
from services.numbers.service_map import get_service_display_name, resolve_canonical_service_key

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


async def quotes(request: web.Request) -> web.Response:
    mode = str(request.query.get("mode") or "temp").strip().lower()
    service = resolve_canonical_service_key(str(request.query.get("service") or ""))
    country = str(request.query.get("country") or "none").strip() or "none"
    state = str(request.query.get("state") or "none").strip() or "none"

    if mode != "temp":
        raise web.HTTPBadRequest(text="unsupported mode")
    if not service:
        raise web.HTTPBadRequest(text="missing service")
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
        headers=dict(_NO_STORE_HEADERS),
    )


def _json_error(message: str, *, status: int, code: str) -> web.Response:
    return web.json_response({"ok": False, "code": code, "message": message}, status=status, headers=dict(_NO_STORE_HEADERS))


async def create_order(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        body = {}

    # Temporary development auth until external API keys/scopes are introduced.
    try:
        user_id = int(request.headers.get("X-User-Id") or (body or {}).get("user_id") or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return _json_error("Missing API user context.", status=401, code="missing_user")

    quote_token = str((body or {}).get("quote_token") or "").strip()
    if not quote_token:
        return _json_error("Missing quote token.", status=400, code="missing_quote")

    idempotency_key = str(request.headers.get("Idempotency-Key") or (body or {}).get("idempotency_key") or "").strip()
    try:
        result = await create_temp_order_from_quote(
            user_id=user_id,
            reseller_id=user_id,
            quote_token=quote_token,
            idempotency_key=idempotency_key,
            lang=str((body or {}).get("language") or "en"),
        )
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code)
    return web.json_response(result, headers=dict(_NO_STORE_HEADERS))


def register_numbers_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/numbers/health", health)
    app.router.add_get("/api/v1/numbers/catalog/bootstrap", catalog_bootstrap)
    app.router.add_get("/api/v1/numbers/quotes", quotes)
    app.router.add_post("/api/v1/numbers/orders", create_order)
