import os
import sys
from types import SimpleNamespace

import pytest
from bson import ObjectId

sys.path.insert(0, os.getcwd())

import handlers.custom_services as custom_services
from handlers.custom_services import (
    _builder_add_options_kb,
    _endpoint_preorder_enabled,
    _endpoint_ready_for_sale,
    _is_cancel_input,
    _is_id_info_trigger,
    _parse_inventory_payload,
    _is_services_trigger,
)
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
    assert "cstm:adds:x1" not in folder_actions
    assert "cstm:addse:x1" not in folder_actions

    assert "cstm:addf:x2" not in endpoint_actions
    assert "cstm:adde:x2" not in endpoint_actions
    assert "cstm:adds:x2" not in endpoint_actions
    assert "cstm:addse:x2" not in endpoint_actions


def test_endpoint_ready_for_sale_variants():
    assert _endpoint_ready_for_sale({"delivery_type": "text", "delivery_text": "hello"})
    assert _endpoint_ready_for_sale({"delivery_type": "photo", "delivery_file_id": "file123"})
    assert _endpoint_ready_for_sale({"delivery_type": "document", "delivery_file_id": "file456"})
    assert _endpoint_ready_for_sale(
        {"delivery_type": "inventory", "inventory_items": ["a:b"], "available_qty": 1}
    )
    assert not _endpoint_ready_for_sale({"delivery_type": "text", "delivery_text": ""})
    assert not _endpoint_ready_for_sale({"delivery_type": "inventory", "inventory_items": [], "available_qty": 0})


def test_endpoint_preorder_flag_reads_boolean():
    assert _endpoint_preorder_enabled({"preorder_enabled": True}) is True
    assert _endpoint_preorder_enabled({"preorder_enabled": False}) is False
    assert _endpoint_preorder_enabled({}) is False


def test_parse_inventory_payload_supports_email_blocks():
    payload = """Email: first@example.com
Password: pass-1
Recovery: No Recovery
=================
Email: second@example.com
Password: pass-2
Recovery: No Recovery
"""

    assert _parse_inventory_payload(payload) == [
        "Email: first@example.com\nPassword: pass-1\nRecovery: No Recovery",
        "Email: second@example.com\nPassword: pass-2\nRecovery: No Recovery",
    ]


def test_parse_inventory_payload_supports_html_and_arabic_labels():
    payload = (
        "الايميل: first@example.com<br>"
        "كلمة السر : pass-1<br>"
        "الريكفري : لا يوجد<br>"
        "=================<br>"
        "الايميل: second@example.com<br>"
        "كلمة السر : pass-2<br>"
        "الريكفري : لا يوجد"
    )

    assert _parse_inventory_payload(payload) == [
        "Email: first@example.com\nPassword: pass-1\nRecovery: لا يوجد",
        "Email: second@example.com\nPassword: pass-2\nRecovery: لا يوجد",
    ]


@pytest.mark.asyncio
async def test_owner_can_open_builder_on_main_bot(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    async def _fake_is_reseller(*_args, **_kwargs):
        return False

    monkeypatch.setattr(custom_services, "_is_current_bot_reseller", _fake_is_reseller)

    async def _fake_main(_bot_id):
        return True

    monkeypatch.setattr(custom_services, "is_main_bot", _fake_main)
    monkeypatch.setattr(custom_services, "OWNER_ID", 9001)

    assert await custom_services._can_open_builder_catalog(9001, _Bot()) is True
    assert await custom_services._can_open_builder_catalog(9002, _Bot()) is False


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
