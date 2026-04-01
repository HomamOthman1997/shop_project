import os
import sys

sys.path.insert(0, os.getcwd())

from services.numbers.keyboards.core_numbers_kb import provider_choice_kb
from utils.provider_alias import provider_display_name, provider_public_id


def test_provider_public_ids_shift_pvadeals_and_alisms():
    assert provider_public_id("pvadeals") == "S5"
    assert provider_public_id("alisms") == "S6"
    assert provider_display_name("pvadeals") == "Echo"
    assert provider_display_name("alisms") == "Foxtrot"


def test_provider_choice_kb_hides_smsman_lanes():
    kb = provider_choice_kb(
        {
            "herosms": {"price": 0.6, "api_service_name": "go", "available_for_buy": True},
            "smsman": {"price": 0.3, "api_service_name": "123", "available_for_buy": True},
            "smsman_s6": {"price": 0.4, "api_service_name": "124", "available_for_buy": True},
            "pvadeals": {
                "price": 1.0,
                "api_service_name": "abc",
                "available_for_buy": True,
                "provider_country_iso": "US",
            },
            "alisms": {
                "price": 0.1,
                "api_service_name": "go",
                "available_for_buy": True,
                "provider_country_iso": "CO",
            },
        },
        lang="en",
        usd_to_syp=0,
    )
    labels = [button.text for row in kb.inline_keyboard for button in row]
    joined = " | ".join(labels)
    assert any(label.startswith("Echo [US] |") for label in labels)
    assert "1.00 💲" in labels
    assert any(label.startswith("Foxtrot [CO] |") for label in labels)
    assert "0.10 💲" in labels
    assert "Golf" not in joined
    assert "Hotel" not in joined


def test_provider_choice_kb_prefers_state_tag_over_country():
    kb = provider_choice_kb(
        {
            "smspool": {
                "price": 0.13,
                "api_service_name": "tg",
                "available_for_buy": True,
                "provider_country_iso": "US",
                "provider_state_code": "CA",
            }
        },
        lang="en",
        usd_to_syp=0,
    )
    rows = [[button.text for button in row] for row in kb.inline_keyboard]
    assert rows[0] == [rows[0][0], "0.13 💲", "Buy"]
    assert rows[0][0].startswith("Charlie [CA] |")


def test_provider_choice_kb_shows_country_tag_when_available():
    kb = provider_choice_kb(
        {
            "herosms": {
                "price": 0.02,
                "api_service_name": "go",
                "available_for_buy": True,
                "provider_country_iso": "KE",
            }
        },
        lang="en",
        usd_to_syp=0,
    )
    rows = [[button.text for button in row] for row in kb.inline_keyboard]
    assert rows[0] == [rows[0][0], "0.02 💲", "Buy"]
    assert rows[0][0].startswith("Alpha [KE] |")


def test_provider_choice_kb_shows_us_tag_for_us_only_providers():
    kb = provider_choice_kb(
        {
            "textverified": {
                "price": 0.75,
                "api_service_name": "gmail",
                "available_for_buy": True,
                "provider_country_iso": "US",
            },
            "telabot": {
                "price": 0.45,
                "api_service_name": "gmail",
                "available_for_buy": True,
                "provider_country_iso": "US",
            },
        },
        lang="en",
        usd_to_syp=0,
    )
    rows = [[button.text for button in row] for row in kb.inline_keyboard]
    assert rows[0] == [rows[0][0], "0.75 💲", "Buy"]
    assert rows[1] == [rows[1][0], "0.45 💲", "Buy"]
    assert rows[0][0].startswith("Bravo [US] |")
    assert rows[1][0].startswith("Delta [US] |")


def test_provider_choice_kb_uses_read_only_info_buttons_and_name_only_primary_style():
    kb = provider_choice_kb(
        {
            "smspool": {
                "price": 0.13,
                "api_service_name": "tg",
                "available_for_buy": True,
                "provider_country_iso": "CO",
            }
        },
        lang="en",
        usd_to_syp=0,
    )
    first_row = kb.inline_keyboard[0]
    assert len(first_row) == 3
    assert [button.callback_data for button in first_row] == [
        "buy_provider_info:smspool",
        "buy_provider_info:smspool",
        "buy_provider:smspool",
    ]
    assert first_row[0].style == "primary"
    assert not hasattr(first_row[1], "style")
    assert not hasattr(first_row[2], "style")
