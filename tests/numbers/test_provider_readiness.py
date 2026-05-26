from services.numbers.provider_readiness import (
    provider_purchase_enabled,
    provider_quote_enabled,
    provider_readiness,
    readiness_block_payload,
)


def test_provider_readiness_quarantines_polling_only_providers():
    assert provider_readiness("smspool").status == "quarantine"
    assert provider_quote_enabled("smspool", mode="temp") is False
    assert provider_purchase_enabled("vaksms", mode="temp") is False
    assert provider_readiness("pvapins").webhook_documented is False


def test_provider_readiness_keeps_refund_risk_visible_but_not_auto_refundable():
    readiness = provider_readiness("nonvoip")
    assert readiness.status == "refund_risk"
    assert readiness.quote_enabled is True
    assert readiness.purchase_enabled is True
    assert readiness.auto_refund_enabled is False


def test_readiness_block_payload_is_customer_safe():
    payload = readiness_block_payload("smsready", mode="temp")
    assert payload["available_for_buy"] is False
    assert payload["provider_reason"] == "provider_disabled"
    assert "api.sms-ready.com" in payload["provider_reason_message"]
