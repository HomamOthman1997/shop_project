import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services.numbers import miniapp


def test_numbers_miniapp_does_not_import_telegram_handler_helpers_directly():
    source = Path(miniapp.__file__).read_text(encoding="utf-8")

    assert "services.numbers.handlers" not in source


def test_numbers_bootstrap_payload_has_core_filters():
    miniapp._BOOTSTRAP_CACHE["data"] = None

    payload = miniapp._bootstrap_payload()

    assert payload["defaults"] == {"mode": "temp", "service": "", "country": "none", "state": "none"}
    assert [item["key"] for item in payload["modes"]] == ["temp", "rental", "voice"]
    us_country = next(item for item in payload["countries"] if item["code"] == "1")
    any_state = next(item for item in payload["states_us"] if item["code"] == "none")
    assert "usa" in {str(alias).lower() for alias in us_country["aliases"]}
    assert "any" in {str(alias).lower() for alias in any_state["aliases"]}
    assert any(item["key"] == "telegram" for item in payload["services"])


@pytest.mark.asyncio
async def test_numbers_country_suggestions_rank_available_prices(monkeypatch):
    miniapp._CHEAP_COUNTRY_CACHE.clear()
    calls = []

    async def fake_get_all_prices(service, country, state, *, ignore_balance=False, with_success_rates=True):
        calls.append((service, country, state, ignore_balance, with_success_rates))
        prices = {"1": 0.44, "2": 0.22, "24": 0.33}
        price = prices.get(str(country))
        if price is None:
            return {}
        return {"textverified": {"price": price, "base_price": price - 0.01}}

    monkeypatch.setattr(miniapp, "get_all_prices", fake_get_all_prices)

    rows = await miniapp._country_suggestions_for_service("temp", "gmail", limit=3)

    assert [row["code"] for row in rows] == ["1", "2", "24"]
    assert rows[0]["price_label"] == "$0.44"
    assert calls
    assert all(call[3] is True and call[4] is False for call in calls)


@pytest.mark.asyncio
async def test_numbers_country_suggestions_endpoint(monkeypatch):
    async def fake_suggestions(mode, service, limit=10):
        return [{"code": "44", "name": "United Kingdom", "price": 0.22, "price_label": "$0.22"}]

    monkeypatch.setattr(miniapp, "_country_suggestions_for_service", fake_suggestions)
    request = make_mocked_request("GET", "/mini/numbers/api/country-suggestions?mode=temp&service=gmail")

    response = await miniapp.country_suggestions(request)
    payload = json.loads(response.text)

    assert payload["ok"] is True
    assert payload["mode"] == "temp"
    assert payload["service"] == "gmail"
    assert payload["countries"][0]["price_label"] == "$0.22"


def test_numbers_price_rows_use_public_provider_ids(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "numbers_success_rate_display_min_attempts", 1, raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "alpha_provider": {
                "price": 1.25,
                "base_price": 1.0,
                "api_service_name": "telegram",
                "success_rate": 88,
                "success_attempts": 10,
                "recommended_success_rate": 92,
                "context_success_attempts": 5,
                "provider_state_code": "CA",
            },
            "beta_provider": {
                "price": 0,
                "available_for_buy": False,
                "provider_reason": "provider_balance_low",
                "success_attempts": 0,
            },
        },
        "temp",
        service="telegram",
        country="none",
        state="none",
    )

    assert rows[0]["provider_id"].startswith("S")
    assert rows[0]["price_label"] == "$1.25"
    assert rows[0]["success_rate"] == "92%"
    assert rows[0]["success_attempts"] == 10
    assert rows[0]["location_tag"] == "CA"
    assert len(rows) == 1
    assert rows[0]["available"] is True
    assert rows[0]["recommended"] is True


@pytest.mark.asyncio
async def test_numbers_prices_endpoint_skips_blocking_success_rates(monkeypatch):
    calls = {}

    async def fake_get_all_prices(service, country, state, with_success_rates=True, provider_codes=None):
        calls["service"] = service
        calls["country"] = country
        calls["state"] = state
        calls["with_success_rates"] = with_success_rates
        calls["provider_codes"] = tuple(provider_codes or ())
        return {
            "textverified": {
                "price": 0.44,
                "base_price": 0.4,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "recommended_success_rate": 91,
                "success_attempts": 5,
            }
        }

    monkeypatch.setattr(miniapp, "get_all_prices", fake_get_all_prices)
    request = make_mocked_request("GET", "/mini/numbers/api/prices?mode=temp&service=telegram&country=1&state=none")

    response = await miniapp.prices(request)
    payload = json.loads(response.text)

    assert calls == {
        "service": "telegram",
        "country": "1",
        "state": "none",
        "with_success_rates": False,
        "provider_codes": miniapp._TEMP_PRICE_SCREEN_PROVIDER_CODES,
    }
    assert payload["providers"][0]["success_rate"] == "91%"


def test_numbers_account_activity_payload_formats_ledger_rows():
    created_at = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    rows = miniapp._ledger_activity_payload(
        [
            {
                "_id": "tx-1",
                "direction": "debit",
                "amount": -0.44,
                "reason": "purchase_core_user_debit",
                "category": "core_purchase",
                "balance_after": 1.56,
                "created_at": created_at,
                "order_id": "order-1",
            },
            {
                "_id": "tx-2",
                "direction": "credit",
                "amount": 0.44,
                "reason": "refund_core_user_credit",
                "category": "core_refund",
                "balance_after": 2.0,
                "created_at": created_at,
                "order_id": "order-1",
            },
        ],
        "en",
    )

    assert rows[0]["label"] == "Numbers purchase"
    assert rows[0]["amount_label"] == "-$0.44"
    assert rows[0]["balance_label"] == "$1.56"
    assert rows[1]["label"] == "Numbers refund"
    assert rows[1]["amount_label"] == "+$0.44"


