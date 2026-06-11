from services import landing_page


def test_landing_page_exposes_public_website_navigation():
    html = landing_page.landing_page_html()

    assert 'src="/auth/static/i18n.js"' in html
    assert 'href="/login"' in html
    assert 'href="/register"' in html
    assert 'class="nav-links"' in html
    assert 'href="/catalog"' in html
    assert 'href="#services"' in html
    assert 'href="#account"' in html
    assert 'href="/catalog/numbers"' in html
    assert 'href="/catalog/digital"' in html
    assert 'href="/mini/numbers"' not in html
    assert 'href="/mini/digital"' not in html
    assert 'class="eyebrow"' not in html
    assert ".quick-panel { display: none; }" in html


def test_landing_page_allows_price_browsing_but_keeps_purchase_account_gated():
    html = landing_page.landing_page_html()

    assert "استعرض الخدمات والأسعار" in html
    assert "الشراء" in html
    assert "بعد الحساب والتأكيد" in html


def test_catalog_page_uses_public_showcase_before_login():
    html = landing_page.catalog_page_html()

    assert "اختر القسم الذي تريده" in html
    assert 'class="showcase-grid"' in html
    assert 'class="category-tabs"' not in html
    assert 'href="/catalog/digital?category=games"' in html
    assert 'href="/catalog/numbers"' in html
    assert 'href="/login?next=/app/services"' in html
    assert 'href="/register?next=/catalog/digital"' in html


def test_catalog_section_shows_subcategory_tabs():
    html = landing_page.catalog_page_html("digital")

    assert 'class="category-tabs"' in html
    assert 'href="/catalog/digital?category=games"' in html
    assert 'href="/catalog/digital?category=apps"' in html
    assert "PUBG و BGMI" in html


def test_catalog_category_filters_items():
    html = landing_page.catalog_page_html("digital", category_slug="games")

    assert "<h1>شحن الألعاب</h1>" in html
    assert "PUBG Mobile UC" in html
    assert "Streaming" not in html
    assert 'class="category-tab active" href="/catalog/digital?category=games"' in html
