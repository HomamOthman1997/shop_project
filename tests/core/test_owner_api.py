import ast
import base64
import inspect
import json
import textwrap
from datetime import UTC, datetime

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from bson import ObjectId

from services.numbers import customer_flows
from services.platform import owner_api
from services.platform.website_auth import WebsiteAuthContext


def test_register_owner_api_routes():
    app = web.Application()

    owner_api.register_owner_api_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/api/v1/owner/dashboard") in routes
    assert ("GET", "/api/v1/owner/queues") in routes
    assert ("GET", "/api/v1/owner/users") in routes
    assert ("GET", "/api/v1/owner/users/{customer_id}") in routes
    assert ("POST", "/api/v1/owner/users/{customer_id}/action") in routes
    assert ("GET", "/api/v1/owner/finance/audit") in routes
    assert ("GET", "/api/v1/owner/system/status") in routes
    assert ("POST", "/api/v1/owner/system/test-log") in routes
    assert ("GET", "/api/v1/owner/audit") in routes
    assert ("GET", "/api/v1/owner/resellers") in routes
    assert ("GET", "/api/v1/owner/resellers/{reseller_id}") in routes
    assert ("GET", "/api/v1/owner/digital/orders") in routes
    assert ("POST", "/api/v1/owner/digital/orders/{order_id}/action") in routes
    assert ("GET", "/api/v1/owner/custom-preorders") in routes
    assert ("POST", "/api/v1/owner/custom-preorders/{preorder_id}/action") in routes
    assert ("POST", "/api/v1/owner/custom-preorders/{preorder_id}/attachment") in routes
    assert ("GET", "/api/v1/owner/custom-catalog") in routes
    assert ("POST", "/api/v1/owner/custom-catalog/nodes") in routes
    assert ("GET", "/api/v1/owner/custom-catalog/nodes/{node_id}") in routes
    assert ("PATCH", "/api/v1/owner/custom-catalog/nodes/{node_id}") in routes
    assert ("DELETE", "/api/v1/owner/custom-catalog/nodes/{node_id}") in routes
    assert ("POST", "/api/v1/owner/custom-catalog/nodes/{node_id}/action") in routes
    assert ("POST", "/api/v1/owner/custom-catalog/nodes/{node_id}/inventory") in routes
    assert ("GET", "/api/v1/owner/custom-catalog/nodes/{node_id}/stock-events") in routes
    assert ("GET", "/api/v1/owner/numbers/refund-reviews") in routes
    assert ("POST", "/api/v1/owner/numbers/refund-reviews/{order_id}/resolve") in routes
    assert ("GET", "/api/v1/owner/settings") in routes
    assert ("PUT", "/api/v1/owner/settings") in routes
    assert ("POST", "/api/v1/owner/routing-targets/{target_key}") in routes
    assert ("PATCH", "/api/v1/owner/payment-methods/{method_code}") in routes
    assert ("GET", "/api/v1/owner/recharge-reviews") in routes
    assert ("GET", "/api/v1/owner/recharge-reviews/{request_id}/proof") in routes
    assert ("POST", "/api/v1/owner/recharge-reviews/{request_id}/action") in routes
    assert ("GET", "/api/v1/owner/identity-reviews") in routes
    assert ("POST", "/api/v1/owner/identity-reviews/{review_id}/action") in routes
    assert ("GET", "/api/v1/owner/support-tickets") in routes
    assert ("GET", "/api/v1/owner/support-tickets/{ticket_id}") in routes
    assert ("POST", "/api/v1/owner/support-tickets/{ticket_id}/attachment") in routes
    assert ("POST", "/api/v1/owner/support-tickets/{ticket_id}/action") in routes
    assert ("GET", "/api/v1/owner/api-keys") in routes
    assert ("POST", "/api/v1/owner/api-keys") in routes
    assert ("POST", "/api/v1/owner/api-keys/{key_id}/revoke") in routes
    assert ("GET", "/api/v1/owner/webhooks") in routes
    assert ("POST", "/api/v1/owner/webhooks") in routes
    assert ("POST", "/api/v1/owner/webhooks/{webhook_id}/revoke") in routes
    assert ("GET", "/api/v1/owner/provider-readiness") in routes
    assert ("GET", "/api/v1/owner/provider-webhook-events") in routes
    assert ("POST", "/api/v1/owner/provider-webhook-events/{event_id}/replay") in routes
    assert ("GET", "/api/v1/owner/digital-provider-sources") in routes
    assert ("POST", "/api/v1/owner/digital-provider-sources/scan") in routes
    assert ("POST", "/api/v1/owner/digital-provider-sources/{source_id}/action") in routes
    assert ("GET", "/api/v1/owner/bot-creation-reviews") in routes
    assert ("POST", "/api/v1/owner/bot-creation-reviews/{request_id}/action") in routes
    assert ("GET", "/api/v1/owner/bots") in routes
    assert ("POST", "/api/v1/owner/bots/{bot_id}/subscription/action") in routes
    assert ("POST", "/api/v1/owner/reseller-deposits") in routes
    assert ("POST", "/api/v1/owner/broadcast") in routes


def test_available_owner_management_items_point_to_registered_owner_routes():
    app = web.Application()
    owner_api.register_owner_api_routes(app)
    routes = {route.resource.canonical for route in app.router.routes()}

    available = [
        item
        for section in owner_api._management_sections()
        for item in section["items"]
        if item["status"] == "available"
    ]

    assert available
    assert all(item["endpoint"].startswith("/api/v1/owner/") for item in available)
    assert all(item["endpoint"] in routes for item in available)


def test_all_mutating_owner_routes_write_an_audit_event():
    app = web.Application()
    owner_api.register_owner_api_routes(app)

    missing_audit = []
    for route in app.router.routes():
        if route.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            continue
        if not route.resource.canonical.startswith("/api/v1/owner/"):
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(route.handler)))
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if "_write_owner_audit" not in calls:
            missing_audit.append(f"{route.method} {route.resource.canonical} ({route.handler.__name__})")

    assert missing_audit == []


