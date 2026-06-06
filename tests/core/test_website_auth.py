import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from pymongo.errors import DuplicateKeyError

from services.platform import website_auth


def json_request(method: str, path: str, body: dict | None = None, *, token: str = ""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = make_mocked_request(method, path, headers=headers)
    request._read_bytes = json.dumps(body or {}).encode("utf-8")
    return request


def test_register_website_auth_routes():
    app = web.Application()

    website_auth.register_website_auth_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("POST", "/api/v1/auth/register") in routes
    assert ("POST", "/api/v1/auth/login") in routes
    assert ("GET", "/api/v1/auth/me") in routes
    assert ("POST", "/api/v1/auth/telegram/link") in routes
    assert ("DELETE", "/api/v1/auth/telegram/link") in routes
    assert ("POST", "/api/v1/auth/email/send-code") in routes
    assert ("POST", "/api/v1/auth/email/verify") in routes
    assert ("GET", "/login") in routes
    assert ("GET", "/account") in routes


def test_shop_root_serves_website_auth_page():
    from services.digital_products.miniapp import create_app

    app = create_app()
    routes = {(route.method, route.resource.canonical, route.handler.__name__) for route in app.router.routes()}

    assert ("GET", "/", "auth_page") in routes


def test_password_hash_round_trip():
    salt, password_hash = website_auth._password_hash("long-secure-password")

    assert website_auth._password_matches(
        "long-secure-password",
        {"password_salt": salt, "password_hash": password_hash},
    )
    assert not website_auth._password_matches(
        "wrong-password",
        {"password_salt": salt, "password_hash": password_hash},
    )


def test_public_account_requires_verified_email_for_buying():
    account = website_auth._public_account(
        {
            "_id": "account-1",
            "customer_id": 900000000001,
            "email": "user@example.com",
            "identity_status": "not_submitted",
        }
    )
    assert account["email_verified"] is False
    assert account["capabilities"]["buy_services"] is False

    verified = website_auth._public_account({**account, "_id": "account-1", "email_verified_at": website_auth._now()})
    assert verified["email_verified"] is True
    assert verified["capabilities"]["buy_services"] is True

    linked = website_auth._public_account({**account, "_id": "account-1", "telegram_id": 123})
    assert linked["capabilities"]["buy_services"] is False


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(monkeypatch):
    async def duplicate(_doc):
        raise DuplicateKeyError("duplicate")

    monkeypatch.setattr(website_auth, "create_website_account", duplicate)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))
    monkeypatch.setattr(website_auth, "allocate_website_customer_id", lambda: __import__("asyncio").sleep(0, result=900000000001))

    with pytest.raises(web.HTTPConflict):
        await website_auth.register(
            json_request("POST", "/api/v1/auth/register", {"email": "USER@example.com", "password": "secure-password"})
        )


@pytest.mark.asyncio
async def test_rate_limit_rejects_excess_attempts(monkeypatch):
    async def denied(*_args, **_kwargs):
        return False

    monkeypatch.setattr(website_auth, "consume_website_auth_rate_limit", denied)

    with pytest.raises(web.HTTPTooManyRequests):
        await website_auth._enforce_rate_limit(
            json_request("POST", "/api/v1/auth/login"),
            bucket="login",
            discriminator="user@example.com",
            limit=10,
        )


@pytest.mark.asyncio
async def test_cookie_session_requires_csrf_for_mutation(monkeypatch):
    async def session(_token_hash, *, now):
        return {"account_id": "account-1"}

    async def account(_account_id):
        return {"_id": "account-1", "email": "user@example.com", "status": "active"}

    monkeypatch.setattr(website_auth, "find_website_session", session)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    request = make_mocked_request(
        "POST",
        "/api/v1/auth/logout",
        headers={"Cookie": "phantom_session=session-token; phantom_csrf=csrf-token"},
    )

    with pytest.raises(web.HTTPForbidden):
        await website_auth.require_website_auth(request)


@pytest.mark.asyncio
async def test_cookie_session_accepts_matching_csrf(monkeypatch):
    async def session(_token_hash, *, now):
        return {"account_id": "account-1"}

    async def account(_account_id):
        return {"_id": "account-1", "email": "user@example.com", "status": "active"}

    monkeypatch.setattr(website_auth, "find_website_session", session)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    request = make_mocked_request(
        "POST",
        "/api/v1/auth/logout",
        headers={
            "Cookie": "phantom_session=session-token; phantom_csrf=csrf-token",
            "X-CSRF-Token": "csrf-token",
        },
    )

    auth = await website_auth.require_website_auth(request)

    assert auth.account_id == "account-1"


