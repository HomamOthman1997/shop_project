import os
import sys

sys.path.insert(0, os.getcwd())

from services.numbers.handlers.core_numbers_buy import (
    _temp_code_notice_text,
    _temp_code_received_text,
)


def test_temp_code_received_text_hides_code_from_status_card():
    text = _temp_code_received_text(
        "ar",
        "265464",
        {
            "provider_number": "16812933224",
            "temp_country": "1",
            "temp_service_key": "paypal",
            "provider": "textverified",
            "temp_reuse_warranty_sec": 900,
        },
    )

    assert "265464" not in text
    assert "paypal" in text


def test_temp_code_notice_text_includes_code_and_balance_notice():
    text = _temp_code_notice_text("ar", code="265464", amount=0.50, balance=9.50)

    assert "265464" in text
    assert "💲 0.50" in text
    assert "💲 9.50" in text
    assert "الرصيد الحالي" in text
