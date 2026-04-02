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
async def test_recharge_proof_text_uses_current_user_language(monkeypatch):
    message = _FakeMessage("not a screenshot")
    state = _FakeState()

    async def _fake_user(_user_id):
        return {"language": "ar"}

    monkeypatch.setattr(main_menu, "get_user", _fake_user)

    await main_menu.receive_recharge_proof_text(message, state)

    assert message.answers
    assert message.answers[-1]["text"] == t("ar", "send_payment_proof_screenshot_now")
