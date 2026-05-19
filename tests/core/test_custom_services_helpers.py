import os
import sys
from types import SimpleNamespace

import pytest
from bson import ObjectId

sys.path.insert(0, os.getcwd())

import handlers.custom_services as custom_services
from handlers.custom_services import (
    _auto_fulfill_inventory_preorders,
    _builder_add_options_kb,
    _can_manage_builder,
    _can_manage_builder_structure,
    _allowed_buy_quantities,
    _buy_qty_options,
    _buy_qty_kb,
    _delivery_preview_text,
    _is_ssn_stock_context,
    _endpoint_preorder_enabled,
    _endpoint_ready_for_sale,
    _is_cancel_input,
    _is_id_info_trigger,
    _custom_services_admin_ids,
    _parse_inventory_submission,
    _parse_inventory_payload,
    _public_available_qty,
    _public_endpoint_text,
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
    folder_labels = [btn.text for row in folder_kb.inline_keyboard for btn in row]

    assert "cstm:addf:x1" in folder_actions
    assert "cstm:adde:x1" in folder_actions
    assert "Add Folder" in folder_labels
    assert "Add Item" in folder_labels
    assert "cstm:adds:x1" not in folder_actions
    assert "cstm:addse:x1" not in folder_actions

    assert "cstm:addf:x2" not in endpoint_actions
    assert "cstm:adde:x2" not in endpoint_actions
    assert "cstm:adds:x2" not in endpoint_actions
    assert "cstm:addse:x2" not in endpoint_actions


def test_email_services_allow_multi_quantity_presets():
    endpoint = {"name": "GMAIL Fresh"}
    assert _allowed_buy_quantities(endpoint, {"buy_service_name": "GMAIL Fresh"}) == [1, 5, 10]


def test_ssn_services_allow_multi_quantity_presets():
    endpoint = {"name": "SSN Fullz"}
    assert _allowed_buy_quantities(endpoint, {"buy_service_name": "SSN Fullz"}) == [1, 5, 10]


def test_non_email_services_allow_only_single_quantity():
    endpoint = {"name": "Netflix"}
    assert _allowed_buy_quantities(endpoint, {"buy_service_name": "Netflix"}) == [1]


def test_non_email_services_force_single_quantity_option_even_with_stock():
    endpoint = {"name": "PayPal with Bank", "available_qty": 20, "min_qty": 5}
    assert _buy_qty_options(endpoint, {"buy_service_name": "PayPal with Bank", "buy_min_qty": 5}) == [1]


def test_buy_qty_keyboard_filters_to_supported_quantities():
    kb = _buy_qty_kb(
        lang="en",
        endpoint_id="ep1",
        min_qty=1,
        available_qty=6,
        back_node_id="root1",
        quantities=[1, 5],
    )
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "1" in labels
    assert "5" in labels
    assert "10" not in labels


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


def test_stock_preview_masks_sensitive_values():
    preview = custom_services._stock_preview_text(
        ["Email: first@example.com\nPassword: pass-1\nRecovery: recovery@example.com"],
        [],
    )

    assert "Parsed stock items: 1" in preview
    assert "fi***@example.com" in preview
    assert "pass-1" not in preview
    assert "recovery@example.com" not in preview


def test_stock_preview_keeps_generic_blocks_understandable():
    preview = custom_services._stock_preview_text(
        ["PayPal: seller@example.com\nPassword: pass-1\nBank: Wise\n2FA: backup-code"],
        [],
    )

    assert "PayPal: se***@example.com" in preview
    assert "Bank: Wise" in preview
    assert "pass-1" not in preview
    assert "backup-code" not in preview


def test_stock_preview_abbreviates_unlabeled_plain_lines():
    preview = custom_services._stock_preview_text(
        ["dfgbdfmbn,ds\ndfdsfsdfsd\nsdfdsfsdfsds"],
        [],
    )

    assert "dfg***ds" in preview
    assert "dfd***sd" in preview
    assert "\n***\n***\n***" not in preview


def test_stock_input_prompt_uses_block_copy_for_non_email_items():
    prompt = custom_services._stock_input_prompt("en", {"name": "Paypal"}, mode="append")

    assert "Multi-line accounts stay one item." in prompt
    assert "separate each item with =====" in prompt
    assert "Mode: add to existing stock." in prompt
    assert "one item per line" not in prompt


def test_stock_input_prompt_keeps_line_mode_for_email_items():
    prompt = custom_services._stock_input_prompt("en", {"name": "Gmail"}, mode="replace")

    assert "one item per line" in prompt
    assert "email1@gmail.com:pass1" in prompt


def test_stock_preview_keyboard_is_localized():
    ar_labels = [btn.text for row in custom_services._stock_preview_kb("ar").inline_keyboard for btn in row]
    assert "✅ حفظ الستوك" in ar_labels
    assert "✏️ إرسال من جديد" in ar_labels


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


def test_parse_inventory_payload_splits_repeated_email_blocks_without_separators():
    payload = """Email: first@example.com
Password: pass-1
Recovery: No Recovery

Email: second@example.com
Password: pass-2
Recovery: No Recovery
"""

    assert _parse_inventory_payload(payload, ssn_mode=False) == [
        "Email: first@example.com\nPassword: pass-1\nRecovery: No Recovery",
        "Email: second@example.com\nPassword: pass-2\nRecovery: No Recovery",
    ]


def test_parse_inventory_payload_splits_repeated_email_inside_separator_block():
    payload = """Email: first@example.com
Password: pass-1
Recovery: No Recovery
=================
Email: second@example.com
Password: pass-2
Recovery: No Recovery
Email: third@example.com
Password: pass-3
Recovery: No Recovery
"""

    assert _parse_inventory_payload(payload, ssn_mode=False) == [
        "Email: first@example.com\nPassword: pass-1\nRecovery: No Recovery",
        "Email: second@example.com\nPassword: pass-2\nRecovery: No Recovery",
        "Email: third@example.com\nPassword: pass-3\nRecovery: No Recovery",
    ]


def test_split_claimed_inventory_items_caps_delivery_and_returns_overflow():
    from handlers.custom_services import _split_claimed_inventory_items

    deliver, overflow = _split_claimed_inventory_items(
        [
            "Email: first@example.com\nPassword: pass-1\nRecovery: No Recovery",
            "Email: second@example.com\nPassword: pass-2\nRecovery: No Recovery\nEmail: third@example.com\nPassword: pass-3\nRecovery: No Recovery",
        ],
        2,
    )

    assert deliver == [
        "Email: first@example.com\nPassword: pass-1\nRecovery: No Recovery",
        "Email: second@example.com\nPassword: pass-2\nRecovery: No Recovery",
    ]
    assert overflow == ["Email: third@example.com\nPassword: pass-3\nRecovery: No Recovery"]


def test_delivery_preview_caps_malformed_inventory_to_requested_qty():
    malformed = (
        "Email: fifth@example.com\n"
        "Password: pass-5\n"
        "Recovery: No Recovery\n"
        "Email: sixth@example.com\n"
        "Password: pass-6\n"
        "Recovery: No Recovery"
    )
    text = _delivery_preview_text(
        endpoint={"delivery_type": "inventory"},
        qty=1,
        lang="en",
        stock_items=[malformed],
    )

    assert text is not None
    assert "fifth@example.com" in text
    assert "sixth@example.com" not in text
    assert text.count("Email:") == 1
    assert "Digital Delivery" not in text
    assert "Qty:" not in text


def test_customer_purchase_success_text_is_compact_for_single_item():
    text = custom_services._customer_purchase_success_text(
        lang="ar",
        service="Paypal",
        qty=1,
        total=2.0,
        delivery_text="بيانات الطلب:\n\naccount payload",
    )

    assert "تم الشراء بنجاح" in text
    assert "المنتج: Paypal" in text
    assert "الإجمالي: 2.00" in text
    assert "account payload" in text
    assert "تسليم رقمي" not in text
    assert "الكمية:" not in text
    assert "المتبقي" not in text
    assert "==========" not in text


def test_parse_inventory_payload_splits_repeated_arabic_email_blocks_without_separators():
    payload = """الإيميل: first@example.com
كلمة المرور: pass-1
بريد الاسترداد: No Recovery

الايميل: second@example.com
الباسورد: pass-2
ريكفري: No Recovery
"""

    assert _parse_inventory_payload(payload, ssn_mode=False) == [
        "Email: first@example.com\nPassword: pass-1\nRecovery: No Recovery",
        "Email: second@example.com\nPassword: pass-2\nRecovery: No Recovery",
    ]


def test_delivery_preview_separates_multiple_inventory_items():
    text = _delivery_preview_text(
        endpoint={"delivery_type": "inventory"},
        qty=2,
        lang="en",
        stock_items=[
            "Email: first@example.com\nPassword: pass-1",
            "Email: second@example.com\nPassword: pass-2",
        ],
    )

    assert text is not None
    assert "=================" in text
    assert "first@example.com" in text
    assert "second@example.com" in text


def test_parse_inventory_payload_supports_numbered_ssn_blocks():
    payload = """Number: 1

Account Information

Primary Email: alfred69dorsey@gmail.com

Recovary Email: osamah99dwaji@gmail.com

Mail Pass: ALFRED69DORSEY@@

Bank Pass: ALFRED69DORSEY@@

SSN: ALFRED DORSEY  4400 SE NAEF RD F11  MILWAUKEE  OR  97267  10/26/2000  541591832  5037375270  USA

GENDER: M
"""
    parsed = _parse_inventory_payload(payload)

    assert len(parsed) == 1
    assert "SSN: 541-59-1832" in parsed[0]
    assert "Gender: Male (m)" in parsed[0]
    assert "Birthdate: 10/26/2000" in parsed[0]
    assert "First Name: ALFRED" in parsed[0]
    assert "Last Name: DORSEY" in parsed[0]
    assert "Address: 4400 SE NAEF RD F11" in parsed[0]
    assert "City: MILWAUKEE" in parsed[0]
    assert "State: OR" in parsed[0]
    assert "Zip: 97267" in parsed[0]
    assert "Phone: 503 737-5270" in parsed[0]
    assert "Email: alfred69dorsey@gmail.com" in parsed[0]


def test_parse_inventory_payload_supports_pipe_delimited_ssn_rows():
    payload = """ssn | dob (year-month-day) | firstname|  middle| lastname | address | city | state | zip | phone | email | driver license | iss_state
612344358|1990-02-05|Karina||Pedraza|10157 palazzo Marcelli ct |Las Vegas|NV|89147|725 265-5670|Kpedraza1116@outlook.com|2102423544|NV
"""
    parsed = _parse_inventory_payload(payload)

    assert len(parsed) == 1
    assert "SSN: 612-34-4358" in parsed[0]
    assert "Birthdate: 2/5/1990" in parsed[0]
    assert "First Name: Karina" in parsed[0]
    assert "Last Name: Pedraza" in parsed[0]
    assert "Address: 10157 palazzo Marcelli ct" in parsed[0]
    assert "City: Las Vegas" in parsed[0]
    assert "State: NV" in parsed[0]
    assert "Driver License: 2102423544" in parsed[0]


def test_parse_inventory_payload_supports_spaced_ssn_rows():
    payload = """first  last  address  city  st  zip  dob  ssn
SHERVON  ADAMS  859 WILLIAM ST  POMONA  CA  91768  11/13/1976  626868571
PHYLLIS J  MORGAN  1873 SILVER OAKS CIR APT B  AURORA  IL  60504  3/15/1950  361822211
"""
    parsed = _parse_inventory_payload(payload)

    assert len(parsed) == 2
    assert "SSN: 626-86-8571" in parsed[0]
    assert "Birthdate: 11/13/1976" in parsed[0]
    assert "First Name: SHERVON" in parsed[0]
    assert "Last Name: ADAMS" in parsed[0]
    assert "City: POMONA" in parsed[0]
    assert "State: CA" in parsed[0]
    assert "SSN: 361-82-2211" in parsed[1]
    assert "Birthdate: 3/15/1950" in parsed[1]
    assert "First Name: PHYLLIS" in parsed[1]
    assert "Middle Name: J" in parsed[1]
    assert "Last Name: MORGAN" in parsed[1]
    assert "Address: 1873 SILVER OAKS CIR APT B" in parsed[1]


def test_parse_inventory_payload_supports_json_ssn_rows():
    payload = """{"ssn": "063460145", "first_name": "ROSANNE", "last_name": "HANTON", "middle_name": "", "dob": "09/07/1954", "gender": "F", "email": "rhanton@boriken.org", "phone": "", "addr1": "221 East 122nd Street", "addr2": "3204", "city": "New York", "state": "NY", "zip": 10035, "country": null}"""
    parsed = _parse_inventory_payload(payload)

    assert len(parsed) == 1
    assert "SSN: 063-46-0145" in parsed[0]
    assert "Gender: Female (f)" in parsed[0]
    assert "Birthdate: 09/07/1954" in parsed[0]
    assert "First Name: ROSANNE" in parsed[0]
    assert "Last Name: HANTON" in parsed[0]
    assert "Address: 221 East 122nd Street 3204" in parsed[0]
    assert "City: New York" in parsed[0]
    assert "State: NY" in parsed[0]
    assert "Zip: 10035" in parsed[0]
    assert "Email: rhanton@boriken.org" in parsed[0]


def test_parse_inventory_payload_can_skip_ssn_parsing_for_non_ssn_services():
    payload = """first  last  address  city  st  zip  dob  ssn
SHERVON  ADAMS  859 WILLIAM ST  POMONA  CA  91768  11/13/1976  626868571
"""
    parsed = _parse_inventory_payload(payload, ssn_mode=False)

    assert parsed == [
        "first  last  address  city  st  zip  dob  ssn\n"
        "SHERVON  ADAMS  859 WILLIAM ST  POMONA  CA  91768  11/13/1976  626868571",
    ]


def test_parse_inventory_payload_keeps_non_email_accounts_as_one_item():
    payload = """PayPal: seller@example.com
Password: pass-1
2FA: backup-code
"""

    assert _parse_inventory_payload(payload, ssn_mode=False) == [
        "PayPal: seller@example.com\nPassword: pass-1\n2FA: backup-code"
    ]
    assert _parse_inventory_payload(payload, ssn_mode=False, split_plain_lines=True) == [
        "PayPal: seller@example.com",
        "Password: pass-1",
        "2FA: backup-code",
    ]


def test_paypal_bank_stock_block_stays_one_item_in_builder_flow():
    payload = """PayPal: seller@example.com
Password: pass-1
Bank: Wise
2FA: backup-code
"""
    split_plain_lines = custom_services._service_supports_multi_qty({"name": "PayPal with Bank"})

    assert split_plain_lines is False
    assert _parse_inventory_payload(payload, ssn_mode=False, split_plain_lines=split_plain_lines) == [
        "PayPal: seller@example.com\nPassword: pass-1\nBank: Wise\n2FA: backup-code"
    ]


def test_parse_inventory_submission_adds_incomplete_ssn_warnings():
    payload = """{"ssn": "063460145", "first_name": "ROSANNE", "last_name": "HANTON"}"""
    items, raw_payload, warnings = _parse_inventory_submission(payload, ssn_mode=True)

    assert len(items) == 1
    assert raw_payload == payload
    assert warnings
    assert "Birthdate" in warnings[0]
    assert "Address" in warnings[0]


def test_is_ssn_stock_context_checks_endpoint_and_parent():
    assert _is_ssn_stock_context({"name": "California Fullz"}, {"name": "SSN"}) is True
    assert _is_ssn_stock_context({"name": "SSN Deluxe"}, None) is True
    assert _is_ssn_stock_context({"name": "GMAIL Fresh"}, {"name": "Email"}) is False


def test_public_available_qty_hides_unconfigured_endpoint_stock():
    endpoint = {
        "name": "OUTLOOK",
        "delivery_type": "",
        "available_qty": 1,
        "inventory_items": [],
        "preorder_enabled": False,
    }
    assert _public_available_qty(endpoint) == 0


def test_public_endpoint_text_hides_internal_builder_fields():
    endpoint = {
        "name": "GMAIL",
        "price": 1.0,
        "available_qty": 1,
        "inventory_items": [],
        "delivery_type": "",
        "product_info_text": "",
        "preorder_enabled": False,
        "min_qty": 1,
    }
    text = _public_endpoint_text(endpoint, catalog_title="Custom Services", lang="en")

    assert "Name: GMAIL" in text
    assert "Price:" in text
    assert "Available: 0" in text
    assert "Minimum Qty" not in text
    assert "Delivery:" not in text
    assert "Stock Items:" not in text
    assert "Preorder:" not in text
    assert "Product Info:" not in text


def test_public_endpoint_text_does_not_hide_unavailable_for_reseller_preorder():
    endpoint = {
        "name": "GMAIL",
        "price": 1.0,
        "available_qty": 0,
        "inventory_items": [],
        "delivery_type": "inventory",
        "product_info_text": "",
        "preorder_enabled": True,
    }

    reseller_text = _public_endpoint_text(endpoint, catalog_title="Custom Services", lang="en")
    main_text = _public_endpoint_text(
        endpoint,
        catalog_title="Custom Services",
        lang="en",
        preorder_available=True,
    )

    assert t("en", "custom_service_unavailable") in reseller_text
    assert t("en", "custom_service_unavailable") not in main_text


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
    monkeypatch.setattr(custom_services.settings, "custom_services_admin_ids", "")

    assert await custom_services._can_open_builder_catalog(9001, _Bot()) is True
    assert await custom_services._can_open_builder_catalog(9002, _Bot()) is False


def test_custom_services_admin_ids_parses_csv(monkeypatch):
    monkeypatch.setattr(custom_services.settings, "custom_services_admin_ids", " 12, 34,invalid,,56 ")
    assert _custom_services_admin_ids() == {12, 34, 56}


@pytest.mark.asyncio
async def test_open_custom_user_goes_directly_to_catalog_for_regular_user(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Message:
        def __init__(self):
            self.text = "Custom Services"
            self.bot = _Bot()
            self.from_user = SimpleNamespace(id=5001)
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})
            return SimpleNamespace(message_id=1)

    class _State:
        def __init__(self):
            self.data = {}
            self.cleared = False

        async def clear(self):
            self.cleared = True

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def get_data(self):
            return dict(self.data)

    rendered = {}

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_main(_bot_id):
        return True

    async def _fake_can_open_builder(_user_id, _bot):
        return False

    async def _fake_owner(_user_id, _bot_id):
        return 7001

    async def _fake_wallet(_user_id, _bot_id):
        return 7001

    async def _fake_root(_owner_id, **_kwargs):
        return {"_id": "root1"}

    async def _fake_children(*_args, **_kwargs):
        return [{"_id": "folder1", "node_type": "folder"}]

    async def _fake_render(message_or_cb, state, reseller_id, node_id, *, is_builder, catalog_type, **_kwargs):
        rendered.update(
            {
                "reseller_id": reseller_id,
                "node_id": node_id,
                "is_builder": is_builder,
                "catalog_type": catalog_type,
            }
        )

    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "is_main_bot", _fake_main)
    monkeypatch.setattr(custom_services, "_can_open_builder_catalog", _fake_can_open_builder)
    monkeypatch.setattr(custom_services, "_resolve_catalog_owner_id", _fake_owner)
    monkeypatch.setattr(custom_services, "_resolve_user_reseller", _fake_wallet)
    monkeypatch.setattr(custom_services, "ensure_root_node", _fake_root)
    monkeypatch.setattr(custom_services, "list_children", _fake_children)
    monkeypatch.setattr(custom_services, "_render_node", _fake_render)

    message = _Message()
    state = _State()

    await custom_services.open_custom_user(message, state)

    assert state.cleared is True
    assert rendered["is_builder"] is False
    assert rendered["node_id"] == "root1"
    assert len(message.answers) == 1


