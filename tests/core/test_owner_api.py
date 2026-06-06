import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services.platform import owner_api
from services.platform.website_auth import WebsiteAuthContext


def test_register_owner_api_routes():
    app = web.Application()

    owner_api.register_owner_api_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/api/v1/owner/dashboard") in routes
    assert ("GET", "/api/v1/owner/queues") in routes
    assert ("GET", "/api/v1/owner/digital/orders") in routes
    assert ("POST", "/api/v1/owner/digital/orders/{order_id}/action") in routes
    assert ("GET", "/api/v1/owner/numbers/refund-reviews") in routes
    assert ("POST", "/api/v1/owner/numbers/refund-reviews/{order_id}/resolve") in routes
    assert ("GET", "/api/v1/owner/settings") in routes
    assert ("PUT", "/api/v1/owner/settings") in routes
    assert ("PATCH", "/api/v1/owner/payment-methods/{method_code}") in routes
    assert ("GET", "/api/v1/owner/recharge-reviews") in routes
    assert ("POST", "/api/v1/owner/recharge-reviews/{request_id}/action") in routes
    assert ("GET", "/api/v1/owner/identity-reviews") in routes
    assert ("POST", "/api/v1/owner/identity-reviews/{review_id}/action") in routes
    assert ("GET", "/api/v1/owner/support-tickets") in routes
    assert ("POST", "/api/v1/owner/support-tickets/{ticket_id}/action") in routes


@pytest.mark.asyncio
async def test_owner_dashboard_returns_metrics_and_management_catalog(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def count(collection, query):
        return {"website_accounts": 12, "orders": 3}.get(collection, 1)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "_count", count)

    response = await owner_api.owner_dashboard(make_mocked_request("GET", "/api/v1/owner/dashboard"))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["owner"]["email"] == "homamothman1@gmail.com"
    assert payload["metrics"]["website_accounts"] == 12
    assert payload["metrics"]["open_numbers_orders"] == 3
    assert any(section["key"] == "finance" for section in payload["sections"])
    assert any(
        item["key"] == "digital_orders"
        for section in payload["sections"]
        for item in section["items"]
    )


@pytest.mark.asyncio
async def test_owner_queues_returns_sanitized_pending_rows(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def recent(collection, query, *, projection, limit=8):
        if collection == "recharge_requests":
            return [{"_id": "r-1", "user_id": 12, "status": "pending", "method": "USDT", "paid_amount": "10"}]
        if collection == "orders":
            return [{"_id": "o-1", "user_id": 13, "status": "pending", "manual_item_name": "PUBG 60 UC", "price": 1.0}]
        return []

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "_recent", recent)

    response = await owner_api.owner_queues(make_mocked_request("GET", "/api/v1/owner/queues"))
    payload = json.loads(response.text)

    assert payload["queues"]["recharge"][0]["title"] == "USDT"
    assert payload["queues"]["digital"][0]["title"] == "PUBG 60 UC"
    assert payload["queues"]["identity"] == []
    assert "projection" not in payload


@pytest.mark.asyncio
async def test_owner_digital_order_action_uses_shared_manual_action(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def execute(*, auth, order_id, body, rate_limit=None):
        calls["auth"] = auth
        calls["order_id"] = order_id
        calls["body"] = body
        return web.json_response({"ok": True, "action": body["action"]})

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "execute_manual_order_action", execute)
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/digital/orders/order-1/action",
        match_info={"order_id": "order-1"},
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps({"action": "complete", "notify_user": True}).encode()

    response = await owner_api.owner_digital_order_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth"].scopes == ("*",)
    assert calls["auth"].user_id == 900000000001
    assert calls["order_id"] == "order-1"
    assert calls["body"]["action"] == "complete"
    assert payload["action"] == "complete"


