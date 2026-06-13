import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services import landing_page


@pytest.mark.asyncio
async def test_landing_page_redirects_authenticated_user_to_account_home(monkeypatch):
    async def authenticated(_request):
        return object()

    monkeypatch.setattr(landing_page, "require_website_auth", authenticated)

    with pytest.raises(web.HTTPFound) as exc:
        await landing_page.landing_page(make_mocked_request("GET", "/"))

    assert exc.value.location == "/app"


@pytest.mark.asyncio
async def test_landing_page_stays_public_without_valid_session(monkeypatch):
    async def anonymous(_request):
        raise web.HTTPUnauthorized(text="missing session")

    monkeypatch.setattr(landing_page, "require_website_auth", anonymous)

    response = await landing_page.landing_page(make_mocked_request("GET", "/"))

    assert response.status == 200
    assert "Phantom Services" in response.text


def test_landing_page_exposes_public_website_navigation():
    html = landing_page.landing_page_html()

    assert 'src="/auth/static/i18n.js"' in html
    assert 'href="/login"' in html
    assert 'href="/register"' in html
    assert 'id="catalog-search"' in html
    assert "<h1>Phantom Services</h1>" in html
    assert 'href="/catalog/games"' in html
    assert 'href="/catalog/chat-apps"' in html
    assert 'href="/catalog/social-services"' in html
    assert 'href="/catalog/subscriptions"' in html
    assert 'href="/catalog/store-cards"' in html
    assert 'href="/catalog/verification-numbers"' in html
    assert 'href="/catalog/internet-providers"' in html
    assert 'href="/catalog/paid-apps"' in html
    assert 'href="/catalog/mobile-recharge"' in html
    assert 'href="/catalog/esim"' in html
    assert 'class="catalog-nav"' in html
    assert 'class="service-grid"' not in html
    assert 'class="side-nav"' not in html
    assert 'class="sidebar"' not in html
    assert 'class="hero-card"' not in html
    assert 'class="buy-note"' not in html
    assert 'class="rate-strip"' not in html
    assert "سعر صرف تقريبي" not in html
    assert "يمكنك تصفح التصنيفات" not in html
    assert "<h1>كتالوغ Phantom</h1>" not in html
    assert '<a href="/catalog">الكتالوغ</a>' not in html
    assert 'href="/mini/numbers"' not in html
    assert 'href="/mini/digital"' not in html
    assert 'class="eyebrow"' not in html
    assert "إنشاء حساب" in html


def test_landing_page_keeps_public_entry_focused_on_services():
    html = landing_page.landing_page_html()
    catalog_html = landing_page.catalog_page_html()

    assert html == catalog_html
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
    assert "رجوع إلى الأقسام" not in html
    assert 'href="/catalog/games"' in html
    assert 'href="/catalog/chat-apps"' in html
    assert 'href="/catalog/social-services"' in html
    assert 'href="/catalog/subscriptions"' in html
    assert 'href="/catalog/store-cards"' in html
    assert 'href="/catalog/verification-numbers"' in html
    assert 'href="/catalog/internet-providers"' in html
    assert 'href="/catalog/paid-apps"' in html
    assert 'href="/catalog/numbers"' not in html
    assert 'href="/catalog/digital/' not in html
    assert 'class="catalog-card green" href="/catalog/games" data-catalog-search=' in html
    assert html.count("data-preserve-catalog-query") >= 10
    assert "PUBG Mobile UC" not in html
    assert 'href="/login"' in html
    assert 'href="/register"' in html


def test_catalog_search_script_filters_public_content():
    html = landing_page.catalog_page_html()

    assert 'input.addEventListener("input", applySearch)' in html
    assert 'params.get("q")' in html
    assert 'node.hidden = !isVisible' in html
    assert 'node.hasAttribute("data-root-search-result")' in html
    assert 'encodeURIComponent(input.value.trim())' in html
    assert 'data-preserve-catalog-query' in html
    assert 'const syncQueryLinks = (query) =>' in html
    assert 'params.set("q", query)' in html
    assert 'لا توجد نتائج مطابقة' in html


