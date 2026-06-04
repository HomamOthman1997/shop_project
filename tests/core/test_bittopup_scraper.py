import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.digital_products.bittopup_index import bittopup_indexed_urls
from services.digital_products.bittopup_scraper import parse_bittopup_product_page, parse_bittopup_sitemap, scrape_bittopup_offers


def test_parse_bittopup_sitemap_reads_public_product_urls_only():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://bittopup.com/</loc></url>
      <url><loc>https://bittopup.com/pubg-mobile-uc/</loc></url>
      <url><loc>https://bittopup.com/goods/Free-Fire-Diamonds-EU-+-TR</loc></url>
      <url><loc>https://bittopup.com/article/foo/</loc></url>
      <url><loc>https://bittopup.com/apple-gift-card-us/</loc></url>
    </urlset>
    """

    assert parse_bittopup_sitemap(xml) == [
        "https://bittopup.com/pubg-mobile-uc/",
        "https://bittopup.com/goods/Free-Fire-Diamonds-EU-+-TR",
        "https://bittopup.com/apple-gift-card-us/",
    ]


def test_bittopup_index_contains_operator_selected_pages_only():
    urls = bittopup_indexed_urls()

    assert len(urls) == 28
    assert "https://bittopup.com/goods/soulchill" in urls
    assert "https://bittopup.com/goods/pubg-uc" in urls
    assert "https://bittopup.com/goods/PlayStation-Network-Card-US" not in urls


def test_parse_bittopup_product_page_extracts_manual_provider_offers():
    html = """
    <html>
      <head><title>Buy PUBG Mobile UC - BitTopup</title></head>
      <body>
        <h1>PUBG Mobile UC</h1>
        <h3>60 UC</h3>
        <span>USD 0.90</span>
        <h3>300 + 25 UC</h3>
        <span>USD 4.73</span>
      </body>
    </html>
    """

    offers = parse_bittopup_product_page(html, url="https://bittopup.com/pubg-mobile-uc/")

    assert len(offers) == 2
    assert offers[0].source_ref == "pubg-mobile-uc#60-uc"
    assert offers[0].price_usd == 0.9
    assert offers[0].compare_key == "pubg:global:60:uc"
    assert offers[0].parse_confidence >= 0.8
    assert offers[1].compare_key == "pubg:global:300:uc"


def test_parse_bittopup_product_page_maps_free_fire_diamonds():
    html = """
    <html>
      <head><title>Free Fire Diamonds EU TR Recharge</title></head>
      <body>
        <h1>Free Fire Diamonds EU + TR</h1>
        <h3>1080+270 Diamonds EU + TR</h3>
        <span>USD 10.345</span>
      </body>
    </html>
    """

    offers = parse_bittopup_product_page(html, url="https://bittopup.com/goods/Free-Fire-Diamonds-EU-+-TR")

    assert offers
    assert offers[0].compare_key == "free_fire:eu:1080:diamond"


def test_parse_bittopup_product_page_uses_catalog_card_compare_keys():
    html = """
    <html>
      <head><title>PlayStation Network Card (US) Recharge</title></head>
      <body>
        <h1>PlayStation Network Card (US)</h1>
        <h3>10 USD</h3>
        <span>USD 10.40</span>
      </body>
    </html>
    """

    offers = parse_bittopup_product_page(html, url="https://bittopup.com/goods/PlayStation-Network-Card-US")

    assert offers
    assert offers[0].compare_key == "playstation:usa:10:usd"


def test_parse_bittopup_product_page_keeps_global_card_region():
    html = """
    <html>
      <head><title>Steam Wallet Code Global Recharge</title></head>
      <body>
        <h1>Steam Wallet Code Global</h1>
        <h3>10 USD</h3>
        <span>USD 9.80</span>
      </body>
    </html>
    """

    offers = parse_bittopup_product_page(html, url="https://bittopup.com/goods/Steam-Wallet-Code-Global")

    assert offers
    assert offers[0].compare_key == "steam:global:10:usd"


def test_parse_bittopup_product_page_uses_internal_index_metadata():
    html = """
    <html>
      <head><title>Nimo TV Diamonds</title></head>
      <body>
        <h1>Nimo TV Diamonds</h1>
        <h3>100 Diamonds</h3>
        <span>USD 1.00</span>
      </body>
    </html>
    """

    offers = parse_bittopup_product_page(html, url="https://bittopup.com/goods/Nimo-TV-Diamonds")

    assert offers
    assert offers[0].compare_key == "nimo_tv:global:100:diamond"


def test_parse_bittopup_product_page_maps_chat_app_units():
    html = """
    <html>
      <head><title>Soul Chill</title></head>
      <body>
        <h1>Soul Chill</h1>
        <h3>1000 crystals</h3>
        <span>USD 1.90</span>
      </body>
    </html>
    """

    offers = parse_bittopup_product_page(html, url="https://bittopup.com/goods/soulchill")

    assert offers
    assert offers[0].compare_key == "soul_chill:global:1000:crystal"
    assert offers[0].parse_confidence >= 0.8


@pytest.mark.asyncio
async def test_scrape_bittopup_offers_uses_internal_index(monkeypatch):
    from services.digital_products import bittopup_scraper

    async def fake_fetch(url, *, timeout_sec=25.0):
        if url.endswith("goods-sitemap.xml"):
            return """<?xml version="1.0" encoding="UTF-8"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://bittopup.com/goods/pubg-uc</loc></url>
              <url><loc>https://bittopup.com/goods/soulchill</loc></url>
              <url><loc>https://bittopup.com/goods/PlayStation-Network-Card-US</loc></url>
            </urlset>
            """
        if url.endswith("/soulchill"):
            return "<html><h1>Soul Chill</h1><h3>1000 crystals</h3><span>USD 1.90</span></html>"
        if url.endswith("/pubg-uc"):
            return "<html><h1>PUBG Mobile UC</h1><h3>60 UC</h3><span>USD 0.99</span></html>"
        raise AssertionError(f"unexpected fetch {url}")

    monkeypatch.setattr(bittopup_scraper, "_fetch_text", fake_fetch)

    offers, stats, errors = await scrape_bittopup_offers()

    assert errors == []
    assert stats["pages_checked"] == 2
    assert [offer.source_url for offer in offers] == [
        "https://bittopup.com/goods/pubg-uc",
        "https://bittopup.com/goods/soulchill",
    ]
    assert offers[1].compare_key == "soul_chill:global:1000:crystal"


def test_bittopup_scan_result_text_is_operator_readable():
    from handlers.admin_services import _bittopup_scan_result_text

    text = _bittopup_scan_result_text(
        {
            "status": "success",
            "pages_checked": 12,
            "offers_seen": 44,
            "active": 30,
            "under_review": 3,
            "unmapped": 10,
            "disabled": 1,
            "errors": 0,
        }
    )

    assert "BitTopup scan finished" in text
    assert "Pages checked: 12" in text
    assert "Under review: 3" in text
    assert "Errors: 0" in text


def test_bittopup_scan_result_text_explains_skipped_scan():
    from handlers.admin_services import _bittopup_scan_result_text

    text = _bittopup_scan_result_text({"status": "skipped", "reason": "already_running"})

    assert "scan skipped" in text
    assert "already running" in text


@pytest.mark.asyncio
async def test_bittopup_price_watch_skips_when_already_running(monkeypatch):
    import asyncio
    from services.digital_products import bittopup_scraper

    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_unlocked(*, max_pages=None):
        started.set()
        await release.wait()
        return {"provider": "bittopup", "status": "success", "errors": 0}

    monkeypatch.setattr(bittopup_scraper, "_run_bittopup_price_watch_unlocked", fake_unlocked)
    first = asyncio.create_task(bittopup_scraper.run_bittopup_price_watch())
    await started.wait()

    second = await bittopup_scraper.run_bittopup_price_watch()
    release.set()
    await first

    assert second["status"] == "skipped"
    assert second["reason"] == "already_running"
