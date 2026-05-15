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
        "Preorder",
    ]
    assert [row["position"] for row in child_docs] == [0, 1, 2, 3, 4, 5, 6]


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
        "Preorder",
    ]


@pytest.mark.asyncio
async def test_set_endpoint_inventory_persists_raw_payload_and_warnings(monkeypatch):
    captured = {}

    class _Collection:
        async def find_one_and_update(self, query, update, return_document=None):
            captured["query"] = query
            captured["update"] = update
            return {"_id": query["_id"]}

    monkeypatch.setattr(repo, "db", SimpleNamespace(custom_services=_Collection()))

    await repo.set_endpoint_inventory(
        ObjectId(),
        77,
        inventory_items=["A", "B"],
        raw_payload="RAW INPUT",
        parse_warnings=["warn-1", "warn-2"],
        catalog_type="custom",
    )

    payload = captured["update"]["$set"]
    assert payload["inventory_items"] == ["A", "B"]
    assert payload["inventory_raw_payload"] == "RAW INPUT"
    assert payload["inventory_parse_warnings"] == ["warn-1", "warn-2"]
    assert payload["available_qty"] == 2


@pytest.mark.asyncio
async def test_clone_catalog_copies_structure_without_sensitive_stock(monkeypatch):
    source_root = ObjectId()
    source_folder = ObjectId()
    source_endpoint = ObjectId()
    inserted = []

    docs = [
        {
            "_id": source_root,
            "reseller_id": 1,
            "catalog_type": "custom",
            "name": "Services",
            "node_type": "folder",
            "parent_id": None,
            "is_root": True,
            "is_active": True,
            "position": 0,
        },
        {
            "_id": source_folder,
            "reseller_id": 1,
            "catalog_type": "custom",
            "name": "Email",
            "node_type": "folder",
            "parent_id": source_root,
            "is_root": False,
            "is_active": True,
            "position": 0,
        },
        {
            "_id": source_endpoint,
            "reseller_id": 1,
            "catalog_type": "custom",
            "name": "Gmail",
            "node_type": "endpoint",
            "parent_id": source_folder,
            "is_root": False,
            "is_active": True,
            "position": 0,
            "price": 3.0,
            "available_qty": 2,
            "min_qty": 1,
            "preorder_enabled": True,
            "inventory_items": ["Email: real@example.com\nPassword: secret"],
            "inventory_raw_payload": "Email: real@example.com\nPassword: secret",
            "inventory_parse_warnings": ["warn"],
            "product_info_text": "Fresh account",
            "delivery_type": "inventory",
            "delivery_text": "secret text",
            "delivery_file_id": "file-id",
            "delivery_caption": "caption",
            "delivery_filename": "stock.txt",
        },
    ]

    class _Cursor:
        def __init__(self, rows):
            self.rows = list(rows)

        def sort(self, *_args, **_kwargs):
            self.rows.sort(key=lambda row: int(row.get("position", 0)))
            return self

        async def to_list(self, _limit):
            return list(self.rows)

    class _InsertOneResult:
        def __init__(self, inserted_id):
            self.inserted_id = inserted_id

    class _Collection:
        async def find_one(self, query, *args, **kwargs):
            for row in docs:
                if all(row.get(key) == value for key, value in query.items()):
                    return dict(row)
            return None

        async def count_documents(self, query):
            return len([row for row in docs if all(row.get(key) == value for key, value in query.items())])

        async def insert_one(self, doc):
            new_doc = dict(doc)
            new_doc["_id"] = ObjectId()
            docs.append(new_doc)
            inserted.append(new_doc)
            return _InsertOneResult(new_doc["_id"])

        async def insert_many(self, rows):
            raise AssertionError("clone target should not seed default folders")

        def find(self, query, *args, **kwargs):
            def _matches(row):
                return all(row.get(key) == value for key, value in query.items())

            return _Cursor([dict(row) for row in docs if _matches(row)])

    monkeypatch.setattr(repo, "db", SimpleNamespace(custom_services=_Collection()))

    result = await repo.clone_catalog_from_reseller_template(source_reseller_id=1, target_reseller_id=2)

    assert result["success"] is True
    cloned_endpoint = next(row for row in inserted if row.get("node_type") == "endpoint")
    assert cloned_endpoint["price"] == 3.0
    assert cloned_endpoint["product_info_text"] == "Fresh account"
    assert cloned_endpoint["available_qty"] == 0
    assert cloned_endpoint["inventory_items"] == []
    assert cloned_endpoint["inventory_raw_payload"] == ""
    assert cloned_endpoint["delivery_type"] == ""
    assert cloned_endpoint["delivery_text"] == ""
    assert cloned_endpoint["delivery_file_id"] == ""
