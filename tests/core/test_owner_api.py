import json
from datetime import UTC, datetime

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
    assert ("GET", "/api/v1/owner/users") in routes
    assert ("GET", "/api/v1/owner/users/{customer_id}") in routes
    assert ("POST", "/api/v1/owner/users/{customer_id}/action") in routes
    assert ("GET", "/api/v1/owner/finance/audit") in routes
    assert ("GET", "/api/v1/owner/digital/orders") in routes
    assert ("POST", "/api/v1/owner/digital/orders/{order_id}/action") in routes
    assert ("GET", "/api/v1/owner/numbers/refund-reviews") in routes
    assert ("POST", "/api/v1/owner/numbers/refund-reviews/{order_id}/resolve") in routes
    assert ("GET", "/api/v1/owner/settings") in routes
    assert ("PUT", "/api/v1/owner/settings") in routes
    assert ("POST", "/api/v1/owner/routing-targets/{target_key}") in routes
    assert ("PATCH", "/api/v1/owner/payment-methods/{method_code}") in routes
    assert ("GET", "/api/v1/owner/recharge-reviews") in routes
    assert ("POST", "/api/v1/owner/recharge-reviews/{request_id}/action") in routes
    assert ("GET", "/api/v1/owner/identity-reviews") in routes
    assert ("POST", "/api/v1/owner/identity-reviews/{review_id}/action") in routes
    assert ("GET", "/api/v1/owner/support-tickets") in routes
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
        return {"days": days, "negative_wallets_count": 1}

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "scan_financial_anomalies", scan)

    response = await owner_api.owner_finance_audit(make_mocked_request("GET", "/api/v1/owner/finance/audit?days=7&limit=5"))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["audit"]["negative_wallets_count"] == 1
    assert calls == {"days": 7, "max_rows": 5}


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

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def credit(**kwargs):
        calls.update(kwargs)
        return {"_id": "ledger-1"}

    class LedgerEntries:
        async def update_one(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "credit_reseller_main_wallet", credit)
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


@pytest.mark.asyncio
async def test_owner_broadcast_uses_delivery_helper(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def send(**kwargs):
        calls.update(kwargs)
        return True

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "send_owner_broadcast", send)
    request = make_mocked_request("POST", "/api/v1/owner/broadcast", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"chat_id": -1001, "message_thread_id": 3, "text": "Hello owners"}).encode()

    response = await owner_api.owner_broadcast(request)

    assert response.status == 200
    assert calls == {"chat_id": -1001, "message_thread_id": 3, "text": "Hello owners"}


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


@pytest.mark.asyncio
async def test_owner_create_api_key_filters_scopes(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def create(**kwargs):
        calls.update(kwargs)
        return "ph_live_secret", {"_id": "key-1", "prefix": "ph_live_abc", **kwargs, "status": "active"}

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "create_api_key", create)
    request = make_mocked_request("POST", "/api/v1/owner/api-keys")
    request._read_bytes = json.dumps({"scopes": ["numbers:quotes", "bad"], "name": "Client", "user_id": 10, "reseller_id": 11}).encode()

    response = await owner_api.owner_create_api_key(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["api_key"] == "ph_live_secret"
    assert calls["scopes"] == ["numbers:quotes"]
    assert calls["user_id"] == 10
    assert calls["reseller_id"] == 11


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
async def test_owner_provider_webhook_replay_delegates(monkeypatch):
    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def replay(event_id):
        return {"ok": True, "event_id": event_id}

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "replay_provider_webhook_event", replay)
    request = make_mocked_request(
        "POST",
        "/api/v1/owner/provider-webhook-events/event-1/replay",
        match_info={"event_id": "event-1"},
    )

    response = await owner_api.owner_replay_provider_webhook_event(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["event_id"] == "event-1"


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

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def approve(source_id, *, actor_id=None):
        calls["source_id"] = source_id
        calls["actor_id"] = actor_id
        return {"_id": "bittopup:pubg#60", "source_token": source_id, "price_status": "active", "observed_price": 1.1, "active_price": 1.1}

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "approve_provider_source", approve)
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


@pytest.mark.asyncio
async def test_owner_run_digital_provider_scan_delegates(monkeypatch):
    calls = {}

    async def owner(_request):
        return WebsiteAuthContext("owner-1", 900000000001, "homamothman1@gmail.com", None, "hash")

    async def scan(*, max_pages=None):
        calls["max_pages"] = max_pages
        return {"provider": "bittopup", "status": "success"}

    monkeypatch.setattr(owner_api, "require_website_owner", owner)
    monkeypatch.setattr(owner_api, "run_bittopup_price_watch", scan)
    request = make_mocked_request("POST", "/api/v1/owner/digital-provider-sources/scan", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"max_pages": 2}).encode()

    response = await owner_api.owner_run_digital_provider_scan(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["max_pages"] == 2
    assert payload["scan"]["status"] == "success"
