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
