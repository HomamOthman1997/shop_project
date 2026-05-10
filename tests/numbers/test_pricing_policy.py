from config import settings
from services.numbers.pricing_policy import temp_sale_price


def test_temp_sale_price_uses_configured_floor(monkeypatch):
    monkeypatch.setattr(
        settings,
        "numbers_temp_price_floors_json",
        '{"whatsapp":{"US":2.25}}',
        raising=False,
    )

    assert temp_sale_price(
        service_key="whatsapp",
        base_price=0.5,
        markup_percent=0.0,
        requested_country="1",
        provider_country_iso="US",
    ) == 2.25


def test_temp_sale_price_ignores_bad_floor_config(monkeypatch):
    monkeypatch.setattr(settings, "numbers_temp_price_floors_json", "not-json", raising=False)

    assert temp_sale_price(
        service_key="telegram",
        base_price=0.5,
        markup_percent=0.0,
        requested_country="1",
        provider_country_iso="US",
    ) == 0.9
