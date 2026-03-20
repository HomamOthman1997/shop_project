import os
import sys

sys.path.insert(0, os.getcwd())

import utils.services_keyboard as services_keyboard
from services.numbers.service_map import _merge_google_gmail


def test_merge_google_gmail_in_service_map():
    data = {
        "gmail": {
            "display_name": "Gmail",
            "providers": {"textverified": "gmail", "herosms": "go"},
            "aliases": ["gmail"],
        },
        "google": {
            "display_name": "Google",
            "providers": {"textverified": "google"},
            "aliases": ["google"],
        },
    }

    _merge_google_gmail(data)

    assert "gmail" in data
    assert "google" not in data
    assert data["gmail"]["display_name"] == "Gmail / Google"
    assert "google" in data["gmail"]["aliases"]
    assert data["gmail"]["providers"]["herosms"] == "go"


def test_merge_google_gmail_does_not_absorb_google_voice():
    data = {
        "gmail": {
            "display_name": "Gmail",
            "providers": {"textverified": "gmail"},
            "aliases": ["gmail"],
        },
        "googlevoice": {
            "display_name": "Google Voice",
            "providers": {"textverified": "googlevoice"},
            "aliases": ["googlevoice"],
        },
        "google": {
            "display_name": "Google",
            "providers": {"textverified": "google"},
            "aliases": ["google"],
        },
    }

    _merge_google_gmail(data)

    assert "gmail" in data
    assert "google" not in data
    assert "googlevoice" in data
    assert data["googlevoice"]["providers"]["textverified"] == "googlevoice"


def test_services_keyboard_collapses_google_to_gmail(monkeypatch):
    monkeypatch.setattr(services_keyboard, "load_full_services", lambda: ["gmail", "google", "telegram"])
    monkeypatch.setattr(services_keyboard, "load_top_services", lambda: ["google", "gmail", "telegram"])

    kb = services_keyboard.build_services_keyboard()
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    callbacks = [btn.callback_data for btn in buttons]
    texts = [btn.text for btn in buttons]

    assert callbacks.count("flow:service:gmail") == 1
    assert "flow:service:google" not in callbacks
    assert "Gmail / Google" in texts
