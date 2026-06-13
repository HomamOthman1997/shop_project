import os
import json
import sys

import pytest

sys.path.insert(0, os.getcwd())


def test_create_app_registers_health_routes():
    from services.digital_products import miniapp

    app = miniapp.create_app()

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/") in routes
    assert ("GET", "/health") in routes
    assert ("GET", "/healthz") in routes
    assert ("GET", "/ready") in routes
    assert ("GET", "/api/v1/digital/families/{service_key}/{family_key}/packages") in routes


def test_named_game_gift_products_are_grouped_under_games_not_store_cards():
    from services.digital_products import miniapp

    snapshot = {
        "gift_categories": [{"id": "cards", "name": "Gift Cards"}],
        "products_by_category": {
            "cards": [
                {"id": "pubg-card", "name": "PUBG Mobile Gift Card", "price": 10, "stock": 1},
                {"id": "valorant-card", "name": "Valorant Gift Card 10 USD", "price": 10, "stock": 1},
                {"id": "steam-card", "name": "Steam Gift Card", "price": 10, "stock": 1},
            ]
        },
    }

    groups, _source_map = miniapp._grouped_gift_categories(snapshot)
    grouped = {(row["service_key"], row["name"]) for row in groups}

    assert ("games", "PUBG") in grouped
    assert ("games", "Valorant") in grouped
    assert ("store_cards", "Steam") in grouped
    assert ("store_cards", "PUBG") not in grouped
    assert ("store_cards", "Valorant") not in grouped


def test_store_card_service_tree_uses_countries_and_global_only():
    from services.digital_products import miniapp

    snapshot = {
        "gift_categories": [
            {"id": "ps-network", "name": "PlayStation Network"},
            {"id": "ps-austria", "name": "PlayStation Austria"},
        ],
        "products_by_category": {
            "ps-network": [{"id": "psn-10", "name": "PlayStation Network 10", "price": 10, "stock": 1}],
            "ps-austria": [{"id": "ps-at-10", "name": "PlayStation Austria 10", "price": 10, "stock": 1}],
        },
    }
    group_id = "grp:g:store_cards:playstation"

    tree = miniapp._build_service_tree(
        snapshot,
        grouped_games=[],
        game_source_map={},
        grouped_gifts=[{"id": group_id, "service_key": "store_cards", "name": "PlayStation"}],
        gift_source_map={group_id: ["ps-network", "ps-austria"]},
    )

    playstation = next(row for row in tree if row["key"] == "store_cards")["families"][0]
    assert playstation["selection_kind"] == "region"
    assert [(row["name"], row["variant_kind"]) for row in playstation["variants"]] == [
        ("Global", "region"),
        ("Austria", "region"),
    ]


def test_game_country_variants_are_allowed_but_random_options_are_not():
    from services.digital_products import miniapp

    assert miniapp._is_allowed_game_variant({"name": "Brazil", "variant_kind": "region"}) is True
    assert miniapp._is_allowed_game_variant({"name": "Random bundle", "variant_kind": "option"}) is False


@pytest.mark.asyncio
async def test_website_enabled_starts_http_server_without_miniapps(monkeypatch):
    from services.digital_products import miniapp

    calls = {}

    class FakeRunner:
        def __init__(self, app):
            calls["app"] = app

        async def setup(self):
            calls["runner_setup"] = True

    class FakeSite:
        def __init__(self, runner, host, port):
            calls["site"] = (runner, host, port)

        async def start(self):
            calls["site_started"] = True

    async def fake_bootstrap():
        calls["bootstrap"] = True

    async def fake_catalog():
        calls["catalog_warmed"] = True
        return {}

    monkeypatch.setattr(miniapp.settings, "website_enabled", True, raising=False)
    monkeypatch.setattr(miniapp.settings, "digital_products_miniapp_enabled", False, raising=False)
    monkeypatch.setattr(miniapp.settings, "numbers_miniapp_enabled", False, raising=False)
    monkeypatch.setattr(miniapp.settings, "cardex_miniapp_enabled", False, raising=False)
    monkeypatch.setattr(miniapp.settings, "digital_products_miniapp_host", "0.0.0.0", raising=False)
    monkeypatch.setattr(miniapp.settings, "digital_products_miniapp_port", 8123, raising=False)
    monkeypatch.setattr(miniapp, "bootstrap_miniapp_indexes", fake_bootstrap)
    monkeypatch.setattr(miniapp, "_catalog_payload", fake_catalog)
    monkeypatch.setattr(miniapp.web, "AppRunner", FakeRunner)
    monkeypatch.setattr(miniapp.web, "TCPSite", FakeSite)

    started = await miniapp.start_miniapp_server()

    assert started is not None
    assert calls["bootstrap"] is True
    assert calls["catalog_warmed"] is True
    assert calls["runner_setup"] is True
    assert calls["site_started"] is True
    assert calls["site"][1:] == ("0.0.0.0", 8123)


