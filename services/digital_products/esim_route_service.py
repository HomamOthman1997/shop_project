from __future__ import annotations

import asyncio
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import settings
from services.digital_products.esim_access_client import EsimAccessClient


_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "esim_catalog.json"
_LIVE_CACHE: dict[str, Any] = {"expires_at": 0.0, "rows": None, "coverage_map": None, "countries": None}

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


def _gbs_display(gbs: str) -> str:
    # gbs already carries its unit for sub-GB values ("500MB") — appending GB
    # blindly produced labels like "500MBGB".
    return gbs if gbs.upper().endswith(("MB", "GB")) else f"{gbs}GB"


def _allowance_label(row: dict[str, Any], *, lang: str) -> str:
    name = str(row.get("name") or "").strip()
    gbs = str(row.get("gbs") or "").strip()
    data_type = str(row.get("data_type") or "").strip().lower()
    if "daily" in data_type:
        upper_name = name.upper()
        if "500MB" in upper_name:
            return "500MB/يوم" if lang.startswith("ar") else "500MB/day"
        if gbs and gbs not in {"0", "0.0"}:
            return f"{_gbs_display(gbs)}/يوم" if lang.startswith("ar") else f"{_gbs_display(gbs)}/day"
        return "يومي" if lang.startswith("ar") else "Daily"
    if gbs and gbs not in {"0", "0.0"}:
        return _gbs_display(gbs)
    return "Data"


def _normalize_country(name: str) -> str:
    return " ".join(str(name or "").strip().split())


def _normalize_coverage_map(raw: dict[str, set[str] | list[str]]) -> dict[str, set[str]]:
    normalized: dict[str, set[str]] = {}
    for name, countries in (raw or {}).items():
        region_name = _normalize_country(name)
        if not region_name:
            continue
        normalized[region_name] = {
            _normalize_country(country)
            for country in (countries or [])
            if _normalize_country(country) and _normalize_country(country) != "Syria"
        }
    return normalized


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


