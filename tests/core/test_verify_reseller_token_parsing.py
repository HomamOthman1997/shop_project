import os
import sys

sys.path.insert(0, os.getcwd())

import handlers.verify_reseller as vr


def test_extract_token_input_accepts_wrapped_botfather_payload():
    raw = "Use this token:\n<1234567890：AAExample_token-value_1234567890>\nKeep it safe."
    assert vr._extract_token_input(raw) == "1234567890:AAExample_token-value_1234567890"
