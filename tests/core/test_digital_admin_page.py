import pytest
from aiohttp.test_utils import make_mocked_request

from services.digital_products import miniapp


@pytest.mark.asyncio
async def test_digital_admin_index_serves_admin_shell():
    response = await miniapp.admin_index(make_mocked_request("GET", "/mini/digital/admin"))

    assert response.status == 200
    assert "Digital Admin" in response.text
    assert "/mini/digital/static/admin.js" in response.text


@pytest.mark.asyncio
async def test_digital_admin_static_file_serves_js():
    response = await miniapp.static_file(make_mocked_request("GET", "/mini/digital/static/admin.js", match_info={"name": "admin.js"}))

    assert response.status == 200
    assert response.content_type == "application/javascript"
    assert b"manual-action" in response.body