def test_catalog_root_search_indexes_miniapp_families_without_showing_them_by_default():
    html = landing_page.catalog_page_html()

    assert 'data-root-search-result data-preserve-catalog-query hidden' in html
    assert 'class="catalog-card green root-search-card" href="/catalog/games/jawaker"' in html
    assert 'href="/catalog/games/jawaker" data-catalog-search=' in html
    assert 'href="/catalog/verification-numbers/telegram_numbers" data-catalog-search=' in html
    assert 'data-root-search-result data-preserve-catalog-query hidden' in html
    assert '<small class="catalog-section-kicker">ضمن الألعاب</small>' in html
    assert '<small class="catalog-section-kicker">ضمن أرقام تأكيد</small>' in html
    assert "جواكر" in html
    assert "ببجي" in html
    assert "ارقام تلجرام" in html
    assert 'const rootOnly = node.hasAttribute("data-root-search-result");' in html
    assert 'rootOnly ? Boolean(query) && haystack.includes(query)' in html


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
    assert 'href="/catalog/games/pubg"' in html
    assert 'href="/catalog/games/free_fire"' in html
    assert 'href="/catalog/games/games"' not in html
    assert 'href="/catalog/games/cards"' not in html
    assert "بطاقات الألعاب" not in html
    assert "شحن ألعاب الموبايل" not in html
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
    assert 'href="/catalog/social-services/tiktok_services"' in social
    assert 'href="/catalog/social-services/instagram_services"' in social
    assert 'href="/catalog/social-services/messaging"' not in social

    cards = landing_page.catalog_page_html("store-cards")
    assert 'href="/catalog/store-cards/steam"' in cards
    assert 'href="/catalog/store-cards/playstation"' in cards
    assert 'href="/catalog/store-cards/google_play"' in cards
    assert 'href="/catalog/store-cards/mobile-stores"' not in cards
    assert 'href="/catalog/store-cards/platform-stores"' not in cards
    assert 'href="/catalog/store-cards/payment-cards"' not in cards
    assert 'href="/catalog/store-cards/gaming-stores"' not in cards
    assert "Roblox" not in cards
    assert "Discord و IMO" not in cards

    apps = landing_page.catalog_page_html("paid-apps", category_slug="dft_pro")
    assert "DFT Pro" in apps
    assert 'href="/catalog/paid-apps/mobile-tools"' not in landing_page.catalog_page_html("paid-apps")


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
    assert 'href="/catalog/mobile-recharge/esim"' not in recharge
    assert 'href="/catalog/mobile-recharge/ukraine"' not in recharge
    assert 'href="/catalog/mobile-recharge/global"' not in recharge


def test_esim_is_a_separate_disabled_section_until_api_is_enabled():
    root = landing_page.catalog_page_html()
    esim = landing_page.catalog_page_html("esim")
    payload = landing_page.public_catalog_payload()
    sections = {row["slug"]: row for row in payload["sections"]}

    assert 'href="/catalog/esim"' in root
    assert "قريباً - API غير مفعّل" in root
    assert "<h1>eSIM</h1>" in esim
    assert "الخدمة غير مفعّلة حالياً" in esim
    assert "سيتم فتح الباقات والشراء بعد تفعيل وربط الـ API." in esim
    assert "/login?next=/app/digital" not in esim
    assert sections["esim"]["enabled"] is False
    assert sections["esim"]["categories_count"] == 0
    assert sections["mobile-recharge"]["enabled"] is True
    assert all(row["slug"] != "esim" for row in sections["mobile-recharge"]["categories"])


def test_public_catalog_payload_exposes_nested_sections_for_customer_app():
    payload = landing_page.public_catalog_payload()
    sections = {row["slug"]: row for row in payload["sections"]}

    assert sections["games"]["service"] == "digital"
    assert sections["verification-numbers"]["service"] == "numbers"
    assert sections["games"]["categories_count"] > 100
    jawaker = next(row for row in sections["games"]["categories"] if row["slug"] == "jawaker")
    assert jawaker["service_key"] == "games"
    assert jawaker["family_key"] == "jawaker"
    assert any(row["slug"] == "telegram_numbers" for row in sections["verification-numbers"]["categories"])
    store_slugs = {row["slug"] for row in sections["store-cards"]["categories"]}
    assert {"steam", "playstation", "google_play"} <= store_slugs
    assert not {"mobile-stores", "platform-stores", "payment-cards"} & store_slugs