@pytest.mark.asyncio
async def test_owner_paged_rows_returns_next_offset_and_applies_offset():
    class Cursor:
        def __init__(self):
            self.rows = [{"id": index} for index in range(7)]

        def skip(self, offset):
            self.rows = self.rows[offset:]
            return self

        def limit(self, limit):
            self.rows = self.rows[:limit]
            return self

        async def to_list(self, length=None):
            return self.rows[:length]

    request = make_mocked_request("GET", "/api/v1/owner/example?limit=2&offset=3")
    rows, pagination = await owner_api._paged_rows(Cursor(), request)

    assert rows == [{"id": 3}, {"id": 4}]
    assert pagination == {"offset": 3, "limit": 2, "has_more": True, "next_offset": 5}


def test_owner_operational_lists_use_shared_pagination_contract():
    handlers = [
        owner_api.owner_admin_audit,
        owner_api.owner_digital_orders,
        owner_api.owner_custom_preorders,
        owner_api.owner_recharge_reviews,
        owner_api.owner_identity_reviews,
        owner_api.owner_support_tickets,
        owner_api.owner_bot_creation_reviews,
        owner_api.owner_bots,
        owner_api.owner_api_keys,
        owner_api.owner_webhooks,
    ]

    for handler in handlers:
        assert "_paged_rows" in inspect.getsource(handler), handler.__name__
        assert '"pagination"' in inspect.getsource(handler), handler.__name__

    assert '"pagination"' in inspect.getsource(owner_api.owner_numbers_refund_reviews)
    assert '"pagination"' in inspect.getsource(owner_api.owner_provider_webhook_events)
    assert '"pagination"' in inspect.getsource(owner_api.owner_digital_provider_sources)


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
async def test_owner_admin_audit_filters_by_action_target_and_search(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    class Cursor:
        def sort(self, *_args):
            return self

        def limit(self, value):
            assert value == 26
            return self

        async def to_list(self, length=None):
            assert length == 26
            return []

    class AuditCollection:
        def __init__(self):
            self.query = None

        def find(self, query):
            self.query = query
            return Cursor()

    class FakeDb:
        def __init__(self):
            self.owner_admin_audit = AuditCollection()

    fake_db = FakeDb()
    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "db", fake_db)
    request = make_mocked_request(
        "GET",
        "/api/v1/owner/audit?action=recharge_review.accept&target_type=recharge_request&q=900000000123&limit=25",
    )

    response = await owner_api.owner_admin_audit(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["filters"] == {"q": "900000000123", "action": "recharge_review.accept", "target_type": "recharge_request"}
    assert fake_db.owner_admin_audit.query["action"] == "recharge_review.accept"
    assert fake_db.owner_admin_audit.query["target_type"] == "recharge_request"
    assert {"actor_id": 900000000123} in fake_db.owner_admin_audit.query["$or"]


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
async def test_owner_user_detail_returns_account_wallet_and_activity(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    class FakeCursor:
        def __init__(self, rows):
            self.rows = list(rows)

        def sort(self, *_args):
            return self

        def limit(self, limit):
            self.rows = self.rows[:limit]
            return self

        async def to_list(self, length=None):
            return self.rows[:length] if length is not None else list(self.rows)

    class FakeCollection:
        def __init__(self, rows):
            self.rows = list(rows)

        async def find_one(self, query, *args, **kwargs):
            for row in self.rows:
                ok = True
                for key, value in query.items():
                    if isinstance(value, dict) and "$in" in value:
                        ok = row.get(key) in value["$in"]
                    elif row.get(key) != value:
                        ok = False
                if ok:
                    return row
            return None

        def find(self, query=None, *args, **kwargs):
            query = query or {}
            rows = []
            for row in self.rows:
                ok = True
                for key, value in query.items():
                    if isinstance(value, dict) and "$in" in value:
                        ok = row.get(key) in value["$in"]
                    elif row.get(key) != value:
                        ok = False
                if ok:
                    rows.append(row)
            return FakeCursor(rows)

    class FakeDb:
        website_accounts = FakeCollection([
            {"_id": "acct-1", "customer_id": 900000000123, "email": "user@example.com", "email_verified_at": datetime(2026, 6, 7, tzinfo=UTC), "status": "active"}
        ])
        users = FakeCollection([
            {"telegram_id": 900000000123, "username": "user", "banned": False}
        ])
        wallets = FakeCollection([
            {"wallet_key": "user:900000000123:user:900000000123", "owner_type": "user", "owner_id": 900000000123, "reseller_id": 900000000123, "wallet_type": "user", "balance": 12.5}
        ])
        orders = FakeCollection([
            {"_id": "order-1", "user_id": 900000000123, "status": "paid", "service_type": "core", "retail_amount": 2.0}
        ])
        recharge_requests = FakeCollection([
            {"_id": "rch-1", "user_id": 900000000123, "status": "accepted", "amount": 10.0}
        ])

    async def entries(user_id, reseller_id, limit=12):
        return [{"_id": "tx-1", "direction": "credit", "amount": 12.5, "reason": "manual", "balance_after": 12.5, "created_at": datetime(2026, 6, 7, tzinfo=UTC)}]

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "db", FakeDb())
    monkeypatch.setattr(owner_api, "list_user_wallet_entries", entries)

    request = make_mocked_request("GET", "/api/v1/owner/users/900000000123", match_info={"customer_id": "900000000123"})
    response = await owner_api.owner_user_detail(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["user"]["email"] == "user@example.com"
    assert payload["wallet"]["balance"] == 12.5
    assert payload["ledger"][0]["reason"] == "manual"
    assert payload["orders"][0]["id"] == "order-1"


def test_public_owner_account_payload_treats_banned_website_account_as_banned():
    payload = owner_api._public_account_payload(
        {"_id": "acct-1", "customer_id": 900000000123, "email": "user@example.com", "status": "banned"},
        None,
    )

    assert payload["banned"] is True
    assert payload["status"] == "banned"


@pytest.mark.asyncio
async def test_owner_users_supports_offset_pagination(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    class Cursor:
        def __init__(self, rows):
            self.rows = list(rows)

        def sort(self, *_args):
            return self

        def skip(self, offset):
            self.rows = self.rows[offset:]
            return self

        def limit(self, limit):
            self.rows = self.rows[:limit]
            return self

        async def to_list(self, length=None):
            return self.rows[:length] if length is not None else self.rows

    class Collection:
        def __init__(self, rows):
            self.rows = rows

        def find(self, *_args, **_kwargs):
            return Cursor(self.rows)

        async def find_one(self, *_args, **_kwargs):
            return None

    class FakeDb:
        website_accounts = Collection(
            [{"_id": f"acct-{index}", "customer_id": index, "email": f"user{index}@example.com"} for index in range(5)]
        )
        users = Collection([])
        wallets = Collection([])

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "db", FakeDb())

    response = await owner_api.owner_users(make_mocked_request("GET", "/api/v1/owner/users?limit=2&offset=2"))
    payload = json.loads(response.text)

    assert [row["customer_id"] for row in payload["users"]] == [2, 3]
    assert payload["pagination"] == {"offset": 2, "limit": 2, "has_more": True, "next_offset": 4}


@pytest.mark.asyncio
async def test_owner_resellers_pages_across_all_bot_and_wallet_owners(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    class Cursor:
        def __init__(self, rows):
            self.rows = list(rows)

        def sort(self, *_args):
            return self

        async def to_list(self, length=None):
            return self.rows[:length] if length is not None else self.rows

    class Collection:
        def __init__(self, rows, distinct_ids):
            self.rows = rows
            self.distinct_ids = distinct_ids

        async def distinct(self, _field, _query):
            return self.distinct_ids

        def find(self, query=None, *_args, **_kwargs):
            query = query or {}
            wanted = set((query.get("owner_id") or {}).get("$in") or [])
            rows = [row for row in self.rows if not wanted or row.get("owner_id") in wanted]
            return Cursor(rows)

    class EmptyUsers:
        def find(self, *_args, **_kwargs):
            return Cursor([])

    class FakeDb:
        bots = Collection([{"bot_id": 20, "owner_id": 2, "active": True}], [4, 2, 1])
        wallets = Collection([], [3, 2])
        users = EmptyUsers()

    async def balance(reseller_id, *, wallet_type):
        return float(reseller_id) if wallet_type == "main" else 0.0

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "db", FakeDb())
    monkeypatch.setattr(owner_api, "get_reseller_wallet_balance", balance)

    response = await owner_api.owner_resellers(make_mocked_request("GET", "/api/v1/owner/resellers?limit=2&offset=1"))
    payload = json.loads(response.text)

    assert [row["reseller_id"] for row in payload["resellers"]] == [2, 3]
    assert payload["pagination"] == {"offset": 1, "limit": 2, "has_more": True, "next_offset": 3}


@pytest.mark.asyncio
async def test_owner_user_action_bans_website_only_account(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    class FakeAccounts:
        def __init__(self):
            self.row = {"_id": "acct-1", "customer_id": 900000000123, "email": "user@example.com", "status": "active"}
            self.updated = None

        async def find_one(self, query):
            return dict(self.row) if query == {"customer_id": 900000000123} else None

        async def update_one(self, query, update):
            self.updated = (query, update)
            self.row.update(update["$set"])

    class EmptyUsers:
        async def find_one(self, _query):
            return None

        async def update_one(self, *_args, **_kwargs):
            raise AssertionError("website-only ban must not require a Telegram user update")

    class FakeDb:
        def __init__(self):
            self.website_accounts = FakeAccounts()
            self.users = EmptyUsers()

    fake_db = FakeDb()

    async def audit(**_kwargs):
        return None

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "db", fake_db)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/users/900000000123/action",
        headers={"Content-Type": "application/json"},
        match_info={"customer_id": "900000000123"},
    )
    request._read_bytes = json.dumps({"action": "ban"}).encode("utf-8")

    response = await owner_api.owner_user_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert fake_db.website_accounts.updated[0] == {"customer_id": 900000000123}
    assert fake_db.website_accounts.row["status"] == "banned"
    assert payload["user"]["banned"] is True


@pytest.mark.asyncio
async def test_owner_finance_audit_delegates_to_financial_scan(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    calls = {}

    async def scan(*, days, max_rows):
        calls["days"] = days
        calls["max_rows"] = max_rows
        return {"days": days, "since": datetime(2026, 6, 7, 9, 0, tzinfo=UTC), "negative_wallets_count": 1}

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "scan_financial_anomalies", scan)

    response = await owner_api.owner_finance_audit(make_mocked_request("GET", "/api/v1/owner/finance/audit?days=7&limit=5"))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["audit"]["negative_wallets_count"] == 1
    assert payload["audit"]["since"] == "2026-06-07T09:00:00+00:00"
    assert calls == {"days": 7, "max_rows": 5}


@pytest.mark.asyncio
async def test_owner_system_status_combines_runtime_and_routing(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def count(collection, query):
        return {"bots": 2, "orders": 3, "recharge_requests": 4}.get(collection, 0)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "_mongo_health", lambda: _async_value({"status": "healthy"}))
    monkeypatch.setattr(owner_api, "get_bot_logs_target", lambda: _async_value({"chat_id": -1001}))
    monkeypatch.setattr(owner_api, "get_provider_balance_alert_settings", lambda: _async_value({"enabled": True, "chat_id": -1002}))
    monkeypatch.setattr(owner_api, "get_all_support_targets", lambda: _async_value({"numbers": {"chat_id": -1003}, "services": {}}))
    monkeypatch.setattr(owner_api, "_count", count)
    monkeypatch.setattr(owner_api, "provider_readiness_rows", lambda: [{"status": "ready"}, {"status": "disabled"}])

    response = await owner_api.owner_system_status(make_mocked_request("GET", "/api/v1/owner/system/status"))
    payload = json.loads(response.text)["system"]

    assert response.status == 200
    assert payload["mongo"]["status"] == "healthy"
    assert payload["routing"]["logs_bound"] is True
    assert payload["routing"]["support_bound"] == 1
    assert payload["provider_readiness"] == {"ready": 1, "total": 2}


@pytest.mark.asyncio
async def test_owner_system_test_log_requires_bound_target(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "get_bot_logs_target", lambda: _async_value(None))

    response = await owner_api.owner_system_test_log(make_mocked_request("POST", "/api/v1/owner/system/test-log"))

    assert response.status == 409


@pytest.mark.asyncio
async def test_owner_digital_order_action_uses_shared_manual_action(monkeypatch):
    calls = {}
    audit_calls = []

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

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "execute_manual_order_action", execute)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/digital/orders/order-1/action",
        match_info={"order_id": "order-1"},
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps({"action": "complete", "notify_user": True, "delivery_text": "private delivery"}).encode()

    response = await owner_api.owner_digital_order_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth"].scopes == ("*",)
    assert calls["auth"].user_id == 900000000001
    assert calls["order_id"] == "order-1"
    assert calls["body"]["action"] == "complete"
    assert payload["action"] == "complete"
    assert audit_calls[0]["action"] == "digital_order.complete"
    assert audit_calls[0]["target_id"] == "order-1"
    assert "private delivery" not in json.dumps(audit_calls[0])


