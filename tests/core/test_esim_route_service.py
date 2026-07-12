import os
import sys

sys.path.insert(0, os.getcwd())

from services.digital_products.esim_route_service import (
    available_days,
    build_route_offers,
    build_single_country_offers,
    choose_recommended_offer,
    choose_best_multi_area,
    plans_for_days,
    route_available_days,
    search_countries,
    single_country_plans,
    usage_matches,
)


def test_search_countries_finds_turkey():
    results = search_countries("turk", limit=10)
    assert "Turkey" in results


def test_single_country_plans_exist_for_turkey():
    rows = single_country_plans("Turkey")
    assert rows
    assert any(int(row.get("days") or 0) == 7 for row in rows)


def test_multi_area_match_covers_turkey_cyprus_ukraine():
    match = choose_best_multi_area(["Turkey", "Cyprus", "Ukraine"])
    assert match is not None
    assert match["coverage_full"] is True
    assert "Turkey" in match["covered"]
    assert "Cyprus" in match["covered"]
    assert "Ukraine" in match["covered"]


def test_multi_area_days_and_packages_available():
    match = choose_best_multi_area(["Turkey", "Cyprus"])
    assert match is not None
    days = available_days(match["plans"])
    assert 7 in days
    plans = plans_for_days(match["plans"], 7)
    assert plans


def test_route_available_days_for_multi_country_route():
    days = route_available_days(["Turkey", "Cyprus", "Ukraine"])
    assert 7 in days
    assert 30 in days


def test_usage_matching_filters_small_vs_medium():
    rows = single_country_plans("Turkey")
    assert any(usage_matches(row, "low") for row in rows)
    assert any(usage_matches(row, "mid") for row in rows)


def test_build_route_offers_prefers_full_coverage_options():
    offers = build_route_offers(["Turkey", "Cyprus", "Ukraine"], days=7, usage_key="low")
    assert offers
    assert any(bool(offer["coverage_full"]) for offer in offers)


def test_build_single_country_offers_for_one_country():
    offers = build_single_country_offers("Turkey", days=7, usage_key="low")
    assert offers
    assert offers[0]["offer_type"] == "single_country"


def test_choose_recommended_offer_prefers_simpler_region_when_difference_is_one_or_less():
    offers = [
        {"offer_type": "all_singles", "coverage_full": True, "price_usd": 17.43},
        {"offer_type": "single_region", "coverage_full": True, "price_usd": 18.00},
    ]
    chosen = choose_recommended_offer(offers, absolute_threshold_usd=1.0)
    assert chosen is not None
    assert chosen["offer_type"] == "single_region"


def test_country_plan_table_includes_singles_and_covering_regions():
    from services.digital_products.esim_route_service import _country_plan_table_from

    rows = [
        {"type": "Single", "region": "Kenya", "name": "Kenya 1GB 7Days", "price_usd": 2.0, "days": 7, "gbs": "1"},
        {"type": "Single", "region": "Kenya", "name": "Kenya 3GB 30Days", "price_usd": 5.0, "days": 30, "gbs": "3"},
        {"type": "Single", "region": "Turkey", "name": "Turkey 1GB", "price_usd": 2.5, "days": 7, "gbs": "1"},
        {"type": "Multi-Area", "region": "Africa", "name": "Africa 1GB 7Days", "price_usd": 4.0, "days": 7, "gbs": "1"},
        {"type": "Multi-Area", "region": "Europe", "name": "Europe 1GB 7Days", "price_usd": 3.0, "days": 7, "gbs": "1"},
    ]
    coverage_map = {"Africa": {"Kenya", "Nigeria", "Egypt"}, "Europe": {"France", "Germany"}}

    entries = _country_plan_table_from(rows, coverage_map, "Kenya")

    names = [entry["plan"]["name"] for entry in entries]
    # Kenya singles + the Africa regional plan; Turkey/Europe stay out.
    assert "Kenya 1GB 7Days" in names and "Kenya 3GB 30Days" in names
    assert "Africa 1GB 7Days" in names
    assert "Turkey 1GB" not in names and "Europe 1GB 7Days" not in names
    # Sorted by price and coverage metadata carried for the table column.
    assert names[0] == "Kenya 1GB 7Days"
    region_entry = next(entry for entry in entries if entry["coverage_kind"] == "region")
    assert region_entry["coverage_label"] == "Africa"
    assert region_entry["coverage_count"] == 3
    assert "Kenya" in region_entry["coverage_countries"]
    single_entry = next(entry for entry in entries if entry["coverage_kind"] == "single")
    assert single_entry["coverage_label"] == "Kenya"
    assert single_entry["coverage_count"] == 1


def test_country_plan_table_caps_region_plans():
    from services.digital_products.esim_route_service import _country_plan_table_from

    rows = [
        {"type": "Multi-Area", "region": "Africa", "name": f"Africa plan {i}", "price_usd": 1.0 + i, "days": 7, "gbs": "1"}
        for i in range(30)
    ]
    entries = _country_plan_table_from(rows, {"Africa": {"Kenya"}}, "Kenya", region_plan_cap=5)
    assert len(entries) == 5
    # The cheapest region plans survive the cap.
    assert entries[0]["plan"]["name"] == "Africa plan 0"


def test_allowance_label_keeps_mb_unit():
    from services.digital_products.esim_route_service import plan_allowance_label

    assert plan_allowance_label({"name": "X 100MB 7Days", "gbs": "100MB", "data_type": ""}, lang="ar") == "100MB"
    assert plan_allowance_label({"name": "X 300MB/Day", "gbs": "300MB", "data_type": "daily"}, lang="ar") == "300MB/يوم"
    assert plan_allowance_label({"name": "X 3GB", "gbs": "3", "data_type": ""}, lang="ar") == "3GB"