@pytest.mark.asyncio
async def test_catalog_payload_reuses_cached_service_tree(monkeypatch):
    from services.digital_products import miniapp

    calls = {"snapshot": 0}

    async def _fake_snapshot(force=False):
        assert force is False
        calls["snapshot"] += 1
        return {"enabled": True, "games": []}

    monkeypatch.setattr(miniapp, "_CATALOG_PAYLOAD_CACHE", {"ts": 0.0, "data": None, "provider_state": {}})
    monkeypatch.setattr(miniapp, "_miniapp_provider_state", lambda: {"za3em_enabled": True})
    monkeypatch.setattr(miniapp, "get_catalog_snapshot", _fake_snapshot)
    monkeypatch.setattr(miniapp, "_markup_percent", lambda: __import__("asyncio").sleep(0, result=0.0))
    monkeypatch.setattr(miniapp, "_grouped_gift_categories", lambda _snapshot: ([], {}))
    monkeypatch.setattr(miniapp, "_grouped_games", lambda _snapshot: ([], {}))
    monkeypatch.setattr(miniapp, "_build_service_tree", lambda *_args: [])

    first = await miniapp._catalog_payload()
    second = await miniapp._catalog_payload()

    assert calls["snapshot"] == 1
    assert first == second


class _DummyRequest:
    def __init__(self, body, headers=None):
        self._body = dict(body)
        self.headers = dict(headers or {})

    async def json(self):
        return dict(self._body)


class _DummyQueryRequest:
    def __init__(self, query):
        self.query = dict(query)

class _DummyMatchRequest:
    def __init__(self, match_info, query=None):
        self.match_info = dict(match_info)
        self.query = dict(query or {})


