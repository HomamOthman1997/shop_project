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
