import os
import sys

sys.path.insert(0, os.getcwd())

from services.digital_products.product_watchlist import (
    active_product_provider_sources,
    active_product_watchlist,
    bittopup_watch_urls,
    load_product_provider_sources,
    provider_sources_by_package,
    provider_sources_by_product,
    validate_product_provider_sources,
    validate_product_watchlist,
    watchlist_by_provider,
)


def test_product_watchlist_loads_seed_products():
    rows = active_product_watchlist()

    keys = {row.product_key for row in rows}
    assert "pubg" in keys
    assert "chatgpt_via_apple" in keys
    assert "soul_chill" in keys
    assert "mico_live" in keys
    assert "kwai" in keys


def test_product_watchlist_keeps_g2bulk_first_policy():
    rows = active_product_watchlist()
    by_key = {row.product_key: row for row in rows}

    assert by_key["pubg"].preferred_provider == "g2bulk"
    assert by_key["pubg"].sourcing_policy == "g2bulk_first"
    assert by_key["chatgpt_via_apple"].sourcing_policy == "indirect_apple"
    assert by_key["syriatel"].category == "syrian_services"
    assert by_key["electricity_bills"].category == "syrian_services"


def test_product_watchlist_provider_grouping_and_bittopup_urls():
    rows = active_product_watchlist()
    grouped = watchlist_by_provider(rows)
    urls = bittopup_watch_urls(rows)

    assert "g2bulk" in grouped
    assert "bittopup" in grouped
    assert "https://bittopup.com/goods/soulchill" in urls
    assert "https://bittopup.com/goods/pubg-uc" in urls


def test_product_watchlist_validation_detects_duplicate_and_missing_fields():
    rows = active_product_watchlist()
    broken = [
        *rows[:1],
        rows[0],
        rows[0].__class__(
            product_key="broken",
            category="",
            priority="",
            display_name="",
            region_policy="global",
            default_duration="",
            unit_kind="",
            preferred_provider="",
            sourcing_policy="",
            g2bulk_hint="",
            bittopup_slug="",
            g2g_search_query="",
            public_note="",
            active=True,
        ),
    ]

    codes = {issue["code"] for issue in validate_product_watchlist(broken)}

    assert "duplicate_product" in codes
    assert "missing_category" in codes
    assert "missing_display_name" in codes
    assert "missing_preferred_provider" in codes
    assert "missing_sourcing_policy" in codes


def test_empty_product_provider_sources_seed_is_supported():
    assert active_product_provider_sources() == []


def test_product_provider_source_indexes_and_validation(tmp_path):
    csv_path = tmp_path / "sources.csv"
    csv_path.write_text(
        "\n".join(
            [
                "product_key,package_key,package_name,duration,provider,fulfillment_mode,source_ref,source_url,price_usd,available,public_note",
                "netflix,netflix_1m,Netflix 1 Month,1 month,external,manual_topup,netflix-a,https://example.test/a,4.25,true,",
                "netflix,netflix_1m,Netflix 1 Month,1 month,g2g,manual_topup,netflix-b,https://example.test/b,4.75,true,",
                "netflix,netflix_1m,Netflix 1 Month,1 month,g2g,manual_topup,netflix-b,https://example.test/b,4.75,true,",
                "unknown,,Broken,,external,manual_topup,,https://example.test/broken,0,true,",
            ]
        ),
        encoding="utf-8",
    )

    sources = load_product_provider_sources(csv_path)
    by_product = provider_sources_by_product(sources)
    by_package = provider_sources_by_package(sources)
    issues = validate_product_provider_sources(sources, known_product_keys={"netflix"})

    assert len(by_product["netflix"]) == 3
    assert len(by_package[("netflix", "netflix_1m")]) == 3
    codes = {issue["code"] for issue in issues}
    assert "duplicate_source" in codes
    assert "unknown_product" in codes
    assert "missing_package_key" in codes
    assert "missing_source_ref" in codes
    assert "invalid_price" in codes
