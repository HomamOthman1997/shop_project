import json
from datetime import UTC, datetime

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from bson import ObjectId

from services.numbers import api
from services.numbers import api_payloads
from services.platform.api_auth import ApiAuthContext
from services.platform.api_rate_limits import ApiRateLimitDecision


def api_auth_context(**kwargs):
    return ApiAuthContext(**kwargs)


async def allow_rate_limit(auth, *, bucket, limit, window_seconds=60):
    return ApiRateLimitDecision(bucket=bucket, limit=limit, remaining=limit - 1, reset_at=9999999999, window_seconds=60)


def test_register_numbers_api_routes_adds_versioned_endpoints():
    app = web.Application()

    api.register_numbers_api_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/api/v1/numbers/health") in routes
    assert ("GET", "/api/v1/numbers/docs") in routes
    assert ("GET", "/api/v1/numbers/openapi.json") in routes
    assert ("GET", "/api/v1/numbers/catalog/bootstrap") in routes
    assert ("GET", "/api/v1/numbers/country-suggestions") in routes
    assert ("GET", "/api/v1/numbers/account") in routes
    assert ("GET", "/api/v1/numbers/recharge") in routes
    assert ("GET", "/api/v1/numbers/recharge/requests") in routes
    assert ("POST", "/api/v1/numbers/recharge/submit") in routes
    assert ("GET", "/api/v1/numbers/support") in routes
    assert ("POST", "/api/v1/numbers/support/ticket") in routes
    assert ("GET", "/api/v1/numbers/support/tickets/{ticket_id}") in routes
    assert ("POST", "/api/v1/numbers/support/tickets/{ticket_id}/reply") in routes
    assert ("GET", "/api/v1/numbers/quotes") in routes
    assert ("GET", "/api/v1/numbers/orders") in routes
    assert ("GET", "/api/v1/numbers/orders/{order_id}") in routes
    assert ("POST", "/api/v1/numbers/orders") in routes
    assert ("POST", "/api/v1/numbers/orders/{order_id}/refresh") in routes
    assert ("POST", "/api/v1/numbers/orders/{order_id}/resend") in routes
    assert ("POST", "/api/v1/numbers/orders/{order_id}/replace") in routes
    assert ("POST", "/api/v1/numbers/orders/{order_id}/alternate") in routes
    assert ("GET", "/api/v1/numbers/orders/{order_id}/recording") in routes
    assert ("POST", "/api/v1/numbers/orders/{order_id}/rental/sms") in routes
    assert ("POST", "/api/v1/numbers/orders/{order_id}/rental/finish") in routes
    assert ("POST", "/api/v1/numbers/orders/{order_id}/rental/renew") in routes
    assert ("POST", "/api/v1/numbers/orders/{order_id}/rental/wake") in routes
    assert ("POST", "/api/v1/numbers/orders/{order_id}/rental/notes") in routes
    assert ("GET", "/api/v1/numbers/ops/refund-reviews") in routes
    assert ("POST", "/api/v1/numbers/ops/refund-reviews/{order_id}/resolve") in routes
    assert ("GET", "/api/v1/numbers/ops/provider-readiness") in routes
    assert ("GET", "/api/v1/numbers/ops/provider-webhook-events") in routes
    assert ("POST", "/api/v1/numbers/ops/provider-webhook-events/{event_id}/replay") in routes


@pytest.mark.asyncio
async def test_numbers_api_health():
    request = make_mocked_request("GET", "/api/v1/numbers/health")

    response = await api.health(request)
    payload = json.loads(response.text)

    assert payload == {
        "ok": True,
        "status": "healthy",
        "service": "numbers-api",
        "version": "v1",
    }


@pytest.mark.asyncio
async def test_numbers_api_openapi_schema_exposes_public_contract():
    request = make_mocked_request("GET", "/api/v1/numbers/openapi.json")

    response = await api.openapi_schema(request)
    payload = json.loads(response.text)

    assert payload["openapi"] == "3.1.0"
    assert payload["info"]["title"] == "Phantom Numbers API"
    assert payload["servers"][0]["url"] == "/api/v1/numbers"
    assert "/docs" in payload["paths"]
    assert "/openapi.json" in payload["paths"]
    assert "/catalog/bootstrap" in payload["paths"]
    assert "/orders/{order_id}/refresh" in payload["paths"]
    assert "/recharge/submit" in payload["paths"]
    assert "x-required-scope" not in payload["paths"]["/docs"]["get"]
    assert payload["paths"]["/orders"]["post"]["x-required-scope"] == "numbers:orders:create"
    assert payload["paths"]["/recharge/submit"]["post"]["x-required-scope"] == "numbers:account:read"
    assert any(param["name"] == "Idempotency-Key" for param in payload["paths"]["/orders"]["post"]["parameters"])
    assert payload["paths"]["/orders/{order_id}/rental/renew"]["post"]["x-required-scope"] == "numbers:orders:rental"
    assert payload["components"]["securitySchemes"]["BearerAuth"]["type"] == "http"
    assert payload["x-phantom-api-discovery"]["actions"]["submit_recharge"]["enabled"] is True
    assert "/mini/" not in json.dumps(payload["paths"])


@pytest.mark.asyncio
async def test_numbers_api_docs_renders_self_hosted_reference():
    request = make_mocked_request("GET", "/api/v1/numbers/docs")

    response = await api.api_docs(request)
    text = response.text or ""

    assert response.content_type == "text/html"
    assert "Phantom Numbers API" in text
    assert "Endpoint Reference" in text
    assert "Action Catalog" in text
    assert "/api/v1/numbers/openapi.json" in text
    assert "/api/v1/numbers/orders/{order_id}/refresh" in text
    assert "/api/v1/numbers/support/ticket" in text
    assert "numbers:orders:create" in text
    assert "numbers:account:read" in text
    assert "/mini/" not in text


