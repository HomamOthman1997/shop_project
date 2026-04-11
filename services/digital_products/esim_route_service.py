from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "esim_catalog.json"

_MULTI_AREA_COVERAGE: dict[str, set[str]] = {
    "Europe (30+ areas)": {
        "Austria",
        "Belgium",
        "Bulgaria",
        "Croatia",
        "Cyprus",
        "Czech Republic",
        "Denmark",
        "Estonia",
        "Finland",
        "France",
        "Germany",
        "Greece",
        "Hungary",
        "Iceland",
        "Ireland",
        "Italy",
        "Latvia",
        "Lithuania",
        "Luxembourg",
        "Malta",
        "Netherlands",
        "Norway",
        "Poland",
        "Portugal",
        "Romania",
        "Slovakia",
        "Slovenia",
        "Spain",
        "Sweden",
        "Switzerland",
        "Turkey",
        "Ukraine",
        "United Kingdom",
    },
    "Europe (40+ areas)": {
        "Albania",
        "Austria",
        "Belgium",
        "Bosnia and Herzegovina",
        "Bulgaria",
        "Croatia",
        "Cyprus",
        "Czech Republic",
        "Denmark",
        "Estonia",
        "Finland",
        "France",
        "Germany",
        "Greece",
        "Hungary",
        "Iceland",
        "Ireland",
        "Italy",
        "Latvia",
        "Liechtenstein",
        "Lithuania",
        "Luxembourg",
        "Malta",
        "Moldova",
        "Montenegro",
        "Netherlands",
        "North Macedonia",
        "Norway",
        "Poland",
        "Portugal",
        "Romania",
        "Serbia",
        "Slovakia",
        "Slovenia",
        "Spain",
        "Sweden",
        "Switzerland",
        "Turkey",
        "Ukraine",
        "United Kingdom",
    },
    "Europe (40+ areas) & Morocco": {
        "Albania",
        "Austria",
        "Belgium",
        "Bosnia and Herzegovina",
        "Bulgaria",
        "Croatia",
        "Cyprus",
        "Czech Republic",
        "Denmark",
        "Estonia",
        "Finland",
        "France",
        "Germany",
        "Greece",
        "Hungary",
        "Iceland",
        "Ireland",
        "Italy",
        "Latvia",
        "Liechtenstein",
        "Lithuania",
        "Luxembourg",
        "Malta",
        "Moldova",
        "Montenegro",
        "Morocco",
        "Netherlands",
        "North Macedonia",
        "Norway",
        "Poland",
        "Portugal",
        "Romania",
        "Serbia",
        "Slovakia",
        "Slovenia",
        "Spain",
        "Sweden",
        "Switzerland",
        "Turkey",
        "Ukraine",
        "United Kingdom",
    },
    "Gulf Region": {
        "Bahrain",
        "Kuwait",
        "Oman",
        "Qatar",
        "Saudi Arabia",
        "United Arab Emirates",
    },
    "Middle East & North Africa": {
        "Algeria",
        "Bahrain",
        "Egypt",
        "Israel",
        "Jordan",
        "Kuwait",
        "Morocco",
        "Oman",
        "Qatar",
        "Saudi Arabia",
        "Tunisia",
        "United Arab Emirates",
    },
    "Asia (7 areas)": {
        "Hong Kong",
        "Indonesia",
        "Japan",
        "Malaysia",
        "Singapore",
        "South Korea",
        "Thailand",
    },
    "Asia (20 areas)": {
        "Cambodia",
        "China mainland",
        "Hong Kong",
        "India",
        "Indonesia",
        "Japan",
        "Laos",
        "Macau",
        "Malaysia",
        "Pakistan",
        "Philippines",
        "Singapore",
        "South Korea",
        "Sri Lanka",
        "Taiwan",
        "Thailand",
        "Turkey",
        "United Arab Emirates",
        "Vietnam",
    },
    "Asia (20+ areas)": {
        "Cambodia",
        "China mainland",
        "Hong Kong",
        "India",
        "Indonesia",
        "Japan",
        "Laos",
        "Macau",
        "Malaysia",
        "Pakistan",
        "Philippines",
        "Singapore",
        "South Korea",
        "Sri Lanka",
        "Taiwan",
        "Thailand",
        "Turkey",
        "United Arab Emirates",
        "Vietnam",
    },
    "China mainland & Japan & South Korea": {
        "China mainland",
        "Japan",
        "South Korea",
    },
    "USA & Canada": {
        "Canada",
        "United States",
    },
    "Global (120+ areas)": {
        "Australia",
        "Austria",
        "Belgium",
        "Brazil",
        "Canada",
        "China mainland",
        "Cyprus",
        "Egypt",
        "France",
        "Germany",
        "Greece",
        "Hong Kong",
        "India",
        "Indonesia",
        "Italy",
        "Japan",
        "Malaysia",
        "Mexico",
        "Morocco",
        "Netherlands",
        "Oman",
        "Philippines",
        "Portugal",
        "Qatar",
        "Saudi Arabia",
        "Singapore",
        "South Africa",
        "South Korea",
        "Spain",
        "Thailand",
        "Turkey",
        "Ukraine",
        "United Arab Emirates",
        "United Kingdom",
        "United States",
        "Vietnam",
    },
}


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "country"


