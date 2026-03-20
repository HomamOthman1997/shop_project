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
    monkeypatch.setattr(reseller_recharge, "_owner_notifications_target", fake_owner_target)

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
