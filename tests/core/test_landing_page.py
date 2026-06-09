from services import landing_page


def test_landing_page_exposes_public_website_navigation():
    html = landing_page.landing_page_html()

    assert 'src="/auth/static/i18n.js"' in html
    assert 'href="/login"' in html
    assert 'href="/register"' in html
    assert 'class="nav-links"' in html
    assert 'href="#services"' in html
    assert 'href="#account"' in html
    assert 'href="/app/numbers"' in html
    assert 'href="/app/digital"' in html
    assert 'href="/mini/numbers"' not in html
    assert 'href="/mini/digital"' not in html
    assert 'class="eyebrow"' not in html
    assert ".quick-panel { display: none; }" in html


def test_landing_page_allows_price_browsing_but_keeps_purchase_account_gated():
    html = landing_page.landing_page_html()

    assert "استعرض الخدمات والأسعار" in html
    assert "الشراء" in html
    assert "بعد الحساب والتأكيد" in html
