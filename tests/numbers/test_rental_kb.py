import os
import sys

sys.path.insert(0, os.getcwd())

from services.numbers.keyboards.core_numbers_kb import rental_providers_kb


def test_rental_providers_kb_uses_internal_provider_codes_for_layout():
    kb = rental_providers_kb(
        provider_rows=[
            {"provider": "smspool", "pricing_mode": "monthly", "avg_price": 10.0, "available_for_buy": True},
            {"provider": "textverified", "pricing_mode": "monthly", "avg_price": 11.0, "available_for_buy": True},
            {"provider": "pvadeals", "pricing_mode": "monthly", "avg_price": 12.0, "available_for_buy": True},
        ],
        lang="en",
        provider_options={
            "smspool": [
                {"provider": "smspool", "duration": 24, "price": 1.0},
                {"provider": "smspool", "duration": 168, "price": 2.0},
                {"provider": "smspool", "duration": 672, "price": 3.0},
                {"provider": "smspool", "duration": 720, "price": 4.0},
            ],
            "textverified": [
                {"provider": "textverified", "duration": 24, "price": 1.0},
                {"provider": "textverified", "duration": 72, "price": 2.0},
                {"provider": "textverified", "duration": 168, "price": 3.0},
                {"provider": "textverified", "duration": 336, "price": 4.0},
                {"provider": "textverified", "duration": 720, "price": 5.0},
            ],
            "pvadeals": [
                {"provider": "pvadeals", "duration": 72, "price": 6.0},
                {"provider": "pvadeals", "duration": 168, "price": 7.0},
                {"provider": "pvadeals", "duration": 336, "price": 8.0},
                {"provider": "pvadeals", "duration": 720, "price": 10.0},
            ],
        },
        usd_to_syp=0,
    )
    rows = [[button.text for button in row] for row in kb.inline_keyboard]
    assert rows[0] == ["Charlie"]
    assert rows[1] == ["1D | 1.00 💲", "7D | 2.00 💲", "28D | 3.00 💲"]
    assert rows[2] == ["Bravo"]
    assert rows[3] == ["1D | 1.00 💲", "3D | 2.00 💲", "7D | 3.00 💲"]
    assert rows[4] == ["14D | 4.00 💲", "30D | 5.00 💲"]
    assert rows[5] == ["Echo"]
    assert rows[6] == ["3D | 6.00 💲", "7D | 7.00 💲", "14D | 8.00 💲"]
    assert rows[7] == ["30D | 10.00 💲"]
    assert kb.inline_keyboard[0][0].style == "primary"
    assert kb.inline_keyboard[1][0].style is None
