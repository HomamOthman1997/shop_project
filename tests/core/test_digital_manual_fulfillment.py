import pytest

from services.digital_products import manual_fulfillment as mf


def test_select_auto_api_offer_picks_cheapest_non_manual(monkeypatch):
    monkeypatch.setattr(mf, "digital_provider_enabled", lambda provider: True)
    order = {
        "provider_offers_attempted": [
            {"provider": "bittopup", "ref_id": "manual-1", "price": 1.0, "fulfillment_mode": "manual_topup", "source_url": "https://example.test"},
            {"provider": "g2bulk", "ref_id": "auto-expensive", "price": 3.0},
            {"provider": "g2bulk", "ref_id": "auto-cheap", "price": 2.0},
        ]
    }

    offer = mf.select_auto_api_offer(order)

    assert offer["ref_id"] == "auto-cheap"


def test_select_future_offer_picks_cheapest_g2bulk_future(monkeypatch):
    monkeypatch.setattr(mf, "digital_provider_enabled", lambda provider: True)
    order = {
        "provider_offers_attempted": [
            {"provider": "g2bulk", "ref_id": "auto-1", "price": 21.25},
            {"provider": "g2bulk", "ref_id": "future-expensive", "price": 22.0, "source": "future"},
            {"provider": "g2bulk", "ref_id": "future-cheap", "price": 21.63, "source_product_name": "G2Bulk Future"},
        ]
    }

    offer = mf.select_future_offer(order)

    assert offer["ref_id"] == "future-cheap"


@pytest.mark.asyncio
async def test_submit_manual_future_updates_processing_with_delivery(monkeypatch):
    calls = {}
    monkeypatch.setattr(mf, "digital_provider_enabled", lambda provider: True)

    async def fake_update(order_id, details):
        calls.setdefault("updates", []).append((order_id, details))

    async def fake_provider_order(**kwargs):
        calls["provider"] = kwargs
        return {"status": 200, "data": {"order_id": "256358", "code": "PRIVATE-CODE"}}

    monkeypatch.setattr(mf, "update_order_details", fake_update)
    monkeypatch.setattr(mf, "create_provider_gift_order", fake_provider_order)

    order = {
        "_id": "order-1",
        "provider_offers_attempted": [
            {"provider": "g2bulk", "ref_id": "future-1", "price": 21.63, "source": "future"},
        ],
    }
    result = await mf.submit_manual_future(order, actor_id=999)

    assert result["ok"] is True
    assert calls["provider"] == {"provider": "g2bulk", "ref_id": "future-1", "quantity": 1}
    assert calls["updates"][0][1]["manual_fulfillment_status"] == "future_submitting"
    assert calls["updates"][1][1]["manual_fulfillment_status"] == "processing"
    assert calls["updates"][1][1]["provider_order_id"] == "256358"
    assert calls["updates"][1][1]["delivery_lines_private"] == ["PRIVATE-CODE"]
