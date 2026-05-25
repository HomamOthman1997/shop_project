from __future__ import annotations

from aiohttp import web

from services.numbers.api_payloads import TEMP_QUOTE_PROVIDER_CODES, normalize_temp_quote_rows, numbers_bootstrap_payload
from services.numbers.manager import get_all_prices
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


def register_numbers_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/numbers/health", health)
    app.router.add_get("/api/v1/numbers/catalog/bootstrap", catalog_bootstrap)
    app.router.add_get("/api/v1/numbers/quotes", quotes)
