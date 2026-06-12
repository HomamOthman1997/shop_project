import pytest

from services.digital_products import manual_catalog


def _tree():
    return [
        {"_id": "root", "parent_id": None, "is_root": True, "name": "Website manual catalog"},
        {
            "_id": "section",
            "parent_id": "root",
            "website_level": "section",
            "website_slug": "mobile-recharge",
            "website_accent": "blue",
            "name": "شحن الرصيد",
        },
        {"_id": "family", "parent_id": "section", "website_level": "family", "name": "شحن أوكرانيا"},
        {"_id": "variant", "parent_id": "family", "website_level": "variant", "name": "Ukraine"},
        {
            "_id": "product",
            "parent_id": "variant",
            "website_level": "product",
            "node_type": "endpoint",
            "name": "شحن 100 UAH",
            "price": 3.5,
            "input_fields": [{"id": "phone_number", "label": "رقم الهاتف", "required": True}],
        },
    ]


def test_parse_input_fields_text_requires_explicit_ids_and_preserves_optional_fields():
    fields = manual_catalog.parse_input_fields_text(
        "phone_number|رقم الهاتف|required|text\nnotes|ملاحظات|optional|text\nbad line"
    )

    assert fields == [
        {"id": "phone_number", "label": "رقم الهاتف", "required": True, "type": "text"},
        {"id": "notes", "label": "ملاحظات", "required": False, "type": "text"},
    ]


@pytest.mark.asyncio
async def test_public_sections_exposes_only_complete_manual_families(monkeypatch):
    async def nodes(_owner_id, *, catalog_type):
        assert catalog_type == "website_manual"
        return _tree()

    monkeypatch.setattr(manual_catalog, "list_catalog_nodes", nodes)

    sections = await manual_catalog.public_sections(77)

    assert sections[0]["slug"] == "mobile-recharge"
    assert sections[0]["categories"][0]["service_key"] == "website_manual"
    assert sections[0]["categories"][0]["family_key"] == "family"


@pytest.mark.asyncio
async def test_fresh_quote_payload_reads_current_manual_product_price(monkeypatch):
    rows = {row["_id"]: row for row in _tree()}

    async def node(node_id, *, reseller_id, catalog_type):
        assert reseller_id == 77
        assert catalog_type == "website_manual"
        return rows.get(str(node_id))

    monkeypatch.setattr(manual_catalog, "get_node", node)

    quote = await manual_catalog.fresh_quote_payload("product", owner_id=77)

    assert quote["kind"] == "manual"
    assert quote["sale_price"] == 3.5
    assert quote["manual_variant_name"] == "Ukraine"
    assert quote["input_fields"][0]["id"] == "phone_number"
