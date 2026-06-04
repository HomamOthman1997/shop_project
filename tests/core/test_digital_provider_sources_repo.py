from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from database import digital_provider_sources_repo as repo


class _FakeProviderSources:
    def __init__(self, current=None):
        self.rows = {}
        if current:
            self.rows[current["_id"]] = dict(current)

    async def find_one(self, query):
        if "_id" in query:
            return self.rows.get(query["_id"])
        return None

    async def update_one(self, query, update, upsert=False):
        key = query["_id"]
        row = dict(self.rows.get(key) or {})
        row.update(update.get("$setOnInsert") or {})
        row.update(update.get("$set") or {})
        self.rows[key] = row
        return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)


def _patch_sources(monkeypatch, current):
    collection = _FakeProviderSources(current)
    monkeypatch.setattr(repo, "db", SimpleNamespace(digital_provider_sources=collection))
    return collection


@pytest.mark.asyncio
async def test_upsert_provider_source_can_auto_approve_unreviewed_curated_source(monkeypatch):
    collection = _patch_sources(
        monkeypatch,
        {
            "_id": "bittopup:soulchill#1000-crystal",
            "provider": "bittopup",
            "source_ref": "soulchill#1000-crystal",
            "compare_key": "soul_chill:global:1000:crystal",
            "price_status": "under_review",
            "active_price": 1.0,
            "observed_price": 1.0,
        },
    )

    result = await repo.upsert_provider_source(
        provider="bittopup",
        source_ref="soulchill#1000-crystal",
        compare_key="soul_chill:global:1000:crystal",
        source_url="https://bittopup.com/goods/soulchill",
        source_product_name="Soul Chill",
        source_denomination_name="1000 Crystal",
        active_price=None,
        observed_price=4.0,
        available=True,
        fulfillment_mode="manual_topup",
        parse_confidence=0.9,
        parser_version="test",
        max_auto_change_percent=10,
        auto_approve_unreviewed=True,
    )

    saved = collection.rows["bittopup:soulchill#1000-crystal"]
    assert result["status"] == "active"
    assert saved["price_status"] == "active"
    assert saved["active_price"] == 4.0
    assert saved["review_reason"] == ""


@pytest.mark.asyncio
async def test_upsert_provider_source_keeps_approved_price_guardrail(monkeypatch):
    collection = _patch_sources(
        monkeypatch,
        {
            "_id": "bittopup:soulchill#1000-crystal",
            "provider": "bittopup",
            "source_ref": "soulchill#1000-crystal",
            "compare_key": "soul_chill:global:1000:crystal",
            "price_status": "active",
            "active_price": 1.0,
            "observed_price": 1.0,
            "approved_at": datetime(2026, 6, 4, tzinfo=UTC),
        },
    )

    result = await repo.upsert_provider_source(
        provider="bittopup",
        source_ref="soulchill#1000-crystal",
        compare_key="soul_chill:global:1000:crystal",
        source_url="https://bittopup.com/goods/soulchill",
        source_product_name="Soul Chill",
        source_denomination_name="1000 Crystal",
        active_price=None,
        observed_price=4.0,
        available=True,
        fulfillment_mode="manual_topup",
        parse_confidence=0.9,
        parser_version="test",
        max_auto_change_percent=10,
        auto_approve_unreviewed=True,
    )

    saved = collection.rows["bittopup:soulchill#1000-crystal"]
    assert result["status"] == "under_review"
    assert result["reason"] == "price_change_gt_guardrail"
    assert saved["active_price"] == 1.0
    assert saved["observed_price"] == 4.0
