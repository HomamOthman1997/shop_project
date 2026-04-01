from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database.mongo import db
from services.digital_products.catalog_service import get_catalog_snapshot


async def run_digital_products_validation() -> dict[str, Any]:
    started = datetime.now(UTC)
    issues: list[str] = []
    snapshot = await get_catalog_snapshot(force=True)
    enabled = bool(snapshot.get("enabled"))
    games = list(snapshot.get("games") or [])
    gift_categories = list(snapshot.get("gift_categories") or [])

    if not enabled:
        issues.append("catalog_disabled")
    if enabled and not games:
        issues.append("games_empty")
    if enabled and not gift_categories:
        issues.append("gift_categories_empty")

    products_by_category = snapshot.get("products_by_category") or {}
    if not isinstance(products_by_category, dict):
        issues.append("products_by_category_invalid")
        products_by_category = {}

    empty_categories = 0
    for cat in gift_categories[:40]:
        cat_id = str(cat.get("id") or "").strip()
        if not cat_id:
            issues.append("gift_category_missing_id")
            continue
        rows = products_by_category.get(cat_id) or []
        if not isinstance(rows, list) or not rows:
            empty_categories += 1
    if empty_categories > 0:
        issues.append(f"gift_categories_without_products:{empty_categories}")

    report: dict[str, Any] = {
        "kind": "digital_products_validation",
        "created_at": datetime.now(UTC),
        "started_at": started,
        "enabled": enabled,
        "games_count": len(games),
        "gift_categories_count": len(gift_categories),
        "issues": sorted(set(issues)),
        "healthy": len(issues) == 0,
    }
    await db.ops_validation_reports.insert_one(report)
    return report
