import os
import sys

sys.path.insert(0, os.getcwd())

from services.numbers.handlers.core_numbers_buy import (
    _temp_code_notice_text,
    _temp_code_received_text,
)
from services.numbers.handlers.temp_order_utils import _temp_waiting_text


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


def test_temp_waiting_text_marks_resend_window_expired():
    text = _temp_waiting_text(
        lang="en",
        provider_code="textverified",
        number="+15550001111",
        country_code="1",
        interval_sec=30,
        elapsed_sec=901,
        reuse_warranty_sec=900,
        service_name="gmail",
    )

    assert "guaranteed resend period ended" in text
    assert "Resend is guaranteed for the first 15 minutes" not in text
