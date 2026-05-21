"""Compatibility wrapper for Telegram imports.

Shared implementation lives in `services.numbers.shared.rental_policy`.
"""

from services.numbers.shared.rental_policy import (  # noqa: F401
    HERO_RENTAL_CANCEL_WINDOW_SEC,
    RENTAL_EXIT_GUARD_FALLBACK_SYNC_WINDOW_SEC,
    _is_within_hero_rental_cancel_window,
    _rental_deadline_at,
    _rental_no_sms_yet,
    _rental_protection_policy,
    _rental_safe_cutoff_at,
)
