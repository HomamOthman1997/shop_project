from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_numbers_miniapp_has_recharge_surface_and_support_order_context():
    index = (ROOT / "webapp" / "numbers" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "webapp" / "numbers" / "app.js").read_text(encoding="utf-8")

    assert 'id="rechargeView"' in index
    assert 'id="rechargeDetails"' in index
    assert 'id="supportOrder"' in index
    assert "function surfaceTabs()" in app
    assert "clientActionEndpoint(\"recharge\"" in app
    assert 'clientActionEndpoint("recharge", "/mini/numbers/api/recharge")' in app
    assert 'clientActionEndpoint("country_suggestions", "/mini/numbers/api/country-suggestions")' in app
    assert 'clientActionEndpoint("purchase", "/mini/numbers/api/purchase")' in app
    assert 'clientActionEndpoint("orders", "/mini/numbers/api/orders")' in app
    assert "renderSupportOrders" in app


def test_numbers_miniapp_customer_state_copy_and_rendering_exist():
    app = (ROOT / "webapp" / "numbers" / "app.js").read_text(encoding="utf-8")

    assert "function customerState(order)" in app
    assert "function renderOrderStateNote(order)" in app
    assert "function orderActionEnabled(order, key" in app
    assert "waitForWebhook" in app
    assert "supportReviewQueued" in app


def test_numbers_miniapp_recording_preview_uses_telegram_auth_headers():
    app = (ROOT / "webapp" / "numbers" / "app.js").read_text(encoding="utf-8")

    assert "authHeaders(" not in app
    assert "headers: headers()" in app


def test_numbers_miniapp_order_actions_use_backend_endpoints():
    app = (ROOT / "webapp" / "numbers" / "app.js").read_text(encoding="utf-8")

    assert "function apiOrderAction(order, key" in app
    assert "function orderActionMetaText(order, key" in app
    assert "function orderActionIdempotencyKey(order, key)" in app
    assert "function purchaseAction(row)" in app
    assert "function clientAction(key" in app
    assert 'orderActionEndpoint(order, "download_recording"' in app
    assert 'orderActionEndpoint(order, "preview_recording"' in app
    assert 'api(action.endpoint' in app
    assert 'api(`/mini/numbers/api/country-suggestions?' not in app
    assert 'endpoint: action.endpoint || "/mini/numbers/api/purchase"' not in app
    assert "/mini/numbers/api/orders/${" not in app
    assert "fallbackEndpoint" not in app
    assert 'api(`/mini/numbers/api/orders/${encodeURIComponent(order.id)}/replace`' not in app
    assert 'api(`/mini/numbers/api/orders/${encodeURIComponent(order.id)}/alternate`' not in app
    assert 'api(`/mini/numbers/api/orders/${encodeURIComponent(order.id)}/second-code`' not in app


def test_numbers_miniapp_figma_skin_runtime_guards_are_present():
    app = (ROOT / "webapp" / "numbers" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "webapp" / "numbers" / "styles.css").read_text(encoding="utf-8")
    index = (ROOT / "webapp" / "numbers" / "index.html").read_text(encoding="utf-8")

    assert 'urlParams.get("qa") === "exact-mockup"' in app
    assert "function applyTelegramTheme()" in app
    assert 'tg?.onEvent?.("themeChanged", applyTelegramTheme)' in app
    assert 'body.telegram-webapp-runtime.telegram-dark' in css
    assert "2026-05-27 Figma production conversion" in css
    assert "20260527-figma-production" in index


def test_numbers_miniapp_provider_aliases_stay_customer_safe():
    app = (ROOT / "webapp" / "numbers" / "app.js").read_text(encoding="utf-8")

    assert '{ code: "S2", name: "Bravo" }' in app
    assert 'textverified: "S2"' in app
    assert 'smsready: "S9"' in app
    assert "REFERENCE_PROVIDER_IDS" in app
    assert "function isRecommendationTag" in app
    assert "row.location_tag && !isRecommendationTag(row.location_tag)" in app
    assert '{ code: "BR", name: "BRAVO" }' not in app
    assert '{ code: "HT", name: "HOTEL" }' not in app


def test_numbers_miniapp_v2_uses_server_driven_contracts():
    app = (ROOT / "webapp" / "numbers_v2" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "webapp" / "numbers_v2" / "index.html").read_text(encoding="utf-8")

    assert "/mini/numbers-v2/static/app.js" in index
    assert "state.clientActions = bootstrap.client?.actions || {}" in app
    assert "state.bootstrap?.client?.tabs" in app
    assert "row.purchase_action || actionFor" in app
    assert "const action = order.actions?.[key]" in app
    assert 'id="orderFilters"' in index
    assert "function renderOrderFilters()" in app
    assert "function orderBucket(order)" in app
    assert "state.orderFilter" in app
    assert 'id="countrySuggestions"' in index
    assert "function loadCountrySuggestions()" in app
    assert 'actionFor("country_suggestions"' in app
    assert "phantom_numbers_v2_prefs" in app
    assert "/mini/numbers/api/orders/${" not in app
    assert "miniapp-replace-" not in app
    assert "miniapp-alternate-" not in app
