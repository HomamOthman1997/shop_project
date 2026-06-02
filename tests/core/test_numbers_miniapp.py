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
    assert payload["client"]["primary_surface"] == "miniapp"
    assert payload["client"]["telegram_order_flow_enabled"] is False
    assert payload["client"]["provider_sms_polling_enabled"] is False
    assert payload["client"]["manual_customer_refund_enabled"] is False
    assert [item["key"] for item in payload["client"]["tabs"]] == ["buy", "orders", "recharge", "account", "support"]
    assert payload["client"]["actions"]["orders"]["endpoint"] == "/mini/numbers/api/orders"
    assert payload["client"]["actions"]["country_suggestions"]["endpoint"] == "/mini/numbers/api/country-suggestions"
    assert payload["client"]["actions"]["purchase"]["endpoint"] == "/mini/numbers/api/purchase"
    assert payload["client"]["actions"]["purchase"]["method"] == "POST"
    assert payload["client"]["actions"]["submit_recharge"]["method"] == "POST"
    assert payload["client"]["features"]["server_managed_refunds"] is True
    assert [item["key"] for item in payload["modes"]] == ["temp", "rental", "voice"]
    us_country = next(item for item in payload["countries"] if item["code"] == "1")
    any_state = next(item for item in payload["states_us"] if item["code"] == "none")
    assert "usa" in {str(alias).lower() for alias in us_country["aliases"]}
    assert "any" in {str(alias).lower() for alias in any_state["aliases"]}
    assert any(item["key"] == "telegram" for item in payload["services"])


@pytest.mark.asyncio
async def test_numbers_bootstrap_endpoint_adds_user_language(monkeypatch):
    miniapp._BOOTSTRAP_CACHE["data"] = None

    async def fake_get_user(_user_id):
        return {"language": "en"}

    monkeypatch.setattr(miniapp, "_optional_auth", lambda _request: {"user_id": 123, "user": {"language_code": "ar"}})
    monkeypatch.setattr(miniapp, "get_user", fake_get_user)

    request = make_mocked_request("GET", "/mini/numbers/api/bootstrap")
    response = await miniapp.bootstrap(request)
    payload = json.loads(response.text)

    assert payload["language"] == "en"
    assert payload["direction"] == "ltr"
    assert payload["defaults"] == {"mode": "temp", "service": "", "country": "none", "state": "none"}


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
            "textverified": {
                "price": 1.25,
                "base_price": 1.0,
                "api_service_name": "telegram",
                "success_rate": 88,
                "success_attempts": 10,
                "recommended_success_rate": 92,
                "context_success_attempts": 5,
                "provider_state_code": "CA",
            },
            "telabot": {
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
    assert rows[0]["success_rate"] == "90%"
    assert rows[0]["success_attempts"] == 10
    assert rows[0]["location_tag"] == "CA"
    assert len(rows) == 1
    assert rows[0]["available"] is True
    assert rows[0]["recommended"] is True
    assert rows[0]["purchase_action"]["enabled"] is True
    assert rows[0]["purchase_action"]["endpoint"] == "/mini/numbers/api/purchase"
    assert rows[0]["purchase_action"]["body"]["quote_token"] == rows[0]["quote_token"]


def test_numbers_price_rows_show_fixed_rate_for_trusted_providers(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "numbers_success_rate_display_min_attempts", 5, raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "pvadeals": {
                "price": 1.25,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "success_rate": 12,
                "success_attempts": 0,
            },
            "vaksms": {
                "price": 1.35,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "success_rate": 73,
                "success_attempts": 10,
            },
            "herosms": {
                "price": 1.45,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "success_rate": 99,
                "success_attempts": 10,
            },
        },
        "temp",
        service="telegram",
        country="none",
        state="none",
    )

    by_id = {row["provider_id"]: row for row in rows}
    assert by_id["S5"]["success_rate"] == "90%"
    assert by_id["S6"]["success_rate"] == "73%"
    assert by_id["S1"]["success_rate"] == "70%"


@pytest.mark.asyncio
async def test_numbers_prices_endpoint_skips_blocking_success_rates(monkeypatch):
    calls = {}

    async def fake_get_all_prices(
        service,
        country,
        state,
        ignore_balance=False,
        with_success_rates=True,
        provider_codes=None,
        soft_timeout_sec=None,
    ):
        calls["service"] = service
        calls["country"] = country
        calls["state"] = state
        calls["ignore_balance"] = ignore_balance
        calls["with_success_rates"] = with_success_rates
        calls["provider_codes"] = tuple(provider_codes or ())
        calls["soft_timeout_sec"] = soft_timeout_sec
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
        "ignore_balance": True,
        "with_success_rates": False,
        "provider_codes": miniapp._TEMP_PRICE_SCREEN_PROVIDER_CODES,
        "soft_timeout_sec": None,
    }
    assert payload["providers"][0]["success_rate"] == "90%"


