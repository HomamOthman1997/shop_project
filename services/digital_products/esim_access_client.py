from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import uuid4

import aiohttp

from config import settings


class EsimAccessClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        access_code: str | None = None,
        secret_key: str | None = None,
        timeout_sec: float = 20.0,
    ) -> None:
        self.base_url = str(base_url or settings.esim_access_api_base).rstrip("/")
        self.access_code = str(access_code or settings.esim_access_code or "").strip()
        self.secret_key = str(secret_key or settings.esim_access_secret_key or "").strip()
        self.timeout_sec = float(timeout_sec)

    def configured(self) -> bool:
        return bool(self.access_code and self.secret_key)

    def _request_headers(self, body_text: str) -> dict[str, str]:
        timestamp = str(int(__import__("time").time() * 1000))
        request_id = str(uuid4())
        sign_str = f"{timestamp}{request_id}{self.access_code}{body_text}"
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().lower()
        return {
            "Content-Type": "application/json",
            "RT-AccessCode": self.access_code,
            "RT-RequestID": request_id,
            "RT-Timestamp": timestamp,
            "RT-Signature": signature,
        }

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("ESIM_ACCESS_NOT_CONFIGURED")
        body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self.base_url}/{path.lstrip('/')}",
                data=body_text.encode("utf-8"),
                headers=self._request_headers(body_text),
            ) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text) if text else {}
                except Exception:
                    data = {"success": False, "errorMessage": text or f"HTTP {resp.status}"}
                data.setdefault("http_status", resp.status)
                return data

    async def list_packages(
        self,
        *,
        location_code: str = "",
        package_type: str = "BASE",
        package_code: str = "",
        slug: str = "",
        iccid: str = "",
        data_type: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "locationCode": str(location_code or ""),
            "type": str(package_type or "BASE"),
            "packageCode": str(package_code or ""),
            "slug": str(slug or ""),
            "iccid": str(iccid or ""),
        }
        if data_type is not None:
            payload["dataType"] = int(data_type)
        return await self._post("/package/list", payload)

    async def list_locations(self) -> dict[str, Any]:
        return await self._post("/location/list", {})

    async def order_profiles(
        self,
        *,
        transaction_id: str,
        amount: int,
        package_info_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "transactionId": str(transaction_id),
            "amount": int(amount),
            "packageInfoList": package_info_list,
        }
        return await self._post("/esim/order", payload)

    async def query_profiles(
        self,
        *,
        order_no: str = "",
        iccid: str = "",
        page_num: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        payload = {
            "orderNo": str(order_no or ""),
            "iccid": str(iccid or ""),
            "pager": {"pageNum": int(page_num), "pageSize": int(page_size)},
        }
        return await self._post("/esim/query", payload)
