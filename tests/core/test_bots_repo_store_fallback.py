import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

import database.bots_repo as bots_repo


@pytest.mark.asyncio
async def test_get_reseller_id_for_configured_digital_bot_falls_back_to_owner(monkeypatch):
    async def fake_get_bot_by_id(_bot_id):
        return None

    monkeypatch.setattr(bots_repo, "get_bot_by_id", fake_get_bot_by_id)
    monkeypatch.setattr(
        bots_repo,
        "settings",
        SimpleNamespace(
            owner_id=7417429062,
            bot_digital_products_token="8212446189:token",
            bot_card_ex_token="8602099671:token",
        ),
    )

    reseller_id = await bots_repo.get_reseller_id_for_bot(8212446189)
    assert reseller_id == 7417429062


@pytest.mark.asyncio
async def test_get_reseller_id_for_configured_card_bot_falls_back_to_owner(monkeypatch):
    async def fake_get_bot_by_id(_bot_id):
        return None

    monkeypatch.setattr(bots_repo, "get_bot_by_id", fake_get_bot_by_id)
    monkeypatch.setattr(
        bots_repo,
        "settings",
        SimpleNamespace(
            owner_id=7417429062,
            bot_digital_products_token="8212446189:token",
            bot_card_ex_token="8602099671:token",
        ),
    )

    reseller_id = await bots_repo.get_reseller_id_for_bot(8602099671)
    assert reseller_id == 7417429062
