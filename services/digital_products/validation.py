from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from config import settings
from database.mongo import db
from services.digital_products.catalog_service import get_catalog_snapshot, za3em_provider_enabled
from services.digital_products.esim_access_client import EsimAccessClient
from services.digital_products.g2bulk_client import G2BulkClient
from services.digital_products.za3em_client import Za3emClient


_ZA3EM_SECTIONS = {
    "games",
    "chat_apps",
    "communications_data",
    "numbers_services",
    "paid_subscriptions",
    "store_cards",
    "social_services",
    "internet_providers",
    "paid_apps",
}


def _count_services(*, games: list[dict[str, Any]], gift_categories: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {"games": len(games)}
    for cat in gift_categories:
        if not isinstance(cat, dict):
            continue
        key = str(cat.get("service_key") or "other").strip() or "other"
        counts[key] = counts.get(key, 0) + int(cat.get("count") or 1)
    return dict(sorted(counts.items()))


async def run_digital_products_validation() -> dict[str, Any]:
    started = datetime.now(UTC)
    issues: list[str] = []
    g2_client = G2BulkClient()
    za3em_client = Za3emClient()
    esim_client = EsimAccessClient()
    za3em_enabled = za3em_provider_enabled()
    provider_status: dict[str, dict[str, Any]] = {
        "g2bulk": {
            "enabled": True,
            "configured": bool(g2_client.configured()),
            "base_url": str(getattr(settings, "g2bulk_base_url", "") or ""),
        },
        "za3em": {
            "enabled": bool(za3em_enabled),
            "configured": bool(za3em_client.configured()),
            "base_url": str(getattr(settings, "za3em_base_url", "") or ""),
        },
        "esim_access": {
            "enabled": bool(esim_client.configured()),
            "configured": bool(esim_client.configured()),
            "base_url": str(getattr(settings, "esim_access_api_base", "") or ""),
        },
    }
    if not g2_client.configured():
        issues.append("g2bulk_not_configured")
    if za3em_enabled and not za3em_client.configured():
        issues.append("za3em_not_configured")
    if za3em_enabled and za3em_client.configured():
        status, data = await za3em_client._request("GET", "/client/api/products")
        provider_status["za3em"]["products_http_status"] = int(status)
        provider_status["za3em"]["products_count"] = len(data) if isinstance(data, list) else 0
        if status != 200:
            issues.append(f"za3em_products_unavailable:{status}")
        elif not isinstance(data, list) or not data:
            issues.append("za3em_products_empty")

    snapshot = await get_catalog_snapshot(force=True)
    enabled = bool(snapshot.get("enabled"))
    games = list(snapshot.get("games") or [])
    gift_categories = list(snapshot.get("gift_categories") or [])
    service_counts = _count_services(games=games, gift_categories=gift_categories)

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

    if za3em_enabled:
        missing_sections = sorted(section for section in _ZA3EM_SECTIONS if service_counts.get(section, 0) <= 0)
        if missing_sections:
            issues.append("za3em_sections_empty:" + ",".join(missing_sections[:8]))

    report: dict[str, Any] = {
        "kind": "digital_products_validation",
        "created_at": datetime.now(UTC),
        "started_at": started,
        "enabled": enabled,
        "games_count": len(games),
        "gift_categories_count": len(gift_categories),
        "service_counts": service_counts,
        "provider_status": provider_status,
        "issues": sorted(set(issues)),
        "healthy": len(issues) == 0,
    }
    await db.ops_validation_reports.insert_one(report)
    return report