@pytest.mark.asyncio
async def test_owner_digital_orders_include_owner_details_and_actions(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext(
            account_id="owner-1",
            customer_id=900000000001,
            email="homamothman1@gmail.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def sort(self, *_args):
            return self

        def limit(self, *_args):
            return self

        async def to_list(self, *, length):
            return self.rows[:length]

    class FakeOrders:
        def find(self, query):
            self.query = query
            return FakeCursor(
                [
                    {
                        "_id": "order-1",
                        "user_id": 123,
                        "reseller_id": 456,
                        "status": "paid",
                        "fulfillment_mode": "manual_topup",
                        "manual_fulfillment_status": "processing",
                        "manual_execution_route": "auto_api",
                        "manual_route_updated_by": 900000000001,
                        "manual_route_updated_at": datetime(2026, 6, 7, 8, 30, tzinfo=UTC),
                        "manual_item_name": "PUBG 60 UC",
                        "player_id": "555",
                        "price": 1.5,
                        "provider_code": "bittopup",
                        "provider_ref_id": "pubg#60",
                        "provider_order_id": "api-1",
                        "service_type": "core_digital_products",
                        "api_order_source": "website",
                        "created_at": datetime(2026, 6, 7, 8, 0, tzinfo=UTC),
                    }
                ]
            )

    class FakeDb:
        orders = FakeOrders()

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "db", FakeDb())

    response = await owner_api.owner_digital_orders(make_mocked_request("GET", "/api/v1/owner/digital/orders?status=processing"))
    payload = json.loads(response.text)
    order = payload["orders"][0]

    assert response.status == 200
    assert order["id"] == "order-1"
    assert order["available_actions"] == ["claim", "auto_api", "future", "complete", "refund"]
    assert order["owner_details"]["user_id"] == "123"
    assert order["owner_details"]["reseller_id"] == "456"
    assert order["owner_details"]["provider_ref_id"] == "pubg#60"
    assert order["owner_details"]["provider_order_id"] == "api-1"
    assert order["owner_details"]["execution_route"] == "auto_api"


@pytest.mark.asyncio
async def test_owner_resolve_numbers_refund_review_marks_review_only(monkeypatch):
    calls = {}
    audit_calls = []

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

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "resolve_api_temp_refund_support_review", resolve)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
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
    assert audit_calls[0]["action"] == "numbers_refund_review.resolve"
    assert audit_calls[0]["metadata"]["number_mode"] == "temp"
    assert "Checked manually" not in json.dumps(audit_calls[0])
    assert "No financial action" not in json.dumps(audit_calls[0])


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
    monkeypatch.setattr(owner_api, "get_numbers_markup_percent", lambda: _async_value(3.5))
    monkeypatch.setattr(owner_api, "get_provider_balance_alert_settings", lambda: _async_value({"enabled": True, "threshold_usd": 2.0}))
    monkeypatch.setattr(owner_api, "get_all_support_targets", lambda: _async_value({"numbers": {"chat_id": -1002}}))
    monkeypatch.setattr(owner_api, "get_bot_logs_target", lambda: _async_value(None))
    monkeypatch.setattr(owner_api, "_system_setting", system_setting)

    response = await owner_api.owner_settings(make_mocked_request("GET", "/api/v1/owner/settings"))
    payload = json.loads(response.text)

    assert payload["finance"]["exchange_rate"] == 13500.0
    assert payload["finance"]["numbers_markup_percent"] == 3.5
    assert payload["finance"]["numbers_markup_editable"] is True
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

    async def set_numbers(value):
        calls["numbers_markup"] = value

    async def settings(_request):
        return web.json_response({"ok": True})

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "set_digital_products_markup_percent", set_markup)
    monkeypatch.setattr(owner_api, "set_numbers_markup_percent", set_numbers)
    monkeypatch.setattr(owner_api, "owner_settings", settings)
    request = make_mocked_request("PUT", "/api/v1/owner/settings", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"key": "digital_markup_percent", "value": 7.5}).encode()

    response = await owner_api.owner_update_settings(request)

    assert response.status == 200
    assert calls["markup"] == 7.5

    numbers_request = make_mocked_request("PUT", "/api/v1/owner/settings", headers={"Content-Type": "application/json"})
    numbers_request._read_bytes = json.dumps({"key": "numbers_markup_percent", "value": 20}).encode()
    numbers_response = await owner_api.owner_update_settings(numbers_request)
    assert numbers_response.status == 200
    assert calls["numbers_markup"] == 20.0


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
async def test_owner_update_routing_target_binds_support_topic(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def bind(category, **kwargs):
        calls["category"] = category
        calls.update(kwargs)

    async def settings(_request):
        return web.json_response({"ok": True})

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "bind_support_target", bind)
    monkeypatch.setattr(owner_api, "owner_settings", settings)
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/routing-targets/support_numbers",
        match_info={"target_key": "support_numbers"},
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps({"chat_id": -1001, "message_thread_id": 9}).encode()

    response = await owner_api.owner_update_routing_target(request)

    assert response.status == 200
    assert calls == {"category": "numbers", "chat_id": -1001, "message_thread_id": 9}


