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


def test_numbers_miniapp_country_suggestions_are_not_loaded_by_ui():
    app = (ROOT / "webapp" / "numbers" / "app.js").read_text(encoding="utf-8")

    assert "countrySuggestion" not in app
    assert "loadCountrySuggestions" not in app
    assert "country_suggestions" not in app
    assert "/mini/numbers/api/country-suggestions" not in app


def test_numbers_miniapp_v2_uses_server_driven_contracts():
    app = (ROOT / "webapp" / "numbers_v2" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "webapp" / "numbers_v2" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "webapp" / "numbers_v2" / "styles.css").read_text(encoding="utf-8")

    assert "/mini/numbers-v2/static/app.js" in index
    assert "20260603-v2-017" in index
    assert 'html lang="en" dir="ltr"' in index
    assert "شراء رقم جديد" not in index
    assert "state.clientActions = bootstrap.client?.actions || {}" in app
    assert "state.bootstrap?.client?.tabs" in app
    assert "row.purchase_action || actionFor" in app
    assert "const action = order.actions?.[key]" in app
    assert 'id="orderFilters"' in index
    assert "function renderOrderFilters()" in app
    assert "function orderMode(order)" in app
    assert "state.numberModeFilter" in app
    assert "numberModeFilters()" in app
    assert "\"test_active\"" in app
    assert 'id="countrySuggestions"' not in index
    assert 'id="menuDrawer"' in index
    assert 'id="menuList"' in index
    assert 'id="bottomNav"' not in index
    assert "loadCountrySuggestions" not in app
    assert "function openMenu()" in app
    assert "function closeMenu()" in app
    assert "function rechargeRateLabel(method)" in app
    assert "function renderRechargeMethodCard(method)" in app
    assert "recharge-method-card" in css
    assert "recharge-method-grid" in css
    assert "أي دولة" in app
    assert "function renderAccountActivity(item)" in app
    assert "quick-actions" not in app
    assert "account-activity" in css
    assert 'actionFor("country_suggestions"' not in app
    assert "RENTAL_UNLIMITED_SERVICE_KEY" in app
    assert "TEMP_NOT_LISTED_SERVICE_KEY" in app
    assert "function servicePickerRows()" in app
    assert "function notListedServiceRow(query)" in app
    assert "function fetchPricePayload(service)" in app
    assert "AbortController" in app
    assert "function updateOrderInState(order)" in app
    assert "function testActiveMessage(order)" in app
    assert "function orderWaitingForCode(order)" in app
    assert "function renderRefundSafetyNote()" in app
    assert "customerState.message_key ? labelForKey(customerState.message_key)" in app
    assert "customerState.status_label_key" in app
    assert "code-box-waiting" in css
    assert "refund-safety-note" in css
    assert 'id="resultModal"' in index
    assert "function showResultModal(message" in app
    assert "showResultModal(testActiveMessage" in app
    assert ".result-modal" in css
    assert "انتهت مهلة الاتصال" not in app
    assert "function looksLikeHtmlResponse(text)" in app
    assert 'code: "server_unavailable"' in app
    assert "function offerCountryDisplay(row)" in app
    assert "function rentalDurationChoices(rows)" in app
    assert "function rentalDurationSelector(rows)" in app
    assert "function rentalDurationGroup(hours)" in app
    assert "rental-duration-selector" in css
    assert "rental-duration-label" in css
    assert "state.rentalDurationFilter" in app
    assert "quote TTL 5" not in app
    assert "row.location_tag ||" in app
    assert "function countryNameFromValue(value)" in app
    assert "providerName.textContent = provider.name" in app
    assert "providerMeta.textContent = [countryTag, row.option_label]" in app
    assert "<strong>${provider.id}" not in app
    assert "function shouldTryNotListedFallback()" in app
    assert "function resetBuySelections" in app
    assert "function openIssueReport(order)" in app
    assert "function supportMessageHasUserText(value)" in app
    assert "function supportMessageText(value)" in app
    assert "\"report_issue\"" in app
    assert "supportOrderContext(order)" in app
    assert "function setLanguage(lang)" in app
    assert "document.documentElement.dir" in app
    assert "const i18n = {" in app
    assert "function downloadActivityCsv(button)" in app
    assert "function toggleAccountActivity(button)" in app
    assert "function changeAccountLanguage(language, button)" in app
    assert "account_activity" in app
    assert "account_activity_export" in app
    assert 'id="rechargeButton"' in index
    assert 'id="themeToggle"' in index
    assert "function toggleTheme(event)" in app
    assert "function pickerAllowsAnyCountry()" in app
    assert ".filter((row) => ![\"\", \"none\", \"any\"].includes(String(row.code || \"\").trim().toLowerCase()))" in app
    assert "key !== RENTAL_UNLIMITED_SERVICE_KEY && state.country === \"any\"" in app
    assert "return pickerAllowsAnyCountry() ? [anyCountry, ...countries] : countries" in app
    assert "state.fallbackOffer" in app
    assert "fallback_service" in app
    assert "hiddenServiceNeedles" in app
    assert "state.mode === \"temp\" && query" in app
    assert "button.append(document.createTextNode" in app
    assert "requests.slice(0, 4)" not in app
    assert "suggestedRegionIsos" not in app
    assert "function isFastSuggestionCountry" not in app
    assert "state.country === \"none\"" in app
    assert "state-hidden" in css
    assert "/mini/numbers/api/orders/${" not in app
    assert "miniapp-replace-" not in app
    assert "miniapp-alternate-" not in app
