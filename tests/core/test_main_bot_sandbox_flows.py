import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

import handlers.main_menu as main_menu
import handlers.verify_reseller as verify_reseller


class _FakeBot:
    def __init__(self, bot_id: int = 111):
        self._bot_id = bot_id

    async def get_me(self):
        return SimpleNamespace(id=self._bot_id)


class _FakeMessage:
    def __init__(self, user_id: int = 50, text: str | None = None, bot_id: int = 111):
        self.from_user = SimpleNamespace(id=user_id)
        self.text = text
        self.bot = _FakeBot(bot_id=bot_id)
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.photo = []
        self.answers: list[tuple[str, object | None]] = []
        self.deleted = False

    async def answer(self, text, reply_markup=None, **_kwargs):
        self.answers.append((str(text), reply_markup))
        return SimpleNamespace(message_id=321)

    async def edit_text(self, text, reply_markup=None, **_kwargs):
        self.answers.append((str(text), reply_markup))
        return SimpleNamespace(message_id=321)

    async def delete(self):
        self.deleted = True


class _FakeCallback:
    def __init__(self, user_id: int = 50, data: str = "", bot_id: int = 111):
        self.from_user = SimpleNamespace(id=user_id)
        self.data = data
        self.bot = _FakeBot(bot_id=bot_id)
        self.message = _FakeMessage(user_id=user_id, bot_id=bot_id)
        self.answers: list[str] = []

    async def answer(self, text=None, **_kwargs):
        self.answers.append("" if text is None else str(text))


class _FakeState:
    def __init__(self, data=None):
        self._data = dict(data or {})
        self.cleared = False
        self.state = None

    async def get_data(self):
        return dict(self._data)

    async def get_state(self):
        return self.state

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def set_state(self, state):
        self.state = state

    async def clear(self):
        self.cleared = True
        self._data.clear()


@pytest.mark.asyncio
async def test_main_bot_balance_missing_wallet_scope_shows_main_bot_message(monkeypatch):
    message = _FakeMessage()

    async def _get_user(_user_id):
        return {"language": "en"}

    async def _false(*_args, **_kwargs):
        return False

    async def _true(*_args, **_kwargs):
        return True

    async def _none(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main_menu, "get_user", _get_user)
    monkeypatch.setattr(main_menu, "is_reseller", _false)
    monkeypatch.setattr(main_menu, "is_main_bot", _true)
    monkeypatch.setattr(main_menu, "_resolve_user_reseller", _none)

    await main_menu.balance_handler(message)

    assert message.answers
    assert message.answers[-1][0] in {"platform_wallet_scope_missing", "main_bot_wallet_scope_missing"}


@pytest.mark.asyncio
async def test_support_close_returns_main_menu(monkeypatch):
    callback = _FakeCallback()
    state = _FakeState()
    called = {}

    async def _return_main_menu(message, user_id):
        called["message"] = message
        called["user_id"] = user_id

    monkeypatch.setattr(main_menu, "_return_main_menu", _return_main_menu)

    await main_menu.support_close(callback, state)

    assert state.cleared is True
    assert called["message"] is callback.message
    assert called["user_id"] == callback.from_user.id


@pytest.mark.asyncio
async def test_support_button_does_not_clear_existing_state(monkeypatch):
    message = _FakeMessage(text=main_menu.t("en", "btn_support"))
    state = _FakeState({"flow": "numbers"})

    async def _get_user(_user_id):
        return {"language": "en"}

    monkeypatch.setattr(main_menu, "get_user", _get_user)

    await main_menu.simple_menu_placeholders(message, state)

    assert state.cleared is False
    assert message.answers
    assert message.answers[-1][1].__class__.__name__ == "InlineKeyboardMarkup"


@pytest.mark.asyncio
async def test_user_settings_close_returns_main_menu(monkeypatch):
    callback = _FakeCallback()
    called = {}

    async def _return_main_menu(message, user_id):
        called["message"] = message
        called["user_id"] = user_id

    monkeypatch.setattr(main_menu, "_return_main_menu", _return_main_menu)

    await main_menu.user_settings_close(callback)

    assert called["message"] is callback.message
    assert called["user_id"] == callback.from_user.id


@pytest.mark.asyncio
async def test_account_button_during_recharge_method_keeps_state(monkeypatch):
    message = _FakeMessage(text=main_menu.t("en", "user_settings_my_account"))
    state = _FakeState({"recharge_lang": "en"})
    state.state = main_menu.RechargeFlow.waiting_method

    async def _get_user(_user_id):
        return {"language": "en"}

    async def _open_account(_message, _user, _lang):
        await _message.answer("ACCOUNT")

    monkeypatch.setattr(main_menu, "get_user", _get_user)
    monkeypatch.setattr(main_menu, "_open_user_settings_message", _open_account)

    await main_menu.ask_recharge_amount(message, state)

    assert state.cleared is False
    assert state.state == main_menu.RechargeFlow.waiting_method
    assert message.answers[-1][0] == "ACCOUNT"


def test_user_settings_main_keyboard_hides_redundant_balance_button():
    kb = main_menu._user_settings_main_kb("en", {"language": "en"})

    buttons = [button.text for row in kb.inline_keyboard for button in row]

    assert main_menu.t("en", "btn_balance") not in buttons
    assert main_menu.t("en", "btn_add_balance") in buttons


