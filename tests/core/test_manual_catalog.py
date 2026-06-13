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


def _static_tree():
    return [
        {"_id": "root", "parent_id": None, "is_root": True, "name": "Website manual catalog"},
        {
            "_id": "section",
            "parent_id": "root",
            "website_level": "section",
            "website_slug": "games",
            "website_section_key": "games",
            "website_accent": "green",
            "name": "Games",
        },
        {
            "_id": "family",
            "parent_id": "section",
            "website_level": "family",
            "website_section_key": "games",
            "website_family_key": "pubg",
            "name": "PUBG",
        },
        {
            "_id": "variant",
            "parent_id": "family",
            "website_level": "variant",
            "website_section_key": "games",
            "website_family_key": "pubg",
            "website_variant_key": "global",
            "name": "Global",
        },
        {
            "_id": "product",
            "parent_id": "variant",
            "website_level": "product",
            "node_type": "endpoint",
            "name": "325 UC manual",
            "price": 6.6,
            "website_image_url": "https://cdn.example.test/pubg-uc.png",
            "input_fields": [{"id": "player_id", "label": "Player ID", "required": True}],
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
    assert sections[0]["categories"][0]["node_id"] == "family"
    assert sections[0]["categories"][0]["service_key"] == "website_manual"
    assert sections[0]["categories"][0]["family_key"] == "family"


@pytest.mark.asyncio
async def test_static_manual_overlay_does_not_duplicate_builtin_family_in_public_catalog(monkeypatch):
    async def nodes(_owner_id, *, catalog_type):
        assert catalog_type == "website_manual"
        return _static_tree()

    monkeypatch.setattr(manual_catalog, "list_catalog_nodes", nodes)

    sections = await manual_catalog.public_sections(77)
    builtin_sections = await manual_catalog.public_sections(77, include_builtin=True)
    packages = await manual_catalog.static_family_packages("games", "pubg", owner_id=77)

    assert sections == []
    assert builtin_sections[0]["categories"][0]["node_id"] == "family"
    assert packages["variants"][0]["id"] == "manual:variant"
    assert packages["variants"][0]["node_id"] == "variant"
    assert packages["packages"][0]["name"] == "325 UC manual"
    assert packages["packages"][0]["image_url"] == "https://cdn.example.test/pubg-uc.png"
    assert packages["packages"][0]["input_fields"][0]["id"] == "player_id"


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


@pytest.mark.asyncio
async def test_fresh_quote_payload_uses_manual_price_with_optional_api_execution(monkeypatch):
    rows = {row["_id"]: dict(row) for row in _static_tree()}
    rows["product"].update(
        {
            "website_execution_mode": "api",
            "website_source_kind": "game",
            "website_source_key": "game:pubgm:325",
            "website_api_source": {
                "kind": "game",
                "game_id": "pubgm",
                "game_name": "PUBG Mobile",
                "item_id": "325",
                "requires_server": True,
                "provider_offers": [
                    {"provider": "g2bulk", "ref_id": "325", "price": 4.2, "available": True, "fulfillment_mode": "auto_topup"}
                ],
            },
        }
    )

    async def node(node_id, *, reseller_id, catalog_type):
        assert reseller_id == 77
        assert catalog_type == "website_manual"
        return rows.get(str(node_id))

    monkeypatch.setattr(manual_catalog, "get_node", node)

    quote = await manual_catalog.fresh_quote_payload("product", owner_id=77)

    assert quote["execution_mode"] == "api"
    assert quote["sale_price"] == 6.6
    assert quote["provider"] == "g2bulk"
    assert quote["provider_ref_id"] == "325"
    assert quote["game_id"] == "pubgm"
    assert quote["requires_server"] is True
    assert quote["provider_offers"][0]["fulfillment_mode"] == "auto_topup"


@pytest.mark.asyncio
async def test_upsert_static_manual_product_moves_existing_source_to_new_variant(monkeypatch):
    source_key = "gift:ps-global:ps-my-20"
    existing = {
        "_id": "product",
        "parent_id": "old-variant",
        "website_level": "product",
        "node_type": "endpoint",
        "website_source_key": source_key,
    }
    moved = dict(existing, parent_id="target-variant")
    calls = {"move": [], "updates": []}

    async def ensure_path(_owner_id, *, service_key, family_key, family_name, variant_name):
        assert service_key == "store_cards"
        assert family_key == "playstation"
        assert family_name == "PlayStation"
        assert variant_name == "Malaysia"
        return {"variant": {"_id": "target-variant"}}

    async def nodes(_owner_id, *, catalog_type):
        assert catalog_type == "website_manual"
        return [existing]

    async def move(node_id, owner_id, new_parent_id, *, catalog_type):
        calls["move"].append((node_id, owner_id, new_parent_id, catalog_type))
        return moved

    async def update(node_id, owner_id, *, catalog_type, **updates):
        calls["updates"].append((node_id, owner_id, catalog_type, updates))
        return {**moved, **updates}

    monkeypatch.setattr(manual_catalog, "ensure_static_family_path", ensure_path)
    monkeypatch.setattr(manual_catalog, "list_catalog_nodes", nodes)
    monkeypatch.setattr(manual_catalog, "move_node_to_parent", move)
    monkeypatch.setattr(manual_catalog, "update_node_website_metadata", update)

    product, was_created = await manual_catalog.upsert_static_manual_product(
        77,
        service_key="store_cards",
        family_key="playstation",
        family_name="PlayStation",
        variant_name="Malaysia",
        product_name="PlayStation MYR 20",
        price=20.0,
        input_fields=[{"id": "account", "label": "Account", "required": True}],
        source_key=source_key,
        source_kind="gift",
        api_source={"kind": "gift", "variant_name": "Malaysia"},
        import_cache={},
    )

    assert was_created is False
    assert product["parent_id"] == "target-variant"
    assert product["website_variant_key"] == "malaysia"
    assert calls["move"] == [("product", 77, "target-variant", "website_manual")]
    assert calls["updates"][0][3]["website_api_source"]["variant_name"] == "Malaysia"
