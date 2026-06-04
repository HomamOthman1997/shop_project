import os
import sys

import pytest

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


def test_game_topup_can_reuse_matching_manual_future_offer():
    offers = catalog_service._matching_manual_game_source_offers(
        {
            "products_by_category": {
                "future": [
                    {
                        "compare_key": "pubg:global:1800:uc",
                        "clean_name": "1800 UC Voucher",
                        "provider_offers": [
                            {"provider": "g2bulk", "ref_id": "future-1800", "price": 20.5, "available": True, "source": "gift"}
                        ],
                    }
                ]
            }
        },
        compare_key="pubg:global:1800:uc",
    )

    assert offers[0]["provider"] == "g2bulk"
    assert offers[0]["source"] == "future"
    assert offers[0]["fulfillment_mode"] == "manual_topup"
    assert offers[0]["source_product_name"] == "G2Bulk Future"


@pytest.mark.asyncio
async def test_cached_game_topup_is_enriched_with_matching_manual_offer(monkeypatch):
    async def fake_active_sources(*, provider=None):
        return []

    monkeypatch.setattr(catalog_service, "list_active_provider_sources", fake_active_sources)

    rows = await catalog_service._enrich_cached_game_topups_with_manual_sources(
        [
            {
                "id": "2968",
                "name": "1800 UC",
                "price": 21.25,
                "compare_key": "pubg:global:1800:uc",
                "provider_offers": [{"provider": "g2bulk", "ref_id": "2968", "price": 21.25, "available": True}],
            }
        ],
        {
            "products_by_category": {
                "future": [
                    {
                        "compare_key": "pubg:global:1800:uc",
                        "clean_name": "1800 UC Voucher",
                        "provider_offers": [
                            {"provider": "g2bulk", "ref_id": "future-1800", "price": 20.5, "available": True, "source": "gift"}
                        ],
                    }
                ]
            }
        },
    )

    refs = {offer["ref_id"] for offer in rows[0]["provider_offers"]}
    assert {"2968", "future-1800"} <= refs
    assert rows[0]["best_provider_ref_id"] == "future-1800"


def test_product_compare_key_keeps_store_card_region():
    assert (
        catalog_service._product_compare_key(
            category_name="PlayStation Network Card (US)",
            product_name="10 USD",
        )
        == "playstation:usa:10:usd"
    )
    assert (
        catalog_service._product_compare_key(
            category_name="Steam Wallet Code Global",
            product_name="10 USD",
        )
        == "steam:global:10:usd"
    )


def test_product_compare_key_classifies_telegram_chat_products():
    assert (
        catalog_service._product_compare_key(
            category_name="Telegram Gifts",
            product_name="100 Stars",
        )
        == "telegram:global:100:star"
    )
