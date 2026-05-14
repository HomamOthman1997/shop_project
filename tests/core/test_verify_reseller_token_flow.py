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


def test_add_to_group_url_carries_create_flow_payload():
    url = vr._add_to_group_url("@test_bot", start_payload="setup_ABC123")

    assert url.startswith("https://t.me/test_bot?startgroup=setup_ABC123&admin=")
    assert "manage_topics" in url


def test_create_bot_intro_explains_trial_subscription_and_scope(monkeypatch):
    monkeypatch.setattr(vr.settings, "reseller_bot_trial_days", 14, raising=False)
    monkeypatch.setattr(vr.settings, "reseller_bot_trial_price_usd", 2.5, raising=False)
    monkeypatch.setattr(vr.settings, "reseller_bot_monthly_price_usd", 9.0, raising=False)
    monkeypatch.setattr(vr.settings, "reseller_bot_grace_days", 4, raising=False)

    text = vr._intro_prompt_html("en")

    assert "Create Your Bot" in text
    assert "customer-facing Telegram bot" in text
    assert "Trial: 14 days" in text
    assert "2.50" in text
    assert "9.00" in text
    assert "4-day grace period" in text
    assert "Auto Setup Topics" in text
    assert "You manage your customers, pricing, and support" in text


def test_create_bot_intro_arabic_explains_terms(monkeypatch):
    monkeypatch.setattr(vr.settings, "reseller_bot_trial_days", 14, raising=False)
    monkeypatch.setattr(vr.settings, "reseller_bot_trial_price_usd", 2.5, raising=False)
    monkeypatch.setattr(vr.settings, "reseller_bot_monthly_price_usd", 9.0, raising=False)
    monkeypatch.setattr(vr.settings, "reseller_bot_grace_days", 4, raising=False)

    text = vr._intro_prompt_html("ar")

    assert "إنشاء بوتك الخاص" in text
    assert "التريل: 14 يوم" in text
    assert "2.50" in text
    assert "9.00" in text
    assert "مهلة 4 أيام" in text
    assert "Manage Topics" in text
    assert "أنت تدير زبائنك وأسعارك ودعمك" in text


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


@pytest.mark.asyncio
async def test_auto_setup_reseller_topics_discovers_group_and_binds_routes(monkeypatch):
    calls = {}

    class _TempSession:
        async def close(self):
            return None

    class _TempBot:
        def __init__(self, token):
            self.token = token
            self.session = _TempSession()

        async def get_me(self):
            return SimpleNamespace(id=8791141203)

        async def get_chat_member(self, chat_id, user_id):
            calls["member"] = (chat_id, user_id)
            return SimpleNamespace(status="administrator", can_manage_topics=True)

        async def create_forum_topic(self, chat_id, name):
            calls.setdefault("topics", []).append((chat_id, name))
            return SimpleNamespace(message_thread_id=11 if name == "Payment Requests" else 22)

    async def _discover(_token, _flow_ref):
        return [-100777]

    async def _set_pay(reseller_id, chat_id, message_thread_id):
        calls["pay"] = (reseller_id, chat_id, message_thread_id)

    async def _set_ex(reseller_id, chat_id, message_thread_id):
        calls["ex"] = (reseller_id, chat_id, message_thread_id)

    monkeypatch.setattr(vr, "Bot", _TempBot)
    monkeypatch.setattr(vr, "_discover_setup_group_candidates", _discover)
    monkeypatch.setattr(vr, "set_recharge_routing", _set_pay)
    monkeypatch.setattr(vr, "set_exchange_routing", _set_ex)

    ok, err = await vr._auto_setup_reseller_topics(
        bot_token="8791141203:AAE3lSGuFNNtWvSjL5mgk9VRNAhxIknW1x0",
        reseller_id=77,
        data={vr.FLOW_REF_KEY: "ABC123"},
        pay_route=None,
        ex_route=None,
    )

    assert ok is True
    assert err == ""
    assert calls["member"] == (-100777, 8791141203)
    assert calls["topics"] == [(-100777, "Payment Requests"), (-100777, "Exchange Alerts")]
    assert calls["pay"] == (77, -100777, 11)
    assert calls["ex"] == (77, -100777, 22)


@pytest.mark.asyncio
async def test_preflight_auto_sets_topics_when_group_routing_missing(monkeypatch):
    async def _no_pay(_reseller_id):
        return None

    async def _no_ex(_reseller_id):
        return None

    async def _auto_setup(**kwargs):
        return True, ""

    monkeypatch.setattr(vr, "get_recharge_routing", _no_pay)
    monkeypatch.setattr(vr, "get_exchange_routing", _no_ex)
    monkeypatch.setattr(vr, "_auto_setup_reseller_topics", _auto_setup)

    ok, checks = await vr._run_preflight_checks(
        {
            "bot_token": "8791141203:AAE3lSGuFNNtWvSjL5mgk9VRNAhxIknW1x0",
            "bot_id": 8791141203,
            "channel": "@my_channel",
            "token_verified": True,
            "channel_verified": True,
            "admin_verified": True,
        },
        requester_id=77,
    )

    assert ok is True
    assert checks["reseller_group"] is True
    assert checks["auto_topics"] is True


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
