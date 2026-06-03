import os
import sys

sys.path.insert(0, os.getcwd())

from services.digital_products.static_taxonomy import detect_service_key_strict


def test_chat_alias_line_does_not_match_online():
    assert detect_service_key_strict("FINAL FANTASY XIV Online") != "chat_apps"
    assert detect_service_key_strict("LINE Gift Card") == "chat_apps"