def test_numbers_account_activity_payload_includes_order_subject():
    created_at = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)

    rows = miniapp._ledger_activity_payload(
        [
            {
                "_id": "tx-1",
                "direction": "debit",
                "amount": -0.44,
                "reason": "purchase_core_user_debit",
                "category": "core_purchase",
                "balance_after": 1.56,
                "created_at": created_at,
                "order_id": "order-1",
            },
        ],
        "en",
        {
            "order-1": {
                "number_mode": "voice",
                "temp_service_key": "telegram",
                "provider_number": "+15551234567",
            }
        },
    )

    assert rows[0]["subject"] == "Telegram call · +15551234567"
    assert rows[0]["label"] == "Numbers purchase · Telegram call · +15551234567"


def test_numbers_account_activity_payload_uses_metadata_subject_without_order():
    created_at = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)

    rows = miniapp._ledger_activity_payload(
        [
            {
                "_id": "tx-1",
                "direction": "credit",
                "amount": 5,
                "reason": "recharge_request_accepted",
                "category": "recharge_credit",
                "balance_after": 10,
                "created_at": created_at,
                "order_id": "",
                "metadata": {"bot_username": "PHANTOM_OTP_NUMBERS_BOT"},
            },
            {
                "_id": "tx-2",
                "direction": "debit",
                "amount": -1.25,
                "reason": "purchase_core_user_debit",
                "category": "core_purchase",
                "balance_after": 8.75,
                "created_at": created_at,
                "order_id": "",
                "metadata": {"service_label": "Telegram"},
            },
        ],
        "en",
    )

    assert rows[0]["label"] == "Balance recharge · @PHANTOM_OTP_NUMBERS_BOT"
    assert rows[0]["subject"] == "@PHANTOM_OTP_NUMBERS_BOT"
    assert rows[1]["label"] == "Numbers purchase · Telegram"


def test_numbers_temp_rows_include_signed_quote_and_hide_internal_lanes(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "bot_numbers_token", "numbers-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "bot_main_token", "main-token", raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "textverified": {
                "price": 0.5,
                "base_price": 0.4,
                "api_service_name": "attapoll",
                "available_for_buy": True,
            },
            "smsman": {
                "price": 0.3,
                "base_price": 0.25,
                "api_service_name": "1230",
                "available_for_buy": True,
            },
        },
        "temp",
        service="attapoll",
        country="1",
        state="none",
    )

    assert [row["provider_id"] for row in rows] == ["S2"]
    quote = miniapp._verify_quote_token(rows[0]["quote_token"])
    assert quote["service"] == "attapoll"
    assert quote["provider"] == "textverified"


def test_numbers_rental_options_include_signed_quotes(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "bot_numbers_token", "numbers-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "bot_main_token", "main-token", raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "herosms": {
                "available_for_buy": True,
                "api_service_name": "go",
                "options": [
                    {"duration": 2, "duration_label": "2h", "price": 0.55, "base_price": 0.5},
                ],
            }
        },
        "rental",
        service="google",
        country="1",
    )

    option = rows[0]["options"][0]
    assert option["duration_label"] == "2h"
    quote = miniapp._verify_quote_token(option["quote_token"])
    assert quote["mode"] == "rental"
    assert quote["service"] == "google"
    assert quote["provider"] == "herosms"


def test_numbers_rental_textverified_options_use_selected_state(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "bot_numbers_token", "numbers-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "bot_main_token", "main-token", raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "textverified": {
                "available_for_buy": True,
                "api_service_name": "Telegram",
                "options": [
                    {
                        "duration": 24,
                        "duration_label": "1d",
                        "price": 1.5,
                        "tv_duration_key": "P1D",
                        "tv_is_renewable": True,
                    },
                ],
            }
        },
        "rental",
        service="telegram",
        country="1",
        state="CA",
    )

    option = rows[0]["options"][0]
    assert option["with_state"] is True
    assert option["state_code"] == "CA"
    assert option["renewable"] is True
    assert option["price"] == 3.5
    quote = miniapp._verify_quote_token(option["quote_token"])
    assert quote["state"] == "CA"
    assert quote["option_key"][4] == "ca"


@pytest.mark.asyncio
async def test_numbers_rental_quote_resolves_textverified_state_option(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "bot_numbers_token", "numbers-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "bot_main_token", "main-token", raising=False)

    raw_prices = {
        "textverified": {
            "available_for_buy": True,
            "api_service_name": "Telegram",
            "options": [
                {
                    "duration": 24,
                    "duration_label": "1d",
                    "price": 1.5,
                    "tv_duration_key": "P1D",
                    "tv_is_renewable": False,
                },
            ],
        }
    }

    rows = miniapp._normalize_provider_rows(raw_prices, "rental", service="telegram", country="1", state="NY")

    async def fake_get_all_rental_prices(service, country, with_success_rates=False):
        assert service == "telegram"
        assert country == "1"
        assert with_success_rates is False
        return raw_prices

    monkeypatch.setattr(miniapp, "get_all_rental_prices", fake_get_all_rental_prices)

    offer = await miniapp._resolve_rental_offer_from_quote(rows[0]["options"][0]["quote_token"])

    assert offer["provider_code"] == "textverified"
    assert offer["option"]["tv_with_state"] is True
    assert offer["option"]["state_code"] == "NY"
    assert offer["option"]["price"] == 3.5


def test_numbers_voice_rows_include_signed_quote(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "bot_numbers_token", "numbers-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "bot_main_token", "main-token", raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "textverified": {
                "price": 0.44,
                "base_price": 0.4,
                "api_service_name": "attapoll",
                "available_for_buy": True,
                "voice_capable": True,
            }
        },
        "voice",
        service="attapoll",
        country="1",
        state="none",
    )

    assert rows[0]["quote_token"]
    quote = miniapp._verify_quote_token(rows[0]["quote_token"])
    assert quote["mode"] == "voice"
    assert quote["service"] == "attapoll"
    assert quote["country"] == "1"
    assert quote["state"] == "none"


