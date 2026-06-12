import json
import re

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from services import landing_page
from services.platform import owner_api, website_auth


def json_request(method: str, path: str, body: dict | None = None, *, token: str = ""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = make_mocked_request(method, path, headers=headers)
    request._read_bytes = json.dumps(body or {}).encode("utf-8")
    return request


def raw_request(method: str, path: str, body: str, *, content_type: str = "application/json"):
    request = make_mocked_request(method, path, headers={"Content-Type": content_type})
    request._read_bytes = body.encode("utf-8")
    return request


def test_register_website_auth_routes():
    app = web.Application()

    website_auth.register_website_auth_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("POST", "/api/v1/auth/register") in routes
    assert ("POST", "/api/v1/auth/login") in routes
    assert ("GET", "/api/v1/auth/me") in routes
    assert ("POST", "/api/v1/auth/language") in routes
    assert ("POST", "/api/v1/auth/password") in routes
    assert ("POST", "/api/v1/auth/telegram/link") in routes
    assert ("DELETE", "/api/v1/auth/telegram/link") in routes
    assert ("POST", "/api/v1/auth/email/send-code") in routes
    assert ("POST", "/api/v1/auth/email/verify") in routes
    assert ("GET", "/login") in routes
    assert ("GET", "/register") in routes
    assert ("GET", "/account") in routes
    assert ("GET", "/app") in routes
    assert ("GET", "/app/{tail}") in routes
    assert ("GET", "/admin") in routes
    assert ("GET", "/admin/{tail}") in routes


def test_shop_root_serves_public_landing_page():
    from services.digital_products.miniapp import create_app

    app = create_app()
    routes = {(route.method, route.resource.canonical, route.handler.__name__) for route in app.router.routes()}

    assert ("GET", "/", "landing_page") in routes
    assert ("GET", "/catalog", "catalog_page") in routes
    assert ("GET", "/catalog/{slug}/{category}", "catalog_page") in routes
    assert ("GET", "/catalog/{slug}", "catalog_page") in routes


def test_auth_page_loads_site_translator():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "index.html").read_text(encoding="utf-8")

    assert 'src="/auth/static/i18n.js"' in html
    assert html.index("/auth/static/i18n.js") < html.index("/auth/static/app.js")


def test_owner_dashboard_frontend_guards_stale_tab_loads():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")

    assert "let ownerDashboardLoadId = 0;" in js
    assert "const loadId = ++ownerDashboardLoadId;" in js
    assert "const loadTab = activeOwnerTab;" in js
    assert "loadId !== ownerDashboardLoadId || loadTab !== activeOwnerTab" in js


@pytest.mark.asyncio
async def test_public_landing_page_links_to_auth_and_service_routes():
    response = await landing_page.landing_page(make_mocked_request("GET", "/"))

    assert response.status == 200
    text = response.text
    assert 'href="/login"' in text
    assert 'href="/register"' in text
    assert 'href="/catalog"' in text
    assert 'href="/catalog/games"' in text
    assert 'href="/catalog/chat-apps"' in text
    assert 'href="/catalog/social-services"' in text
    assert 'href="/catalog/subscriptions"' in text
    assert 'href="/catalog/store-cards"' in text
    assert 'href="/catalog/verification-numbers"' in text
    assert 'href="/catalog/internet-providers"' in text
    assert 'href="/catalog/paid-apps"' in text
    assert "الشراء" not in text
    assert "طلباتي" not in text


@pytest.mark.asyncio
async def test_public_catalog_page_exposes_sections_without_checkout():
    response = await landing_page.catalog_page(make_mocked_request("GET", "/catalog"))

    assert response.status == 200
    text = response.text
    assert "كتالوغ Phantom" in text
    assert 'href="/catalog/games"' in text
    assert 'href="/catalog/chat-apps"' in text
    assert 'href="/catalog/social-services"' in text
    assert 'href="/catalog/subscriptions"' in text
    assert 'href="/catalog/store-cards"' in text
    assert 'href="/catalog/verification-numbers"' in text
    assert 'href="/catalog/internet-providers"' in text
    assert 'href="/catalog/paid-apps"' in text
    assert 'href="/catalog/mobile-recharge"' in text
    assert 'href="/register"' in text
    assert 'href="/login"' in text
    assert "PUBG Mobile UC" not in text


@pytest.mark.asyncio
async def test_public_catalog_section_limits_to_selected_group():
    request = make_mocked_request("GET", "/catalog/numbers", match_info={"slug": "numbers"})
    response = await landing_page.catalog_page(request)

    assert response.status == 200
    text = response.text
    assert "<h1>أرقام تأكيد</h1>" in text
    assert "اختر الصنف الفرعي" in text
    assert "أرقام مؤقتة" in text
    assert "شراء رقم لمدة قصيرة" not in text
    assert "PUBG و BGMI" not in text


@pytest.mark.asyncio
async def test_public_catalog_keeps_digital_alias_for_games_section():
    request = make_mocked_request("GET", "/catalog/digital", match_info={"slug": "digital"})
    response = await landing_page.catalog_page(request)

    assert response.status == 200
    assert "<h1>الألعاب</h1>" in response.text