@pytest.mark.asyncio
async def test_owner_bot_subscription_action_delegates_activation(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def activate(bot_id, *, months, note=None):
        calls.update({"bot_id": bot_id, "months": months, "note": note})
        return {"status": "active", "renewal_plan_months": months, "renewal_charge_usd": 10, "subscription_ends_at": None}

    class BotsCollection:
        async def find_one(self, query, projection=None):
            return {"bot_id": query["bot_id"], "owner_id": 7, "active": True, "subscription": {"status": "active", "renewal_plan_months": 6}}

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "activate_bot_subscription", activate)
    monkeypatch.setattr(owner_api.db, "bots", BotsCollection())
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/bots/123/subscription/action",
        match_info={"bot_id": "123"},
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps({"action": "activate", "months": 6, "note": "paid"}).encode()

    response = await owner_api.owner_bot_subscription_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls == {"bot_id": 123, "months": 6, "note": "paid"}
    assert payload["bot"]["bot_id"] == 123


@pytest.mark.asyncio
async def test_owner_reseller_deposit_credits_main_wallet(monkeypatch):
    calls = {}
    audit_calls = []

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def credit(**kwargs):
        calls.update(kwargs)
        return {"_id": "ledger-1"}

    class LedgerEntries:
        async def update_one(self, *_args, **_kwargs):
            return None

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "credit_reseller_main_wallet", credit)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    monkeypatch.setattr(owner_api.db, "ledger_entries", LedgerEntries())
    request = make_mocked_request("POST", "/api/v1/owner/reseller-deposits", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"reseller_id": 77, "amount": 12.5, "note": "cash"}).encode()

    response = await owner_api.owner_reseller_deposit(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["reseller_id"] == 77
    assert calls["amount"] == 12.5
    assert calls["actor_id"] == 900000000001
    assert payload["deposit"]["ledger_entry_id"] == "ledger-1"
    assert audit_calls[0]["metadata"] == {"amount": 12.5}
    assert "cash" not in json.dumps(audit_calls[0])


@pytest.mark.asyncio
async def test_owner_broadcast_uses_delivery_helper(monkeypatch):
    calls = {}
    audit_calls = []

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def send(**kwargs):
        calls.update(kwargs)
        return True

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "send_owner_broadcast", send)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request("POST", "/api/v1/owner/broadcast", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"chat_id": -1001, "message_thread_id": 3, "text": "Hello owners"}).encode()

    response = await owner_api.owner_broadcast(request)

    assert response.status == 200
    assert calls == {"chat_id": -1001, "message_thread_id": 3, "text": "Hello owners"}
    assert audit_calls[0]["action"] == "broadcast.send"
    assert audit_calls[0]["metadata"] == {"message_thread_id": 3, "length": 12}
    assert "Hello owners" not in json.dumps(audit_calls[0])