def test_numbers_price_rows_mark_best_choice_and_hide_unavailable(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "bot_numbers_token", "numbers-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "bot_main_token", "main-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "numbers_success_rate_display_min_attempts", 1, raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "herosms": {
                "price": 0.1,
                "base_price": 0.08,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "success_rate": 50,
                "success_attempts": 20,
            },
            "textverified": {
                "price": 0.11,
                "base_price": 0.09,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "success_rate": 99,
                "success_attempts": 20,
            },
            "down": {
                "price": 0.09,
                "api_service_name": "telegram",
                "available_for_buy": False,
                "provider_reason": "provider_balance_low",
            },
        },
        "temp",
        service="telegram",
        country="none",
        state="none",
    )

    assert [row["provider_id"] for row in rows] == ["S2", "S1"]
    assert rows[0]["recommended"] is True
    assert all(row["available"] for row in rows)
    assert all("reason" not in row for row in rows)
    assert all("base_price_label" not in row for row in rows)


def test_numbers_provider_debug_rows_explain_hidden_providers(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "numbers_success_rate_display_min_attempts", 1, raising=False)

    rows = miniapp._provider_debug_rows(
        {
            "smsman": {
                "price": 0.3,
                "api_service_name": "1230",
                "available_for_buy": True,
                "success_rate": 75,
                "success_attempts": 6,
            },
            "down": {
                "price": 0.09,
                "api_service_name": "telegram",
                "available_for_buy": False,
                "provider_reason": "provider_balance_low",
            },
        },
        "temp",
    )

    by_code = {row["provider_code"]: row for row in rows}
    assert by_code["smsman"]["visible"] is False
    assert by_code["smsman"]["reason"] == "hidden_provider"
    assert by_code["down"]["visible"] is False
    assert by_code["down"]["reason"] == "provider_balance_low"


@pytest.mark.asyncio
async def test_numbers_voice_prices_fallback_to_generic_route(monkeypatch):
    calls = []

    async def fake_get_all_voice_prices(service, country, state, *, ignore_balance=False):
        calls.append((service, country, state, ignore_balance))
        if service == "telegram":
            return {"textverified": {"available_for_buy": False, "provider_reason": "service_not_supported"}}
        if service == miniapp._VOICE_GENERIC_SERVICE:
            return {
                "textverified": {
                    "price": 0.5,
                    "base_price": 0.4,
                    "api_service_name": miniapp._VOICE_GENERIC_SERVICE,
                    "available_for_buy": True,
                    "voice_capable": True,
                }
            }
        return {}

    monkeypatch.setattr(miniapp, "get_all_voice_prices", fake_get_all_voice_prices)

    rows = await miniapp._get_miniapp_voice_prices("telegram", "1", "none")

    assert rows["textverified"]["api_service_name"] == miniapp._VOICE_GENERIC_SERVICE
    assert rows["textverified"]["voice_fallback_service"] is True
    assert calls[0] == ("telegram", "1", "none", False)
    assert calls[1] == (miniapp._VOICE_GENERIC_SERVICE, "1", "none", False)


@pytest.mark.asyncio
async def test_numbers_voice_prices_endpoint_ignores_provider_balance_like_bot(monkeypatch):
    calls = {}

    async def fake_get_miniapp_voice_prices(service, country, state, *, ignore_balance=False):
        calls["service"] = service
        calls["country"] = country
        calls["state"] = state
        calls["ignore_balance"] = ignore_balance
        return {
            "textverified": {
                "price": 0.55,
                "base_price": 0.5,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "voice_capable": True,
            }
        }

    monkeypatch.setattr(miniapp, "_get_miniapp_voice_prices", fake_get_miniapp_voice_prices)
    request = make_mocked_request("GET", "/mini/numbers/api/prices?mode=voice&service=telegram&country=none&state=CA")

    response = await miniapp.prices(request)
    payload = json.loads(response.text)

    assert calls == {"service": "telegram", "country": "1", "state": "CA", "ignore_balance": True}
    assert payload["providers"][0]["quote_token"]


def test_numbers_voice_rows_preserve_selected_state_in_quote(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "bot_numbers_token", "numbers-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "bot_main_token", "main-token", raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "textverified": {
                "price": 0.44,
                "base_price": 0.4,
                "api_service_name": "attapoll",
                "available_for_buy": True,
                "voice_capable": True,
            }
        },
        "voice",
        service="attapoll",
        country="1",
        state="NY",
    )

    quote = miniapp._verify_quote_token(rows[0]["quote_token"])

    assert quote["mode"] == "voice"
    assert quote["state"] == "NY"


def test_numbers_voice_order_payload_exposes_recording_download():
    payload = miniapp._order_payload(
        {
            "_id": "voice-order-id",
            "number_mode": "voice",
            "status": "success",
            "temp_wait_state": "call_received",
            "provider": "textverified",
            "provider_number": "+15551234567",
            "temp_service_key": "attapoll",
            "temp_country": "1",
            "selling_price": 0.44,
            "base_price": 0.4,
            "voice_recording_uri": "https://example.test/recording.wav",
            "voice_calls": [{"recordingUri": "https://example.test/recording.wav"}],
        }
    )

    assert payload["mode"] == "voice"
    assert payload["public_status"] == "call_received"
    assert payload["recording_available"] is True
    assert payload["recording_url"] == "/mini/numbers/api/orders/voice-order-id/recording"


def test_numbers_order_event_payload_is_customer_safe():
    payload = miniapp._event_payload(
        {
            "event": "provider_cancel_failed",
            "created_at": datetime(2026, 5, 21, 12, 30, tzinfo=UTC),
            "payload": {"raw": "internal provider error"},
        },
        "en",
    )

    assert payload == {
        "event": "provider_cancel_failed",
        "label": "Provider refund is retrying",
        "time": "2026-05-21 12:30 UTC",
    }


