import os
import sys

sys.path.insert(0, os.getcwd())

from database.owner_payment_settings_repo import _default_owner_payment_methods, render_owner_method_instructions
from handlers.reseller_recharge import _owner_topup_methods_kb


def test_default_owner_payment_methods_shape():
    methods = _default_owner_payment_methods(13500.0)
    codes = {m.get("code") for m in methods}
    assert len(methods) >= 4
    assert "owner_shamcash_syp" in codes
    assert "owner_shamcash_usd" in codes
    assert "owner_crypto_usdt" in codes


def test_render_owner_method_instructions():
    method = {
        "instructions": "Pay to {target} via {currency} at {per_credit}",
        "target": "WALLET_123",
        "currency": "USD",
        "per_credit": 1.5,
        "support": "@help",
    }
    text = render_owner_method_instructions(method)
    assert "WALLET_123" in text
    assert "USD" in text
    assert "1.5" in text


def test_owner_topup_methods_keyboard():
    kb = _owner_topup_methods_kb(
        [
            {"code": "owner_manual_usd", "title": "Manual USD"},
            {"code": "owner_crypto_usdt", "title": "USDT"},
        ]
    )
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "rs_core_topup:method:owner_manual_usd" in callbacks
    assert "rs_core_topup:method:owner_crypto_usdt" in callbacks
    assert "rs_core_topup:cancel" in callbacks


def test_main_reseller_bot_link_helper(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as core_buy

    monkeypatch.setattr(core_buy.settings, "main_bot_username", "@cyberzone_main_bot")
    assert core_buy._main_reseller_bot_link() == "https://t.me/cyberzone_main_bot"

    monkeypatch.setattr(core_buy.settings, "main_bot_username", "")
    assert core_buy._main_reseller_bot_link() is None