@pytest.mark.asyncio
async def test_owner_resolve_numbers_refund_review_marks_review_only(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def resolve(**kwargs):
        calls.update(kwargs)
        return {
            "_id": kwargs["order_id"],
            "temp_refund_support_review_status": "resolved",
            "temp_refund_support_review_resolution": kwargs["resolution"],
            "temp_refund_support_review_notes": kwargs["notes"],
            "number_mode": "temp",
        }

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "resolve_api_temp_refund_support_review", resolve)
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/numbers/refund-reviews/order-1/resolve",
        match_info={"order_id": "order-1"},
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps({"resolution": "Checked manually", "notes": "No financial action"}).encode()

    response = await owner_api.owner_resolve_numbers_refund_review(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["actor_user_id"] == 900000000001
    assert calls["reseller_id"] is None
    assert calls["resolution"] == "Checked manually"
    assert payload["review"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_owner_settings_returns_finance_alerts_and_routing(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def system_setting(doc_id):
        if doc_id == "owner_notifications":
            return {"chat_id": -1001, "message_thread_id": 4}
        return None

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "get_owner_payment_methods", lambda: _async_value([{"code": "owner_crypto_usdt"}]))
    monkeypatch.setattr(owner_api, "get_owner_exchange_rate", lambda: _async_value(13500.0))
    monkeypatch.setattr(owner_api, "get_digital_products_markup_percent", lambda: _async_value(4.0))
    monkeypatch.setattr(owner_api, "get_provider_balance_alert_settings", lambda: _async_value({"enabled": True, "threshold_usd": 2.0}))
    monkeypatch.setattr(owner_api, "get_all_support_targets", lambda: _async_value({"numbers": {"chat_id": -1002}}))
    monkeypatch.setattr(owner_api, "get_bot_logs_target", lambda: _async_value(None))
    monkeypatch.setattr(owner_api, "_system_setting", system_setting)

    response = await owner_api.owner_settings(make_mocked_request("GET", "/api/v1/owner/settings"))
    payload = json.loads(response.text)

    assert payload["finance"]["exchange_rate"] == 13500.0
    assert payload["finance"]["numbers_markup_editable"] is False
    assert payload["alerts"]["threshold_usd"] == 2.0
    assert payload["routing"]["owner_notifications"]["bound"] is True
    assert payload["routing"]["support"]["numbers"]["chat_id"] == -1002


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_owner_update_settings_validates_and_applies_supported_setting(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def set_markup(value):
        calls["markup"] = value

    async def settings(_request):
        return web.json_response({"ok": True})

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "set_digital_products_markup_percent", set_markup)
    monkeypatch.setattr(owner_api, "owner_settings", settings)
    request = make_mocked_request("PUT", "/api/v1/owner/settings", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"key": "digital_markup_percent", "value": 7.5}).encode()

    response = await owner_api.owner_update_settings(request)

    assert response.status == 200
    assert calls["markup"] == 7.5

    invalid = make_mocked_request("PUT", "/api/v1/owner/settings", headers={"Content-Type": "application/json"})
    invalid._read_bytes = json.dumps({"key": "numbers_markup_percent", "value": 20}).encode()
    invalid_response = await owner_api.owner_update_settings(invalid)
    assert invalid_response.status == 400


@pytest.mark.asyncio
async def test_owner_update_payment_method_only_accepts_supported_fields(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def update(code, **kwargs):
        calls["code"] = code
        calls["kwargs"] = kwargs
        return True

    async def settings(_request):
        return web.json_response({"ok": True})

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "update_owner_payment_method", update)
    monkeypatch.setattr(owner_api, "owner_settings", settings)
    request = make_mocked_request(
        "PATCH",
        "/api/v1/owner/payment-methods/owner_crypto_usdt",
        match_info={"method_code": "owner_crypto_usdt"},
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps({"target": "0x123", "enabled": False, "unsafe": "ignored"}).encode()

    response = await owner_api.owner_update_payment_method(request)

    assert response.status == 200
    assert calls["code"] == "owner_crypto_usdt"
    assert calls["kwargs"] == {"target": "0x123", "enabled": False}


@pytest.mark.asyncio
async def test_owner_recharge_accept_uses_shared_financial_decision(monkeypatch):
    calls = {}
    request_id = "507f1f77bcf86cd799439011"

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    reads = 0

    async def find_one(request_oid):
        nonlocal reads
        reads += 1
        return {"_id": request_oid, "status": "pending" if reads == 1 else "accepted", "amount": 10, "user_id": 7, "reseller_id": 8}

    async def update(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"_id": args[0], "status": "accepted", "amount": 10, "user_id": 7, "reseller_id": 8}

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "_recharge_request", find_one)
    monkeypatch.setattr(owner_api, "update_recharge_request", update)
    request = make_mocked_request("POST", f"/api/v1/owner/recharge-reviews/{request_id}/action", match_info={"request_id": request_id})
    request._read_bytes = json.dumps({"action": "accept", "approved_amount": 9.5}).encode()

    response = await owner_api.owner_recharge_review_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["args"][1] == "accepted"
    assert calls["kwargs"]["approved_amount"] == 9.5
    assert payload["review"]["status"] == "accepted"


@pytest.mark.asyncio
async def test_owner_identity_reject_requires_reason(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    request = make_mocked_request("POST", "/api/v1/owner/identity-reviews/review-1/action", match_info={"review_id": "review-1"})
    request._read_bytes = json.dumps({"action": "reject", "note": ""}).encode()

    response = await owner_api.owner_identity_review_action(request)

    assert response.status == 400


@pytest.mark.asyncio
async def test_owner_support_action_uses_shared_ticket_state(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def get_ticket(_ticket_id):
        return {"_id": "507f1f77bcf86cd799439011", "ticket_no": 4, "status": "open", "category": "numbers"}

    async def solve(ticket_id, *, actor_id):
        calls["ticket_id"] = ticket_id
        calls["actor_id"] = actor_id

    async def send(_ticket, _text):
        return True

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "get_support_ticket", get_ticket)
    monkeypatch.setattr(owner_api, "mark_support_ticket_solved", solve)
    monkeypatch.setattr(owner_api, "send_ticket_message", send)
    request = make_mocked_request("POST", "/api/v1/owner/support-tickets/507f1f77bcf86cd799439011/action", match_info={"ticket_id": "507f1f77bcf86cd799439011"})
    request._read_bytes = json.dumps({"action": "solve"}).encode()

    response = await owner_api.owner_support_ticket_action(request)

    assert response.status == 200
    assert calls == {"ticket_id": "507f1f77bcf86cd799439011", "actor_id": 900000000001}