@pytest.mark.asyncio
async def test_owner_recharge_accept_uses_shared_financial_decision(monkeypatch):
    calls = {}
    audit_calls = []
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

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "_recharge_request", find_one)
    monkeypatch.setattr(owner_api, "update_recharge_request", update)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request("POST", f"/api/v1/owner/recharge-reviews/{request_id}/action", match_info={"request_id": request_id})
    request._read_bytes = json.dumps({"action": "accept", "approved_amount": 9.5}).encode()

    response = await owner_api.owner_recharge_review_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["args"][1] == "accepted"
    assert calls["kwargs"]["approved_amount"] == 9.5
    assert payload["review"]["status"] == "accepted"
    assert audit_calls[0]["action"] == "recharge_review.accept"
    assert audit_calls[0]["metadata"]["user_id"] == 7


def test_recharge_proof_storage_keeps_uploaded_bytes_for_owner_dashboard():
    stored = customer_flows._recharge_proof_storage(
        proof_bytes=b"proof-bytes",
        proof_filename="receipt.jpg",
        proof_content_type="image/jpeg",
    )

    assert stored["filename"] == "receipt.jpg"
    assert stored["content_type"] == "image/jpeg"
    assert stored["size_bytes"] == len(b"proof-bytes")
    assert base64.b64decode(stored["content_base64"].encode("ascii")) == b"proof-bytes"


@pytest.mark.asyncio
async def test_owner_recharge_reviews_expose_stored_proof_url(monkeypatch):
    request_id = ObjectId()
    row = {
        "_id": request_id,
        "user_id": 900000000123,
        "reseller_id": 900000000123,
        "wallet_type": "user",
        "method": "USDT",
        "amount": 10.0,
        "status": "pending",
        "details": {
            "proof_storage": {
                "filename": "receipt.jpg",
                "content_type": "image/jpeg",
                "content_base64": base64.b64encode(b"proof-bytes").decode("ascii"),
            }
        },
    }

    class Cursor:
        def sort(self, *_args):
            return self

        def skip(self, *_args):
            return self

        def limit(self, *_args):
            return self

        async def to_list(self, length=None):
            return [row]

    class RechargeRequests:
        def find(self, query):
            assert query == {"status": "pending"}
            return Cursor()

    monkeypatch.setattr(owner_api, "require_website_owner", lambda _request: __import__("asyncio").sleep(0, result=True))
    monkeypatch.setattr(owner_api, "db", type("Db", (), {"recharge_requests": RechargeRequests()})())

    response = await owner_api.owner_recharge_reviews(make_mocked_request("GET", "/api/v1/owner/recharge-reviews?status=pending"))
    payload = json.loads(response.text)

    review = payload["reviews"][0]
    assert review["has_proof"] is True
    assert review["proof_url"] == f"/api/v1/owner/recharge-reviews/{request_id}/proof"
    assert review["proof_filename"] == "receipt.jpg"