@pytest.mark.asyncio
async def test_public_catalog_query_category_filters_section_items():
    request = make_mocked_request("GET", "/catalog/digital?category=games", match_info={"slug": "digital"})
    response = await landing_page.catalog_page(request)

    assert response.status == 200
    assert "<h1>شحن ألعاب الموبايل</h1>" in response.text
    assert "PUBG Mobile UC" in response.text
    assert "Adobe" not in response.text


@pytest.mark.asyncio
async def test_public_catalog_nested_category_filters_section_items():
    request = make_mocked_request(
        "GET",
        "/catalog/digital/games",
        match_info={"slug": "digital", "category": "games"},
    )
    response = await landing_page.catalog_page(request)

    assert response.status == 200
    assert "<h1>شحن ألعاب الموبايل</h1>" in response.text
    assert "PUBG Mobile UC" in response.text
    assert "Adobe" not in response.text


@pytest.mark.asyncio
async def test_website_auth_page_contains_admin_dashboard_tabs():
    response = await website_auth.auth_page(make_mocked_request("GET", "/admin"))

    assert response.status == 200
    text = response.text
    assert 'class="admin-tabs"' in text
    assert 'data-owner-tab="finance"' in text
    assert 'data-owner-tab="orders"' in text


@pytest.mark.asyncio
async def test_website_auth_page_contains_owner_sidebar_navigation():
    response = await website_auth.auth_page(make_mocked_request("GET", "/admin"))

    assert response.status == 200
    text = response.text
    assert 'class="nav-item owner-nav"' in text
    assert 'data-owner-tab="overview"' in text
    assert 'data-owner-tab="system"' in text
    assert 'data-view="owner"' not in text