@pytest.mark.asyncio
async def test_numbers_api_catalog_bootstrap_has_core_selectors():
    api_payloads.clear_numbers_api_payload_cache()
    request = make_mocked_request("GET", "/api/v1/numbers/catalog/bootstrap")

    response = await api.catalog_bootstrap(request)
    payload = json.loads(response.text)

    assert payload["ok"] is True
    assert payload["version"] == "v1"
    assert payload["defaults"] == {"mode": "temp", "service": "", "country": "none", "state": "none"}
    assert payload["client"] == {
        "primary_surface": "miniapp",
        "telegram_order_flow_enabled": False,
        "provider_sms_polling_enabled": False,
        "manual_customer_refund_enabled": False,
    }
    assert payload["api"]["base_path"] == "/api/v1/numbers"
    assert payload["api"]["quote_ttl_sec"] == api_payloads.QUOTE_TTL_SEC
    assert payload["api"]["actions"]["api_docs"]["endpoint"] == "/api/v1/numbers/docs"
    assert payload["api"]["actions"]["openapi"]["endpoint"] == "/api/v1/numbers/openapi.json"
    assert payload["api"]["capabilities"]["server_managed_refunds"] is True
    assert payload["api"]["capabilities"]["manual_customer_refund_enabled"] is False
    assert payload["api"]["actions"]["quotes"]["endpoint"] == "/api/v1/numbers/quotes"
    assert payload["api"]["actions"]["quotes"]["scope"] == "numbers:quotes"
    assert payload["api"]["actions"]["create_order"]["method"] == "POST"
    assert payload["api"]["actions"]["create_order"]["requires_idempotency_key"] is True
    assert payload["api"]["actions"]["resend_order"]["scope"] == "numbers:orders:resend"
    assert payload["api"]["actions"]["submit_recharge"]["enabled"] is True
    assert "/mini/" not in json.dumps(payload["api"]["actions"])
    assert [item["key"] for item in payload["modes"]] == ["temp", "rental", "voice"]
    assert any(item["key"] == "telegram" for item in payload["services"])
    assert any(item["code"] == "1" for item in payload["countries"])
    assert any(item["code"] == "none" for item in payload["states_us"])