@pytest.mark.asyncio
async def test_open_custom_user_shows_landing_for_admin(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Message:
        def __init__(self):
            self.text = "Custom Services"
            self.bot = _Bot()
            self.from_user = SimpleNamespace(id=9002)
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})
            return SimpleNamespace(message_id=1)

    class _State:
        def __init__(self):
            self.data = {}

        async def clear(self):
            self.data.clear()

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def get_data(self):
            return dict(self.data)

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_main(_bot_id):
        return True

    async def _fake_can_open_builder(_user_id, _bot):
        return True

    async def _fake_owner(_user_id, _bot_id):
        return 7001

    async def _fake_wallet(_user_id, _bot_id):
        return 7001

    async def _fake_root(_owner_id, **_kwargs):
        return {"_id": "root-owner"}

    async def _fake_children(*_args, **_kwargs):
        return []

    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "is_main_bot", _fake_main)
    monkeypatch.setattr(custom_services, "_can_open_builder_catalog", _fake_can_open_builder)
    monkeypatch.setattr(custom_services, "_resolve_catalog_owner_id", _fake_owner)
    monkeypatch.setattr(custom_services, "_resolve_user_reseller", _fake_wallet)
    monkeypatch.setattr(custom_services, "ensure_root_node", _fake_root)
    monkeypatch.setattr(custom_services, "list_children", _fake_children)
    monkeypatch.setattr(custom_services, "OWNER_ID", 9001)

    message = _Message()
    state = _State()

    await custom_services.open_custom_user(message, state)

    assert state.data["custom_mode"] == "builder"
    assert state.data["custom_catalog_owner_id"] == 9001
    assert state.data["custom_root_node_id"] == "root-owner"
    assert len(message.answers) == 2
    assert "Custom Services" in message.answers[-1]["text"]
    markup = message.answers[-1]["kwargs"]["reply_markup"]
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callbacks == ["cstm:entry:catalog", "cstm:entry:builder", "cstm:cancel"]


