import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.digital_products import manual_fulfillment, smart_routing

COMPARE_KEY = "pubg:global:8100:uc"


def _quote(**over):
    base = {
        "kind": "manual",
        "source_kind": "game",
        "game_id": "pubgm",
        "game_name": "PUBG Mobile",
        "item_name": "8100 UC",
        "compare_key": COMPARE_KEY,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_smart_routing_applicable_requires_game_and_compare_key():
    assert smart_routing.smart_routing_applicable(_quote()) is True
    assert smart_routing.smart_routing_applicable(_quote(source_kind="gift")) is False
    assert smart_routing.smart_routing_applicable(_quote(game_id="")) is False
    assert smart_routing.smart_routing_applicable(
        {"source_kind": "game", "game_id": "x", "compare_key": "", "item_name": ""}
    ) is False


def test_quote_like_from_order_round_trips_identifiers():
    order = {
        "website_source_kind": "game",
        "game_id": "pubgm",
        "manual_game_name": "PUBG Mobile",
        "manual_product_name": "PUBG",
        "manual_item_name": "8100 UC",
        "manual_variant_name": "Global",
        "compare_key": COMPARE_KEY,
    }
    q = smart_routing.quote_like_from_order(order)
    assert q["source_kind"] == "game"
    assert q["game_id"] == "pubgm"
    assert q["compare_key"] == COMPARE_KEY
    assert smart_routing.smart_routing_applicable(q) is True


def test_profitable_candidates_filters_unprofitable_and_sorts_cheapest_first():
    plan = {
        "candidates": [
            {"provider": "g2bulk", "route": "auto_api", "ref_id": "a", "cost_price": 87.0},
            {"provider": "g2bulk", "route": "auto_api", "ref_id": "b", "cost_price": 82.5},
            {"provider": "mangerr", "route": "auto_api", "ref_id": "c", "cost_price": 90.0},  # > sale
            {"provider": "g2bulk", "route": "future", "ref_id": "d", "cost_price": 0.0},  # invalid cost
        ]
    }
    rows = smart_routing.profitable_candidates(plan, sale_price=88.0)
    assert [r["ref_id"] for r in rows] == ["b", "a"]


# ---------------------------------------------------------------------------
# resolve_smart_game_routing — merge across providers, dedupe, sort
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_merges_dedupes_and_sorts_pubg_offers(monkeypatch):
    async def fake_topups(game_id, *, force=False):
        assert game_id == "pubgm"
        return [
            {
                "compare_key": COMPARE_KEY,
                "name": "8100 UC",
                "catalogue_name": "PUBG 8100",
                "provider_offers": [
                    {"provider": "g2bulk", "ref_id": "g2-auto-cheap", "price": 82.5, "available": True},
                    {"provider": "g2bulk", "ref_id": "g2-auto-promo", "price": 87.0, "available": True},
                    {"provider": "g2bulk", "ref_id": "g2-future", "price": 80.0, "available": True, "source": "future"},
                    # Duplicate of g2-auto-cheap at a worse price -> deduped away.
                    {"provider": "g2bulk", "ref_id": "g2-auto-cheap", "price": 99.0, "available": True},
                ],
            },
            {
                "compare_key": "other:key",
                "provider_offers": [{"provider": "g2bulk", "ref_id": "x", "price": 1.0, "available": True}],
            },
        ]

    class FakeMangerr:
        def configured(self):
            return True

        async def get_products_response(self):
            return 200, [
                {"id": "mg-1", "price": 81.0, "available": True, "name": "8100 UC", "category_name": "PUBG", "params": []},
                {"id": "mg-2", "price": 50.0, "available": True, "name": "other", "category_name": "PUBG", "params": []},
            ]

    def fake_product_compare_key(*, category_name, product_name):
        return COMPARE_KEY if product_name == "8100 UC" else "nope"

    monkeypatch.setattr(smart_routing, "get_game_topups", fake_topups)
    monkeypatch.setattr(smart_routing, "MangerrClient", FakeMangerr)
    monkeypatch.setattr(smart_routing, "_product_compare_key", fake_product_compare_key)

    plan = await smart_routing.resolve_smart_game_routing(_quote(), sale_price=90.0)

    assert plan["enabled"] is True
    cands = plan["candidates"]
    refs = {(c["provider"], c["route"], c["ref_id"], c["cost_price"]) for c in cands}
    assert ("g2bulk", "future", "g2-future", 80.0) in refs
    assert ("mangerr", "auto_api", "mg-1", 81.0) in refs
    assert ("g2bulk", "auto_api", "g2-auto-cheap", 82.5) in refs
    assert ("g2bulk", "auto_api", "g2-auto-promo", 87.0) in refs
    # The g2bulk promo/base duplicate (same family, two prices) is collapsed to the cheapest.
    assert sum(1 for c in cands if c["ref_id"] == "g2-auto-cheap") == 1
    # Cheapest-first ordering.
    costs = [c["cost_price"] for c in cands]
    assert costs == sorted(costs)
    assert costs[0] == 80.0


@pytest.mark.asyncio
async def test_resolve_disabled_when_not_applicable():
    plan = await smart_routing.resolve_smart_game_routing({"source_kind": "gift"}, sale_price=10.0)
    assert plan["enabled"] is False
    assert plan["candidates"] == []


# ---------------------------------------------------------------------------
# execute_smart_game_routing — try cheapest first, fallback, no-loss guard
# ---------------------------------------------------------------------------

def _order(**over):
    base = {
        "_id": "order-1",
        "retail_amount": 90.0,
        "sale_price": 90.0,
        "game_id": "pubgm",
        "player_id": "PLAYER123",
        "server_id": "",
        "manual_item_name": "8100 UC",
        "routing_candidates": [],
    }
    base.update(over)
    return base


def _auto_cand(ref, cost):
    return {
        "provider": "g2bulk",
        "route": "auto_api",
        "ref_id": ref,
        "cost_price": cost,
        "game_id": "pubgm",
        "compare_key": COMPARE_KEY,
    }


def _ok_resp(order_id="EXT1"):
    return {"status": 200, "data": {"order_id": order_id, "success": True}}


def _fail_resp(msg="boom"):
    return {"status": 200, "data": {"success": False, "error": msg}}


@pytest.fixture
def _patch_updates(monkeypatch):
    async def noop(*a, **k):
        return None

    monkeypatch.setattr(manual_fulfillment, "update_order_details", noop)


@pytest.mark.asyncio
async def test_execute_picks_cheapest_auto_and_stops_on_success(monkeypatch, _patch_updates):
    calls = []

    async def fake_game_order(**kw):
        calls.append(kw["ref_id"])
        return _ok_resp("EXT-CHEAP")

    monkeypatch.setattr(manual_fulfillment, "create_provider_game_order", fake_game_order)
    order = _order(routing_candidates=[_auto_cand("cheap", 82.5), _auto_cand("pricey", 87.0)])

    result = await manual_fulfillment.execute_smart_game_routing(order, actor_id=1)

    assert result["ok"] is True
    assert result["route"] == "auto_api"
    assert result["provider_order_id"] == "EXT-CHEAP"
    assert calls == ["cheap"]


@pytest.mark.asyncio
async def test_execute_falls_back_to_next_when_cheapest_fails(monkeypatch, _patch_updates):
    calls = []

    async def fake_game_order(**kw):
        calls.append(kw["ref_id"])
        return _fail_resp() if kw["ref_id"] == "cheap" else _ok_resp("EXT-NEXT")

    monkeypatch.setattr(manual_fulfillment, "create_provider_game_order", fake_game_order)
    order = _order(routing_candidates=[_auto_cand("cheap", 82.5), _auto_cand("pricey", 87.0)])

    result = await manual_fulfillment.execute_smart_game_routing(order, actor_id=1)

    assert result["ok"] is True
    assert calls == ["cheap", "pricey"]
    assert result["provider_order_id"] == "EXT-NEXT"
    assert [a["status"] for a in result["attempts"]] == ["failed", "success"]


@pytest.mark.asyncio
async def test_execute_skips_candidate_that_would_lose_money(monkeypatch, _patch_updates):
    calls = []

    async def fake_game_order(**kw):
        calls.append(kw["ref_id"])
        return _ok_resp()

    monkeypatch.setattr(manual_fulfillment, "create_provider_game_order", fake_game_order)
    # Sale price is 90; the 95 candidate must be skipped before the profitable 80 one runs.
    order = _order(routing_candidates=[_auto_cand("toopricey", 95.0), _auto_cand("good", 80.0)])

    result = await manual_fulfillment.execute_smart_game_routing(order, actor_id=1)

    assert result["ok"] is True
    assert calls == ["good"]
    assert result["attempts"][0]["status"] == "skipped_unprofitable"


@pytest.mark.asyncio
async def test_execute_all_failures_route_to_manual_review(monkeypatch, _patch_updates):
    async def fake_game_order(**kw):
        return _fail_resp("nope")

    monkeypatch.setattr(manual_fulfillment, "create_provider_game_order", fake_game_order)
    order = _order(routing_candidates=[_auto_cand("a", 80.0), _auto_cand("b", 85.0)])

    result = await manual_fulfillment.execute_smart_game_routing(order, actor_id=1)

    assert result["ok"] is False
    assert result["route"] == manual_fulfillment.ROUTE_MANUAL_REVIEW
    assert result["code"] == "smart_route_manual_review"


@pytest.mark.asyncio
async def test_execute_without_candidates_routes_to_manual_review(_patch_updates):
    result = await manual_fulfillment.execute_smart_game_routing(_order(routing_candidates=[]), actor_id=1)
    assert result["ok"] is False
    assert result["route"] == manual_fulfillment.ROUTE_MANUAL_REVIEW


@pytest.mark.asyncio
async def test_execute_future_route_buys_voucher_for_admin(monkeypatch, _patch_updates):
    seen = {}

    async def fake_gift_order(*, provider, ref_id, quantity=1):
        seen["provider"] = provider
        seen["ref_id"] = ref_id
        seen["quantity"] = quantity
        return {"status": 200, "data": {"order_id": "FUT1", "code": "VOUCHER-XYZ"}}

    monkeypatch.setattr(manual_fulfillment, "create_provider_gift_order", fake_gift_order)
    cand = {
        "provider": "g2bulk",
        "route": "future",
        "ref_id": "fut-1",
        "cost_price": 80.0,
        "compare_key": COMPARE_KEY,
        "quantity": 1,
    }
    order = _order(routing_candidates=[cand])

    result = await manual_fulfillment.execute_smart_game_routing(order, actor_id=1)

    assert result["ok"] is True
    assert result["route"] == manual_fulfillment.ROUTE_FUTURE
    assert seen == {"provider": "g2bulk", "ref_id": "fut-1", "quantity": 1}
    assert "VOUCHER-XYZ" in result["delivery_lines_private"]
