import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

import handlers.verify_reseller as vr


class _FakeState:
    def __init__(self):
        self.data = {}
        self.state = None

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, value):
        self.state = value

    async def get_data(self):
        return dict(self.data)


class _FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.from_user = SimpleNamespace(id=123)
        self.chat = SimpleNamespace(id=456)
        self.bot = SimpleNamespace()


@pytest.mark.asyncio
async def test_save_token_accepts_valid_token_when_no_pending_or_registered(monkeypatch):
    state = _FakeState()
    message = _FakeMessage("8791141203:AAE3lSGuFNNtWvSjL5mgk9VRNAhxIknW1x0")
    prompts = []

    class _TempSession:
        async def close(self):
            return None

    class _TempBot:
        def __init__(self, token):
            self.token = token
            self.session = _TempSession()

        async def get_me(self):
            return SimpleNamespace(id=8791141203, username="testsdfsdfsfsbot", first_name="test 2")

    async def _fake_user(_uid):
        return {"language": "ar"}

    async def _fake_delete(*_args, **_kwargs):
        return None

    async def _fake_prompt(**kwargs):
        prompts.append(kwargs)
        return None

    async def _fake_intro_delete(*_args, **_kwargs):
        return None

    async def _fake_show_channel(*_args, **_kwargs):
        return None

    async def _fake_registered(_bot_id):
        return False

    async def _fake_pending(_bot_id):
        return False

    monkeypatch.setattr(vr, "Bot", _TempBot)
    monkeypatch.setattr(vr, "get_user", _fake_user)
    monkeypatch.setattr(vr, "_safe_delete_user_message", _fake_delete)
    monkeypatch.setattr(vr, "_set_or_edit_prompt", _fake_prompt)
    monkeypatch.setattr(vr, "_delete_intro_message", _fake_intro_delete)
    monkeypatch.setattr(vr, "_show_channel_picker_prompt", _fake_show_channel)
    monkeypatch.setattr(vr, "_is_bot_id_already_registered", _fake_registered)
    monkeypatch.setattr(vr, "_has_pending_bot_request_for_bot_id", _fake_pending)

    await vr.save_token(message, state)

    assert state.data["bot_id"] == 8791141203
    assert state.data["bot_username"] == "testsdfsdfsfsbot"
    assert state.state == vr.VerifyReseller.waiting_for_channel
    assert prompts


@pytest.mark.asyncio
async def test_save_token_explains_registered_bot_and_stays_on_token_step(monkeypatch):
    state = _FakeState()
    message = _FakeMessage("8791141203:AAE3lSGuFNNtWvSjL5mgk9VRNAhxIknW1x0")
    prompts = []

    class _TempSession:
        async def close(self):
            return None

    class _TempBot:
        def __init__(self, token):
            self.token = token
            self.session = _TempSession()

        async def get_me(self):
            return SimpleNamespace(id=8791141203, username="already_here_bot", first_name="Already Here")

    async def _fake_user(_uid):
        return {"language": "en"}

    async def _fake_delete(*_args, **_kwargs):
        return None

    async def _fake_prompt(**kwargs):
        prompts.append(kwargs)
        return None

    async def _fake_registered(_bot_id):
        return True

    async def _fake_pending(_bot_id):
        return False

    monkeypatch.setattr(vr, "Bot", _TempBot)
    monkeypatch.setattr(vr, "get_user", _fake_user)
    monkeypatch.setattr(vr, "_safe_delete_user_message", _fake_delete)
    monkeypatch.setattr(vr, "_set_or_edit_prompt", _fake_prompt)
    monkeypatch.setattr(vr, "_is_bot_id_already_registered", _fake_registered)
    monkeypatch.setattr(vr, "_has_pending_bot_request_for_bot_id", _fake_pending)

    await vr.save_token(message, state)

    assert state.state is None
    assert prompts
    text = prompts[-1]["text"]
    assert "Step 1/6 - Bot Token" in text
    assert "token you sent belongs to a bot" in text
    buttons = prompts[-1]["reply_markup"].inline_keyboard
    assert buttons[0][0].text == "🔁 I Have a New Token"
