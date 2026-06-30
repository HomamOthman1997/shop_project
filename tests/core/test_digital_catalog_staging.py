import os
import sys

sys.path.insert(0, os.getcwd())

from services.digital_products.catalog_sources import CatalogOffer
from services.digital_products.catalog_sources.base import parse_compare_key
from services.digital_products.catalog_staging_service import (
    ALLOWED_REGIONS,
    build_staging_items,
    staged_api_source,
    staged_product_payload,
)
from services.digital_products.manual_catalog import compute_orphan_products


def _offer(**over):
    base = dict(
        provider="g2bulk",
        ref_id="264",
        source_key="game:pubgm:264",
        service_key="games",
        family_key="pubg",
        family_name="PUBG",
        sub_category="topup",
        region="global",
        compare_key="pubg:global:60:uc",
        unit_kind="uc",
        package_name="60 UC",
        price_usd=0.85,
        requires_server=True,
        input_fields=[{"id": "player_id"}],
    )
    base.update(over)
    return CatalogOffer(**base)


def _by_key(items):
    return {item["staging_key"]: item for item in items}


def test_parse_compare_key():
    assert parse_compare_key("pubg:global:8100:uc") == ("pubg", "global", "8100", "uc")
    assert parse_compare_key("roblox:usa:10:usd") == ("roblox", "usa", "10", "usd")
    assert parse_compare_key("") == ("", "", "", "")


def test_region_filter_keeps_only_usa_eu_uk_global():
    assert ALLOWED_REGIONS == {"global", "usa", "uk", "eu", ""}
    offers = [
        _offer(ref_id="a", source_key="game:pubgm:a", region="global", compare_key="pubg:global:60:uc"),
        _offer(ref_id="b", source_key="game:pubgm:b", region="usa", compare_key="pubg:usa:60:uc"),
        _offer(ref_id="c", source_key="game:pubgm:c", region="eu", compare_key="pubg:eu:60:uc"),
        _offer(ref_id="d", source_key="game:pubgm:d", region="latam", compare_key="pubg:latam:60:uc"),
        _offer(ref_id="e", source_key="game:pubgm:e", region="sea", compare_key="pubg:sea:60:uc"),
        _offer(ref_id="f", source_key="game:pubgm:f", region="ph", compare_key="pubg:ph:60:uc"),
    ]
    items, dropped = build_staging_items(offers)
    by_key = _by_key(items)
    assert dropped == 3
    assert by_key["pubg:global:60:uc"]["status"] == "new"
    assert by_key["pubg:usa:60:uc"]["status"] == "new"
    assert by_key["pubg:eu:60:uc"]["status"] == "new"
    assert by_key["pubg:latam:60:uc"]["status"] == "dropped"
    assert by_key["pubg:latam:60:uc"]["drop_reason"] == "region_latam"
    assert by_key["pubg:sea:60:uc"]["status"] == "dropped"
    assert by_key["pubg:ph:60:uc"]["status"] == "dropped"


def test_merge_same_compare_key_picks_cheapest_and_lists_providers():
    offers = [
        _offer(provider="g2bulk", ref_id="264", source_key="game:pubgm:264", price_usd=0.85),
        _offer(provider="mangerr", ref_id="m1", source_key="mangerr:m1", price_usd=0.80),
    ]
    items, _ = build_staging_items(offers)
    assert len(items) == 1
    item = items[0]
    assert item["suggested_price_usd"] == 0.80
    assert {o["provider"] for o in item["provider_offers"]} == {"g2bulk", "mangerr"}
    # cheapest offer becomes the primary live source_key
    assert item["source_key"] == "mangerr:m1"


def test_sub_types_split_into_separate_items():
    offers = [
        _offer(ref_id="uc", source_key="game:pubgm:uc", sub_category="topup", compare_key="pubg:global:60:uc"),
        _offer(ref_id="pass", source_key="game:pubgm:pass", sub_category="passes", compare_key="pubg:global:1:elitepass", package_name="Elite Pass", price_usd=9.99),
    ]
    items, _ = build_staging_items(offers)
    by_key = _by_key(items)
    assert by_key["pubg:global:60:uc"]["sub_category"] == "topup"
    assert by_key["pubg:global:1:elitepass"]["sub_category"] == "passes"


