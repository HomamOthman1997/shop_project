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


def _plan_gb_value(row: dict[str, Any]) -> float:
    raw = str(row.get("gbs") or "").strip()
    try:
        value = float(raw)
    except Exception:
        value = 0.0
    data_type = str(row.get("data_type") or "").strip().lower()
    name = str(row.get("name") or "").strip().lower()
    if "daily" in data_type or "daily" in name:
        return max(value, 999.0)
    return value


def usage_thresholds(usage_key: str) -> tuple[float, float | None]:
    key = str(usage_key or "").strip().lower()
    if key == "mid":
        return 5.0, 10.0
    if key == "high":
        return 10.0, None
    return 0.0, 5.0


def usage_matches(row: dict[str, Any], usage_key: str) -> bool:
    minimum, maximum = usage_thresholds(usage_key)
    value = _plan_gb_value(row)
    if value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True


def plans_for_usage(rows: list[dict[str, Any]], usage_key: str) -> list[dict[str, Any]]:
    selected = [row for row in rows if usage_matches(row, usage_key)]
    selected.sort(key=_money_key)
    return selected


def usage_label(usage_key: str, *, lang: str) -> str:
    key = str(usage_key or "").strip().lower()
    if str(lang).lower().startswith("ar"):
        if key == "mid":
            return "من 5 إلى 10 GB"
        if key == "high":
            return "أكثر من 10 GB"
        return "أقل من 5 GB"
    if key == "mid":
        return "5 to 10 GB"
    if key == "high":
        return "More than 10 GB"
    return "Less than 5 GB"


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


def route_available_days(countries: list[str]) -> list[int]:
    wanted = {_normalize_country(name) for name in countries if _normalize_country(name) and _normalize_country(name) != "Syria"}
    values: set[int] = set()
    for country in wanted:
        values.update(available_days(single_country_plans(country)))
    for region_name, coverage in _MULTI_AREA_COVERAGE.items():
        if not (wanted & coverage):
            continue
        rows = [
            row
            for row in _catalog()
            if str(row.get("type") or "").strip() == "Multi-Area" and _normalize_country(str(row.get("region") or "")) == region_name
        ]
        values.update(available_days(rows))
    return sorted(day for day in values if day > 0)


def _single_country_best(country: str, *, days: int, usage_key: str) -> dict[str, Any] | None:
    rows = plans_for_usage(plans_for_days(single_country_plans(country), days), usage_key)
    return rows[0] if rows else None


