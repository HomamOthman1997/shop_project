import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from bson import ObjectId

sys.path.insert(0, os.getcwd())

import handlers.owner_requests as owner_requests


class _FakeCollection:
    def __init__(self, req):
        self.req = req
        self.updated: list[tuple[dict, dict]] = []

    async def find_one(self, query, *args, **kwargs):
        if query.get("_id") == self.req.get("_id") and query.get("status") == "pending":
            return dict(self.req)
        return None

    async def update_one(self, selector, update, **kwargs):
        self.updated.append((dict(selector), dict(update)))
        if selector.get("_id") == self.req.get("_id"):
            status = ((update.get("$set") or {}).get("status") or "").strip()
            if status:
                self.req["status"] = status
        return SimpleNamespace(modified_count=1)


class _FakeBotsCollection:
    async def find_one(self, *_args, **_kwargs):
        return None

    async def update_one(self, *_args, **_kwargs):
        return SimpleNamespace(modified_count=1)

    async def delete_one(self, *_args, **_kwargs):
        return SimpleNamespace(deleted_count=1)


class _FakeMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=-100123)
        self.message_id = 77
        self.message_thread_id = 9
        self.edited = False

    async def edit_reply_markup(self, **_kwargs):
        self.edited = True
        return None


class _FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def get_me(self):
        return SimpleNamespace(id=888)

    async def send_message(self, chat_id, text, **_kwargs):
        self.sent.append((int(chat_id), str(text)))
        return SimpleNamespace(message_id=333)


class _FakeCallback:
    def __init__(self, data: str, user_id: int):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, username="owner")
        self.bot = _FakeBot()
        self.message = _FakeMessage()
        self.answers: list[str] = []

    async def answer(self, text=None, **_kwargs):
        self.answers.append(str(text or ""))
        return True


def _build_req():
    req_id = ObjectId()
    return {
        "_id": req_id,
        "status": "pending",
        "requester_id": 12345,
        "requester_lang": "en",
        "payload": {
            "bot_id": 555001,
            "bot_token": "123456:ABCDEF_xxxxxxxxxxxxxxxxxxxxxxxx",
            "bot_username": "new_bot",
            "channel": "@chan",
            "fullname": "Name",
            "phone": "+1",
            "address": "Addr",
        },
        "created_at": datetime.now(UTC),
    }


@pytest.mark.asyncio
async def test_owner_review_approve_branch(monkeypatch):
    req = _build_req()
    fake_db = SimpleNamespace(
        bot_creation_requests=_FakeCollection(req),
        bots=_FakeBotsCollection(),
    )
    monkeypatch.setattr(owner_requests, "db", fake_db)
    monkeypatch.setattr(owner_requests, "OWNER_ID", 999)

    async def _ok(*_a, **_k):
        return None

    async def _balance(*_a, **_k):
        return 1.0

    async def _sync(*_a, **_k):
        return {"status": "trial_active"}

    monkeypatch.setattr(owner_requests, "add_bot", _ok)
    monkeypatch.setattr(owner_requests, "get_reseller_wallet_balance", _balance)
    monkeypatch.setattr(owner_requests, "sync_bot_subscription", _sync)
    monkeypatch.setattr(owner_requests, "update_bot_channel", _ok)
    monkeypatch.setattr(owner_requests, "update_reseller_info", _ok)
    monkeypatch.setattr(owner_requests, "verify_bot", _ok)
    monkeypatch.setattr(owner_requests, "_notify_requester", _ok)
    callback = _FakeCallback(f"verify_owner:approve:{str(req['_id'])}", user_id=999)

    await owner_requests.owner_review_callback(callback)

    assert req["status"] == "approved"
    assert callback.answers
    assert callback.message.edited is True


@pytest.mark.asyncio
async def test_owner_review_approve_requires_trial_balance(monkeypatch):
    req = _build_req()
    fake_db = SimpleNamespace(
        bot_creation_requests=_FakeCollection(req),
        bots=_FakeBotsCollection(),
    )
    monkeypatch.setattr(owner_requests, "db", fake_db)
    monkeypatch.setattr(owner_requests, "OWNER_ID", 999)

    called = {"add_bot": False, "notified": ""}

    async def _add_bot(*_a, **_k):
        called["add_bot"] = True

    async def _balance(*_a, **_k):
        return 0.0

    async def _notify(_req, text):
        called["notified"] = str(text)

    monkeypatch.setattr(owner_requests, "add_bot", _add_bot)
    monkeypatch.setattr(owner_requests, "get_reseller_wallet_balance", _balance)
    monkeypatch.setattr(owner_requests, "_notify_requester", _notify)

    callback = _FakeCallback(f"verify_owner:approve:{str(req['_id'])}", user_id=999)

    await owner_requests.owner_review_callback(callback)

    assert req["status"] == "failed"
    assert called["add_bot"] is False
    assert "not enough" in called["notified"].lower()


@pytest.mark.asyncio
async def test_owner_review_reject_branch(monkeypatch):
    req = _build_req()
    fake_db = SimpleNamespace(
        bot_creation_requests=_FakeCollection(req),
        bots=_FakeBotsCollection(),
    )
    monkeypatch.setattr(owner_requests, "db", fake_db)
    monkeypatch.setattr(owner_requests, "OWNER_ID", 321)

    async def _ok(*_a, **_k):
        return None

    monkeypatch.setattr(owner_requests, "_notify_requester", _ok)
    callback = _FakeCallback(f"verify_owner:reject:{str(req['_id'])}", user_id=321)

    await owner_requests.owner_review_callback(callback)

    assert req["status"] == "rejected"
    assert callback.answers
