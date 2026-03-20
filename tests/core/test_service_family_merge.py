import os
import sys

sys.path.insert(0, os.getcwd())

import utils.services_keyboard as services_keyboard
from services.numbers.service_map import _merge_service_families


def test_merge_service_families_keeps_non_family_entries():
    data = {
        "gmail": {
            "display_name": "Gmail",
            "providers": {"smspool": "gmail"},
            "aliases": ["gmail"],
        },
        "googlevoice": {
            "display_name": "Google Voice",
            "providers": {"textverified": "google_voice"},
            "aliases": ["googlevoice"],
        },
        "evoice": {
            "display_name": "eVoice",
            "providers": {"smspool": "evoice"},
            "aliases": ["evoice"],
        },
    }

    _merge_service_families(data)

    assert "gmail" in data
    assert "googlevoice" in data
    assert "evoice" in data
    assert data["googlevoice"]["providers"]["textverified"] == "google_voice"


def test_merge_service_families_merges_company_family_variants():
    data = {
        "microsoft": {
            "display_name": "Microsoft",
            "providers": {"smspool": "microsoft"},
            "aliases": ["microsoft"],
        },
        "microsoftoutlook": {
            "display_name": "Microsoft Outlook",
            "providers": {"herosms": "ms_outlook"},
            "aliases": ["microsoftoutlook"],
        },
    }

    _merge_service_families(data)

    assert "microsoftoutlook" not in data
    assert "microsoft" in data
    assert data["microsoft"]["providers"]["herosms"] == "ms_outlook"


def test_services_keyboard_collapses_twitterx_into_twitter(monkeypatch):
    monkeypatch.setattr(services_keyboard, "load_full_services", lambda: ["twitter", "twitterx", "telegram"])
    monkeypatch.setattr(services_keyboard, "load_top_services", lambda: ["twitterx", "twitter", "telegram"])

    kb = services_keyboard.build_services_keyboard()
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    callbacks = [btn.callback_data for btn in buttons]
    texts = [btn.text for btn in buttons]

    assert callbacks.count("flow:service:twitter") == 1
    assert "flow:service:twitterx" not in callbacks
    assert "Twitter / X" in texts