@pytest.mark.asyncio
async def test_main_bot_admin_gets_operational_access_only(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    async def _fake_is_reseller(*_args, **_kwargs):
        return False

    async def _fake_main(_bot_id):
        return True

    monkeypatch.setattr(custom_services, "_is_current_bot_reseller", _fake_is_reseller)
    monkeypatch.setattr(custom_services, "is_main_bot", _fake_main)
    monkeypatch.setattr(custom_services, "OWNER_ID", 9001)
    monkeypatch.setattr(custom_services.settings, "custom_services_admin_ids", "9002, 9003")

    assert await custom_services._can_open_builder_catalog(9002, _Bot()) is True
    assert await _can_manage_builder(9002, _Bot()) is True
    assert await _can_manage_builder_structure(9002, _Bot()) is False
    assert await _can_manage_builder_structure(9001, _Bot()) is True


@pytest.mark.asyncio
async def test_preview_endpoint_as_customer_uses_public_view(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Message:
        def __init__(self):
            self.edits = []

        async def edit_text(self, text, **kwargs):
            self.edits.append({"text": text, "kwargs": kwargs})

    class _Callback:
        data = "cstm:preview:ep1"
        from_user = SimpleNamespace(id=9001)

        def __init__(self):
            self.bot = _Bot()
            self.message = _Message()
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})

    class _State:
        async def get_data(self):
            return {"custom_catalog_owner_id": 9001}

    async def _fake_can_manage(_user_id, _bot):
        return True

    async def _fake_owner(_user_id, _bot, _data):
        return 9001

    async def _fake_get_node(_node_id, **_kwargs):
        return {
            "_id": "ep1",
            "reseller_id": 9001,
            "node_type": "endpoint",
            "name": "Gmail",
            "price": 2.0,
            "available_qty": 3,
            "delivery_type": "inventory",
            "inventory_items": ["x"],
            "product_info_text": "Fresh account",
        }

    async def _fake_preorder(_endpoint, _bot):
        return False

    async def _fake_lang(_user_id):
        return "en"

    monkeypatch.setattr(custom_services, "_user_lang", _fake_lang)
    monkeypatch.setattr(custom_services, "_can_manage_builder", _fake_can_manage)
    monkeypatch.setattr(custom_services, "_builder_catalog_owner_id", _fake_owner)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "_can_use_preorder", _fake_preorder)

    callback = _Callback()
    await custom_services.preview_endpoint_as_customer(callback, _State())

    assert callback.message.edits
    text = callback.message.edits[-1]["text"]
    assert "Gmail" in text
    assert "Fresh account" in text
    assert "Stock Items" not in text


