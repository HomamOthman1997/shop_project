import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.getcwd())

import utils.financial_manager as financial_manager
from database.financial_ledger import _money, _money_decimal
from utils.financial_manager import FinancialManager


def test_money_decimal_quantizes_without_binary_drift():
    assert _money_decimal("1.005") == Decimal("1.01")
    assert _money(Decimal("0.335")) == 0.34


@pytest.mark.asyncio
async def test_financial_manager_preserves_decimal_inputs(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_process_core_purchase(**kwargs):
        captured.update(kwargs)
        return True, "OK", {}

    monkeypatch.setattr(financial_manager, "_process_core_purchase", fake_process_core_purchase)

    ok, message = await FinancialManager.process_core_purchase(
        user_id=1,
        order_id="ord-1",
        sale_price=Decimal("10.20"),
        cost_price=Decimal("10.00"),
        reseller_id=9,
    )

    assert ok is True
    assert message == "Success"
    assert captured["sale_price"] == Decimal("10.20")
    assert captured["cost_price"] == Decimal("10.00")