def test_manual_catalog_categories_merge_into_existing_section():
    payload = landing_page.merge_manual_catalog(
        landing_page.public_catalog_payload(),
        [
            {
                "slug": "mobile-recharge",
                "title": "شحن الرصيد",
                "categories": [
                    {
                        "slug": "manual-family-1",
                        "title": "شحن أوكرانيا",
                        "service_key": "website_manual",
                        "family_key": "family-1",
                    }
                ],
            }
        ],
    )
    sections = {row["slug"]: row for row in payload["sections"]}

    manual = next(row for row in sections["mobile-recharge"]["categories"] if row["slug"] == "manual-family-1")
    assert manual["service_key"] == "website_manual"
    assert sections["mobile-recharge"]["categories_count"] == len(sections["mobile-recharge"]["categories"])


def test_manual_catalog_updates_existing_static_category_metadata():
    base = landing_page.public_catalog_payload()
    base_games_count = next(row for row in base["sections"] if row["slug"] == "games")["categories_count"]

    payload = landing_page.merge_manual_catalog(
        base,
        [
            {
                "slug": "games",
                "node_id": "section-games",
                "title": "Games Edited",
                "subtitle": "Managed website games",
                "categories": [
                    {
                        "slug": "pubg",
                        "node_id": "family-pubg",
                        "title": "PUBG",
                        "manual": True,
                        "service_key": "games",
                        "family_key": "pubg",
                    }
                ],
            }
        ],
    )
    games = next(row for row in payload["sections"] if row["slug"] == "games")
    pubg = next(row for row in games["categories"] if row["slug"] == "pubg")

    assert games["categories_count"] == base_games_count
    assert games["node_id"] == "section-games"
    assert games["title"] == "Games Edited"
    assert games["subtitle"] == "Managed website games"
    assert pubg["node_id"] == "family-pubg"
    assert pubg["manual"] is True


def test_manual_catalog_hidden_category_removes_static_category():
    payload = landing_page.merge_manual_catalog(
        landing_page.public_catalog_payload(),
        [
            {
                "slug": "games",
                "categories": [
                    {
                        "slug": "pubg",
                        "service_key": "games",
                        "family_key": "pubg",
                        "hidden": True,
                    }
                ],
            }
        ],
    )
    games = next(row for row in payload["sections"] if row["slug"] == "games")

    assert all(row["slug"] != "pubg" for row in games["categories"])
    assert games["categories_count"] == len(games["categories"])


def test_family_backed_catalog_sections_only_expose_direct_product_families():
    sections = {row["slug"]: row for row in landing_page.public_catalog_payload()["sections"]}

    for slug in (
        "games",
        "chat-apps",
        "social-services",
        "subscriptions",
        "store-cards",
        "verification-numbers",
        "internet-providers",
        "paid-apps",
        "mobile-recharge",
    ):
        assert sections[slug]["categories"]
        assert all(row["generated"] for row in sections[slug]["categories"])
        assert all(row["service_key"] and row["family_key"] for row in sections[slug]["categories"])


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
    html = landing_page.catalog_page_html("games", category_slug="pubg")

    assert "<h1>PUBG</h1>" in html
    assert "اختر المنتج أو الخدمة" in html
    assert 'class="category-tabs"' in html
    assert 'href="/catalog/games" data-preserve-catalog-query>الألعاب</a>' in html
    assert "<span>PUBG</span>" in html
    assert "رجوع إلى الأصناف" in html
    assert "باقات وخدمات PUBG" in html
    assert "Adobe" not in html
    assert 'class="category-tab active" href="/catalog/games/pubg" data-preserve-catalog-query' in html


def test_catalog_checkout_links_open_the_right_authenticated_workspace():
    games = landing_page.catalog_page_html("games", category_slug="pubg")
    numbers = landing_page.catalog_page_html("verification-numbers", category_slug="telegram_numbers")

    assert "/app/services" not in games
    assert "/app/services" not in numbers
    assert 'href="/login?next=/app/digital"' in games
    assert 'href="/register?next=/app/digital"' in games
    assert 'href="/login?next=/app/numbers"' in numbers
    assert 'href="/register?next=/app/numbers"' in numbers
