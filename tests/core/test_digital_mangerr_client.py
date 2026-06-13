import asyncio

from services.digital_products.mangerr_client import MangerrClient


def test_mangerr_get_products_supports_filters(monkeypatch):
    client = MangerrClient()
    calls = []

    async def fake_request(method, path, *, params=None):
        calls.append((method, path, params))
        return 200, [{"id": 365, "name": "UC 60"}]

    monkeypatch.setattr(client, "_request", fake_request)

    rows = asyncio.run(client.get_products([365, "366"], minimal=True))

    assert rows == [{"id": 365, "name": "UC 60"}]
    assert calls == [("GET", "/client/api/products", {"products_id": "365,366", "base": 1})]


def test_mangerr_products_response_preserves_provider_error(monkeypatch):
    client = MangerrClient()

    async def fake_request(method, path, *, params=None):
        return 526, {"title": "Invalid SSL certificate"}

    monkeypatch.setattr(client, "_request", fake_request)

    status, body = asyncio.run(client.get_products_response())

    assert status == 526
    assert body["title"] == "Invalid SSL certificate"


def test_mangerr_create_order_requires_uuid(monkeypatch):
    client = MangerrClient()
    called = False

    async def fake_request(*args, **kwargs):
        nonlocal called
        called = True
        return 200, {}

    monkeypatch.setattr(client, "_request", fake_request)

    result = asyncio.run(client.create_order(product_id=365, order_uuid=""))

    assert result["data"]["msg"] == "MISSING_ORDER_UUID"
    assert called is False


def test_mangerr_check_orders_uses_uuid_flag(monkeypatch):
    client = MangerrClient()
    calls = []

    async def fake_request(method, path, *, params=None):
        calls.append((method, path, params))
        return 200, {"status": "OK"}

    monkeypatch.setattr(client, "_request", fake_request)

    result = asyncio.run(client.check_orders(["order-1", "order-2"], by_uuid=True))

    assert result["status"] == 200
    assert calls == [("GET", "/client/api/check", {"orders": "[order-1,order-2]", "uuid": 1})]