@pytest.mark.asyncio
async def test_numbers_prices_endpoint_limits_not_listed_providers(monkeypatch):
    calls = {}

    async def fake_get_all_prices(
        service,
        country,
        state,
        ignore_balance=False,
        with_success_rates=True,
        provider_codes=None,
        soft_timeout_sec=None,
    ):
        calls["service"] = service
        calls["provider_codes"] = tuple(provider_codes or ())
        calls["soft_timeout_sec"] = soft_timeout_sec
        return {
            "textverified": {
                "price": 0.55,
                "base_price": 0.5,
                "api_service_name": "servicenotlisted",
                "available_for_buy": True,
            }
        }

    monkeypatch.setattr(miniapp, "get_all_prices", fake_get_all_prices)
    request = make_mocked_request("GET", "/mini/numbers/api/prices?mode=temp&service=not_listed_generic&country=1&state=none")

    response = await miniapp.prices(request)
    payload = json.loads(response.text)

    assert calls == {
        "service": "notlistedgeneric",
        "provider_codes": miniapp._TEMP_NOT_LISTED_PRICE_PROVIDER_CODES,
        "soft_timeout_sec": None,
    }
    assert payload["providers"][0]["price_label"] == "$0.55"


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


@pytest.mark.asyncio
async def test_numbers_recharge_method_payload_renders_payment_details():
    payload = await miniapp._recharge_method_payload(
        {
            "code": "owner_usdt",
            "title": "USDT",
            "currency": "USD",
            "per_credit": 1,
            "target": "T_WALLET",
            "support": "@support",
            "instructions": "Send payment to {target}. Contact {support}.",
        },
        "en",
    )

    assert payload["code"] == "owner_usdt"
    assert payload["target"] == "T_WALLET"
    assert payload["rate_label"] == "1 credit = $1"
    assert "T_WALLET" not in payload["instructions"]
    assert "@support" in payload["instructions"]


def test_numbers_recharge_request_payload_formats_user_visible_status():
    row = miniapp._recharge_request_payload(
        {
            "_id": "req-1",
            "method": "USDT",
            "status": "need_more_proof",
            "amount": 2.5,
            "details": {"paid_amount": 2.5, "paid_currency": "USD"},
            "delivery": {"delivered": True},
            "created_at": datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
        },
        "ar",
    )

    assert row["status_label"] == "يحتاج إثبات إضافي"
    assert row["credits_label"] == "$2.5"
    assert row["paid_label"] == "$2.5"
    assert row["delivery_ok"] is True


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
            "nonvoip": {
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
    quote = miniapp._api_verify_quote_token(rows[0]["quote_token"])
    assert quote["service"] == "attapoll"
    assert quote["provider_id"] == "S2"
    assert "provider" not in quote


def test_numbers_rental_options_include_signed_quotes(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "bot_numbers_token", "numbers-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "bot_main_token", "main-token", raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "herosms": {
                "available_for_buy": True,
                "api_service_name": "go",
                "options": [
                    {
                        "country": "187",
                        "provider_country_iso": "US",
                        "provider_country_name": "United States",
                        "duration": 2,
                        "duration_label": "2h",
                        "price": 0.55,
                        "base_price": 0.5,
                    },
                ],
            }
        },
        "rental",
        service="google",
        country="1",
    )

    option = rows[0]["options"][0]
    assert option["duration_label"] == "2h"
    assert option["location_tag"] == "United States"
    assert option["country"] == "187"
    assert option["purchase_action"]["enabled"] is True
    assert option["purchase_action"]["body"]["quote_token"] == option["quote_token"]
    quote = miniapp._api_verify_quote_token(option["quote_token"])
    assert quote["mode"] == "rental"
    assert quote["service"] == "google"
    assert quote["provider_id"] == "S1"
    assert quote["option_key"][-1] == "187"
    assert "provider" not in quote


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
    quote = miniapp._api_verify_quote_token(option["quote_token"])
    assert quote["state"] == "CA"
    assert quote["option_key"][4] == "ca"


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
    quote = miniapp._api_verify_quote_token(rows[0]["quote_token"])
    assert quote["mode"] == "voice"
    assert quote["service"] == "attapoll"
    assert quote["country"] == "1"
    assert quote["state"] == "none"
    assert rows[0]["purchase_action"]["endpoint"] == "/mini/numbers/api/purchase"
    assert rows[0]["purchase_action"]["body"]["quote_token"] == rows[0]["quote_token"]


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


