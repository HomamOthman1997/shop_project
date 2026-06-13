from scripts.compare_mangerr_g2bulk_games import (
    compare_products,
    infer_game_family,
    normalize_g2bulk_product,
    normalize_mangerr_product,
)


def test_mangerr_uc_product_is_classified_as_pubg():
    item = normalize_mangerr_product(
        {
            "id": 365,
            "name": "UC 60",
            "category_name": "UC 60",
            "price": 0.104,
            "available": True,
            "params": ["playerId"],
        }
    )

    assert item is not None
    assert item.game_key == "pubg"
    assert item.compare_key == "pubg:global:60:uc"


def test_known_game_family_uses_static_catalog():
    assert infer_game_family("Wuthering Waves", "60 Lunites") == ("wuthering_waves", "Wuthering Waves")


def test_unknown_g2bulk_game_uses_its_game_name_as_family():
    item = normalize_g2bulk_product(
        {"code": "brand_new_game", "name": "Brand New Game"},
        {"id": 55, "name": "100 Coins", "price": 1.0},
    )

    assert item is not None
    assert item.game_key == "brand_new_game"


def test_mangerr_product_can_use_dynamic_g2bulk_game_alias():
    item = normalize_mangerr_product(
        {"id": 55, "name": "100 Coins", "category_name": "Brand New Game", "price": 0.9, "available": True},
        game_aliases={"brand new game": ("brand_new_game", "Brand New Game")},
    )

    assert item is not None
    assert item.game_key == "brand_new_game"


def test_comparison_matches_same_game_package_and_picks_cheaper():
    mangerr = normalize_mangerr_product(
        {
            "id": 365,
            "name": "UC 60",
            "category_name": "PUBG",
            "price": 0.104,
            "available": True,
        }
    )
    g2bulk = normalize_g2bulk_product(
        {"code": "pubgm", "name": "PUBG Mobile"},
        {"id": 99, "name": "60", "price": 0.12},
    )

    assert mangerr is not None
    assert g2bulk is not None
    result = compare_products([g2bulk], [mangerr])

    assert result["matches"][0]["cheaper_provider"] == "mangerr"
    assert result["matches"][0]["price_difference"] == 0.016