def test_customer_dashboard_has_recharge_support_and_order_filter_tabs():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    html = (root / "webapp" / "auth" / "index.html").read_text(encoding="utf-8")
    js = (root / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")
    css = (root / "webapp" / "auth" / "styles.css").read_text(encoding="utf-8")
    i18n = (root / "webapp" / "auth" / "i18n.js").read_text(encoding="utf-8")

    assert 'data-view="recharge"' in html
    assert 'data-panel="recharge"' in html
    assert 'id="support-ticket-form"' in html
    assert 'id="support-ticket-list"' in html
    assert 'id="support-ticket-detail"' in html
    assert 'id="download-activity"' in html
    assert 'id="password-change-form"' in html
    assert 'id="identity-message"' in html
    assert 'id="auth-context-message"' in html
    assert 'data-order-filter="numbers"' in html
    assert 'data-order-filter="digital"' in html
    assert 'recharge: "/app/recharge"' in js
    assert "function appLanguage" in js
    assert "function persistAccountLanguage" in js
    assert 'api("/api/v1/auth/language"' in js
    assert "currentAccount.language === language" in js
    assert 'api("/api/v1/numbers/account")' in js
    assert "function combinedRecentActivity" in js
    assert "function activityAmountLabel" in js
    assert "function downloadAccountActivity" in js
    assert "function submitPasswordChange" in js
    assert 'api("/api/v1/auth/password"' in js
    assert "/api/v1/numbers/account/activity.csv?language=" in js
    assert "digitalAccount.wallet?.balance_label || numbersAccount.wallet?.balance_label" in js
    assert "function settledValue" in js
    assert "function renderLoadError" in js
    assert "function friendlyApiMessage" in js
    assert "email verification required" in js
    assert "يجب تأكيد البريد الإلكتروني قبل تنفيذ هذا الإجراء." in js
    assert "function authContextForPath" in js
    assert "applyAuthContextMessage();" in js
    assert "بعد الدخول سنعيدك إلى نفس القسم." in js
    assert 'if (pathname.startsWith("/app/services")) return "home";' in js
    assert "function setPostAuthMessage" in js
    assert 'setPostAuthMessage(message, "تم تأكيد البريد.");' in js
    assert 'setPostAuthMessage(message, "البريد مؤكد مسبقا.");' in js
    assert "Promise.allSettled" in js
    assert "/api/v1/numbers/recharge/requests?limit=10&language=" in js
    assert "/api/v1/numbers/support?language=" in js
    assert "/api/v1/digital/orders/${encodeURIComponent(orderId)}" in js
    assert 'api("/api/v1/numbers/support/ticket"' in js
    assert 'numbersApiEndpoint("quotes", "/api/v1/numbers/quotes")' in js
    assert 'numbersApiEndpoint("create_order", "/api/v1/numbers/orders")' in js
    assert "const quoteToken = row.quote_token || row.purchase_action?.body?.quote_token" in js
    assert 'body: JSON.stringify({ quote_token: quoteToken, language: appLanguage() })' in js
    assert "const productCategories = payload.product_categories || [];" in js
    assert 'class="digital-category-tabs"' in js
    assert 'data-digital-filter="category:${esc(row.id)}"' in js
    assert 'row.category === selectedCategory' in js
    assert ".numbers-app-shell" in css
    assert ".numbers-picker-drawer" in css
    assert ".digital-category-tabs" in css
    assert '"الأمان": "Security"' in i18n
    assert '"تغيير كلمة المرور": "Change password"' in i18n
    assert ".language-toggle {" in i18n
    assert "bottom: auto;" in i18n
    assert 'const button = event.currentTarget.querySelector("button[type=\'submit\']");' in js
    assert "function numberClientActionsHtml" in js
    assert "function copyOrderValue" in js
    assert "function downloadOrderAction" in js
    assert "download_recording: \"تحميل التسجيل\"" in js
    assert "rental_notes: \"ملاحظات الإيجار\"" in js
    assert "data-copy-order-value" in js
    assert 'if (actionKey === "download_recording"' in js
    assert "options.body = JSON.stringify({ language: appLanguage() });" in js
    assert "function renderSupportTickets" in js
    assert "function renderSupportTicketDetail" in js
    assert "function submitSupportTicketReply" in js
    assert "/api/v1/numbers/support/tickets/" in js
    assert "renderSupportTickets(support)" in js
    assert "$(\"#identity-message\")" in js
    assert "جاري إرسال طلب مراجعة الهوية..." in js
    assert "تم إرسال طلب مراجعة الهوية." in js
    assert "نعمل على صندوق تذاكر" not in js
    assert "إرسال إثبات الدفع من الموقع غير مفعّل بعد" not in js
    assert "رفع صور الوثائق سيضاف" not in html
    assert "الدعم غير مفعّل حالياً" in js
    assert '"تذاكري": "My tickets"' in i18n
    assert '"فتح تذكرة دعم": "Open support ticket"' in i18n
    assert '"الرصيد والمدفوعات": "Balance and payments"' in i18n
    assert '"ردك": "Your reply"' in i18n
    assert '"انتهت الجلسة. سجّل دخولك مرة أخرى للمتابعة.": "Your session expired. Sign in again to continue."' in i18n
    assert '"يجب تأكيد البريد الإلكتروني قبل تنفيذ هذا الإجراء.": "You must verify your email before performing this action."' in i18n
    assert '"هذه الصفحة مخصصة لحساب المالك فقط.": "This page is for the owner account only."' in i18n
    assert '"سجّل دخولك أو أنشئ حساباً للمتابعة إلى هذه الصفحة. بعد الدخول سنعيدك إلى نفس القسم.": "Sign in or create an account to continue to this page. After signing in, we will return you to the same section."' in i18n
    assert '"سجّل دخولك بحساب المالك للوصول إلى لوحة الإدارة.": "Sign in with the owner account to access the admin dashboard."' in i18n
    assert '"تتم المراجعة حالياً من بياناتك الأساسية، وقد يطلب الدعم وثائق إضافية عند الحاجة.": "Review currently uses your basic details, and support may request additional documents when needed."' in i18n
    assert '"تم إرسال طلب مراجعة الهوية.": "Identity review request submitted."' in i18n
    assert '"تعذر تحميل نشاط الحساب حالياً.": "Could not load account activity right now."' in i18n
    assert '"تعذر تحميل طرق الشحن حالياً.": "Could not load recharge methods right now."' in i18n
    assert '"تعذر تحميل خيارات الدعم حالياً.": "Could not load support options right now."' in i18n
    assert '"تم تحميل الطلبات المتاحة فقط. تعذر تحميل أحد الأقسام مؤقتاً.": "Only available orders were loaded. One section could not be loaded temporarily."' in i18n
    assert '"يمكنك نسخ بيانات الدفع من هنا. إذا لم يظهر نموذج رفع الإثبات، افتح تذكرة من مركز الدعم بعد التحويل.": "You can copy payment details here. If the proof upload form does not appear, open a support ticket after the transfer."' in i18n
    assert ".support-ticket-detail" in css
    assert ".support-reply-form" in css
    assert ".support-ticket-form" in css
    assert ".security-form" in css
    assert ".auth-context-message" in css
    assert ".order-filter-bar" in css


def test_customer_dashboard_keeps_products_out_of_account_sections():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "index.html").read_text(encoding="utf-8")
    account_block = html[html.index('data-panel="account"'): html.index('data-panel="support"')]

    assert 'id="recharge-list"' not in account_block
    assert "Telegram" in account_block
    assert 'id="activity-list"' in account_block


