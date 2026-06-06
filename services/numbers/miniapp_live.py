"""Process-local live update signals for the Numbers mini app."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import suppress
from typing import Any


_SUBSCRIBERS: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)


def subscribe_number_updates(user_id: int) -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=10)
    _SUBSCRIBERS[int(user_id)].add(queue)
    return queue


def unsubscribe_number_updates(user_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
    subscribers = _SUBSCRIBERS.get(int(user_id))
    if not subscribers:
        return
    subscribers.discard(queue)
    if not subscribers:
        _SUBSCRIBERS.pop(int(user_id), None)


async def publish_number_order_update(*, user_id: int, order_id: Any, reason: str) -> int:
    delivered = 0
    event = {
        "type": "order_changed",
        "order_id": str(order_id or ""),
        "reason": str(reason or ""),
    }
    for queue in tuple(_SUBSCRIBERS.get(int(user_id), ())):
        if queue.full():
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with suppress(asyncio.QueueFull):
            queue.put_nowait(event)
            delivered += 1
    return delivered
