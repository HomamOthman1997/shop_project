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
