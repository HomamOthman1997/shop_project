from __future__ import annotations

import logging
from typing import Any

from config import settings
from services.numbers.core.session_manager import SessionManager

logger = logging.getLogger("za3em")


class Za3emClient:
    def __init__(self) -> None:
        self.base_url = str(getattr(settings, "za3em_base_url", "") or "").strip().rstrip("/")
        self.api_token = str(getattr(settings, "za3em_api_token", "") or "").strip()

    def configured(self) -> bool:
        return bool(self.base_url and self.api_token)

    async def _session(self):
        return await SessionManager.get_session()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        if not self.configured():
            return 0, {"status": "ERROR", "msg": "ZA3EM_NOT_CONFIGURED"}

        session = await self._session()
        headers = {
            "Accept": "application/json",
            "api-token": self.api_token,
        }
        url = f"{self.base_url}/{str(path or '').lstrip('/')}"
        try:
            async with session.request(
                method.upper(),
                url,
                headers=headers,
                params=params or None,
                timeout=30,
            ) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = {"raw_text": text}
                return int(resp.status), data
        except Exception as exc:
            logger.exception("Za3em request failed %s %s: %s", method, path, exc)
            return 0, {"status": "ERROR", "msg": str(exc)}

    async def get_profile(self) -> tuple[int, Any]:
        return await self._request("GET", "/client/api/profile")

    async def get_products(self) -> list[dict[str, Any]]:
        status, data = await self._request("GET", "/client/api/products")
        if status != 200 or not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    async def create_order(
        self,
        *,
        product_id: int | str,
        quantity: int = 1,
        order_uuid: str,
        player_id: str | None = None,
        server_id: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pid = str(product_id or "").strip()
        ouid = str(order_uuid or "").strip()
        if not pid:
            return {"status": 0, "data": {"status": "ERROR", "msg": "INVALID_PRODUCT_ID"}}
        if not ouid:
            return {"status": 0, "data": {"status": "ERROR", "msg": "MISSING_ORDER_UUID"}}
        params: dict[str, Any] = {
            "qty": max(1, int(quantity or 1)),
            "order_uuid": ouid,
        }
        if str(player_id or "").strip():
            params["playerId"] = str(player_id).strip()
        if str(server_id or "").strip():
            params["serverId"] = str(server_id).strip()
        if isinstance(extra_params, dict):
            for key, value in extra_params.items():
                k = str(key or "").strip()
                if not k:
                    continue
                params[k] = value
        status, data = await self._request("GET", f"/client/api/newOrder/{pid}/params", params=params)
        return {"status": status, "data": data}

    async def check_orders(self, orders: list[str], *, by_uuid: bool = False) -> dict[str, Any]:
        cleaned = [str(item or "").strip() for item in orders if str(item or "").strip()]
        if not cleaned:
            return {"status": 0, "data": {"status": "ERROR", "msg": "MISSING_ORDERS"}}
        params: dict[str, Any] = {"orders": "[" + ",".join(cleaned) + "]"}
        if by_uuid:
            params["uuid"] = 1
        status, data = await self._request("GET", "/client/api/check", params=params)
        return {"status": status, "data": data}