def test_numbers_temp_order_payload_exposes_second_code_action():
    created_at = datetime.now(UTC) - timedelta(minutes=2)
    reuse_until = created_at + timedelta(minutes=10)
    payload = miniapp._order_payload(
        {
            "_id": "temp-order-id",
            "number_mode": "temp",
            "status": "success",
            "provisioning_state": "provisioned",
            "provider": "textverified",
            "provider_order_id": "abc",
            "provider_number": "+15551234567",
            "temp_service_key": "attapoll",
            "temp_country": "1",
            "selling_price": 0.44,
            "base_price": 0.4,
            "created_at": created_at,
            "temp_wait_started_at": created_at,
            "temp_wait_state": "code_received",
            "temp_last_code": "123456",
            "temp_first_sms_at": created_at + timedelta(seconds=30),
            "temp_last_sms_at": created_at + timedelta(seconds=30),
            "temp_codes": ["123456"],
            "temp_codes_count": 1,
            "temp_reuse_warranty_until": reuse_until,
        }
    )

    assert payload["public_status"] == "code_received"
    assert payload["code"] == "123456"
    assert payload["can_refresh"] is True
    assert payload["can_second_code"] is True
    assert payload["second_code_price_label"] == "$0.22"
    details = {item["key"]: item["value"] for item in payload["details"]}
    assert details["provider"] == "Bravo"
    assert details["country"] == "United States"
    assert details["reuseUntil"].endswith("UTC")


def test_numbers_temp_order_payload_uses_provisioning_provider_fallback():
    payload = miniapp._order_payload(
        {
            "_id": "temp-order-id",
            "number_mode": "temp",
            "status": "success",
            "provisioning_provider": "textverified",
            "provider_order_id": "abc",
            "provider_number": "+15551234567",
            "temp_service_key": "attapoll",
            "temp_country": "1",
            "selling_price": 0.44,
            "base_price": 0.4,
            "temp_wait_state": "waiting",
            "temp_codes": [],
            "temp_codes_count": 0,
        }
    )

    assert payload["provider"] == "Bravo"
    assert payload["provider_id"] == "S2"
    details = {item["key"]: item["value"] for item in payload["details"]}
    assert details["provider"] == "Bravo"


def test_numbers_temp_second_code_pending_hides_old_code():
    created_at = datetime.now(UTC) - timedelta(minutes=2)
    last_sms_at = created_at + timedelta(seconds=30)
    second_requested_at = created_at + timedelta(seconds=90)

    payload = miniapp._order_payload(
        {
            "_id": "temp-order-id",
            "number_mode": "temp",
            "status": "success",
            "provisioning_state": "provisioned",
            "provider": "textverified",
            "provider_order_id": "abc",
            "provider_number": "+15551234567",
            "temp_service_key": "attapoll",
            "temp_country": "1",
            "selling_price": 0.44,
            "base_price": 0.4,
            "created_at": created_at,
            "temp_wait_started_at": second_requested_at,
            "temp_wait_state": "waiting",
            "temp_last_code": "123456",
            "temp_first_sms_at": last_sms_at,
            "temp_last_sms_at": last_sms_at,
            "temp_second_code_last_at": second_requested_at,
            "temp_codes": ["123456"],
            "temp_codes_count": 1,
        }
    )

    assert payload["public_status"] == "waiting"
    assert payload["code"] == ""
    assert payload["can_second_code"] is False


def test_numbers_refund_pending_temp_order_can_refresh():
    payload = miniapp._order_payload(
        {
            "_id": "temp-order-id",
            "number_mode": "temp",
            "status": "success",
            "temp_wait_state": "refund_pending",
            "provider": "textverified",
            "provider_order_id": "abc",
            "provider_number": "+15551234567",
            "temp_service_key": "attapoll",
            "temp_country": "1",
            "selling_price": 0.44,
            "base_price": 0.4,
            "temp_codes": [],
            "temp_codes_count": 0,
        }
    )

    assert payload["public_status"] == "refund_pending"
    assert payload["can_refresh"] is True
    assert payload["can_cancel"] is False
    assert payload["can_replace"] is False


def test_numbers_terminal_provider_refund_reasons_cover_edge_cases():
    assert miniapp._provider_terminal_refund_reason("", allow_empty=False) == ""
    assert miniapp._provider_terminal_refund_reason("", allow_empty=True) == "provider_empty_response"
    assert miniapp._provider_terminal_refund_reason({"status": "refunded"}) == "provider_already_refunded"
    assert miniapp._provider_terminal_refund_reason("Activation not found", allow_missing=True) == "provider_missing_or_expired"
    assert miniapp._provider_terminal_refund_reason("Timed Out", allow_missing=False) == ""
    assert miniapp._provider_terminal_refund_reason("Timed Out", allow_missing=True) == "provider_missing_or_expired"


def test_numbers_expired_temp_order_without_code_exposes_replacement():
    payload = miniapp._order_payload(
        {
            "_id": "expired-temp-id",
            "number_mode": "temp",
            "status": "expired",
            "temp_wait_state": "waiting",
            "provider": "textverified",
            "provider_order_id": "abc",
            "provider_number": "+15551234567",
            "temp_service_key": "attapoll",
            "temp_country": "1",
            "selling_price": 0.44,
            "base_price": 0.4,
            "temp_codes": [],
            "temp_codes_count": 0,
        }
    )

    assert payload["public_status"] == "expired"
    assert payload["can_replace"] is True


def test_numbers_refund_pending_voice_order_can_refresh():
    payload = miniapp._order_payload(
        {
            "_id": "voice-order-id",
            "number_mode": "voice",
            "status": "success",
            "temp_wait_state": "refund_pending",
            "provider": "textverified",
            "provider_order_id": "abc",
            "provider_number": "+15551234567",
            "temp_service_key": "attapoll",
            "temp_country": "1",
            "selling_price": 0.44,
            "base_price": 0.4,
        }
    )

    assert payload["public_status"] == "refund_pending"
    assert payload["can_refresh"] is True
    assert payload["can_cancel"] is False
    assert payload["can_replace"] is False


