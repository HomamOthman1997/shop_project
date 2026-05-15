import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

import handlers.verify_reseller as vr


class _FakeState:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, value):
        self.state = value


class _FakeCallback:
    def __init__(self, user_id=77):
        self.data = "verify:confirm_create"
        self.from_user = SimpleNamespace(id=user_id, username="reseller", first_name="Test", last_name="User")
        self.message = SimpleNamespace(chat=SimpleNamespace(id=555), message_id=444)
        self.bot = SimpleNamespace()
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))


def test_phone_region_and_location_syria_detection():
    assert vr._extract_phone_region("+963991234567") == "SY"
    assert vr._phone_is_syrian("00963991234567") is True
    assert vr._phone_is_syrian("+15551234567") is False

    assert vr._is_location_in_syria(33.5138, 36.2765) is True
    assert vr._is_location_in_syria(40.7128, -74.0060) is False


@pytest.mark.asyncio
async def test_confirm_routes_non_syrian_phone_or_location_to_manual_review(monkeypatch):
    state = _FakeState(
        {
            "bot_token": "1234567890:AAExample_token-value_1234567890",
            "bot_id": 555001,
            "channel": "@chan",
            "fullname": "User Name",
            "phone": "+15551234567",
            "phone_country": "United States",
            "phone_region": "US",
            "address": "Telegram location: 40.712800, -74.006000",
            "location_latitude": 40.7128,
            "location_longitude": -74.0060,
            "location_country_code": "OUTSIDE_SYRIA",
            "location_is_syria": False,
            "location_live": True,
            "preflight_ok": True,
            "preflight_checks": {"token": True, "channel": True, "admin": True, "reseller_group": True},
        }
    )
    callback = _FakeCallback()
    captured = {}

    async def _get_user(_user_id):
        return {"language": "en"}

    async def _false(*_args, **_kwargs):
        return False

    async def _manual_review(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(vr, "get_user", _get_user)
    monkeypatch.setattr(vr, "_is_bot_id_already_registered", _false)
    monkeypatch.setattr(vr, "get_user_wallet_balance", lambda *_args, **_kwargs: __import__("asyncio").sleep(0, result=10.0))
    monkeypatch.setattr(vr, "_submit_manual_bot_creation_review", _manual_review)
    monkeypatch.setattr(vr, "add_bot", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not auto-create")))

    await vr.confirm_create_flow(callback, state)

    assert captured["reasons"] == ["phone_not_syria", "location_not_syria"]
    assert captured["payload"]["phone_region"] == "US"
    assert captured["payload"]["location"]["country_code"] == "OUTSIDE_SYRIA"


@pytest.mark.asyncio
async def test_confirm_rechecks_stale_failed_preflight(monkeypatch):
    state = _FakeState(
        {
            "bot_token": "1234567890:AAExample_token-value_1234567890",
            "bot_id": 555001,
            "channel": "@chan",
            "fullname": "User Name",
            "phone": "+963991234567",
            "address": "Telegram location: 34.900000, 35.900000",
            "preflight_ok": False,
            "preflight_checks": {
                "token": True,
                "channel": True,
                "admin": True,
                "reseller_group": False,
                "warning": "old failure",
            },
        }
    )
    callback = _FakeCallback()
    captured = {}

    async def _get_user(_user_id):
        return {"language": "en"}

    async def _false(*_args, **_kwargs):
        return False

    async def _recheck(_data, requester_id=None):
        captured["requester_id"] = requester_id
        return False, {
            "token": True,
            "channel": True,
            "admin": True,
            "reseller_group": False,
            "warning": "fresh failure",
        }

    async def _set_or_edit_prompt(**kwargs):
        captured["text"] = kwargs.get("text", "")

    monkeypatch.setattr(vr, "get_user", _get_user)
    monkeypatch.setattr(vr, "_is_bot_id_already_registered", _false)
    monkeypatch.setattr(vr, "_run_preflight_checks", _recheck)
    monkeypatch.setattr(vr, "_set_or_edit_prompt", _set_or_edit_prompt)

    await vr.confirm_create_flow(callback, state)

    assert captured["requester_id"] == 77
    assert "fresh failure" in captured["text"]