def test_owner_dashboard_tabs_have_routes_nav_and_content_groups():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    html = (root / "webapp" / "auth" / "index.html").read_text(encoding="utf-8")
    js = (root / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")
    owner_titles_block = js[js.index("const ownerTabTitles"): js.index("function setPageTitle")]
    owner_groups_block = js[js.index("const ownerGroupTargets"): js.index("const ownerLoadingLabels")]

    route_keys = set(re.findall(r"^\s+([a-z_]+):\s+\"/admin", js, flags=re.MULTILINE))
    title_keys = set(re.findall(r"^\s+([a-z_]+):\s+\"", owner_titles_block, flags=re.MULTILINE))
    group_keys = set(re.findall(r"^\s+([a-z_]+):\s+\[", owner_groups_block, flags=re.MULTILINE))
    sidebar_keys = set(re.findall(r'class="nav-item owner-nav"[^>]+data-owner-tab="([^"]+)"', html))
    header_tab_keys = set(re.findall(r'class="admin-tab[^"]*"[^>]+data-owner-tab="([^"]+)"', html))

    assert route_keys == title_keys == group_keys == sidebar_keys == header_tab_keys
    for _group, raw_ids in re.findall(r'^\s+([a-z_]+):\s+\[([^\]]+)\]', owner_groups_block, flags=re.MULTILINE):
        for node_id in re.findall(r'"([^"]+)"', raw_ids):
            assert f'id="{node_id}"' in html


def test_every_owner_api_route_has_a_dashboard_callsite():
    from pathlib import Path

    app = web.Application()
    owner_api.register_owner_api_routes(app)
    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")
    api_calls = [
        next(value for value in groups if value)
        for groups in re.findall(r"""(?:api|ownerApi)\((?:`([^`]+)`|"([^"]+)"|'([^']+)')""", js)
    ]
    missing = []
    for route in app.router.routes():
        if route.method == "HEAD":
            continue
        canonical = route.resource.canonical
        if canonical == "/api/v1/owner/recharge-reviews/{request_id}/proof" and "row.proof_url" in js:
            continue
        parts = [part for part in re.split(r"\{[^}]+\}", canonical) if part]
        if not any(all(part in call for part in parts) for call in api_calls):
            missing.append(f"{route.method} {canonical}")

    assert missing == []


def test_owner_dashboard_overview_shortcuts_cover_management_sections():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    js = (root / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")
    owner_api = (root / "services" / "platform" / "owner_api.py").read_text(encoding="utf-8")
    shortcut_block = js[js.index("const ownerShortcutTabs"): js.index("const ownerGroupTargets")]
    group_block = js[js.index("const ownerGroupTargets"): js.index("const ownerLoadingLabels")]
    management_block = owner_api[owner_api.index("def _management_sections"): owner_api.index("async def owner_dashboard")]

    management_keys = set(re.findall(r'\{"key": "([^"]+)"', management_block))
    section_keys = {"operations", "finance", "catalog", "system"}
    miniapp_only = {"cardex_admin"}
    shortcut_pairs = dict(re.findall(r'^\s+([a-z_]+):\s+"([a-z_]+)"', shortcut_block, flags=re.MULTILINE))
    owner_tabs = set(re.findall(r'^\s+([a-z_]+):\s+\[', group_block, flags=re.MULTILINE))

    assert "function openOwnerShortcut" in js
    assert 'data-owner-shortcut' in js
    assert (management_keys - section_keys - miniapp_only) <= set(shortcut_pairs)
    assert set(shortcut_pairs.values()) <= owner_tabs


def test_owner_admin_tools_are_grouped_by_operational_area():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    html = (root / "webapp" / "auth" / "index.html").read_text(encoding="utf-8")
    js = (root / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")
    shortcut_block = js[js.index("const ownerShortcutTabs"): js.index("const ownerGroupTargets")]
    group_block = js[js.index("const ownerGroupTargets"): js.index("const ownerLoadingLabels")]
    request_block = js[js.index("function ownerRequestMap"): js.index("function tagOwnerGroups")]

    assert 'id="owner-broadcast-tools"' in html
    assert 'id="owner-reseller-deposit-tools"' in html
    assert 'id="owner-bot-tools"' in html
    assert 'broadcast: "system"' in shortcut_block
    assert 'reseller_deposits: "finance"' in shortcut_block
    assert 'bot_subscriptions: "integrations"' in shortcut_block
    assert '"owner-broadcast-tools"' in group_block
    assert '"owner-reseller-deposit-tools"' in group_block
    assert 'integrations: {' in request_block
    assert 'bots: () => ownerApi("/api/v1/owner/bots?status=all&limit=30")' in request_block


def test_owner_api_calls_use_extended_timeout_helper():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")

    assert "const OWNER_API_TIMEOUT_MS = 45000;" in js
    assert "function ownerApi(path, options = {})" in js
    assert "return api(path, {timeoutMs: OWNER_API_TIMEOUT_MS, ...options});" in js
    assert 'api("/api/v1/owner' not in js
    assert "api(`/api/v1/owner" not in js


def test_owner_numbers_markup_is_editable_from_dashboard():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")
    settings_block = js[js.index("function renderOwnerSettings"): js.index("function renderOwnerPaymentMethods")]

    assert 'data-owner-setting="numbers_markup_percent"' in settings_block
    assert 'value="${esc(finance.numbers_markup_percent || 0)}"' in settings_block
    assert "معطل مؤقتاً" not in settings_block


def test_owner_audit_trail_has_connected_filters():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")

    assert 'let ownerAuditFilters = {q: "", action: "", target_type: ""};' in js
    assert 'new URLSearchParams({limit: "50"})' in js
    assert 'id="owner-audit-filter-form"' in js
    assert 'id="owner-audit-filter-reset"' in js
    assert 'addEventListener("submit", applyOwnerAuditFilters)' in js
    assert 'addEventListener("click", resetOwnerAuditFilters)' in js


def test_owner_user_management_has_connected_pagination():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")

    assert "let ownerUserRows = [];" in js
    assert "let ownerUserQuery = \"\";" in js
    assert 'id="owner-users-load-more"' in js
    assert "function loadMoreOwnerUsers(event)" in js
    assert "renderOwnerUserManagement(payload, true);" in js


def test_owner_reseller_management_has_connected_pagination():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")

    assert "let ownerResellerRows = [];" in js
    assert "let ownerResellerQuery = \"\";" in js
    assert 'id="owner-resellers-load-more"' in js
    assert "function loadMoreOwnerResellers(event)" in js
    assert "renderOwnerResellerManagement(payload, true);" in js


def test_owner_operational_lists_have_connected_pagination():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")

    assert "let ownerPagedRows = {};" in js
    assert "function ownerPagedItems(key, payload, field, append = false)" in js
    assert "function ownerPagedRequest(key, offset)" in js
    assert "async function loadMoreOwnerList(button)" in js
    for key in ("digital", "preorders", "refunds", "recharge", "identity", "support", "botCreationReviews", "bots"):
        assert f'ownerPaginationButton("{key}"' in js
        assert f"{key}:" in js
    assert 'ownerPaginationButton("ownerAudit"' in js
    assert 'ownerPaginationButton("apiKeys"' in js
    assert 'ownerPaginationButton("webhooks"' in js
    assert "async function loadMoreOwnerAudit(event)" in js
    assert "async function loadMoreOwnerIntegration(button)" in js
    assert 'ownerPaginationButton("providerEvents"' in js
    assert 'ownerPaginationButton("providerSources"' in js
    assert "async function loadMoreOwnerProviderDiagnostics(button)" in js


def test_owner_provider_source_links_reject_unsafe_protocols():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")

    assert "function safeExternalUrl(value)" in js
    assert '[\"http:\", \"https:\"].includes(url.protocol)' in js
    assert 'href="${esc(safeExternalUrl(source.source_url))}"' in js
    assert 'rel="noopener noreferrer"' in js


def test_owner_routing_cards_use_stable_field_group():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    js = (root / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")
    css = (root / "webapp" / "auth" / "styles.css").read_text(encoding="utf-8")

    assert 'class="owner-routing-fields"' in js
    assert ".owner-routing-fields" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    mobile_block = css[css.index("@media (max-width: 820px)"): css.index("/* Desktop website polish */")]
    assert ".owner-routing-fields { grid-template-columns: 1fr; }" in mobile_block
    assert ".owner-routing-fields input" in css


def test_owner_action_feedback_is_visible_on_desktop_and_mobile():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "styles.css").read_text(encoding="utf-8")

    assert "#owner-message:not(:empty)" in css
    assert "position: fixed;" in css
    assert "z-index: 30;" in css
    assert "width: calc(100vw - 24px);" in css


def test_sensitive_owner_actions_require_confirmation():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")

    assert "Pay the $1 bug reward to this user?" in js
    assert "Approve this identity verification request" in js
    assert "Reject this recharge request?" in js
    assert "Reject this reseller bot creation request?" in js


def test_owner_recharge_reviews_render_uploaded_proof_link():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    js = (root / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")
    css = (root / "webapp" / "auth" / "styles.css").read_text(encoding="utf-8")

    assert "row.proof_url" in js
    assert 'href="${esc(row.proof_url)}"' in js
    assert 'target="_blank"' in js
    assert ".button-link" in css


def test_sensitive_owner_forms_block_duplicate_submissions():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "webapp" / "auth" / "app.js").read_text(encoding="utf-8")

    assert "function setOwnerFormBusy(form, busy)" in js
    assert 'form.setAttribute("aria-busy", busy ? "true" : "false");' in js
    assert js.count("setOwnerFormBusy(form, true);") >= 6
    assert js.count("setOwnerFormBusy(form, false);") >= 6


def test_password_hash_round_trip():
    salt, password_hash = website_auth._password_hash("long-secure-password")

    assert website_auth._password_matches(
        "long-secure-password",
        {"password_salt": salt, "password_hash": password_hash},
    )
    assert not website_auth._password_matches(
        "wrong-password",
        {"password_salt": salt, "password_hash": password_hash},
    )


@pytest.mark.asyncio
async def test_change_password_updates_hash_after_current_password_check(monkeypatch):
    old_salt, old_hash = website_auth._password_hash("old-secure-password")
    saved = {}

    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def account(_account_id):
        return {
            "_id": "account-1",
            "customer_id": 900000000001,
            "email": "user@example.com",
            "password_salt": old_salt,
            "password_hash": old_hash,
            "status": "active",
        }

    async def update(account_id, *, salt, password_hash, now):
        saved.update({"account_id": account_id, "password_salt": salt, "password_hash": password_hash, "now": now})
        return {
            "_id": account_id,
            "customer_id": 900000000001,
            "email": "user@example.com",
            "password_salt": salt,
            "password_hash": password_hash,
            "status": "active",
        }

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    monkeypatch.setattr(website_auth, "update_website_account_password", update)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))

    response = await website_auth.change_password(
        json_request(
            "POST",
            "/api/v1/auth/password",
            {"current_password": "old-secure-password", "new_password": "new-secure-password"},
        )
    )
    body = json.loads(response.text)

    assert response.status == 200
    assert body["ok"] is True
    assert saved["account_id"] == "account-1"
    assert website_auth._password_matches("new-secure-password", saved)
    assert not website_auth._password_matches("old-secure-password", saved)


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current_password(monkeypatch):
    old_salt, old_hash = website_auth._password_hash("old-secure-password")

    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def account(_account_id):
        return {
            "_id": "account-1",
            "password_salt": old_salt,
            "password_hash": old_hash,
            "status": "active",
        }

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))

    with pytest.raises(web.HTTPUnauthorized):
        await website_auth.change_password(
            json_request(
                "POST",
                "/api/v1/auth/password",
                {"current_password": "wrong-secure-password", "new_password": "new-secure-password"},
            )
        )


