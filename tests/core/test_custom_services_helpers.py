import os
import sys
from types import SimpleNamespace

import pytest
from bson import ObjectId

sys.path.insert(0, os.getcwd())

from handlers.custom_services import _builder_add_options_kb, _is_cancel_input, _is_id_info_trigger, _is_services_trigger
from utils.translations import t


def _flatten_callback_data(kb):
    return [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]


def test_services_trigger_accepts_main_variants():
    assert _is_services_trigger(t("en", "btn_services"))
    assert _is_services_trigger(t("ar", "btn_services"))
    assert _is_services_trigger("/services")
    assert _is_services_trigger("/custom_services")
    assert _is_services_trigger("custom services")
    assert _is_services_trigger("كوستوم")


def test_services_trigger_rejects_random_text():
    assert not _is_services_trigger("hello there")
    assert not _is_services_trigger("support")
    assert not _is_services_trigger("")
    assert not _is_services_trigger(None)


def test_id_info_trigger_is_archived():
    assert not _is_id_info_trigger(t("en", "btn_id_info"))
    assert not _is_id_info_trigger(t("ar", "btn_id_info"))
    assert not _is_id_info_trigger("/id_info")
    assert not _is_id_info_trigger("id info")
    assert not _is_id_info_trigger("ID-INFO")


def test_id_info_trigger_rejects_random_text():
    assert not _is_id_info_trigger("hello there")
    assert not _is_id_info_trigger("services")
    assert not _is_id_info_trigger("")
    assert not _is_id_info_trigger(None)


def test_cancel_input_variants():
    assert _is_cancel_input("/cancel")
    assert _is_cancel_input("cancel")
    assert _is_cancel_input("إلغاء")
    assert _is_cancel_input("الغاء")
    assert not _is_cancel_input("back")


def test_builder_add_options_for_folder_and_endpoint():
    folder_kb = _builder_add_options_kb("x1", "folder")
    endpoint_kb = _builder_add_options_kb("x2", "endpoint")

    folder_actions = _flatten_callback_data(folder_kb)
    endpoint_actions = _flatten_callback_data(endpoint_kb)

    assert "cstm:addf:x1" in folder_actions
    assert "cstm:adde:x1" in folder_actions
    assert "cstm:adds:x1" in folder_actions
    assert "cstm:addse:x1" in folder_actions

    assert "cstm:addf:x2" not in endpoint_actions
    assert "cstm:adde:x2" not in endpoint_actions
    assert "cstm:adds:x2" in endpoint_actions
    assert "cstm:addse:x2" in endpoint_actions


@pytest.mark.asyncio
async def test_deactivate_node_cascades(monkeypatch):
    import database.custom_services_repo as repo

    root = ObjectId()
    child_a = ObjectId()
    child_b = ObjectId()
    grand_child = ObjectId()

    edges = {
        root: [child_a, child_b],
        child_a: [grand_child],
        child_b: [],
        grand_child: [],
    }

    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        async def to_list(self, _limit):
            return self.rows

    class FakeResult:
        def __init__(self, count):
            self.modified_count = count

    class FakeCollection:
        def __init__(self):
            self.updated_ids = []

        def find(self, query, projection):
            parent = query["parent_id"]
            return FakeCursor([{"_id": cid} for cid in edges.get(parent, [])])

        async def update_many(self, query, update):
            self.updated_ids = list(query["_id"]["$in"])
            return FakeResult(len(self.updated_ids))

    fake_collection = FakeCollection()
    monkeypatch.setattr(repo, "db", SimpleNamespace(custom_services=fake_collection))

    modified = await repo.deactivate_node(root, 77)
    assert modified == 4
    assert set(fake_collection.updated_ids) == {root, child_a, child_b, grand_child}
