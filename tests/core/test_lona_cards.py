import os
import sys

sys.path.insert(0, os.getcwd())

from decimal import Decimal

import handlers.store_sections as store_sections
from services.digital_products.lona_cards import (
    find_lona_product,
    is_lona_managed_category_name,
    lona_products_for_category,
    parse_face_value,
    quote_lona_product,
    validate_lona_amount,
)


def _product_by_kind(category_id: str, kind: str):
    for product in lona_products_for_category(category_id):
        if str((product.get("manual_card") or {}).get("kind") or "") == kind:
            return product
    raise AssertionError(f"missing {kind} product for {category_id}")


def _fixed_product(category_id: str, value: int):
    for product in lona_products_for_category(category_id):
        meta = product.get("manual_card") or {}
        if str(meta.get("kind") or "") == "fixed" and int(meta.get("face_value") or 0) == int(value):
            return product
    raise AssertionError(f"missing fixed {value} for {category_id}")


def test_itunes_fixed_and_mixed_pricing_rules():
    fixed_10 = _fixed_product("lona_itunes", 10)
    fixed_quote = quote_lona_product("lona_itunes", str(fixed_10["id"]))

    assert fixed_quote["rate_percent"] == 88.0
    assert fixed_quote["price"] == 8.80
    assert fixed_quote["warranty_months"] == 2

    mixed = _product_by_kind("lona_itunes", "mixed")
    ok, reason = validate_lona_amount("lona_itunes", str(mixed["id"]), Decimal("12"))
    assert ok is True
    assert reason == ""
    mixed_quote = quote_lona_product("lona_itunes", str(mixed["id"]), Decimal("12"))
    assert mixed_quote["rate_percent"] == 80.0
    assert mixed_quote["price"] == 9.60

    assert validate_lona_amount("lona_itunes", str(mixed["id"]), Decimal("10")) == (False, "fixed_value")
    assert validate_lona_amount("lona_itunes", str(mixed["id"]), Decimal("45")) == (False, "multiple_of_five")


def test_amazon_us_mixed_uses_newsletter_cap_and_rate():
    mixed = _product_by_kind("lona_amazon_us", "mixed")

    assert quote_lona_product("lona_amazon_us", str(mixed["id"]), Decimal("99"))["price"] == 76.23
    assert validate_lona_amount("lona_amazon_us", str(mixed["id"]), Decimal("100")) == (False, "fixed_value")
    assert validate_lona_amount("lona_amazon_us", str(mixed["id"]), Decimal("101")) == (False, "above_max")


def test_walmart_standard_and_stopped_values():
    amount = _product_by_kind("lona_walmart", "amount")
    fixed_55 = _fixed_product("lona_walmart", 55)

    assert quote_lona_product("lona_walmart", str(fixed_55["id"]))["price"] == 38.50
    assert quote_lona_product("lona_walmart", str(amount["id"]), Decimal("20"))["price"] == 14.60
    assert validate_lona_amount("lona_walmart", str(amount["id"]), Decimal("10")) == (False, "stopped")
    assert validate_lona_amount("lona_walmart", str(amount["id"]), Decimal("12")) == (False, "not_multiple_of_five")
    assert validate_lona_amount("lona_walmart", str(amount["id"]), Decimal("55")) == (False, "fixed_value")


def test_lona_categories_hide_matching_provider_categories():
    assert is_lona_managed_category_name("iTunes Gift Cards")
    assert is_lona_managed_category_name("Amazon US")
    assert not is_lona_managed_category_name("Discord Nitro")

    categories = store_sections._gift_categories_for_ui(
        {
            "enabled": True,
            "gift_categories": [
                {"id": "provider_itunes", "name": "iTunes Gift Cards", "clean_name": "iTunes"},
                {"id": "provider_discord", "name": "Discord Nitro", "clean_name": "Discord Nitro"},
            ]
        }
    )
    ids = [str(row.get("id") or "") for row in categories]

    assert "lona_itunes" in ids
    assert "provider_itunes" not in ids
    assert "provider_discord" in ids


def test_parse_face_value_accepts_common_formats():
    assert parse_face_value("$12") == Decimal("12.00")
    assert parse_face_value("12.5 usd") == Decimal("12.50")
    assert parse_face_value("1,000") == Decimal("1000.00")
    assert parse_face_value("abc") is None
