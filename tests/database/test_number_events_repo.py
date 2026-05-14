import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.getcwd())

from database.number_events_repo import build_numbers_report_from_events


def test_build_numbers_report_from_events_summarizes_core_metrics():
    now = datetime.now(UTC)
    since = now - timedelta(days=7)
    events = [
        {
            "order_id": "o1",
            "user_id": 10,
            "reseller_id": 20,
            "provider": "textverified",
            "service_id": "gmail",
            "number_mode": "temp",
            "event": "wallet_charged",
            "status_after": "paid",
            "created_at": since + timedelta(hours=1),
            "payload": {},
        },
        {
            "order_id": "o1",
            "user_id": 10,
            "reseller_id": 20,
            "provider": "textverified",
            "service_id": "gmail",
            "number_mode": "temp",
            "event": "provider_buy_success",
            "status_after": "success",
            "created_at": since + timedelta(hours=1, minutes=1),
            "payload": {},
        },
        {
            "order_id": "o1",
            "user_id": 10,
            "reseller_id": 20,
            "provider": "textverified",
            "service_id": "gmail",
            "number_mode": "temp",
            "event": "code_received",
            "status_after": "success",
            "created_at": since + timedelta(hours=1, minutes=2),
            "payload": {"seconds_since_purchase": 45},
        },
        {
            "order_id": "o2",
            "user_id": 11,
            "reseller_id": 21,
            "provider": "smspool",
            "service_id": "discord",
            "number_mode": "temp",
            "event": "provider_buy_failed",
            "status_after": "refunded",
            "created_at": since + timedelta(hours=2),
            "payload": {},
        },
        {
            "order_id": "o2",
            "user_id": 11,
            "reseller_id": 21,
            "provider": "smspool",
            "service_id": "discord",
            "number_mode": "temp",
            "event": "refund_success",
            "status_after": "refunded",
            "created_at": since + timedelta(hours=2, minutes=1),
            "payload": {},
        },
        {
            "order_id": "o3",
            "user_id": 12,
            "reseller_id": 22,
            "provider": "herosms",
            "service_id": "google:rental",
            "number_mode": "rental",
            "event": "auto_protection_triggered",
            "status_after": "cancelled",
            "created_at": since + timedelta(hours=3),
            "payload": {},
        },
        {
            "order_id": "o3",
            "user_id": 12,
            "reseller_id": 22,
            "provider": "herosms",
            "service_id": "google:rental",
            "number_mode": "rental",
            "event": "cancelled_refunded",
            "status_after": "cancelled",
            "created_at": since + timedelta(hours=3, minutes=1),
            "payload": {},
        },
        {
            "order_id": "o4",
            "user_id": 13,
            "reseller_id": 23,
            "provider": "vak",
            "service_id": "whatsapp",
            "number_mode": "temp",
            "event": "second_code_attempted",
            "status_after": "success",
            "created_at": since + timedelta(hours=4),
            "payload": {"seconds_since_first_code": 1200},
        },
        {
            "order_id": "o4",
            "user_id": 13,
            "reseller_id": 23,
            "provider": "vak",
            "service_id": "whatsapp",
            "number_mode": "temp",
            "event": "second_code_provider_rejected",
            "status_after": "success",
            "created_at": since + timedelta(hours=4, minutes=1),
            "payload": {"seconds_since_first_code": 1260},
        },
    ]

    report = build_numbers_report_from_events(events, since=since, until=now)

    assert report["totals"]["events"] == 9
    assert report["totals"]["total_orders_seen"] == 4
    assert report["event_counts"]["provider_buy_failed"] == 1
    assert report["event_counts"]["refund_success"] == 1
    assert any(row["provider"] == "textverified" and row["codes_received"] == 1 for row in report["provider_service_summary"])
    assert any(
        row["provider"] == "vak" and row["second_code_attempts"] == 1 and row["second_code_failures"] == 1
        for row in report["provider_service_summary"]
    )
    assert any(row["provider"] == "smspool" and row["count"] == 1 for row in report["top_provider_failures"])
    assert any(row["provider"] == "vak" and row["count"] == 1 for row in report["top_second_code_failures"])
    assert any(row["provider"] == "herosms" and row["count"] == 1 for row in report["top_protection_saved"])