def country_slug(name: str) -> str:
    return _slugify(name)


@lru_cache(maxsize=1)
def _catalog() -> list[dict[str, Any]]:
    with _CATALOG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _money_key(row: dict[str, Any]) -> tuple[float, int]:
    return (float(row.get("price_usd") or 0.0), int(row.get("days") or 0))


def _allowance_label(row: dict[str, Any], *, lang: str) -> str:
    name = str(row.get("name") or "").strip()
    gbs = str(row.get("gbs") or "").strip()
    data_type = str(row.get("data_type") or "").strip().lower()
    if "daily" in data_type:
        upper_name = name.upper()
        if "500MB" in upper_name:
            return "500MB/يوم" if lang.startswith("ar") else "500MB/day"
        if gbs and gbs not in {"0", "0.0"}:
            return f"{gbs}GB/يوم" if lang.startswith("ar") else f"{gbs}GB/day"
        return "يومي" if lang.startswith("ar") else "Daily"
    if gbs and gbs not in {"0", "0.0"}:
        return f"{gbs}GB"
    return "Data"


def _normalize_country(name: str) -> str:
    return " ".join(str(name or "").strip().split())


def searchable_countries() -> list[str]:
    values: set[str] = set()
    for row in _catalog():
        if str(row.get("type") or "").strip() == "Single":
            region = _normalize_country(str(row.get("region") or ""))
            if region:
                values.add(region)
    for countries in _MULTI_AREA_COVERAGE.values():
        values.update(_normalize_country(name) for name in countries if name)
    values.discard("Syria")
    return sorted(values)


def search_countries(query: str, *, limit: int = 20) -> list[str]:
    raw = _normalize_country(query).lower()
    countries = searchable_countries()
    if not raw:
        return countries[:limit]
    starts = [name for name in countries if name.lower().startswith(raw)]
    contains = [name for name in countries if raw in name.lower() and name not in starts]
    return (starts + contains)[:limit]


def single_country_plans(country: str) -> list[dict[str, Any]]:
    target = _normalize_country(country)
    rows = [
        row
        for row in _catalog()
        if str(row.get("type") or "").strip() == "Single" and _normalize_country(str(row.get("region") or "")) == target
    ]
    rows.sort(key=_money_key)
    return rows


def available_days(rows: list[dict[str, Any]]) -> list[int]:
    return sorted({int(row.get("days") or 0) for row in rows if int(row.get("days") or 0) > 0})


def plans_for_days(rows: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    selected = [row for row in rows if int(row.get("days") or 0) == int(days)]
    selected.sort(key=_money_key)
    return selected


def choose_best_multi_area(countries: list[str]) -> dict[str, Any] | None:
    wanted = {_normalize_country(name) for name in countries if _normalize_country(name) and _normalize_country(name) != "Syria"}
    if not wanted:
        return None
    candidates: list[dict[str, Any]] = []
    for region_name, coverage in _MULTI_AREA_COVERAGE.items():
        covered = sorted(wanted & coverage)
        if not covered:
            continue
        plans = [
            row
            for row in _catalog()
            if str(row.get("type") or "").strip() == "Multi-Area" and _normalize_country(str(row.get("region") or "")) == region_name
        ]
        if not plans:
            continue
        missing = sorted(wanted - coverage)
        cheapest = min(float(row.get("price_usd") or 0.0) for row in plans)
        candidates.append(
            {
                "region_name": region_name,
                "plans": sorted(plans, key=_money_key),
                "covered": covered,
                "missing": missing,
                "coverage_full": not missing,
                "coverage_size": len(coverage),
                "score_covered": len(covered),
                "cheapest_price": cheapest,
            }
        )
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            0 if item["coverage_full"] else 1,
            -int(item["score_covered"]),
            float(item["cheapest_price"]),
            int(item["coverage_size"]),
        )
    )
    return candidates[0]


def package_button_label(row: dict[str, Any], *, lang: str) -> str:
    allowance = _allowance_label(row, lang=lang)
    price = float(row.get("price_usd") or 0.0)
    return f"{allowance} - ${price:.2f}"


def package_summary(row: dict[str, Any], *, lang: str) -> str:
    allowance = _allowance_label(row, lang=lang)
    days = int(row.get("days") or 0)
    speed = str(row.get("speed") or "").strip()
    price = float(row.get("price_usd") or 0.0)
    if str(lang).lower().startswith("ar"):
        lines = [
            f"الباقة: {allowance}",
            f"المدة: {days} يوم",
            f"السرعة: {speed or '-'}",
            f"السعر: ${price:.2f}",
        ]
    else:
        lines = [
            f"Package: {allowance}",
            f"Duration: {days} days",
            f"Speed: {speed or '-'}",
            f"Price: ${price:.2f}",
        ]
    return "\n".join(lines)