@pytest.mark.asyncio
async def test_owner_recharge_review_proof_downloads_stored_upload(monkeypatch):
    request_id = ObjectId()
    row = {
        "_id": request_id,
        "details": {
            "proof_storage": {
                "filename": "receipt.jpg",
                "content_type": "image/jpeg",
                "content_base64": base64.b64encode(b"proof-bytes").decode("ascii"),
            }
        },
    }

    monkeypatch.setattr(owner_api, "require_website_owner", lambda _request: __import__("asyncio").sleep(0, result=True))
    monkeypatch.setattr(owner_api, "_recharge_request", lambda _request_id: __import__("asyncio").sleep(0, result=row))

    response = await owner_api.owner_recharge_review_proof(
        make_mocked_request(
            "GET",
            f"/api/v1/owner/recharge-reviews/{request_id}/proof",
            match_info={"request_id": str(request_id)},
        )
    )

    assert response.status == 200
    assert response.body == b"proof-bytes"
    assert response.content_type == "image/jpeg"
    assert response.headers["Content-Disposition"] == 'inline; filename="receipt.jpg"'


@pytest.mark.asyncio
async def test_owner_recharge_need_more_proof_clears_stored_upload(monkeypatch):
    request_id = ObjectId()
    updates = []
    audit_calls = []

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def recharge(_request_id):
        return {"_id": request_id, "status": "pending", "amount": 10, "user_id": 7, "reseller_id": 8}

    class RechargeRequests:
        async def find_one_and_update(self, query, update, **_kwargs):
            updates.append((query, update))
            return {"_id": request_id, "status": "need_more_proof", "amount": 10, "user_id": 7, "reseller_id": 8}

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "_recharge_request", recharge)
    monkeypatch.setattr(owner_api, "db", type("Db", (), {"recharge_requests": RechargeRequests()})())
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)

    request = make_mocked_request(
        "POST",
        f"/api/v1/owner/recharge-reviews/{request_id}/action",
        match_info={"request_id": str(request_id)},
    )
    request._read_bytes = json.dumps({"action": "need_more_proof", "note": "send clearer receipt"}).encode()

    response = await owner_api.owner_recharge_review_action(request)

    assert response.status == 200
    assert updates[0][1]["$set"]["proof_file_id"] is None
    assert updates[0][1]["$unset"] == {"details.proof_storage": ""}
    assert audit_calls[0]["action"] == "recharge_review.need_more_proof"


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
async def test_owner_identity_action_updates_website_account_by_customer_id(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    class IdentityRequests:
        async def find_one_and_update(self, query, update, **_kwargs):
            assert query == {"_id": "review-1", "status": "pending"}
            return {
                "_id": "review-1",
                "customer_id": 900000000123,
                "status": update["$set"]["status"],
                "review_note": update["$set"]["review_note"],
                "reviewed_by": update["$set"]["reviewed_by"],
            }

    class WebsiteAccounts:
        def __init__(self):
            self.updated = None

        async def update_one(self, query, update):
            self.updated = (query, update)

    class FakeDb:
        def __init__(self):
            self.identity_verification_requests = IdentityRequests()
            self.website_accounts = WebsiteAccounts()

    fake_db = FakeDb()
    audit_calls = []

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "db", fake_db)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request("POST", "/api/v1/owner/identity-reviews/review-1/action", match_info={"review_id": "review-1"})
    request._read_bytes = json.dumps({"action": "approve", "note": "ok"}).encode()

    response = await owner_api.owner_identity_review_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["review"]["status"] == "approved"
    assert fake_db.website_accounts.updated[0] == {"customer_id": 900000000123}
    assert fake_db.website_accounts.updated[1]["$set"]["identity_status"] == "approved"
    assert audit_calls[0]["action"] == "identity.approve"
    assert audit_calls[0]["metadata"]["customer_id"] == 900000000123


@pytest.mark.asyncio
async def test_owner_support_action_uses_shared_ticket_state(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def get_ticket(_ticket_id):
        return {
            "_id": "507f1f77bcf86cd799439011",
            "ticket_no": 4,
            "status": "open",
            "category": "numbers",
            "bug_triage": {"status": "confirmed", "marked_at": datetime(2026, 6, 7, 9, 10, tzinfo=UTC)},
            "bug_reward": {"status": "paid", "paid_at": datetime(2026, 6, 7, 9, 11, tzinfo=UTC)},
        }

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
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["ticket"]["bug_triage"]["marked_at"] == "2026-06-07T09:10:00+00:00"
    assert payload["ticket"]["bug_reward"]["paid_at"] == "2026-06-07T09:11:00+00:00"
    assert calls == {"ticket_id": "507f1f77bcf86cd799439011", "actor_id": 900000000001}


@pytest.mark.asyncio
async def test_owner_support_attachment_delivers_and_records(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def ticket(_ticket_id):
        return {"_id": "ticket-1", "source_bot_id": 5, "user_id": 7}

    async def deliver(_ticket, **kwargs):
        calls["deliver"] = kwargs
        return True, "document"

    async def audit(**_kwargs):
        return None

    class Part:
        def __init__(self, name, *, text="", content=b"", filename=""):
            self.name = name
            self.filename = filename
            self.headers = {"Content-Type": "application/octet-stream"}
            self._text = text
            self._content = content
            self._read = False

        async def text(self):
            return self._text

        async def read_chunk(self):
            if self._read:
                return b""
            self._read = True
            return self._content

    class Reader:
        def __init__(self):
            self.parts = iter([Part("caption", text="Invoice"), Part("attachment", content=b"file", filename="invoice.txt")])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.parts)
            except StopIteration:
                raise StopAsyncIteration

    class Collection:
        async def insert_one(self, doc):
            calls["message"] = doc

        async def update_one(self, query, update):
            calls["ticket_update"] = (query, update)

    class Request:
        match_info = {"ticket_id": "ticket-1"}
        headers = {"Content-Type": "multipart/form-data; boundary=x"}

        async def multipart(self):
            return Reader()

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "get_support_ticket", ticket)
    monkeypatch.setattr(owner_api, "send_ticket_attachment", deliver)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    monkeypatch.setattr(owner_api.db, "support_ticket_messages", Collection())
    monkeypatch.setattr(owner_api.db, "support_tickets", Collection())

    response = await owner_api.owner_support_ticket_attachment(Request())

    assert response.status == 200
    assert calls["deliver"]["content"] == b"file"
    assert calls["deliver"]["filename"] == "invoice.txt"
    assert calls["message"]["kind"] == "document"


