import os
import sys
from types import SimpleNamespace

import pytest
from bson import ObjectId

sys.path.insert(0, os.getcwd())

import database.custom_services_repo as repo


@pytest.mark.asyncio
async def test_ensure_root_node_seeds_default_custom_folders(monkeypatch):
    inserted_docs = []
    root_id = ObjectId()

    class _InsertOneResult:
        inserted_id = root_id

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

    assert root["_id"] == root_id
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


@pytest.mark.asyncio
async def test_ensure_root_node_seeds_existing_empty_root(monkeypatch):
    inserted_docs = []
    root_id = ObjectId()

    class _Collection:
        async def find_one(self, query):
            return {
                "_id": root_id,
                "reseller_id": 77,
                "catalog_type": "custom",
                "name": "Services",
                "node_type": "folder",
                "parent_id": None,
                "is_root": True,
                "is_active": True,
                "position": 0,
            }

        async def count_documents(self, query):
            return 0

        async def insert_many(self, docs):
            inserted_docs.extend(docs)
            return SimpleNamespace(inserted_ids=[f"child-{i}" for i in range(len(docs))])

    monkeypatch.setattr(repo, "db", SimpleNamespace(custom_services=_Collection()))

    root = await repo.ensure_root_node(77, catalog_type="custom")

    assert root["_id"] == root_id
    assert [row["name"] for row in inserted_docs] == [
        "Email",
        "SSN",
        "ICloud",
        "VISA CARD",
        "BANKS",
        "PAYPAL",
    ]