@pytest.mark.asyncio
async def test_website_family_packages_does_not_load_api_gifts_without_manual_catalog(monkeypatch):
    from services.digital_products import miniapp

    async def _fake_auth(_request, scope):
        assert scope == "digital:catalog"

    async def _fake_catalog():
        return {
            "service_tree": [
                {
                    "key": "chat_apps",
                    "families": [
                        {
                            "family_key": "honey_jar",
                            "name": "Honey Jar",
                            "selection_kind": "general",
                            "variants": [
                                {
                                    "id": "chat-honey",
                                    "name": "Global",
                                    "game_ids": [],
                                    "gift_category_ids": ["chat-honey"],
                                    "offer_mode": "all",
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    async def _fake_gifts(category_id, query, offer_mode):
        raise AssertionError("API gifts must not be shown directly on the website catalog")

    async def _fake_manual(*_args, **_kwargs):
        return None

    monkeypatch.setattr(miniapp, "require_digital_user_auth", _fake_auth)
    monkeypatch.setattr(miniapp, "_catalog_payload", _fake_catalog)
    monkeypatch.setattr(miniapp, "_gift_products", _fake_gifts)
    monkeypatch.setattr(miniapp, "manual_static_family_packages", _fake_manual)
    monkeypatch.setattr(miniapp, "make_digital_quote_token", lambda payload: f"quote:{payload['kind']}:{payload['item_id']}")

    response = await miniapp.website_family_packages(_DummyMatchRequest({"service_key": "chat_apps", "family_key": "honey_jar"}))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["family_name"] == "Honey Jar"
    assert payload["packages"] == []


@pytest.mark.asyncio
async def test_website_game_family_packages_does_not_load_api_games_without_manual_catalog(monkeypatch):
    from services.digital_products import miniapp

    async def _fake_auth(_request, _scope):
        return None

    async def _fake_catalog():
        return {
            "service_tree": [
                {
                    "key": "games",
                    "families": [
                        {
                            "family_key": "pubg",
                            "name": "PUBG",
                            "selection_kind": "general",
                            "variants": [{"id": "pubgm", "name": "Global", "game_ids": ["pubgm"], "gift_category_ids": []}],
                        }
                    ],
                }
            ]
        }

    async def _fake_game_items(game_id):
        raise AssertionError("API game products must be imported into manual catalog first")

    async def _fake_manual(*_args, **_kwargs):
        return None

    monkeypatch.setattr(miniapp, "require_digital_user_auth", _fake_auth)
    monkeypatch.setattr(miniapp, "_catalog_payload", _fake_catalog)
    monkeypatch.setattr(miniapp, "_game_items", _fake_game_items)
    monkeypatch.setattr(miniapp, "manual_static_family_packages", _fake_manual)
    monkeypatch.setattr(miniapp, "make_digital_quote_token", lambda payload: f"quote:{payload['game_id']}:{payload['item_id']}")

    response = await miniapp.website_family_packages(_DummyMatchRequest({"service_key": "games", "family_key": "pubg"}))
    payload = json.loads(response.text)

    assert payload["family_name"] == "PUBG"
    assert payload["packages"] == []


@pytest.mark.asyncio
async def test_website_family_packages_requires_explicit_variant_before_loading(monkeypatch):
    from services.digital_products import miniapp

    async def _fake_auth(_request, _scope):
        return None

    async def _fake_catalog():
        return {
            "service_tree": [
                {
                    "key": "store_cards",
                    "families": [
                        {
                            "family_key": "playstation",
                            "name": "PlayStation",
                            "selection_kind": "region",
                            "variants": [
                                {"id": "ps-us", "name": "US", "variant_kind": "region", "game_ids": [], "gift_category_ids": ["ps-us"]},
                                {"id": "ps-tr", "name": "Turkey", "variant_kind": "region", "game_ids": [], "gift_category_ids": ["ps-tr"]},
                            ],
                        }
                    ],
                }
            ]
        }

    async def _unexpected_gifts(*_args):
        raise AssertionError("products must not load before a variant is selected")

    async def _fake_manual(*_args, **_kwargs):
        return None

    monkeypatch.setattr(miniapp, "require_digital_user_auth", _fake_auth)
    monkeypatch.setattr(miniapp, "_catalog_payload", _fake_catalog)
    monkeypatch.setattr(miniapp, "_gift_products", _unexpected_gifts)
    monkeypatch.setattr(miniapp, "manual_static_family_packages", _fake_manual)

    response = await miniapp.website_family_packages(
        _DummyMatchRequest({"service_key": "store_cards", "family_key": "playstation"})
    )
    payload = json.loads(response.text)

    assert payload["requires_variant_selection"] is False
    assert payload["packages"] == []
    assert payload["variants"] == []


@pytest.mark.asyncio
async def test_website_family_packages_rejects_api_variant_without_manual_catalog(monkeypatch):
    from services.digital_products import miniapp

    loaded = []

    async def _fake_auth(_request, _scope):
        return None

    async def _fake_catalog():
        return {
            "service_tree": [
                {
                    "key": "games",
                    "families": [
                        {
                            "family_key": "pubg",
                            "name": "PUBG",
                            "selection_kind": "region",
                            "variants": [
                                {"id": "pubg-global", "name": "Global", "variant_kind": "region", "game_ids": ["pubg-global"], "gift_category_ids": []},
                                {"id": "pubg-tr", "name": "Turkey", "variant_kind": "region", "game_ids": ["pubg-tr"], "gift_category_ids": []},
                            ],
                        }
                    ],
                }
            ]
        }

    async def _fake_game_items(game_id):
        loaded.append(game_id)
        raise AssertionError("API game products must not load from variant selection")

    async def _fake_manual(*_args, **_kwargs):
        return None

    monkeypatch.setattr(miniapp, "require_digital_user_auth", _fake_auth)
    monkeypatch.setattr(miniapp, "_catalog_payload", _fake_catalog)
    monkeypatch.setattr(miniapp, "_game_items", _fake_game_items)
    monkeypatch.setattr(miniapp, "manual_static_family_packages", _fake_manual)
    monkeypatch.setattr(miniapp, "make_digital_quote_token", lambda payload: f"quote:{payload['game_id']}:{payload['item_id']}")

    with pytest.raises(miniapp.web.HTTPNotFound) as exc_info:
        await miniapp.website_family_packages(
            _DummyMatchRequest({"service_key": "games", "family_key": "pubg"}, {"variant_id": "pubg-tr"})
        )

    assert loaded == []
    assert exc_info.value.text == "variant not found"


@pytest.mark.asyncio
async def test_website_family_packages_rejects_variant_outside_family(monkeypatch):
    from services.digital_products import miniapp

    async def _fake_auth(_request, _scope):
        return None

    async def _fake_catalog():
        return {
            "service_tree": [
                {
                    "key": "games",
                    "families": [
                        {
                            "family_key": "pubg",
                            "name": "PUBG",
                            "variants": [{"id": "pubg-global", "name": "Global", "game_ids": ["pubg-global"], "gift_category_ids": []}],
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(miniapp, "require_digital_user_auth", _fake_auth)
    monkeypatch.setattr(miniapp, "_catalog_payload", _fake_catalog)
    monkeypatch.setattr(miniapp, "manual_static_family_packages", lambda *_args, **_kwargs: __import__("asyncio").sleep(0, result=None))

    with pytest.raises(miniapp.web.HTTPNotFound) as exc_info:
        await miniapp.website_family_packages(
            _DummyMatchRequest({"service_key": "games", "family_key": "pubg"}, {"variant_id": "pubg-turkey"})
        )
    assert exc_info.value.text == "variant not found"


@pytest.mark.asyncio
async def test_website_family_packages_serves_manual_admin_catalog(monkeypatch):
    from services.digital_products import miniapp

    async def _fake_auth(_request, scope):
        assert scope == "digital:catalog"

    async def _fake_packages(family_id, *, variant_id):
        assert family_id == "family-1"
        assert variant_id == "variant-1"
        return {
            "ok": True,
            "packages": [{"kind": "manual", "id": "product-1", "name": "100 UAH", "price_label": "$3.50"}],
        }

    async def _fake_quote(endpoint_id):
        assert endpoint_id == "product-1"
        return {"kind": "manual", "item_id": endpoint_id, "sale_price": 3.5}

    monkeypatch.setattr(miniapp, "require_digital_user_auth", _fake_auth)
    monkeypatch.setattr(miniapp, "manual_family_packages", _fake_packages)
    monkeypatch.setattr(miniapp, "fresh_manual_quote_payload", _fake_quote)
    monkeypatch.setattr(miniapp, "make_digital_quote_token", lambda payload: f"quote:{payload['item_id']}")

    response = await miniapp.website_family_packages(
        _DummyMatchRequest(
            {"service_key": "website_manual", "family_key": "family-1"},
            {"variant_id": "variant-1"},
        )
    )
    payload = json.loads(response.text)

    assert payload["packages"][0]["quote_token"] == "quote:product-1"


@pytest.mark.asyncio
async def test_website_family_packages_serves_static_manual_family_without_api_family(monkeypatch):
    from services.digital_products import miniapp

    async def _fake_auth(_request, scope):
        assert scope == "digital:catalog"

    async def _fake_catalog():
        return {"service_tree": [{"key": "games", "families": []}]}

    async def _fake_manual(service_key, family_key, *, variant_id="", variant_name=""):
        assert (service_key, family_key) == ("games", "pubg")
        assert variant_id == ""
        assert variant_name == ""
        return {
            "ok": True,
            "service_key": "games",
            "family_key": "pubg",
            "family_name": "PUBG",
            "selection_kind": "general",
            "requires_variant_selection": False,
            "variants": [{"id": "manual:variant-1", "name": "Global"}],
            "selected_variant_id": "manual:variant-1",
            "selected_variant_name": "Global",
            "packages": [{"kind": "manual", "id": "product-1", "name": "325 UC", "price_usd": 6.6}],
        }

    async def _fake_quote(endpoint_id):
        assert endpoint_id == "product-1"
        return {"kind": "manual", "item_id": endpoint_id, "sale_price": 6.6}

    monkeypatch.setattr(miniapp, "require_digital_user_auth", _fake_auth)
    monkeypatch.setattr(miniapp, "_catalog_payload", _fake_catalog)
    monkeypatch.setattr(miniapp, "manual_static_family_packages", _fake_manual)
    monkeypatch.setattr(miniapp, "fresh_manual_quote_payload", _fake_quote)
    monkeypatch.setattr(miniapp, "make_digital_quote_token", lambda payload: f"quote:{payload['item_id']}")

    response = await miniapp.website_family_packages(_DummyMatchRequest({"service_key": "games", "family_key": "pubg"}))
    payload = json.loads(response.text)

    assert payload["family_name"] == "PUBG"
    assert payload["packages"][0]["quote_token"] == "quote:product-1"


@pytest.mark.asyncio
async def test_website_family_packages_serves_manual_only_for_api_backed_family(monkeypatch):
    from services.digital_products import miniapp

    async def _fake_auth(_request, _scope):
        return None

    async def _fake_catalog():
        return {
            "service_tree": [
                {
                    "key": "games",
                    "families": [
                        {
                            "family_key": "pubg",
                            "name": "PUBG",
                            "selection_kind": "general",
                            "variants": [{"id": "pubgm", "name": "Global", "game_ids": ["pubgm"], "gift_category_ids": []}],
                        }
                    ],
                }
            ]
        }

    async def _fake_manual(_service_key, _family_key, *, variant_id="", variant_name=""):
        if variant_id:
            return None
        if variant_name and variant_name != "Global":
            return None
        return {
            "ok": True,
            "variants": [{"id": "manual:variant-1", "name": "Global"}],
            "packages": [{"kind": "manual", "id": "product-1", "name": "325 UC manual", "price_usd": 6.6}],
        }

    async def _fake_quote(endpoint_id):
        return {"kind": "manual", "item_id": endpoint_id, "sale_price": 6.6}

    monkeypatch.setattr(miniapp, "require_digital_user_auth", _fake_auth)
    monkeypatch.setattr(miniapp, "_catalog_payload", _fake_catalog)
    monkeypatch.setattr(miniapp, "manual_static_family_packages", _fake_manual)
    monkeypatch.setattr(miniapp, "fresh_manual_quote_payload", _fake_quote)
    monkeypatch.setattr(miniapp, "make_digital_quote_token", lambda payload: f"quote:{payload['item_id']}")

    response = await miniapp.website_family_packages(_DummyMatchRequest({"service_key": "games", "family_key": "pubg"}))
    payload = json.loads(response.text)

    assert [row["name"] for row in payload["variants"]] == ["Global"]
    assert {row["name"] for row in payload["packages"]} == {"325 UC manual"}


@pytest.mark.asyncio
async def test_import_api_family_materializes_manual_products_without_api_execution(monkeypatch):
    from services.digital_products import miniapp

    calls = []

    async def _fake_catalog():
        return {
            "service_tree": [
                {
                    "key": "games",
                    "families": [
                        {
                            "family_key": "pubg",
                            "name": "PUBG",
                            "variants": [{"id": "pubgm", "name": "Global", "game_ids": ["pubgm"], "gift_category_ids": []}],
                        }
                    ],
                }
            ]
        }

    async def _fake_game_items(game_id):
        assert game_id == "pubgm"
        return {
            "game_name": "PUBG Mobile",
            "game_id": game_id,
            "items": [
                {
                    "kind": "game",
                    "id": "325",
                    "game_id": game_id,
                    "name": "325 UC",
                    "price_usd": 6.6,
                    "requires_server": True,
                    "best_provider_code": "g2bulk",
                    "fulfillment_mode": "auto_topup",
                }
            ],
        }

    async def _fake_upsert(owner_id, **kwargs):
        calls.append((owner_id, kwargs))
        return {"_id": "product-1", "name": kwargs["product_name"]}, True

    monkeypatch.setattr(miniapp, "_catalog_payload", _fake_catalog)
    monkeypatch.setattr(miniapp, "_game_items", _fake_game_items)
    monkeypatch.setattr(miniapp, "upsert_static_manual_product", _fake_upsert)

    result = await miniapp._import_api_family_to_manual(77, service_key="games", family_key="pubg")

    assert result["created"] == 1
    assert calls[0][0] == 77
    assert calls[0][1]["product_name"] == "325 UC"
    assert calls[0][1]["source_key"] == "game:pubgm:325"
    assert calls[0][1]["execution_mode"] == "manual"
    assert calls[0][1]["api_source"]["game_id"] == "pubgm"
    assert calls[0][1]["input_fields"][1]["id"] == "server_id"


@pytest.mark.asyncio
async def test_game_items_uses_cached_catalog_topups(monkeypatch):
    from services.digital_products import miniapp

    async def _fake_snapshot(force=False):
        assert force is False
        return {"games": [{"id": "pubgm", "name": "PUBG Mobile"}]}

    async def _fake_topups(game_id, force=False):
        assert game_id == "pubgm"
        assert force is False
        return []

    monkeypatch.setattr(miniapp, "get_catalog_snapshot", _fake_snapshot)
    monkeypatch.setattr(miniapp, "get_game_topups", _fake_topups)
    monkeypatch.setattr(miniapp, "_markup_percent", lambda: __import__("asyncio").sleep(0, result=0.0))

    payload = await miniapp._game_items("pubgm")

    assert payload["items"] == []


@pytest.mark.asyncio
async def test_esim_offers_recommends_without_route_signature_mismatch(monkeypatch):
    from services.digital_products import miniapp

    async def _fake_offers(country, *, days, usage_key):
        assert (country, days, usage_key) == ("Turkey", 7, "low")
        return [
            {
                "offer_type": "single_country",
                "coverage_full": True,
                "price_usd": 4.0,
                "_cost_price_usd": 4.0,
                "summary": "Turkey 1GB",
            },
            {
                "offer_type": "single_region",
                "coverage_full": True,
                "price_usd": 4.5,
                "_cost_price_usd": 4.5,
                "summary": "Regional 1GB",
            },
        ]

    monkeypatch.setattr(miniapp, "build_single_country_offers_live", _fake_offers)

    response = await miniapp.esim_offers(_DummyQueryRequest({"country": "Turkey", "days": "7", "usage": "low"}))

    assert response.status == 200
    assert '"recommended_index": 1' in response.text


@pytest.mark.asyncio
async def test_create_selection_uses_server_gift_quote(monkeypatch):
    from services.digital_products import miniapp

    stored = {}

    def _fake_verify(init_data):
        assert init_data == "signed"
        return {"user_id": 42}

    async def _fake_quote(category_id, product_id, quantity):
        assert (category_id, product_id, quantity) == ("cat1", "prod1", 3)
        return 7.5

    async def _fake_create_selection(user_id, payload):
        stored["user_id"] = user_id
        stored["payload"] = dict(payload)
        return "tok1"

    monkeypatch.setattr(miniapp, "_verify_init_data", _fake_verify)
    monkeypatch.setattr(miniapp, "_server_quote_gift_selection", _fake_quote)
    monkeypatch.setattr(miniapp, "_create_selection", _fake_create_selection)

    request = _DummyRequest(
        {
            "kind": "gift",
            "category_id": "cat1",
            "product_id": "prod1",
            "quantity": 3,
            "quoted_price_usd": 0.01,
        },
        headers={"X-Telegram-Init-Data": "signed"},
    )

    response = await miniapp.create_selection(request)

    assert response.status == 200
    assert stored["user_id"] == 42
    assert stored["payload"]["quoted_price_usd"] == 7.5


@pytest.mark.asyncio
async def test_create_selection_preserves_gift_quantity_and_extra_params(monkeypatch):
    from services.digital_products import miniapp

    stored = {}

    def _fake_verify(_init_data):
        return {"user_id": 42}

    async def _fake_quote(category_id, product_id, quantity):
        assert (category_id, product_id, quantity) == ("chat", "tada", 1500)
        return 1.94

    async def _fake_create_selection(user_id, payload):
        stored["user_id"] = user_id
        stored["payload"] = dict(payload)
        return "tok-chat"

    monkeypatch.setattr(miniapp, "_verify_init_data", _fake_verify)
    monkeypatch.setattr(miniapp, "_server_quote_gift_selection", _fake_quote)
    monkeypatch.setattr(miniapp, "_create_selection", _fake_create_selection)

    request = _DummyRequest(
        {
            "kind": "gift",
            "category_id": "chat",
            "product_id": "tada",
            "quantity": 1500,
            "extra_params": {"player_id": "65554686865468"},
            "quoted_price_usd": 0.01,
        }
    )

    response = await miniapp.create_selection(request)

    assert response.status == 200
    assert stored["payload"] == {
        "kind": "gift",
        "category_id": "chat",
        "product_id": "tada",
        "quantity": 1500,
        "extra_params": {"player_id": "65554686865468"},
        "quoted_price_usd": 1.94,
    }


@pytest.mark.asyncio
async def test_create_selection_uses_server_game_quote(monkeypatch):
    from services.digital_products import miniapp

    stored = {}

    def _fake_verify(_init_data):
        return {"user_id": 91}

    async def _fake_quote(game_id, item_id, group_key):
        assert (game_id, item_id, group_key) == ("pubgm", "8100", "topup")
        return 82.0

    async def _fake_create_selection(user_id, payload):
        stored["user_id"] = user_id
        stored["payload"] = dict(payload)
        return "tok2"

    monkeypatch.setattr(miniapp, "_verify_init_data", _fake_verify)
    monkeypatch.setattr(miniapp, "_server_quote_game_selection", _fake_quote)
    monkeypatch.setattr(miniapp, "_create_selection", _fake_create_selection)

    request = _DummyRequest(
        {
            "kind": "game",
            "game_id": "pubgm",
            "item_id": "8100",
            "group_key": "topup",
            "player_id": "12345",
            "quoted_price_usd": 1,
        },
        headers={"X-Telegram-Init-Data": "signed"},
    )

    response = await miniapp.create_selection(request)

    assert response.status == 200
    assert stored["user_id"] == 91
    assert stored["payload"]["quoted_price_usd"] == 82.0
    assert stored["payload"]["player_id"] == "12345"


@pytest.mark.asyncio
async def test_create_selection_routes_manual_game_addon_payload(monkeypatch):
    from services.digital_products import miniapp

    stored = {}

    def _fake_verify(_init_data):
        return {"user_id": 91}

    async def _fake_quote(game_id, item_id, group_key):
        assert (game_id, item_id, group_key) == ("pubgm_addons", "prime_1m", "passes")
        return 1.0

    async def _fake_create_selection(user_id, payload):
        stored["user_id"] = user_id
        stored["payload"] = dict(payload)
        return "tok-addon"

    monkeypatch.setattr(miniapp, "_verify_init_data", _fake_verify)
    monkeypatch.setattr(miniapp, "_server_quote_game_selection", _fake_quote)
    monkeypatch.setattr(miniapp, "_create_selection", _fake_create_selection)

    request = _DummyRequest(
        {
            "kind": "game",
            "game_id": "pubgm_addons",
            "item_id": "prime_1m",
            "group_key": "passes",
            "player_id": "998877",
            "server_id": "ignored-by-ui",
            "quoted_price_usd": 0.5,
        }
    )

    response = await miniapp.create_selection(request)

    assert response.status == 200
    assert stored["payload"]["quoted_price_usd"] == 1.0
    assert stored["payload"]["group_key"] == "passes"
    assert stored["payload"]["player_id"] == "998877"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected_payload"),
    [
        ("esim", {"kind": "esim"}),
        ("simtopup", {"kind": "simtopup", "section": "data"}),
        ("numbers_services", {"kind": "numbers_services", "service_key": "whatsapp", "service_label": "WhatsApp"}),
    ],
)
async def test_create_selection_supports_direct_digital_flows(monkeypatch, kind, expected_payload):
    from services.digital_products import miniapp

    stored = {}

    def _fake_verify(_init_data):
        return {"user_id": 7}

    async def _fake_create_selection(user_id, payload):
        stored["user_id"] = user_id
        stored["payload"] = dict(payload)
        return "tok-direct"

    monkeypatch.setattr(miniapp, "_verify_init_data", _fake_verify)
    monkeypatch.setattr(miniapp, "_create_selection", _fake_create_selection)

    body = {"kind": kind}
    if kind == "simtopup":
        body["section"] = "data"
    if kind == "numbers_services":
        body["service_key"] = "whatsapp"
        body["service_label"] = "WhatsApp"
    request = _DummyRequest(body, headers={"X-Telegram-Init-Data": "signed"})

    response = await miniapp.create_selection(request)

    assert response.status == 200
    assert stored["user_id"] == 7
    assert stored["payload"] == expected_payload


@pytest.mark.asyncio
async def test_create_selection_allows_missing_init_data_for_webapp_send_data(monkeypatch):
    from services.digital_products import miniapp

    stored = {}

    async def _fake_create_selection(user_id, payload):
        stored["user_id"] = user_id
        stored["payload"] = dict(payload)
        return "tok-no-init"

    monkeypatch.setattr(miniapp, "_create_selection", _fake_create_selection)

    request = _DummyRequest({"kind": "numbers_services", "service_key": "telegram"})
    response = await miniapp.create_selection(request)

    assert response.status == 200
    assert stored["user_id"] is None
    assert stored["payload"] == {"kind": "numbers_services", "service_key": "telegram"}
