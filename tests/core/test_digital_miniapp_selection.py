import os
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


class _DummyRequest:
    def __init__(self, body, headers=None):
        self._body = dict(body)
        self.headers = dict(headers or {})

    async def json(self):
        return dict(self._body)


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
