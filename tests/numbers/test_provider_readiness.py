from services.numbers.provider_readiness import (
    provider_purchase_enabled,
    provider_quote_enabled,
    provider_readiness,
    readiness_block_payload,
)


def test_provider_readiness_override_can_enable_provider(monkeypatch):
    from services.numbers import provider_readiness as readiness_module

    monkeypatch.setattr(
        readiness_module.settings,
        "numbers_provider_readiness_overrides",
        '{"smsready":{"status":"webhook_pending","quote_enabled":true,"purchase_enabled":true,"auto_refund_enabled":true,"reason":"verified from Railway"}}',
    )

    readiness = provider_readiness("smsready")
    assert readiness.status == "webhook_pending"
    assert readiness.quote_enabled is True
    assert readiness.purchase_enabled is True
    assert readiness.auto_refund_enabled is True
    assert readiness.reason == "verified from Railway"


def test_provider_readiness_rows_include_override_only_provider(monkeypatch):
    from services.numbers import provider_readiness as readiness_module

    monkeypatch.setattr(
        readiness_module.settings,
        "numbers_provider_readiness_overrides",
        '{"newprovider":{"status":"quarantine","reason":"manual hold"}}',
    )

    rows = {row["provider"]: row for row in readiness_module.provider_readiness_rows()}
    assert rows["newprovider"]["status"] == "quarantine"
    assert rows["newprovider"]["reason"] == "manual hold"


def test_provider_readiness_enables_confirmed_polling_only_providers():
    assert provider_readiness("smspool").status == "polling_required"
    assert provider_quote_enabled("smspool", mode="temp") is True
    assert provider_purchase_enabled("vaksms", mode="temp") is True
    assert provider_readiness("pvapins").webhook_documented is False
    assert provider_readiness("pvapins").auto_refund_enabled is True


def test_provider_readiness_keeps_refund_risk_visible_but_not_auto_refundable():
    readiness = provider_readiness("nonvoip")
    assert readiness.status == "refund_risk"
    assert readiness.quote_enabled is True
    assert readiness.purchase_enabled is True
    assert readiness.auto_refund_enabled is False


def test_smsready_is_enabled_after_webhook_verification():
    readiness = provider_readiness("smsready")
    assert readiness.status == "webhook_pending"
    assert provider_quote_enabled("smsready", mode="temp") is True
    assert provider_purchase_enabled("smsready", mode="temp") is True
    assert readiness.auto_refund_enabled is True
