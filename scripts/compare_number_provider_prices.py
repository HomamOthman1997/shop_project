import asyncio
import json
import re
import statistics
from collections import defaultdict
from typing import Any

import requests

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.manager import PROVIDERS
from services.numbers.providers.herosms_provider import HeroSMSProvider
from services.numbers.providers.nonvoip_provider import NonVoipProvider
from services.numbers.providers.smspool_provider import SMSPoolProvider
from services.numbers.providers.telabot_provider import TelabotProvider
from services.numbers.providers.textverified_provider import TextVerifiedProvider
from services.numbers.service_map import (
    get_service_aliases,
    get_service_display_name,
    get_service_provider_map,
    iter_service_entries,
)


BULK_PRICE_PROVIDERS: tuple[str, ...] = ("smspool", "telabot", "nonvoip")
DIRECT_PRICE_PROVIDERS: tuple[str, ...] = ("herosms",)
ALL_PROVIDERS: tuple[str, ...] = ("smspool", "telabot", "textverified", "herosms", "nonvoip", "vaksms")


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if number <= 0:
        return None
    return number


def _normalize_bulk_index() -> dict[str, dict[str, float]]:
    return {provider: {} for provider in BULK_PRICE_PROVIDERS}


async def _fetch_smspool_bulk_prices() -> dict[str, float]:
    provider = SMSPoolProvider()
    key = settings.smspool_key
    if not key:
        return {}
    status, data = await provider._request_form(  # noqa: SLF001 - audit script
        path="/request/pricing",
        payload={"key": key},
    )
    if status != 200 or not isinstance(data, list):
        return {}

    by_service: dict[str, float] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        service_code = str(row.get("service") or "").strip()
        if not service_code:
            continue
        price = _as_float(row.get("price"))
        if price is None:
            continue
        prev = by_service.get(service_code)
        if prev is None or price < prev:
            by_service[service_code] = price
    return by_service


async def _fetch_telabot_bulk_prices() -> dict[str, float]:
    provider = TelabotProvider()
    data = await provider.list_services()
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for service_name, row in data.items():
        price = _as_float((row or {}).get("price"))
        if price is None:
            continue
        out[str(service_name)] = price
    return out


async def _fetch_nonvoip_bulk_prices() -> dict[str, float]:
    provider = NonVoipProvider()
    rows = await provider.list_services(force_refresh=True)
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        service_id = str(row.get("id") or "").strip()
        price = _as_float(row.get("price"))
        if not service_id or price is None:
            continue
        out[service_id] = price
    return out


async def _fetch_hero_prices(service_provider_codes: dict[str, str], concurrency: int = 25) -> dict[str, float]:
    provider = HeroSMSProvider()
    semaphore = asyncio.Semaphore(concurrency)
    out: dict[str, float] = {}

    async def worker(service_code: str) -> None:
        async with semaphore:
            result = await provider.get_price(service_code)
        if not isinstance(result, dict) or not result.get("success"):
            return
        price = _as_float(result.get("price"))
        if price is None:
            return
        out[service_code] = price

    tasks = [worker(service_code) for service_code in sorted(set(service_provider_codes.values())) if service_code]
    await asyncio.gather(*tasks)
    return out


def _build_textverified_coverage() -> set[str]:
    services = TextVerifiedProvider._sms_services()  # noqa: SLF001 - audit script
    return {str(service) for service in services if str(service).strip()}


