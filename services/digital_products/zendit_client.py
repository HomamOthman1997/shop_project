from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from config import settings


class ZenditClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_token: str | None = None,
        timeout_sec: float = 30.0,
    ) -> None:
        self.base_url = str(base_url or settings.zendit_api_base or "https://api.zendit.io/v1").rstrip("/")
        self.api_token = str(api_token or settings.zendit_api_token or "").strip()
        self.timeout_sec = float(timeout_sec)

    def configured(self) -> bool:
        return bool(self.base_url and self.api_token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        if not self.configured():
            return 0, {"message": "ZENDIT_NOT_CONFIGURED", "errorCode": "config_error"}

        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.request(
                    method.upper(),
                    f"{self.base_url}/{path.lstrip('/')}",
                    headers=self._headers(),
                    params=params or None,
                    json=payload or None,
                ) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {"raw_text": text}
                    return int(resp.status), data
            except asyncio.TimeoutError:
                return 0, {"message": "ZENDIT_TIMEOUT", "errorCode": "timeout"}
            except Exception as exc:
                return 0, {"message": str(exc), "errorCode": "request_error"}

    async def get_balance(self) -> tuple[int, Any]:
        return await self._request("GET", "/balance")

    async def msisdn_lookup(self, msisdn: str) -> tuple[int, Any]:
        return await self._request("GET", f"/tools/phonenumberlookup/{msisdn}")

    async def list_topup_offers(
        self,
        *,
        limit: int,
        offset: int,
        brand: str | None = None,
        country: str | None = None,
        regions: str | None = None,
        sub_type: str | None = None,
    ) -> tuple[int, Any]:
        params: dict[str, Any] = {"_limit": int(limit), "_offset": int(offset)}
        if brand:
            params["brand"] = str(brand).strip()
        if country:
            params["country"] = str(country).strip().upper()
        if regions:
            params["regions"] = str(regions).strip()
        if sub_type:
            params["subType"] = str(sub_type).strip()
        return await self._request("GET", "/topups/offers", params=params)

    async def get_topup_offer(self, offer_id: str) -> tuple[int, Any]:
        return await self._request("GET", f"/topups/offers/{offer_id}")

    async def purchase_topup(
        self,
        *,
        offer_id: str,
        recipient_phone_number: str,
        transaction_id: str,
        value: dict[str, Any] | None = None,
        sender: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        payload: dict[str, Any] = {
            "offerId": str(offer_id).strip(),
            "recipientPhoneNumber": str(recipient_phone_number).strip(),
            "transactionId": str(transaction_id).strip(),
        }
        if sender:
            payload["sender"] = sender
        if value:
            payload["value"] = value
        return await self._request("POST", "/topups/purchases", payload=payload)

    async def get_topup_transaction(self, transaction_id: str) -> tuple[int, Any]:
        return await self._request("GET", f"/topups/purchases/{transaction_id}")
