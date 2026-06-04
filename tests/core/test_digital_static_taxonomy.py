import os
import sys

sys.path.insert(0, os.getcwd())

from services.digital_products.static_taxonomy import detect_service_key_strict, guess_family


def test_chat_alias_line_does_not_match_online():
    assert detect_service_key_strict("FINAL FANTASY XIV Online") != "chat_apps"
    assert detect_service_key_strict("LINE Gift Card") == "chat_apps"
    assert detect_service_key_strict("Telegram Stars") == "chat_apps"
    assert detect_service_key_strict("Telegram Gift") == "chat_apps"


def test_clash_coc_alias_does_not_match_cocco():
    assert guess_family("games", "Cocco", ["Cocco 800000"])[0] != "clash_of_clans"
    assert guess_family("games", "Clash of Clans", ["Gold Pass"])[0] == "clash_of_clans"