def build_route_offers(countries: list[str], *, days: int, usage_key: str) -> list[dict[str, Any]]:
    wanted = [_normalize_country(name) for name in countries if _normalize_country(name) and _normalize_country(name) != "Syria"]
    if not wanted:
        return []

    offers: list[dict[str, Any]] = []

    single_parts: list[dict[str, Any]] = []
    all_singles_ok = True
    for country in wanted:
        row = _single_country_best(country, days=days, usage_key=usage_key)
        if not row:
            all_singles_ok = False
            break
        single_parts.append({"kind": "single", "country": country, "plan": row})
    if all_singles_ok and single_parts:
        total = sum(float(part["plan"].get("price_usd") or 0.0) for part in single_parts)
        offers.append(
            {
                "offer_type": "all_singles",
                "title_en": "Separate country plans",
                "title_ar": "باقات منفصلة لكل دولة",
                "covered": wanted,
                "missing": [],
                "coverage_full": True,
                "price_usd": total,
                "parts": single_parts,
                "sort_rank": 0,
            }
        )

    for region_name, coverage in _MULTI_AREA_COVERAGE.items():
        covered = [name for name in wanted if name in coverage]
        if not covered:
            continue
        region_rows = plans_for_usage(
            plans_for_days(
                [
                    row
                    for row in _catalog()
                    if str(row.get("type") or "").strip() == "Multi-Area"
                    and _normalize_country(str(row.get("region") or "")) == region_name
                ],
                days,
            ),
            usage_key,
        )
        if not region_rows:
            continue
        best_region = region_rows[0]
        missing = [name for name in wanted if name not in coverage]
        offers.append(
            {
                "offer_type": "single_region",
                "title_en": "One regional plan",
                "title_ar": "باقة ريجن واحدة",
                "covered": covered,
                "missing": missing,
                "coverage_full": not missing,
                "price_usd": float(best_region.get("price_usd") or 0.0),
                "parts": [{"kind": "region", "region_name": region_name, "plan": best_region}],
                "sort_rank": 1,
            }
        )
        if len(missing) == 1:
            leftover = missing[0]
            extra = _single_country_best(leftover, days=days, usage_key=usage_key)
            if extra:
                offers.append(
                    {
                        "offer_type": "region_plus_single",
                        "title_en": "Regional plan + one extra country",
                        "title_ar": "باقة ريجن + دولة إضافية",
                        "covered": wanted,
                        "missing": [],
                        "coverage_full": True,
                        "price_usd": float(best_region.get("price_usd") or 0.0) + float(extra.get("price_usd") or 0.0),
                        "parts": [
                            {"kind": "region", "region_name": region_name, "plan": best_region},
                            {"kind": "single", "country": leftover, "plan": extra},
                        ],
                        "sort_rank": 2,
                    }
                )

    unique: dict[tuple[str, tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
    for offer in offers:
        key = (
            str(offer.get("offer_type") or ""),
            tuple(str(part.get("region_name") or part.get("country") or "") for part in offer.get("parts") or []),
            tuple(str(part.get("plan", {}).get("code") or "") for part in offer.get("parts") or []),
        )
        current = unique.get(key)
        if current is None or float(offer.get("price_usd") or 0.0) < float(current.get("price_usd") or 0.0):
            unique[key] = offer

    final_offers = list(unique.values())
    final_offers.sort(
        key=lambda item: (
            0 if item.get("coverage_full") else 1,
            float(item.get("price_usd") or 0.0),
            int(item.get("sort_rank") or 99),
        )
    )
    return final_offers[:3]


def build_single_country_offers(country: str, *, days: int, usage_key: str) -> list[dict[str, Any]]:
    rows = plans_for_usage(plans_for_days(single_country_plans(country), days), usage_key)
    offers: list[dict[str, Any]] = []
    for row in rows[:5]:
        offers.append(
            {
                "offer_type": "single_country",
                "title_en": "Single-country plan",
                "title_ar": "باقة دولة واحدة",
                "covered": [country],
                "missing": [],
                "coverage_full": True,
                "price_usd": float(row.get("price_usd") or 0.0),
                "parts": [{"kind": "single", "country": country, "plan": row}],
                "sort_rank": 0,
            }
        )
    return offers


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


def offer_button_label(offer: dict[str, Any], *, lang: str) -> str:
    title = str(offer.get("title_ar") if str(lang).lower().startswith("ar") else offer.get("title_en") or "").strip()
    return f"{title} - ${float(offer.get('price_usd') or 0.0):.2f}"


def offer_summary(offer: dict[str, Any], *, lang: str) -> str:
    is_ar = str(lang).lower().startswith("ar")
    lines: list[str] = []
    title = str(offer.get("title_ar") if is_ar else offer.get("title_en") or "").strip()
    if title:
        lines.append(title)
    covered = list(offer.get("covered") or [])
    missing = list(offer.get("missing") or [])
    if covered:
        joined = "، ".join(covered) if is_ar else ", ".join(covered)
        lines.append(f"{'يغطي' if is_ar else 'Covers'}: {joined}")
    if missing:
        joined = "، ".join(missing) if is_ar else ", ".join(missing)
        lines.append(f"{'لا يغطي' if is_ar else 'Does not cover'}: {joined}")
    lines.append(f"{'السعر الإجمالي' if is_ar else 'Total price'}: ${float(offer.get('price_usd') or 0.0):.2f}")
    lines.append("")
    for part in offer.get("parts") or []:
        if part.get("kind") == "region":
            region_name = str(part.get("region_name") or "").strip()
            lines.append(f"{'ريجن' if is_ar else 'Region'}: {region_name}")
        elif part.get("kind") == "single":
            country = str(part.get("country") or "").strip()
            lines.append(f"{'دولة' if is_ar else 'Country'}: {country}")
        lines.append(package_summary(dict(part.get("plan") or {}), lang=lang))
        lines.append("")
    return "\n".join(line for line in lines if line is not None).strip()
