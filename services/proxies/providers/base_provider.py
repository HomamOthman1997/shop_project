from typing import Any


class BaseProxyProvider:
    async def list_offers(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def rent_offer(self, offer: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def refresh_proxy(self, order_data: dict[str, Any], *, with_check: bool = False) -> dict[str, Any]:
        return {"success": False, "raw": {"title": "NOT_SUPPORTED", "operation": "refresh_proxy"}}

    async def reconfigure_proxy(self, order_data: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
        return {"success": False, "raw": {"title": "NOT_SUPPORTED", "operation": "reconfigure_proxy"}}

    async def renew_proxy(self, order_data: dict[str, Any]) -> dict[str, Any]:
        return {"success": False, "raw": {"title": "NOT_SUPPORTED", "operation": "renew_proxy"}}

    async def report_proxy(self, order_data: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
        payload = {"title": "NOT_SUPPORTED", "operation": "report_proxy"}
        if reason:
            payload["reason"] = reason
        return {"success": False, "raw": payload}
