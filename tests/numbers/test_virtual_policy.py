from services.numbers.virtual_policy import apply_virtual_offer_policy, is_virtual_offer


def test_virtual_policy_blocks_sensitive_virtual_recommendations():
    offer = {
        "price": 0.36,
        "provider_country_iso": "USV",
        "available_for_buy": True,
    }

    apply_virtual_offer_policy(offer, service_key="gmail")

    assert offer["virtual_number"] is True
    assert offer["recommendation_blocked"] is True
    assert offer["recommendation_reason"] == "virtual_low_confidence"


def test_virtual_policy_keeps_non_sensitive_virtual_buyable():
    offer = {
        "price": 0.12,
        "provider_country": "United States Virtual",
        "available_for_buy": True,
    }

    apply_virtual_offer_policy(offer, service_key="discord")

    assert offer["virtual_number"] is True
    assert "recommendation_blocked" not in offer


def test_virtual_policy_detects_site_stock_location():
    offer = {
        "raw": {
            "site": {
                "id": "usv",
                "name": "United States Virtual",
                "available": [{"price": 0.36, "count": 100}],
            }
        }
    }

    assert is_virtual_offer(offer) is True
