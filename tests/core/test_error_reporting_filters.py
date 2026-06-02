import logging
import os
import sys

sys.path.insert(0, os.getcwd())

from utils.sentry_reporting import _before_send
from utils.telegram_error_reporting import TelegramErrorHandler


CONFLICT_MESSAGE = (
    "Failed to fetch updates - TelegramConflictError: Telegram server says - "
    "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running"
)


def test_telegram_error_handler_suppresses_polling_conflict():
    record = logging.LogRecord(
        name="aiogram.dispatcher",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=CONFLICT_MESSAGE,
        args=(),
        exc_info=None,
    )

    assert TelegramErrorHandler._is_transient_polling_noise(record, record.getMessage()) is True


def test_telegram_error_handler_suppresses_getupdates_retry_after():
    record = logging.LogRecord(
        name="aiogram.dispatcher",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=(
            "Failed to fetch updates - TelegramRetryAfter: Telegram server says - Flood control "
            "exceeded on method 'GetUpdates'. Retry in 5 seconds."
        ),
        args=(),
        exc_info=None,
    )

    assert TelegramErrorHandler._is_transient_polling_noise(record, record.getMessage()) is True


def test_telegram_error_handler_suppresses_getupdates_bad_gateway():
    record = logging.LogRecord(
        name="aiogram.dispatcher",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Failed to fetch updates - TelegramServerError: Telegram server says - Bad Gateway",
        args=(),
        exc_info=None,
    )

    assert TelegramErrorHandler._is_transient_polling_noise(record, record.getMessage()) is True


def test_sentry_before_send_drops_polling_conflict():
    event = {
        "logger": "aiogram.dispatcher",
        "message": CONFLICT_MESSAGE,
    }

    assert _before_send(event, {}) is None


def test_sentry_before_send_drops_getupdates_retry_after():
    event = {
        "logger": "aiogram.dispatcher",
        "message": (
            "Failed to fetch updates - TelegramRetryAfter: Telegram server says - Flood control "
            "exceeded on method 'GetUpdates'. Retry in 5 seconds."
        ),
    }

    assert _before_send(event, {}) is None


def test_sentry_before_send_drops_getupdates_bad_gateway():
    event = {
        "logger": "aiogram.dispatcher",
        "message": "Failed to fetch updates - TelegramServerError: Telegram server says - Bad Gateway",
    }

    assert _before_send(event, {}) is None


def test_sentry_before_send_keeps_non_conflict_events():
    event = {
        "logger": "app",
        "message": "Something failed",
        "extra": {"api_key": "secret-value"},
    }

    result = _before_send(event, {})

    assert result is not None
    assert result["extra"]["api_key"] == "[redacted]"
