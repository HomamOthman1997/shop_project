from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

import aiohttp

from database.webhooks_repo import (
    list_due_webhook_deliveries,
    mark_webhook_delivery_failure,
    mark_webhook_delivery_success,
)
from services.platform.webhooks import canonical_webhook_body, webhook_signature

WebhookPostFn = Callable[[str, bytes, dict[str, str], float], Awaitable[tuple[int, str]]]

DEFAULT_WEBHOOK_TIMEOUT_SEC = 8.0
DEFAULT_WEBHOOK_MAX_ATTEMPTS = 8


def webhook_retry_delay_seconds(attempts_before_current: int) -> int:
    return min(3600, 30 * (2 ** max(0, int(attempts_before_current))))


async def _post_with_aiohttp(url: str, body: bytes, headers: dict[str, str], timeout_sec: float) -> tuple[int, str]:
    timeout = aiohttp.ClientTimeout(total=float(timeout_sec))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        return await _post_with_session(session, url, body, headers)


async def _post_with_session(
    session: aiohttp.ClientSession,
    url: str,
    body: bytes,
    headers: dict[str, str],
) -> tuple[int, str]:
    async with session.post(url, data=body, headers=headers) as response:
        return int(response.status), await response.text()


async def deliver_webhook_once(
    delivery: dict[str, Any],
    *,
    post_fn: WebhookPostFn | None = None,
    timeout_sec: float = DEFAULT_WEBHOOK_TIMEOUT_SEC,
    max_attempts: int = DEFAULT_WEBHOOK_MAX_ATTEMPTS,
) -> dict[str, Any]:
    event = delivery.get("event") if isinstance(delivery.get("event"), dict) else {}
    url = str(delivery.get("url") or "").strip()
    secret = str(delivery.get("secret") or "")
    delivery_id = delivery.get("_id")
    attempts = int(delivery.get("attempts") or 0)
    body = canonical_webhook_body(event)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "PhantomApp-Webhooks/1.0",
        "X-Webhook-Event": str(event.get("type") or ""),
        "X-Webhook-Id": str(event.get("id") or ""),
        "X-Webhook-Signature": webhook_signature(secret, event),
    }
    sender = post_fn or _post_with_aiohttp

    try:
        status_code, response_text = await sender(url, body, headers, float(timeout_sec))
    except Exception as exc:
        terminal = attempts + 1 >= max(1, int(max_attempts))
        next_attempt_at = None if terminal else datetime.now(UTC) + timedelta(seconds=webhook_retry_delay_seconds(attempts))
        await mark_webhook_delivery_failure(
            delivery_id=delivery_id,
            status_code=None,
            response_text=str(exc),
            next_attempt_at=next_attempt_at,
            terminal=terminal,
        )
        return {"status": "failed" if terminal else "retry", "status_code": None, "error": str(exc)}

    if 200 <= int(status_code) <= 299:
        await mark_webhook_delivery_success(
            delivery_id=delivery_id,
            status_code=int(status_code),
            response_text=str(response_text or ""),
        )
        return {"status": "delivered", "status_code": int(status_code)}

    terminal = attempts + 1 >= max(1, int(max_attempts))
    next_attempt_at = None if terminal else datetime.now(UTC) + timedelta(seconds=webhook_retry_delay_seconds(attempts))
    await mark_webhook_delivery_failure(
        delivery_id=delivery_id,
        status_code=int(status_code),
        response_text=str(response_text or ""),
        next_attempt_at=next_attempt_at,
        terminal=terminal,
    )
    return {"status": "failed" if terminal else "retry", "status_code": int(status_code)}


async def run_webhook_delivery_sweep(
    *,
    limit: int = 100,
    post_fn: WebhookPostFn | None = None,
    timeout_sec: float = DEFAULT_WEBHOOK_TIMEOUT_SEC,
    max_attempts: int = DEFAULT_WEBHOOK_MAX_ATTEMPTS,
) -> dict[str, int]:
    deliveries = await list_due_webhook_deliveries(now=datetime.now(UTC), limit=max(1, int(limit)))
    stats = {"checked": len(deliveries), "delivered": 0, "retry": 0, "failed": 0}
    if not deliveries:
        return stats
    sender = post_fn
    session: aiohttp.ClientSession | None = None
    if sender is None:
        timeout = aiohttp.ClientTimeout(total=float(timeout_sec))
        session = aiohttp.ClientSession(timeout=timeout)

        async def sender(url: str, body: bytes, headers: dict[str, str], timeout_sec: float) -> tuple[int, str]:
            return await _post_with_session(session, url, body, headers)

    try:
        for delivery in deliveries:
            result = await deliver_webhook_once(
                delivery,
                post_fn=sender,
                timeout_sec=float(timeout_sec),
                max_attempts=int(max_attempts),
            )
            status = str(result.get("status") or "")
            if status == "delivered":
                stats["delivered"] += 1
            elif status == "failed":
                stats["failed"] += 1
            else:
                stats["retry"] += 1
    finally:
        if session is not None:
            await session.close()
    return stats
