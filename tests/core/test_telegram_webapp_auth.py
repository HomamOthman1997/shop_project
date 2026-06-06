import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from aiohttp import web

from services.platform.telegram_webapp_auth import verify_telegram_init_data


def signed_init_data(*, token: str, user_id: int = 123, auth_date: int | None = None) -> str:
    auth_date = int(time.time()) if auth_date is None else int(auth_date)
    pairs = {
        "auth_date": str(auth_date),
        "query_id": "query-1",
        "user": json.dumps({"id": user_id, "username": "homam"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_verify_telegram_init_data_returns_authenticated_user():
    raw = signed_init_data(token="123:test", auth_date=1_900_000_000)

    result = verify_telegram_init_data(raw, bot_tokens=("123:test",), now=1_900_000_010)

    assert result["user_id"] == 123
    assert result["user"]["username"] == "homam"
    assert result["query_id"] == "query-1"


def test_verify_telegram_init_data_rejects_expired_payload():
    raw = signed_init_data(token="123:test", auth_date=1_800_000_000)

    with pytest.raises(web.HTTPUnauthorized) as exc_info:
        verify_telegram_init_data(raw, bot_tokens=("123:test",), now=1_900_000_000)
    assert exc_info.value.text == "expired initData"


def test_verify_telegram_init_data_rejects_tampered_payload():
    raw = signed_init_data(token="123:test", auth_date=1_900_000_000).replace("homam", "attacker")

    with pytest.raises(web.HTTPUnauthorized) as exc_info:
        verify_telegram_init_data(raw, bot_tokens=("123:test",), now=1_900_000_010)
    assert exc_info.value.text == "bad initData"
