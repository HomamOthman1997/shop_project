import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(0, os.getcwd())

from services.subscriptions import bot_subscription_service as svc
from services.subscriptions import presentation as sub_pres
from services.subscriptions.presentation import subscription_summary_lines


class _AsyncCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def limit(self, _n):
        return self

    def __aiter__(self):
        self._it = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _BotsCollection:
    def __init__(self, docs):
        self.docs = {int(doc["bot_id"]): dict(doc) for doc in docs}

    async def find_one(self, query, _projection=None):
        bot_id = query.get("bot_id")
        if bot_id is not None:
            return self.docs.get(int(bot_id))
        owner_id = query.get("owner_id")
        if owner_id is not None:
            for doc in self.docs.values():
                if int(doc.get("owner_id") or 0) != int(owner_id):
                    continue
                if doc.get("subscription", {}).get("trial_granted") is True:
                    return {"_id": doc.get("_id", 1)}
        return None

    async def update_one(self, query, update):
        doc = self.docs[int(query["bot_id"])]
        for key, value in (update.get("$set") or {}).items():
            parts = key.split(".")
            target = doc
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value

    def find(self, query, _projection=None):
        active = query.get("active")
        rows = [doc for doc in self.docs.values() if doc.get("active") == active]
        return _AsyncCursor(rows)


