from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from services.digital_products.lona_cards import (
    lona_products_for_category,
    quote_lona_product,
    validate_lona_amount,
)


DEC2 = Decimal("0.01")


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(DEC2, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")
    return amount


def _fmt_amount(value: Any) -> str:
    text = format(_money(value).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _norm(text: Any) -> str:
    raw = str(text or "").upper().strip()
    raw = re.sub(r"[^A-Z0-9]+", " ", raw)
    return " ".join(raw.split())


def _market(
    market_id: str,
    category_id: str,
    brand: str,
    region: str,
    *,
    brand_aliases: tuple[str, ...] = (),
    region_aliases: tuple[str, ...] = (),
    currency: str = "USD",
) -> dict[str, Any]:
    return {
        "id": market_id,
        "category_id": category_id,
        "brand": brand.upper(),
        "region": region.upper(),
        "currency": currency.upper(),
        "brand_aliases": tuple(alias.upper() for alias in (brand, *brand_aliases)),
        "region_aliases": tuple(alias.upper() for alias in (region, *region_aliases, "GLOBAL")),
    }


LONA_CARDEX_MARKETS: tuple[dict[str, Any], ...] = (
    _market("itunes_usa", "lona_itunes", "ITUNES", "USA", brand_aliases=("APPLE",), region_aliases=("US",)),
    _market("amazon_us", "lona_amazon_us", "AMAZON", "USA", region_aliases=("US",)),
    _market("amazon_uk", "lona_amazon_uk", "AMAZON", "UK", region_aliases=("UNITED KINGDOM", "GB")),
    _market("amazon_de", "lona_amazon_de", "AMAZON", "DE", region_aliases=("GERMANY", "GERMAN")),
    _market("amazon_fr", "lona_amazon_fr_it_es", "AMAZON", "FR", region_aliases=("FRANCE",)),
    _market("amazon_it", "lona_amazon_fr_it_es", "AMAZON", "IT", region_aliases=("ITALY",)),
    _market("amazon_es", "lona_amazon_fr_it_es", "AMAZON", "SPAIN", region_aliases=("ES",)),
    _market("uber_uk", "lona_uber_uk", "UBER", "UK", region_aliases=("UNITED KINGDOM", "GB")),
    _market("uber_us", "lona_uber_us", "UBER", "USA", region_aliases=("US",)),
    _market("walmart_usa", "lona_walmart", "WALMART", "USA", region_aliases=("US",)),
    _market("nintendo_global", "lona_nintendo", "NINTENDO", "GLOBAL", brand_aliases=("NETENDU",)),
    _market("razer_us", "lona_razer_us", "RAZER", "USA", brand_aliases=("RAYZER",), region_aliases=("US",)),
    _market("razer_global", "lona_razer_global", "RAZER", "GLOBAL", brand_aliases=("RAYZER",)),
    _market("steam_usa", "lona_steam_usa", "STEAM", "USA", region_aliases=("US",)),
    _market("canada_global", "lona_canada", "CANADA", "GLOBAL", brand_aliases=("CANADA CARDS",)),
    _market("playstation_usa", "lona_playstation", "PLAYSTATION", "USA", brand_aliases=("PSN",), region_aliases=("US",)),
    _market("starbucks_usa", "lona_starbucks", "STARBUCKS", "USA", region_aliases=("US",)),
    _market(
        "visa_tremendous",
        "lona_visa_tremendous",
        "VISA",
        "TREMENDOUS",
        brand_aliases=("VISA TREMENDOUS", "TREMENDOUS"),
        region_aliases=("GLOBAL",),
    ),
)


def _market_match_score(market: dict[str, Any], brand: str, region: str | None, currency: str | None) -> int:
    if _norm(currency or market.get("currency")) != _norm(market.get("currency")):
        return 0
    brand_norm = _norm(brand)
    if brand_norm not in {_norm(alias) for alias in market.get("brand_aliases") or ()}:
        return 0
    region_norm = _norm(region or "GLOBAL")
    if region_norm == _norm(market.get("region")):
        return 3
    if region_norm in {_norm(alias) for alias in market.get("region_aliases") or ()}:
        return 1 if region_norm == "GLOBAL" else 2
    return 0


def _market_matches(market: dict[str, Any], brand: str, region: str | None, currency: str | None) -> bool:
    return _market_match_score(market, brand, region, currency) > 0


def lona_cardex_market_for(brand: str, region: str | None, currency: str | None = "USD") -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any] | None] = (0, None)
    for market in LONA_CARDEX_MARKETS:
        score = _market_match_score(market, brand, region, currency)
        if score > best[0]:
            best = (score, market)
    return best[1]