@pytest.mark.asyncio
async def test_render_root_builder_hides_root_rename(monkeypatch):
    root = {
        "_id": "root1",
        "reseller_id": 9001,
        "catalog_type": "custom",
        "node_type": "folder",
        "name": "Services",
        "parent_id": None,
        "is_root": True,
    }

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Message:
        def __init__(self):
            self.from_user = SimpleNamespace(id=9001)
            self.bot = _Bot()
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})

    class _State:
        def __init__(self):
            self.data = {"custom_return_to": "reseller_menu"}

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

    async def _fake_get_node(_node_id, **_kwargs):
        return dict(root)

    async def _fake_children(*_args, **_kwargs):
        return []

    async def _fake_lang(_user_id):
        return "en"

    async def _fake_access(_user_id, _bot):
        return "full"

    async def _fake_toggle(_user_id, _bot):
        return False

    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "list_children", _fake_children)
    monkeypatch.setattr(custom_services, "_user_lang", _fake_lang)
    monkeypatch.setattr(custom_services, "_custom_services_access_level", _fake_access)
    monkeypatch.setattr(custom_services, "_can_toggle_preorder", _fake_toggle)

    message = _Message()
    await custom_services._render_node(
        message,
        _State(),
        reseller_id=9001,
        node_id=root["_id"],
        is_builder=True,
        catalog_type="custom",
    )

    markup = message.answers[-1]["kwargs"]["reply_markup"]
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
    labels = [btn.text for row in markup.inline_keyboard for btn in row]

    assert f"cstm:rename:{root['_id']}" not in callbacks
    assert f"cstm:edittxt:{root['_id']}" in callbacks
    assert "Back to Reseller Menu" in labels


