from services import landing_page


def test_landing_page_exposes_public_website_navigation():
    html = landing_page.landing_page_html()

    assert 'src="/auth/static/i18n.js"' in html
    assert 'href="/login"' in html
    assert 'href="/register"' in html
    assert 'href="/catalog"' in html
    assert 'href="/catalog/games"' in html
    assert 'href="/catalog/chat-apps"' in html
    assert 'href="/catalog/subscriptions"' in html
    assert 'href="/catalog/verification-numbers"' in html
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
    assert 'href="/catalog/subscriptions"' in html
    assert 'href="/catalog/verification-numbers"' in html
    assert "PUBG Mobile UC" not in html
    assert 'href="/login"' in html
    assert 'href="/register"' in html


def test_catalog_search_script_filters_public_content():
    html = landing_page.catalog_page_html()

    assert 'input.addEventListener("input", applySearch)' in html
    assert 'params.get("q")' in html
    assert 'node.hidden = !isVisible' in html
    assert 'لا توجد نتائج مطابقة' in html


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