@pytest.mark.asyncio
async def test_language_change_refreshes_reply_keyboard(monkeypatch):
    callback = _FakeCallback(data="uset:langset:en", bot_id=222)
    updated = {}

    async def _get_user(_user_id):
        return {"language": "en"}

    async def _main_text(*_args, **_kwargs):
        return "ACCOUNT"

    async def _menu(lang, bot_id, user_id=None):
        updated["lang"] = lang
        updated["bot_id"] = bot_id
        updated["user_id"] = user_id
        return "REPLY_MENU"

    async def _false(*_args, **_kwargs):
        return False

    class _Users:
        async def update_one(self, query, update):
            updated["query"] = query
            updated["update"] = update

    monkeypatch.setattr(main_menu, "get_user", _get_user)
    monkeypatch.setattr(main_menu, "_user_settings_main_text", _main_text)
    monkeypatch.setattr(main_menu, "menu_for_current_bot", _menu)
    monkeypatch.setattr(main_menu, "db", SimpleNamespace(users=_Users()))
    monkeypatch.setattr(main_menu, "is_numbers_bot", _false)

    await main_menu.user_settings_language_set(callback, _FakeState())

    assert updated["update"]["$set"]["language"] == "en"
    assert callback.message.answers[-1] == ("Main Menu", "REPLY_MENU")
    assert updated["lang"] == "en"
    assert updated["user_id"] == callback.from_user.id


@pytest.mark.asyncio
async def test_numbers_language_change_restarts_numbers_flow(monkeypatch):
    callback = _FakeCallback(data="uset:langset:ar", bot_id=879)
    state = _FakeState({"old": "value"})
    restarted = {}

    async def _get_user(_user_id):
        return {"language": "ar"}

    async def _true(*_args, **_kwargs):
        return True

    async def _restart(message, state_arg, *, lang):
        restarted["message"] = message
        restarted["state"] = state_arg
        restarted["lang"] = lang
        await message.answer("RESTARTED")

    class _Users:
        async def update_one(self, query, update):
            restarted["update"] = update

    monkeypatch.setattr(main_menu, "get_user", _get_user)
    monkeypatch.setattr(main_menu, "is_numbers_bot", _true)
    monkeypatch.setattr(main_menu, "db", SimpleNamespace(users=_Users()))
    monkeypatch.setattr("handlers.start._open_numbers_start_menu", _restart)

    await main_menu.user_settings_language_set(callback, state)

    assert restarted["update"]["$set"]["language"] == "ar"
    assert state.cleared is True
    assert restarted["message"] is callback.message
    assert restarted["state"] is state
    assert restarted["lang"] == "ar"
    assert callback.message.answers[-1][0] == "RESTARTED"


@pytest.mark.asyncio
async def test_create_bot_insufficient_balance_stays_in_flow(monkeypatch):
    callback = _FakeCallback(user_id=77, data="verify:confirm_create", bot_id=222)
    callback.message.chat = SimpleNamespace(id=999)
    callback.message.message_id = 444
    state = _FakeState(
        {
            "bot_token": "123:ABC",
            "bot_id": 555001,
            "channel": "@chan",
            "fullname": "User Name",
            "phone": "+123456",
            "address": "Some valid address",
            "preflight_ok": True,
            "preflight_checks": {"token": True, "channel": True, "admin": True, "reseller_group": False},
        }
    )
    captured = {}

    async def _get_user(_user_id):
        return {"language": "en"}

    async def _false(*_args, **_kwargs):
        return False

    async def _set_or_edit_prompt(**kwargs):
        captured["text"] = kwargs.get("text", "")

    monkeypatch.setattr(verify_reseller, "get_user", _get_user)
    monkeypatch.setattr(verify_reseller, "_is_bot_id_already_registered", _false)
    monkeypatch.setattr(verify_reseller, "get_reseller_wallet_balance", lambda *_args, **_kwargs: __import__("asyncio").sleep(0, result=0.0))
    monkeypatch.setattr(verify_reseller, "_set_or_edit_prompt", _set_or_edit_prompt)

    await verify_reseller.confirm_create_flow(callback, state)

    assert "not enough" in captured["text"].lower()
    assert "top up your balance in the main bot" in captured["text"].lower()


@pytest.mark.asyncio
async def test_receive_replacement_proof_uses_review_queue_for_main_bot(monkeypatch):
    message = _FakeMessage(user_id=90, bot_id=8147766487)
    message.photo = [SimpleNamespace(file_id="proof-1")]
    state = _FakeState()
    request_doc = {
        "_id": "req-1",
        "user_id": 90,
        "status": "need_more_proof",
        "details": {"wallet_scope": "main_bot"},
    }
    seen = {"main_bot_flow": None}

    class _FakeRechargeRequests:
        async def find_one(self, query, sort=None):
            if query.get("user_id") == 90 and query.get("status") == "need_more_proof":
                return dict(request_doc)
            if query.get("_id") == "req-1":
                return dict(request_doc)
            return None

        async def update_one(self, query, update):
            request_doc.update(update.get("$set", {}))
            return None

    fake_db = SimpleNamespace(recharge_requests=_FakeRechargeRequests())

    async def _get_user(_user_id):
        return {"language": "en"}

    async def _notify(message_arg, req_arg, user_arg, *, main_bot_flow):
        seen["main_bot_flow"] = main_bot_flow
        return True, "owner_topic", 11, -1001, 914

    async def _true(*_args, **_kwargs):
        return True

    monkeypatch.setattr(main_menu, "db", fake_db)
    monkeypatch.setattr(main_menu, "get_user", _get_user)
    monkeypatch.setattr(main_menu, "_notify_recharge_request_to_review_queue", _notify)
    monkeypatch.setattr(main_menu, "_uses_platform_wallet", _true)

    await main_menu.receive_replacement_proof(message, state)

    assert seen["main_bot_flow"] is True
    assert request_doc["status"] == "pending"
    assert request_doc["proof_file_id"] == "proof-1"
