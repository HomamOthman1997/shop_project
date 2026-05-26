from services.numbers.provider_delivery import (
    order_uses_provider_sms_webhook,
    provider_sms_delivery_strategy,
    provider_sms_polling_enabled,
)


def test_polling_required_providers_are_explicit_exceptions(monkeypatch):
    from services.numbers import provider_delivery

    monkeypatch.setattr(provider_delivery.settings, "numbers_provider_sms_polling_enabled", False)

    for provider in ("pvapins", "vaksms", "smspool"):
        assert provider_sms_delivery_strategy(provider) == "polling"
        assert provider_sms_polling_enabled(provider) is True
        assert order_uses_provider_sms_webhook({"provider": provider}) is False


def test_webhook_providers_stay_blocked_when_global_polling_is_disabled(monkeypatch):
    from services.numbers import provider_delivery

    monkeypatch.setattr(provider_delivery.settings, "numbers_provider_sms_polling_enabled", False)

    assert provider_sms_delivery_strategy("textverified") == "webhook"
    assert provider_sms_polling_enabled("textverified") is False
    assert order_uses_provider_sms_webhook({"provider": "textverified"}) is True
