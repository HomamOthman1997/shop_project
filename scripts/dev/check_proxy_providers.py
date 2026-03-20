import asyncio
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from services.numbers.core.session_manager import SessionManager
from services.proxies.manager import get_proxy_catalog
from services.proxies.providers.fourg_proxy_provider import FourGProxyProvider
from services.proxies.providers.nine_proxy_provider import NineProxyProvider


async def main() -> None:
    nine = NineProxyProvider()
    fourg = FourGProxyProvider()

    print("== Proxy Provider Health ==")
    print(f"9Proxy configured: {nine._configured()} | base: {nine.base_url}")
    status, payload = await nine._request("GET", "/client/v1/account/get-info")
    message = payload.get("message") if isinstance(payload, dict) else str(payload)
    print(f"9Proxy account/get-info: {status} | {message}")

    offers_9 = await nine.list_offers()
    print(f"9Proxy offers: {len(offers_9)}")

    print(f"4G configured: {fourg._configured()} | base: {fourg.base_url}")
    offers_4g = await fourg.list_offers()
    print(f"4G offers: {len(offers_4g)}")
    if offers_4g:
        sample = offers_4g[0]
        print("4G sample:", json.dumps(sample, ensure_ascii=False)[:400])

    catalog = await get_proxy_catalog()
    by_provider: dict[str, int] = {}
    for offer in catalog:
        code = str(offer.get("provider") or "")
        by_provider[code] = by_provider.get(code, 0) + 1
    print(f"Catalog offers: {len(catalog)} | split: {by_provider}")

    await SessionManager.close()


if __name__ == "__main__":
    asyncio.run(main())
