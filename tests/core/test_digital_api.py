import json
from datetime import UTC, datetime

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services.digital_products import api
from services.platform.api_auth import ApiAuthContext
from services.platform.api_rate_limits import ApiRateLimitDecision
from tests.core.test_telegram_webapp_auth import signed_init_data


async def allow_rate_limit(auth, *, bucket, limit, window_seconds=60):
    return ApiRateLimitDecision(bucket=bucket, limit=limit, remaining=limit - 1, reset_at=9999999999, window_seconds=window_seconds)


def auth_context(scope: str = "digital:catalog") -> ApiAuthContext:
    return ApiAuthContext(key_id="key-1", user_id=123, reseller_id=456, scopes=(scope,))


def json_request(method: str, path: str, body: dict | None = None, *, headers: dict | None = None, match_info: dict | None = None):
    kwargs = {"match_info": match_info} if match_info is not None else {}
    request = make_mocked_request(method, path, headers={"Content-Type": "application/json", **(headers or {})}, **kwargs)
    request._read_bytes = json.dumps(body or {}).encode("utf-8")
    return request


def test_register_digital_api_routes_adds_versioned_endpoints():
    app = web.Application()

    api.register_digital_api_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/api/v1/digital/health") in routes
    assert ("GET", "/api/v1/digital/account") in routes
    assert ("GET", "/api/v1/digital/catalog") in routes
    assert ("GET", "/api/v1/digital/source-diagnostics") in routes
    assert ("GET", "/api/v1/digital/quotes") in routes
    assert ("GET", "/api/v1/digital/orders") in routes
    assert ("GET", "/api/v1/digital/orders/{order_id}") in routes
    assert ("GET", "/api/v1/digital/admin/orders") in routes
    assert ("POST", "/api/v1/digital/orders") in routes
    assert ("POST", "/api/v1/digital/orders/{order_id}/manual-action") in routes


def test_digital_quote_token_round_trips_signed_payload():
    token = api.make_digital_quote_token({"kind": "game", "game_id": "pubgm", "item_id": "1800_uc", "sale_price": 21.25})

    payload = api.verify_digital_quote_token(token)

    assert payload["kind"] == "game"
    assert payload["game_id"] == "pubgm"
    assert payload["item_id"] == "1800_uc"
    assert payload["sale_price"] == 21.25
    assert payload["exp"] > 0


@pytest.mark.asyncio
async def test_digital_user_auth_uses_direct_wallet_for_telegram_user(monkeypatch):
    monkeypatch.setattr(api.settings, "bot_digital_products_token", "123:test", raising=False)
    request = make_mocked_request(
        "GET",
        "/api/v1/digital/account",
        headers={"X-Telegram-Init-Data": signed_init_data(token="123:test", user_id=777)},
    )

    auth = await api.require_digital_user_auth(request, "digital:account:read")

    assert auth.user_id == 777
    assert auth.reseller_id == 777
    assert auth.key_id == "telegram:777"


@pytest.mark.asyncio
async def test_digital_user_auth_rejects_admin_scope_for_telegram_user(monkeypatch):
    monkeypatch.setattr(api.settings, "bot_digital_products_token", "123:test", raising=False)
    request = make_mocked_request(
        "GET",
        "/api/v1/digital/admin/orders",
        headers={"X-Telegram-Init-Data": signed_init_data(token="123:test", user_id=777)},
    )

    with pytest.raises(web.HTTPForbidden) as exc_info:
        await api.require_digital_user_auth(request, "digital:orders:manage")
    assert exc_info.value.text == "api key required"


