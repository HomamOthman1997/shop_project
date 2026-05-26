import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())


class _DummyMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=100)
        self.message_id = 200
        self.edits: list[str] = []

    async def edit_text(self, text, **kwargs):
        self.edits.append(text)


class _DummyCallback:
    def __init__(self, data: str, user_id: int):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = _DummyMessage()
        self.answers: list[dict] = []

    async def answer(self, text=None, show_alert=None, **kwargs):
        self.answers.append({"text": text, "show_alert": show_alert, **kwargs})


class _DummyState:
    async def set_state(self, value):
        self.value = value


@pytest.mark.asyncio
async def test_legacy_cancel_buy_rejects_non_owner(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict[str, bool] = {}
    order_id = "507f1f77bcf86cd799439222"

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_get_reservation_by_message(_chat_id, _message_id):
        return {"status": "reserved", "order_id": order_id, "user_id": 111}

    async def _fake_get_order(_order_id):
        return {
            "_id": order_id,
            "user_id": 111,
            "reseller_id": 111,
            "provider": "nonvoip",
            "provider_order_id": "prov-1",
            "selling_price": 1.0,
            "base_price": 0.5,
        }

    class _FinancialManager:
        @classmethod
        async def refund_core_purchase(cls, *args, **kwargs):
            calls["refund"] = True
            return True, "OK"

    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb.reservations_repo, "get_reservation_by_message", _fake_get_reservation_by_message)
    monkeypatch.setattr(hb, "get_order", _fake_get_order)
    monkeypatch.setattr(hb, "FinancialManager", _FinancialManager)

    callback = _DummyCallback("buy:cancel", user_id=222)
    await hb.cancel_buy(callback, _DummyState())

    assert callback.answers[-1]["show_alert"] is True
    assert "refund" not in calls


@pytest.mark.asyncio
async def test_legacy_resend_uses_user_scoped_order_loader(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict[str, object] = {}
    order_id = "507f1f77bcf86cd799439333"

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_load_user_order(raw_id, user_id):
        calls["load"] = (raw_id, user_id)
        return None, None

    class _Provider:
        async def resend(self, _provider_order_id):
            calls["provider_resend"] = True
            return True

    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_load_user_order", _fake_load_user_order)
    monkeypatch.setitem(hb.PROVIDERS, "nonvoip", _Provider())

    callback = _DummyCallback(f"buy:resend:{order_id}", user_id=222)
    await hb.resend_code(callback, _DummyState())

    assert calls["load"] == (order_id, 222)
    assert callback.answers[-1]["show_alert"] is True
    assert "provider_resend" not in calls
