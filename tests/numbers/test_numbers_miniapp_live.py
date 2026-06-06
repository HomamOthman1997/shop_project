import pytest

from services.numbers.miniapp_live import (
    publish_number_order_update,
    subscribe_number_updates,
    unsubscribe_number_updates,
)


@pytest.mark.asyncio
async def test_publish_number_order_update_notifies_subscribed_user_only():
    user_queue = subscribe_number_updates(123)
    other_queue = subscribe_number_updates(456)
    try:
        delivered = await publish_number_order_update(
            user_id=123,
            order_id="order-1",
            reason="provider_webhook_code_received",
        )

        assert delivered == 1
        assert user_queue.get_nowait() == {
            "type": "order_changed",
            "order_id": "order-1",
            "reason": "provider_webhook_code_received",
        }
        assert other_queue.empty()
    finally:
        unsubscribe_number_updates(123, user_queue)
        unsubscribe_number_updates(456, other_queue)