def is_lona_cardex_managed(brand: str, region: str | None, currency: str | None = "USD") -> bool:
    return lona_cardex_market_for(brand, region, currency) is not None


def is_lona_cardex_managed_rule(row: dict[str, Any]) -> bool:
    return is_lona_cardex_managed(
        str(row.get("brand") or ""),
        str(row.get("region") or "GLOBAL"),
        str(row.get("currency") or "USD"),
    )


def _base_rule(market: dict[str, Any], product: dict[str, Any], *, label: str, denomination: Decimal) -> dict[str, Any]:
    meta = dict(product.get("manual_card") or {})
    rate = float(_money(meta.get("rate_percent") or 0))
    product_id = str(product.get("id") or "")
    return {
        "_id": f"lona-cardex:{market['id']}:{product_id}",
        "brand": str(market["brand"]),
        "region": str(market["region"]),
        "currency": str(market["currency"]),
        "denomination": float(_money(denomination)),
        "denominations": [float(_money(denomination))] if denomination > 0 else [],
        "denomination_label": label,
        "range_min": None,
        "range_max": None,
        "customer_buy_rate_percent": rate,
        "trader_rate_percent": rate,
        "public_note": "LONA rates. Warranty: 2 months.",
        "active": True,
        "lona_cardex": True,
        "lona_kind": str(meta.get("kind") or ""),
        "requires_custom_value": str(meta.get("kind") or "") in {"mixed", "amount"},
        "readonly": True,
    }


def lona_cardex_rules() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for market in LONA_CARDEX_MARKETS:
        products = lona_products_for_category(str(market["category_id"]))
        for product in products:
            meta = dict(product.get("manual_card") or {})
            kind = str(meta.get("kind") or "")
            if kind == "fixed":
                amount = _money(meta.get("face_value") or 0)
                rows.append(_base_rule(market, product, label=_fmt_amount(amount), denomination=amount))
            elif kind == "mixed":
                rows.append(_base_rule(market, product, label="Mixed", denomination=Decimal("0")))
            elif kind == "amount":
                rows.append(_base_rule(market, product, label="Custom Amount", denomination=Decimal("0")))
    return rows


def merge_lona_cardex_rules(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = [row for row in rows if not is_lona_cardex_managed_rule(row)]
    return lona_cardex_rules() + filtered


def quote_lona_cardex_submission(
    *,
    brand: str,
    denomination: Decimal,
    currency: str,
    region: str | None,
) -> dict[str, Any] | None:
    market = lona_cardex_market_for(brand, region, currency)
    if not market:
        return None
    amount = _money(denomination)
    products = lona_products_for_category(str(market["category_id"]))
    for product in products:
        meta = dict(product.get("manual_card") or {})
        if str(meta.get("kind") or "") != "fixed":
            continue
        if _money(meta.get("face_value") or 0) == amount:
            quote = quote_lona_product(str(market["category_id"]), str(product.get("id") or ""))
            if not quote:
                return None
            rule = _base_rule(market, product, label=_fmt_amount(amount), denomination=amount)
            return _quote_from_lona(rule, quote)
    for wanted_kind in ("mixed", "amount"):
        for product in products:
            meta = dict(product.get("manual_card") or {})
            if str(meta.get("kind") or "") != wanted_kind:
                continue
            ok, _reason = validate_lona_amount(str(market["category_id"]), str(product.get("id") or ""), amount)
            if not ok:
                continue
            quote = quote_lona_product(str(market["category_id"]), str(product.get("id") or ""), amount)
            if not quote:
                continue
            label = "Mixed" if wanted_kind == "mixed" else "Custom Amount"
            rule = _base_rule(market, product, label=label, denomination=Decimal("0"))
            return _quote_from_lona(rule, quote)
    return None


def _quote_from_lona(rule: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
    rate = Decimal(str(quote.get("rate_percent") or 0))
    face = Decimal(str(quote.get("face_value") or 0))
    value = (face * rate / Decimal("100")).quantize(DEC2, rounding=ROUND_HALF_UP)
    return {
        "configured": True,
        "rule": rule,
        "customer_buy_rate_percent": float(rate),
        "trader_rate_percent": float(rate),
        "customer_value_usd": float(value),
        "trader_value_usd": float(value),
        "public_note": str(rule.get("public_note") or ""),
    }