@pytest.mark.asyncio
async def test_numbers_api_country_suggestions_uses_quotes_scope(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_check_rate_limit(auth, *, bucket, limit, window_seconds=60):
        calls["rate_limit"] = (bucket, limit)
        return await allow_rate_limit(auth, bucket=bucket, limit=limit, window_seconds=window_seconds)

    async def fake_country_suggestions(mode, service, limit=10):
        calls["suggestions"] = (mode, service, limit)
        return [{"code": "44", "name": "United Kingdom", "price": 0.22, "price_label": "$0.22"}]

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", fake_check_rate_limit)
    monkeypatch.setattr(api, "country_suggestions_for_service", fake_country_suggestions)

    request = make_mocked_request("GET", "/api/v1/numbers/country-suggestions?mode=temp&service=gmail&limit=6")

    response = await api.country_suggestions(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:quotes"
    assert calls["rate_limit"] == ("numbers:country-suggestions", 60)
    assert calls["suggestions"] == ("temp", "gmail", 6)
    assert payload == {
        "ok": True,
        "mode": "temp",
        "service": "gmail",
        "countries": [{"code": "44", "name": "United Kingdom", "price": 0.22, "price_label": "$0.22"}],
    }


@pytest.mark.asyncio
async def test_numbers_api_country_suggestions_rejects_bad_mode(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)

    request = make_mocked_request("GET", "/api/v1/numbers/country-suggestions?mode=bad&service=gmail")

    response = await api.country_suggestions(request)
    payload = json.loads(response.text)

    assert response.status == 400
    assert payload["code"] == "unsupported_mode"
    assert payload["error"] == "Unsupported mode."
    assert payload["message"] == payload["error"]


@pytest.mark.asyncio
async def test_numbers_api_account_returns_wallet_snapshot(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user(user_id):
        calls["user_id"] = user_id
        return {
            "telegram_id": user_id,
            "username": "customer",
            "language": "ar",
            "created_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        }

    async def fake_get_user_wallet_balance(user_id, reseller_id):
        calls["wallet"] = (user_id, reseller_id)
        return 12.5

    async def fake_list_user_wallet_entries(user_id, reseller_id, limit=8):
        calls["activity"] = (user_id, reseller_id, limit)
        return [
            {
                "_id": "tx-1",
                "direction": "debit",
                "amount": -0.44,
                "reason": "purchase_core_user_debit",
                "category": "core_purchase",
                "balance_after": 12.5,
                "created_at": datetime(2026, 5, 25, 12, 5, tzinfo=UTC),
                "order_id": "order-1",
                "metadata": {"provider": "textverified", "debug": "hidden"},
            },
            {
                "_id": "tx-2",
                "direction": "credit",
                "amount": 1.0,
                "reason": "refund_core_user_credit",
                "category": "core_refund",
                "balance_after": 12.94,
                "created_at": datetime(2026, 5, 25, 12, 10, tzinfo=UTC),
                "order_id": "order-1",
            },
        ]

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user", fake_get_user)
    monkeypatch.setattr(api, "get_user_wallet_balance", fake_get_user_wallet_balance)
    monkeypatch.setattr(api, "list_user_wallet_entries", fake_list_user_wallet_entries)
    request = make_mocked_request("GET", "/api/v1/numbers/account")

    response = await api.account(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:account:read"
    assert calls["wallet"] == (123, 456)
    assert payload["ok"] is True
    assert payload["user"]["username"] == "customer"
    assert payload["user"]["language"] == "ar"
    assert payload["wallet"] == {"balance": 12.5, "currency": "USD", "balance_label": "$12.50"}
    assert calls["activity"] == (123, 456, 8)
    assert payload["recent_activity"][0] == {
        "id": "tx-1",
        "kind": "numbers_purchase",
        "label": "Numbers purchase",
        "direction": "debit",
        "amount": -0.44,
        "amount_label": "-$0.44",
        "balance_after": 12.5,
        "balance_label": "$12.50",
        "created_at": "2026-05-25T12:05:00+00:00",
        "order_id": "order-1",
    }
    assert payload["recent_activity"][1]["kind"] == "numbers_refund"
    assert "reason" not in payload["recent_activity"][0]
    assert "metadata" not in payload["recent_activity"][0]
    assert response.headers["X-RateLimit-Bucket"] == "numbers:account:read"


@pytest.mark.asyncio
async def test_numbers_api_recharge_returns_read_only_options(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_wallet_balance(user_id, reseller_id):
        calls["wallet"] = (user_id, reseller_id)
        return 7.25

    async def fake_get_owner_payment_methods():
        calls["methods"] = True
        return [
            {
                "code": "usdt",
                "title": "USDT",
                "currency": "USD",
                "per_credit": 1,
                "target": "T_WALLET",
                "support": "@support",
                "instructions": "Send payment to {target}.",
            },
            {"code": "disabled", "enabled": False},
        ]

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_wallet_balance", fake_get_user_wallet_balance)
    monkeypatch.setattr(api, "get_owner_payment_methods", fake_get_owner_payment_methods)

    request = make_mocked_request("GET", "/api/v1/numbers/recharge")

    response = await api.recharge_options(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:account:read"
    assert calls["wallet"] == (123, 456)
    assert payload["wallet"]["balance_label"] == "$7.25"
    assert payload["methods"][0]["code"] == "usdt"
    assert payload["methods"][0]["target"] == "T_WALLET"
    assert payload["actions"]["submit_recharge"]["enabled"] is True
    assert payload["capabilities"]["submit_recharge_proof"] is True


@pytest.mark.asyncio
async def test_numbers_api_submit_recharge_uses_shared_flow(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="website:account-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    async def fake_parse(_request):
        return (
            {"method_code": "usdt", "paid_amount": "10", "language": "ar"},
            b"proof-bytes",
            "proof.jpg",
            "image/jpeg",
        )

    async def fake_get_user(user_id):
        calls["get_user"] = user_id
        return {"telegram_id": user_id, "username": "site_user"}

    async def fake_submit_recharge_request(**kwargs):
        calls["submit"] = kwargs
        return {"ok": True, "message": "submitted", "request": {"id": "req-1"}, "delivery_ok": True}

    async def fake_get_user_wallet_balance(user_id, reseller_id):
        calls["wallet"] = (user_id, reseller_id)
        return 12.0

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_parse_recharge_submit_form", fake_parse)
    monkeypatch.setattr(api, "get_user", fake_get_user)
    monkeypatch.setattr(api, "shared_submit_recharge_request", fake_submit_recharge_request)
    monkeypatch.setattr(api, "get_user_wallet_balance", fake_get_user_wallet_balance)

    request = make_mocked_request("POST", "/api/v1/numbers/recharge/submit")

    response = await api.submit_recharge(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth_scope"] == "numbers:account:read"
    assert calls["submit"]["fields"]["method_code"] == "usdt"
    assert calls["submit"]["proof_bytes"] == b"proof-bytes"
    assert calls["submit"]["source"] == "website"
    assert calls["submit"]["source_label"] == "Phantom Website"
    assert calls["wallet"] == (123, 123)
    assert payload["request"]["id"] == "req-1"
    assert payload["wallet"]["balance_label"] == "$12.00"


@pytest.mark.asyncio
async def test_numbers_api_support_returns_read_only_contract(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    class FakeCursor:
        def sort(self, field, direction):
            calls["sort"] = (field, direction)
            return self

        def limit(self, value):
            calls["limit"] = value
            return self

        async def to_list(self, length):
            calls["length"] = length
            return [
                {
                    "_id": "ticket-1",
                    "ticket_no": 9,
                    "category": "numbers",
                    "status": "open",
                    "opened_at": datetime(2026, 1, 1, tzinfo=UTC),
                    "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
                    "payload_count": 1,
                }
            ]

    class FakeSupportTickets:
        def find(self, query):
            calls["ticket_query"] = query
            return FakeCursor()

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "db", type("Db", (), {"support_tickets": FakeSupportTickets()})())

    request = make_mocked_request("GET", "/api/v1/numbers/support?ticket_limit=12")

    response = await api.support_options(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:account:read"
    assert calls["ticket_query"] == {"scope": "platform", "owner_id": None, "user_id": 123}
    assert calls["sort"] == ("opened_at", -1)
    assert calls["limit"] == 12
    assert calls["length"] == 12
    assert [row["key"] for row in payload["categories"]] == ["numbers", "services", "user_balance"]
    assert [row["label"] for row in payload["categories"]] == ["طلبات الأرقام", "الخدمات الرقمية", "الرصيد والمدفوعات"]
    assert payload["tickets"][0]["ticket_no"] == 9
    assert payload["tickets"][0]["category_label"] == "طلبات الأرقام"
    assert payload["tickets"][0]["is_open"] is True
    assert payload["actions"]["submit_ticket"]["enabled"] is True
    assert payload["actions"]["submit_ticket"]["endpoint"] == "/api/v1/numbers/support/ticket"
    assert payload["capabilities"]["submit_ticket"] is True
    assert payload["capabilities"]["central_support"] is True


@pytest.mark.asyncio
async def test_numbers_api_recharge_requests_are_scoped_to_current_user(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="website:account-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    async def fake_purchase_ready(request):
        calls["purchase_ready"] = True

    async def fake_recent(user_id, lang, *, limit, money_fn, compact_datetime_fn, text_fn):
        calls["recent"] = (user_id, lang, limit)
        return [{"id": "req-1", "status": "pending"}]

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "require_website_purchase_ready", fake_purchase_ready)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "shared_recent_recharge_requests_payload", fake_recent)

    response = await api.recharge_requests(make_mocked_request("GET", "/api/v1/numbers/recharge/requests?limit=50&language=ar"))
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth_scope"] == "numbers:account:read"
    assert calls["purchase_ready"] is True
    assert calls["recent"] == (123, "ar", 30)
    assert payload["requests"] == [{"id": "req-1", "status": "pending"}]


@pytest.mark.asyncio
async def test_numbers_api_support_ticket_uses_shared_flow(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="website:account-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    async def fake_purchase_ready(request):
        calls["purchase_ready"] = True

    async def fake_get_user(user_id):
        calls["get_user"] = user_id
        return {"telegram_id": user_id, "username": "site_user"}

    async def fake_submit_support_ticket(**kwargs):
        calls["submit"] = kwargs
        return {"ok": True, "ticket_id": "ticket-1", "ticket_no": 7, "message": "sent"}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "require_website_purchase_ready", fake_purchase_ready)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user", fake_get_user)
    monkeypatch.setattr(api, "shared_submit_support_ticket", fake_submit_support_ticket)

    request = make_mocked_request("POST", "/api/v1/numbers/support/ticket", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"category": "numbers", "message": "Need help", "language": "ar"}).encode()

    response = await api.support_ticket(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth_scope"] == "numbers:account:read"
    assert calls["purchase_ready"] is True
    assert calls["submit"]["category"] == "numbers"
    assert calls["submit"]["message"] == "Need help"
    assert calls["submit"]["source_label"] == "Phantom Website"
    assert payload["ticket_no"] == 7


@pytest.mark.asyncio
async def test_numbers_api_support_ticket_detail_is_scoped_to_current_user(monkeypatch):
    ticket_id = ObjectId()
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="website:account-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    async def fake_purchase_ready(request):
        calls["purchase_ready"] = True

    class MessageCursor:
        def sort(self, field, direction):
            calls["message_sort"] = (field, direction)
            return self

        def limit(self, value):
            calls["message_limit"] = value
            return self

        async def to_list(self, length):
            calls["message_length"] = length
            return [{"_id": ObjectId(), "ticket_id": ticket_id, "direction": "owner_to_user", "text": "Reply", "created_at": datetime(2026, 1, 3, tzinfo=UTC)}]

    class Tickets:
        async def find_one(self, query):
            calls["ticket_query"] = query
            return {"_id": ticket_id, "ticket_no": 4, "category": "numbers", "status": "replied", "user_id": 123}

    class Messages:
        def find(self, query):
            calls["message_query"] = query
            return MessageCursor()

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "require_website_purchase_ready", fake_purchase_ready)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "db", type("Db", (), {"support_tickets": Tickets(), "support_ticket_messages": Messages()})())

    request = make_mocked_request("GET", f"/api/v1/numbers/support/tickets/{ticket_id}", match_info={"ticket_id": str(ticket_id)})
    response = await api.support_ticket_detail(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["ticket_query"] == {"_id": ticket_id, "scope": "platform", "owner_id": None, "user_id": 123}
    assert calls["message_query"] == {"ticket_id": ticket_id}
    assert payload["ticket"]["ticket_no"] == 4
    assert payload["messages"][0]["actor"] == "support"
    assert payload["messages"][0]["text"] == "Reply"


@pytest.mark.asyncio
async def test_numbers_api_support_ticket_reply_records_website_message(monkeypatch):
    ticket_id = ObjectId()
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="website:account-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    async def fake_purchase_ready(request):
        calls["purchase_ready"] = True

    class Tickets:
        async def find_one(self, query):
            calls.setdefault("ticket_queries", []).append(query)
            return {"_id": ticket_id, "ticket_no": 4, "category": "numbers", "status": "open", "user_id": 123}

        async def update_one(self, query, update):
            calls["ticket_update"] = (query, update)

    class Messages:
        async def insert_one(self, doc):
            calls["inserted_message"] = doc

        def find(self, query):
            calls["message_query"] = query
            return self

        def sort(self, field, direction):
            return self

        def limit(self, value):
            return self

        async def to_list(self, length):
            return [calls["inserted_message"]]

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "require_website_purchase_ready", fake_purchase_ready)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "db", type("Db", (), {"support_tickets": Tickets(), "support_ticket_messages": Messages()})())

    request = make_mocked_request("POST", f"/api/v1/numbers/support/tickets/{ticket_id}/reply", match_info={"ticket_id": str(ticket_id)}, headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"message": "More details", "language": "en"}).encode()

    response = await api.support_ticket_reply(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["inserted_message"]["direction"] == "user_to_owner"
    assert calls["inserted_message"]["actor_id"] == 123
    assert calls["inserted_message"]["text"] == "More details"
    assert calls["ticket_update"][0] == {"_id": ticket_id}
    assert calls["ticket_update"][1]["$set"]["status"] == "awaiting_admin"
    assert calls["ticket_update"][1]["$inc"] == {"payload_count": 1}
    assert payload["message"] == "Reply sent."
    assert payload["messages"][0]["actor"] == "customer"


@pytest.mark.asyncio
async def test_numbers_api_temp_quotes_show_primary_nonvoip_provider(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    async def fake_get_all_prices(service, country, state, ignore_balance=False, with_success_rates=True, provider_codes=None):
        calls["args"] = {
            "service": service,
            "country": country,
            "state": state,
            "ignore_balance": ignore_balance,
            "with_success_rates": with_success_rates,
            "provider_codes": tuple(provider_codes or ()),
        }
        return {
            "telabot": {
                "price": 0.44,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "provider_country": "102",
                "provider_country_iso": "GR",
                "recommended_success_rate": 91,
                "success_attempts": 5,
            },
            "nonvoip": {
                "price": 0.01,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "success_attempts": 99,
            },
        }

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_all_prices", fake_get_all_prices)
    request = make_mocked_request("GET", "/api/v1/numbers/quotes?mode=temp&service=telegram&country=1&state=CA")

    response = await api.quotes(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:quotes"
    assert calls["args"] == {
        "service": "telegram",
        "country": "1",
        "state": "CA",
        "ignore_balance": True,
        "with_success_rates": False,
        "provider_codes": api.TEMP_QUOTE_PROVIDER_CODES,
    }
    assert payload["ok"] is True
    assert payload["mode"] == "temp"
    assert payload["service"]["key"] == "telegram"
    assert len(payload["providers"]) == 2
    assert payload["providers"][0]["provider_id"] == "S7"
    assert payload["providers"][0]["provider"] == "Golf"
    assert payload["providers"][0]["price_label"] == "$0.01"
    assert payload["providers"][1]["provider_id"] == "S4"
    assert payload["providers"][1]["price_label"] == "$0.44"
    assert payload["providers"][0]["quote_token"]
    quote = api_payloads.verify_quote_token(payload["providers"][0]["quote_token"])
    assert quote["provider_id"] == payload["providers"][0]["provider_id"]
    assert "provider" not in quote
    assert "provider" not in quote
    assert response.headers["X-RateLimit-Bucket"] == "numbers:quotes"


@pytest.mark.asyncio
async def test_numbers_api_rental_quotes_return_signed_options(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    async def fake_get_all_rental_prices(service, country, with_success_rates=True, ignore_balance=False):
        calls["args"] = {
            "service": service,
            "country": country,
            "with_success_rates": with_success_rates,
            "ignore_balance": ignore_balance,
        }
        return {
            "textverified": {
                "api_service_name": "telegram",
                "available_for_buy": True,
                "options": [
                    {
                        "duration": 24,
                        "duration_label": "1d",
                        "price": 4.0,
                        "base_price": 3.0,
                        "tv_duration_key": "oneDay",
                        "tv_is_renewable": False,
                    }
                ],
            }
        }

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_all_rental_prices", fake_get_all_rental_prices)
    request = make_mocked_request("GET", "/api/v1/numbers/quotes?mode=rental&service=telegram&country=1&state=NY")

    response = await api.quotes(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:quotes"
    assert calls["args"] == {"service": "telegram", "country": "1", "with_success_rates": False, "ignore_balance": True}
    assert payload["ok"] is True
    assert payload["mode"] == "rental"
    assert payload["providers"][0]["provider"] == "Bravo"
    assert payload["providers"][0]["provider_id"].startswith("S")
    assert payload["providers"][0]["options"][0]["price"] == 6.0
    assert payload["providers"][0]["options"][0]["with_state"] is True
    quote = api_payloads.verify_quote_token(payload["providers"][0]["options"][0]["quote_token"])
    assert quote["mode"] == "rental"
    assert quote["provider_id"] == payload["providers"][0]["provider_id"]
    assert quote["state"] == "NY"
    assert "provider" not in quote
    assert response.headers["X-RateLimit-Bucket"] == "numbers:quotes"


def test_rental_quote_rows_hide_same_duration_price_outliers():
    rows = api_payloads.normalize_rental_quote_rows(
        {
            "pvadeals": {
                "api_service_name": "WhatsApp",
                "available_for_buy": True,
                "options": [
                    {"country": "USA", "duration": 72, "duration_days": 3, "duration_label": "3d", "price": 3.3},
                ],
            },
            "pvapins": {
                "api_service_name": "whatsapp",
                "available_for_buy": True,
                "options": [
                    {"country": "USA", "duration": 72, "duration_days": 3, "duration_label": "3d", "price": 37.95},
                ],
            },
        },
        service="whatsapp",
        country="1",
        state="none",
    )

    assert [(row["provider"], row["price"]) for row in rows] == [("Echo", 3.3)]
    assert rows[0]["options"][0]["duration_label"] == "3d"


@pytest.mark.asyncio
async def test_numbers_api_voice_quotes_return_signed_token(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    async def fake_get_all_voice_prices(service, country, state, ignore_balance=False):
        calls["args"] = {
            "service": service,
            "country": country,
            "state": state,
            "ignore_balance": ignore_balance,
        }
        return {
            "textverified": {
                "price": 0.66,
                "base_price": 0.5,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "voice_capable": True,
                "success_attempts": 6,
                "success_rate": 92,
            }
        }

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_all_voice_prices", fake_get_all_voice_prices)
    request = make_mocked_request("GET", "/api/v1/numbers/quotes?mode=voice&service=telegram&country=1&state=CA")

    response = await api.quotes(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:quotes"
    assert calls["args"] == {"service": "telegram", "country": "1", "state": "CA", "ignore_balance": True}
    assert payload["ok"] is True
    assert payload["mode"] == "voice"
    assert payload["country"] == "1"
    assert payload["providers"][0]["provider"] == "Bravo"
    assert payload["providers"][0]["provider_id"] == "S2"
    assert payload["providers"][0]["price_label"] == "$0.66"
    assert payload["providers"][0]["quote_token"]
    quote = api_payloads.verify_quote_token(payload["providers"][0]["quote_token"])
    assert quote["mode"] == "voice"
    assert quote["provider_id"] == "S2"
    assert quote["state"] == "CA"
    assert "provider" not in quote
    assert response.headers["X-RateLimit-Bucket"] == "numbers:quotes"


@pytest.mark.asyncio
async def test_numbers_api_list_orders_combines_number_modes(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_recent(user_id, limit=20, days=5):
        calls["recent"] = (user_id, limit, days)
        return [
            {
                "_id": "temp-1",
                "status": "success",
                "number_mode": "temp",
                "temp_service_key": "telegram",
                "temp_country": "1",
                "temp_state": "CA",
                "provider_public_id": "S01",
                "provider": "textverified",
                "provider_number": "15550001111",
                "selling_price": 1.25,
                "base_price": 1.0,
                "temp_wait_state": "waiting",
                "created_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
            },
            {
                "_id": "voice-1",
                "status": "success",
                "number_mode": "voice",
                "temp_service_key": "whatsapp",
                "created_at": datetime(2026, 5, 25, 11, 0, tzinfo=UTC),
            },
        ]

    async def fake_rentals(user_id, limit=20):
        calls["rentals"] = (user_id, limit)
        return [
            {
                "_id": "rent-1",
                "status": "success",
                "number_mode": "rental",
                "service_id": "gmail",
                "provider_number": "15550002222",
                "created_at": datetime(2026, 5, 25, 13, 0, tzinfo=UTC),
            }
        ]

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "list_user_recent_temp_and_voice_orders", fake_recent)
    monkeypatch.setattr(api, "list_user_rental_orders", fake_rentals)
    request = make_mocked_request("GET", "/api/v1/numbers/orders?mode=all&limit=5")

    response = await api.list_orders(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:orders:read"
    assert calls["recent"] == (123, 5, 5)
    assert calls["rentals"] == (123, 5)
    assert [item["id"] for item in payload["orders"]] == ["rent-1", "temp-1", "voice-1"]
    assert payload["orders"][1]["provider_id"] == "S01"
    assert payload["orders"][1]["provider"] == "Bravo"
    assert payload["orders"][1]["provider"] != "textverified"
    assert "base_price" not in payload["orders"][1]
    assert response.headers["X-RateLimit-Bucket"] == "numbers:orders:read"


@pytest.mark.asyncio
async def test_numbers_api_list_orders_filters_mode(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_recent(user_id, limit=20, days=5):
        return [
            {"_id": "temp-1", "number_mode": "temp", "created_at": datetime(2026, 5, 25, 12, 0, tzinfo=UTC)},
            {"_id": "voice-1", "number_mode": "voice", "created_at": datetime(2026, 5, 25, 11, 0, tzinfo=UTC)},
        ]

    async def fail_rentals(*args, **kwargs):
        raise AssertionError("rental query should not run for temp-only mode")

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "list_user_recent_temp_and_voice_orders", fake_recent)
    monkeypatch.setattr(api, "list_user_rental_orders", fail_rentals)
    request = make_mocked_request("GET", "/api/v1/numbers/orders?mode=temp")

    response = await api.list_orders(request)
    payload = json.loads(response.text)

    assert [item["id"] for item in payload["orders"]] == ["temp-1"]


@pytest.mark.asyncio
async def test_numbers_api_get_order_detail_is_owner_scoped(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        calls["get"] = (order_id, user_id, reseller_id)
        return {
            "_id": order_id,
            "status": "success",
            "number_mode": "temp",
            "temp_service_key": "telegram",
            "provider": "textverified",
            "provider_number": "15550001111",
            "selling_price": 1.25,
            "base_price": 0.5,
        }

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    request = make_mocked_request("GET", "/api/v1/numbers/orders/order-1", match_info={"order_id": "order-1"})

    response = await api.get_order_detail(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:orders:read"
    assert calls["get"] == ("order-1", 123, 456)
    assert payload["order"]["id"] == "order-1"
    assert payload["order"]["provider"] == "Bravo"
    assert payload["order"]["number"] == "15550001111"
    assert "base_price" not in payload["order"]
    assert payload["order"]["api_actions"]["refresh"]["endpoint"] == "/api/v1/numbers/orders/order-1/refresh"
    assert payload["order"]["api_actions"]["refresh"]["scope"] == "numbers:orders:refresh"
    assert payload["order"]["api_actions"]["resend"]["endpoint"] == "/api/v1/numbers/orders/order-1/resend"
    assert payload["order"]["api_actions"]["resend"]["requires_idempotency_key"] is True
    assert payload["order"]["api_actions"]["cancel"]["endpoint"] == "/api/v1/numbers/orders/order-1/cancel"
    assert payload["order"]["api_actions"]["cancel"]["scope"] == "numbers:orders:cancel"
    assert payload["order"]["api_actions"]["cancel"]["requires_idempotency_key"] is True
    assert "/mini/" not in json.dumps(payload["order"]["api_actions"])


@pytest.mark.asyncio
async def test_numbers_api_order_payload_exposes_rental_action_contract(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        return {
            "_id": order_id,
            "status": "success",
            "number_mode": "rental",
            "service_id": "telegram:rental",
            "provider_order_id": "rent-1",
            "provider_number": "15550001111",
            "rental_country": "1",
            "rental_is_renewable": True,
        }

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    request = make_mocked_request("GET", "/api/v1/numbers/orders/rental-1", match_info={"order_id": "rental-1"})

    response = await api.get_order_detail(request)
    payload = json.loads(response.text)
    actions = payload["order"]["api_actions"]

    assert actions["rental_sms"]["enabled"] is True
    assert actions["rental_sms"]["endpoint"] == "/api/v1/numbers/orders/rental-1/rental/sms"
    assert actions["rental_renew"]["enabled"] is True
    assert actions["rental_renew"]["scope"] == "numbers:orders:rental"
    assert actions["rental_renew"]["requires_idempotency_key"] is True
    assert actions["rental_finish"]["endpoint"] == "/api/v1/numbers/orders/rental-1/rental/finish"
    assert "/mini/" not in json.dumps(actions)


@pytest.mark.asyncio
async def test_numbers_api_order_payload_exposes_voice_recording_action(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        return {
            "_id": order_id,
            "status": "success",
            "number_mode": "voice",
            "temp_service_key": "telegram",
            "provider_number": "15550001111",
            "voice_recording_uri": "https://recording.example/test.mp3",
        }

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    request = make_mocked_request("GET", "/api/v1/numbers/orders/voice-1", match_info={"order_id": "voice-1"})

    response = await api.get_order_detail(request)
    payload = json.loads(response.text)
    action = payload["order"]["api_actions"]["download_recording"]

    assert action["enabled"] is True
    assert action["method"] == "GET"
    assert action["scope"] == "numbers:orders:read"
    assert action["endpoint"] == "/api/v1/numbers/orders/voice-1/recording"


@pytest.mark.asyncio
async def test_numbers_api_get_order_detail_returns_404(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        return None

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    request = make_mocked_request("GET", "/api/v1/numbers/orders/missing", match_info={"order_id": "missing"})

    response = await api.get_order_detail(request)
    payload = json.loads(response.text)

    assert response.status == 404
    assert payload["code"] == "order_not_found"


@pytest.mark.asyncio
async def test_numbers_api_refresh_order_uses_refresh_service(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        calls["get"] = (order_id, user_id, reseller_id)
        return {"_id": order_id, "user_id": user_id, "reseller_id": reseller_id, "number_mode": "temp"}

    async def fake_refresh_number_order(order):
        calls["refresh"] = order
        return {"ok": True, "order": {"id": order["_id"], "code": "123456"}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    monkeypatch.setattr(api, "refresh_number_order", fake_refresh_number_order)
    request = make_mocked_request("POST", "/api/v1/numbers/orders/order-1/refresh", match_info={"order_id": "order-1"})

    response = await api.refresh_order(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:orders:refresh"
    assert calls["get"] == ("order-1", 123, 456)
    assert payload == {"ok": True, "order": {"id": "order-1", "code": "123456"}}
    assert response.headers["X-RateLimit-Bucket"] == "numbers:orders:refresh"


@pytest.mark.asyncio
async def test_numbers_api_resend_order_uses_resend_service(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        calls["get"] = (order_id, user_id, reseller_id)
        return {"_id": order_id, "user_id": user_id, "reseller_id": reseller_id, "number_mode": "temp"}

    async def fake_request_number_order_resend(order, *, user_id, reseller_id):
        calls["resend"] = (order, user_id, reseller_id)
        return {"ok": True, "order": {"id": order["_id"], "public_status": "waiting"}, "second_order_id": "second-1"}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    monkeypatch.setattr(api, "request_number_order_resend", fake_request_number_order_resend)
    request = make_mocked_request("POST", "/api/v1/numbers/orders/order-1/resend", match_info={"order_id": "order-1"})

    response = await api.resend_order(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:orders:resend"
    assert calls["get"] == ("order-1", 123, 456)
    assert calls["resend"][1:] == (123, 456)
    assert payload == {"ok": True, "order": {"id": "order-1", "public_status": "waiting"}, "second_order_id": "second-1"}
    assert response.headers["X-RateLimit-Bucket"] == "numbers:orders:resend"


@pytest.mark.asyncio
async def test_numbers_api_replace_order_uses_replacement_service(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        calls["get"] = (order_id, user_id, reseller_id)
        return {"_id": order_id, "user_id": user_id, "reseller_id": reseller_id, "number_mode": "temp"}

    async def fake_request_replacement_order(**kwargs):
        calls["replace"] = kwargs
        return {"ok": True, "order": {"id": "replacement-1"}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    monkeypatch.setattr(api, "request_replacement_order", fake_request_replacement_order)
    request = make_mocked_request(
        "POST",
        "/api/v1/numbers/orders/order-1/replace",
        headers={"Content-Type": "application/json", "Idempotency-Key": "replace-1"},
        match_info={"order_id": "order-1"},
    )
    request._read_bytes = json.dumps({"language": "en"}).encode("utf-8")

    response = await api.replace_order(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:orders:replace"
    assert calls["get"] == ("order-1", 123, 456)
    assert calls["replace"]["idempotency_key"] == "replace-1"
    assert calls["replace"]["alternate_provider"] is False
    assert payload == {"ok": True, "order": {"id": "replacement-1"}}
    assert response.headers["X-RateLimit-Bucket"] == "numbers:orders:replace"


@pytest.mark.asyncio
async def test_numbers_api_alternate_order_sets_alternate_flag(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        return {"_id": order_id, "user_id": user_id, "reseller_id": reseller_id, "number_mode": "temp"}

    async def fake_request_replacement_order(**kwargs):
        calls["replace"] = kwargs
        return {"ok": True, "order": {"id": "alternate-1"}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    monkeypatch.setattr(api, "request_replacement_order", fake_request_replacement_order)
    request = make_mocked_request(
        "POST",
        "/api/v1/numbers/orders/order-1/alternate",
        headers={"Idempotency-Key": "alternate-1"},
        match_info={"order_id": "order-1"},
    )

    response = await api.alternate_provider_order(request)

    assert response.status == 200
    assert calls["replace"]["alternate_provider"] is True
    assert calls["replace"]["idempotency_key"] == "alternate-1"


@pytest.mark.asyncio
async def test_numbers_api_download_recording_is_owner_scoped(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        calls["get"] = (order_id, user_id, reseller_id)
        return {
            "_id": order_id,
            "user_id": user_id,
            "reseller_id": reseller_id,
            "number_mode": "voice",
            "provider": "textverified",
            "voice_recording_uri": "/api/pub/v2/calls/call-1/recording",
        }

    async def fake_download_voice_order_recording(order):
        calls["download"] = (order["provider"], order["voice_recording_uri"])
        return {"content": b"audio-bytes", "content_type": "audio/mpeg", "filename": "call-recording.mp3"}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    monkeypatch.setattr(api, "download_voice_order_recording", fake_download_voice_order_recording)
    request = make_mocked_request("GET", "/api/v1/numbers/orders/order-1/recording", match_info={"order_id": "order-1"})

    response = await api.download_order_recording(request)

    assert calls["auth_scope"] == "numbers:orders:read"
    assert calls["get"] == ("order-1", 123, 456)
    assert calls["download"] == ("textverified", "/api/pub/v2/calls/call-1/recording")
    assert response.status == 200
    assert response.body == b"audio-bytes"
    assert response.content_type == "audio/mpeg"
    assert response.headers["Content-Disposition"] == 'attachment; filename="call-recording.mp3"'
    assert response.headers["X-RateLimit-Bucket"] == "numbers:orders:read"


@pytest.mark.asyncio
async def test_numbers_api_download_recording_returns_not_ready(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        return {"_id": order_id, "number_mode": "voice", "provider": "textverified"}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    request = make_mocked_request("GET", "/api/v1/numbers/orders/order-1/recording", match_info={"order_id": "order-1"})

    response = await api.download_order_recording(request)
    payload = json.loads(response.text)

    assert response.status == 404
    assert payload["code"] == "recording_not_ready"
    assert response.headers["X-RateLimit-Bucket"] == "numbers:orders:read"


@pytest.mark.asyncio
async def test_numbers_api_rental_sms_uses_rental_service(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        calls["get"] = (order_id, user_id, reseller_id)
        return {"_id": order_id, "user_id": user_id, "reseller_id": reseller_id, "number_mode": "rental"}

    async def fake_rental_sms_state(order):
        calls["service"] = order
        return {"ok": True, "messages": ["Code 123"], "order": {"id": order["_id"], "mode": "rental"}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    monkeypatch.setattr(api, "rental_sms_state", fake_rental_sms_state)
    request = make_mocked_request("POST", "/api/v1/numbers/orders/rental-1/rental/sms", match_info={"order_id": "rental-1"})

    response = await api.rental_sms_order(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:orders:rental"
    assert calls["get"] == ("rental-1", 123, 456)
    assert calls["service"]["_id"] == "rental-1"
    assert payload == {"ok": True, "messages": ["Code 123"], "order": {"id": "rental-1", "mode": "rental"}}
    assert response.headers["X-RateLimit-Bucket"] == "numbers:orders:rental"


@pytest.mark.asyncio
async def test_numbers_api_renew_rental_requires_scoped_order_and_passes_idempotency(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_get_user_number_order(order_id, user_id, reseller_id):
        calls["get"] = (order_id, user_id, reseller_id)
        return {"_id": order_id, "user_id": user_id, "reseller_id": reseller_id, "number_mode": "rental"}

    async def fake_renew_rental_order(**kwargs):
        calls["renew"] = kwargs
        return {"ok": True, "order": {"id": kwargs["order"]["_id"], "mode": "rental"}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_user_number_order", fake_get_user_number_order)
    monkeypatch.setattr(api, "renew_rental_order", fake_renew_rental_order)
    request = make_mocked_request(
        "POST",
        "/api/v1/numbers/orders/rental-1/rental/renew",
        headers={"Idempotency-Key": "renew-1"},
        match_info={"order_id": "rental-1"},
    )

    response = await api.renew_rental(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:orders:rental"
    assert calls["get"] == ("rental-1", 123, 456)
    assert calls["renew"]["user_id"] == 123
    assert calls["renew"]["idempotency_key"] == "renew-1"
    assert calls["renew"]["order"]["_id"] == "rental-1"
    assert payload == {"ok": True, "order": {"id": "rental-1", "mode": "rental"}}
    assert response.headers["X-RateLimit-Bucket"] == "numbers:orders:rental"


@pytest.mark.asyncio
async def test_numbers_api_quotes_reject_unsupported_modes(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    request = make_mocked_request("GET", "/api/v1/numbers/quotes?mode=unknown&service=telegram&country=1")

    response = await api.quotes(request)
    payload = json.loads(response.text)

    assert response.status == 400
    assert payload["code"] == "unsupported_mode"
    assert response.headers["X-RateLimit-Bucket"] == "numbers:quotes"


@pytest.mark.asyncio
async def test_numbers_api_create_order_requires_api_key(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        raise web.HTTPUnauthorized(text="missing api key")

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    request = make_mocked_request("POST", "/api/v1/numbers/orders", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"quote_token": "quote"}).encode("utf-8")

    with pytest.raises(web.HTTPUnauthorized):
        await api.create_order(request)


@pytest.mark.asyncio
async def test_numbers_api_create_order_uses_order_service(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_create_number_order_from_quote(**kwargs):
        calls.update(kwargs)
        return {"ok": True, "order": {"id": "order-1"}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "create_number_order_from_quote", fake_create_number_order_from_quote)
    request = make_mocked_request(
        "POST",
        "/api/v1/numbers/orders",
        headers={"Content-Type": "application/json", "Authorization": "Bearer key", "Idempotency-Key": "idem-1"},
    )
    request._read_bytes = json.dumps({"quote_token": "quote-1", "language": "en"}).encode("utf-8")

    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload == {"ok": True, "order": {"id": "order-1"}}
    assert response.headers["X-RateLimit-Bucket"] == "numbers:orders:create"
    assert calls == {
        "auth_scope": "numbers:orders:create",
        "user_id": 123,
        "reseller_id": 456,
        "quote_token": "quote-1",
        "idempotency_key": "idem-1",
        "lang": "en",
    }


@pytest.mark.asyncio
async def test_numbers_api_lists_refund_reviews_scoped_to_reseller(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_list_reviews(**kwargs):
        calls["list"] = kwargs
        return [
            {
                "_id": "order-1",
                "source": "numbers_api",
                "number_mode": "temp",
                "user_id": 123,
                "reseller_id": 456,
                "provider": "echo",
                "provider_order_id": "P-100",
                "provider_number": "+15550001111",
                "temp_service_key": "anthropic",
                "temp_country": "us",
                "status": "success",
                "temp_refund_support_review_status": "open",
                "temp_refund_support_review_reason": "provider_cancel_failed",
            }
        ]

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "list_api_temp_refund_support_reviews", fake_list_reviews)
    request = make_mocked_request("GET", "/api/v1/numbers/ops/refund-reviews?limit=10")

    response = await api.list_refund_reviews(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth_scope"] == "numbers:support:review"
    assert calls["list"] == {"limit": 10, "reseller_id": 456, "include_resolved": False}
    assert payload["ok"] is True
    assert payload["reviews"][0]["id"] == "order-1"
    assert payload["reviews"][0]["status"] == "open"
    assert payload["reviews"][0]["reason"] == "provider_cancel_failed"
    assert payload["reviews"][0]["details"]["provider_order_id"] == "P-100"
    assert payload["reviews"][0]["details"]["number"] == "+15550001111"
    assert payload["reviews"][0]["details"]["service"] == "anthropic"


@pytest.mark.asyncio
async def test_numbers_api_resolve_refund_review_marks_review_only(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_resolve_review(**kwargs):
        calls["resolve"] = kwargs
        return {
            "_id": kwargs["order_id"],
            "source": "numbers_api",
            "number_mode": "temp",
            "user_id": 777,
            "reseller_id": 456,
            "status": "success",
            "temp_refund_support_review_status": "resolved",
            "temp_refund_support_review_reason": "provider_cancel_failed",
            "temp_refund_support_review_resolution": kwargs["resolution"],
            "temp_refund_support_review_notes": kwargs["notes"],
        }

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "resolve_api_temp_refund_support_review", fake_resolve_review)
    request = make_mocked_request(
        "POST",
        "/api/v1/numbers/ops/refund-reviews/order-1/resolve",
        headers={"Content-Type": "application/json"},
        match_info={"order_id": "order-1"},
    )
    request._read_bytes = json.dumps({"resolution": "reviewed in provider dashboard", "notes": "SUP-1"}).encode("utf-8")

    response = await api.resolve_refund_review(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth_scope"] == "numbers:support:review"
    assert calls["resolve"] == {
        "order_id": "order-1",
        "actor_user_id": 123,
        "reseller_id": 456,
        "resolution": "reviewed in provider dashboard",
        "notes": "SUP-1",
    }
    assert payload["review"]["status"] == "resolved"
    assert payload["review"]["resolution"] == "reviewed in provider dashboard"
