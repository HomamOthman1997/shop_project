from __future__ import annotations

from typing import Any

from aiohttp import web

from database.api_keys_repo import create_api_key, list_api_keys, revoke_api_key, serialize_api_key_doc
from services.platform.api_auth import ApiAuthContext, require_api_auth

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

_ALLOWED_CUSTOMER_SCOPES = {
    "numbers:quotes",
    "numbers:orders:create",
}


def _json_error(message: str, *, status: int, code: str) -> web.Response:
    return web.json_response({"ok": False, "code": code, "message": message}, status=status, headers=dict(_NO_STORE_HEADERS))


def _is_super_key(auth: ApiAuthContext) -> bool:
    return "*" in set(auth.scopes)


def _clean_scopes(values: Any) -> list[str]:
    scopes = sorted({str(value).strip() for value in (values or []) if str(value).strip()})
    return [scope for scope in scopes if scope in _ALLOWED_CUSTOMER_SCOPES]


async def list_keys(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "api_keys:manage")
    rows = await list_api_keys(reseller_id=auth.reseller_id)
    return web.json_response({"ok": True, "keys": rows}, headers=dict(_NO_STORE_HEADERS))


async def create_key(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "api_keys:manage")
    try:
        body = await request.json()
    except Exception:
        body = {}

    scopes = _clean_scopes((body or {}).get("scopes") or [])
    if not scopes:
        return _json_error("At least one valid scope is required.", status=400, code="missing_scopes")

    user_id = auth.user_id
    reseller_id = auth.reseller_id
    if _is_super_key(auth):
        try:
            user_id = int((body or {}).get("user_id") or user_id)
            reseller_id = int((body or {}).get("reseller_id") or reseller_id)
        except Exception:
            return _json_error("Invalid user or reseller id.", status=400, code="invalid_owner")

    api_key, doc = await create_api_key(
        user_id=user_id,
        reseller_id=reseller_id,
        name=str((body or {}).get("name") or "").strip(),
        scopes=scopes,
    )
    return web.json_response(
        {
            "ok": True,
            "api_key": api_key,
            "key": serialize_api_key_doc(doc),
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def revoke_key(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "api_keys:manage")
    key_id = str(request.match_info.get("key_id") or "").strip()
    ok = await revoke_api_key(key_id=key_id, reseller_id=None if _is_super_key(auth) else auth.reseller_id)
    if not ok:
        return _json_error("API key was not found.", status=404, code="key_not_found")
    return web.json_response({"ok": True, "id": key_id, "status": "revoked"}, headers=dict(_NO_STORE_HEADERS))


def register_api_key_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/api-keys", list_keys)
    app.router.add_post("/api/v1/api-keys", create_key)
    app.router.add_post("/api/v1/api-keys/{key_id}/revoke", revoke_key)
