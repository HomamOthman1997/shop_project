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


@pytest.mark.asyncio
async def test_receive_channel_keeps_manual_channel_in_channel_step(monkeypatch):
    state = _FakeState()
    message = _FakeMessage("@my_channel")
    handled = {}

    async def _fake_user(_uid):
        return {"language": "en"}

    async def _fake_delete(*_args, **_kwargs):
        handled["deleted"] = True

    async def _fake_handle_channel(message_arg, state_arg, lang, channel_norm):
        handled["message"] = message_arg
        handled["state"] = state_arg
        handled["lang"] = lang
        handled["channel_norm"] = channel_norm

    async def _fail_save_token(*_args, **_kwargs):
        raise AssertionError("manual channel was routed as a bot token")

    monkeypatch.setattr(vr, "get_user", _fake_user)
    monkeypatch.setattr(vr, "_safe_delete_user_message", _fake_delete)
    monkeypatch.setattr(vr, "_handle_channel_value", _fake_handle_channel)
    monkeypatch.setattr(vr, "save_token", _fail_save_token)

    await vr.receive_channel(message, state)

    assert handled["deleted"] is True
    assert handled["channel_norm"] == "@my_channel"
    assert state.state is None


@pytest.mark.asyncio
async def test_receive_channel_shared_uses_chat_id_as_trusted_channel(monkeypatch):
    state = _FakeState()
    message = _FakeMessage("")
    message.chat_shared = SimpleNamespace(request_id=vr.CHANNEL_PICKER_REQUEST_ID, chat_id=-1001234567890)
    handled = {}

    async def _fake_user(_uid):
        return {"language": "en"}

    async def _fake_handle_channel(message_arg, state_arg, lang, channel_norm, **kwargs):
        handled["message"] = message_arg
        handled["state"] = state_arg
        handled["lang"] = lang
        handled["channel_norm"] = channel_norm
        handled["trusted_channel"] = kwargs.get("trusted_channel")

    monkeypatch.setattr(vr, "get_user", _fake_user)
    monkeypatch.setattr(vr, "_handle_channel_value", _fake_handle_channel)

    await vr.receive_channel_shared(message, state)

    assert handled["channel_norm"] == "-1001234567890"
    assert handled["trusted_channel"] is True


def test_add_to_channel_url_targets_requested_bot_username():
    url = vr._add_to_channel_url("@test_bot")

    assert url.startswith("https://t.me/test_bot?startchannel=true&admin=")
    assert "Digital" not in url


@pytest.mark.asyncio
async def test_channel_admin_prompt_refreshes_add_link_from_token(monkeypatch):
    state = _FakeState()
    state.data.update(
        {
            "bot_token": "8791141203:AAE3lSGuFNNtWvSjL5mgk9VRNAhxIknW1x0",
            "bot_username": "PHanToOomDigitalServices",
        }
    )
    message = _FakeMessage("")
    prompts = []

    class _TempSession:
        async def close(self):
            return None

    class _TempBot:
        def __init__(self, token):
            self.token = token
            self.session = _TempSession()

        async def get_me(self):
            return SimpleNamespace(id=8791141203, username="test_bot", first_name="test")

    async def _fake_is_admin(*_args, **_kwargs):
        return False

    async def _fake_prompt(**kwargs):
        prompts.append(kwargs)
        return None

    async def _fake_show_channel(*_args, **_kwargs):
        return None

    monkeypatch.setattr(vr, "Bot", _TempBot)
    monkeypatch.setattr(vr, "_is_bot_admin_in_channel", _fake_is_admin)
    monkeypatch.setattr(vr, "_set_or_edit_prompt", _fake_prompt)
    monkeypatch.setattr(vr, "_show_channel_picker_prompt", _fake_show_channel)

    await vr._handle_channel_value(message, state, "en", "@my_channel", trusted_channel=True)

    buttons = prompts[-1]["reply_markup"].inline_keyboard
    assert buttons[0][0].url.startswith("https://t.me/test_bot?startchannel=true&admin=")
    assert "PHanToOomDigitalServices" not in buttons[0][0].url
    assert state.data["bot_username"] == "test_bot"


def test_telegram_chat_ref_coerces_numeric_channel_ids():
    assert vr._telegram_chat_ref("-1001234567890") == -1001234567890
    assert vr._telegram_chat_ref("@my_channel") == "@my_channel"


@pytest.mark.asyncio
async def test_is_bot_admin_in_channel_uses_numeric_shared_chat_id(monkeypatch):
    seen = {}

    class _TempSession:
        async def close(self):
            return None

    class _TempBot:
        def __init__(self, token):
            self.token = token
            self.session = _TempSession()

        async def get_me(self):
            return SimpleNamespace(id=42)

        async def get_chat(self, chat_id):
            seen["get_chat_id"] = chat_id
            return SimpleNamespace(id=chat_id)

        async def get_chat_member(self, chat_id, user_id):
            seen["get_member_chat_id"] = chat_id
            seen["get_member_user_id"] = user_id
            return SimpleNamespace(status="administrator")

    monkeypatch.setattr(vr, "Bot", _TempBot)

    assert await vr._is_bot_admin_in_channel("8791141203:AAE3lSGuFNNtWvSjL5mgk9VRNAhxIknW1x0", "-1001234567890") is True
    assert seen["get_chat_id"] == -1001234567890
    assert isinstance(seen["get_chat_id"], int)
    assert seen["get_member_chat_id"] == -1001234567890
    assert seen["get_member_user_id"] == 42


@pytest.mark.asyncio
async def test_is_bot_admin_in_channel_falls_back_to_admin_list(monkeypatch):
    seen = {}

    class _TempSession:
        async def close(self):
            return None

    class _TempBot:
        def __init__(self, token):
            self.token = token
            self.session = _TempSession()

        async def get_me(self):
            return SimpleNamespace(id=42)

        async def get_chat(self, chat_id):
            return SimpleNamespace(id=chat_id)

        async def get_chat_member(self, chat_id, user_id):
            seen["get_member_chat_id"] = chat_id
            seen["get_member_user_id"] = user_id
            return SimpleNamespace(status="member")

        async def get_chat_administrators(self, chat_id):
            seen["get_admins_chat_id"] = chat_id
            return [SimpleNamespace(user=SimpleNamespace(id=42))]

    monkeypatch.setattr(vr, "Bot", _TempBot)

    assert await vr._is_bot_admin_in_channel("8791141203:AAE3lSGuFNNtWvSjL5mgk9VRNAhxIknW1x0", "-1001234567890") is True
    assert seen["get_member_chat_id"] == -1001234567890
    assert seen["get_member_user_id"] == 42
    assert seen["get_admins_chat_id"] == -1001234567890