@pytest.mark.asyncio
async def test_owner_custom_preorder_action_fulfills_with_delivery_text(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def fulfill(preorder_id, *, actor_id, delivery_text):
        calls.update({"preorder_id": preorder_id, "actor_id": actor_id, "delivery_text": delivery_text})
        return True, "fulfilled", {"_id": preorder_id, "status": "fulfilled", "service_name": "Account"}

    async def get_preorder(preorder_id):
        return {"_id": preorder_id, "status": "fulfilled", "service_name": "Account"}

    async def audit(**_kwargs):
        return None

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "fulfill_preorder_from_owner", fulfill)
    monkeypatch.setattr(owner_api, "get_preorder_request", get_preorder)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/custom-preorders/pre-1/action",
        match_info={"preorder_id": "pre-1"},
    )
    request._read_bytes = json.dumps({"action": "fulfill", "delivery_text": "CODE-123"}).encode()

    response = await owner_api.owner_custom_preorder_action(request)

    assert response.status == 200
    assert calls == {"preorder_id": "pre-1", "actor_id": 900000000001, "delivery_text": "CODE-123"}


@pytest.mark.asyncio
async def test_owner_custom_preorder_reject_requires_reason(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/custom-preorders/pre-1/action",
        match_info={"preorder_id": "pre-1"},
    )
    request._read_bytes = json.dumps({"action": "reject", "reason": ""}).encode()

    response = await owner_api.owner_custom_preorder_action(request)

    assert response.status == 400


@pytest.mark.asyncio
async def test_owner_create_custom_catalog_folder(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def root(owner_id, *, catalog_type):
        return {"_id": "root-1", "reseller_id": owner_id, "catalog_type": catalog_type, "node_type": "folder", "is_root": True}

    async def node(_node_id, *, reseller_id, catalog_type):
        return {"_id": "root-1", "reseller_id": reseller_id, "catalog_type": catalog_type, "node_type": "folder", "is_root": True}

    async def create(reseller_id, parent_id, name, *, catalog_type):
        calls.update({"reseller_id": reseller_id, "parent_id": parent_id, "name": name, "catalog_type": catalog_type})
        return {"_id": "folder-1", "parent_id": parent_id, "name": name, "catalog_type": catalog_type, "node_type": "folder"}

    async def audit(**_kwargs):
        return None

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "_owner_catalog_id", lambda: 77)
    monkeypatch.setattr(owner_api, "ensure_root_node", root)
    monkeypatch.setattr(owner_api, "get_node", node)
    monkeypatch.setattr(owner_api, "create_folder", create)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request("POST", "/api/v1/owner/custom-catalog/nodes")
    request._read_bytes = json.dumps({"node_type": "folder", "name": " Accounts "}).encode()

    response = await owner_api.owner_create_custom_catalog_node(request)

    assert response.status == 200
    assert calls == {"reseller_id": 77, "parent_id": "root-1", "name": "Accounts", "catalog_type": "custom"}


@pytest.mark.asyncio
async def test_owner_custom_catalog_move_delegates(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def move(node_id, owner_id, direction, *, catalog_type):
        calls.update({"node_id": node_id, "owner_id": owner_id, "direction": direction, "catalog_type": catalog_type})
        return True, "moved"

    async def audit(**_kwargs):
        return None

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "_owner_catalog_id", lambda: 77)
    monkeypatch.setattr(owner_api, "move_node_in_parent", move)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request("POST", "/api/v1/owner/custom-catalog/nodes/node-1/action", match_info={"node_id": "node-1"})
    request._read_bytes = json.dumps({"action": "move", "direction": "up"}).encode()

    response = await owner_api.owner_custom_catalog_node_action(request)

    assert response.status == 200
    assert calls == {"node_id": "node-1", "owner_id": 77, "direction": "up", "catalog_type": "custom"}


