from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from database.webhooks_repo import active_webhooks_for_event, enqueue_webhook_delivery


def canonical_webhook_body(event: dict[str, Any]) -> bytes:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def webhook_signature(secret: str, event: dict[str, Any]) -> str:
    digest = hmac.new(str(secret or "").encode("utf-8"), canonical_webhook_body(event), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def enqueue_event_for_user(
    *,
    user_id: int,
    reseller_id: int,
    event_type: str,
    data: dict[str, Any],
) -> dict[str, int]:
    event = {
        "id": _event_id(event_type=event_type, user_id=user_id, data=data),
        "type": str(event_type or "").strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "data": data,
    }
    hooks = await active_webhooks_for_event(user_id=int(user_id), reseller_id=int(reseller_id), event_type=event_type)
    queued = 0
    for hook in hooks:
        await enqueue_webhook_delivery(webhook=hook, event=event)
        queued += 1
    return {"matched": len(hooks), "queued": queued}


def _event_id(*, event_type: str, user_id: int, data: dict[str, Any]) -> str:
    raw = canonical_webhook_body({"type": event_type, "user_id": user_id, "data": data})
    return hashlib.sha256(raw).hexdigest()[:32]
