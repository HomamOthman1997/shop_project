from __future__ import annotations

import pytest

from database import numbers_provider_circuit_repo as circuit


class _FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def update_one(self, query, update, upsert=False):
        key = query["_id"]
        row = self.rows.setdefault(key, {"_id": key})
        if "$setOnInsert" in update and len(row) == 1:
            row.update(update["$setOnInsert"])
        if "$set" in update:
            row.update(update["$set"])
        for field, inc in (update.get("$inc") or {}).items():
            row[field] = int(row.get(field) or 0) + int(inc)
        return None

    async def find_one(self, query):
        expires_gt = (query.get("expires_at") or {}).get("$gt")
        alternatives = query.get("$or") or []
        for row in self.rows.values():
            if expires_gt is not None and not (row.get("expires_at") and row["expires_at"] > expires_gt):
                continue
            if any(self._matches(row, alt) for alt in alternatives):
                return dict(row)
        return None

    def _matches(self, row: dict, query: dict) -> bool:
        for key, value in query.items():
            if isinstance(value, dict) and "$in" in value:
                if row.get(key) not in value["$in"]:
                    return False
                continue
            if row.get(key) != value:
                return False
        return True


class _FakeDB:
    def __init__(self) -> None:
        self.number_provider_purchase_blocks = _FakeCollection()


@pytest.mark.asyncio
async def test_telegram_failure_blocks_provider_for_service(monkeypatch):
    fake_db = _FakeDB()
    monkeypatch.setattr(circuit, "db", fake_db)

    row = await circuit.mark_number_provider_purchase_failure(
        mode="temp",
        provider_code="textverified",
        service_key="telegram",
        country="1",
        provider_country_iso="US",
        reason="country_mismatch",
    )

    assert row["scope"] == "location"
    blocked = await circuit.number_provider_purchase_blocked(
        mode="temp",
        provider_code="textverified",
        service_key="telegram",
        country="44",
        provider_country_iso="GB",
    )
    assert blocked is not None
    assert blocked["scope"] == "provider_service"


@pytest.mark.asyncio
async def test_non_telegram_failure_stays_location_scoped(monkeypatch):
    fake_db = _FakeDB()
    monkeypatch.setattr(circuit, "db", fake_db)

    await circuit.mark_number_provider_purchase_failure(
        mode="temp",
        provider_code="textverified",
        service_key="whatsapp",
        country="1",
        provider_country_iso="US",
        reason="provider_buy_failed",
    )

    blocked = await circuit.number_provider_purchase_blocked(
        mode="temp",
        provider_code="textverified",
        service_key="whatsapp",
        country="44",
        provider_country_iso="GB",
    )
    assert blocked is None
