import pytest
from aiohttp.test_utils import make_mocked_request

from services.digital_products import miniapp


@pytest.mark.asyncio
async def test_digital_user_index_serves_api_driven_shell():
    response = await miniapp.index(make_mocked_request("GET", "/mini/digital"))

    assert response.status == 200
    assert "Digital Services" in response.text
    assert "/mini/digital/static/app.js" in response.text
    assert "data-tab=\"store\"" in response.text
    assert "data-tab=\"orders\"" in response.text
    assert "data-tab=\"account\"" in response.text


@pytest.mark.asyncio
async def test_digital_user_app_uses_versioned_digital_api_only_for_purchases():
    response = await miniapp.static_file(make_mocked_request("GET", "/mini/digital/static/app.js", match_info={"name": "app.js"}))
    source = response.body.decode("utf-8")

    assert response.status == 200
    assert "/api/v1/digital/catalog" in source
    assert "/mini/digital/api/catalog" in source
    assert "service_tree" in source
    assert "featured_collections" in source
    assert "/api/v1/digital/quotes" in source
    assert "/api/v1/digital/orders" in source
    assert "/api/v1/digital/account" in source
    assert "/mini/digital/api/selection" not in source
    assert "sendData" not in source