def test_numbers_refunded_temp_order_payload_exposes_replace_action():
    payload = miniapp._order_payload(
        {
            "_id": "temp-order-id",
            "number_mode": "temp",
            "status": "cancelled",
            "temp_wait_state": "refunded",
            "provider": "textverified",
            "provider_order_id": "abc",
            "provider_number": "+15551234567",
            "temp_service_key": "attapoll",
            "temp_country": "1",
            "selling_price": 0.44,
            "base_price": 0.4,
            "temp_codes": [],
            "temp_codes_count": 0,
        }
    )

    assert payload["public_status"] == "refunded"
    assert payload["can_replace"] is True
    assert payload["can_alternate_provider"] is False
    assert payload["can_refresh"] is False
    assert payload["can_second_code"] is False


def test_numbers_refunded_temp_order_payload_exposes_alternate_after_failed_retry():
    payload = miniapp._order_payload(
        {
            "_id": "temp-order-id",
            "number_mode": "temp",
            "status": "cancelled",
            "temp_wait_state": "refunded",
            "provider": "textverified",
            "provider_order_id": "abc",
            "provider_number": "+15551234567",
            "temp_service_key": "attapoll",
            "temp_country": "1",
            "selling_price": 0.44,
            "base_price": 0.4,
            "temp_codes": [],
            "temp_codes_count": 0,
            "temp_alternate_enabled": True,
            "temp_alternate_provider": "herosms",
            "temp_alternate_price": 0.66,
        }
    )

    assert payload["public_status"] == "refunded"
    assert payload["can_replace"] is True
    assert payload["can_alternate_provider"] is True
    assert payload["alternate_provider_id"] == "S1"
    assert payload["alternate_provider"] == "Alpha"
    assert payload["alternate_provider_price_label"] == "$0.66"


def test_numbers_pick_alternate_temp_provider_ignores_current_hidden_and_unbuyable():
    prices = {
        "textverified": {"price": 0.10, "api_service_name": "gmail"},
        "smsman": {"price": 0.01, "api_service_name": "gmail"},
        "bad": {"price": 0.02, "api_service_name": ""},
        "herosms": {"price": 0.30, "api_service_name": "gmail"},
        "smspool": {"price": 0.20, "api_service_name": "gmail"},
    }

    picked = miniapp._pick_alternate_temp_provider(
        prices,
        current_provider="textverified",
        service="gmail",
        country="1",
        state="none",
    )

    assert picked is not None
    provider_code, info = picked
    assert provider_code == "smspool"
    assert info["price"] == 0.20


def test_numbers_pick_alternate_temp_provider_uses_retry_score_not_price_only():
    prices = {
        "textverified": {"price": 0.10, "api_service_name": "gmail"},
        "cheaplow": {
            "price": 0.20,
            "api_service_name": "gmail",
            "success_rate": 45,
            "success_attempts": 10,
        },
        "herosms": {
            "price": 0.24,
            "api_service_name": "gmail",
            "success_rate": 92,
            "success_attempts": 10,
        },
    }

    picked = miniapp._pick_alternate_temp_provider(
        prices,
        current_provider="textverified",
        service="gmail",
        country="1",
        state="none",
    )

    assert picked is not None
    provider_code, info = picked
    assert provider_code == "herosms"
    assert info["success_rate"] == 92


@pytest.mark.asyncio
async def test_numbers_enable_alternate_provider_suggestion_persists_best_option(monkeypatch):
    order = {
        "_id": "temp-order-id",
        "number_mode": "temp",
        "status": "cancelled",
        "temp_wait_state": "refunded",
        "provider": "textverified",
        "provider_order_id": "abc",
        "provider_number": "+15551234567",
        "temp_service_key": "gmail",
        "temp_country": "1",
        "temp_state": "none",
        "selling_price": 0.44,
        "base_price": 0.4,
        "temp_codes": [],
        "temp_codes_count": 0,
    }
    calls: dict = {}

    async def _fake_prices(service, country, state, with_success_rates=False):
        calls["prices"] = (service, country, state, with_success_rates)
        return {
            "textverified": {"price": 0.10, "api_service_name": "gmail"},
            "herosms": {"price": 0.42, "base_price": 0.40, "api_service_name": "gmail"},
        }

    async def _fake_update(order_id, patch):
        calls["update"] = (order_id, dict(patch))

    async def _fake_log(order_arg, event, payload):
        calls["log"] = (order_arg, event, payload)

    monkeypatch.setattr(miniapp, "get_all_prices", _fake_prices)
    monkeypatch.setattr(miniapp, "update_order_details", _fake_update)
    monkeypatch.setattr(miniapp, "_log_temp_event", _fake_log)

    result = await miniapp._enable_alternate_provider_suggestion(order_id=order["_id"], order=dict(order), lang="en")

    assert result is not None
    assert result["provider"] == "herosms"
    assert calls["prices"] == ("gmail", "1", "none", False)
    assert calls["update"][0] == "temp-order-id"
    assert calls["update"][1]["temp_alternate_provider"] == "herosms"
    assert calls["update"][1]["temp_alternate_api_service"] == "gmail"
    assert calls["update"][1]["temp_alternate_price"] == 0.42
    assert calls["log"][1] == "alternate_provider_suggested"


@pytest.mark.asyncio
async def test_numbers_request_replacement_number_uses_current_provider(monkeypatch):
    order = {
        "_id": "temp-order-id",
        "number_mode": "temp",
        "status": "cancelled",
        "temp_wait_state": "refunded",
        "provider": "textverified",
        "provider_order_id": "abc",
        "provider_number": "+15551234567",
        "temp_service_key": "gmail",
        "temp_country": "1",
        "temp_state": "none",
        "selling_price": 0.44,
        "base_price": 0.4,
        "temp_codes": [],
        "temp_codes_count": 0,
    }
    calls: dict = {}

    async def _fake_prices(service, country, state, with_success_rates=False):
        calls["prices"] = (service, country, state, with_success_rates)
        return {"textverified": {"price": 0.44, "base_price": 0.4, "api_service_name": "gmail"}}

    async def _fake_purchase(**kwargs):
        calls["purchase"] = kwargs
        return {"ok": True, "order": {"id": "replacement-order"}}

    async def _fake_log(order_arg, event, payload):
        calls["log"] = (order_arg, event, payload)

    monkeypatch.setattr(miniapp, "get_all_prices", _fake_prices)
    monkeypatch.setattr(miniapp, "_purchase_temp_offer", _fake_purchase)
    monkeypatch.setattr(miniapp, "_log_temp_event", _fake_log)

    result = await miniapp._request_replacement_number(
        order_id=order["_id"],
        order=dict(order),
        user_id=123,
        reseller_id=123,
        lang="en",
    )

    assert result["ok"] is True
    assert calls["prices"] == ("gmail", "1", "none", False)
    assert calls["purchase"]["offer"]["provider_code"] == "textverified"
    assert calls["purchase"]["source_order_id"] == "temp-order-id"
    assert calls["purchase"]["source_reason"] == "replace_request"
    assert calls["log"][1] == "replacement_requested"