@pytest.mark.asyncio
async def test_change_password_rejects_reused_password(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))

    response = await website_auth.change_password(
        json_request(
            "POST",
            "/api/v1/auth/password",
            {"current_password": "same-secure-password", "new_password": "same-secure-password"},
        )
    )
    body = json.loads(response.text)

    assert response.status == 400
    assert body["message"] == "new password must be different"


def test_public_account_requires_verified_email_for_buying():
    account = website_auth._public_account(
        {
            "_id": "account-1",
            "customer_id": 900000000001,
            "email": "user@example.com",
            "identity_status": "not_submitted",
        }
    )
    assert account["email_verified"] is False
    assert account["capabilities"]["buy_services"] is False

    verified = website_auth._public_account({**account, "_id": "account-1", "email_verified_at": website_auth._now()})
    assert verified["email_verified"] is True
    assert verified["capabilities"]["buy_services"] is True

    linked = website_auth._public_account({**account, "_id": "account-1", "telegram_id": 123})
    assert linked["capabilities"]["buy_services"] is False


@pytest.mark.asyncio
async def test_update_language_persists_website_account_language(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    saved = {}

    async def update(account_id, customer_id, language, *, now):
        saved.update({"account_id": account_id, "customer_id": customer_id, "language": language, "now": now})
        return {
            "_id": account_id,
            "customer_id": customer_id,
            "email": "user@example.com",
            "status": "active",
            "language": language,
        }

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "update_website_account_language", update)

    response = await website_auth.update_language(
        json_request("POST", "/api/v1/auth/language", {"language": "en"})
    )
    body = json.loads(response.text)

    assert response.status == 200
    assert saved["account_id"] == "account-1"
    assert saved["customer_id"] == 900000000001
    assert saved["language"] == "en"
    assert body["account"]["language"] == "en"


