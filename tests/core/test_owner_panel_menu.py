import os
import sys

sys.path.insert(0, os.getcwd())

from handlers.admin_services import _owner_panel_home_text, _owner_panel_main_kb


def test_owner_panel_main_keyboard_exposes_quick_actions():
    kb = _owner_panel_main_kb()
    callbacks = [
        btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
        if btn.callback_data
    ]

    assert "owner_panel:act:dashboard" in callbacks
    assert "owner_panel:cat:subscriptions" in callbacks
    assert "owner_panel:cat:main_bot" in callbacks
    assert "owner_panel:cat:system" in callbacks
    assert "owner_panel:act:broadcast" in callbacks
    assert "owner_panel:act:owner_payment_methods" in callbacks
    assert "owner_panel:act:reseller_topup_requests" in callbacks


def test_owner_panel_home_text_mentions_quick_actions():
    text = _owner_panel_home_text()

    assert "Choose a section or a quick action" in text
    assert "Main Bot Finance" in text
    assert "Routing & Alerts" in text
