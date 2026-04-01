from __future__ import annotations

import logging
import time


class TransientNetworkNoiseFilter(logging.Filter):
    """Rate-limit repetitive transient network outage logs."""

    def __init__(self, *, cooldown_sec: float = 45.0) -> None:
        super().__init__()
        self._cooldown_sec = max(1.0, float(cooldown_sec))
        self._last_seen: dict[str, float] = {}

    def _is_transient_network(self, record: logging.LogRecord, message: str) -> tuple[bool, str]:
        logger_name = str(record.name or "").lower()
        text = str(message or "").lower()

        if logger_name.startswith("aiogram.dispatcher"):
            if "telegramconflicterror" in text or "terminated by other getupdates request" in text:
                if "failed to fetch updates" in text:
                    return True, "aiogram:failed_fetch_updates:conflict"
                if "sleep for" in text and "try again" in text:
                    return True, "aiogram:failed_fetch_updates:conflict_backoff"
                return True, "aiogram:failed_fetch_updates:conflict_generic"
            if "failed to fetch updates" in text and (
                "telegramnetworkerror" in text
                or "cannot connect to host api.telegram.org" in text
                or "clientconnectorerror" in text
                or "clientoserror" in text
                or "server disconnected" in text
                or "network location cannot be reached" in text
                or "connection was aborted" in text
                or "semaphore timeout period has expired" in text
            ):
                return True, "aiogram:failed_fetch_updates:network"
            return False, ""

        if logger_name.startswith("urllib3.connectionpool"):
            if "ingest.de.sentry.io" in text and (
                "failed to resolve" in text
                or "nameresolutionerror" in text
                or "getaddrinfo failed" in text
            ):
                return True, "urllib3:sentry_dns_retry"
            return False, ""

        if logger_name in {"root", ""}:
            if "database query failed" in text and (
                "getaddrinfo failed" in text or "replicasetnoprimary" in text
            ):
                return True, "root:db_dns_failure"

        return False, ""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(getattr(record, "msg", "") or "")

        is_noise, key = self._is_transient_network(record, rendered)
        if not is_noise:
            return True

        now = time.monotonic()
        last = self._last_seen.get(key, 0.0)
        if now - last < self._cooldown_sec:
            return False
        self._last_seen[key] = now
        return True


def install_transient_noise_filter(handler: logging.Handler, *, cooldown_sec: float = 45.0) -> None:
    handler.addFilter(TransientNetworkNoiseFilter(cooldown_sec=cooldown_sec))