def test_numbers_price_rows_prefer_classified_provider_over_unclassified_when_close(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "bot_numbers_token", "numbers-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "bot_main_token", "main-token", raising=False)
    monkeypatch.setattr(miniapp.settings, "numbers_success_rate_display_min_attempts", 1, raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "smsready": {
                "price": 0.1,
                "base_price": 0.08,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "success_rate": 95,
                "success_attempts": 20,
            },
            "telabot": {
                "price": 0.11,
                "base_price": 0.09,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "success_rate": 95,
                "success_attempts": 20,
            },
        },
        "temp",
        service="telegram",
        country="none",
        state="none",
    )

    assert rows[0]["provider_id"] == "S4"
    assert rows[0]["recommended"] is True


def test_numbers_provider_debug_rows_explain_hidden_providers(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "numbers_success_rate_display_min_attempts", 1, raising=False)

    rows = miniapp._provider_debug_rows(
        {
            "nonvoip": {
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
    assert by_code["nonvoip"]["visible"] is False
    assert by_code["nonvoip"]["reason"] == "hidden_provider"
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

    quote = miniapp._api_verify_quote_token(rows[0]["quote_token"])

    assert quote["mode"] == "voice"
    assert quote["state"] == "NY"
    assert rows[0]["purchase_action"]["method"] == "POST"
    assert rows[0]["purchase_action"]["body"]["quote_token"] == rows[0]["quote_token"]


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
    assert payload["actions"]["preview_recording"]["enabled"] is True
    assert payload["actions"]["preview_recording"]["method"] == "GET"
    assert payload["actions"]["download_recording"]["endpoint"] == "/mini/numbers/api/orders/voice-order-id/recording"
    assert "base_price_label" not in payload


def test_numbers_voice_recording_uri_accepts_provider_variants():
    assert (
        miniapp._voice_recording_uri_from_calls(
            [
                {
                    "id": "call_1",
                    "recording": {"downloadUrl": "https://example.test/nested.mp3"},
                }
            ]
        )
        == "https://example.test/nested.mp3"
    )
    assert (
        miniapp._voice_recording_uri_from_calls(
            [
                {
                    "id": "call_2",
                    "recording_url": "/api/pub/v2/calls/call_2/recording",
                }
            ]
        )
        == "/api/pub/v2/calls/call_2/recording"
    )


def test_numbers_voice_order_payload_waiting_for_recording_can_refresh():
    payload = miniapp._order_payload(
        {
            "_id": "voice-order-id",
            "number_mode": "voice",
            "status": "success",
            "temp_wait_state": "waiting_for_recording",
            "provider": "textverified",
            "provider_order_id": "abc",
            "provider_number": "+15551234567",
            "temp_service_key": "attapoll",
            "temp_country": "1",
            "selling_price": 0.44,
            "base_price": 0.4,
            "voice_calls_count": 1,
            "voice_calls": [{"id": "call_1", "recordingUri": None}],
        }
    )

    assert payload["public_status"] == "waiting_for_recording"
    assert payload["recording_available"] is False
    assert payload["can_refresh"] is True
    assert payload["can_cancel"] is False


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
    assert "base_price_label" not in payload
    details = {item["key"]: item["value"] for item in payload["details"]}
    assert details["provider"] == "Bravo"
    assert details["country"] == "United States"
    assert details["reuseUntil"].endswith("UTC")
    assert payload["actions"]["copy_number"]["enabled"] is True
    assert payload["actions"]["copy_number"]["method"] == "CLIENT"
    assert payload["actions"]["copy_code"]["enabled"] is True
    assert payload["actions"]["refresh"]["endpoint"] == "/mini/numbers/api/orders/temp-order-id/refresh"
    assert payload["actions"]["refresh"]["busy_label_key"] == "checkingOrder"
    assert payload["actions"]["test_active"]["enabled"] is True
    assert payload["actions"]["test_active"]["endpoint"] == "/mini/numbers/api/orders/temp-order-id/refresh"
    assert payload["actions"]["test_active"]["label_key"] == "testActive"
    assert payload["actions"]["second_code"]["enabled"] is True
    assert payload["actions"]["second_code"]["endpoint"] == "/mini/numbers/api/orders/temp-order-id/second-code"
    assert payload["actions"]["second_code"]["confirm_label_key"] == "confirmSecondCode"
    assert payload["actions"]["second_code"]["success_label_key"] == "secondCodeRequested"


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
    assert payload["actions"]["copy_code"]["enabled"] is False
    assert payload["actions"]["second_code"]["enabled"] is False


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
    assert payload["refund"]["reason"] == "refund_pending"
    assert "base_price_label" not in payload


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
    assert payload["refund"]["reason"] == "automatic_refund"


def test_numbers_order_payload_uses_customer_safe_refund_reason():
    payload = miniapp._order_payload(
        {
            "_id": "temp-order-id",
            "number_mode": "temp",
            "status": "cancelled",
            "temp_wait_state": "refunded",
            "temp_refund_reason": "provider_cancel_failed",
            "temp_refund_source": "provider",
            "temp_provider_terminal_reason": "provider_missing_or_expired",
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
    assert payload["refund"]["reason"] == "automatic_refund"
    assert "provider" not in payload["refund"]["reason"]


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


@pytest.mark.asyncio
async def test_numbers_miniapp_replace_order_uses_shared_service(monkeypatch):
    raw_id = str(miniapp.ObjectId())
    source_order = {
        "_id": raw_id,
        "number_mode": "temp",
        "user_id": 123,
        "reseller_id": 123,
        "status": "cancelled",
        "temp_wait_state": "refunded",
    }
    replacement_order = {
        "_id": "replacement-order",
        "number_mode": "temp",
        "user_id": 123,
        "reseller_id": 123,
        "status": "success",
        "temp_wait_state": "waiting",
    }
    calls: dict = {}

    async def _fake_load_or_create_user(auth):
        calls["auth"] = auth
        return {"language": "en"}

    async def _fake_get_order(order_id):
        if str(order_id) == raw_id:
            return dict(source_order)
        if str(order_id) == "replacement-order":
            return dict(replacement_order)
        return None

    async def _fake_request_replacement_order(**kwargs):
        calls["replace"] = kwargs
        return {"ok": True, "order": {"id": "replacement-order"}}

    async def _fake_order_payload_with_events(order, lang):
        return {"id": str(order.get("_id")), "mode": order.get("number_mode"), "lang": lang, "events": []}

    async def _fake_balance(user_id, reseller_id):
        calls["balance"] = (user_id, reseller_id)
        return 12.5

    monkeypatch.setattr(
        miniapp,
        "_require_auth",
        lambda _request: {"user_id": 123, "user": {"language_code": "en"}},
    )
    monkeypatch.setattr(miniapp, "_load_or_create_user", _fake_load_or_create_user)
    monkeypatch.setattr(miniapp, "get_order", _fake_get_order)
    monkeypatch.setattr(miniapp, "_api_request_replacement_order", _fake_request_replacement_order)
    monkeypatch.setattr(miniapp, "_order_payload_with_events", _fake_order_payload_with_events)
    monkeypatch.setattr(miniapp, "get_user_wallet_balance", _fake_balance)

    request = make_mocked_request(
        "POST",
        f"/mini/numbers/api/orders/{raw_id}/replace",
        headers={"Content-Type": "application/json", "Idempotency-Key": "replace-1"},
        match_info={"order_id": raw_id},
    )
    request._read_bytes = b"{}"

    response = await miniapp.replace_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["replace"]["order"] == source_order
    assert calls["replace"]["user_id"] == 123
    assert calls["replace"]["reseller_id"] == 123
    assert calls["replace"]["idempotency_key"] == "replace-1"
    assert calls["replace"]["alternate_provider"] is False
    assert payload["order"] == {"id": "replacement-order", "mode": "temp", "lang": "en", "events": []}
    assert payload["message"] == "Replacement number requested."
    assert payload["balance_label"] == "$12.5"


@pytest.mark.asyncio
async def test_numbers_miniapp_alternate_order_uses_shared_service(monkeypatch):
    raw_id = str(miniapp.ObjectId())
    source_order = {
        "_id": raw_id,
        "number_mode": "temp",
        "user_id": 123,
        "reseller_id": 123,
        "status": "cancelled",
        "temp_wait_state": "refunded",
        "temp_alternate_enabled": True,
    }
    calls: dict = {}

    async def _fake_load_or_create_user(_auth):
        return {"language": "en"}

    async def _fake_get_order(order_id):
        if str(order_id) == raw_id:
            return dict(source_order)
        if str(order_id) == "alternate-order":
            return {"_id": "alternate-order", "number_mode": "temp", "user_id": 123}
        return None

    async def _fake_request_replacement_order(**kwargs):
        calls["replace"] = kwargs
        return {"ok": True, "order": {"id": "alternate-order"}}

    async def _fake_order_payload_with_events(order, lang):
        return {"id": str(order.get("_id")), "mode": order.get("number_mode"), "lang": lang, "events": []}

    async def _fake_balance(_user_id, _reseller_id):
        return 8.0

    monkeypatch.setattr(
        miniapp,
        "_require_auth",
        lambda _request: {"user_id": 123, "user": {"language_code": "en"}},
    )
    monkeypatch.setattr(miniapp, "_load_or_create_user", _fake_load_or_create_user)
    monkeypatch.setattr(miniapp, "get_order", _fake_get_order)
    monkeypatch.setattr(miniapp, "_api_request_replacement_order", _fake_request_replacement_order)
    monkeypatch.setattr(miniapp, "_order_payload_with_events", _fake_order_payload_with_events)
    monkeypatch.setattr(miniapp, "get_user_wallet_balance", _fake_balance)

    request = make_mocked_request(
        "POST",
        f"/mini/numbers/api/orders/{raw_id}/alternate",
        headers={"Content-Type": "application/json"},
        match_info={"order_id": raw_id},
    )
    request._read_bytes = b"{}"

    response = await miniapp.alternate_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["replace"]["order"] == source_order
    assert calls["replace"]["idempotency_key"] == f"miniapp:alternate:123:{raw_id}"
    assert calls["replace"]["alternate_provider"] is True
    assert payload["order"]["id"] == "alternate-order"
    assert payload["message"] == "Alternate provider number requested."


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["rental", "voice"])
async def test_numbers_miniapp_purchase_api_quotes_use_shared_order_service(monkeypatch, mode):
    if mode == "rental":
        rows = miniapp._normalize_provider_rows(
            {
                "herosms": {
                    "available_for_buy": True,
                    "api_service_name": "telegram",
                    "options": [{"duration": 24, "duration_label": "1d", "price": 1.25, "base_price": 1.0}],
                }
            },
            "rental",
            service="telegram",
            country="1",
            state="none",
        )
        quote_token = rows[0]["options"][0]["quote_token"]
        order_id = "rental-order"
    else:
        rows = miniapp._normalize_provider_rows(
            {
                "textverified": {
                    "price": 0.44,
                    "base_price": 0.4,
                    "api_service_name": "telegram",
                    "available_for_buy": True,
                    "voice_capable": True,
                }
            },
            "voice",
            service="telegram",
            country="1",
            state="CA",
        )
        quote_token = rows[0]["quote_token"]
        order_id = "voice-order"

    calls: dict = {}

    async def _fake_load_or_create_user(_auth):
        return {"language": "en"}

    async def _fake_create_number_order_from_quote(**kwargs):
        calls["create"] = kwargs
        return {"ok": True, "order": {"id": order_id}}

    async def _fake_get_order(value):
        if str(value) == order_id:
            return {"_id": order_id, "number_mode": mode, "user_id": 123, "status": "success"}
        return None

    async def _fake_order_payload_with_events(order, lang):
        return {"id": str(order.get("_id")), "mode": order.get("number_mode"), "lang": lang, "events": []}

    async def _fake_recent_events(_order_id, _lang, limit=5):
        return []

    async def _fake_balance(_user_id, _reseller_id):
        return 9.0

    monkeypatch.setattr(
        miniapp,
        "_require_auth",
        lambda _request: {"user_id": 123, "user": {"language_code": "en"}},
    )
    monkeypatch.setattr(miniapp, "_load_or_create_user", _fake_load_or_create_user)
    monkeypatch.setattr(miniapp, "_api_create_number_order_from_quote", _fake_create_number_order_from_quote)
    monkeypatch.setattr(miniapp, "get_order", _fake_get_order)
    monkeypatch.setattr(miniapp, "_order_payload_with_events", _fake_order_payload_with_events)
    monkeypatch.setattr(miniapp, "_recent_order_events_payload", _fake_recent_events)
    monkeypatch.setattr(miniapp, "get_user_wallet_balance", _fake_balance)
    request = make_mocked_request(
        "POST",
        "/mini/numbers/api/purchase",
        headers={"Content-Type": "application/json", "Idempotency-Key": "purchase-1"},
    )
    request._read_bytes = json.dumps({"quote_token": quote_token}).encode("utf-8")

    response = await miniapp.purchase_temp(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["create"]["quote_token"] == quote_token
    assert calls["create"]["idempotency_key"] == "purchase-1"
    assert miniapp._api_verify_quote_token(quote_token)["mode"] == mode
    assert payload["order"]["id"] == order_id
    assert payload["order"]["mode"] == mode


@pytest.mark.asyncio
async def test_numbers_miniapp_purchase_rejects_non_api_quote_tokens(monkeypatch):
    async def _fake_load_or_create_user(_auth):
        return {"language": "en"}

    monkeypatch.setattr(
        miniapp,
        "_require_auth",
        lambda _request: {"user_id": 123, "user": {"language_code": "en"}},
    )
    monkeypatch.setattr(miniapp, "_load_or_create_user", _fake_load_or_create_user)
    request = make_mocked_request(
        "POST",
        "/mini/numbers/api/purchase",
        headers={"Content-Type": "application/json", "Idempotency-Key": "legacy-purchase-1"},
    )
    request._read_bytes = json.dumps({"quote_token": "legacy-miniapp-token.invalid"}).encode("utf-8")

    response = await miniapp.purchase_temp(request)
    payload = json.loads(response.text)

    assert response.status == 400
    assert payload["code"] == "invalid_quote"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "handler_name", "service_name"),
    [
        ("sms", "rental_sms_order", "_api_rental_sms_state"),
        ("finish", "finish_order", "_api_finish_rental_order"),
        ("renew", "renew_order", "_api_renew_rental_order"),
        ("wake", "wake_order", "_api_wake_rental_order"),
        ("notes", "notes_order", "_api_rental_notes_state"),
    ],
)
async def test_numbers_miniapp_rental_actions_use_shared_services(monkeypatch, action, handler_name, service_name):
    raw_id = str(miniapp.ObjectId())
    source_order = {
        "_id": raw_id,
        "number_mode": "rental",
        "user_id": 123,
        "reseller_id": 123,
        "status": "success",
        "provider": "herosms",
        "provider_order_id": "rent-1",
        "rental_is_renewable": True,
    }
    calls: dict = {}

    async def _fake_load_or_create_user(_auth):
        return {"language": "en"}

    async def _fake_get_order(order_id):
        if str(order_id) == raw_id:
            return dict(source_order)
        if str(order_id) == "shared-rental-order":
            return {"_id": "shared-rental-order", "number_mode": "rental", "user_id": 123, "status": "success"}
        return None

    async def _fake_shared_service(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        payload = {"ok": True, "order": {"id": "shared-rental-order"}}
        if action == "sms":
            payload["messages"] = ["Code 111"]
        if action == "notes":
            payload["notes"] = "memo"
            payload["tags"] = ["vip"]
        return payload

    async def _fake_order_payload_with_events(order, lang):
        return {"id": str(order.get("_id")), "mode": order.get("number_mode"), "lang": lang, "events": []}

    async def _fake_recent_events(_order_id, _lang, limit=5):
        return []

    monkeypatch.setattr(
        miniapp,
        "_require_auth",
        lambda _request: {"user_id": 123, "user": {"language_code": "en"}},
    )
    monkeypatch.setattr(miniapp, "_load_or_create_user", _fake_load_or_create_user)
    monkeypatch.setattr(miniapp, "get_order", _fake_get_order)
    monkeypatch.setattr(miniapp, service_name, _fake_shared_service)
    monkeypatch.setattr(miniapp, "_order_payload_with_events", _fake_order_payload_with_events)
    monkeypatch.setattr(miniapp, "_recent_order_events_payload", _fake_recent_events)

    request = make_mocked_request(
        "POST",
        f"/mini/numbers/api/orders/{raw_id}/{action}",
        headers={"Content-Type": "application/json", "Idempotency-Key": f"rental-{action}-1"},
        match_info={"order_id": raw_id},
    )
    request._read_bytes = b"{}"

    response = await getattr(miniapp, handler_name)(request)
    payload = json.loads(response.text)

    assert response.status == 200
    if action == "renew":
        assert calls["kwargs"]["order"] == source_order
        assert calls["kwargs"]["user_id"] == 123
        assert calls["kwargs"]["idempotency_key"] == f"rental-{action}-1"
        assert calls["kwargs"]["source"] == "numbers_miniapp"
    else:
        assert calls["args"] == (source_order,)
        assert calls["kwargs"]["source"] == "numbers_miniapp"
    assert payload["order"]["id"] == "shared-rental-order"


def test_provider_terminal_status_classifier_keeps_waiting_states_open():
    assert miniapp._provider_terminal_refund_reason("STATUS_WAIT_CODE", allow_missing=True) == ""
    assert miniapp._provider_terminal_refund_reason({"error_code": "wait_sms"}, allow_missing=True) == ""
    assert miniapp._provider_terminal_refund_reason("NO_ACTIVATION", allow_missing=True) == "provider_missing_or_expired"
    assert miniapp._provider_terminal_refund_reason({"status": "Timed Out"}, allow_missing=True) == "provider_missing_or_expired"
    assert miniapp._provider_terminal_refund_reason("provider request timeout", allow_missing=True) == ""
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

    async def _fake_api_refresh(order_arg):
        calls["api_refresh"] = order_arg["_id"]
        stored.update(
            {
                "status": "cancelled",
                "temp_wait_state": "refunded",
                "temp_provider_terminal_reason": "provider_missing_or_expired",
            }
        )
        return {"ok": True, "order": {"id": order_arg["_id"], "status": "cancelled"}}

    monkeypatch.setitem(miniapp.PROVIDERS, "herosms", _DummyProvider())
    monkeypatch.setattr(miniapp, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(miniapp, "get_order", _fake_get_order)
    monkeypatch.setattr(miniapp, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(miniapp, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(miniapp, "fetch_provider_sms", _fake_fetch_provider_sms)
    monkeypatch.setattr(miniapp, "_log_temp_event", _fake_log)
    monkeypatch.setattr(miniapp, "_log_number_event_from_order", _fake_log)
    monkeypatch.setattr(miniapp, "_api_refresh_number_order", _fake_api_refresh)

    refreshed = await miniapp._refresh_temp_order(dict(stored))

    assert calls["api_refresh"] == "order-old"
    assert "fetch" not in calls
    assert refreshed["status"] == "cancelled"
    assert refreshed["temp_wait_state"] == "refunded"
    assert refreshed["temp_provider_terminal_reason"] == "provider_missing_or_expired"


@pytest.mark.asyncio
async def test_refresh_refund_pending_order_credits_wallet_when_provider_timed_out(monkeypatch):
    now = datetime.now(UTC)
    stored = {
        "_id": "order-pending-timeout",
        "number_mode": "temp",
        "status": "success",
        "user_id": 123,
        "reseller_id": 123,
        "provider": "textverified",
        "provider_order_id": "prov-timeout",
        "provider_number": "+15703604255",
        "temp_service_key": "gmail",
        "temp_country": "1",
        "selling_price": 0.83,
        "base_price": 0.75,
        "created_at": now - timedelta(minutes=20),
        "temp_wait_started_at": now - timedelta(minutes=20),
        "temp_wait_timeout_sec": 300,
        "temp_wait_state": "refund_pending",
        "temp_codes": [],
        "temp_codes_count": 0,
    }
    calls: dict = {}

    class _DummyProvider:
        async def cancel(self, _activation_id):
            raise AssertionError("terminal provider status should finalize local refund before cancel retry")

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
        return {"success": True, "messages": [], "raw": {"status": "Timed Out"}}

    async def _fake_log(*args, **kwargs):
        return None

    async def _fake_api_refresh(order_arg):
        calls["api_refresh"] = order_arg["_id"]
        stored.update(
            {
                "status": "cancelled",
                "temp_wait_state": "refunded",
                "temp_provider_terminal_reason": "provider_missing_or_expired",
            }
        )
        return {"ok": True, "order": {"id": order_arg["_id"], "status": "cancelled"}}

    monkeypatch.setitem(miniapp.PROVIDERS, "textverified", _DummyProvider())
    monkeypatch.setattr(miniapp, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(miniapp, "get_order", _fake_get_order)
    monkeypatch.setattr(miniapp, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(miniapp, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(miniapp, "fetch_provider_sms", _fake_fetch_provider_sms)
    monkeypatch.setattr(miniapp, "_log_temp_event", _fake_log)
    monkeypatch.setattr(miniapp, "_log_number_event_from_order", _fake_log)
    monkeypatch.setattr(miniapp, "_api_refresh_number_order", _fake_api_refresh)

    refreshed = await miniapp._refresh_temp_order(dict(stored))

    assert calls["api_refresh"] == "order-pending-timeout"
    assert "fetch" not in calls
    assert refreshed["status"] == "cancelled"
    assert refreshed["temp_wait_state"] == "refunded"
    assert refreshed["temp_provider_terminal_reason"] == "provider_missing_or_expired"


@pytest.mark.asyncio
async def test_numbers_miniapp_refresh_voice_uses_shared_refresh_service(monkeypatch):
    now = datetime.now(UTC)
    raw_id = "64b64c0f0f0f0f0f0f0f0f0f"
    stored = {
        "_id": raw_id,
        "number_mode": "voice",
        "status": "success",
        "user_id": 123,
        "reseller_id": 123,
        "provider": "textverified",
        "provider_order_id": "prov-voice",
        "provider_number": "+15703604255",
        "temp_service_key": "gmail",
        "temp_country": "1",
        "selling_price": 0.83,
        "base_price": 0.75,
        "created_at": now,
        "temp_wait_started_at": now,
        "temp_wait_timeout_sec": 300,
        "temp_wait_state": "waiting_for_call",
        "voice_calls": [],
    }
    calls: dict = {}

    async def _fake_get_order(_order_id):
        return dict(stored)

    async def _fake_load_or_create_user(_auth):
        return {"language": "en"}

    async def _fake_api_refresh(order):
        calls["refresh"] = dict(order)
        stored["api_last_refresh_mode"] = "provider_webhook"
        return {"ok": True, "message": "Waiting for provider webhook.", "order": {"id": raw_id}}

    async def _fake_order_payload_with_events(order, lang):
        calls["payload"] = dict(order)
        return {"id": str(order.get("_id")), "mode": order.get("number_mode"), "refresh_mode": order.get("api_last_refresh_mode")}

    async def _fake_balance(user_id, reseller_id):
        calls["balance"] = (user_id, reseller_id)
        return 4.25

    monkeypatch.setattr(
        miniapp,
        "_require_auth",
        lambda _request: {"user_id": 123, "user": {"language_code": "en"}},
    )
    monkeypatch.setattr(miniapp, "_load_or_create_user", _fake_load_or_create_user)
    monkeypatch.setattr(miniapp, "get_order", _fake_get_order)
    monkeypatch.setattr(miniapp, "_api_refresh_number_order", _fake_api_refresh)
    monkeypatch.setattr(miniapp, "_order_payload_with_events", _fake_order_payload_with_events)
    monkeypatch.setattr(miniapp, "get_user_wallet_balance", _fake_balance)

    request = make_mocked_request(
        "POST",
        f"/mini/numbers/api/orders/{raw_id}/refresh",
        match_info={"order_id": raw_id},
    )

    response = await miniapp.refresh_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["refresh"]["_id"] == raw_id
    assert payload["message"] == "Waiting for provider webhook."
    assert payload["order"] == {"id": raw_id, "mode": "voice", "refresh_mode": "provider_webhook"}
    assert payload["balance_label"] == "$4.25"


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
    assert "base_price_label" not in payload
    assert payload["actions"]["rental_sms"]["endpoint"] == "/mini/numbers/api/orders/rental-order-id/sms"
    assert payload["actions"]["rental_sms"]["idempotency_key"] == "miniapp-rental-sms-rental-order-id"
    assert payload["actions"]["rental_renew"]["enabled"] is True
    assert payload["actions"]["rental_renew"]["confirm_label_key"] == "renew"
    assert payload["actions"]["rental_renew"]["idempotency_key"] == "miniapp-rental-renew-rental-order-id"
    assert payload["actions"]["rental_wake"]["enabled"] is True
    assert payload["actions"]["test_active"]["enabled"] is True
    assert payload["actions"]["test_active"]["endpoint"] == "/mini/numbers/api/orders/rental-order-id/wake"
    assert payload["actions"]["rental_notes"]["enabled"] is True
    assert payload["actions"]["report_issue"]["enabled"] is True
    assert payload["actions"]["report_issue"]["method"] == "CLIENT"
    assert payload["actions"]["report_issue"]["label_key"] == "reportIssue"
    assert payload["actions"]["rental_finish"]["endpoint"] == "/mini/numbers/api/orders/rental-order-id/finish"
    assert payload["actions"]["rental_finish"]["confirm_label_key"] == "finish"
    details = {item["key"]: item["value"] for item in payload["details"]}
    assert details["provider"] == "Bravo"
    assert details["country"] == "United States"
    assert details["duration"] == "1d"


def test_numbers_rental_order_payload_does_not_expose_manual_cancel():
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
    assert payload["can_cancel"] is False


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
    assert ("GET", "/mini/numbers-v2") in routes
    assert ("GET", "/mini/numbers-v2/static/{name}") in routes
    assert ("GET", "/mini/numbers/api/bootstrap") in routes
    assert ("GET", "/mini/numbers/api/country-suggestions") in routes
    assert ("GET", "/mini/numbers/api/account") in routes
    assert ("POST", "/mini/numbers/api/account/language") in routes
    assert ("GET", "/mini/numbers/api/recharge") in routes
    assert ("POST", "/mini/numbers/api/recharge/submit") in routes
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
    assert ("POST", "/mini/numbers/api/orders/{order_id}/cancel") not in routes


def test_numbers_miniapp_frontend_has_no_order_auto_polling():
    source = (Path(miniapp.__file__).parents[2] / "webapp" / "numbers" / "app.js").read_text(encoding="utf-8")

    assert "orderPollTimer" not in source
    assert "ORDER_POLL_INTERVAL_MS" not in source
    assert "orderNeedsPolling" not in source
    assert "scheduleOrderPoll" not in source
    assert "orderActionHeaders(order, key, options.headers)" in source
    assert "orderActionIdempotencyKey(order, key)" in source
    assert "miniapp-purchase-" in source
    assert "miniapp-rental-" not in source
    assert "miniapp-replace-" not in source
    assert "miniapp-alternate-" not in source
    assert "state.client = payload.client || {}" in source


def test_numbers_support_categories_are_numbers_scoped():
    rows = miniapp._support_categories_payload("en")

    assert [row["key"] for row in rows] == ["numbers", "user_balance"]
    assert rows[0]["label"] == "Numbers orders"
