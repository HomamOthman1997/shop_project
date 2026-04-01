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


@pytest.mark.asyncio
async def test_verify_proxy_endpoint_localhost_fails():
    res = await verify_proxy_endpoint("localhost:8080")
    assert res["decision"] == "fail"
    assert res["reason"] == "localhost_host"


@pytest.mark.asyncio
async def test_verify_proxy_endpoint_internal_suffix_fails():
    res = await verify_proxy_endpoint("proxy01.internal:8080")
    assert res["decision"] == "fail"
    assert res["reason"] == "local_suffix_host"


@pytest.mark.asyncio
async def test_verify_proxy_endpoint_invalid_port_fails():
    res = await verify_proxy_endpoint("8.8.8.8:70000")
    assert res["decision"] == "fail"
    assert res["reason"] == "invalid_port"


@pytest.mark.asyncio
async def test_verify_proxy_endpoint_userinfo_host_fails():
    res = await verify_proxy_endpoint("user@8.8.8.8:1080")
    assert res["decision"] == "fail"
    assert res["reason"] == "userinfo_not_allowed"


@pytest.mark.asyncio
async def test_verify_proxy_endpoint_invalid_hostname_fails():
    res = await verify_proxy_endpoint("bad_host_name.com:1080")
    assert res["decision"] == "fail"
    assert res["reason"] == "invalid_host"