@pytest.mark.asyncio
async def test_numbers_request_replacement_number_uses_alternate_provider(monkeypatch):
    order = {
        "_id": "temp-order-id",
        "number_mode": "temp",
        "status": "cancelled",
        "temp_wait_state": "refunded",
        "provider": "textverified",
        "provider_order_id": "abc",
        "provider_number": "+15551234567",
        "temp_service_key": "gmail",
        "temp_country": "1",
        "temp_state": "none",
        "selling_price": 0.44,
        "base_price": 0.4,
        "temp_codes": [],
        "temp_codes_count": 0,
        "temp_alternate_enabled": True,
        "temp_alternate_provider": "herosms",
    }
    calls: dict = {}

    async def _fake_prices(service, country, state, with_success_rates=False):
        return {
            "textverified": {"price": 0.44, "base_price": 0.4, "api_service_name": "gmail"},
            "herosms": {"price": 0.66, "base_price": 0.6, "api_service_name": "gmail"},
        }

    async def _fake_purchase(**kwargs):
        calls["purchase"] = kwargs
        return {"ok": True, "order": {"id": "alternate-order"}}

    async def _fake_log(order_arg, event, payload):
        calls["log"] = (order_arg, event, payload)

    monkeypatch.setattr(miniapp, "get_all_prices", _fake_prices)
    monkeypatch.setattr(miniapp, "_purchase_temp_offer", _fake_purchase)
    monkeypatch.setattr(miniapp, "_log_temp_event", _fake_log)

    result = await miniapp._request_replacement_number(
        order_id=order["_id"],
        order=dict(order),
        user_id=123,
        reseller_id=123,
        lang="en",
        alternate_provider=True,
    )

    assert result["ok"] is True
    assert calls["purchase"]["offer"]["provider_code"] == "herosms"
    assert calls["purchase"]["offer"]["info"]["price"] == 0.66
    assert calls["purchase"]["source_reason"] == "alternate_provider_request"
    assert calls["log"][2]["alternate_provider"] is True


def test_provider_terminal_status_classifier_keeps_waiting_states_open():
    assert miniapp._provider_terminal_refund_reason("STATUS_WAIT_CODE", allow_missing=True) == ""
    assert miniapp._provider_terminal_refund_reason({"error_code": "wait_sms"}, allow_missing=True) == ""
    assert miniapp._provider_terminal_refund_reason("NO_ACTIVATION", allow_missing=True) == "provider_missing_or_expired"
    assert miniapp._provider_terminal_refund_reason({"status": "Timed Out"}, allow_missing=True) == "provider_missing_or_expired"
    assert miniapp._provider_terminal_refund_reason("STATUS_CANCEL") == "provider_already_refunded"


