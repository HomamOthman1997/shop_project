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
