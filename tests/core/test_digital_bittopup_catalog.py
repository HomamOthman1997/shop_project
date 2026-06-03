import os
import sys

sys.path.insert(0, os.getcwd())

from services.digital_products import catalog_service


def test_bittopup_provider_sources_become_manual_provider_offers():
    index = catalog_service._build_provider_source_index(
        [
            {
                "provider": "bittopup",
                "source_ref": "pubg#60-uc",
                "compare_key": "pubg:global:60:uc",
                "source_url": "https://bittopup.com/pubg/",
                "source_product_name": "PUBG Mobile UC",
                "source_denomination_name": "60 UC",
                "fulfillment_mode": "manual_topup",
                "active_price": 0.9,
                "available": True,
                "price_status": "active",
            }
        ]
    )

    offer = index["pubg:global:60:uc"][0]
    assert offer["provider"] == "bittopup"
    assert offer["price"] == 0.9
    assert offer["fulfillment_mode"] == "manual_topup"
    assert offer["source_url"] == "https://bittopup.com/pubg/"


def test_product_compare_key_matches_bittopup_pubg_source():
    assert (
        catalog_service._product_compare_key(
            category_name="PUBG MOBILE UC Vouchers",
            product_name="60 UC",
        )
        == "pubg:global:60:uc"
    )