@pytest.mark.asyncio
async def test_digital_order_detail_is_scoped_to_current_customer(monkeypatch):
    calls = {}
    order = {
        "_id": "order-1",
        "user_id": 123,
        "reseller_id": 123,
        "service_type": "core_digital_products",
        "digital_kind": "game",
        "manual_item_name": "1800 UC",
        "manual_game_name": "PUBG Mobile",
        "status": "paid",
        "retail_amount": 21.25,
    }

    async def fake_require_auth(request, required_scope):
        calls["scope"] = required_scope
        return ApiAuthContext(key_id="website:account-1", user_id=123, reseller_id=123, scopes=("digital:orders:read",))

    class Orders:
        async def find_one(self, query):
            calls["query"] = query
            return order

    monkeypatch.setattr(api, "require_digital_user_auth", fake_require_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "db", type("Db", (), {"orders": Orders()})())

    request = make_mocked_request("GET", "/api/v1/digital/orders/order-1", match_info={"order_id": "order-1"})
    response = await api.order_detail(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["scope"] == "digital:orders:read"
    assert calls["query"]["_id"] == "order-1"
    assert calls["query"]["user_id"] == 123
    assert calls["query"]["reseller_id"] == 123
    assert payload["order"]["id"] == "order-1"
    assert payload["order"]["api_actions"]["get"]["scope"] == "digital:orders:read"
    assert payload["order"]["api_actions"]["get"]["endpoint"] == "/api/v1/digital/orders/order-1"


@pytest.mark.asyncio
async def test_digital_catalog_exposes_backend_product_watchlist(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    async def fake_snapshot(force=False):
        return {"games": [], "gift_categories": [], "providers": {}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_catalog_snapshot", fake_snapshot)
    monkeypatch.setattr(api, "load_product_provider_sources", lambda: [])

    request = make_mocked_request("GET", "/api/v1/digital/catalog")
    response = await api.catalog(request)
    payload = json.loads(response.text)

    assert response.status == 200
    products = {row["id"]: row for row in payload["products"]}
    categories = {row["id"]: row for row in payload["product_categories"]}
    assert products["syriatel"]["category"] == "syrian_services"
    assert products["syriatel"]["input_fields"][0]["id"] == "phone_number"
    assert products["syriatel"]["api_actions"]["quotes"]["endpoint"] == "/api/v1/digital/quotes?kind=product&product_id=syriatel"
    assert products["chatgpt_via_apple"]["sourcing_policy"] == "indirect_apple"
    assert products["chatgpt_via_apple"]["input_fields"][0]["id"] == "apple_region"
    assert categories["syrian_services"]["count"] >= 12
    assert categories["syrian_services"]["label"]["ar"] == "خدمات سورية"
    category_order = [row["id"] for row in payload["product_categories"]]
    assert category_order[:4] == ["games", "chat_apps", "gift_cards", "subscriptions"]
    featured = {row["id"]: row for row in payload["featured_collections"]}
    assert "bittopup" in featured
    assert "pubg" in featured["bittopup"]["product_ids"]
    assert payload["source_diagnostics"]["status"] == "ok"
    assert payload["source_diagnostics"]["issues_count"] == 0
    assert payload["source_diagnostics"]["watchlist_issues_count"] == 0
    assert payload["source_diagnostics"]["source_issues_count"] == 0


@pytest.mark.asyncio
async def test_digital_catalog_reports_provider_source_diagnostics(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    async def fake_snapshot(force=False):
        return {"games": [], "gift_categories": [], "providers": {}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_catalog_snapshot", fake_snapshot)
    monkeypatch.setattr(
        api,
        "load_product_provider_sources",
        lambda: [
            api.ProductProviderSource(
                product_key="missing_product",
                package_key="broken",
                package_name="Broken",
                duration="",
                provider="external",
                fulfillment_mode="manual_topup",
                source_ref="broken-source",
                source_url="https://example.test/broken",
                price_usd=1.0,
                available=True,
                public_note="",
            )
        ],
    )

    request = make_mocked_request("GET", "/api/v1/digital/catalog")
    response = await api.catalog(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["source_diagnostics"]["status"] == "needs_review"
    assert payload["source_diagnostics"]["source_issues_count"] == 1
    assert payload["source_diagnostics"]["issue_counts"]["unknown_product"] == 1


@pytest.mark.asyncio
async def test_digital_catalog_diagnostics_include_inactive_broken_sources(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    async def fake_snapshot(force=False):
        return {"games": [], "gift_categories": [], "providers": {}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_catalog_snapshot", fake_snapshot)
    monkeypatch.setattr(api, "active_product_provider_sources", lambda: [])
    monkeypatch.setattr(
        api,
        "load_product_provider_sources",
        lambda: [
            api.ProductProviderSource(
                product_key="syriatel",
                package_key="syriatel_balance",
                package_name="Syriatel Balance",
                duration="",
                provider="external",
                fulfillment_mode="manual_topup",
                source_ref="syriatel-balance",
                source_url="https://example.test/syriatel",
                price_usd=0.0,
                available=False,
                public_note="",
            )
        ],
    )

    request = make_mocked_request("GET", "/api/v1/digital/catalog")
    response = await api.catalog(request)
    payload = json.loads(response.text)
    products = {row["id"]: row for row in payload["products"]}

    assert response.status == 200
    assert products["syriatel"]["orderable"] is False
    assert payload["source_diagnostics"]["status"] == "needs_review"
    assert payload["source_diagnostics"]["issue_counts"]["invalid_price"] == 1


@pytest.mark.asyncio
async def test_digital_source_diagnostics_endpoint_returns_details(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["scope"] = required_scope
        return auth_context(required_scope)

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(
        api,
        "load_product_provider_sources",
        lambda: [
            api.ProductProviderSource(
                product_key="missing_product",
                package_key="broken",
                package_name="Broken",
                duration="",
                provider="external",
                fulfillment_mode="manual_topup",
                source_ref="broken-source",
                source_url="https://example.test/broken",
                price_usd=1.0,
                available=True,
                public_note="",
            )
        ],
    )

    request = make_mocked_request("GET", "/api/v1/digital/source-diagnostics")
    response = await api.source_diagnostics(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["scope"] == "digital:sources:read"
    assert payload["diagnostics"]["status"] == "needs_review"
    assert payload["diagnostics"]["source_issues"][0]["code"] == "unknown_product"


@pytest.mark.asyncio
async def test_digital_product_quotes_return_empty_until_backend_source_exists(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "active_product_provider_sources", lambda: [])

    request = make_mocked_request("GET", "/api/v1/digital/quotes?kind=product&product_id=syriatel")
    response = await api.quotes(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["kind"] == "product"
    assert payload["product"]["id"] == "syriatel"
    assert payload["offers"] == []


@pytest.mark.asyncio
async def test_digital_product_quotes_are_signed_from_backend_sources(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(
        api,
        "active_product_provider_sources",
        lambda: [
            api.ProductProviderSource(
                product_key="netflix",
                package_key="netflix_1m",
                package_name="Netflix 1 Month",
                duration="1 month",
                provider="external",
                fulfillment_mode="manual_topup",
                source_ref="netflix-manual-1m",
                source_url="https://example.test/netflix",
                price_usd=4.25,
                available=True,
                public_note="Manual source",
            ),
            api.ProductProviderSource(
                product_key="netflix",
                package_key="netflix_1m",
                package_name="Netflix 1 Month",
                duration="1 month",
                provider="g2g",
                fulfillment_mode="manual_topup",
                source_ref="g2g-netflix-1m",
                source_url="https://example.test/g2g-netflix",
                price_usd=4.75,
                available=True,
                public_note="Marketplace source",
            )
        ],
    )

    request = make_mocked_request("GET", "/api/v1/digital/quotes?kind=product&product_id=netflix")
    response = await api.quotes(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["offers"][0]["id"] == "netflix_1m"
    quote = api.verify_digital_quote_token(payload["offers"][0]["quote_token"])
    assert quote["kind"] == "product"
    assert quote["product_id"] == "netflix"
    assert quote["provider"] == "external"
    assert len(quote["provider_offers"]) == 2
    assert quote["provider_offers"][0]["source_url"] == "https://example.test/netflix"
    assert quote["provider_offers"][1]["source_url"] == "https://example.test/g2g-netflix"


@pytest.mark.asyncio
async def test_digital_quotes_returns_signed_game_offers(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["scope"] = required_scope
        return auth_context(required_scope)

    async def fake_snapshot(force=False):
        return {"games": [{"id": "pubgm", "name": "PUBG Mobile", "image_url": ""}], "gift_categories": [], "providers": {}}

    async def fake_topups(game_id, force=False):
        calls["topups"] = (game_id, force)
        return [
            {
                "id": "1800_uc",
                "name": "1800 UC",
                "price": 21.25,
                "best_provider": "g2bulk",
                "best_provider_ref_id": "2968",
                "provider_offers": [{"provider": "g2bulk", "ref_id": "2968", "price": 21.25, "available": True}],
            }
        ]

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_catalog_snapshot", fake_snapshot)
    monkeypatch.setattr(api, "get_game_topups", fake_topups)
    monkeypatch.setattr(api, "digital_provider_enabled", lambda provider: True)

    request = make_mocked_request("GET", "/api/v1/digital/quotes?kind=game&game_id=pubgm")
    response = await api.quotes(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["scope"] == "digital:catalog"
    assert calls["topups"] == ("pubgm", False)
    assert payload["offers"][0]["id"] == "1800_uc"
    assert payload["fulfillment"]["mode"] == "manual_topup"
    assert payload["fulfillment"]["min_minutes"] == 1
    assert payload["fulfillment"]["max_minutes"] == 60
    quote = api.verify_digital_quote_token(payload["offers"][0]["quote_token"])
    assert quote["game_id"] == "pubgm"
    assert quote["provider_offers"][0]["ref_id"] == "2968"


@pytest.mark.asyncio
async def test_digital_create_order_charges_and_marks_manual_topup(monkeypatch):
    calls = {}
    quote_token = api.make_digital_quote_token(
        {
            "kind": "game",
            "game_id": "pubgm",
            "game_name": "PUBG Mobile",
            "item_id": "1800_uc",
            "item_name": "1800 UC",
            "requires_server": False,
            "sale_price": 21.25,
            "cost_price": 21.25,
            "provider": "g2bulk",
            "provider_ref_id": "2968",
            "provider_offers": [{"provider": "g2bulk", "ref_id": "2968", "price": 21.25, "available": True}],
        }
    )

    async def fake_require_api_auth(request, required_scope):
        calls["scope"] = required_scope
        return auth_context(required_scope)

    async def fake_charge(**kwargs):
        calls["charge"] = kwargs
        return {
            "_id": "order-1",
            "user_id": kwargs["user_id"],
            "reseller_id": kwargs["reseller_id"],
            "service_type": "core_digital_products",
            "service_ref_id": kwargs["service_ref_id"],
            "retail_amount": kwargs["sale_price"],
            "wholesale_amount": kwargs["cost_price"],
            "status": "paid",
            "created_at": datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
        }, None

    async def fake_update(order_id, details):
        calls.setdefault("updates", []).append((order_id, details))

    async def fake_notify(order, *, player_data, offers):
        calls["notify"] = {"order": order, "player_data": player_data, "offers": offers}
        return True

    async def fake_existing(idempotency_key, auth):
        return None

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_idempotent_order", fake_existing)
    monkeypatch.setattr(api, "_charge_digital_order", fake_charge)
    monkeypatch.setattr(api, "update_order_details", fake_update)
    monkeypatch.setattr(api, "_notify_owner_manual_order", fake_notify)

    request = json_request(
        "POST",
        "/api/v1/digital/orders",
        {"quote_token": quote_token, "player_id": "51293484551"},
        headers={"Idempotency-Key": "digital-order-1"},
    )
    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["scope"] == "digital:orders:create"
    assert calls["charge"] == {
        "user_id": 123,
        "reseller_id": 456,
        "service_ref_id": "g2bulk:game:2968",
        "sale_price": 21.25,
        "cost_price": 21.25,
    }
    first_update = calls["updates"][0][1]
    assert first_update["manual_fulfillment_required"] is True
    assert first_update["manual_fulfillment_status"] == "pending"
    assert first_update["fulfillment_min_minutes"] == 1
    assert first_update["fulfillment_max_minutes"] == 60
    assert first_update["fulfillment_label"] == "تنفيذ يدوي خلال دقيقة إلى ساعة"
    assert first_update["api_idempotency_key"] == "digital-order-1"
    assert calls["notify"]["player_data"]["Player Id"] == "51293484551"
    assert payload["order"]["id"] == "order-1"
    assert payload["order"]["public_status"] == "pending"
    assert payload["order"]["fulfillment_mode"] == "manual_topup"
    assert payload["order"]["fulfillment_min_minutes"] == 1
    assert payload["order"]["fulfillment_max_minutes"] == 60


@pytest.mark.asyncio
async def test_digital_create_product_order_uses_customer_data(monkeypatch):
    calls = {}
    quote_token = api.make_digital_quote_token(
        {
            "kind": "product",
            "product_id": "netflix",
            "product_name": "Netflix",
            "item_id": "netflix_1m",
            "item_name": "Netflix 1 Month",
            "duration": "1 month",
            "input_fields": [
                {"id": "account", "required": True},
                {"id": "notes", "required": False},
            ],
            "sale_price": 4.25,
            "cost_price": 4.25,
            "provider": "external",
            "provider_ref_id": "netflix-manual-1m",
            "provider_offers": [
                {
                    "provider": "external",
                    "ref_id": "netflix-manual-1m",
                    "price": 4.25,
                    "available": True,
                    "fulfillment_mode": "manual_topup",
                    "source_url": "https://example.test/netflix",
                }
            ],
        }
    )

    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    async def fake_charge(**kwargs):
        calls["charge"] = kwargs
        return {
            "_id": "order-product-1",
            "user_id": kwargs["user_id"],
            "reseller_id": kwargs["reseller_id"],
            "service_type": "core_digital_products",
            "service_ref_id": kwargs["service_ref_id"],
            "retail_amount": kwargs["sale_price"],
            "wholesale_amount": kwargs["cost_price"],
            "status": "paid",
            "created_at": datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
        }, None

    async def fake_update(order_id, details):
        calls.setdefault("updates", []).append((order_id, details))

    async def fake_notify(order, *, player_data, offers):
        calls["notify"] = {"order": order, "player_data": player_data, "offers": offers}
        return True

    async def fake_existing(idempotency_key, auth):
        return None

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_idempotent_order", fake_existing)
    monkeypatch.setattr(api, "_charge_digital_order", fake_charge)
    monkeypatch.setattr(api, "update_order_details", fake_update)
    monkeypatch.setattr(api, "_notify_owner_manual_order", fake_notify)
    monkeypatch.setattr(
        api,
        "active_product_provider_sources",
        lambda: [
            api.ProductProviderSource(
                product_key="netflix",
                package_key="netflix_1m",
                package_name="Netflix 1 Month",
                duration="1 month",
                provider="external",
                fulfillment_mode="manual_topup",
                source_ref="netflix-manual-1m",
                source_url="https://example.test/netflix",
                price_usd=4.25,
                available=True,
                public_note="Manual source",
            )
        ],
    )

    request = json_request(
        "POST",
        "/api/v1/digital/orders",
        {"quote_token": quote_token, "customer_data": {"account": "customer@example.test"}},
    )
    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["charge"]["service_ref_id"] == "external:product:netflix-manual-1m"
    first_update = calls["updates"][0][1]
    assert first_update["digital_kind"] == "product"
    assert first_update["product_id"] == "netflix"
    assert first_update["customer_data"] == {"account": "customer@example.test"}
    assert calls["notify"]["player_data"] == {"account": "customer@example.test"}
    assert calls["notify"]["offers"][0]["source_url"] == "https://example.test/netflix"
    assert payload["order"]["id"] == "order-product-1"


@pytest.mark.asyncio
async def test_digital_create_manual_catalog_order_rechecks_price_and_queues_manual_fulfillment(monkeypatch):
    calls = {}
    quote_token = api.make_digital_quote_token(
        {
            "kind": "manual",
            "product_id": "family-1",
            "product_name": "شحن أوكرانيا",
            "item_id": "product-1",
            "item_name": "100 UAH",
            "sale_price": 3.5,
        }
    )

    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    async def fake_existing(_idempotency_key, _auth):
        return None

    async def fake_fresh(endpoint_id, **_kwargs):
        assert endpoint_id == "product-1"
        return {
            "kind": "manual",
            "product_id": "family-1",
            "product_name": "شحن أوكرانيا",
            "item_id": "product-1",
            "item_name": "100 UAH",
            "manual_variant_name": "Ukraine",
            "sale_price": 3.5,
            "cost_price": 3.5,
            "input_fields": [{"id": "phone_number", "required": True}],
            "provider": "manual_catalog",
            "provider_ref_id": "product-1",
            "provider_offers": [{"provider": "manual_catalog", "ref_id": "product-1", "price": 3.5}],
        }

    async def fake_charge(**kwargs):
        calls["charge"] = kwargs
        return {
            "_id": "manual-order-1",
            "user_id": kwargs["user_id"],
            "reseller_id": kwargs["reseller_id"],
            "service_type": "core_digital_products",
            "retail_amount": kwargs["sale_price"],
            "wholesale_amount": kwargs["cost_price"],
            "status": "paid",
        }, None

    async def fake_update(order_id, details):
        calls.setdefault("updates", []).append((order_id, details))

    async def fake_notify(order, *, player_data, offers):
        calls["notify"] = {"player_data": player_data, "offers": offers}
        return True

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_idempotent_order", fake_existing)
    monkeypatch.setattr(api, "fresh_manual_quote_payload", fake_fresh)
    monkeypatch.setattr(api, "_charge_digital_order", fake_charge)
    monkeypatch.setattr(api, "update_order_details", fake_update)
    monkeypatch.setattr(api, "_notify_owner_manual_order", fake_notify)

    request = json_request(
        "POST",
        "/api/v1/digital/orders",
        {"quote_token": quote_token, "customer_data": {"phone_number": "+380000000000"}},
    )
    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["charge"]["service_ref_id"] == "manual_catalog:manual:product-1"
    assert calls["updates"][0][1]["digital_kind"] == "manual"
    assert calls["updates"][0][1]["manual_variant_name"] == "Ukraine"
    assert calls["notify"]["player_data"]["phone_number"] == "+380000000000"
    assert payload["order"]["public_status"] == "pending"


def _manual_game_quote_token():
    return api.make_digital_quote_token(
        {
            "kind": "manual",
            "product_id": "family-1",
            "product_name": "PUBG",
            "item_id": "product-1",
            "item_name": "325 UC",
            "sale_price": 6.6,
        }
    )


def _fresh_manual_game_quote():
    return {
        "kind": "manual",
        "product_id": "family-1",
        "product_name": "PUBG",
        "item_id": "product-1",
        "item_name": "325 UC",
        "manual_variant_name": "Global",
        "sale_price": 6.6,
        "cost_price": 6.6,
        "input_fields": [{"id": "player_id", "required": True}, {"id": "server_id", "required": True}],
        "provider": "g2bulk",
        "provider_ref_id": "325",
        "provider_offers": [{"provider": "g2bulk", "ref_id": "325", "price": 4.2, "available": True, "fulfillment_mode": "auto_topup"}],
        "execution_mode": "api",
        "api_execution_supported": True,
        "source_kind": "game",
        "source_key": "game:pubgm:325",
        "game_id": "pubgm",
        "requires_server": True,
        "api_player_field": "player_id",
        "api_server_field": "server_id",
    }


def _wire_manual_order_basics(monkeypatch, calls):
    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    async def fake_existing(_idempotency_key, _auth):
        return None

    async def fake_fresh(endpoint_id, **_kwargs):
        assert endpoint_id == "product-1"
        return _fresh_manual_game_quote()

    async def fake_charge(**kwargs):
        calls["charge"] = kwargs
        return {
            "_id": "manual-order-1",
            "user_id": kwargs["user_id"],
            "reseller_id": kwargs["reseller_id"],
            "service_type": "core_digital_products",
            "retail_amount": kwargs["sale_price"],
            "wholesale_amount": kwargs["cost_price"],
            "status": "paid",
        }, None

    async def fake_update(order_id, details):
        calls.setdefault("updates", []).append((order_id, details))

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_idempotent_order", fake_existing)
    monkeypatch.setattr(api, "fresh_manual_quote_payload", fake_fresh)
    monkeypatch.setattr(api, "_charge_digital_order", fake_charge)
    monkeypatch.setattr(api, "update_order_details", fake_update)


@pytest.mark.asyncio
async def test_digital_create_manual_catalog_order_uses_smart_routing_for_games(monkeypatch):
    calls = {}
    _wire_manual_order_basics(monkeypatch, calls)

    async def fake_resolve(quote, *, sale_price):
        calls["resolve_sale_price"] = sale_price
        return {
            "enabled": True,
            "compare_key": "pubg:global:325:uc",
            "sale_price": sale_price,
            "candidates": [{"provider": "g2bulk", "route": "auto_api", "ref_id": "325", "cost_price": 4.2}],
            "diagnostics": {},
        }

    async def fake_execute(order, *, actor_id):
        calls["execute"] = (order, actor_id)
        return {
            "ok": True,
            "route": "auto_api",
            "provider_order_id": "g2-1",
            "patch": {"manual_execution_route": "auto_api", "manual_fulfillment_status": "processing", "provider_order_id": "g2-1"},
        }

    async def fail_auto(*_args, **_kwargs):
        raise AssertionError("legacy submit_manual_auto_api should not run when smart routing applies")

    async def fail_notify(*_args, **_kwargs):
        raise AssertionError("owner manual notification should not run after a successful smart auto route")

    monkeypatch.setattr(api, "resolve_smart_game_routing", fake_resolve)
    monkeypatch.setattr(api, "execute_smart_game_routing", fake_execute)
    monkeypatch.setattr(api, "submit_manual_auto_api", fail_auto)
    monkeypatch.setattr(api, "_notify_owner_manual_order", fail_notify)

    request = json_request(
        "POST",
        "/api/v1/digital/orders",
        {"quote_token": _manual_game_quote_token(), "customer_data": {"player_id": "12345", "server_id": "1"}},
    )
    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["charge"]["sale_price"] == 6.6
    assert calls["resolve_sale_price"] == 6.6
    assert calls["execute"][0]["game_id"] == "pubgm"
    assert calls["execute"][0]["player_id"] == "12345"
    assert calls["execute"][0]["routing_candidates"]
    assert calls["updates"][-1][1]["owner_notification_source"] == "smart_auto_api"
    assert payload["order"]["public_status"] == "processing"


@pytest.mark.asyncio
async def test_digital_create_manual_catalog_order_legacy_auto_when_smart_not_applicable(monkeypatch):
    calls = {}
    _wire_manual_order_basics(monkeypatch, calls)

    async def fake_auto(order, *, actor_id):
        calls["auto"] = (order, actor_id)
        return {
            "ok": True,
            "patch": {"manual_execution_route": "auto_api", "manual_fulfillment_status": "processing", "provider_order_id": "g2-1"},
        }

    async def fail_notify(*_args, **_kwargs):
        raise AssertionError("owner manual notification should not run after successful auto API")

    # Force the legacy single-offer path (e.g. a game whose compare_key cannot be derived).
    monkeypatch.setattr(api, "smart_routing_applicable", lambda _quote: False)
    monkeypatch.setattr(api, "submit_manual_auto_api", fake_auto)
    monkeypatch.setattr(api, "_notify_owner_manual_order", fail_notify)

    request = json_request(
        "POST",
        "/api/v1/digital/orders",
        {"quote_token": _manual_game_quote_token(), "customer_data": {"player_id": "12345", "server_id": "1"}},
    )
    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auto"][0]["player_id"] == "12345"
    assert calls["auto"][0]["server_id"] == "1"
    assert calls["auto"][0]["game_id"] == "pubgm"
    assert calls["updates"][0][1]["manual_execution_mode"] == "api"
    assert calls["updates"][-1][1]["owner_notification_source"] == "auto_api"
    assert payload["order"]["public_status"] == "processing"


@pytest.mark.asyncio
async def test_digital_create_product_order_requires_backend_input_fields(monkeypatch):
    quote_token = api.make_digital_quote_token(
        {
            "kind": "product",
            "product_id": "syriatel",
            "product_name": "Syriatel",
            "item_id": "syriatel_balance",
            "item_name": "Syriatel Balance",
            "sale_price": 1.0,
            "cost_price": 1.0,
            "provider": "external",
            "provider_ref_id": "syriatel-balance",
            "input_fields": [{"id": "phone_number", "required": True}, {"id": "amount", "required": True}],
            "provider_offers": [{"provider": "external", "ref_id": "syriatel-balance", "price": 1.0, "available": True}],
        }
    )

    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    async def fake_existing(idempotency_key, auth):
        return None

    async def fail_charge(**kwargs):
        raise AssertionError("charge should not run when required fields are missing")

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_idempotent_order", fake_existing)
    monkeypatch.setattr(api, "_charge_digital_order", fail_charge)
    monkeypatch.setattr(
        api,
        "active_product_provider_sources",
        lambda: [
            api.ProductProviderSource(
                product_key="syriatel",
                package_key="syriatel_balance",
                package_name="Syriatel Balance",
                duration="",
                provider="external",
                fulfillment_mode="manual_topup",
                source_ref="syriatel-balance",
                source_url="https://example.test/syriatel",
                price_usd=1.0,
                available=True,
                public_note="Manual source",
            )
        ],
    )

    request = json_request(
        "POST",
        "/api/v1/digital/orders",
        {"quote_token": quote_token, "customer_data": {"phone_number": "0999999999"}},
    )
    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 400
    assert payload["code"] == "missing_customer_data_fields"
    assert "amount" in payload["message"]


@pytest.mark.asyncio
async def test_digital_create_product_order_rejects_removed_source(monkeypatch):
    quote_token = api.make_digital_quote_token(
        {
            "kind": "product",
            "product_id": "netflix",
            "product_name": "Netflix",
            "item_id": "netflix_1m",
            "item_name": "Netflix 1 Month",
            "sale_price": 4.25,
            "cost_price": 4.25,
            "provider": "external",
            "provider_ref_id": "netflix-manual-1m",
            "input_fields": [{"id": "account", "required": True}],
            "provider_offers": [{"provider": "external", "ref_id": "netflix-manual-1m", "price": 4.25, "available": True}],
        }
    )

    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    async def fake_existing(idempotency_key, auth):
        return None

    async def fail_charge(**kwargs):
        raise AssertionError("charge should not run when backend source is gone")

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_idempotent_order", fake_existing)
    monkeypatch.setattr(api, "_charge_digital_order", fail_charge)
    monkeypatch.setattr(api, "active_product_provider_sources", lambda: [])

    request = json_request(
        "POST",
        "/api/v1/digital/orders",
        {"quote_token": quote_token, "customer_data": {"account": "customer@example.test"}},
    )
    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 409
    assert payload["code"] == "product_source_unavailable"


@pytest.mark.asyncio
async def test_digital_create_product_order_rejects_changed_backend_price(monkeypatch):
    quote_token = api.make_digital_quote_token(
        {
            "kind": "product",
            "product_id": "netflix",
            "product_name": "Netflix",
            "item_id": "netflix_1m",
            "item_name": "Netflix 1 Month",
            "sale_price": 4.25,
            "cost_price": 4.25,
            "provider": "external",
            "provider_ref_id": "netflix-manual-1m",
            "input_fields": [{"id": "account", "required": True}],
            "provider_offers": [{"provider": "external", "ref_id": "netflix-manual-1m", "price": 4.25, "available": True}],
        }
    )

    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    async def fake_existing(idempotency_key, auth):
        return None

    async def fail_charge(**kwargs):
        raise AssertionError("charge should not run when backend price changed")

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_idempotent_order", fake_existing)
    monkeypatch.setattr(api, "_charge_digital_order", fail_charge)
    monkeypatch.setattr(
        api,
        "active_product_provider_sources",
        lambda: [
            api.ProductProviderSource(
                product_key="netflix",
                package_key="netflix_1m",
                package_name="Netflix 1 Month",
                duration="1 month",
                provider="external",
                fulfillment_mode="manual_topup",
                source_ref="netflix-manual-1m",
                source_url="https://example.test/netflix",
                price_usd=5.0,
                available=True,
                public_note="Manual source",
            )
        ],
    )

    request = json_request(
        "POST",
        "/api/v1/digital/orders",
        {"quote_token": quote_token, "customer_data": {"account": "customer@example.test"}},
    )
    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 409
    assert payload["code"] == "quote_price_changed"
    assert payload["current_price"] == 5.0


@pytest.mark.asyncio
async def test_digital_create_order_replays_existing_idempotent_order(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return auth_context(required_scope)

    async def fake_existing(idempotency_key, auth):
        assert idempotency_key == "retry-1"
        return {
            "_id": "order-1",
            "user_id": auth.user_id,
            "reseller_id": auth.reseller_id,
            "service_type": "core_digital_products",
            "api_order_source": "digital_api",
            "api_idempotency_key": idempotency_key,
            "manual_fulfillment_status": "pending",
            "retail_amount": 21.25,
            "wholesale_amount": 21.25,
        }

    async def fail_charge(**kwargs):
        raise AssertionError("charge should not run for idempotent replay")

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_idempotent_order", fake_existing)
    monkeypatch.setattr(api, "_charge_digital_order", fail_charge)

    request = json_request("POST", "/api/v1/digital/orders", {"quote_token": "expired-or-invalid"}, headers={"Idempotency-Key": "retry-1"})
    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["order"]["id"] == "order-1"
    assert payload["order"]["idempotent_replay"] is True


@pytest.mark.asyncio
async def test_digital_admin_orders_lists_manual_orders(monkeypatch):
    calls = {}
    rows = [
        {
            "_id": "order-1",
            "user_id": 123,
            "reseller_id": 456,
            "service_type": "core_digital_products",
            "fulfillment_mode": "manual_topup",
            "manual_fulfillment_status": "processing",
            "manual_item_name": "Netflix 1 Month",
            "retail_amount": 4.25,
            "wholesale_amount": 4.25,
            "status": "paid",
        }
    ]

    class FakeCursor:
        def sort(self, *args, **kwargs):
            calls["sort"] = (args, kwargs)
            return self

        def limit(self, limit):
            calls["limit"] = limit
            return self

        async def to_list(self, length):
            calls["length"] = length
            return rows

    class FakeOrders:
        def find(self, query):
            calls["query"] = query
            return FakeCursor()

    class FakeDb:
        orders = FakeOrders()

    async def fake_require_api_auth(request, required_scope):
        calls["scope"] = required_scope
        return ApiAuthContext(key_id="admin-key", user_id=999, reseller_id=456, scopes=("digital:orders:manage",))

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "db", FakeDb())

    request = make_mocked_request("GET", "/api/v1/digital/admin/orders?status=processing&limit=25")
    response = await api.list_admin_manual_orders(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["scope"] == "digital:orders:manage"
    assert calls["query"]["fulfillment_mode"] == "manual_topup"
    assert calls["query"]["reseller_id"] == 456
    assert calls["query"]["manual_fulfillment_status"] == "processing"
    assert calls["limit"] == 25
    assert payload["orders"][0]["id"] == "order-1"
    assert payload["orders"][0]["public_status"] == "processing"


@pytest.mark.asyncio
async def test_digital_manual_order_claim_updates_processing(monkeypatch):
    calls = {}
    order = {
        "_id": "order-1",
        "user_id": 123,
        "reseller_id": 456,
        "service_type": "core_digital_products",
        "fulfillment_mode": "manual_topup",
        "manual_item_name": "Netflix 1 Month",
        "status": "paid",
        "retail_amount": 4.25,
        "wholesale_amount": 4.25,
    }

    async def fake_require_api_auth(request, required_scope):
        calls["scope"] = required_scope
        return ApiAuthContext(key_id="admin-key", user_id=999, reseller_id=456, scopes=("digital:orders:manage",))

    async def fake_find(order_id, auth):
        calls["find"] = (order_id, auth.reseller_id)
        return order

    async def fake_update(order_id, details):
        calls.setdefault("updates", []).append((order_id, details))

    async def fake_notify(updated_order, *, status):
        calls["notify"] = (updated_order, status)
        return True

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_manageable_manual_order", fake_find)
    monkeypatch.setattr(api, "update_order_details", fake_update)
    monkeypatch.setattr(api, "_notify_manual_order_user", fake_notify)

    request = json_request(
        "POST",
        "/api/v1/digital/orders/order-1/manual-action",
        {"action": "claim", "note": "working"},
        match_info={"order_id": "order-1"},
    )
    response = await api.manual_order_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["scope"] == "digital:orders:manage"
    assert calls["find"] == ("order-1", 456)
    assert calls["updates"][0][1]["manual_fulfillment_status"] == "processing"
    assert calls["updates"][0][1]["manual_action_note"] == "working"
    assert calls["notify"][1] == "processing"
    assert payload["order"]["public_status"] == "processing"


@pytest.mark.asyncio
async def test_digital_manual_order_auto_api_action_uses_backend_executor(monkeypatch):
    calls = {}
    order = {
        "_id": "order-1",
        "user_id": 123,
        "reseller_id": 456,
        "service_type": "core_digital_products",
        "fulfillment_mode": "manual_topup",
        "manual_item_name": "1800 UC",
        "status": "paid",
        "retail_amount": 21.25,
        "wholesale_amount": 21.25,
    }

    async def fake_require_api_auth(request, required_scope):
        calls["scope"] = required_scope
        return ApiAuthContext(key_id="admin-key", user_id=999, reseller_id=456, scopes=("digital:orders:manage",))

    async def fake_find(order_id, auth):
        return order

    async def fake_submit(order_arg, *, actor_id):
        calls["submit"] = (order_arg, actor_id)
        return {
            "ok": True,
            "code": "auto_api_submitted",
            "provider_order_id": "provider-1",
            "patch": {
                "manual_execution_route": "auto_api",
                "manual_fulfillment_status": "processing",
                "provider_order_id": "provider-1",
            },
        }

    async def fake_notify(updated_order, *, status):
        calls["notify"] = (updated_order, status)
        return True

    async def fake_update(order_id, details):
        calls.setdefault("updates", []).append((order_id, details))

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_manageable_manual_order", fake_find)
    monkeypatch.setattr(api, "submit_manual_auto_api", fake_submit)
    monkeypatch.setattr(api, "_notify_manual_order_user", fake_notify)
    monkeypatch.setattr(api, "update_order_details", fake_update)

    request = json_request(
        "POST",
        "/api/v1/digital/orders/order-1/manual-action",
        {"action": "auto_api"},
        match_info={"order_id": "order-1"},
    )
    response = await api.manual_order_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["scope"] == "digital:orders:manage"
    assert calls["submit"][1] == 999
    assert calls["notify"][1] == "processing"
    assert payload["provider_order_id"] == "provider-1"
    assert payload["order"]["public_status"] == "processing"


@pytest.mark.asyncio
async def test_digital_manual_order_complete_marks_success(monkeypatch):
    calls = {}
    order = {
        "_id": "order-1",
        "user_id": 123,
        "reseller_id": 456,
        "service_type": "core_digital_products",
        "fulfillment_mode": "manual_topup",
        "manual_item_name": "Netflix 1 Month",
        "status": "paid",
        "retail_amount": 4.25,
        "wholesale_amount": 4.25,
    }

    async def fake_require_api_auth(request, required_scope):
        return ApiAuthContext(key_id="admin-key", user_id=999, reseller_id=456, scopes=("digital:orders:manage",))

    async def fake_find(order_id, auth):
        return order

    async def fake_update(order_id, details):
        calls.setdefault("updates", []).append((order_id, details))

    async def fake_status(order_id, status):
        calls["status"] = (order_id, status)

    async def fake_notify(updated_order, *, status, extra_message=""):
        calls["notify"] = (updated_order, status)
        calls["notify_message"] = extra_message
        return True

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_manageable_manual_order", fake_find)
    monkeypatch.setattr(api, "update_order_details", fake_update)
    monkeypatch.setattr(api, "update_order_status", fake_status)
    monkeypatch.setattr(api, "_notify_manual_order_user", fake_notify)

    request = json_request(
        "POST",
        "/api/v1/digital/orders/order-1/manual-action",
        {"action": "complete", "customer_message": "تكرم عينك، اطلب وتنال"},
        match_info={"order_id": "order-1"},
    )
    response = await api.manual_order_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["updates"][0][1]["manual_fulfillment_status"] == "completed"
    assert calls["status"] == ("order-1", "success")
    assert calls["notify"][1] == "completed"
    # The admin's delivery note reaches the customer and is stored on the order.
    assert calls["notify_message"] == "تكرم عينك، اطلب وتنال"
    assert calls["updates"][0][1]["manual_delivery_message"] == "تكرم عينك، اطلب وتنال"
    assert payload["order"]["public_status"] == "completed"


@pytest.mark.asyncio
async def test_digital_manual_order_refund_uses_financial_manager(monkeypatch):
    calls = {}
    order = {
        "_id": "order-1",
        "user_id": 123,
        "reseller_id": 456,
        "service_type": "core_digital_products",
        "fulfillment_mode": "manual_topup",
        "manual_item_name": "Netflix 1 Month",
        "status": "paid",
        "retail_amount": 4.25,
        "wholesale_amount": 4.25,
    }

    async def fake_require_api_auth(request, required_scope):
        return ApiAuthContext(key_id="admin-key", user_id=999, reseller_id=456, scopes=("digital:orders:manage",))

    async def fake_find(order_id, auth):
        return order

    async def fake_update(order_id, details):
        calls.setdefault("updates", []).append((order_id, details))

    async def fake_refund(cls, **kwargs):
        calls["refund"] = kwargs
        return True, "Refund Success"

    async def fake_notify(updated_order, *, status):
        calls["notify"] = (updated_order, status)
        return False

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "_check_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "_find_manageable_manual_order", fake_find)
    monkeypatch.setattr(api, "update_order_details", fake_update)
    monkeypatch.setattr(api.FinancialManager, "refund_core_purchase", classmethod(fake_refund))
    monkeypatch.setattr(api, "_notify_manual_order_user", fake_notify)

    request = json_request(
        "POST",
        "/api/v1/digital/orders/order-1/manual-action",
        {"action": "refund"},
        match_info={"order_id": "order-1"},
    )
    response = await api.manual_order_action(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["refund"] == {
        "user_id": 123,
        "order_id": "order-1",
        "sale_price": 4.25,
        "cost_price": 4.25,
        "reseller_id": 456,
    }
    assert calls["updates"][0][1]["manual_fulfillment_status"] == "refunded"
    assert calls["notify"][1] == "refunded"
    assert payload["order"]["public_status"] == "refunded"
