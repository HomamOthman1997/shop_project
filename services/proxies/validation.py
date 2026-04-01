from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database.mongo import db
from services.proxies.manager import PROXY_PROVIDERS, get_proxy_catalog


async def run_proxy_catalog_validation() -> dict[str, Any]:
    started = datetime.now(UTC)
    issues: list[str] = []
    provider_counts: dict[str, int] = {}

    catalog = await get_proxy_catalog()
    if not isinstance(catalog, list):
        catalog = []
        issues.append("catalog_not_list")

    for provider in PROXY_PROVIDERS.keys():
        provider_counts[provider] = 0
    for item in catalog:
        provider = str(item.get("provider") or "").strip().lower()
        if provider:
            provider_counts[provider] = int(provider_counts.get(provider, 0)) + 1
        if float(item.get("price") or 0.0) < 0:
            issues.append("negative_price")
        if not str(item.get("offer_id") or "").strip():
            issues.append("missing_offer_id")

    for provider in PROXY_PROVIDERS.keys():
        if provider_counts.get(provider, 0) <= 0:
            issues.append(f"provider_empty_catalog:{provider}")

    report = {
        "kind": "proxy_catalog_validation",
        "created_at": datetime.now(UTC),
        "started_at": started,
        "total_offers": len(catalog),
        "provider_counts": provider_counts,
        "issues": sorted(set(issues)),
        "healthy": len(issues) == 0,
    }
    await db.ops_validation_reports.insert_one(report)
    return report
