import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.proxies.risk_engine import verify_proxy_endpoint


@pytest.mark.asyncio
async def test_verify_proxy_endpoint_missing_host_fails():
    res = await verify_proxy_endpoint("")
    assert res["decision"] == "fail"
    assert res["reason"] == "missing_host"


@pytest.mark.asyncio
async def test_verify_proxy_endpoint_non_global_fails():
    res = await verify_proxy_endpoint("10.10.10.10:1000")
    assert res["decision"] == "fail"
    assert res["reason"] == "non_global_ip"


@pytest.mark.asyncio
async def test_verify_proxy_endpoint_global_passes():
    res = await verify_proxy_endpoint("8.8.8.8:1000")
    assert res["decision"] in {"pass", "gray"}
    assert res["host"] == "8.8.8.8"
