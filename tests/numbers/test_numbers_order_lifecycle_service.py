from datetime import UTC, datetime

import pytest

from services.numbers import order_lifecycle_service as lifecycle


@pytest.mark.asyncio
async def test_order_provisioning_transaction_charges_then_provisions():
    calls = []

    async def fake_charge_fn(**kwargs):
        calls.append(("charge", kwargs["order_id"]))

    async def fake_provision():
        calls.append(("provision", "ok"))
        return {"provider_order_id": "p-1"}

    result = await lifecycle.execute_order_provisioning_transaction(
        order={"_id": "order-1"},
        order_id="order-1",
        user_id=123,
        reseller_id=456,
        final_price=1.25,
        cost_price=1.0,
        lang="en",
        number_mode="temp",
        source="numbers_api",
        provision_fn=fake_provision,
        unexpected_failure_message="failed",
        charge_fn=fake_charge_fn,
    )

    assert result == {"provider_order_id": "p-1"}
    assert calls == [("charge", "order-1"), ("provision", "ok")]


@pytest.mark.asyncio
async def test_order_provisioning_transaction_stops_on_charge_failure():
    async def fake_charge_fn(**kwargs):
        raise lifecycle.OrderChargeError("insufficient_balance", "Not enough balance.")

    async def fake_provision():
        raise AssertionError("provider should not be called after charge failure")

    with pytest.raises(lifecycle.OrderChargeError) as exc:
        await lifecycle.execute_order_provisioning_transaction(
            order={"_id": "order-1"},
            order_id="order-1",
            user_id=123,
            reseller_id=456,
            final_price=1.25,
            cost_price=1.0,
            lang="en",
            number_mode="temp",
            source="numbers_api",
            provision_fn=fake_provision,
            unexpected_failure_message="failed",
            charge_fn=fake_charge_fn,
        )

    assert exc.value.code == "insufficient_balance"


@pytest.mark.asyncio
async def test_order_provisioning_transaction_does_not_double_refund_expected_provider_failure(monkeypatch):
    calls = {}

    async def fake_charge_fn(**kwargs):
        calls["charge"] = True

    async def fake_refund_core_purchase(cls, *args, **kwargs):
        calls["refund"] = True
        return True, "ok"

    async def fake_provision():
        raise lifecycle.ProviderProvisioningError("provider_empty", refund_ok=True, raw="provider_empty")

    monkeypatch.setattr(lifecycle.FinancialManager, "refund_core_purchase", classmethod(fake_refund_core_purchase))

    with pytest.raises(lifecycle.ProviderProvisioningError) as exc:
        await lifecycle.execute_order_provisioning_transaction(
            order={"_id": "order-1"},
            order_id="order-1",
            user_id=123,
            reseller_id=456,
            final_price=1.25,
            cost_price=1.0,
            lang="en",
            number_mode="temp",
            source="numbers_api",
            provision_fn=fake_provision,
            unexpected_failure_message="failed",
            charge_fn=fake_charge_fn,
        )

    assert exc.value.refund_ok is True
    assert calls == {"charge": True}


@pytest.mark.asyncio
async def test_order_provisioning_transaction_rolls_back_unexpected_provider_exception(monkeypatch):
    calls = {}
    now = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)

    async def fake_charge_fn(**kwargs):
        calls["charge"] = kwargs

    async def fake_refund_core_purchase(cls, user_id, order_id, sale_price, cost_price, reseller_id=None):
        calls["refund"] = (user_id, order_id, sale_price, cost_price, reseller_id)
        return True, "ok"

    async def fake_update_order_status(order_id, status):
        calls["status"] = (order_id, status)

    async def fake_update_order_details(order_id, patch):
        calls["details"] = (order_id, patch)

    async def fake_provision():
        raise RuntimeError("database write failed after provider call")

    monkeypatch.setattr(lifecycle.FinancialManager, "refund_core_purchase", classmethod(fake_refund_core_purchase))
    monkeypatch.setattr(lifecycle, "update_order_status", fake_update_order_status)
    monkeypatch.setattr(lifecycle, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(lifecycle, "_utc_now", lambda: now)

    with pytest.raises(lifecycle.UnexpectedProvisioningError) as exc:
        await lifecycle.execute_order_provisioning_transaction(
            order={"_id": "order-1"},
            order_id="order-1",
            user_id=123,
            reseller_id=456,
            final_price=1.25,
            cost_price=1.0,
            lang="en",
            number_mode="temp",
            source="numbers_api",
            provision_fn=fake_provision,
            unexpected_failure_message="Provider could not reserve the number. Your balance was refunded.",
            charge_fn=fake_charge_fn,
        )

    assert exc.value.public_message == "Provider could not reserve the number. Your balance was refunded."
    assert calls["refund"] == (123, "order-1", 1.25, 1.0, 456)
    assert calls["status"] == ("order-1", "refunded")
    assert calls["details"] == (
        "order-1",
        {"provisioning_state": "provider_failed_refunded", "provisioning_failure_at": now},
    )
