import os
import sys

sys.path.insert(0, os.getcwd())

from services.numbers.keyboards.core_numbers_kb import provider_choice_kb
from utils.provider_alias import provider_display_name, provider_public_id
from utils.user_money import format_usd


def _provider_rows(kb):
    return [
        row
        for row in kb.inline_keyboard
        if len(row) == 2 and str(getattr(row[0], "callback_data", "") or "").startswith("buy_provider_info:")
    ]


def test_provider_public_ids_shift_pvadeals_and_vaksms():
    assert provider_public_id("pvadeals") == "S5"
    assert provider_public_id("vaksms") == "S6"
    assert provider_display_name("pvadeals") == "Echo"
    assert provider_display_name("vaksms") == "Foxtrot"


def test_smsman_display_name_tracks_nonvoip_brand():
    assert provider_public_id("smsman") == "S7"
    assert provider_public_id("smsman_s6") == "S8"
    assert provider_display_name("smsman") == "NonVoIP"
    assert provider_display_name("smsman_s6") == "NonVoIP"


def test_new_provider_display_names_are_obfuscated():
    assert provider_public_id("smsready") == "S9"
    assert provider_public_id("pvapins") == "S10"
    assert provider_display_name("smsready") == "Golf"
    assert provider_display_name("pvapins") == "Hotel"


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
            "vaksms": {
                "price": 0.1,
                "api_service_name": "go",
                "available_for_buy": True,
                "provider_country_iso": "CO",
            },
        },
        lang="en",
        usd_to_syp=0,
        show_all=True,
    )
    labels = [button.text for row in kb.inline_keyboard for button in row]
    joined = " | ".join(labels)
    assert any(label.startswith("Echo [US] |") for label in labels)
    assert f"Buy | {format_usd(1.0)}" in labels
    assert any(label.startswith("Foxtrot [CO] |") for label in labels)


def test_provider_choice_kb_does_not_recommend_blocked_provider():
    kb = provider_choice_kb(
        {
            "vaksms": {
                "price": 0.11,
                "api_service_name": "wa",
                "available_for_buy": True,
                "provider_country_iso": "ID",
                "recommendation_blocked": True,
            },
            "textverified": {
                "price": 1.65,
                "api_service_name": "whatsapp",
                "available_for_buy": True,
                "provider_country_iso": "US",
            },
        },
        lang="en",
    )
    labels = [[button.text for button in row] for row in kb.inline_keyboard]
    assert labels[0][0].startswith("Best option |")
    assert "1.65" in labels[0][0]


def test_provider_choice_kb_show_all_hides_low_balance_providers():
    kb = provider_choice_kb(
        {
            "herosms": {
                "price": 0.44,
                "api_service_name": "go",
                "available_for_buy": False,
                "testing_visible": True,
                "provider_reason": "provider_balance_low",
            },
            "telabot": {
                "price": 0.385,
                "api_service_name": "GMail",
                "available_for_buy": False,
                "testing_visible": True,
                "provider_reason": "provider_balance_low",
                "provider_country_iso": "US",
            },
            "textverified": {
                "price": 0.825,
                "api_service_name": "gmail",
                "available_for_buy": True,
                "provider_country_iso": "US",
            },
        },
        lang="en",
        show_all=True,
    )
    rows = _provider_rows(kb)
    labels = [[button.text for button in row] for row in rows]
    assert not any(row[0].startswith("Alpha |") for row in labels)
    assert not any(row[0].startswith("Delta [US] |") for row in labels)
    assert any(row[0].startswith("Bravo [US] |") for row in labels)


