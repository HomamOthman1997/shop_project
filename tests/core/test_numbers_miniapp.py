from aiohttp import web

from services.numbers import miniapp


def test_numbers_bootstrap_payload_has_core_filters():
    miniapp._BOOTSTRAP_CACHE["data"] = None

    payload = miniapp._bootstrap_payload()

    assert payload["defaults"] == {"mode": "temp", "service": "telegram", "country": "1", "state": "none"}
    assert [item["key"] for item in payload["modes"]] == ["temp", "rental", "voice"]
    assert any(item["code"] == "1" for item in payload["countries"])
    assert any(item["code"] == "none" for item in payload["states_us"])
    assert any(item["key"] == "telegram" for item in payload["services"])


def test_numbers_price_rows_use_public_provider_ids(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "numbers_success_rate_display_min_attempts", 1, raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "alpha_provider": {"price": 1.25, "base_price": 1.0, "success_rate": 88, "success_attempts": 10},
            "beta_provider": {
                "price": 0,
                "available_for_buy": False,
                "provider_reason": "provider_balance_low",
                "success_attempts": 0,
            },
        },
        "temp",
    )

    assert rows[0]["provider_id"].startswith("S")
    assert rows[0]["price_label"] == "$1.25"
    assert rows[0]["success_rate"] == "88%"
    assert rows[-1]["available"] is False
    assert rows[-1]["reason"] == "Provider balance is low"


def test_numbers_temp_rows_include_signed_quote_and_hide_internal_lanes(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "bot_numbers_token", "numbers-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "bot_main_token", "main-token", raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "textverified": {
                "price": 0.5,
                "base_price": 0.4,
                "api_service_name": "attapoll",
                "available_for_buy": True,
            },
            "smsman": {
                "price": 0.3,
                "base_price": 0.25,
                "api_service_name": "1230",
                "available_for_buy": True,
            },
        },
        "temp",
        service="attapoll",
        country="1",
        state="none",
    )

    assert [row["provider_id"] for row in rows] == ["S2"]
    quote = miniapp._verify_quote_token(rows[0]["quote_token"])
    assert quote["service"] == "attapoll"
    assert quote["provider"] == "textverified"


def test_register_numbers_routes_adds_public_endpoints():
    app = web.Application()

    miniapp.register_numbers_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/mini/numbers") in routes
    assert ("GET", "/mini/numbers/static/{name}") in routes
    assert ("GET", "/mini/numbers/api/bootstrap") in routes
    assert ("GET", "/mini/numbers/api/prices") in routes
    assert ("GET", "/mini/numbers/api/orders") in routes
    assert ("POST", "/mini/numbers/api/purchase") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/refresh") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/cancel") in routes
