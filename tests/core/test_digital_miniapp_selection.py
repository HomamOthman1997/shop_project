import os
import sys

import pytest

sys.path.insert(0, os.getcwd())


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
        }
    )

    response = await miniapp.create_selection(request)

    assert response.status == 200
    assert stored["user_id"] == 91
    assert stored["payload"]["quoted_price_usd"] == 82.0
    assert stored["payload"]["player_id"] == "12345"
