from __future__ import annotations

from aiohttp import web

from services.numbers.api_payloads import numbers_bootstrap_payload

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


def register_numbers_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/numbers/health", health)
    app.router.add_get("/api/v1/numbers/catalog/bootstrap", catalog_bootstrap)
