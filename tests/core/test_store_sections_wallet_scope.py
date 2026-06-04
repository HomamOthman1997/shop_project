import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())


class _DummyCallback:
    def __init__(self):
        self.from_user = SimpleNamespace(id=12345)
        self.bot = SimpleNamespace(id=67890)
        self.message = None
        self.answers: list[dict] = []

    async def answer(self, text=None, show_alert=None, **kwargs):
        self.answers.append({"text": text, "show_alert": show_alert, **kwargs})


class _DummyState:
    async def get_data(self):
        return {
            "esim_recommended_offer": {
                "package_code": "TR_5GB_30D",
                "price_usd": 2.88,
                "_cost_price_usd": 2.30,
            },
            "esim_selected_days": 30,
        }


class _DummyMessage:
    def __init__(self):
        self.from_user = SimpleNamespace(id=999999)
        self.bot = SimpleNamespace(get_me=lambda: None)
        self.answers: list[dict] = []

        async def _get_me():
            return SimpleNamespace(id=67890)

        self.bot.get_me = _get_me

    async def answer(self, text=None, reply_markup=None, **kwargs):
        self.answers.append({"text": text, "reply_markup": reply_markup, **kwargs})


@pytest.mark.asyncio
async def test_esim_purchase_uses_platform_user_wallet_scope(monkeypatch):
    import handlers.store_sections as store_sections

    captured: dict[str, object] = {}

    async def _true(_bot_id):
        return True

    async def _false(_bot_id):
        return False

    async def _fail_store_owner_scope(_bot_id):
        raise AssertionError("platform eSIM purchase must not use store-owner wallet scope")

    async def _core_charge(**kwargs):
        captured.update(kwargs)
        return None, "stop-after-charge-scope-check"

    monkeypatch.setattr(store_sections, "get_user", lambda _user_id: __import__("asyncio").sleep(0, result={"language": "en"}))
    monkeypatch.setattr(store_sections, "guard_core_service_callback", lambda *_args, **_kwargs: __import__("asyncio").sleep(0, result=True))
    monkeypatch.setattr(store_sections, "is_digital_products_bot", _true)
    monkeypatch.setattr(store_sections, "is_main_bot", _false)
    monkeypatch.setattr(store_sections, "get_store_owner_scope_for_bot", _fail_store_owner_scope)
    monkeypatch.setattr(store_sections.settings, "esim_access_code", "configured")
    monkeypatch.setattr(store_sections.settings, "esim_access_secret_key", "configured")
    monkeypatch.setattr(store_sections, "_core_charge", _core_charge)

    callback = _DummyCallback()
    await store_sections.esim_buy_recommended_offer(callback, _DummyState())

    assert captured["user_id"] == 12345
    assert captured["reseller_id"] == 12345
    assert callback.answers[-1]["text"] == "stop-after-charge-scope-check"


@pytest.mark.asyncio
async def test_core_charge_falls_back_to_platform_wallet_when_old_scope_is_empty(monkeypatch):
    import handlers.store_sections as store_sections

    calls: dict[str, object] = {}

    async def _balance(user_id, reseller_id):
        calls.setdefault("balances", []).append((user_id, reseller_id))
        return 0.0 if reseller_id == 999 else 100.0

    async def _create_order(**kwargs):
        calls["order"] = kwargs
        return {"_id": "order-1", **kwargs}

    async def _process(**kwargs):
        calls["process"] = kwargs
        return True, "Success"

    async def _update_status(order_id, status):
        calls.setdefault("statuses", []).append((order_id, status))

    async def _update_details(order_id, payload):
        calls["details"] = (order_id, payload)

    monkeypatch.setattr(store_sections, "get_user_wallet_balance", _balance)
    monkeypatch.setattr(store_sections, "create_order_v3", _create_order)
    monkeypatch.setattr(store_sections.FinancialManager, "process_core_purchase", _process)
    monkeypatch.setattr(store_sections, "update_order_status", _update_status)
    monkeypatch.setattr(store_sections, "update_order_details", _update_details)

    order, err = await store_sections._core_charge(
        user_id=123,
        reseller_id=999,
        service_ref_id="g2bulk:topup:pubg",
        sale_price=21.25,
        cost_price=21.25,
    )

    assert err is None
    assert order["_id"] == "order-1"
    assert calls["order"]["reseller_id"] == 123
    assert calls["process"]["reseller_id"] == 123
    assert calls["details"][1]["wallet_scope_fallback_from"] == 999
    assert calls["details"][1]["wallet_scope_fallback_to"] == 123


@pytest.mark.asyncio
async def test_game_prefill_purchase_uses_callback_user_not_bot_message_user(monkeypatch):
    import handlers.store_sections as store_sections

    calls: dict[str, object] = {}

    async def _get_user(user_id):
        calls["get_user"] = user_id
        return {"language": "en"}

    async def _resolve_user_reseller(user_id, bot_id):
        calls["resolve"] = (user_id, bot_id)
        return user_id

    async def _core_charge(**kwargs):
        calls["charge"] = kwargs
        return {"_id": "order-1", "user_id": kwargs["user_id"], "reseller_id": kwargs["reseller_id"]}, None

    async def _details(order_id, payload):
        calls["details"] = (order_id, payload)

    async def _notify(**kwargs):
        calls["notify"] = kwargs
        return True

    monkeypatch.setattr(store_sections, "get_user", _get_user)
    monkeypatch.setattr(store_sections, "_resolve_user_reseller", _resolve_user_reseller)
    monkeypatch.setattr(store_sections, "_core_charge", _core_charge)
    monkeypatch.setattr(store_sections, "digital_provider_enabled", lambda _provider: True)
    monkeypatch.setattr(store_sections, "get_catalog_snapshot", lambda force=False: __import__("asyncio").sleep(0, result={}))
    monkeypatch.setattr(store_sections, "_find_game_name", lambda _game_id, _snapshot: "PUBG Mobile")
    monkeypatch.setattr(store_sections, "update_order_details", _details)
    monkeypatch.setattr(store_sections, "_notify_owner_manual_topup", _notify)

    message = _DummyMessage()
    await store_sections._execute_g2bulk_game_purchase(
        message,
        {
            "game_id": "pubg",
            "item_id": "1800",
            "name": "1800 UC",
            "player_id": "51293484551",
            "provider_offers": [{"provider": "g2bulk", "ref_id": "1800", "price": 21.25, "available": True}],
            "sale_price": 21.25,
        },
        server_id="",
        customer_user_id=7731488539,
    )

    assert calls["get_user"] == 7731488539
    assert calls["resolve"] == (7731488539, 67890)
    assert calls["charge"]["user_id"] == 7731488539
    assert calls["charge"]["reseller_id"] == 7731488539
    assert message.answers[-1]["text"].startswith("✅ Order Created Successfully!")
