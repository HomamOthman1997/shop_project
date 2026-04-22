import os
import sys
from types import SimpleNamespace

import pytest
from pymongo import ReturnDocument

sys.path.insert(0, os.getcwd())

import database.cardex_repo as cardex_repo


class _AsyncCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def limit(self, n):
        self.rows = self.rows[: int(n)]
        return self

    def __aiter__(self):
        self._idx = 0
        return self

    async def __anext__(self):
        if self._idx >= len(self.rows):
            raise StopAsyncIteration
        row = self.rows[self._idx]
        self._idx += 1
        return dict(row)


class _FakeCollection:
    def __init__(self, rows=None, *, unique_idempotency=False):
        self.rows = [dict(row) for row in (rows or [])]
        self.unique_idempotency = unique_idempotency

    def _match(self, row, query):
        for key, expected in (query or {}).items():
            actual = row.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$gte" in expected and float(actual or 0) < float(expected["$gte"]):
                    return False
                if "$lte" in expected and actual > expected["$lte"]:
                    return False
                if "$exists" in expected:
                    exists = key in row
                    if bool(expected["$exists"]) != exists:
                        return False
            elif actual != expected:
                return False
        return True

    async def find_one(self, query, *args, **kwargs):
        for row in self.rows:
            if self._match(row, query):
                return dict(row)
        return None

    def find(self, query):
        return _AsyncCursor([row for row in self.rows if self._match(row, query)])

    async def insert_one(self, doc):
        if self.unique_idempotency and doc.get("idempotency_key"):
            for row in self.rows:
                if row.get("idempotency_key") == doc.get("idempotency_key"):
                    from pymongo.errors import DuplicateKeyError

                    raise DuplicateKeyError("duplicate idempotency_key")
        self.rows.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("_id"))

    async def update_one(self, query, update, **kwargs):
        for row in self.rows:
            if self._match(row, query):
                self._apply_update(row, update)
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    async def find_one_and_update(self, query, update, *, upsert=False, return_document=None, **kwargs):
        for row in self.rows:
            if self._match(row, query):
                before = dict(row)
                self._apply_update(row, update, is_insert=False)
                return dict(row if return_document == ReturnDocument.AFTER else before)
        if not upsert:
            return None
        doc = {k: v for k, v in query.items() if not isinstance(v, dict)}
        self._apply_update(doc, update, is_insert=True)
        self.rows.append(doc)
        return dict(doc)

    def _apply_update(self, row, update, *, is_insert=False):
        for key, value in update.get("$setOnInsert", {}).items():
            if is_insert:
                row[key] = value
        for key, value in update.get("$set", {}).items():
            row[key] = value
        for key, value in update.get("$inc", {}).items():
            row[key] = float(row.get(key) or 0.0) + float(value)


class _FakeDb:
    def __init__(self):
        self.cardex_wallets = _FakeCollection()
        self.cardex_cards = _FakeCollection()
        self.cardex_ledger = _FakeCollection(unique_idempotency=True)
        self.cardex_withdrawals = _FakeCollection()


@pytest.fixture
def fake_cardex_db(monkeypatch):
    fake = _FakeDb()
    monkeypatch.setattr(cardex_repo, "db", fake)
    return fake


@pytest.mark.asyncio
async def test_cardex_wallet_delta_is_atomic_and_non_negative(fake_cardex_db):
    fake_cardex_db.cardex_wallets.rows.append(
        {"user_id": "u1", "pending_usd": 0.0, "available_usd": 5.0, "locked_usd": 0.0}
    )

    wallet = await cardex_repo.update_wallet_deltas("u1", available_delta=-cardex_repo.Decimal("3"))

    assert wallet["available_usd"] == 2.0
    with pytest.raises(ValueError, match="Wallet invariant"):
        await cardex_repo.update_wallet_deltas("u1", available_delta=-cardex_repo.Decimal("3"))
    assert fake_cardex_db.cardex_wallets.rows[0]["available_usd"] == 2.0


@pytest.mark.asyncio
async def test_accept_card_is_claimed_once(fake_cardex_db):
    fake_cardex_db.cardex_cards.rows.append(
        {
            "_id": "card-1",
            "seller_user_id": "seller-1",
            "status": "submitted",
            "customer_value_usd": 10.0,
        }
    )

    card = await cardex_repo.accept_card("card-1", actor_user_id="admin")

    assert card["status"] == "customer_pending_credit"
    assert fake_cardex_db.cardex_wallets.rows[0]["pending_usd"] == 10.0
    assert len(fake_cardex_db.cardex_ledger.rows) == 1
    with pytest.raises(ValueError, match="current status"):
        await cardex_repo.accept_card("card-1", actor_user_id="admin")
    assert fake_cardex_db.cardex_wallets.rows[0]["pending_usd"] == 10.0
    assert len(fake_cardex_db.cardex_ledger.rows) == 1


@pytest.mark.asyncio
async def test_release_due_cards_is_idempotent(fake_cardex_db):
    fake_cardex_db.cardex_cards.rows.append(
        {
            "_id": "card-2",
            "seller_user_id": "seller-2",
            "status": "customer_pending_credit",
            "available_on": cardex_repo._now(),
            "customer_value_usd": 12.0,
        }
    )
    fake_cardex_db.cardex_wallets.rows.append(
        {"user_id": "seller-2", "pending_usd": 12.0, "available_usd": 0.0, "locked_usd": 0.0}
    )

    first = await cardex_repo.release_due_cards()
    second = await cardex_repo.release_due_cards()

    assert first == {"released": 1}
    assert second == {"released": 0}
    wallet = fake_cardex_db.cardex_wallets.rows[0]
    assert wallet["pending_usd"] == 0.0
    assert wallet["available_usd"] == 12.0
    assert len(fake_cardex_db.cardex_ledger.rows) == 1


@pytest.mark.asyncio
async def test_create_withdrawal_locks_available_balance_once(fake_cardex_db):
    fake_cardex_db.cardex_wallets.rows.append(
        {"user_id": "u2", "pending_usd": 0.0, "available_usd": 10.0, "locked_usd": 0.0}
    )

    row = await cardex_repo.create_withdrawal(
        user_id="u2",
        requested_usd_amount=cardex_repo.Decimal("8"),
        payout_currency="USD",
        notes="wallet",
    )

    assert row["status"] == "requested"
    wallet = fake_cardex_db.cardex_wallets.rows[0]
    assert wallet["available_usd"] == 2.0
    assert wallet["locked_usd"] == 8.0
    with pytest.raises(ValueError, match="Wallet invariant"):
        await cardex_repo.create_withdrawal(
            user_id="u2",
            requested_usd_amount=cardex_repo.Decimal("3"),
            payout_currency="USD",
            notes="wallet",
        )
    assert wallet["available_usd"] == 2.0
    assert wallet["locked_usd"] == 8.0
    assert len(fake_cardex_db.cardex_withdrawals.rows) == 1