@pytest.mark.asyncio
async def test_rename_root_node_start_is_blocked(monkeypatch):
    root = {"_id": "root1", "catalog_type": "custom", "node_type": "folder", "name": "Services", "is_root": True}

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Message:
        def __init__(self):
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})

    class _Callback:
        def __init__(self):
            self.data = "cstm:rename:root1"
            self.from_user = SimpleNamespace(id=9001)
            self.bot = _Bot()
            self.message = _Message()
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": str(text or ""), "kwargs": kwargs})

    class _State:
        def __init__(self):
            self.state = None
            self.data = {}

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, state):
            self.state = state

    async def _fake_lang(_user_id):
        return "en"

    async def _fake_can_structure(_user_id, _bot):
        return True

    async def _fake_owner(_user_id, _bot, _data):
        return 9001

    async def _fake_get_node(_node_id, **_kwargs):
        return dict(root)

    monkeypatch.setattr(custom_services, "_user_lang", _fake_lang)
    monkeypatch.setattr(custom_services, "_can_manage_builder_structure", _fake_can_structure)
    monkeypatch.setattr(custom_services, "_builder_catalog_owner_id", _fake_owner)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)

    callback = _Callback()
    state = _State()
    await custom_services.rename_node_start(callback, state)

    assert callback.answers[-1]["kwargs"].get("show_alert") is True
    assert "main catalog" in callback.answers[-1]["text"]
    assert state.state is None
    assert callback.message.answers == []


