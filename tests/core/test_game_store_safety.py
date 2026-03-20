import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.getcwd())

from handlers.store_sections import (
    _apply_markup_decimal,
    _poll_g2bulk_order_status,
    _provider_status_is_failure,
    _provider_status_is_success,
)


def test_apply_markup_decimal_rounds_safely():
    assert _apply_markup_decimal("10", "2") == Decimal("10.20")
    assert _apply_markup_decimal("0.87", "2") == Decimal("0.89")


def test_provider_status_helpers_are_conservative():
    assert _provider_status_is_success({"data": {"status": "completed"}}) is True
    assert _provider_status_is_failure({"data": {"status": "failed"}}) is True
    assert _provider_status_is_success({"data": {"status": "processing"}}) is False
    assert _provider_status_is_failure({"data": {"status": "processing"}}) is False


@pytest.mark.asyncio
async def test_poll_g2bulk_order_status_waits_for_final_success():
    class FakeClient:
        def __init__(self):
            self.responses = [
                {"status": 200, "data": {"status": "processing"}},
                {"status": 200, "data": {"status": "pending"}},
                {"status": 200, "data": {"status": "completed"}},
            ]

        async def get_order_status(self, _order_id):
            return self.responses.pop(0)

    resp = await _poll_g2bulk_order_status(FakeClient(), "123", attempts=3, delay_sec=0)
    assert resp == {"status": 200, "data": {"status": "completed"}}


@pytest.mark.asyncio
async def test_poll_g2bulk_order_status_stops_on_failure():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get_order_status(self, _order_id):
            self.calls += 1
            if self.calls == 1:
                return {"status": 200, "data": {"status": "pending"}}
            return {"status": 200, "data": {"status": "failed"}}

    client = FakeClient()
    resp = await _poll_g2bulk_order_status(client, "123", attempts=5, delay_sec=0)
    assert resp == {"status": 200, "data": {"status": "failed"}}
    assert client.calls == 2