@pytest.mark.asyncio
async def test_update_language_rejects_invalid_language(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    monkeypatch.setattr(website_auth, "require_website_auth", auth)

    response = await website_auth.update_language(
        json_request("POST", "/api/v1/auth/language", {"language": "fr"})
    )
    body = json.loads(response.text)

    assert response.status == 400
    assert body["message"] == "invalid language"


def test_public_account_marks_configured_owner(monkeypatch):
    monkeypatch.setattr(website_auth.settings, "website_owner_email", "homamothman1@gmail.com", raising=False)

    account = website_auth._public_account(
        {
            "_id": "owner-1",
            "customer_id": 900000000001,
            "email": "HomamOthman1@gmail.com",
            "email_normalized": "homamothman1@gmail.com",
            "email_verified_at": website_auth._now(),
            "identity_status": "not_submitted",
        }
    )

    assert account["is_owner"] is True
    assert account["capabilities"]["owner_dashboard"] is True


@pytest.mark.asyncio
async def test_require_website_owner_rejects_non_owner(monkeypatch):
    async def verified(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    monkeypatch.setattr(website_auth, "require_website_email_verified", verified)
    monkeypatch.setattr(website_auth.settings, "website_owner_email", "homamothman1@gmail.com", raising=False)

    with pytest.raises(web.HTTPForbidden):
        await website_auth.require_website_owner(make_mocked_request("GET", "/api/v1/owner/dashboard"))


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(monkeypatch):
    async def duplicate(_doc):
        raise DuplicateKeyError("duplicate")

    monkeypatch.setattr(website_auth, "create_website_account", duplicate)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))
    monkeypatch.setattr(website_auth, "allocate_website_customer_id", lambda: __import__("asyncio").sleep(0, result=900000000001))

    with pytest.raises(web.HTTPConflict):
        await website_auth.register(
            json_request("POST", "/api/v1/auth/register", {"email": "USER@example.com", "password": "secure-password"})
        )


