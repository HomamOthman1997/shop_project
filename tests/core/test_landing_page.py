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

    assert "اختر القسم" in html
    assert 'id="catalog-search"' in html
    assert "data-catalog-search" in html
    assert 'id="catalog-empty"' in html
    assert 'class="category-tabs"' not in html
    assert 'class="breadcrumbs"' in html
    assert "رجوع إلى الأقسام" in html
    assert 'href="/catalog/digital"' in html
    assert 'href="/catalog/numbers"' in html
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
    html = landing_page.catalog_page_html("digital")

    assert "اختر الصنف الفرعي" in html
    assert 'class="category-tabs"' not in html
    assert 'class="breadcrumbs"' in html
    assert "<span>المنتجات الرقمية</span>" in html
    assert "رجوع إلى الأقسام" in html
    assert 'href="/catalog/digital/games"' in html
    assert 'href="/catalog/digital/apps"' in html
    assert "شحن الألعاب" in html
    assert "PUBG Mobile UC" not in html


def test_catalog_category_filters_items():
    html = landing_page.catalog_page_html("digital", category_slug="games")

    assert "<h1>شحن الألعاب</h1>" in html
    assert "اختر المنتج أو الخدمة" in html
    assert 'class="category-tabs"' in html
    assert 'href="/catalog/digital">المنتجات الرقمية</a>' in html
    assert "<span>شحن الألعاب</span>" in html
    assert "رجوع إلى الأصناف" in html
    assert "PUBG Mobile UC" in html
    assert "Streaming" not in html
    assert 'class="category-tab active" href="/catalog/digital/games"' in html
