from datetime import UTC, datetime, timedelta

from aiohttp import web

from services.numbers import miniapp


def test_numbers_bootstrap_payload_has_core_filters():
    miniapp._BOOTSTRAP_CACHE["data"] = None

    payload = miniapp._bootstrap_payload()

    assert payload["defaults"] == {"mode": "temp", "service": "telegram", "country": "1", "state": "none"}
    assert [item["key"] for item in payload["modes"]] == ["temp", "rental", "voice"]
    assert any(item["code"] == "1" for item in payload["countries"])
    assert any(item["code"] == "none" for item in payload["states_us"])
    assert any(item["key"] == "telegram" for item in payload["services"])


def test_numbers_price_rows_use_public_provider_ids(monkeypatch):
    monkeypatch.setattr(miniapp.settings, "numbers_success_rate_display_min_attempts", 1, raising=False)

    rows = miniapp._normalize_provider_rows(
        {
            "alpha_provider": {"price": 1.25, "base_price": 1.0, "success_rate": 88, "success_attempts": 10},
            "beta_provider": {
                "price": 0,
                "available_for_buy": False,
                "provider_reason": "provider_balance_low",
                "success_attempts": 0,
            },
        },
        "temp",
    )

    assert rows[0]["provider_id"].startswith("S")
    assert rows[0]["price_label"] == "$1.25"
    assert rows[0]["success_rate"] == "88%"
    assert rows[-1]["available"] is False
    assert rows[-1]["reason"] == "Provider balance is low"


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
            "selling_price": 1.2,
            "base_price": 1.0,
        }
    )

    assert payload["mode"] == "rental"
    assert payload["can_renew"] is True
    assert payload["can_wake"] is True
    assert payload["can_notes"] is True
    assert payload["can_finish"] is True
    assert payload["notes"] == "Keep alive"
    assert payload["tags"] == ["vip", "login"]
    details = {item["key"]: item["value"] for item in payload["details"]}
    assert details["provider"] == "Bravo"
    assert details["country"] == "United States"
    assert details["duration"] == "1d"


def test_register_numbers_routes_adds_public_endpoints():
    app = web.Application()

    miniapp.register_numbers_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/mini/numbers") in routes
    assert ("GET", "/mini/numbers/static/{name}") in routes
    assert ("GET", "/mini/numbers/api/bootstrap") in routes
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
    assert ("POST", "/mini/numbers/api/orders/{order_id}/finish") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/renew") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/wake") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/notes") in routes
    assert ("POST", "/mini/numbers/api/orders/{order_id}/cancel") in routes


def test_numbers_support_categories_are_numbers_scoped():
    rows = miniapp._support_categories_payload("en")

    assert [row["key"] for row in rows] == ["numbers", "user_balance"]
    assert rows[0]["label"] == "Numbers orders"