def test_default_execution_policy_is_api():
    items, _ = build_staging_items([_offer()])
    assert items[0]["execution_policy"] == "api"


def test_offer_without_compare_key_keyed_by_source_key():
    offers = [_offer(compare_key="", region="global", source_key="gift:steam:10")]
    items, _ = build_staging_items(offers)
    assert items[0]["staging_key"] == "gift:steam:10"
    assert items[0]["status"] == "new"


def test_staged_api_source_pulls_game_id_and_lists_all_providers():
    offers = [
        _offer(provider="g2bulk", ref_id="264", source_key="game:pubgm:264", price_usd=0.85),
        _offer(provider="mangerr", ref_id="m1", source_key="mangerr:m1", price_usd=0.80),
    ]
    item = build_staging_items(offers)[0][0]
    api_source = staged_api_source(item)
    assert api_source["game_id"] == "pubgm"          # taken from the g2bulk offer
    assert api_source["item_id"] == "264"
    assert api_source["compare_key"] == "pubg:global:60:uc"
    assert api_source["provider"] == "mangerr"        # cheapest is primary
    assert {o["provider"] for o in api_source["provider_offers"]} == {"g2bulk", "mangerr"}
    assert all(o["compare_key"] == "pubg:global:60:uc" for o in api_source["provider_offers"])


def test_staged_product_payload_maps_fields_for_live_upsert():
    item = build_staging_items([_offer()])[0][0]
    payload = staged_product_payload(item)
    assert payload["service_key"] == "games"
    assert payload["family_key"] == "pubg"
    assert payload["variant_name"] == "topup"        # sub_category becomes the variant (rule 4 split)
    assert payload["product_name"] == "60 UC"
    assert payload["price"] == 0.85
    assert payload["source_kind"] == "game"
    assert payload["execution_mode"] == "api"
    assert payload["api_source"]["compare_key"] == "pubg:global:60:uc"


def test_staged_product_payload_respects_manual_execution_policy():
    item = build_staging_items([_offer()])[0][0]
    item["execution_policy"] = "manual"
    assert staged_product_payload(item)["execution_mode"] == "manual"


# --- fix #1: region named in the package leaks past a 'global' compare_key ---

def test_region_in_package_name_overrides_global_compare_key():
    offers = [
        _offer(
            ref_id="1",
            source_key="game:ff:1",
            family_key="ff",
            family_name="Free Fire",
            region="global",
            compare_key="ff:global:100:diamond",
            package_name="Free Fire Diamonds LATAM",
        )
    ]
    items, dropped = build_staging_items(offers)
    assert dropped == 1
    item = items[0]
    assert item["region"] == "latam"
    assert item["status"] == "dropped"
    assert item["drop_reason"] == "region_latam"


def test_clean_global_package_name_stays_kept():
    items, dropped = build_staging_items([_offer(package_name="60 UC")])
    assert dropped == 0
    assert items[0]["status"] == "new"


# --- fix #2: items with no G2Bulk game source can't smart-route -> manual ---

def test_mangerr_only_item_defaults_to_manual():
    offers = [_offer(provider="mangerr", ref_id="m1", source_key="mangerr:m1", price_usd=0.80)]
    item = build_staging_items(offers)[0][0]
    assert item["execution_policy"] == "manual"


def test_game_sourced_item_defaults_to_api():
    item = build_staging_items([_offer()])[0][0]
    assert item["execution_policy"] == "api"


def test_payload_downgrades_to_manual_when_no_game_id_even_if_flagged_api():
    item = build_staging_items([_offer(provider="mangerr", ref_id="m1", source_key="mangerr:m1")])[0][0]
    item["execution_policy"] = "api"  # force it, e.g. an admin mis-edit
    payload = staged_product_payload(item)
    assert payload["api_source"]["game_id"] == ""
    assert payload["execution_mode"] == "manual"


# --- Phase 4: clean-rebuild cutover orphan detection ---

def _product(source_key, *, section="games", hidden=False, name="P"):
    return {
        "website_level": "product",
        "name": name,
        "website_source_key": source_key,
        "website_section_key": section,
        "website_hidden": hidden,
    }


