from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import web

from database.api_keys_repo import find_active_api_key, has_scope


@dataclass(frozen=True)
class ApiAuthContext:
    key_id: str
    user_id: int
    reseller_id: int
    scopes: tuple[str, ...]
    name: str = ""


def _extract_api_key(request: web.Request) -> str:
    auth = str(request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return str(request.headers.get("X-API-Key") or "").strip()


async def require_api_auth(request: web.Request, required_scope: str) -> ApiAuthContext:
    api_key = _extract_api_key(request)
    if not api_key:
        raise web.HTTPUnauthorized(text="missing api key")

    doc = await find_active_api_key(api_key)
    if not isinstance(doc, dict):
        raise web.HTTPUnauthorized(text="invalid api key")

    if not has_scope(doc, required_scope):
        raise web.HTTPForbidden(text="missing scope")

    try:
        user_id = int(doc.get("user_id") or 0)
    except Exception:
        user_id = 0
    try:
        reseller_id = int(doc.get("reseller_id") or user_id)
    except Exception:
        reseller_id = user_id
    if user_id <= 0 or reseller_id <= 0:
        raise web.HTTPUnauthorized(text="invalid api key owner")

    return ApiAuthContext(
        key_id=str(doc.get("_id") or ""),
        user_id=user_id,
        reseller_id=reseller_id,
        scopes=tuple(str(scope) for scope in (doc.get("scopes") or [])),
        name=str(doc.get("name") or ""),
    )
