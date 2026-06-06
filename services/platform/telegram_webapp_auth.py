from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Iterable
from urllib.parse import parse_qsl

from aiohttp import web

TELEGRAM_INIT_DATA_HEADER = "X-Telegram-Init-Data"
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60


def configured_bot_tokens(*tokens: Any) -> tuple[str, ...]:
    result: list[str] = []
    for token in tokens:
        value = str(token or "").strip()
        if value and value not in result:
            result.append(value)
    return tuple(result)


def verify_telegram_init_data(
    init_data: str,
    *,
    bot_tokens: Iterable[str],
    max_age_seconds: int | None = DEFAULT_MAX_AGE_SECONDS,
    now: int | None = None,
) -> dict[str, Any]:
    raw = str(init_data or "").strip()
    if not raw:
        raise web.HTTPUnauthorized(text="missing initData")

    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = str(pairs.pop("hash", "") or "").strip()
    if not received_hash:
        raise web.HTTPUnauthorized(text="missing hash")

    tokens = configured_bot_tokens(*bot_tokens)
    if not tokens:
        raise web.HTTPUnauthorized(text="bot token not configured")

    check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    valid_signature = False
    for token in tokens:
        secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
        calculated = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(calculated, received_hash):
            valid_signature = True
            break
    if not valid_signature:
        raise web.HTTPUnauthorized(text="bad initData")

    try:
        auth_date = int(pairs.get("auth_date") or 0)
    except Exception as exc:
        raise web.HTTPUnauthorized(text="invalid auth_date") from exc
    current_time = int(time.time() if now is None else now)
    if auth_date <= 0:
        raise web.HTTPUnauthorized(text="missing auth_date")
    if auth_date > current_time + 30:
        raise web.HTTPUnauthorized(text="invalid auth_date")
    if max_age_seconds is not None and current_time - auth_date > int(max_age_seconds):
        raise web.HTTPUnauthorized(text="expired initData")

    try:
        user = json.loads(pairs.get("user") or "{}")
    except Exception as exc:
        raise web.HTTPUnauthorized(text="invalid user") from exc
    if not isinstance(user, dict):
        raise web.HTTPUnauthorized(text="invalid user")
    try:
        user_id = int(user.get("id") or 0)
    except Exception as exc:
        raise web.HTTPUnauthorized(text="invalid user") from exc
    if user_id <= 0:
        raise web.HTTPUnauthorized(text="missing user")

    return {
        "user_id": user_id,
        "user": user,
        "auth_date": auth_date,
        "query_id": str(pairs.get("query_id") or ""),
    }


def telegram_init_data_from_request(request: web.Request) -> str:
    return str(request.headers.get(TELEGRAM_INIT_DATA_HEADER, "") or "").strip()


def require_telegram_webapp_auth(
    request: web.Request,
    *,
    bot_tokens: Iterable[str],
    max_age_seconds: int | None = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    return verify_telegram_init_data(
        telegram_init_data_from_request(request),
        bot_tokens=bot_tokens,
        max_age_seconds=max_age_seconds,
    )


def optional_telegram_webapp_auth(
    request: web.Request,
    *,
    bot_tokens: Iterable[str],
    max_age_seconds: int | None = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any] | None:
    init_data = telegram_init_data_from_request(request)
    if not init_data:
        return None
    return verify_telegram_init_data(init_data, bot_tokens=bot_tokens, max_age_seconds=max_age_seconds)