@pytest.mark.asyncio
async def test_rename_root_node_submit_from_stale_state_is_blocked(monkeypatch):
    root = {"_id": "root1", "catalog_type": "custom", "node_type": "folder", "name": "Services", "is_root": True}
    rendered = {}

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Message:
        def __init__(self):
            self.text = "New Name"
            self.from_user = SimpleNamespace(id=9001)
            self.bot = _Bot()
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})

    class _State:
        def __init__(self):
            self.cleared = False
            self.data = {
                "custom_mode": "builder",
                "custom_catalog_owner_id": 9001,
                "custom_catalog_type": "custom",
                "rename_node_id": root["_id"],
            }

        async def get_data(self):
            return dict(self.data)

        async def clear(self):
            self.cleared = True
            self.data.clear()

    async def _fake_lang(_user_id):
        return "en"

    async def _fake_can_structure(_user_id, _bot):
        return True

    async def _fake_owner(_user_id, _bot, _data):
        return 9001

    async def _fake_get_node(_node_id, **_kwargs):
        return dict(root)

    async def _fake_rename_node(*_args, **_kwargs):
        raise AssertionError("root rename should not reach repository update")

    async def _fake_render(_message, _state, reseller_id, node_id, **kwargs):
        rendered.update({"reseller_id": reseller_id, "node_id": node_id, **kwargs})

    monkeypatch.setattr(custom_services, "_user_lang", _fake_lang)
    monkeypatch.setattr(custom_services, "_can_manage_builder_structure", _fake_can_structure)
    monkeypatch.setattr(custom_services, "_builder_catalog_owner_id", _fake_owner)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "rename_node", _fake_rename_node)
    monkeypatch.setattr(custom_services, "_render_node", _fake_render)

    message = _Message()
    state = _State()
    await custom_services.rename_node_submit(message, state)

    assert state.cleared is True
    assert "main catalog" in message.answers[-1]["text"]
    assert rendered["node_id"] == root["_id"]
    assert rendered["is_builder"] is True


