import os
import sys
from types import SimpleNamespace

import pytest
from bson import ObjectId

sys.path.insert(0, os.getcwd())

import database.reseller_settings_repo as reseller_repo
import handlers.reseller_recharge as reseller_recharge


@pytest.mark.asyncio
async def test_owner_topup_request_routes_to_owner_before_reseller(monkeypatch):
    calls: list[dict] = []

    async def fake_get_recharge_routing(_reseller_id):
        return {"chat_id": -100777, "message_thread_id": 12}

    async def fake_owner_target():
        return {"chat_id": -100999, "message_thread_id": 21}

    class FakeBot:
        async def send_message(self, *, chat_id, text, reply_markup, message_thread_id=None):
            calls.append(
                {
                    "chat_id": chat_id,
                    "text": text,
                    "thread_id": message_thread_id,
                }
            )
            return SimpleNamespace(message_id=555)

    fake_message = SimpleNamespace(
        from_user=SimpleNamespace(first_name="Cyber", last_name="Zone"),
        bot=FakeBot(),
    )
    req = {
        "_id": "req-1",
        "reseller_id": 42,
        "method": "USDT",
        "details": {"paid_amount": 50, "paid_currency": "USD", "credits": 50},
    }

    monkeypatch.setattr(reseller_recharge, "get_recharge_routing", fake_get_recharge_routing)
    monkeypatch.setattr(reseller_recharge, "_owner_reseller_topup_target", fake_owner_target)

    delivered, route, msg_id, chat_id, thread_id = await reseller_recharge._notify_owner_reseller_topup_request(
        fake_message,
        req,
        {"username": "seller42"},
    )

    assert delivered is True
    assert route == "owner_topic"
    assert msg_id == 555
    assert chat_id == -100999
    assert thread_id == 21
    assert len(calls) == 1
    assert calls[0]["chat_id"] == -100999


@pytest.mark.asyncio
async def test_parse_topic_target_accepts_username_and_tg_resolve():
    class FakeBot:
        async def get_chat(self, chat_id):
            assert chat_id == "@mygroup"
            return SimpleNamespace(id=-1001234567890)

    bot = FakeBot()
    assert await reseller_recharge._parse_topic_target("@mygroup", bot) == (-1001234567890, None)
    assert await reseller_recharge._parse_topic_target("tg://resolve?domain=mygroup&thread=44", bot) == (
        -1001234567890,
        44,
    )


def test_topic_target_error_private_invite_has_actionable_hint():
    text = reseller_recharge._topic_target_parse_error("https://t.me/+secretInviteHash")
    assert "Private invite links cannot be converted" in text
    assert "-100CHAT_ID" in text


@pytest.mark.asyncio
async def test_delete_recharge_address_is_scoped_to_reseller(monkeypatch):
    calls: list[tuple[dict, dict]] = []

    class FakeCollection:
        async def update_one(self, selector, update):
            calls.append((selector, update))

    fake_db = SimpleNamespace(reseller_settings=FakeCollection())
    monkeypatch.setattr(reseller_repo, "db", fake_db)
    address_id = ObjectId()
    await reseller_repo.delete_recharge_address(77, address_id)

    assert calls == [({"reseller_id": 77}, {"$pull": {"addresses": {"_id": address_id}}})]


