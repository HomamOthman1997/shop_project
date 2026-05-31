from services import landing_page


def test_landing_page_links_to_telegram_bots(monkeypatch):
    monkeypatch.setattr(landing_page, "numbers_bot_url", lambda start=None: f"https://t.me/NumbersBot?start={start}")
    monkeypatch.setattr(landing_page, "digital_products_bot_url", lambda start=None: f"https://t.me/DigitalBot?start={start}")
    monkeypatch.setattr(landing_page, "card_ex_bot_url", lambda start=None: f"https://t.me/CardExBot?start={start}")

    html = landing_page.landing_page_html()

    assert 'href="https://t.me/NumbersBot?start=numbers"' in html
    assert 'href="https://t.me/DigitalBot?start=store"' in html
    assert 'href="https://t.me/CardExBot?start=cards"' in html
    assert 'href="/mini/numbers"' not in html
    assert 'href="/mini/digital"' not in html
    assert 'href="/mini/cardex"' not in html


def test_landing_page_keeps_local_fallback_when_bot_username_missing(monkeypatch):
    monkeypatch.setattr(landing_page, "numbers_bot_url", lambda start=None: None)
    monkeypatch.setattr(landing_page, "digital_products_bot_url", lambda start=None: None)
    monkeypatch.setattr(landing_page, "card_ex_bot_url", lambda start=None: None)

    html = landing_page.landing_page_html()

    assert 'href="/mini/numbers"' in html
    assert 'href="/mini/digital"' in html
    assert 'href="/mini/cardex"' in html
