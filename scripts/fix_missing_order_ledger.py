from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from uuid import uuid4

from bson import ObjectId

sys.path.insert(0, os.getcwd())

from config import OWNER_ID
from database.financial_ledger import scan_financial_anomalies
from database.mongo import db


def _to_cycle_key(dt: datetime | None) -> str:
    now = dt or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    return f"{now.year}-{now.month:02d}"


async def _backfill_for_order(order_doc: dict) -> bool:
    order_id = order_doc.get("_id")
    if order_id is None:
        return False

    existing = await db.ledger_entries.find_one(
        {
            "order_id": order_id,
            "reason": "audit_backfill_missing_order_ledger",
        },
        {"_id": 1},
    )
    if existing:
        return False

    created_at = order_doc.get("created_at")
    if not isinstance(created_at, datetime):
        created_at = datetime.now(UTC)
    elif created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)

    now = datetime.now(UTC)
    entry = {
        "tx_uuid": str(uuid4()),
        "order_id": order_id,
        "actor_type": "system",
        "actor_id": int(OWNER_ID),
        "owner_type": "system",
        "owner_id": 0,
        "reseller_id": int(order_doc.get("reseller_id") or 0),
        "wallet_type": "audit_backfill",
        "direction": "noop",
        "amount": 0.0,
        "reason": "audit_backfill_missing_order_ledger",
        "balance_before": None,
        "balance_after": None,
        "cycle_key": _to_cycle_key(created_at),
        "metadata": {
            "backfill_version": 1,
            "backfill_at": now.isoformat(),
            "source": "scripts/fix_missing_order_ledger.py",
            "order_status": str(order_doc.get("status") or ""),
            "service_type": str(order_doc.get("service_type") or ""),
            "service_ref_id": str(order_doc.get("service_ref_id") or order_doc.get("service_id") or ""),
            "retail_amount": float(order_doc.get("retail_amount") or order_doc.get("selling_price") or 0.0),
            "wholesale_amount": float(order_doc.get("wholesale_amount") or order_doc.get("base_price") or 0.0),
        },
        "category": "audit_backfill",
        "tags": ["audit", "backfill", "order"],
        "created_at": now,
    }
    await db.ledger_entries.insert_one(entry)
    return True


async def run(*, days: int = 30, max_rows: int = 200) -> dict:
    before = await scan_financial_anomalies(days=days, max_rows=max_rows)
    missing_rows = list(before.get("orders_missing_ledger") or [])
    fixed = 0
    skipped = 0
    failed = 0
    for row in missing_rows:
        order_id_raw = str(row.get("order_id") or "").strip()
        if not order_id_raw:
            skipped += 1
            continue
        try:
            oid = ObjectId(order_id_raw)
        except Exception:
            skipped += 1
            continue
        order_doc = await db.orders.find_one({"_id": oid})
        if not order_doc:
            skipped += 1
            continue
        try:
            changed = await _backfill_for_order(order_doc)
            if changed:
                fixed += 1
            else:
                skipped += 1
        except Exception:
            failed += 1

    after = await scan_financial_anomalies(days=days, max_rows=max_rows)
    return {
        "days": int(days),
        "before_missing": int(before.get("orders_missing_ledger_count") or 0),
        "after_missing": int(after.get("orders_missing_ledger_count") or 0),
        "fixed": int(fixed),
        "skipped": int(skipped),
        "failed": int(failed),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing order-ledger anomalies with audit marker entries.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-rows", type=int, default=200)
    args = parser.parse_args()
    result = asyncio.run(run(days=max(1, int(args.days)), max_rows=max(1, int(args.max_rows))))
    print(result)


if __name__ == "__main__":
    main()
