import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

import handlers.admin_services as admin_services
import handlers.reseller_recharge as reseller_recharge


class _FakeMessage:
    def __init__(self):
        self.sent_texts: list[str] = []
        self.chat = SimpleNamespace(id=123)

    async def answer(self, text, **_kwargs):
        self.sent_texts.append(str(text))
        return SimpleNamespace(message_id=99)

    async def edit_text(self, text, **_kwargs):
        self.sent_texts.append(str(text))
        return None


class _FakeCallback:
    def __init__(self, *, user_id: int, data: str, message=None, bot=None):
        self.from_user = SimpleNamespace(id=user_id, username="owner")
        self.data = data
        self.message = message
        self.bot = bot or SimpleNamespace(get_me=self._get_me)
        self.answers: list[dict] = []

    async def _get_me(self):
        return SimpleNamespace(id=999)

    async def answer(self, text=None, show_alert=False):
        self.answers.append({"text": text, "show_alert": bool(show_alert)})
        return True


class _FakeState:
    async def clear(self):
        return None

    async def set_state(self, _s):
        return None

    async def update_data(self, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_owner_panel_dashboard_callback(monkeypatch):
    fake_message = _FakeMessage()
    callback = _FakeCallback(
        user_id=int(admin_services.OWNER_ID),
        data="owner_panel:act:dashboard",
        message=fake_message,
    )
    state = _FakeState()

    async def _fake_dashboard():
        return "DASHBOARD_OK"

    monkeypatch.setattr(admin_services, "_build_owner_dashboard_text", _fake_dashboard)

    await admin_services.owner_panel_action(callback, state)

    assert any("DASHBOARD_OK" in x for x in fake_message.sent_texts)
    assert callback.answers


@pytest.mark.asyncio
async def test_owner_panel_open_shows_home_not_dashboard(monkeypatch):
    fake_message = _FakeMessage()

    async def _fake_owner_only(_message):
        return True

    async def _fake_hide(*_args, **_kwargs):
        return None

    monkeypatch.setattr(admin_services, "owner_only", _fake_owner_only)
    monkeypatch.setattr(admin_services, "_hide_owner_reply_keyboard", _fake_hide)

    await admin_services.owner_panel_open_command(fake_message)

    assert any("Owner Panel" in x for x in fake_message.sent_texts)
    assert not any("Owner Dashboard" in x for x in fake_message.sent_texts)


@pytest.mark.asyncio
async def test_reseller_dashboard_callback(monkeypatch):
    fake_message = _FakeMessage()

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=777)

    callback = _FakeCallback(
        user_id=555,
        data="rsmenu:dashboard",
        message=fake_message,
        bot=_Bot(),
    )

    async def _fake_is_reseller(_uid, _bot):
        return True

    async def _fake_lang(_uid):
        return "en"

    async def _fake_hide(*_a, **_k):
        return None

    async def _fake_dash(_rid, _bot_id):
        return "DASHBOARD_OK"

    monkeypatch.setattr(reseller_recharge, "_is_current_bot_reseller", _fake_is_reseller)
    monkeypatch.setattr(reseller_recharge, "_reseller_lang", _fake_lang)
    monkeypatch.setattr(reseller_recharge, "_hide_reply_keyboard", _fake_hide)
    monkeypatch.setattr(reseller_recharge, "_build_reseller_dashboard_text", _fake_dash)

    await reseller_recharge.reseller_menu_dashboard(callback)

    assert any("DASHBOARD_OK" in x for x in fake_message.sent_texts)
    assert callback.answers


@pytest.mark.asyncio
async def test_owner_panel_broadcast_callback(monkeypatch):
    fake_message = _FakeMessage()
    callback = _FakeCallback(
        user_id=int(admin_services.OWNER_ID),
        data="owner_panel:act:broadcast",
        message=fake_message,
    )
    state = _FakeState()

    async def _fake_edit(message, text, **_kwargs):
        await message.edit_text(text)

    monkeypatch.setattr(admin_services, "_safe_edit_text", _fake_edit)

    await admin_services.owner_panel_action(callback, state)

    assert any("إذاعة" in x for x in fake_message.sent_texts)
    assert callback.answers


@pytest.mark.asyncio
async def test_reseller_broadcast_callback(monkeypatch):
    fake_message = _FakeMessage()

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=777)

    callback = _FakeCallback(
        user_id=555,
        data="rsmenu:broadcast",
        message=fake_message,
        bot=_Bot(),
    )
    state = _FakeState()

    async def _fake_is_reseller(_uid, _bot):
        return True

    async def _fake_lang(_uid):
        return "en"

    async def _fake_hide(*_a, **_k):
        return None

    async def _fake_status(_bot):
        return True, "@mychannel", ""

    monkeypatch.setattr(reseller_recharge, "_is_current_bot_reseller", _fake_is_reseller)
    monkeypatch.setattr(reseller_recharge, "_reseller_lang", _fake_lang)
    monkeypatch.setattr(reseller_recharge, "_hide_reply_keyboard", _fake_hide)
    monkeypatch.setattr(reseller_recharge, "_broadcast_channel_status", _fake_status)

    await reseller_recharge.reseller_menu_broadcast(callback, state)

    assert any("إذاعة" in x for x in fake_message.sent_texts)
    assert callback.answers


@pytest.mark.asyncio
async def test_reseller_broadcast_callback_shows_alert_when_channel_invalid(monkeypatch):
    fake_message = _FakeMessage()

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=777)

    callback = _FakeCallback(
        user_id=555,
        data="rsmenu:broadcast",
        message=fake_message,
        bot=_Bot(),
    )
    state = _FakeState()

    async def _fake_is_reseller(_uid, _bot):
        return True

    async def _fake_status(_bot):
        return False, None, "قناة البوت غير مربوطة أو البوت ليس Admin فيها."

    monkeypatch.setattr(reseller_recharge, "_is_current_bot_reseller", _fake_is_reseller)
    monkeypatch.setattr(reseller_recharge, "_broadcast_channel_status", _fake_status)

    await reseller_recharge.reseller_menu_broadcast(callback, state)

    assert not fake_message.sent_texts
    assert callback.answers
    assert callback.answers[-1]["show_alert"] is True
    assert "قناة البوت" in str(callback.answers[-1]["text"] or "")
