import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

from database.number_events_repo import build_numbers_report


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _fmt_provider_row(row: dict) -> str:
    avg_sms = row.get("avg_seconds_to_first_sms")
    avg_sms_text = f"{avg_sms}s" if avg_sms is not None else "-"
    return (
        f"[{row.get('number_mode')}] {row.get('provider')} | {row.get('service_id')} | "
        f"attempts={row.get('purchase_attempts', 0)} | "
        f"provider_ok={row.get('provider_success', 0)} | "
        f"codes={row.get('codes_received', 0)} | "
        f"refunds={row.get('refunds', 0)} | "
        f"provider_failures={row.get('provider_failures', 0)} | "
        f"second_code={row.get('second_code_requests', 0)} | "
        f"saved_by_protection={row.get('protection_saved', 0)} | "
        f"avg_first_sms={avg_sms_text}"
    )


async def _main() -> None:
    days = 7
    try:
        if len(sys.argv) > 1:
            days = max(1, int(sys.argv[1]))
    except Exception:
        days = 7

    report = await build_numbers_report(days=days)
    _section(f"Numbers Report ({days}d)")
    print(json.dumps(report["window"], indent=2, ensure_ascii=False))

    _section("Totals")
    print(json.dumps(report["totals"], indent=2, ensure_ascii=False))

    _section("Event Counts")
    print(json.dumps(report["event_counts"], indent=2, ensure_ascii=False))

    _section("Provider / Service Summary")
    for row in report.get("provider_service_summary", [])[:20]:
        print(_fmt_provider_row(row))

    _section("Top No-Code Cases")
    for row in report.get("top_no_code_cases", []):
        print(f"[{row['number_mode']}] {row['provider']} | {row['service_id']} | count={row['count']}")

    _section("Top Provider Failures")
    for row in report.get("top_provider_failures", []):
        print(f"[{row['number_mode']}] {row['provider']} | {row['service_id']} | count={row['count']}")

    _section("Top Second-Code Usage")
    for row in report.get("top_second_code_usage", []):
        print(f"[{row['number_mode']}] {row['provider']} | {row['service_id']} | count={row['count']}")

    _section("Protection Saved")
    for row in report.get("top_protection_saved", []):
        print(f"[{row['number_mode']}] {row['provider']} | {row['service_id']} | count={row['count']}")

    _section("Suspicious Users")
    for row in report.get("suspicious_users", []):
        print(f"user_id={row['user_id']} | no_code_events={row['no_code_events']}")


if __name__ == "__main__":
    asyncio.run(_main())