def test_provider_choice_kb_compact_hides_show_all_when_only_low_balance_extra():
    kb = provider_choice_kb(
        {
            "textverified": {
                "price": 0.82,
                "api_service_name": "gmail",
                "available_for_buy": True,
                "provider_country_iso": "US",
            },
            "herosms": {
                "price": 0.70,
                "api_service_name": "gmail",
                "available_for_buy": False,
                "testing_visible": True,
                "provider_reason": "provider_balance_low",
            },
        },
        lang="en",
        show_all=False,
    )

    callbacks = [button.callback_data for row in kb.inline_keyboard for button in row]
    assert callbacks[:1] == ["buy_provider:textverified"]
    assert "buy_provider_show_all" not in callbacks


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
        show_all=True,
    )
    rows = [[button.text for button in row] for row in kb.inline_keyboard]
    provider_rows = [[button.text for button in row] for row in _provider_rows(kb)]
    assert rows[0] == [f"Best option | {format_usd(0.13)}"]
    assert provider_rows[0] == [provider_rows[0][0], f"Buy | {format_usd(0.13)}"]
    assert provider_rows[0][0].startswith("Charlie [CA] |")


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
        show_all=True,
    )
    rows = [[button.text for button in row] for row in kb.inline_keyboard]
    provider_rows = [[button.text for button in row] for row in _provider_rows(kb)]
    assert rows[0] == [f"Best option | {format_usd(0.02)}"]
    assert provider_rows[0] == [provider_rows[0][0], f"Buy | {format_usd(0.02)}"]
    assert provider_rows[0][0].startswith("Alpha [KE] |")


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
        show_all=True,
    )
    rows = [[button.text for button in row] for row in kb.inline_keyboard]
    provider_rows = [[button.text for button in row] for row in _provider_rows(kb)]
    assert rows[0] == [f"Best option | {format_usd(0.45)}"]
    assert provider_rows[0] == [provider_rows[0][0], f"Buy | {format_usd(0.75)}"]
    assert provider_rows[1] == [provider_rows[1][0], f"Buy | {format_usd(0.45)}"]
    assert provider_rows[0][0].startswith("Bravo [US] |")
    assert provider_rows[1][0].startswith("Delta [US] |")


def test_provider_choice_kb_uses_info_button_and_buy_action_button():
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
        show_all=True,
    )
    assert kb.inline_keyboard[0][0].callback_data == "buy_provider:smspool"
    first_row = _provider_rows(kb)[0]
    assert len(first_row) == 2
    assert [button.callback_data for button in first_row] == [
        "buy_provider_info:smspool",
        "buy_provider:smspool",
    ]
    assert first_row[0].style == "primary"
    assert getattr(first_row[1], "style", None) is None


def test_provider_choice_kb_initial_view_is_compact():
    kb = provider_choice_kb(
        {
            "herosms": {"price": 0.5, "api_service_name": "wa", "available_for_buy": True},
            "telabot": {"price": 0.7, "api_service_name": "wa", "available_for_buy": True},
        },
        lang="en",
        usd_to_syp=0,
    )

    callbacks = [button.callback_data for row in kb.inline_keyboard for button in row]
    assert callbacks[:2] == ["buy_provider:herosms", "buy_provider_show_all"]
    assert not any(str(value or "").startswith("buy_provider_info:") for value in callbacks)


def test_provider_choice_kb_prefers_proven_success_over_small_savings():
    kb = provider_choice_kb(
        {
            "herosms": {
                "price": 0.50,
                "api_service_name": "wa",
                "available_for_buy": True,
                "recommended_success_rate": 96,
                "success_attempts": 14,
            },
            "telabot": {
                "price": 0.45,
                "api_service_name": "wa",
                "available_for_buy": True,
                "recommended_success_rate": 70,
                "success_attempts": 12,
            },
        },
        lang="en",
        usd_to_syp=0,
    )

    assert kb.inline_keyboard[0][0].callback_data == "buy_provider:herosms"


def test_provider_choice_kb_uses_context_success_for_best_option():
    kb = provider_choice_kb(
        {
            "herosms": {
                "price": 0.60,
                "api_service_name": "wa",
                "available_for_buy": True,
                "success_rate": 99,
                "success_attempts": 20,
                "recommended_success_rate": 58,
                "context_success_attempts": 5,
            },
            "telabot": {
                "price": 0.62,
                "api_service_name": "wa",
                "available_for_buy": True,
                "success_rate": 80,
                "success_attempts": 20,
                "recommended_success_rate": 92,
                "context_success_attempts": 5,
            },
        },
        lang="en",
        usd_to_syp=0,
    )

    assert kb.inline_keyboard[0][0].callback_data == "buy_provider:telabot"