@pytest.mark.asyncio
async def test_reseller_manual_accept_notifies_user_via_source_bot(monkeypatch):
    req_id = ObjectId()
    notified: list[tuple[dict, object, str, object]] = []

    class FakeNotifyBot:
        def __init__(self, name):
            self.name = name
            self.session = SimpleNamespace(close=self._close)

        async def _close(self):
            return None

        async def send_message(self, chat_id, text, reply_markup=None):
            sent.append((self.name, chat_id, text, reply_markup))

    class FakeState:
        async def get_data(self):
            return {"owner_manual_reseller_topup_req_id": str(req_id)}

        async def clear(self):
            return None

    class FakeMessage:
        def __init__(self):
            self.text = "800"
            self.from_user = SimpleNamespace(id=999)
            self.bot = FakeNotifyBot("fallback")
            self.answers = []

        async def answer(self, text):
            self.answers.append(text)

    req = {
        "_id": req_id,
        "user_id": 12345,
        "reseller_id": 12345,
        "status": "accepted",
        "details": {"source_bot_id": 555},
    }

    async def fake_owner_only(_message):
        return True

    async def fake_find_one(query):
        assert query == {"_id": req_id}
        return req

    async def fake_get_balance(_user_id, _scope_id):
        return 10.0

    async def fake_get_user(_user_id):
        return {"language": "en"}

    async def fake_notify(req_arg, fallback_bot, text, *, reply_markup=None):
        notified.append((req_arg, fallback_bot, text, reply_markup))

    async def fake_edit(_bot, _req):
        return None

    async def fake_is_current_bot_reseller(_user_id, _bot):
        return True

    async def fake_update_recharge_request(*_args, **_kwargs):
        return True

    monkeypatch.setattr(reseller_recharge, "_is_current_bot_reseller", fake_is_current_bot_reseller)
    monkeypatch.setattr(reseller_recharge, "update_recharge_request", fake_update_recharge_request)
    monkeypatch.setattr(reseller_recharge, "_notify_recharge_request_user", fake_notify)
    monkeypatch.setattr(reseller_recharge, "_edit_request_card_message", fake_edit)
    monkeypatch.setattr(reseller_recharge, "get_user_wallet_balance", fake_get_balance)
    monkeypatch.setattr(reseller_recharge, "get_user", fake_get_user)
    monkeypatch.setattr(
        reseller_recharge,
        "db",
        SimpleNamespace(recharge_requests=SimpleNamespace(find_one=fake_find_one)),
    )

    message = FakeMessage()
    class _State:
        async def get_data(self):
            return {"manual_recharge_req_id": str(req_id)}

        async def clear(self):
            return None

    await reseller_recharge.recharge_manual_apply(message, _State())

    assert notified
    assert notified[0][0] == req
    assert notified[0][1] is message.bot
    assert "Recharge accepted manually." in notified[0][2]


@pytest.mark.asyncio
async def test_notify_recharge_request_user_uses_source_bot(monkeypatch):
    sent: list[tuple[str, int, str]] = []

    class FakeBot:
        def __init__(self, name):
            self.name = name
            self.session = SimpleNamespace(close=self._close)

        async def _close(self):
            return None

        async def send_message(self, chat_id, text, reply_markup=None):
            sent.append((self.name, chat_id, text))

    async def fake_resolve(_req, _fallback):
        return FakeBot("source")

    monkeypatch.setattr(reseller_recharge, "_resolve_request_user_notification_bot", fake_resolve)

    await reseller_recharge._notify_recharge_request_user(
        {"user_id": 987, "details": {"source_bot_id": 222}},
        FakeBot("fallback"),
        "hello",
    )

    assert sent == [("source", 987, "hello")]


@pytest.mark.asyncio
async def test_resolve_notification_bot_uses_configured_numbers_bot_token(monkeypatch):
    created: list[tuple[str, int | None]] = []

    class FakeCreatedBot:
        def __init__(self, token, timeout=None):
            self.token = token
            self.timeout = timeout
            self.session = SimpleNamespace(close=self._close)
            created.append((token, timeout))

        async def _close(self):
            return None

    class FakeFallbackBot:
        async def get_me(self):
            return SimpleNamespace(id=999)

    class FakeBotsCollection:
        async def find_one(self, *_args, **_kwargs):
            raise AssertionError("configured platform token should be used before db lookup")

    monkeypatch.setattr(reseller_recharge.settings, "bot_numbers_token", "222:NUMBERS", raising=False)
    monkeypatch.setattr(reseller_recharge, "Bot", FakeCreatedBot)
    monkeypatch.setattr(
        reseller_recharge,
        "db",
        SimpleNamespace(bots=FakeBotsCollection()),
    )

    bot = await reseller_recharge._resolve_request_user_notification_bot(
        {"details": {"source_bot_id": 222}},
        FakeFallbackBot(),
    )

    assert bot.token == "222:NUMBERS"
    assert created == [("222:NUMBERS", 30)]