@pytest.mark.asyncio
async def test_send_email_code_stores_token_and_uses_resend_provider(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def account(_account_id):
        return {"_id": "account-1", "email": "user@example.com", "customer_id": 900000000001, "status": "active"}

    stored = {}

    async def create(doc):
        stored.update(doc)

    async def deliver(*, email, code):
        stored["delivered_email"] = email
        stored["delivered_code"] = code
        return {"provider": "resend", "status": "sent"}

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))
    monkeypatch.setattr(website_auth, "create_email_verification_token", create)
    monkeypatch.setattr(website_auth, "_deliver_email_verification_code", deliver)
    monkeypatch.setattr(website_auth, "_generate_email_code", lambda: "123456")

    response = await website_auth.send_email_code(json_request("POST", "/api/v1/auth/email/send-code"))
    body = json.loads(response.text)

    assert body["provider"] == "resend"
    assert body["status"] == "sent"
    assert stored["account_id"] == "account-1"
    assert stored["delivered_email"] == "user@example.com"
    assert stored["delivered_code"] == "123456"


@pytest.mark.asyncio
async def test_verify_email_code_marks_account_verified(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def consume(account_id, code_hash, *, now):
        assert account_id == "account-1"
        assert code_hash == website_auth._email_code_hash("account-1", "123456")
        return {"account_id": account_id}

    async def mark(account_id, *, now):
        return {
            "_id": account_id,
            "customer_id": 900000000001,
            "email": "user@example.com",
            "status": "active",
            "email_verified_at": now,
        }

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))
    monkeypatch.setattr(website_auth, "consume_email_verification_token", consume)
    monkeypatch.setattr(website_auth, "mark_website_email_verified", mark)

    response = await website_auth.verify_email_code(
        json_request("POST", "/api/v1/auth/email/verify", {"code": "123456"})
    )
    body = json.loads(response.text)

    assert body["account"]["email_verified"] is True
    assert body["account"]["capabilities"]["buy_services"] is True


@pytest.mark.asyncio
async def test_require_website_purchase_ready_rejects_unverified_cookie_account(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def account(_account_id):
        return {"_id": "account-1", "email": "user@example.com", "status": "active"}

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    request = make_mocked_request("POST", "/api/v1/digital/orders", headers={"Cookie": "phantom_session=session-token"})

    with pytest.raises(web.HTTPForbidden):
        await website_auth.require_website_purchase_ready(request)


@pytest.mark.asyncio
async def test_require_website_purchase_ready_allows_verified_cookie_account(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def account(_account_id):
        return {"_id": "account-1", "email_verified_at": website_auth._now(), "status": "active"}

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    request = make_mocked_request("POST", "/api/v1/digital/orders", headers={"Cookie": "phantom_session=session-token"})

    await website_auth.require_website_purchase_ready(request)


@pytest.mark.asyncio
async def test_consume_telegram_link_rejects_reused_token(monkeypatch):
    async def missing(_token_hash, *, now):
        return None

    monkeypatch.setattr(website_auth, "consume_telegram_link_token", missing)

    result = await website_auth.consume_telegram_link("link_" + ("a" * 32), telegram_id=123)

    assert result == {"ok": False, "reason": "expired_or_used"}


@pytest.mark.asyncio
async def test_consume_telegram_link_prevents_duplicate_telegram(monkeypatch):
    async def found(_token_hash, *, now):
        return {"account_id": "account-1"}

    async def duplicate(_account_id, _telegram_id, *, now):
        raise DuplicateKeyError("duplicate telegram")

    monkeypatch.setattr(website_auth, "consume_telegram_link_token", found)
    monkeypatch.setattr(website_auth, "link_telegram_account", duplicate)

    result = await website_auth.consume_telegram_link("link_" + ("b" * 32), telegram_id=123)

    assert result == {"ok": False, "reason": "telegram_already_linked"}


@pytest.mark.asyncio
async def test_create_link_returns_main_bot_deep_link(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    stored = {}

    async def create(doc):
        stored.update(doc)

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "create_telegram_link_token", create)
    monkeypatch.setattr(website_auth.settings, "main_bot_username", "@PhantomMainBot", raising=False)
    monkeypatch.setattr(website_auth.secrets, "token_hex", lambda _n: "c" * 32)

    response = await website_auth.create_link(json_request("POST", "/api/v1/auth/telegram/link"))
    body = json.loads(response.text)

    assert body["telegram_url"] == f"https://t.me/PhantomMainBot?start=link_{'c' * 32}"
    assert stored["account_id"] == "account-1"
    assert stored["used_at"] is None
