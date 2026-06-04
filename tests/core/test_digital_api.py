import json
from datetime import UTC, datetime

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services.digital_products import api
from services.platform.api_auth import ApiAuthContext
from services.platform.api_rate_limits import ApiRateLimitDecision


async def allow_rate_limit(auth, *, bucket, limit, window_seconds=60):
    return ApiRateLimitDecision(bucket=bucket, limit=limit, remaining=limit - 1, reset_at=9999999999, window_seconds=window_seconds)


def auth_context(scope: str = "digital:catalog") -> ApiAuthContext:
    return ApiAuthContext(key_id="key-1", user_id=123, reseller_id=456, scopes=(scope,))


def json_request(method: str, path: str, body: dict | None = None, *, headers: dict | None = None):
    request = make_mocked_request(method, path, headers={"Content-Type": "application/json", **(headers or {})})
    request._read_bytes = json.dumps(body or {}).encode("utf-8")
    return request


def test_register_digital_api_routes_adds_versioned_endpoints():
    app = web.Application()

    api.register_digital_api_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/api/v1/digital/health") in routes
    assert ("GET", "/api/v1/digital/account") in routes
    assert ("GET", "/api/v1/digital/catalog") in routes
    assert ("GET", "/api/v1/digital/quotes") in routes
    assert ("GET", "/api/v1/digital/orders") in routes
    assert ("GET", "/api/v1/digital/orders/{order_id}") in routes
    assert ("POST", "/api/v1/digital/orders") in routes


def test_digital_quote_token_round_trips_signed_payload():
    token = api.make_digital_quote_token({"kind": "game", "game_id": "pubgm", "item_id": "1800_uc", "sale_price": 21.25})

    payload = api.verify_digital_quote_token(token)

    assert payload["kind"] == "game"
    assert payload["game_id"] == "pubgm"
    assert payload["item_id"] == "1800_uc"
    assert payload["sale_price"] == 21.25
    assert payload["exp"] > 0


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
        "service_ref_id": "g2bulk:topup:2968",
        "sale_price": 21.25,
        "cost_price": 21.25,
    }
    first_update = calls["updates"][0][1]
    assert first_update["manual_fulfillment_required"] is True
    assert first_update["manual_fulfillment_status"] == "pending"
    assert first_update["api_idempotency_key"] == "digital-order-1"
    assert calls["notify"]["player_data"]["Player Id"] == "51293484551"
    assert payload["order"]["id"] == "order-1"
    assert payload["order"]["public_status"] == "pending"


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
