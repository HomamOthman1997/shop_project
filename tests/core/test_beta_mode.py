import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from keyboards.main_menu_kb import main_menu
from services.proxies import manager as proxy_manager
from services.numbers import manager as numbers_manager
import keyboards.main_menu_kb as main_menu_kb
from utils import beta_mode


def test_main_menu_hides_create_bot_during_beta(monkeypatch):
    monkeypatch.setattr(beta_mode, "beta_mode_enabled", lambda: True)
    monkeypatch.setattr(beta_mode, "beta_disable_create_bot", lambda: True)
    monkeypatch.setattr(main_menu_kb.settings, "beta_mode_enabled", True)
    monkeypatch.setattr(main_menu_kb.settings, "beta_disable_create_bot", True)
    kb = main_menu("en")
    labels = [button.text for row in kb.keyboard for button in row]
    assert "🆕 Create Bot" not in labels


def test_proxy_markup_forces_beta_percent(monkeypatch):
    monkeypatch.setattr(proxy_manager, "beta_mode_enabled", lambda: True)
    monkeypatch.setattr(proxy_manager, "beta_proxy_markup_percent", lambda default=10.0: 10.0)
    assert proxy_manager._proxy_markup_pct() == 10.0


@pytest.mark.asyncio
async def test_numbers_markup_forces_beta_percent(monkeypatch):
    monkeypatch.setattr(numbers_manager, "beta_mode_enabled", lambda: True)
    monkeypatch.setattr(numbers_manager, "beta_numbers_markup_percent", lambda default=10.0: 10.0)
    value = await numbers_manager._effective_numbers_markup_percent()
    assert value == 10.0
