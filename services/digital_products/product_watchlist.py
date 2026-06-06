from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


WATCHLIST_PATH = Path(__file__).resolve().parents[2] / "data" / "digital_product_watchlist.csv"
PROVIDER_SOURCES_PATH = Path(__file__).resolve().parents[2] / "data" / "digital_product_provider_sources.csv"
BITTOPUP_GOODS_BASE_URL = "https://bittopup.com/goods"


@dataclass(frozen=True)
class ProductWatchlistItem:
    product_key: str
    category: str
    priority: str
    display_name: str
    region_policy: str
    default_duration: str
    unit_kind: str
    preferred_provider: str
    sourcing_policy: str
    g2bulk_hint: str
    bittopup_slug: str
    g2g_search_query: str
    public_note: str
    active: bool

    @property
    def bittopup_url(self) -> str:
        return f"{BITTOPUP_GOODS_BASE_URL}/{self.bittopup_slug}" if self.bittopup_slug else ""


@dataclass(frozen=True)
class ProductProviderSource:
    product_key: str
    package_key: str
    package_name: str
    duration: str
    provider: str
    fulfillment_mode: str
    source_ref: str
    source_url: str
    price_usd: float
    available: bool
    public_note: str

    @property
    def source_key(self) -> tuple[str, str, str, str]:
        return (self.product_key, self.package_key, self.provider, self.source_ref)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float:
    try:
        return round(float(str(value or "").strip()), 6)
    except Exception:
        return 0.0


def load_product_watchlist(path: str | Path = WATCHLIST_PATH) -> list[ProductWatchlistItem]:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = csv.DictReader(fh)
        return [
            ProductWatchlistItem(
                product_key=_clean(row.get("product_key")),
                category=_clean(row.get("category")),
                priority=_clean(row.get("priority")),
                display_name=_clean(row.get("display_name")),
                region_policy=_clean(row.get("region_policy")),
                default_duration=_clean(row.get("default_duration")),
                unit_kind=_clean(row.get("unit_kind")),
                preferred_provider=_clean(row.get("preferred_provider")).lower(),
                sourcing_policy=_clean(row.get("sourcing_policy")),
                g2bulk_hint=_clean(row.get("g2bulk_hint")),
                bittopup_slug=_clean(row.get("bittopup_slug")),
                g2g_search_query=_clean(row.get("g2g_search_query")),
                public_note=_clean(row.get("public_note")),
                active=_truthy(row.get("active")),
            )
            for row in rows
            if _clean(row.get("product_key"))
        ]


def active_product_watchlist(path: str | Path = WATCHLIST_PATH) -> list[ProductWatchlistItem]:
    return [item for item in load_product_watchlist(path) if item.active]


def watchlist_by_provider(items: Iterable[ProductWatchlistItem]) -> dict[str, list[ProductWatchlistItem]]:
    grouped: dict[str, list[ProductWatchlistItem]] = {}
    for item in items:
        grouped.setdefault(item.preferred_provider or "external", []).append(item)
    return grouped


def validate_product_watchlist(items: Iterable[ProductWatchlistItem]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        key = item.product_key
        if not key:
            issues.append({"code": "missing_product_key", "product_key": ""})
            continue
        if key in seen:
            issues.append({"code": "duplicate_product", "product_key": key})
        seen.add(key)
        if not item.category:
            issues.append({"code": "missing_category", "product_key": key})
        if not item.display_name:
            issues.append({"code": "missing_display_name", "product_key": key})
        if not item.preferred_provider:
            issues.append({"code": "missing_preferred_provider", "product_key": key})
        if not item.sourcing_policy:
            issues.append({"code": "missing_sourcing_policy", "product_key": key})
    return issues


def bittopup_watch_urls(items: Iterable[ProductWatchlistItem]) -> list[str]:
    urls = [item.bittopup_url for item in items if item.active and item.bittopup_url]
    return sorted(set(urls))


def load_product_provider_sources(path: str | Path = PROVIDER_SOURCES_PATH) -> list[ProductProviderSource]:
    source = Path(path)
    if not source.exists():
        return []
    with source.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = csv.DictReader(fh)
        return [
            ProductProviderSource(
                product_key=_clean(row.get("product_key")),
                package_key=_clean(row.get("package_key")),
                package_name=_clean(row.get("package_name")),
                duration=_clean(row.get("duration")),
                provider=_clean(row.get("provider")).lower(),
                fulfillment_mode=_clean(row.get("fulfillment_mode")),
                source_ref=_clean(row.get("source_ref")),
                source_url=_clean(row.get("source_url")),
                price_usd=_float(row.get("price_usd")),
                available=_truthy(row.get("available")),
                public_note=_clean(row.get("public_note")),
            )
            for row in rows
            if _clean(row.get("product_key")) and _clean(row.get("provider"))
        ]


def active_product_provider_sources(path: str | Path = PROVIDER_SOURCES_PATH) -> list[ProductProviderSource]:
    return [
        item
        for item in load_product_provider_sources(path)
        if item.available and item.price_usd > 0 and item.package_key and item.source_ref
    ]


def provider_sources_by_product(
    sources: Iterable[ProductProviderSource],
) -> dict[str, list[ProductProviderSource]]:
    grouped: dict[str, list[ProductProviderSource]] = {}
    for source in sources:
        grouped.setdefault(source.product_key, []).append(source)
    return grouped


def provider_sources_by_package(
    sources: Iterable[ProductProviderSource],
) -> dict[tuple[str, str], list[ProductProviderSource]]:
    grouped: dict[tuple[str, str], list[ProductProviderSource]] = {}
    for source in sources:
        grouped.setdefault((source.product_key, source.package_key), []).append(source)
    return grouped


def validate_product_provider_sources(
    sources: Iterable[ProductProviderSource],
    *,
    known_product_keys: set[str] | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    known = set(known_product_keys or set())
    for source in sources:
        row_key = "|".join(source.source_key)
        if known and source.product_key not in known:
            issues.append({"code": "unknown_product", "source": row_key, "product_key": source.product_key})
        if not source.package_key:
            issues.append({"code": "missing_package_key", "source": row_key, "product_key": source.product_key})
        if not source.package_name:
            issues.append({"code": "missing_package_name", "source": row_key, "product_key": source.product_key})
        if not source.source_ref:
            issues.append({"code": "missing_source_ref", "source": row_key, "product_key": source.product_key})
        if source.price_usd <= 0:
            issues.append({"code": "invalid_price", "source": row_key, "product_key": source.product_key})
        if source.source_key in seen:
            issues.append({"code": "duplicate_source", "source": row_key, "product_key": source.product_key})
        seen.add(source.source_key)
    return issues