def _rows_from_source(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return list(rows or [])


def _coverage_map_from_source(coverage_map: dict[str, set[str]] | None) -> dict[str, set[str]]:
    return _normalize_coverage_map(coverage_map or _MULTI_AREA_COVERAGE)


def _searchable_countries_from(rows: list[dict[str, Any]], coverage_map: dict[str, set[str]]) -> list[str]:
    values: set[str] = set()
    for row in rows:
        if str(row.get("type") or "").strip() == "Single":
            region = _normalize_country(str(row.get("region") or ""))
            if region and region != "Syria":
                values.add(region)
    for countries in coverage_map.values():
        values.update(_normalize_country(name) for name in countries if _normalize_country(name) and _normalize_country(name) != "Syria")
    return sorted(values)


def search_countries(query: str, *, limit: int = 20) -> list[str]:
    raw = _normalize_country(query).lower()
    countries = searchable_countries()
    if not raw:
        return countries[:limit]
    starts = [name for name in countries if name.lower().startswith(raw)]
    contains = [name for name in countries if raw in name.lower() and name not in starts]
    return (starts + contains)[:limit]


def _single_country_plans_from(rows: list[dict[str, Any]], country: str) -> list[dict[str, Any]]:
    target = _normalize_country(country)
    selected = [
        row
        for row in rows
        if str(row.get("type") or "").strip() == "Single" and _normalize_country(str(row.get("region") or "")) == target
    ]
    selected.sort(key=_money_key)
    return selected


def single_country_plans(country: str) -> list[dict[str, Any]]:
    return _single_country_plans_from(_catalog(), country)


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
    return _route_available_days_from(_catalog(), _MULTI_AREA_COVERAGE, countries)


def _route_available_days_from(
    rows: list[dict[str, Any]],
    coverage_map: dict[str, set[str]] | dict[str, list[str]],
    countries: list[str],
) -> list[int]:
    wanted = {_normalize_country(name) for name in countries if _normalize_country(name) and _normalize_country(name) != "Syria"}
    values: set[int] = set()
    for country in wanted:
        values.update(available_days(_single_country_plans_from(rows, country)))
    normalized_map = _normalize_coverage_map(coverage_map)
    for region_name, coverage in normalized_map.items():
        if not (wanted & coverage):
            continue
        region_rows = [
            row
            for row in rows
            if str(row.get("type") or "").strip() == "Multi-Area" and _normalize_country(str(row.get("region") or "")) == region_name
        ]
        values.update(available_days(region_rows))
    return sorted(day for day in values if day > 0)


def _single_country_best(country: str, *, days: int, usage_key: str) -> dict[str, Any] | None:
    rows = plans_for_usage(plans_for_days(single_country_plans(country), days), usage_key)
    return rows[0] if rows else None


def _single_country_best_from(rows: list[dict[str, Any]], country: str, *, days: int, usage_key: str) -> dict[str, Any] | None:
    selected = plans_for_usage(plans_for_days(_single_country_plans_from(rows, country), days), usage_key)
    return selected[0] if selected else None


def build_route_offers(countries: list[str], *, days: int, usage_key: str) -> list[dict[str, Any]]:
    return _build_route_offers_from(_catalog(), _MULTI_AREA_COVERAGE, countries, days=days, usage_key=usage_key)


def _build_route_offers_from(
    rows: list[dict[str, Any]],
    coverage_map: dict[str, set[str]] | dict[str, list[str]],
    countries: list[str],
    *,
    days: int,
    usage_key: str,
) -> list[dict[str, Any]]:
    wanted = [_normalize_country(name) for name in countries if _normalize_country(name) and _normalize_country(name) != "Syria"]
    if not wanted:
        return []

    offers: list[dict[str, Any]] = []

    single_parts: list[dict[str, Any]] = []
    all_singles_ok = True
    for country in wanted:
        row = _single_country_best_from(rows, country, days=days, usage_key=usage_key)
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

    normalized_map = _normalize_coverage_map(coverage_map)
    for region_name, coverage in normalized_map.items():
        covered = [name for name in wanted if name in coverage]
        if not covered:
            continue
        region_rows = plans_for_usage(
            plans_for_days(
                [
                    row
                    for row in rows
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
            extra = _single_country_best_from(rows, leftover, days=days, usage_key=usage_key)
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
    return _build_single_country_offers_from(_catalog(), country, days=days, usage_key=usage_key)


def _build_single_country_offers_from(
    rows: list[dict[str, Any]],
    country: str,
    *,
    days: int,
    usage_key: str,
) -> list[dict[str, Any]]:
    rows = plans_for_usage(plans_for_days(_single_country_plans_from(rows, country), days), usage_key)
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


def _offer_complexity_rank(offer: dict[str, Any]) -> int:
    offer_type = str(offer.get("offer_type") or "").strip().lower()
    if offer_type == "single_region":
        return 0
    if offer_type == "single_country":
        return 1
    if offer_type == "region_plus_single":
        return 2
    if offer_type == "all_singles":
        return 3
    return 9


def choose_recommended_offer(
    offers: list[dict[str, Any]],
    *,
    absolute_threshold_usd: float = 1.0,
) -> dict[str, Any] | None:
    if not offers:
        return None
    ranked = sorted(
        offers,
        key=lambda item: (
            0 if item.get("coverage_full") else 1,
            float(item.get("price_usd") or 0.0),
            _offer_complexity_rank(item),
        ),
    )
    best = ranked[0]
    best_price = float(best.get("price_usd") or 0.0)
    best_complexity = _offer_complexity_rank(best)
    if best_price <= 0:
        return best

    for candidate in ranked[1:]:
        if bool(candidate.get("coverage_full")) != bool(best.get("coverage_full")):
            continue
        candidate_complexity = _offer_complexity_rank(candidate)
        if candidate_complexity >= best_complexity:
            continue
        candidate_price = float(candidate.get("price_usd") or 0.0)
        delta = candidate_price - best_price
        if delta < 0:
            continue
        if delta <= absolute_threshold_usd:
            return candidate
    return best


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


def _data_type_label(value: Any) -> str:
    mapping = {
        1: "Data in Total",
        2: "Daily Limit (Speed Reduced)",
        3: "Daily Limit (Service Cut-off)",
        4: "Daily Unlimited",
    }
    try:
        return mapping.get(int(value), "Data")
    except Exception:
        return "Data"


def _volume_to_gb_text(volume_bytes: Any) -> str:
    try:
        value = float(volume_bytes or 0.0) / (1024.0 ** 3)
    except Exception:
        value = 0.0
    if value <= 0:
        return "0"
    if value >= 1:
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return text
    value_mb = value * 1024.0
    text = f"{value_mb:.0f}"
    return f"{text}MB"


def _extract_response_obj(payload: dict[str, Any]) -> Any:
    obj = payload.get("obj")
    if obj is not None:
        return obj
    for key in ("data", "result"):
        if key in payload:
            return payload.get(key)
    return None


def _iter_location_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    obj = _extract_response_obj(payload)
    if isinstance(obj, dict):
        for key in ("locationList", "locations", "list", "rows"):
            value = obj.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    if isinstance(obj, list):
        return [row for row in obj if isinstance(row, dict)]
    return []


def _iter_package_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    obj = _extract_response_obj(payload)
    if isinstance(obj, dict):
        for key in ("packageList", "packages", "list", "rows"):
            value = obj.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    if isinstance(obj, list):
        return [row for row in obj if isinstance(row, dict)]
    return []


def _parse_location_dataset(payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, set[str]]]:
    code_to_name: dict[str, str] = {}
    multi_map: dict[str, set[str]] = {}
    for row in _iter_location_items(payload):
        code = str(row.get("code") or "").strip().upper()
        name = _normalize_country(str(row.get("name") or ""))
        row_type = int(row.get("type") or 0)
        if code and name and row_type == 1:
            code_to_name[code] = name
        if row_type == 2 and name:
            sub_locations = row.get("subLocation") or row.get("subLocations") or []
            countries: set[str] = set()
            if isinstance(sub_locations, list):
                for child in sub_locations:
                    if not isinstance(child, dict):
                        continue
                    child_code = str(child.get("code") or "").strip().upper()
                    child_name = _normalize_country(str(child.get("name") or ""))
                    if child_code and child_name:
                        code_to_name[child_code] = child_name
                    if child_name and child_name != "Syria":
                        countries.add(child_name)
            if countries:
                multi_map[name] = countries
    return code_to_name, multi_map


def _normalize_live_catalog(
    package_payload: dict[str, Any],
    location_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, set[str]], list[str]]:
    code_to_name, location_multi_map = _parse_location_dataset(location_payload)
    rows: list[dict[str, Any]] = []
    coverage_map: dict[str, set[str]] = dict(location_multi_map)
    searchable: set[str] = set()
    for item in _iter_package_items(package_payload):
        location_codes = [str(part or "").strip().upper() for part in str(item.get("location") or "").split(",") if str(part or "").strip()]
        location_names = [_normalize_country(code_to_name.get(code, code)) for code in location_codes if _normalize_country(code_to_name.get(code, code))]
        location_names = [name for name in location_names if name != "Syria"]
        package_name = str(item.get("name") or "").strip()
        description = _normalize_country(str(item.get("description") or ""))
        data_type_code = int(item.get("dataType") or 0)
        package_type = "Multi-Area" if len(location_names) > 1 else "Single"
        region_name = location_names[0] if package_type == "Single" and location_names else (description or package_name or "Region")
        if package_type == "Multi-Area" and location_names:
            coverage_map.setdefault(region_name, set()).update(location_names)
        if package_type == "Single" and region_name:
            searchable.add(region_name)
        try:
            price_usd = float(item.get("price") or 0.0) / 10000.0
        except Exception:
            price_usd = 0.0
        rows.append(
            {
                "type": package_type,
                "region": region_name,
                "name": package_name,
                "description": description,
                "data_type": _data_type_label(data_type_code),
                "data_type_code": data_type_code,
                "price_usd": price_usd,
                "code": str(item.get("packageCode") or "").strip(),
                "package_code": str(item.get("packageCode") or "").strip(),
                "slug": str(item.get("slug") or "").strip(),
                "gbs": _volume_to_gb_text(item.get("volume")),
                "days": int(item.get("duration") or item.get("unusedValidTime") or 0),
                "speed": str(item.get("speed") or "").strip(),
                "support_topup_type": int(item.get("supportTopUpType") or 0),
                "location_codes": location_codes,
                "location_names": location_names,
                "retail_price_usd": float(item.get("retailPrice") or 0.0) / 10000.0 if item.get("retailPrice") is not None else 0.0,
            }
        )
    searchable.update(name for names in coverage_map.values() for name in names)
    searchable.discard("Syria")
    rows.sort(key=_money_key)
    return rows, _normalize_coverage_map(coverage_map), sorted(searchable)


async def _fetch_live_dataset(force: bool = False) -> tuple[list[dict[str, Any]], dict[str, set[str]], list[str]] | None:
    if not settings.esim_access_code or not settings.esim_access_secret_key:
        return None
    now = asyncio.get_running_loop().time()
    cached_rows = _LIVE_CACHE.get("rows")
    cached_map = _LIVE_CACHE.get("coverage_map")
    cached_countries = _LIVE_CACHE.get("countries")
    if (
        not force
        and cached_rows is not None
        and cached_map is not None
        and cached_countries is not None
        and float(_LIVE_CACHE.get("expires_at") or 0.0) > now
    ):
        return list(cached_rows), dict(cached_map), list(cached_countries)
    client = EsimAccessClient()
    try:
        package_payload, location_payload = await asyncio.gather(
            client.list_packages(package_type="BASE"),
            client.list_locations(),
        )
    except Exception:
        return None
    if not bool(package_payload.get("success")):
        return None
    rows, coverage_map, countries = _normalize_live_catalog(package_payload, location_payload if isinstance(location_payload, dict) else {})
    if not rows:
        return None
    _LIVE_CACHE["rows"] = rows
    _LIVE_CACHE["coverage_map"] = coverage_map
    _LIVE_CACHE["countries"] = countries
    _LIVE_CACHE["expires_at"] = now + max(30.0, float(getattr(settings, "esim_access_catalog_cache_ttl_sec", 600) or 600))
    return list(rows), dict(coverage_map), list(countries)


async def live_or_local_dataset() -> tuple[list[dict[str, Any]], dict[str, set[str]], list[str], bool]:
    live = await _fetch_live_dataset()
    if live is not None:
        rows, coverage_map, countries = live
        return rows, coverage_map, countries, True
    rows = _catalog()
    coverage_map = _normalize_coverage_map(_MULTI_AREA_COVERAGE)
    countries = _searchable_countries_from(rows, coverage_map)
    return list(rows), coverage_map, countries, False


async def search_countries_live(query: str, *, limit: int = 20) -> list[str]:
    rows, coverage_map, _, _ = await live_or_local_dataset()
    raw = _normalize_country(query).lower()
    countries = _searchable_countries_from(rows, coverage_map)
    if not raw:
        return countries[:limit]
    starts = [name for name in countries if name.lower().startswith(raw)]
    contains = [name for name in countries if raw in name.lower() and name not in starts]
    return (starts + contains)[:limit]


async def single_country_plans_live(country: str) -> list[dict[str, Any]]:
    rows, _, _, _ = await live_or_local_dataset()
    return _single_country_plans_from(rows, country)


async def route_available_days_live(countries: list[str]) -> list[int]:
    rows, coverage_map, _, _ = await live_or_local_dataset()
    return _route_available_days_from(rows, coverage_map, countries)


async def build_route_offers_live(countries: list[str], *, days: int, usage_key: str) -> list[dict[str, Any]]:
    rows, coverage_map, _, _ = await live_or_local_dataset()
    return _build_route_offers_from(rows, coverage_map, countries, days=days, usage_key=usage_key)


async def build_single_country_offers_live(country: str, *, days: int, usage_key: str) -> list[dict[str, Any]]:
    rows, _, _, _ = await live_or_local_dataset()
    return _build_single_country_offers_from(rows, country, days=days, usage_key=usage_key)


def plan_allowance_label(row: dict[str, Any], *, lang: str = "ar") -> str:
    """Public data-allowance label ('3GB', '1GB/يوم', …) for the website table."""
    return _allowance_label(row, lang=lang)


def plan_gb_sort_value(row: dict[str, Any]) -> float:
    """Sortable GB value (daily plans rank as effectively unlimited)."""
    return _plan_gb_value(row)


# How many plans per covering region land in the country table — regions like
# Europe carry dozens; the cheapest few are what a customer actually compares.
_REGION_TABLE_PLAN_CAP = 15


def _country_plan_table_from(
    rows: list[dict[str, Any]],
    coverage_map: dict[str, set[str]] | dict[str, list[str]],
    country: str,
    *,
    region_plan_cap: int = _REGION_TABLE_PLAN_CAP,
) -> list[dict[str, Any]]:
    """Flat, price-sorted table of every plan usable in `country`: all of its
    Single-country plans PLUS the Multi-Area plans whose coverage includes it —
    so a customer picking Kenya also sees the Africa eSIMs, with the coverage
    scope carried on each entry for the التغطية column."""
    target = _normalize_country(country)
    entries: list[dict[str, Any]] = []
    for row in _single_country_plans_from(rows, target):
        entries.append(
            {
                "plan": row,
                "coverage_kind": "single",
                "coverage_label": target,
                "coverage_count": 1,
                "coverage_countries": [target],
            }
        )
    for region_name, coverage in _normalize_coverage_map(coverage_map).items():
        if target not in coverage:
            continue
        region_rows = sorted(
            [
                row
                for row in rows
                if str(row.get("type") or "").strip() == "Multi-Area"
                and _normalize_country(str(row.get("region") or "")) == region_name
            ],
            key=_money_key,
        )
        covered_sorted = sorted(coverage)
        for row in region_rows[: max(0, int(region_plan_cap))]:
            entries.append(
                {
                    "plan": row,
                    "coverage_kind": "region",
                    "coverage_label": region_name,
                    "coverage_count": len(coverage),
                    "coverage_countries": covered_sorted[:40],
                }
            )
    entries.sort(key=lambda item: _money_key(item["plan"]))
    return entries


async def country_plan_table_live(country: str) -> list[dict[str, Any]]:
    rows, coverage_map, _, _ = await live_or_local_dataset()
    return _country_plan_table_from(rows, coverage_map, country)
