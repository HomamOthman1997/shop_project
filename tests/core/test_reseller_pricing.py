import os
import sys

sys.path.insert(0, os.getcwd())

from services.digital_products.reseller_pricing import (
    DEFAULT_CONFIG,
    PricingConfig,
    price_for_viewer,
    reseller_discount_labels,
    retail_price,
    tier_for_monthly_sales,
    wholesale_from_retail,
    wholesale_price,
)


# --- tiers by monthly purchase volume (bronze $1-500, silver 500-1000, gold 1000-2000, platinum 2000+) ---

def test_tier_for_monthly_sales_boundaries():
    assert tier_for_monthly_sales(0) == "bronze"
    assert tier_for_monthly_sales(1) == "bronze"
    assert tier_for_monthly_sales(499.99) == "bronze"
    assert tier_for_monthly_sales(500) == "silver"       # inclusive lower bound
    assert tier_for_monthly_sales(999.99) == "silver"
    assert tier_for_monthly_sales(1000) == "gold"
    assert tier_for_monthly_sales(1999.99) == "gold"
    assert tier_for_monthly_sales(2000) == "platinum"
    assert tier_for_monthly_sales(50000) == "platinum"


# --- retail (normal customer): cost * (1 + section margin) ---

def test_retail_price_games_is_7_percent():
    assert retail_price(100.0, "games") == 107.0
    assert retail_price(0.85, "games") == 0.91  # 0.9095 -> 0.91


def test_retail_price_store_cards_matches_games():
    assert retail_price(50.0, "store_cards") == retail_price(50.0, "games")


def test_retail_price_numbers_is_20_percent():
    assert retail_price(10.0, "numbers") == 12.0


# --- wholesale (reseller): games/cards = cost * (1 + tier margin) 5/4/3/2.5 ---

def test_wholesale_games_by_tier():
    assert wholesale_price("games", "bronze", cost=100.0) == 105.0
    assert wholesale_price("games", "silver", cost=100.0) == 104.0
    assert wholesale_price("games", "gold", cost=100.0) == 103.0
    assert wholesale_price("games", "platinum", cost=100.0) == 102.5


def test_wholesale_store_cards_uses_tier_margin():
    assert wholesale_price("store_cards", "platinum", cost=200.0) == 205.0  # 200 * 1.025


def test_wholesale_numbers_never_discounts():
    # numbers: reseller pays the same 20% as everyone
    for tier in ("bronze", "silver", "gold", "platinum"):
        assert wholesale_price("numbers", tier, cost=10.0) == 12.0


def test_wholesale_topup_is_flat_discount_off_retail():
    # Lifecell roaming retail $16 -> reseller $14.50, tier-independent
    for tier in ("bronze", "platinum"):
        assert wholesale_price("topup", tier, retail=16.0) == 14.5


def test_wholesale_topup_never_negative():
    assert wholesale_price("topup", "bronze", retail=1.0) == 0.0


def test_esim_uses_tier_margin_like_games():
    assert wholesale_price("esim", "gold", cost=100.0) == 103.0


# --- single entry point ---

def test_price_for_viewer_customer_vs_reseller():
    # no tier -> normal customer (7% on games)
    assert price_for_viewer("games", cost=100.0) == 107.0
    # a tier -> reseller wholesale
    assert price_for_viewer("games", tier="silver", cost=100.0) == 104.0
    # topup customer sees the admin-set retail as-is
    assert price_for_viewer("topup", retail=16.0) == 16.0
    assert price_for_viewer("topup", tier="gold", retail=16.0) == 14.5


# --- motivational discount labels (margin-point diff from bronze, hides real margins) ---

def test_reseller_discount_labels():
    labels = reseller_discount_labels()
    assert labels["bronze"] == 0.0
    assert labels["silver"] == 1.0     # 5 - 4
    assert labels["gold"] == 2.0       # 5 - 3
    assert labels["platinum"] == 2.5   # 5 - 2.5


# --- config overrides flow through ---

def test_config_overrides_change_pricing():
    cfg = PricingConfig().with_overrides(retail_margins={"games": 10.0, "store_cards": 10.0, "esim": 15.0, "numbers": 20.0})
    assert retail_price(100.0, "games", cfg) == 110.0
    # default is unchanged (frozen dataclass, no shared mutation)
    assert retail_price(100.0, "games") == 107.0


def test_unknown_tier_falls_back_to_bronze():
    assert wholesale_price("games", "diamond", cost=100.0) == 105.0


# --- wholesale_from_retail: derive reseller price from the stored retail price ---

def test_wholesale_from_retail_games_is_exact():
    # retail 107 = cost 100 * 1.07 -> bronze wholesale should recover 100*1.05 = 105
    assert wholesale_from_retail("games", "bronze", 107.0) == 105.0
    assert wholesale_from_retail("games", "silver", 107.0) == 104.0
    assert wholesale_from_retail("games", "gold", 107.0) == 103.0
    assert wholesale_from_retail("games", "platinum", 107.0) == 102.5


def test_wholesale_from_retail_store_cards():
    assert wholesale_from_retail("store_cards", "platinum", 107.0) == 102.5


def test_wholesale_from_retail_topup_flat():
    assert wholesale_from_retail("topup", "bronze", 16.0) == 14.5
    assert wholesale_from_retail("topup", "platinum", 16.0) == 14.5


def test_wholesale_from_retail_numbers_and_unknown_no_discount():
    assert wholesale_from_retail("numbers", "platinum", 12.0) == 12.0
    assert wholesale_from_retail("paid_subscriptions", "platinum", 20.0) == 20.0


def test_wholesale_from_retail_matches_cost_based_when_margins_align():
    # If retail was formed with the configured retail margin, the two paths agree.
    cost = 3.33
    retail = retail_price(cost, "games")            # cost * 1.07
    assert wholesale_from_retail("games", "gold", retail) == wholesale_price("games", "gold", cost=cost)
