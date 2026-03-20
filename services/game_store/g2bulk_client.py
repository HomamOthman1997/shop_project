from __future__ import annotations

import logging
from typing import Any

from config import settings
from services.numbers.core.session_manager import SessionManager

logger = logging.getLogger("g2bulk")


class G2BulkClient:
    """Thin async wrapper over G2Bulk API v2.

    Notes:
    - API details are based on provider docs available at implementation time.
    - Endpoints and payload shapes are normalized in a tolerant way to avoid hard-fail
      if provider slightly changes the response schema.
    """

    def __init__(self) -> None:
        self.base_url = str(getattr(settings, "g2bulk_base_url", "") or "").strip().rstrip("/")
        self.api_key = str(getattr(settings, "g2bulk_api_key", "") or "").strip()

    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def _session(self):
        return await SessionManager.get_session()

    async def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
        if not self.configured():
            return 0, {"success": False, "error": "G2BULK_NOT_CONFIGURED"}

        session = await self._session()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
        }
        url = f"{self.base_url}{path}"
        try:
            if method.upper() == "GET":
                async with session.get(url, headers=headers, timeout=30) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {"raw_text": text}
                    return int(resp.status), data
            async with session.post(url, headers=headers, json=payload or {}, timeout=30) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = {"raw_text": text}
                return int(resp.status), data
        except Exception as exc:
            logger.exception("G2Bulk request failed %s %s: %s", method, path, exc)
            return 0, {"success": False, "error": str(exc)}

    @staticmethod
    def _extract_list(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("data", "result", "results", "categories", "products", "games", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
        return []

    async def get_categories(self) -> list[dict[str, Any]]:
        # v1 public endpoint
        status, data = await self._request("GET", "/v1/category")
        if status == 200 and isinstance(data, dict):
            rows = data.get("categories")
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
        # legacy fallback
        status, data = await self._request("POST", "/api/v2/user/category/get_categories", payload={})
        if status != 200:
            return []
        return self._extract_list(data)

    async def get_products(self) -> list[dict[str, Any]]:
        # v1 public endpoint
        status, data = await self._request("GET", "/v1/products")
        if status == 200 and isinstance(data, dict):
            rows = data.get("products")
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
        # legacy fallback
        status, data = await self._request("POST", "/api/v2/user/product/get_buyer_products", payload={})
        if status != 200:
            return []
        return self._extract_list(data)

    async def get_games(self) -> list[dict[str, Any]]:
        # v1 public endpoint
        status, data = await self._request("GET", "/v1/games")
        if status == 200 and isinstance(data, dict):
            rows = data.get("games")
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
        # legacy fallback
        status, data = await self._request("POST", "/api/v2/user/game/get_game_names", payload={})
        if status != 200:
            return []
        return self._extract_list(data)

    async def get_game_catalogue(self, game_id: int | str) -> list[dict[str, Any]]:
        # v1 endpoint expects game code
        gcode = str(game_id or "").strip()
        if not gcode:
            return []
        status, data = await self._request("GET", f"/v1/games/{gcode}/catalogue")
        if status == 200 and isinstance(data, dict):
            rows = data.get("catalogues")
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
        # legacy fallback
        try:
            gid = int(game_id)
        except Exception:
            return []
        payload = {"game_id": gid}
        status, data = await self._request("POST", "/api/v2/user/game/get_game_products", payload=payload)
        if status != 200:
            return []
        return self._extract_list(data)

    async def create_voucher_order(self, product_id: int | str, quantity: int = 1) -> dict[str, Any]:
        try:
            pid = int(product_id)
        except Exception:
            return {"status": 0, "data": {"success": False, "error": "INVALID_PRODUCT_ID"}}
        payload = {"quantity": int(quantity)}
        status, data = await self._request("POST", f"/v1/products/{pid}/purchase", payload=payload)
        if status == 404:
            # legacy fallback
            payload = {"product_id": pid, "quantity": int(quantity)}
            status, data = await self._request("POST", "/api/v2/user/order/create_order", payload=payload)
        return {"status": status, "data": data}

    async def create_topup_order(
        self,
        product_id: int | str,
        player_id: str,
        server_id: str | None = None,
        quantity: int = 1,
        game_code: str | None = None,
        catalogue_name: str | None = None,
    ) -> dict[str, Any]:
        payload_v1: dict[str, Any] = {
            "catalogue_name": str(catalogue_name or "").strip(),
            "player_id": str(player_id).strip(),
        }
        if server_id is not None and str(server_id).strip():
            payload_v1["server_id"] = str(server_id).strip()
        gcode = str(game_code or "").strip()
        if gcode and payload_v1.get("catalogue_name"):
            status, data = await self._request("POST", f"/v1/games/{gcode}/order", payload=payload_v1)
            if status != 404:
                return {"status": status, "data": data}

        # legacy fallback
        try:
            pid = int(product_id)
        except Exception:
            return {"status": 0, "data": {"success": False, "error": "INVALID_PRODUCT_ID"}}
        payload_legacy: dict[str, Any] = {
            "product_id": pid,
            "player_id": str(player_id).strip(),
            "quantity": int(quantity),
        }
        if server_id is not None and str(server_id).strip():
            payload_legacy["server_id"] = str(server_id).strip()
        status, data = await self._request("POST", "/api/v2/user/order/create_game_order", payload=payload_legacy)
        return {"status": status, "data": data}

    async def get_order_status(self, order_id: int | str) -> dict[str, Any]:
        try:
            oid = int(order_id)
        except Exception:
            return {"status": 0, "data": {"success": False, "error": "INVALID_ORDER_ID"}}
        payload = {"order_id": oid}
        status, data = await self._request("POST", "/user/order/get_order_status", payload=payload)
        return {"status": status, "data": data}
