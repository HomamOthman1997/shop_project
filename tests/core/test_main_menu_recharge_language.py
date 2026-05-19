import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

import handlers.main_menu as main_menu
from utils.translations import t


class _FakeState:
    async def get_data(self):
        return {"recharge_lang": "en"}

    async def clear(self):
        return None

    async def set_state(self, _state):
        return None


class _FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.answers: list[dict] = []
        self.from_user = type("User", (), {"id": 123})()

    async def answer(self, text, **kwargs):
        self.answers.append({"text": str(text), "kwargs": kwargs})
        return None


@pytest.mark.asyncio
async def test_ask_recharge_amount_uses_method_rate_and_arabic_prompt(monkeypatch):
    class _MethodState:
        def __init__(self):
            self.data = {
                "recharge_lang": "ar",
                "recharge_methods": [
                    {
                        "code": "shamcash_syp",
                        "title": "ShamCash (SYP)",
                        "currency": "SYP",
                        "per_credit": 14500.0,
                        "target": "4837013dbf3a68db82694dde3bc426d9",
                        "instructions": "حوّل المبلغ ثم أرسل إثبات الدفع.",
                    }
                ],
                "recharge_method_map": {"ShamCash (SYP)": "shamcash_syp"},
            }
            self.state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, state):
            self.state = state

        async def clear(self):
            return None

    async def _fake_user(_user_id):
        return {"language": "ar"}

    async def _unexpected_rate():
        raise AssertionError("selected method per_credit should be used")

    message = _FakeMessage("ShamCash (SYP)")
    state = _MethodState()
    monkeypatch.setattr(main_menu, "get_user", _fake_user)
    monkeypatch.setattr(main_menu, "get_owner_exchange_rate", _unexpected_rate)

    await main_menu.ask_recharge_amount(message, state)

    assert state.state == main_menu.RechargeFlow.waiting_amount
    assert "1 كريدت = 14500.0000 SYP" in message.answers[0]["text"]
    assert "1 credit" not in message.answers[0]["text"]
    assert message.answers[-1]["text"] == t("ar", "send_amount_now")


@pytest.mark.asyncio
async def test_recharge_proof_text_uses_current_user_language(monkeypatch):
    message = _FakeMessage("not a screenshot")
    state = _FakeState()

    async def _fake_user(_user_id):
        return {"language": "ar"}

    monkeypatch.setattr(main_menu, "get_user", _fake_user)

    await main_menu.receive_recharge_proof_text(message, state)

    assert message.answers
    assert message.answers[-1]["text"] == t("ar", "send_payment_proof_screenshot_now")


@pytest.mark.asyncio
async def test_receive_recharge_amount_uses_current_user_language(monkeypatch):
    class _AmountState:
        async def get_data(self):
            return {
                "recharge_lang": "en",
                "recharge_method": {"currency": "USD"},
            }

        async def set_state(self, _state):
            return None

        async def update_data(self, **_kwargs):
            return None

    message = _FakeMessage("700")
    state = _AmountState()

    async def _fake_user(_user_id):
        return {"language": "ar"}

    monkeypatch.setattr(main_menu, "get_user", _fake_user)

    await main_menu.receive_recharge_amount(message, state)

    assert message.answers
    assert message.answers[-1]["text"] == t("ar", "send_payment_proof_now")


@pytest.mark.asyncio
async def test_receive_recharge_amount_uses_selected_method_rate(monkeypatch):
    captured = {}

    class _AmountState:
        async def get_data(self):
            return {
                "recharge_lang": "ar",
                "recharge_method": {"currency": "SYP", "per_credit": 14500.0},
            }

        async def set_state(self, state):
            captured["state"] = state

        async def update_data(self, **kwargs):
            captured.update(kwargs)

    message = _FakeMessage("29000")
    state = _AmountState()

    async def _fake_user(_user_id):
        return {"language": "ar"}

    async def _unexpected_rate():
        raise AssertionError("selected method per_credit should be used")

    monkeypatch.setattr(main_menu, "get_user", _fake_user)
    monkeypatch.setattr(main_menu, "get_owner_exchange_rate", _unexpected_rate)

    await main_menu.receive_recharge_amount(message, state)

    assert captured["state"] == main_menu.RechargeFlow.waiting_proof
    assert captured["recharge_per_credit"] == 14500.0
    assert captured["recharge_credits"] == 2.0


@pytest.mark.asyncio
async def test_receive_recharge_proof_stores_effective_per_credit(monkeypatch):
    class _ProofState:
        async def get_data(self):
            return {
                "recharge_paid_amount": 4000.0,
                "recharge_credits": 1.0,
                "recharge_per_credit": 4000.0,
                "recharge_method": {"code": "owner_shamcash_syp", "title": "ShamCash", "currency": "SYP"},
                "recharge_scope_id": 55,
                "recharge_is_main_bot": True,
            }

        async def clear(self):
            return None

    class _Bot:
        async def get_me(self):
            return type("Me", (), {"id": 8147766487})()

    class _Photo:
        file_id = "photo123"

    class _ProofMessage:
        def __init__(self):
            self.photo = [_Photo()]
            self.from_user = type("User", (), {"id": 123})()
            self.bot = _Bot()
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append({"text": str(text), "kwargs": kwargs})
            return None

    captured = {}
    message = _ProofMessage()
    state = _ProofState()

    async def _fake_user(_user_id):
        return {"language": "ar"}

    async def _fake_create_recharge_request(**kwargs):
        captured["details"] = kwargs["details"]
        return {"_id": "req1"}

    async def _fake_notify(*_args, **_kwargs):
        return False, "none", None, None, None

    async def _fake_return_main_menu(*_args, **_kwargs):
        return None

    async def _fake_update_one(*_args, **_kwargs):
        return None

    async def _fake_current_bot_id(_bot):
        return 8147766487

    monkeypatch.setattr(main_menu, "get_user", _fake_user)
    monkeypatch.setattr(main_menu, "create_recharge_request", _fake_create_recharge_request)
    monkeypatch.setattr(main_menu, "_notify_recharge_request_to_review_queue", _fake_notify)
    monkeypatch.setattr(main_menu, "_return_main_menu", _fake_return_main_menu)
    monkeypatch.setattr(main_menu, "_current_bot_id", _fake_current_bot_id)
    monkeypatch.setattr(
        main_menu,
        "db",
        type("DB", (), {"recharge_requests": type("Col", (), {"update_one": staticmethod(_fake_update_one)})()})(),
    )

    await main_menu.receive_recharge_proof(message, state)

    assert captured["details"]["paid_currency"] == "SYP"
    assert captured["details"]["per_credit"] == 4000.0
    assert captured["details"]["source_bot_id"] == 8147766487
