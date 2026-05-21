"""Compatibility wrapper for Telegram imports.

Shared implementation lives in `services.numbers.shared.events`.
"""

from services.numbers.shared.events import (  # noqa: F401
    _log_number_event_from_order,
    _log_rental_event,
    _log_temp_event,
    _number_event_context_from_order,
)
