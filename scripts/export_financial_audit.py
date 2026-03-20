#!/usr/bin/env python3
import asyncio
import csv
import os
import sys
from datetime import datetime

root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root not in sys.path:
    sys.path.insert(0, root)

from database.financial_ledger import export_financial_audit_rows


async def main(days: int = 30, output_path: str | None = None):
    rows = await export_financial_audit_rows(days=days, max_rows=500)
    if output_path is None:
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(root, "data", f"financial_audit_{stamp}.csv")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()} or {"kind"})
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"Exported {len(rows)} audit rows to: {output_path}")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) >= 2 else 30
    output = sys.argv[2] if len(sys.argv) >= 3 else None
    asyncio.run(main(days=days, output_path=output))
