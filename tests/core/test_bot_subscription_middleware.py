import os
import sys
from time import monotonic

import pytest

sys.path.insert(0, os.getcwd())

from middlewares.bot_subscription import BotSubscriptionMiddleware, _subscription_block_text


class _Event:
    from_user = type("User", (), {"id": 123})()


async def _handler(_event, _data):
    return "handled"


def test_subscription_block_text_arabic_is_readable():
    text = _subscription_block_text(
        {
            "status": "payment_required",
            "trial_available": False,
            "renewal_charge_usd": 10.0,
        },
        lang="ar",
    )
    assert "هذا البوت موقوف" in text
    assert "الاشتراك غير مدفوع" in text
    assert "????" not in text


def test_subscription_block_text_arabic_suspended_is_readable():
    text = _subscription_block_text(
        {
            "status": "suspended",
            "renewal_charge_usd": 10.0,
            "grace_ends_at": None,
        },
        lang="ar",
    )
    assert "قيمة التجديد الحالية" in text
    assert "سيعود البوت للعمل" in text


def test_blocked_subscription_cache_ttl_is_shorter():
    middleware = BotSubscriptionMiddleware()
    now = monotonic()
    middleware._subscription_cache[5] = ({"status": "payment_required"}, now - 4.0)
    middleware._subscription_cache[6] = ({"status": "active"}, now - 4.0)

    assert middleware._cached_subscription(5, now) is None
    assert middleware._cached_subscription(6, now) == {"status": "active"}


@pytest.mark.asyncio
async def test_subscription_middleware_skips_platform_bots(monkeypatch):
    middleware = BotSubscriptionMiddleware()
    calls = {"reseller": 0, "subscription": 0}

    async def _platform(_bot_id):
        return True

    async def _reseller(_bot_id):
        calls["reseller"] += 1
        return 999

    async def _subscription(_bot_id):
        calls["subscription"] += 1
        return {"status": "payment_required"}

    monkeypatch.setattr(BotSubscriptionMiddleware, "_is_platform_bot", staticmethod(_platform))
    monkeypatch.setattr("middlewares.bot_subscription.get_reseller_id_for_bot", _reseller)
    monkeypatch.setattr("middlewares.bot_subscription.get_bot_subscription", _subscription)
    async def _runtime_bot_id(_bot):
        return 8797083654

    monkeypatch.setattr("middlewares.bot_subscription.resolve_runtime_bot_id", _runtime_bot_id)

    result = await middleware(_handler, _Event(), {"bot": object()})

    assert result == "handled"
    assert calls == {"reseller": 0, "subscription": 0}
