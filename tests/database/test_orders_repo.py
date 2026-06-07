from bson import ObjectId
import pytest

from database import orders_repo


class _UpdateResult:
    def __init__(self, matched_count: int):
        self.matched_count = matched_count


class _OrdersCollection:
    def __init__(self, order: dict):
        self.order = dict(order)
        self.update_query = None
        self.update_patch = None

    async def update_one(self, query, patch):
        self.update_query = query
        self.update_patch = patch
        if query.get("_id") != self.order.get("_id"):
            return _UpdateResult(0)
        if query.get("number_mode") != self.order.get("number_mode"):
            return _UpdateResult(0)
        if query.get("temp_refund_support_review_required") != self.order.get("temp_refund_support_review_required"):
            return _UpdateResult(0)
        self.order.update(patch.get("$set") or {})
        return _UpdateResult(1)

    async def find_one(self, query):
        if query.get("_id") == self.order.get("_id"):
            return dict(self.order)
        return None


class _Db:
    def __init__(self, order: dict):
        self.orders = _OrdersCollection(order)


@pytest.mark.asyncio
async def test_resolve_temp_refund_review_does_not_require_numbers_api_source(monkeypatch):
    order_id = ObjectId()
    fake_db = _Db(
        {
            "_id": order_id,
            "source": "telegram_bot",
            "number_mode": "temp",
            "temp_refund_support_review_required": True,
            "temp_refund_support_review_status": "open",
        }
    )
    monkeypatch.setattr(orders_repo, "db", fake_db)

    order = await orders_repo.resolve_api_temp_refund_support_review(
        order_id=str(order_id),
        actor_user_id=900000000001,
        resolution="Checked manually",
        notes="Provider cancel failed",
        reseller_id=None,
    )

    assert order is not None
    assert order["temp_refund_support_review_status"] == "resolved"
    assert fake_db.orders.update_query == {
        "_id": order_id,
        "number_mode": "temp",
        "temp_refund_support_review_required": True,
    }
