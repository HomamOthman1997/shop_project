import os
import sys

sys.path.insert(0, os.getcwd())

from services.digital_products.esim_route_service import (
    available_days,
    choose_best_multi_area,
    plans_for_days,
    search_countries,
    single_country_plans,
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