def test_cutover_hides_only_unkept_sourced_products_in_scope():
    nodes = [
        _product("game:pubgm:264", name="keep me"),       # in keep set -> stay
        _product("game:pubgm:old", name="stale region"),  # sourced, not kept -> hide
        _product("", name="admin hand-made"),             # no source key -> never touch
        {"website_level": "family", "name": "PUBG"},       # not a product -> ignored
    ]
    orphans = compute_orphan_products(nodes, keep_source_keys={"game:pubgm:264"}, services={"games"})
    assert [o["name"] for o in orphans] == ["stale region"]


def test_cutover_leaves_untouched_sections_alone():
    nodes = [
        _product("game:pubgm:old", section="games", name="game orphan"),
        _product("manual:syr:1", section="syrian_services", name="syrian product"),
    ]
    # Only the games section was imported/approved, so the cutover scope is {games}.
    orphans = compute_orphan_products(nodes, keep_source_keys=set(), services={"games"})
    assert [o["name"] for o in orphans] == ["game orphan"]


def test_cutover_skips_already_hidden_products():
    nodes = [_product("game:pubgm:old", hidden=True, name="already hidden")]
    orphans = compute_orphan_products(nodes, keep_source_keys=set(), services={"games"})
    assert orphans == []


def test_gift_offer_game_currency_joins_topup_not_region():
    # A game-currency voucher (PUBG UC) must land in the game's "topup" bucket, not a
    # region bucket — so the customer doesn't see UC split across topup + Global. The
    # route (future voucher vs auto) is backend-only, merged via compare_key.
    from services.digital_products.catalog_sources.g2bulk_source import _gift_offer

    item = {"id": "v1", "name": "60 Uc Voucher", "category_id": "c1", "compare_key": "pubg:global:60:uc"}
    price_fn = lambda _it: 1.5
    fields_fn = lambda _it: []
    region_variant_fn = lambda **_kw: "Global"

    game = _gift_offer(item, "games", "pubg", "PUBG Mobile", "Global", fields_fn, price_fn, region_variant_fn)
    assert game.sub_category == "topup"

    card = _gift_offer(item, "gift-cards", "steam", "Steam", "Global", fields_fn, price_fn, region_variant_fn)
    assert card.sub_category == "Global"


def test_compare_key_does_not_treat_subscriptions_or_packs_as_currency():
    # "Prime (1 Month)" / "Weekly Deal Pack 1" must NOT become "1 uc" and collide.
    from services.digital_products.fulfillment_rules import offer_compare_key

    ck = lambda n: offer_compare_key(family_key="pubg", region="global", offer_name=n, default_unit="uc")
    assert ck("Prime (1 Month)") == ""
    assert ck("Prime (3 Months)") == ""
    assert ck("Weekly Deal Pack 1") == ""
    assert ck("Royale Pass") == ""
    # Real currency amounts still resolve correctly.
    assert ck("60") == "pubg:global:60:uc"
    assert ck("8100 UC") == "pubg:global:8100:uc"
    assert ck("60 Uc Voucher") == "pubg:global:60:uc"


def test_build_staging_items_applies_margin_keeps_cost():
    # Margin turns the cheapest provider COST into the suggested SELL price; the raw
    # cost is preserved so the no-loss guard still compares against the true cost.
    offers = [
        _offer(provider="g2bulk", ref_id="264", source_key="game:pubgm:264", price_usd=1.00),
        _offer(provider="mangerr", ref_id="m1", source_key="mangerr:m1", price_usd=0.80),
    ]
    items, _ = build_staging_items(offers, margin_factor=1.25)  # +25%
    assert items[0]["cost_price_usd"] == 0.80
    assert items[0]["suggested_price_usd"] == 1.0  # 0.80 * 1.25
    # default (no margin) is unchanged
    plain, _ = build_staging_items(offers)
    assert plain[0]["suggested_price_usd"] == 0.80


def test_compare_key_g_coins_distinct_from_uc():
    from services.digital_products.fulfillment_rules import offer_compare_key

    ck = lambda n: offer_compare_key(family_key="pubg", region="global", offer_name=n, default_unit="uc")
    assert ck("PUBG G Coins - 100") == "pubg:global:100:gcoin"
    assert ck("100") == "pubg:global:100:uc"  # bare amount still UC
