import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

import database.bots_repo as bots_repo


@pytest.mark.asyncio
async def test_get_reseller_id_for_platform_bot_stays_none(monkeypatch):
    async def fake_get_bot_by_id(_bot_id):
        return None

    monkeypatch.setattr(bots_repo, "get_bot_by_id", fake_get_bot_by_id)
    monkeypatch.setattr(
        bots_repo,
        "settings",
        SimpleNamespace(
            owner_id=7417429062,
            bot_main_token="8147766487:token",
            bot_digital_products_token="8212446189:token",
            bot_card_ex_token="8602099671:token",
        ),
    )

    assert await bots_repo.get_reseller_id_for_bot(8212446189) is None
    assert await bots_repo.get_reseller_id_for_bot(8602099671) is None


@pytest.mark.asyncio
async def test_get_store_owner_scope_for_platform_bot_falls_back_to_owner(monkeypatch):
    async def fake_get_bot_by_id(_bot_id):
        return None

    monkeypatch.setattr(bots_repo, "get_bot_by_id", fake_get_bot_by_id)
    monkeypatch.setattr(
        bots_repo,
        "settings",
        SimpleNamespace(
            owner_id=7417429062,
            bot_main_token="8147766487:token",
            bot_digital_products_token="8212446189:token",
            bot_card_ex_token="8602099671:token",
        ),
    )

    assert await bots_repo.get_store_owner_scope_for_bot(8212446189) == 7417429062
    assert await bots_repo.get_store_owner_scope_for_bot(8602099671) == 7417429062


@pytest.mark.asyncio
async def test_get_store_owner_scope_prefers_real_reseller_ownership(monkeypatch):
    async def fake_get_bot_by_id(_bot_id):
        return {"owner_id": 555}

    monkeypatch.setattr(bots_repo, "get_bot_by_id", fake_get_bot_by_id)
    monkeypatch.setattr(
        bots_repo,
        "settings",
        SimpleNamespace(
            owner_id=7417429062,
            bot_main_token="8147766487:token",
            bot_digital_products_token="8212446189:token",
            bot_card_ex_token="8602099671:token",
        ),
    )

    assert await bots_repo.get_reseller_id_for_bot(999) == 555
    assert await bots_repo.get_store_owner_scope_for_bot(999) == 555
