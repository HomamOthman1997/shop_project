import os
import sys

sys.path.insert(0, os.getcwd())

from database.financial_ledger import _classify_ledger_reason


def test_classify_ledger_reason_core_purchase():
    category, tags = _classify_ledger_reason("purchase_core_user_debit")
    assert category == "core_purchase"
    assert "core" in tags
    assert "purchase" in tags


def test_classify_ledger_reason_manual_adjust():
    category, tags = _classify_ledger_reason("balance_adjust_set")
    assert category == "manual_adjustment"
    assert "manual" in tags
