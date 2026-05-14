import os
import sys

sys.path.insert(0, os.getcwd())

import handlers.verify_reseller as vr


def test_token_validation_rejects_manual_channel_values():
    assert vr.is_valid_token("@my_channel") is False
    assert vr.is_valid_token("my_channel") is False
    assert vr.is_valid_token("-1001234567890") is False


def test_token_validation_accepts_real_bot_token_format():
    assert vr.is_valid_token("1234567890:AAExample_token-value_1234567890") is True


def test_extract_token_input_accepts_wrapped_botfather_payload():
    raw = "Use this token:\n<1234567890：AAExample_token-value_1234567890>\nKeep it safe."
    assert vr._extract_token_input(raw) == "1234567890:AAExample_token-value_1234567890"
