import os
import sys
from time import monotonic

sys.path.insert(0, os.getcwd())

from middlewares.bot_subscription import BotSubscriptionMiddleware, _subscription_block_text


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
