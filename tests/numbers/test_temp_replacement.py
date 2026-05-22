from services.numbers.shared.temp_replacement import temp_replacement_fields


def test_temp_replacement_fields_prefers_temp_values():
    fields = temp_replacement_fields(
        {
            "temp_service_key": "paypal",
            "service_id": "gmail",
            "provider": "HeroSMS",
            "provisioning_provider": "smspool",
            "temp_api_service": "pp",
            "provisioning_service": "gm",
            "temp_country": "1",
            "provisioning_country": "44",
            "temp_state": "NY",
            "provisioning_state_code": "CA",
        }
    )

    assert fields["service"] == "paypal"
    assert fields["provider"] == "herosms"
    assert fields["api_service"] == "pp"
    assert fields["raw_country"] == "1"
    assert fields["raw_state"] == "NY"
    assert fields["country"] == "1"
    assert fields["state"] == "NY"


def test_temp_replacement_fields_falls_back_to_provisioning_values_and_resets_state():
    fields = temp_replacement_fields(
        {
            "service_id": "telegram",
            "provisioning_provider": "pvadeals",
            "provisioning_service": "tg",
            "provisioning_country": "44",
            "provisioning_state_code": "TX",
        }
    )

    assert fields["service"] == "telegram"
    assert fields["provider"] == "pvadeals"
    assert fields["api_service"] == "tg"
    assert fields["raw_country"] == "44"
    assert fields["raw_state"] == "TX"
    assert fields["country"] == "44"
    assert fields["state"] == "none"
