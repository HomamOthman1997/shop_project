from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from services.numbers.api_payloads import country_rows, money_label
from services.numbers.manager import get_all_prices, get_all_rental_prices
from services.numbers.service_map import resolve_canonical_service_key

_CHEAP_COUNTRY_CACHE_TTL_SEC = 300
_CHEAP_COUNTRY_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}

_CHEAP_COUNTRY_ISOS = (
    "US",
    "GB",
    "DE",
    "CA",
    "FR",
    "NL",
    "PL",
    "RO",
    "CZ",
    "ES",
    "IT",
    "BE",
    "AT",
    "CH",
    "IE",
    "PT",
    "FI",
    "NO",
    "SE",
    "DK",
)

TempPriceFn = Callable[..., Awaitable[dict[str, Any]]]
RentalPriceFn = Callable[..., Awaitable[dict[str, Any]]]


def country_name(country_code: str) -> str:
    needle = str(country_code or "").strip()
    for item in country_rows():
        if str(item.get("code") or "") == needle:
            return str(item.get("name") or needle)
    return needle


def _country_code_by_iso() -> dict[str, str]:
    out: dict[str, str] = {}
    for item in country_rows():
        code = str(item.get("code") or "").strip()
        iso = str(item.get("iso") or "").strip().upper()
        if code and iso:
            out.setdefault(iso, code)
    return out


def cheap_country_candidate_codes() -> list[str]:
    by_iso = _country_code_by_iso()
    out: list[str] = []
    seen: set[str] = set()
    for iso in _CHEAP_COUNTRY_ISOS:
        code = by_iso.get(str(iso or "").upper())
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def best_available_country_price(prices: Any) -> float | None:
    best: float | None = None

    def visit(value: Any) -> None:
        nonlocal best
        if isinstance(value, dict):
            if "price" in value:
                try:
                    price = float(value.get("price") or 0.0)
                except Exception:
                    price = 0.0
                if price > 0 and (best is None or price < best):
                    best = price
            for nested in value.values():
                if isinstance(nested, (dict, list, tuple)):
                    visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)

    visit(prices)
    return best


async def country_suggestions_for_service(
    mode: str,
    service: str,
    limit: int = 10,
    *,
    get_temp_prices_fn: TempPriceFn = get_all_prices,
    get_rental_prices_fn: RentalPriceFn = get_all_rental_prices,
) -> list[dict[str, Any]]:
    canonical_service = resolve_canonical_service_key(str(service or ""))
    normalized_mode = str(mode or "temp").strip().lower()
    bounded_limit = max(1, min(int(limit or 10), 20))

    if not canonical_service or normalized_mode == "voice":
        return []

    cache_key = f"{normalized_mode}:{canonical_service}:{bounded_limit}"
    now_ts = time.time()
    cached = _CHEAP_COUNTRY_CACHE.get(cache_key)
    if cached and (now_ts - cached[0]) <= _CHEAP_COUNTRY_CACHE_TTL_SEC:
        return list(cached[1])[:bounded_limit]

    candidates = cheap_country_candidate_codes()
    sem = asyncio.Semaphore(min(6, len(candidates) or 1))

    async def fetch_country(country_code: str) -> dict[str, Any] | None:
        async with sem:
            try:
                if normalized_mode == "rental":
                    prices = await asyncio.wait_for(
                        get_rental_prices_fn(canonical_service, country_code, with_success_rates=False),
                        timeout=4.5,
                    )
                else:
                    prices = await asyncio.wait_for(
                        get_temp_prices_fn(
                            canonical_service,
                            country_code,
                            "none",
                            ignore_balance=True,
                            with_success_rates=False,
                        ),
                        timeout=4.5,
                    )
            except Exception:
                return None

            price = best_available_country_price(prices)
            if price is None:
                return None

            return {
                "code": country_code,
                "name": country_name(country_code),
                "price": float(price),
                "price_label": money_label(price),
            }

    rows = [row for row in await asyncio.gather(*(fetch_country(code) for code in candidates)) if row]
    priority = {code: index for index, code in enumerate(candidates)}
    rows.sort(key=lambda row: (priority.get(str(row.get("code") or ""), 999), float(row.get("price") or 0.0)))

    selected = rows[:bounded_limit]
    _CHEAP_COUNTRY_CACHE[cache_key] = (now_ts, selected)
    return list(selected)