class _LedgerCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def find_one(self, query, _projection=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None


class _DB:
    def __init__(self, docs, ledger_docs=None):
        self.bots = _BotsCollection(docs)
        self.ledger_entries = _LedgerCollection(ledger_docs)


@pytest.fixture
def fixed_now(monkeypatch):
    now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(svc, "_utc_now", lambda: now)
    return now


@pytest.fixture
def pricing(monkeypatch):
    monkeypatch.setattr(svc.settings, "reseller_bot_monthly_price_usd", 10.0, raising=False)
    monkeypatch.setattr(svc.settings, "reseller_bot_trial_price_usd", 1.0, raising=False)
    monkeypatch.setattr(svc.settings, "reseller_bot_trial_days", 30, raising=False)
    monkeypatch.setattr(svc.settings, "reseller_bot_grace_days", 3, raising=False)
    async def _acquire(_lock_key):
        return True
    async def _release(_lock_key):
        return None
    async def _not_applied(_charge_key, _owner_id):
        return False
    monkeypatch.setattr(svc, "acquire_session_lock", _acquire)
    monkeypatch.setattr(svc, "release_session_lock", _release)
    monkeypatch.setattr(svc, "_subscription_charge_already_applied", _not_applied)


@pytest.mark.asyncio
async def test_plan_options(pricing):
    options = svc.get_subscription_plan_options()
    assert options == [
        {"months": 1, "price_usd": 10.0, "discount_percent": 0.0},
        {"months": 6, "price_usd": 54.0, "discount_percent": 10.0},
        {"months": 12, "price_usd": 96.0, "discount_percent": 20.0},
    ]


@pytest.mark.asyncio
async def test_trial_transitions_to_grace(monkeypatch, pricing, fixed_now):
    trial_end = fixed_now - timedelta(minutes=1)
    bot = {
        "bot_id": 100,
        "owner_id": 5,
        "active": True,
        "created_at": fixed_now - timedelta(days=30),
        "subscription": {
            "trial_granted": True,
            "status": "trial_active",
            "trial_started_at": fixed_now - timedelta(days=30),
            "trial_ends_at": trial_end,
            "renewal_plan_months": 1,
            "history": {
                "trial_paid_at": fixed_now - timedelta(days=30),
                "trial_paid_amount": 1.0,
            },
        },
    }
    monkeypatch.setattr(svc, "db", _DB([bot]))
    sub = await svc.get_bot_subscription(100)
    assert sub["status"] == "grace_period"
    assert sub["grace_ends_at"] == trial_end + timedelta(days=3)


@pytest.mark.asyncio
async def test_first_bot_collects_paid_trial_from_main_balance(monkeypatch, pricing, fixed_now):
    charges = []

    async def _balance(_owner_id, wallet_type="main"):
        assert wallet_type == "main"
        return 10.0

    async def _credit(**kwargs):
        charges.append(kwargs)

    bot = {
        "bot_id": 105,
        "owner_id": 11,
        "active": True,
        "created_at": fixed_now,
        "subscription": {
            "trial_granted": True,
            "trial_available": True,
            "status": "payment_required",
            "trial_price_usd": 1.0,
            "renewal_plan_months": 1,
            "renewal_charge_usd": 10.0,
            "history": {},
        },
    }
    monkeypatch.setattr(svc, "db", _DB([bot]))
    monkeypatch.setattr(svc, "get_reseller_wallet_balance", _balance)
    monkeypatch.setattr(svc, "credit_reseller_main_wallet", _credit)
    refreshed = await svc.sync_bot_subscription(105, collect_due=True)
    assert refreshed["status"] == "trial_active"
    assert refreshed["trial_available"] is False
    assert refreshed["trial_ends_at"] == fixed_now + timedelta(days=30)
    assert charges[0]["amount"] == -1.0
    assert charges[0]["reason"] == "bot_subscription_trial_debit"


@pytest.mark.asyncio
async def test_unpaid_legacy_trial_is_reset_to_payment_required(monkeypatch, pricing, fixed_now):
    async def _balance(_owner_id, wallet_type="main"):
        assert wallet_type == "main"
        return 0.0

    bot = {
        "bot_id": 106,
        "owner_id": 12,
        "active": True,
        "created_at": fixed_now,
        "subscription": {
            "trial_granted": True,
            "trial_available": False,
            "status": "trial_active",
            "trial_started_at": fixed_now - timedelta(days=1),
            "trial_ends_at": fixed_now + timedelta(days=29),
            "renewal_plan_months": 1,
            "renewal_charge_usd": 10.0,
            "history": {},
        },
    }
    fake_db = _DB([bot])
    monkeypatch.setattr(svc, "db", fake_db)
    monkeypatch.setattr(svc, "get_reseller_wallet_balance", _balance)

    refreshed = await svc.get_bot_subscription(106)

    assert refreshed["status"] == "payment_required"
    assert refreshed["trial_available"] is True
    assert refreshed["trial_started_at"] is None
    assert refreshed["trial_ends_at"] is None
    assert refreshed["history"]["unpaid_trial_reset_at"] == fixed_now
    assert fake_db.bots.docs[106]["subscription"]["status"] == "payment_required"


@pytest.mark.asyncio
async def test_unpaid_legacy_trial_starts_after_topup(monkeypatch, pricing, fixed_now):
    charges = []

    async def _balance(_owner_id, wallet_type="main"):
        assert wallet_type == "main"
        return 1.0

    async def _credit(**kwargs):
        charges.append(kwargs)

    bot = {
        "bot_id": 107,
        "owner_id": 13,
        "active": True,
        "created_at": fixed_now,
        "subscription": {
            "trial_granted": True,
            "trial_available": False,
            "status": "trial_active",
            "trial_started_at": fixed_now - timedelta(days=1),
            "trial_ends_at": fixed_now + timedelta(days=29),
            "renewal_plan_months": 1,
            "renewal_charge_usd": 10.0,
            "history": {},
        },
    }
    monkeypatch.setattr(svc, "db", _DB([bot]))
    monkeypatch.setattr(svc, "get_reseller_wallet_balance", _balance)
    monkeypatch.setattr(svc, "credit_reseller_main_wallet", _credit)

    refreshed = await svc.sync_bot_subscription(107, collect_due=True)

    assert refreshed["status"] == "trial_active"
    assert refreshed["trial_started_at"] == fixed_now
    assert refreshed["trial_ends_at"] == fixed_now + timedelta(days=30)
    assert refreshed["history"]["trial_paid_amount"] == 1.0
    assert charges[0]["amount"] == -1.0


@pytest.mark.asyncio
async def test_grace_auto_renew_anchors_from_previous_end(monkeypatch, pricing, fixed_now):
    trial_end = fixed_now - timedelta(days=1)
    charges = []

    async def _balance(_owner_id, wallet_type="main"):
        assert wallet_type == "main"
        return 100.0

    async def _credit(**kwargs):
        charges.append(kwargs)

    bot = {
        "bot_id": 101,
        "owner_id": 7,
        "active": True,
        "created_at": fixed_now - timedelta(days=31),
        "subscription": {
            "trial_granted": True,
            "status": "grace_period",
            "trial_started_at": fixed_now - timedelta(days=31),
            "trial_ends_at": trial_end,
            "grace_ends_at": trial_end + timedelta(days=3),
            "renewal_plan_months": 6,
            "renewal_charge_usd": 54.0,
            "history": {
                "trial_paid_at": fixed_now - timedelta(days=31),
                "trial_paid_amount": 1.0,
            },
        },
    }
    monkeypatch.setattr(svc, "db", _DB([bot]))
    monkeypatch.setattr(svc, "get_reseller_wallet_balance", _balance)
    monkeypatch.setattr(svc, "credit_reseller_main_wallet", _credit)
    sub = await svc.run_bot_subscription_sweep(limit=10)
    assert sub["renewed"] == 1
    refreshed = await svc.sync_bot_subscription(101, collect_due=False)
    assert refreshed["status"] == "active"
    assert refreshed["subscription_started_at"] == trial_end
    assert refreshed["subscription_ends_at"] == trial_end + timedelta(days=180)
    assert charges[0]["amount"] == -54.0


@pytest.mark.asyncio
async def test_expired_grace_becomes_suspended_without_balance(monkeypatch, pricing, fixed_now):
    ended = fixed_now - timedelta(days=5)

    async def _balance(_owner_id, wallet_type="main"):
        return 0.0

    bot = {
        "bot_id": 102,
        "owner_id": 8,
        "active": True,
        "created_at": fixed_now - timedelta(days=40),
        "subscription": {
            "trial_granted": False,
            "status": "grace_period",
            "subscription_started_at": ended - timedelta(days=30),
            "subscription_ends_at": ended,
            "grace_ends_at": ended + timedelta(days=3),
            "renewal_plan_months": 1,
        },
    }
    monkeypatch.setattr(svc, "db", _DB([bot]))
    monkeypatch.setattr(svc, "get_reseller_wallet_balance", _balance)
    refreshed = await svc.sync_bot_subscription(102, collect_due=True)
    assert refreshed["status"] == "suspended"


@pytest.mark.asyncio
async def test_set_plan_updates_renewal_price(monkeypatch, pricing, fixed_now):
    bot = {
        "bot_id": 103,
        "owner_id": 9,
        "active": True,
        "created_at": fixed_now,
        "subscription": {
            "trial_granted": False,
            "status": "payment_required",
            "renewal_plan_months": 1,
            "renewal_charge_usd": 10.0,
            "history": {},
        },
    }
    monkeypatch.setattr(svc, "db", _DB([bot]))
    updated = await svc.set_bot_subscription_plan(103, months=12)
    assert updated["renewal_plan_months"] == 12
    assert updated["renewal_charge_usd"] == 96.0
    assert updated["renewal_discount_percent"] == 20.0


@pytest.mark.asyncio
async def test_activate_subscription_anchors_from_existing_end(monkeypatch, pricing, fixed_now):
    current_end = fixed_now + timedelta(days=5)
    bot = {
        "bot_id": 104,
        "owner_id": 10,
        "active": True,
        "created_at": fixed_now - timedelta(days=10),
        "subscription": {
            "trial_granted": False,
            "status": "active",
            "subscription_started_at": fixed_now - timedelta(days=25),
            "subscription_ends_at": current_end,
            "grace_ends_at": current_end + timedelta(days=3),
            "renewal_plan_months": 1,
            "history": {},
        },
    }
    monkeypatch.setattr(svc, "db", _DB([bot]))
    updated = await svc.activate_bot_subscription(104, months=1, note="manual")
    assert updated["subscription_started_at"] == current_end
    assert updated["subscription_ends_at"] == current_end + timedelta(days=30)
    assert updated["history"]["last_activation_note"] == "manual"


@pytest.mark.asyncio
async def test_grace_auto_renew_is_idempotent_when_charge_already_exists(monkeypatch, pricing, fixed_now):
    trial_end = fixed_now - timedelta(days=1)
    charges = []

    async def _balance(_owner_id, wallet_type="main"):
        return 100.0

    async def _credit(**kwargs):
        charges.append(kwargs)

    async def _acquire(_lock_key):
        return True

    async def _release(_lock_key):
        return None

    async def _already_applied(_charge_key, _owner_id):
        return True

    bot = {
        "bot_id": 201,
        "owner_id": 17,
        "active": True,
        "created_at": fixed_now - timedelta(days=31),
        "subscription": {
            "trial_granted": True,
            "status": "grace_period",
            "trial_started_at": fixed_now - timedelta(days=31),
            "trial_ends_at": trial_end,
            "grace_ends_at": trial_end + timedelta(days=3),
            "renewal_plan_months": 6,
            "renewal_charge_usd": 54.0,
            "history": {
                "trial_paid_at": fixed_now - timedelta(days=31),
                "trial_paid_amount": 1.0,
            },
        },
    }
    monkeypatch.setattr(svc, "db", _DB([bot]))
    monkeypatch.setattr(svc, "get_reseller_wallet_balance", _balance)
    monkeypatch.setattr(svc, "credit_reseller_main_wallet", _credit)
    monkeypatch.setattr(svc, "acquire_session_lock", _acquire)
    monkeypatch.setattr(svc, "release_session_lock", _release)
    monkeypatch.setattr(svc, "_subscription_charge_already_applied", _already_applied)

    refreshed = await svc.sync_bot_subscription(201, collect_due=True)
    assert refreshed["status"] == "active"
    assert refreshed["subscription_started_at"] == trial_end
    assert refreshed["subscription_ends_at"] == trial_end + timedelta(days=180)
    assert charges == []


def test_subscription_summary_lines_arabic_are_readable():
    lines = subscription_summary_lines(
        "ar",
        {
            "status": "payment_required",
            "trial_available": False,
            "renewal_plan_months": 1,
            "renewal_charge_usd": 10.0,
            "trial_price_usd": 1.0,
            "renewal_discount_percent": 0.0,
        },
    )

    joined = "\n".join(lines)
    assert "خطة الاشتراك" in joined


def test_reseller_subscription_keyboard_has_activate_and_direct_main_bot_link(monkeypatch):
    monkeypatch.setattr(sub_pres, "main_bot_url", lambda start="hub": "https://t.me/MainBot?start=hub")

    kb = sub_pres.reseller_subscription_kb(
        {
            "status": "payment_required",
            "trial_available": True,
            "trial_price_usd": 1.0,
            "renewal_plan_months": 1,
        },
        "ar",
    )

    assert kb.inline_keyboard[0][0].callback_data == "rs_sub:activate"
    assert "تفعيل الشهر التجريبي" in kb.inline_keyboard[0][0].text
    assert kb.inline_keyboard[1][0].url == "https://t.me/MainBot?start=hub"
    assert kb.inline_keyboard[1][0].callback_data is None
    callbacks = [button.callback_data for row in kb.inline_keyboard for button in row]
    assert "rsmenu:main_bot_services" not in callbacks
    joined = "\n".join(
        subscription_summary_lines(
            "ar",
            {
                "status": "payment_required",
                "trial_available": False,
                "renewal_plan_months": 1,
                "renewal_charge_usd": 10.0,
                "trial_price_usd": 1.0,
                "renewal_discount_percent": 0.0,
            },
        )
    )
    assert "الحالة" in joined
    assert "الدفعة المطلوبة" in joined