@pytest.mark.asyncio
async def test_refresh_temp_order_refunds_old_missing_provider_order(monkeypatch):
    now = datetime.now(UTC)
    stored = {
        "_id": "order-old",
        "number_mode": "temp",
        "status": "success",
        "user_id": 123,
        "reseller_id": 123,
        "provisioning_provider": "herosms",
        "provider_order_id": "prov-old",
        "provider_number": "+15551234567",
        "temp_service_key": "rebtel",
        "temp_country": "1",
        "selling_price": 0.11,
        "base_price": 0.10,
        "created_at": now - timedelta(minutes=20),
        "temp_wait_started_at": now - timedelta(minutes=20),
        "temp_wait_timeout_sec": 300,
        "temp_wait_state": "waiting",
        "temp_codes": [],
        "temp_codes_count": 0,
    }
    calls: dict = {}

    class _DummyProvider:
        async def cancel(self, activation_id):
            calls["cancel"] = activation_id
            return {"success": False, "raw": "NO_ACTIVATION"}

    class _DummyFinancialManager:
        @classmethod
        async def refund_core_purchase(cls, user_id, order_id, sale_price, cost_price, reseller_id=None):
            calls["refund"] = {
                "user_id": user_id,
                "order_id": order_id,
                "sale_price": sale_price,
                "cost_price": cost_price,
                "reseller_id": reseller_id,
            }
            return True, "OK"

    async def _fake_get_order(_order_id):
        return dict(stored)

    async def _fake_update_order_status(_order_id, status):
        calls["status"] = status
        stored["status"] = status

    async def _fake_update_order_details(_order_id, patch):
        stored.update(patch)
        calls.setdefault("details", []).append(dict(patch))

    async def _fake_fetch_provider_sms(_providers, provider, provider_order_id):
        calls["fetch"] = (provider, provider_order_id)
        return {"success": False, "messages": [], "raw": "NO_ACTIVATION"}

    async def _fake_log(*args, **kwargs):
        return None

    monkeypatch.setitem(miniapp.PROVIDERS, "herosms", _DummyProvider())
    monkeypatch.setattr(miniapp, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(miniapp, "get_order", _fake_get_order)
    monkeypatch.setattr(miniapp, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(miniapp, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(miniapp, "fetch_provider_sms", _fake_fetch_provider_sms)
    monkeypatch.setattr(miniapp, "_log_temp_event", _fake_log)
    monkeypatch.setattr(miniapp, "_log_number_event_from_order", _fake_log)

    refreshed = await miniapp._refresh_temp_order(dict(stored))

    assert calls["fetch"] == ("herosms", "prov-old")
    assert calls["cancel"] == "prov-old"
    assert calls["refund"]["order_id"] == "order-old"
    assert calls["status"] == "cancelled"
    assert refreshed["status"] == "cancelled"
    assert refreshed["temp_wait_state"] == "refunded"
    assert refreshed["temp_provider_terminal_reason"] == "provider_missing_or_expired"


@pytest.mark.asyncio
async def test_cancel_temp_order_marks_financial_refund_failure_retryable(monkeypatch):
    now = datetime.now(UTC)
    order = {
        "_id": "finance-fail-order",
        "number_mode": "temp",
        "status": "success",
        "user_id": 123,
        "reseller_id": 123,
        "provider": "textverified",
        "provider_order_id": "prov-finance-fail",
        "provider_number": "+15551234567",
        "selling_price": 0.44,
        "base_price": 0.4,
        "created_at": now - timedelta(minutes=20),
        "temp_wait_started_at": now - timedelta(minutes=20),
        "temp_wait_timeout_sec": 300,
        "temp_wait_state": "waiting",
        "temp_codes": [],
        "temp_codes_count": 0,
    }
    calls: dict = {}

    class _DummyProvider:
        async def cancel(self, activation_id):
            calls["cancel"] = activation_id
            return {"success": True, "raw": "cancelled"}

    class _DummyFinancialManager:
        @classmethod
        async def refund_core_purchase(cls, user_id, order_id, sale_price, cost_price, reseller_id=None):
            calls["refund"] = order_id
            return False, "ledger_write_failed"

    async def _fail_update_order_status(*args, **kwargs):
        raise AssertionError("status must not close when wallet refund fails")

    async def _fake_update_order_details(*args, **kwargs):
        calls.setdefault("details", []).append(args)

    async def _fake_log(*args, **kwargs):
        return None

    monkeypatch.setitem(miniapp.PROVIDERS, "textverified", _DummyProvider())
    monkeypatch.setattr(miniapp, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(miniapp, "update_order_status", _fail_update_order_status)
    monkeypatch.setattr(miniapp, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(miniapp, "_log_temp_event", _fake_log)
    monkeypatch.setattr(miniapp, "_log_number_event_from_order", _fake_log)

    result = await miniapp._cancel_and_refund_temp_order(
        order_id=order["_id"],
        order=dict(order),
        actor_user_id=123,
        reason="test_finance_failure",
        require_no_sms=True,
    )

    assert calls["cancel"] == "prov-finance-fail"
    assert calls["refund"] == "finance-fail-order"
    assert result == {"success": False, "reason": "financial_refund_failed", "raw": "ledger_write_failed"}
    assert miniapp._temp_refund_result_retryable(result) is True


@pytest.mark.asyncio
async def test_cancel_temp_order_exposes_retryable_provider_cancel_failure(monkeypatch):
    order = {
        "_id": "provider-retry-order",
        "number_mode": "temp",
        "status": "success",
        "user_id": 123,
        "reseller_id": 123,
        "provider": "textverified",
        "provider_order_id": "prov-timeout",
        "provider_number": "+15551234567",
        "selling_price": 0.44,
        "base_price": 0.4,
        "temp_wait_state": "waiting",
        "temp_codes": [],
        "temp_codes_count": 0,
    }
    calls = {"cancel": 0}

    class _DummyProvider:
        async def cancel(self, activation_id):
            calls["cancel"] += 1
            assert activation_id == "prov-timeout"
            return {"success": False, "raw": "provider timeout"}

    async def _fake_sleep(_seconds):
        calls["sleep"] = calls.get("sleep", 0) + 1

    async def _fake_log(*args, **kwargs):
        return None

    monkeypatch.setitem(miniapp.PROVIDERS, "textverified", _DummyProvider())
    monkeypatch.setattr(miniapp.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(miniapp, "_log_number_event_from_order", _fake_log)

    result = await miniapp._cancel_and_refund_temp_order(
        order_id=order["_id"],
        order=dict(order),
        actor_user_id=123,
        reason="test_provider_retryable",
        require_no_sms=True,
    )

    assert calls["cancel"] == 4
    assert calls["sleep"] == 2
    assert result["reason"] == "provider_cancel_failed"
    assert result["retryable"] is True
    assert miniapp._temp_refund_result_retryable(result) is True


@pytest.mark.asyncio
async def test_cancel_temp_order_exposes_permanent_provider_cancel_failure(monkeypatch):
    order = {
        "_id": "provider-permanent-order",
        "number_mode": "temp",
        "status": "success",
        "user_id": 123,
        "reseller_id": 123,
        "provider": "textverified",
        "provider_order_id": "prov-denied",
        "provider_number": "+15551234567",
        "selling_price": 0.44,
        "base_price": 0.4,
        "temp_wait_state": "waiting",
        "temp_codes": [],
        "temp_codes_count": 0,
    }

    class _DummyProvider:
        async def cancel(self, _activation_id):
            return {"success": False, "raw": "policy denied"}

    async def _fake_sleep(_seconds):
        return None

    async def _fake_log(*args, **kwargs):
        return None

    monkeypatch.setitem(miniapp.PROVIDERS, "textverified", _DummyProvider())
    monkeypatch.setattr(miniapp.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(miniapp, "_log_number_event_from_order", _fake_log)

    result = await miniapp._cancel_and_refund_temp_order(
        order_id=order["_id"],
        order=dict(order),
        actor_user_id=123,
        reason="test_provider_permanent",
        require_no_sms=True,
    )

    assert result["reason"] == "provider_cancel_failed"
    assert result["retryable"] is False
    assert miniapp._temp_refund_result_retryable(result) is False


@pytest.mark.asyncio
async def test_cancel_temp_order_empty_provider_response_after_timeout_refunds_locally(monkeypatch):
    now = datetime.now(UTC)
    stored = {
        "_id": "provider-empty-order",
        "number_mode": "temp",
        "status": "success",
        "user_id": 123,
        "reseller_id": 123,
        "provider": "textverified",
        "provider_order_id": "prov-empty",
        "provider_number": "+15551234567",
        "selling_price": 0.44,
        "base_price": 0.4,
        "created_at": now - timedelta(minutes=20),
        "temp_wait_started_at": now - timedelta(minutes=20),
        "temp_wait_timeout_sec": 300,
        "temp_wait_state": "waiting",
        "temp_codes": [],
        "temp_codes_count": 0,
    }
    calls: dict = {}

    class _DummyProvider:
        async def cancel(self, activation_id):
            calls["cancel"] = activation_id
            return {"success": False, "raw": ""}

    class _DummyFinancialManager:
        @classmethod
        async def refund_core_purchase(cls, user_id, order_id, sale_price, cost_price, reseller_id=None):
            calls["refund"] = order_id
            return True, "OK"

    async def _fake_update_order_status(_order_id, status):
        calls["status"] = status
        stored["status"] = status

    async def _fake_update_order_details(_order_id, patch):
        stored.update(patch)
        calls["details"] = dict(patch)

    async def _fake_log(*args, **kwargs):
        return None

    monkeypatch.setitem(miniapp.PROVIDERS, "textverified", _DummyProvider())
    monkeypatch.setattr(miniapp, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(miniapp, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(miniapp, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(miniapp, "_log_temp_event", _fake_log)
    monkeypatch.setattr(miniapp, "_log_number_event_from_order", _fake_log)

    result = await miniapp._cancel_and_refund_temp_order(
        order_id=stored["_id"],
        order=dict(stored),
        actor_user_id=123,
        reason="test_empty_provider_terminal",
        require_no_sms=True,
        allow_empty_provider_refund=True,
    )

    assert result == {"success": True, "reason": "ok"}
    assert calls["cancel"] == "prov-empty"
    assert calls["refund"] == "provider-empty-order"
    assert calls["status"] == "cancelled"
    assert stored["temp_wait_state"] == "refunded"
    assert stored["temp_provider_terminal_reason"] == "provider_empty_response"


def test_numbers_rental_order_payload_exposes_renew_and_wake_actions():
    payload = miniapp._order_payload(
        {
            "_id": "rental-order-id",
            "number_mode": "rental",
            "status": "success",
            "provisioning_state": "provisioned",
            "provider": "textverified",
            "provider_order_id": "rental-1",
            "provider_number": "+15551234567",
            "service_id": "telegram:rental",
            "rental_country": "1",
            "rental_duration_label": "1d",
            "rental_is_renewable": True,
            "rental_notes": "Keep alive",
            "rental_tags": ["vip", "login"],
            "rental_sms_messages": ["Code 111", "Code 222"],
            "rental_sms_count": 2,
            "selling_price": 1.2,
            "base_price": 1.0,
        }
    )

    assert payload["mode"] == "rental"
    assert payload["can_renew"] is True
    assert payload["can_wake"] is True
    assert payload["can_notes"] is True
    assert payload["can_finish"] is True
    assert payload["can_sms"] is True
    assert payload["code"] == "Code 222"
    assert payload["messages"] == ["Code 111", "Code 222"]
    assert payload["notes"] == "Keep alive"
    assert payload["tags"] == ["vip", "login"]
    details = {item["key"]: item["value"] for item in payload["details"]}
    assert details["provider"] == "Bravo"
    assert details["country"] == "United States"
    assert details["duration"] == "1d"


def test_numbers_rental_order_payload_exposes_cancel_when_refundable_without_sms():
    now = datetime.now(UTC)
    payload = miniapp._order_payload(
        {
            "_id": "rental-order-id",
            "number_mode": "rental",
            "status": "success",
            "provisioning_state": "provisioned",
            "provider": "herosms",
            "provider_order_id": "rental-1",
            "provider_number": "+15551234567",
            "service_id": "telegram:rental",
            "rental_country": "1",
            "rental_started_at": now,
            "rental_protection_policy": {"refund_deadline_sec": 1200, "safe_cutoff_sec": 60},
            "rental_sms_count": 0,
            "selling_price": 1.2,
            "base_price": 1.0,
        }
    )

    assert payload["public_status"] == "waiting"
    assert payload["can_cancel"] is True


def test_numbers_rental_order_payload_hides_cancel_after_sms():
    payload = miniapp._order_payload(
        {
            "_id": "rental-order-id",
            "number_mode": "rental",
            "status": "success",
            "provisioning_state": "provisioned",
            "provider": "herosms",
            "provider_order_id": "rental-1",
            "provider_number": "+15551234567",
            "service_id": "telegram:rental",
            "rental_country": "1",
            "rental_sms_count": 1,
            "rental_sms_messages": ["Code 123"],
            "selling_price": 1.2,
            "base_price": 1.0,
        }
    )

    assert payload["public_status"] == "code_received"
    assert payload["can_cancel"] is False


def test_register_numbers_routes_adds_public_endpoints():
    app = web.Application()

    miniapp.register_numbers_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/mini/numbers") in routes
    assert ("GET", "/mini/numbers/static/{name}") in routes
    assert ("GET", "/mini/numbers/api/bootstrap") in routes
    assert ("GET", "/mini/numbers/api/country-suggestions") in routes
    assert ("GET", "/mini/numbers/api/account") in routes
    assert ("POST", "/mini/numbers/api/account/language") in routes
    assert ("GET", "/mini/numbers/api/support") in routes
    assert ("POST", "/mini/numbers/api/support/ticket") in routes
    assert ("GET", "/mini/numbers/api/prices") in routes
    assert ("GET", "/mini/numbers/api/orders") in routes
    assert ("POST", "/mini/numbers/api/purchase") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/refresh") in routes
    assert ("GET", "/mini/numbers/api/orders/{order_id}/recording") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/second-code") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/replace") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/alternate") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/sms") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/finish") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/renew") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/wake") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/notes") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/cancel") in routes


def test_numbers_support_categories_are_numbers_scoped():
    rows = miniapp._support_categories_payload("en")

    assert [row["key"] for row in rows] == ["numbers", "user_balance"]
    assert rows[0]["label"] == "Numbers orders"