@pytest.mark.asyncio
async def test_owner_create_api_key_filters_scopes(monkeypatch):
    calls = {}
    audit_calls = []

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def create(**kwargs):
        calls.update(kwargs)
        return "ph_live_secret", {"_id": "key-1", "prefix": "ph_live_abc", **kwargs, "status": "active"}

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "create_api_key", create)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request("POST", "/api/v1/owner/api-keys")
    request._read_bytes = json.dumps({"scopes": ["numbers:quotes", "bad"], "name": "Client", "user_id": 10, "reseller_id": 11}).encode()

    response = await owner_api.owner_create_api_key(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["api_key"] == "ph_live_secret"
    assert calls["scopes"] == ["numbers:quotes"]
    assert calls["user_id"] == 10
    assert calls["reseller_id"] == 11
    assert audit_calls[0]["action"] == "api_key.create"
    assert audit_calls[0]["metadata"]["scopes"] == ["numbers:quotes"]
    assert "ph_live_secret" not in json.dumps(audit_calls[0])


@pytest.mark.asyncio
async def test_owner_create_webhook_requires_https(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    request = make_mocked_request("POST", "/api/v1/owner/webhooks")
    request._read_bytes = json.dumps({"url": "http://example.com/hook", "events": ["numbers.order.sms"]}).encode()

    response = await owner_api.owner_create_webhook(request)

    assert response.status == 400


@pytest.mark.asyncio
async def test_owner_create_webhook_audits_without_secret(monkeypatch):
    audit_calls = []

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def create(**kwargs):
        return "whsec_secret", {"_id": "hook-1", **kwargs, "secret": "whsec_secret", "status": "active"}

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "create_webhook", create)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request("POST", "/api/v1/owner/webhooks")
    request._read_bytes = json.dumps({"url": "https://example.com/hook?token=private", "events": ["numbers.order.sms"], "user_id": 10, "reseller_id": 11}).encode()

    response = await owner_api.owner_create_webhook(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["secret"] == "whsec_secret"
    assert audit_calls[0]["action"] == "webhook.create"
    assert audit_calls[0]["metadata"]["events"] == ["numbers.order.sms"]
    assert audit_calls[0]["metadata"]["url"] == "https://example.com/hook"
    assert "private" not in json.dumps(audit_calls[0])
    assert "whsec_secret" not in json.dumps(audit_calls[0])


@pytest.mark.asyncio
async def test_owner_revoke_integration_credentials_audits_success(monkeypatch):
    audit_calls = []

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def revoke(**_kwargs):
        return True

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "revoke_api_key", revoke)
    monkeypatch.setattr(owner_api, "revoke_webhook", revoke)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)

    key_request = make_mocked_request("POST", "/api/v1/owner/api-keys/key-1/revoke", match_info={"key_id": "key-1"})
    hook_request = make_mocked_request("POST", "/api/v1/owner/webhooks/hook-1/revoke", match_info={"webhook_id": "hook-1"})
    key_response = await owner_api.owner_revoke_api_key(key_request)
    hook_response = await owner_api.owner_revoke_webhook(hook_request)

    assert key_response.status == 200
    assert hook_response.status == 200
    assert [call["action"] for call in audit_calls] == ["api_key.revoke", "webhook.revoke"]
    assert [call["target_id"] for call in audit_calls] == ["key-1", "hook-1"]


@pytest.mark.asyncio
async def test_owner_provider_webhook_replay_delegates(monkeypatch):
    audit_calls = []

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def replay(event_id):
        return {"ok": True, "event_id": event_id}

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "replay_provider_webhook_event", replay)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/provider-webhook-events/event-1/replay",
        match_info={"event_id": "event-1"},
    )

    response = await owner_api.owner_replay_provider_webhook_event(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["event_id"] == "event-1"
    assert audit_calls[0]["action"] == "provider_webhook.replay"
    assert audit_calls[0]["target_id"] == "event-1"


@pytest.mark.asyncio
async def test_owner_digital_provider_sources_returns_sources_and_runs(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def sources(**kwargs):
        assert kwargs["provider"] == "bittopup"
        assert kwargs["status"] == "under_review"
        return [{
            "_id": "bittopup:pubg#60",
            "source_token": "src123",
            "provider": "bittopup",
            "price_status": "under_review",
            "review_reason": "price_change_gt_guardrail",
            "source_product_name": "PUBG UC",
            "source_denomination_name": "60 UC",
            "observed_price": 1.1,
            "active_price": 1.0,
            "compare_key": "pubg:global:60:uc",
        }]

    async def runs(**kwargs):
        return [{"provider": "bittopup", "status": "success", "stats": {"offers_seen": 1}}]

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "list_provider_sources", sources)
    monkeypatch.setattr(owner_api, "list_price_watch_runs", runs)
    response = await owner_api.owner_digital_provider_sources(make_mocked_request("GET", "/api/v1/owner/digital-provider-sources?provider=bittopup&status=under_review"))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["sources"][0]["id"] == "src123"
    assert payload["sources"][0]["observed_price"] == 1.1
    assert payload["runs"][0]["stats"]["offers_seen"] == 1


@pytest.mark.asyncio
async def test_owner_digital_provider_source_action_approves(monkeypatch):
    calls = {}
    audit_calls = []

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def approve(source_id, *, actor_id=None):
        calls["source_id"] = source_id
        calls["actor_id"] = actor_id
        return {"_id": "bittopup:pubg#60", "source_token": source_id, "provider": "bittopup", "price_status": "active", "observed_price": 1.1, "active_price": 1.1}

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "approve_provider_source", approve)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/digital-provider-sources/src123/action",
        match_info={"source_id": "src123"},
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps({"action": "approve"}).encode()

    response = await owner_api.owner_digital_provider_source_action(request)

    assert response.status == 200
    assert calls == {"source_id": "src123", "actor_id": 900000000001}
    assert audit_calls[0]["action"] == "digital_provider_source.approve"
    assert audit_calls[0]["metadata"]["provider"] == "bittopup"


@pytest.mark.asyncio
async def test_owner_run_digital_provider_scan_delegates(monkeypatch):
    calls = {}
    audit_calls = []

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def scan(*, max_pages=None):
        calls["max_pages"] = max_pages
        return {"provider": "bittopup", "status": "success"}

    async def audit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "run_bittopup_price_watch", scan)
    monkeypatch.setattr(owner_api, "_write_owner_audit", audit)
    request = make_mocked_request("POST", "/api/v1/owner/digital-provider-sources/scan", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"max_pages": 2}).encode()

    response = await owner_api.owner_run_digital_provider_scan(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["max_pages"] == 2
    assert payload["scan"]["status"] == "success"
    assert audit_calls[0]["action"] == "digital_provider.scan"
    assert audit_calls[0]["metadata"] == {"max_pages": 2, "status": "success"}
