import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from bson import ObjectId

sys.path.insert(0, os.getcwd())

import handlers.verify_reseller as vr


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
    monkeypatch.setattr(vr, "db", fake_db)
    monkeypatch.setattr(vr, "OWNER_ID", 999)

    async def _ok(*_a, **_k):
        return None

    async def _tpl(*_a, **_k):
        return {"success": True, "reason": "", "copied": 0}

    monkeypatch.setattr(vr, "add_bot", _ok)
    monkeypatch.setattr(vr, "update_bot_channel", _ok)
    monkeypatch.setattr(vr, "update_reseller_info", _ok)
    monkeypatch.setattr(vr, "verify_bot", _ok)
    monkeypatch.setattr(vr, "clone_catalog_from_reseller_template", _tpl)
    monkeypatch.setattr(vr, "_notify_requester_via_source_bot", _ok)
    callback = _FakeCallback(f"verify_owner:approve:{str(req['_id'])}", user_id=999)

    await vr.owner_review_callback(callback)

    assert req["status"] == "approved"
    assert callback.answers
    assert callback.message.edited is True


@pytest.mark.asyncio
async def test_owner_review_reject_branch(monkeypatch):
    req = _build_req()
    fake_db = SimpleNamespace(
        bot_creation_requests=_FakeCollection(req),
        bots=_FakeBotsCollection(),
    )
    monkeypatch.setattr(vr, "db", fake_db)
    monkeypatch.setattr(vr, "OWNER_ID", 321)

    async def _ok(*_a, **_k):
        return None

    monkeypatch.setattr(vr, "_notify_requester_via_source_bot", _ok)
    callback = _FakeCallback(f"verify_owner:reject:{str(req['_id'])}", user_id=321)

    await vr.owner_review_callback(callback)

    assert req["status"] == "rejected"
    assert callback.answers
