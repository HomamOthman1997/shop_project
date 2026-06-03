import os
import sys

sys.path.insert(0, os.getcwd())

from services.digital_products.fulfillment_rules import (
    game_default_unit,
    game_family_key,
    manual_feature_compare_key,
    manual_feature_info,
    offer_compare_key,
    offer_region_label,
)


def test_manual_feature_info_maps_current_feature_categories():
    assert manual_feature_info("PUBG MOBILE UC Vouchers", "8100 Uc Voucher")["family_key"] == "pubg"
    assert manual_feature_info("Yalla Ludo", "10$ USD - 5150 Diamond")["family_key"] == "yalla_ludo"
    assert manual_feature_info("New State Mobile", "300 NC")["family_key"] == "new_state"
    assert manual_feature_info("Roblox US Giftcards", "Roblox 10$ US")["region"] == "USA"


def test_manual_compare_key_prefers_game_currency_over_usd_face_value():
    assert manual_feature_compare_key("PUBG MOBILE UC Vouchers", "8100 Uc Voucher") == "pubg:global:8100:uc"
    assert manual_feature_compare_key("Yalla Ludo", "10$ USD - 5150 Diamond") == "yalla_ludo:global:5150:diamond"
    assert manual_feature_compare_key("Jawaker Gift Cards", "5$- 32500 Token") == "jawaker:global:32500:token"
    assert manual_feature_compare_key("Valorant GiftCard USA", "Valorant Riot 10$") == "valorant:usa:10:usd"


def test_auto_game_compare_key_matches_manual_when_same_amount_unit_region():
    family = game_family_key("pubgm", "PUBG Mobile")
    default_unit = game_default_unit("pubgm", "PUBG Mobile")
    assert offer_compare_key(family_key=family, region="Global", offer_name="8100", default_unit=default_unit) == "pubg:global:8100:uc"
    assert offer_compare_key(family_key="yalla_ludo", region="Global", offer_name="5150 Diamonds") == "yalla_ludo:global:5150:diamond"


def test_region_label_does_not_treat_latam_as_global():
    assert offer_region_label("Free Fire Diamonds LATAM") == "LATAM"
    assert offer_region_label("Some Game SEA") == "SEA"
    assert offer_region_label("Mobile Legends Bang Bang (RUSSIA) PIN") == "RU"
    assert offer_region_label("Garena Undawn RC (Philippines)") == "PH"
    assert offer_region_label("Steam Wallet Code Global") == "Global"
