import os
import sys

sys.path.insert(0, os.getcwd())


def test_digital_game_order_summary_contains_customer_details():
    from handlers.store_sections import _digital_game_order_summary_text

    text = _digital_game_order_summary_text(
        "en",
        order_id="747514",
        game_name="PUBG Mobile",
        package_name="8100 UC",
        player_id="123456",
        price=81.5,
        status="pending",
    )

    assert "Order Created Successfully" in text
    assert "Order ID: #747514" in text
    assert "Game: PUBG Mobile" in text
    assert "Package: 8100 UC" in text
    assert "Player ID: 123456" in text
    assert "Status: PENDING" in text


def test_digital_game_order_summary_includes_voucher_delivery_lines():
    from handlers.store_sections import _digital_game_order_summary_text

    text = _digital_game_order_summary_text(
        "en",
        order_id="747515",
        game_name="PUBG Mobile",
        package_name="1800 UC Voucher",
        player_id="123456",
        price=21.625,
        status="success",
        delivery_lines=["ZJRBuUUf232b37Fdc2"],
    )

    assert "Status: SUCCESS" in text
    assert "Code:" in text
    assert "ZJRBuUUf232b37Fdc2" in text


def test_manual_topup_notification_includes_provider_source_details():
    from handlers.store_sections import _manual_topup_notification_payload

    text, markup = _manual_topup_notification_payload(
        order={"_id": "order-1", "user_id": 123, "reseller_id": 456},
        item_name="60 UC",
        provider_code="bittopup",
        external_order_id="",
        player_data={"player_id": "5275962503"},
        delivery_lines=[],
        provider_offer={
            "ref_id": "pubg-mobile-uc#60-uc",
            "source_url": "https://bittopup.com/pubg-mobile-uc/",
            "source_product_name": "PUBG Mobile UC",
            "source_denomination_name": "60 UC",
            "price": 0.99,
        },
    )

    assert "Provider: bittopup" in text
    assert "Provider ref: pubg-mobile-uc#60-uc" in text
    assert "Source item: PUBG Mobile UC / 60 UC" in text
    assert "Source URL: https://bittopup.com/pubg-mobile-uc/" in text
    assert markup.inline_keyboard[0][0].callback_data == "dpm:done:order-1"


def test_bittopup_offer_is_external_manual_source():
    from handlers.store_sections import MANUAL_TOPUP_MODE, _is_external_manual_source_offer

    assert _is_external_manual_source_offer(
        {"provider": "bittopup", "fulfillment_mode": MANUAL_TOPUP_MODE, "source_url": "https://bittopup.com/pubg/"}
    )
    assert not _is_external_manual_source_offer({"provider": "g2bulk", "fulfillment_mode": MANUAL_TOPUP_MODE})