@pytest.mark.asyncio
async def test_auth_handlers_return_400_for_bad_json_and_email():
    bad_json = await website_auth.login(raw_request("POST", "/api/v1/auth/login", "{bad-json"))
    bad_email = await website_auth.register(
        json_request("POST", "/api/v1/auth/register", {"email": "bad", "password": "secure-password"})
    )

    assert bad_json.status == 400
    assert bad_email.status == 400


@pytest.mark.asyncio
async def test_rate_limit_rejects_excess_attempts(monkeypatch):
    async def denied(*_args, **_kwargs):
        return False

    monkeypatch.setattr(website_auth, "consume_website_auth_rate_limit", denied)

    with pytest.raises(web.HTTPTooManyRequests):
        await website_auth._enforce_rate_limit(
            json_request("POST", "/api/v1/auth/login"),
            bucket="login",
            discriminator="user@example.com",
            limit=10,
        )


@pytest.mark.asyncio
async def test_rate_limit_storage_failure_does_not_break_auth(monkeypatch):
    async def broken(*_args, **_kwargs):
        raise RuntimeError("rate store down")

    monkeypatch.setattr(website_auth, "consume_website_auth_rate_limit", broken)

    await website_auth._enforce_rate_limit(
        json_request("POST", "/api/v1/auth/login"),
        bucket="login",
        discriminator="user@example.com",
        limit=10,
    )


@pytest.mark.asyncio
async def test_login_issues_cookie_session_for_mongo_account(monkeypatch):
    password = "secure-password"
    salt, password_hash = website_auth._password_hash(password)
    account_id = ObjectId()
    sessions = []

    async def account(_email):
        return {
            "_id": account_id,
            "customer_id": 900000000001,
            "email": "user@example.com",
            "email_normalized": "user@example.com",
            "password_salt": salt,
            "password_hash": password_hash,
            "status": "active",
            "email_verified_at": website_auth._now(),
        }

    async def create_session(doc):
        sessions.append(doc)

    monkeypatch.setattr(website_auth, "find_website_account_by_email", account)
    monkeypatch.setattr(website_auth, "create_website_session", create_session)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))

    response = await website_auth.login(
        json_request("POST", "/api/v1/auth/login", {"email": "USER@example.com", "password": password})
    )

    assert response.status == 200
    assert sessions and sessions[0]["account_id"] == str(account_id)
    assert "phantom_session" in response.cookies
    assert "phantom_csrf" in response.cookies


@pytest.mark.asyncio
async def test_issue_session_retries_token_hash_collision(monkeypatch):
    calls = 0

    async def create_session(_doc):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise DuplicateKeyError("duplicate token")

    monkeypatch.setattr(website_auth, "create_website_session", create_session)

    token = await website_auth._issue_session({"_id": ObjectId()})

    assert token
    assert calls == 2


@pytest.mark.asyncio
async def test_cookie_session_requires_csrf_for_mutation(monkeypatch):
    async def session(_token_hash, *, now):
        return {"account_id": "account-1"}

    async def account(_account_id):
        return {"_id": "account-1", "email": "user@example.com", "status": "active"}

    monkeypatch.setattr(website_auth, "find_website_session", session)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    request = make_mocked_request(
        "POST",
        "/api/v1/auth/logout",
        headers={"Cookie": "phantom_session=session-token; phantom_csrf=csrf-token"},
    )

    with pytest.raises(web.HTTPForbidden):
        await website_auth.require_website_auth(request)


@pytest.mark.asyncio
async def test_cookie_session_accepts_matching_csrf(monkeypatch):
    async def session(_token_hash, *, now):
        return {"account_id": "account-1"}

    async def account(_account_id):
        return {"_id": "account-1", "email": "user@example.com", "status": "active"}

    monkeypatch.setattr(website_auth, "find_website_session", session)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    request = make_mocked_request(
        "POST",
        "/api/v1/auth/logout",
        headers={
            "Cookie": "phantom_session=session-token; phantom_csrf=csrf-token",
            "X-CSRF-Token": "csrf-token",
        },
    )

    auth = await website_auth.require_website_auth(request)

    assert auth.account_id == "account-1"


@pytest.mark.asyncio
async def test_send_email_code_stores_token_and_uses_resend_provider(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def account(_account_id):
        return {"_id": "account-1", "email": "user@example.com", "customer_id": 900000000001, "status": "active"}

    stored = {}

    async def create(doc):
        stored.update(doc)

    async def deliver(*, email, code):
        stored["delivered_email"] = email
        stored["delivered_code"] = code
        return {"provider": "resend", "status": "sent"}

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))
    monkeypatch.setattr(website_auth, "create_email_verification_token", create)
    monkeypatch.setattr(website_auth, "_deliver_email_verification_code", deliver)
    monkeypatch.setattr(website_auth, "_generate_email_code", lambda: "123456")

    response = await website_auth.send_email_code(json_request("POST", "/api/v1/auth/email/send-code"))
    body = json.loads(response.text)

    assert body["provider"] == "resend"
    assert body["status"] == "sent"
    assert stored["account_id"] == "account-1"
    assert stored["delivered_email"] == "user@example.com"
    assert stored["delivered_code"] == "123456"


