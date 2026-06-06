from services.numbers.shared.provider_io import normalize_provider_sms_result


def test_normalize_provider_sms_result_wraps_string_message():
    assert normalize_provider_sms_result({"success": True, "messages": "123456", "raw": {}})["messages"] == ["123456"]


def test_normalize_provider_sms_result_handles_invalid_result():
    assert normalize_provider_sms_result("provider failure") == {
        "success": False,
        "messages": [],
        "raw": "provider failure",
    }
