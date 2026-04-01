import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

import database.custom_services_repo as repo


@pytest.mark.asyncio
async def test_ensure_root_node_seeds_default_custom_folders(monkeypatch):
    inserted_docs = []

    class _InsertOneResult:
        inserted_id = "root-1"

    class _Collection:
        async def find_one(self, query):
            return None

        async def insert_one(self, doc):
            inserted_docs.append(("root", doc))
            return _InsertOneResult()

        async def insert_many(self, docs):
            inserted_docs.append(("children", docs))
            return SimpleNamespace(inserted_ids=[f"child-{i}" for i in range(len(docs))])

    monkeypatch.setattr(repo, "db", SimpleNamespace(custom_services=_Collection()))

    root = await repo.ensure_root_node(77, catalog_type="custom")

    assert root["_id"] == "root-1"
    child_docs = next(payload for kind, payload in inserted_docs if kind == "children")
    assert [row["name"] for row in child_docs] == [
        "Email",
        "SSN",
        "ICloud",
        "VISA CARD",
        "BANKS",
        "PAYPAL",
    ]
    assert [row["position"] for row in child_docs] == [0, 1, 2, 3, 4, 5]
