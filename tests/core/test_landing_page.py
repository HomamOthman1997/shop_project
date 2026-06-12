from services import landing_page


def test_landing_page_exposes_public_website_navigation():
    html = landing_page.landing_page_html()

    assert 'src="/auth/static/i18n.js"' in html
    assert 'href="/login"' in html
    assert 'href="/register"' in html
    assert 'href="/catalog"' in html
    assert 'href="/catalog/games"' in html
    assert 'href="/catalog/chat-apps"' in html
    assert 'href="/catalog/social-services"' in html
    assert 'href="/catalog/subscriptions"' in html
    assert 'href="/catalog/store-cards"' in html
    assert 'href="/catalog/verification-numbers"' in html
    assert 'href="/catalog/internet-providers"' in html
    assert 'href="/catalog/paid-apps"' in html
    assert 'href="/catalog/mobile-recharge"' in html
    assert 'class="service-grid"' in html
    assert 'class="side-nav"' not in html
    assert 'class="sidebar"' not in html
    assert 'class="hero-card"' not in html
    assert 'href="/mini/numbers"' not in html
    assert 'href="/mini/digital"' not in html
    assert 'class="eyebrow"' not in html
    assert "تسجيل حساب جديد" in html


def test_landing_page_keeps_public_entry_focused_on_services():
    html = landing_page.landing_page_html()

    assert "<h2>Phantom Services</h2>" not in html
    assert "اختر القسم الذي تريده" not in html
    assert "طلباتي" not in html
    assert "شحن الرصيد" not in html
    assert "الدعم" not in html
    assert "حسابي" not in html
    assert "تأكيد الهوية" not in html


def test_catalog_page_uses_public_showcase_before_login():
    html = landing_page.catalog_page_html()

    assert "اختر القسم" in html
    assert 'id="catalog-search"' in html
    assert "data-catalog-search" in html
    assert 'id="catalog-empty"' in html
    assert 'class="category-tabs"' not in html
    assert 'class="breadcrumbs"' in html
    assert "رجوع إلى الأقسام" in html
    assert 'href="/catalog/games"' in html
    assert 'href="/catalog/chat-apps"' in html
    assert 'href="/catalog/social-services"' in html
    assert 'href="/catalog/subscriptions"' in html
    assert 'href="/catalog/store-cards"' in html
    assert 'href="/catalog/verification-numbers"' in html
    assert 'href="/catalog/internet-providers"' in html
    assert 'href="/catalog/paid-apps"' in html
    assert "PUBG Mobile UC" not in html
    assert 'href="/login"' in html
    assert 'href="/register"' in html


def test_catalog_search_script_filters_public_content():
    html = landing_page.catalog_page_html()

    assert 'input.addEventListener("input", applySearch)' in html
    assert 'params.get("q")' in html
    assert 'node.hidden = !isVisible' in html
    assert 'encodeURIComponent(input.value.trim())' in html
    assert 'لا توجد نتائج مطابقة' in html


def test_catalog_empty_search_links_to_broader_scope():
    section_html = landing_page.catalog_page_html("games")
    category_html = landing_page.catalog_page_html("games", category_slug="free_fire")
    root_html = landing_page.catalog_page_html()

    assert 'id="catalog-empty" data-broader-search="/catalog"' in section_html
    assert 'id="catalog-empty" data-broader-search="/catalog/games"' in category_html
    assert 'id="catalog-empty" data-broader-search=""' in root_html
    assert 'ابحث ضمن نطاق أوسع' in section_html


def test_catalog_section_shows_subcategory_tabs():
    html = landing_page.catalog_page_html("games")

    assert "اختر الصنف الفرعي" in html
    assert 'class="category-tabs"' not in html
    assert 'class="breadcrumbs"' in html
    assert "<span>الألعاب</span>" in html
    assert "رجوع إلى الأقسام" in html
    assert 'href="/catalog/games/games"' in html
    assert 'href="/catalog/games/cards"' in html
    assert "شحن ألعاب الموبايل" in html
    assert "PUBG Mobile UC" not in html


def test_catalog_exposes_custom_miniapp_sections_as_first_level_routes():
    html = landing_page.catalog_page_html()

    for href in (
        "/catalog/social-services",
        "/catalog/store-cards",
        "/catalog/internet-providers",
        "/catalog/paid-apps",
    ):
        assert f'href="{href}"' in html

    social = landing_page.catalog_page_html("social-services")
    assert 'href="/catalog/social-services/tiktok"' in social
    assert 'href="/catalog/social-services/instagram"' in social

    cards = landing_page.catalog_page_html("store-cards")
    assert 'href="/catalog/store-cards/mobile-stores"' in cards
    assert 'href="/catalog/store-cards/gaming-stores"' in cards

    apps = landing_page.catalog_page_html("paid-apps", category_slug="mobile-tools")
    assert "Android AMT" in apps
    assert "DFT Pro" in apps


def test_catalog_sections_include_miniapp_family_categories():
    games = landing_page.catalog_page_html("games")
    numbers = landing_page.catalog_page_html("verification-numbers")
    subscriptions = landing_page.catalog_page_html("subscriptions")
    recharge = landing_page.catalog_page_html("mobile-recharge")

    assert 'href="/catalog/games/free_fire"' in games
    assert 'href="/catalog/games/jawaker"' in games
    assert 'href="/catalog/verification-numbers/telegram_numbers"' in numbers
    assert 'href="/catalog/verification-numbers/chatgpt_numbers"' in numbers
    assert 'href="/catalog/subscriptions/chatgpt"' in subscriptions
    assert 'href="/catalog/mobile-recharge/syriatel"' in recharge


def test_catalog_generated_family_category_renders_as_product_stage():
    html = landing_page.catalog_page_html("games", category_slug="free_fire")

    assert "<h1>Free Fire</h1>" in html
    assert "باقات وخدمات Free Fire" in html
    assert 'href="/login?next=/app/digital"' in html
    assert 'href="/catalog/games/free_fire"' in html


def test_catalog_large_category_tabs_are_compact_but_keep_active_category():
    html = landing_page.catalog_page_html("games", category_slug="jawaker")

    assert html.count('class="category-tab') < 30
    assert 'class="category-tab active" href="/catalog/games/jawaker"' in html
    assert 'class="category-tab more" href="/catalog/games"' in html


def test_catalog_category_filters_items():
    html = landing_page.catalog_page_html("games", category_slug="games")

    assert "<h1>شحن ألعاب الموبايل</h1>" in html
    assert "اختر المنتج أو الخدمة" in html
    assert 'class="category-tabs"' in html
    assert 'href="/catalog/games">الألعاب</a>' in html
    assert "<span>شحن ألعاب الموبايل</span>" in html
    assert "رجوع إلى الأصناف" in html
    assert "PUBG Mobile UC" in html
    assert "Adobe" not in html
    assert 'class="category-tab active" href="/catalog/games/games"' in html


def test_catalog_checkout_links_open_the_right_authenticated_workspace():
    games = landing_page.catalog_page_html("games", category_slug="games")
    numbers = landing_page.catalog_page_html("verification-numbers", category_slug="temporary")

    assert "/app/services" not in games
    assert "/app/services" not in numbers
    assert 'href="/login?next=/app/digital"' in games
    assert 'href="/register?next=/app/digital"' in games
    assert 'href="/login?next=/app/numbers"' in numbers
    assert 'href="/register?next=/app/numbers"' in numbers