@pytest.mark.asyncio
async def test_custom_cancel_from_builder_returns_reseller_menu(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Message:
        def __init__(self):
            self.answers = []
            self.reply_markup_edits = []

        async def edit_reply_markup(self, reply_markup=None, **_kwargs):
            self.reply_markup_edits.append(reply_markup)

        async def answer(self, text, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})

    class _Callback:
        def __init__(self):
            self.data = "cstm:cancel"
            self.from_user = SimpleNamespace(id=9001)
            self.bot = _Bot()
            self.message = _Message()
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": str(text or ""), "kwargs": kwargs})

    class _State:
        def __init__(self):
            self.cleared = False
            self.data = {"custom_mode": "builder", "custom_return_to": "reseller_menu"}

        async def get_data(self):
            return dict(self.data)

        async def clear(self):
            self.cleared = True
            self.data.clear()

    async def _fake_lang(_user_id):
        return "en"

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_is_reseller(_user_id, _bot):
        return True

    async def _fake_menu_for_current_bot(*_args, **_kwargs):
        raise AssertionError("builder cancel should not return the customer menu")

    monkeypatch.setattr(custom_services, "_user_lang", _fake_lang)
    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "_is_current_bot_reseller", _fake_is_reseller)
    monkeypatch.setattr(custom_services, "menu_for_current_bot", _fake_menu_for_current_bot)

    callback = _Callback()
    state = _State()
    await custom_services.custom_panel_cancel(callback, state)

    assert state.cleared is True
    assert "reseller" in callback.message.answers[-1]["text"].lower()
    markup = callback.message.answers[-1]["kwargs"]["reply_markup"]
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
    assert "rsmenu:dashboard" in callbacks
    assert "rsmenu:custom_services" in callbacks


@pytest.mark.asyncio
async def test_custom_cancel_with_stale_state_returns_reseller_menu(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Message:
        def __init__(self):
            self.answers = []

        async def edit_reply_markup(self, reply_markup=None, **_kwargs):
            return None

        async def answer(self, text, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})

    class _Callback:
        def __init__(self):
            self.data = "cstm:cancel"
            self.from_user = SimpleNamespace(id=9001)
            self.bot = _Bot()
            self.message = _Message()
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": str(text or ""), "kwargs": kwargs})

    class _State:
        def __init__(self):
            self.cleared = False

        async def get_data(self):
            return {}

        async def clear(self):
            self.cleared = True

    async def _fake_lang(_user_id):
        return "en"

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_is_reseller(_user_id, _bot):
        return True

    async def _fake_menu_for_current_bot(*_args, **_kwargs):
        raise AssertionError("stale reseller cancel should not return the customer menu")

    monkeypatch.setattr(custom_services, "_user_lang", _fake_lang)
    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "_is_current_bot_reseller", _fake_is_reseller)
    monkeypatch.setattr(custom_services, "menu_for_current_bot", _fake_menu_for_current_bot)

    callback = _Callback()
    state = _State()
    await custom_services.custom_panel_cancel(callback, state)

    assert state.cleared is True
    assert "reseller" in callback.message.answers[-1]["text"].lower()
    markup = callback.message.answers[-1]["kwargs"]["reply_markup"]
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
    assert "rsmenu:dashboard" in callbacks
    assert "rsmenu:custom_services" in callbacks


