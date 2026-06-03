import os
import sys

sys.path.insert(0, os.getcwd())

from services.digital_products.bittopup_scraper import parse_bittopup_product_page, parse_bittopup_sitemap


def test_parse_bittopup_sitemap_reads_public_product_urls_only():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://bittopup.com/</loc></url>
      <url><loc>https://bittopup.com/pubg-mobile-uc/</loc></url>
      <url><loc>https://bittopup.com/article/foo/</loc></url>
      <url><loc>https://bittopup.com/apple-gift-card-us/</loc></url>
    </urlset>
    """

    assert parse_bittopup_sitemap(xml) == [
        "https://bittopup.com/pubg-mobile-uc/",
        "https://bittopup.com/apple-gift-card-us/",
    ]


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