def _median(values: list[float]) -> float | None:
    clean = [v for v in values if isinstance(v, (int, float))]
    if not clean:
        return None
    return float(statistics.median(clean))


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def _fetch_vaksms_catalog() -> dict[str, str]:
    url = "https://vak-sms.com/api/vak/"
    html = requests.get(url, timeout=30).text
    marker = 'id="serviceCodeList1"'
    idx = html.find(marker)
    if idx < 0:
        return {}
    chunk = html[idx:]
    tbody_start = chunk.find("<tbody>")
    tbody_end = chunk.find("</tbody>")
    if tbody_start < 0 or tbody_end < 0:
        return {}
    tbody = chunk[tbody_start:tbody_end]
    row_pattern = re.compile(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", re.S | re.I)
    out: dict[str, str] = {}
    for raw_name, raw_code in row_pattern.findall(tbody):
        name = _strip_html(raw_name)
        code = _strip_html(raw_code)
        if not code:
            continue
        if not name:
            continue
        out[name] = code
    return out


def _fetch_vaksms_prices() -> dict[str, float]:
    api_key = str(getattr(settings, "vaksms_key", "") or "").strip()
    if not api_key:
        return {}
    url = str(getattr(settings, "vaksms_stub_base_url", "https://vak-sms.com/stubs/handler_api.php") or "").strip()
    response = requests.get(url, params={"api_key": api_key, "action": "getPrices"}, timeout=60)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        return {}
    rub_to_usd = float(getattr(settings, "vaksms_rub_to_usd_rate", 0.0112) or 0.0112)
    by_code: dict[str, float] = {}
    for _country_code, service_map in data.items():
        if not isinstance(service_map, dict):
            continue
        for service_code, row in service_map.items():
            if not isinstance(row, dict):
                continue
            cost = _as_float(row.get("cost"))
            count = int(row.get("count") or 0)
            if cost is None or count <= 0:
                continue
            usd_cost = cost * rub_to_usd
            prev = by_code.get(service_code)
            if prev is None or usd_cost < prev:
                by_code[service_code] = usd_cost
    return by_code


def _build_vaksms_service_matches(service_entries: list[tuple[str, dict[str, Any]]], vak_catalog: dict[str, str]) -> dict[str, str]:
    normalized_catalog: dict[str, str] = {}
    for name, code in vak_catalog.items():
        norm = _normalize_name(name)
        if norm and code and norm not in normalized_catalog:
            normalized_catalog[norm] = code

    matches: dict[str, str] = {}
    for service_key, _entry in service_entries:
        candidates: list[str] = [service_key, get_service_display_name(service_key) or ""]
        candidates.extend(get_service_aliases(service_key))
        matched_code = None
        for candidate in candidates:
            norm = _normalize_name(candidate)
            if not norm:
                continue
            code = normalized_catalog.get(norm)
            if code:
                matched_code = code
                break
        if matched_code:
            matches[service_key] = matched_code
    return matches


async def build_report() -> dict[str, Any]:
    service_entries = iter_service_entries()
    hero_requested_map: dict[str, str] = {}
    vak_requested_map: dict[str, str] = {}
    provider_presence: dict[str, int] = defaultdict(int)
    provider_mapped_codes: dict[str, set[str]] = {provider: set() for provider in ALL_PROVIDERS}

    vak_catalog = _fetch_vaksms_catalog()
    vak_prices = _fetch_vaksms_prices()
    vak_matches = _build_vaksms_service_matches(service_entries, vak_catalog)

    for service_key, _entry in service_entries:
        provider_map = get_service_provider_map(service_key)
        for provider_code in ALL_PROVIDERS:
            mapped = str(provider_map.get(provider_code) or "").strip()
            if provider_code == "vaksms":
                mapped = vak_matches.get(service_key, "")
            if not mapped:
                continue
            provider_presence[provider_code] += 1
            provider_mapped_codes[provider_code].add(mapped)
            if provider_code == "herosms":
                hero_requested_map[service_key] = mapped
            if provider_code == "vaksms":
                vak_requested_map[service_key] = mapped

    smspool_prices, telabot_prices, nonvoip_prices, hero_prices = await asyncio.gather(
        _fetch_smspool_bulk_prices(),
        _fetch_telabot_bulk_prices(),
        _fetch_nonvoip_bulk_prices(),
        _fetch_hero_prices(hero_requested_map),
    )
    textverified_catalog = _build_textverified_coverage()

    bulk_price_index = _normalize_bulk_index()
    bulk_price_index["smspool"] = smspool_prices
    bulk_price_index["telabot"] = telabot_prices
    bulk_price_index["nonvoip"] = nonvoip_prices

    per_service_rows: list[dict[str, Any]] = []
    provider_summary: dict[str, dict[str, Any]] = {
        provider: {
            "mapped_services": provider_presence.get(provider, 0),
            "priced_services": 0,
            "cheapest_wins": 0,
            "unique_priced_services": 0,
            "coverage_only_services": 0,
            "overlap_count": 0,
            "avg_over_cheapest_pct": None,
            "median_price": None,
            "price_samples": [],
            "expensive_examples": [],
            "unique_examples": [],
        }
        for provider in ALL_PROVIDERS
    }
    provider_overpay_values: dict[str, list[float]] = defaultdict(list)

    for service_key, _entry in service_entries:
        display_name = get_service_display_name(service_key) or service_key
        provider_map = get_service_provider_map(service_key)
        prices: dict[str, float] = {}
        tv_covered = False

        for provider_code in BULK_PRICE_PROVIDERS:
            mapped = str(provider_map.get(provider_code) or "").strip()
            if not mapped:
                continue
            price = bulk_price_index.get(provider_code, {}).get(mapped)
            if price is not None:
                prices[provider_code] = price
                provider_summary[provider_code]["price_samples"].append(price)

        hero_code = str(provider_map.get("herosms") or "").strip()
        if hero_code:
            price = hero_prices.get(hero_code)
            if price is not None:
                prices["herosms"] = price
                provider_summary["herosms"]["price_samples"].append(price)

        vak_code = vak_requested_map.get(service_key, "")
        if vak_code:
            price = vak_prices.get(vak_code)
            if price is not None:
                prices["vaksms"] = price
                provider_summary["vaksms"]["price_samples"].append(price)

        tv_code = str(provider_map.get("textverified") or "").strip()
        if tv_code and tv_code in textverified_catalog:
            tv_covered = True

        if tv_covered:
            provider_summary["textverified"]["coverage_only_services"] += 1

        for provider_code in prices:
            provider_summary[provider_code]["priced_services"] += 1

        if len(prices) == 1:
            only_provider = next(iter(prices))
            provider_summary[only_provider]["unique_priced_services"] += 1
            if len(provider_summary[only_provider]["unique_examples"]) < 12:
                provider_summary[only_provider]["unique_examples"].append(
                    {"service_key": service_key, "display_name": display_name, "price": prices[only_provider]}
                )

        if len(prices) >= 2:
            cheapest_price = min(prices.values())
            cheapest_providers = sorted(provider for provider, price in prices.items() if abs(price - cheapest_price) < 1e-9)
            for provider_code, price in prices.items():
                provider_summary[provider_code]["overlap_count"] += 1
                if provider_code in cheapest_providers:
                    provider_summary[provider_code]["cheapest_wins"] += 1
                    continue
                overpay_pct = ((price / cheapest_price) - 1.0) * 100.0
                provider_overpay_values[provider_code].append(overpay_pct)
                expensive_examples = provider_summary[provider_code]["expensive_examples"]
                if len(expensive_examples) < 20:
                    expensive_examples.append(
                        {
                            "service_key": service_key,
                            "display_name": display_name,
                            "provider_price": price,
                            "cheapest_price": cheapest_price,
                            "cheapest_providers": cheapest_providers,
                            "overpay_pct": round(overpay_pct, 2),
                        }
                    )

        per_service_rows.append(
            {
                "service_key": service_key,
                "display_name": display_name,
                "prices": prices,
                "textverified_coverage_only": tv_covered,
            }
        )

    for provider_code, row in provider_summary.items():
        price_samples = list(row.pop("price_samples"))
        row["median_price"] = _median(price_samples)
        overpay_values = provider_overpay_values.get(provider_code, [])
        row["avg_over_cheapest_pct"] = round(sum(overpay_values) / len(overpay_values), 2) if overpay_values else None
        row["coverage_gap"] = row["mapped_services"] - row["priced_services"]

    dominated_candidates: list[dict[str, Any]] = []
    for provider_code, row in provider_summary.items():
        if provider_code == "textverified":
            continue
        dominated_candidates.append(
            {
                "provider": provider_code,
                "priced_services": row["priced_services"],
                "cheapest_wins": row["cheapest_wins"],
                "unique_priced_services": row["unique_priced_services"],
                "avg_over_cheapest_pct": row["avg_over_cheapest_pct"],
                "median_price": row["median_price"],
            }
        )

    dominated_candidates.sort(
        key=lambda row: (
            row["cheapest_wins"],
            row["unique_priced_services"],
            10**9 if row["avg_over_cheapest_pct"] is None else -row["avg_over_cheapest_pct"],
            row["priced_services"],
        )
    )

    return {
        "providers": provider_summary,
        "provider_codes": list(ALL_PROVIDERS),
        "service_count": len(service_entries),
        "comparable_service_count": sum(1 for row in per_service_rows if len(row["prices"]) >= 2),
        "priced_service_count": sum(1 for row in per_service_rows if row["prices"]),
        "dominance_ranking": dominated_candidates,
        "notes": {
            "textverified": "No bulk pricing endpoint is wired in the current provider layer. Coverage was measured, but prices were not bulk-compared.",
            "smspool": "Price comparison uses the cheapest available price per service across all countries from /request/pricing.",
            "herosms": "Prices were fetched per mapped service via getPrices because list_services does not expose price fields.",
            "nonvoip": "Comparison reflects the current NonVoIP reseller endpoint only.",
            "vaksms": "Coverage uses exact normalized name matches from the official VAK-SMS docs service table; prices come from the stub getPrices endpoint and were converted from RUB to USD.",
        },
    }


async def main() -> None:
    report = await build_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    await SessionManager.close()


if __name__ == "__main__":
    asyncio.run(main())