@pytest.mark.asyncio
async def test_custom_cancel_from_user_mode_keeps_customer_menu(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Message:
        def __init__(self):
            self.answers = []

        async def edit_reply_markup(self, reply_markup=None, **_kwargs):
            return None

        async def answer(self, text, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})

    class _Callback:
        def __init__(self):
            self.data = "cstm:cancel"
            self.from_user = SimpleNamespace(id=9001)
            self.bot = _Bot()
            self.message = _Message()
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": str(text or ""), "kwargs": kwargs})

    class _State:
        def __init__(self):
            self.data = {"custom_mode": "user", "custom_return_to": "bot_menu"}

        async def get_data(self):
            return dict(self.data)

        async def clear(self):
            self.data.clear()

    async def _fake_lang(_user_id):
        return "en"

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_is_reseller(_user_id, _bot):
        return True

    async def _fake_menu_for_current_bot(lang, bot_id, user_id=None):
        return {"lang": lang, "bot_id": bot_id, "user_id": user_id, "kind": "customer"}

    monkeypatch.setattr(custom_services, "_user_lang", _fake_lang)
    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "_is_current_bot_reseller", _fake_is_reseller)
    monkeypatch.setattr(custom_services, "menu_for_current_bot", _fake_menu_for_current_bot)

    callback = _Callback()
    await custom_services.custom_panel_cancel(callback, _State())

    assert callback.message.answers[-1]["text"] == "Main Menu"
    assert callback.message.answers[-1]["kwargs"]["reply_markup"]["kind"] == "customer"
    assert callback.message.answers[-1]["kwargs"]["reply_markup"]["user_id"] == 9001


@pytest.mark.asyncio
async def test_delete_endpoint_blocks_pending_custom_work(monkeypatch):
    node = {"_id": ObjectId(), "reseller_id": 9001, "node_type": "endpoint", "name": "Gmail"}

    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Callback:
        def __init__(self):
            self.data = f"cstm:del:{node['_id']}"
            self.from_user = SimpleNamespace(id=9001)
            self.bot = _Bot()
            self.message = None
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": str(text or ""), "kwargs": kwargs})

    class _State:
        async def get_data(self):
            return {"custom_catalog_owner_id": 9001}

    async def _fake_can_structure(_user_id, _bot):
        return True

    async def _fake_owner(_user_id, _bot, _data):
        return 9001

    async def _fake_get_node(_node_id, **_kwargs):
        return dict(node)

    async def _fake_has_pending(_node, _owner_id, _catalog_type):
        return True

    async def _fake_lang(_user_id):
        return "en"

    monkeypatch.setattr(custom_services, "_user_lang", _fake_lang)
    monkeypatch.setattr(custom_services, "_can_manage_builder_structure", _fake_can_structure)
    monkeypatch.setattr(custom_services, "_builder_catalog_owner_id", _fake_owner)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "_node_has_pending_custom_work", _fake_has_pending)

    callback = _Callback()
    await custom_services.delete_node_cb(callback, _State())

    assert callback.answers
    assert callback.answers[-1]["kwargs"].get("show_alert") is True
    assert "pending" in callback.answers[-1]["text"].lower()


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


@pytest.mark.asyncio
async def test_auto_fulfill_inventory_preorders_delivers_fifo(monkeypatch):
    deliveries = []
    order_updates = []
    statuses = []
    queue = [{"_id": "pre1", "buyer_user_id": 88, "order_id": "ord1", "qty": 1}, None]

    async def _fake_next_pending(_endpoint_id):
        return queue.pop(0)

    async def _fake_claim(*_args, **_kwargs):
        return {
            "claimed_items": ["Email: first@example.com\nPassword: p1\nRecovery: No Recovery"],
            "remaining_qty": 0,
        }

    async def _fake_mark_fulfilling(preorder_id, actor_id):
        return {"_id": preorder_id, "buyer_user_id": 88, "order_id": "ord1", "qty": 1}

    async def _fake_mark_fulfilled(preorder_id, actor_id):
        return {"_id": preorder_id}

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_send_delivery(**kwargs):
        deliveries.append(kwargs)
        return True

    async def _fake_update_order_details(order_id, payload):
        order_updates.append((order_id, payload))

    async def _fake_update_order_status(order_id, status):
        statuses.append((order_id, status))

    monkeypatch.setattr(custom_services, "get_next_pending_preorder", _fake_next_pending)
    monkeypatch.setattr(custom_services, "claim_endpoint_inventory", _fake_claim)
    monkeypatch.setattr(custom_services, "mark_preorder_fulfilling", _fake_mark_fulfilling)
    monkeypatch.setattr(custom_services, "mark_preorder_fulfilled", _fake_mark_fulfilled)
    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "_send_endpoint_delivery", _fake_send_delivery)
    monkeypatch.setattr(custom_services, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(custom_services, "update_order_status", _fake_update_order_status)

    delivered = await _auto_fulfill_inventory_preorders(
        bot=SimpleNamespace(),
        endpoint={"_id": "ep1", "name": "GMAIL"},
        catalog_owner_id=77,
        catalog_type="custom",
    )

    assert delivered == ["pre1"]
    assert deliveries and deliveries[0]["user_id"] == 88
    assert statuses == [("ord1", "success")]
    assert order_updates and order_updates[0][1]["custom_preorder_fulfilled_automatically"] is True
