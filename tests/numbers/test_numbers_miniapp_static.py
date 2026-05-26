from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_numbers_miniapp_has_recharge_surface_and_support_order_context():
    index = (ROOT / "webapp" / "numbers" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "webapp" / "numbers" / "app.js").read_text(encoding="utf-8")

    assert 'id="rechargeView"' in index
    assert 'id="rechargeDetails"' in index
    assert 'id="supportOrder"' in index
    assert '["recharge", t("tabRecharge"), "recharge"]' in app
    assert 'api("/mini/numbers/api/recharge")' in app
    assert 'api("/mini/numbers/api/orders")' in app
    assert "renderSupportOrders" in app


def test_numbers_miniapp_customer_state_copy_and_rendering_exist():
    app = (ROOT / "webapp" / "numbers" / "app.js").read_text(encoding="utf-8")

    assert "function customerState(order)" in app
    assert "function renderOrderStateNote(order)" in app
    assert "waitForWebhook" in app
    assert "supportReviewQueued" in app