@pytest.mark.asyncio
async def test_verify_email_code_marks_account_verified(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def consume(account_id, code_hash, *, now):
        assert account_id == "account-1"
        assert code_hash == website_auth._email_code_hash("account-1", "123456")
        return {"account_id": account_id}

    async def mark(account_id, *, now):
        return {
            "_id": account_id,
            "customer_id": 900000000001,
            "email": "user@example.com",
            "status": "active",
            "email_verified_at": now,
        }

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))
    monkeypatch.setattr(website_auth, "consume_email_verification_token", consume)
    monkeypatch.setattr(website_auth, "mark_website_email_verified", mark)

    response = await website_auth.verify_email_code(
        json_request("POST", "/api/v1/auth/email/verify", {"code": "123456"})
    )
    body = json.loads(response.text)

    assert body["account"]["email_verified"] is True
    assert body["account"]["capabilities"]["buy_services"] is True


@pytest.mark.asyncio
async def test_email_and_identity_handlers_reject_bad_json_without_server_error(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def account(_account_id):
        return {"_id": "account-1", "email": "user@example.com", "status": "active", "identity_status": "not_submitted"}

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "_enforce_rate_limit", lambda *_args, **_kwargs: __import__("asyncio").sleep(0))
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)

    verify_response = await website_auth.verify_email_code(
        raw_request("POST", "/api/v1/auth/email/verify", "{bad-json")
    )
    identity_response = await website_auth.submit_identity(
        raw_request("POST", "/api/v1/auth/identity", "{bad-json")
    )

    assert verify_response.status == 400
    assert json.loads(verify_response.text)["message"] == "invalid json body"
    assert identity_response.status == 400
    assert json.loads(identity_response.text)["message"] == "invalid json body"


@pytest.mark.asyncio
async def test_require_website_purchase_ready_rejects_unverified_cookie_account(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def account(_account_id):
        return {"_id": "account-1", "email": "user@example.com", "status": "active"}

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    request = make_mocked_request("POST", "/api/v1/digital/orders", headers={"Cookie": "phantom_session=session-token"})

    with pytest.raises(web.HTTPForbidden):
        await website_auth.require_website_purchase_ready(request)


@pytest.mark.asyncio
async def test_require_website_purchase_ready_allows_verified_cookie_account(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    async def account(_account_id):
        return {"_id": "account-1", "email_verified_at": website_auth._now(), "status": "active"}

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "find_website_account_by_id", account)
    request = make_mocked_request("POST", "/api/v1/digital/orders", headers={"Cookie": "phantom_session=session-token"})

    await website_auth.require_website_purchase_ready(request)


@pytest.mark.asyncio
async def test_consume_telegram_link_rejects_reused_token(monkeypatch):
    async def missing(_token_hash, *, now):
        return None

    monkeypatch.setattr(website_auth, "consume_telegram_link_token", missing)

    result = await website_auth.consume_telegram_link("link_" + ("a" * 32), telegram_id=123)

    assert result == {"ok": False, "reason": "expired_or_used"}


@pytest.mark.asyncio
async def test_consume_telegram_link_prevents_duplicate_telegram(monkeypatch):
    async def found(_token_hash, *, now):
        return {"account_id": "account-1"}

    async def duplicate(_account_id, _telegram_id, *, now):
        raise DuplicateKeyError("duplicate telegram")

    monkeypatch.setattr(website_auth, "consume_telegram_link_token", found)
    monkeypatch.setattr(website_auth, "link_telegram_account", duplicate)

    result = await website_auth.consume_telegram_link("link_" + ("b" * 32), telegram_id=123)

    assert result == {"ok": False, "reason": "telegram_already_linked"}


@pytest.mark.asyncio
async def test_create_link_returns_main_bot_deep_link(monkeypatch):
    async def auth(_request):
        return website_auth.WebsiteAuthContext(
            account_id="account-1",
            customer_id=900000000001,
            email="user@example.com",
            telegram_id=None,
            session_token_hash="hash",
        )

    stored = {}

    async def create(doc):
        stored.update(doc)

    monkeypatch.setattr(website_auth, "require_website_auth", auth)
    monkeypatch.setattr(website_auth, "create_telegram_link_token", create)
    monkeypatch.setattr(website_auth.settings, "main_bot_username", "@PhantomMainBot", raising=False)
    monkeypatch.setattr(website_auth.secrets, "token_hex", lambda _n: "c" * 32)

    response = await website_auth.create_link(json_request("POST", "/api/v1/auth/telegram/link"))
    body = json.loads(response.text)

    assert body["telegram_url"] == f"https://t.me/PhantomMainBot?start=link_{'c' * 32}"
    assert stored["account_id"] == "account-1"
    assert stored["used_at"] is None
