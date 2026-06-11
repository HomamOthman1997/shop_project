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
    assert 'href="/catalog/digital?category=games"' in html
    assert 'href="/catalog/numbers"' in html
    assert 'href="/login?next=/app/services"' in html
    assert 'href="/register?next=/catalog/digital"' in html
