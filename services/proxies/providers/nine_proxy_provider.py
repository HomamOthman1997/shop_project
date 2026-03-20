import logging
from typing import Any

from config import settings
from services.numbers.core.session_manager import SessionManager

from .base_provider import BaseProxyProvider

logger = logging.getLogger("proxy_9")


def _as_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


class NineProxyProvider(BaseProxyProvider):
    @property
    def base_url(self) -> str:
        return str(settings.nine_proxy_base_url or "").strip().rstrip("/")

    @property
    def api_key(self) -> str:
        return str(settings.nine_proxy_key or "").strip()

    def _configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    @staticmethod
    def _is_auth_error(status: int, data: Any) -> bool:
        if status in (401, 403):
            return True
        if not isinstance(data, dict):
            return False
        message = str(data.get("message") or "").strip().lower()
        title = str(data.get("title") or "").strip().lower()
        return ("permission denied" in message) or ("auth" in message) or ("auth" in title)

    def _auth_variants(self, params: dict[str, Any]) -> list[tuple[dict[str, str], dict[str, Any]]]:
        # 9Proxy docs use `api-key` header; keep legacy fallbacks for compatibility.
        base_headers = {"Accept": "application/json"}
        return [
            (
                {**base_headers, "api-key": self.api_key},
                dict(params),
            ),
            (
                {
                    **base_headers,
                    "api-key": self.api_key,
                    "api_key": self.api_key,
                    "X-API-KEY": self.api_key,
                    "Authorization": f"Bearer {self.api_key}",
                },
                {**dict(params), "api_key": self.api_key},
            ),
            (
                {
                    **base_headers,
                    "Authorization": f"Bearer {self.api_key}",
                    "X-API-KEY": self.api_key,
                },
                {**dict(params), "api_key": self.api_key},
            ),
        ]

    async def _send_once(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        session = await SessionManager.get_session()
        if method.upper() == "POST":
            async with session.post(url, params=params, headers=headers, json=payload or {}, timeout=20) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = text
                return resp.status, data
        if method.upper() == "PUT":
            async with session.put(url, params=params, headers=headers, json=payload or {}, timeout=20) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = text
                return resp.status, data
        if method.upper() == "DELETE":
            async with session.delete(url, params=params, headers=headers, json=payload or {}, timeout=20) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = text
                return resp.status, data
        async with session.get(url, params=params, headers=headers, timeout=20) as resp:
            text = await resp.text()
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = text
            return resp.status, data

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        if not self._configured():
            return 0, {"title": "NOT_CONFIGURED", "details": "9Proxy settings are missing"}

        url = f"{self.base_url}{path}"
        base_params = dict(params or {})
        last_status = 0
        last_data: Any = {"title": "AUTH_FAILED", "details": "9Proxy auth failed"}
        try:
            for headers, query in self._auth_variants(base_params):
                status, data = await self._send_once(
                    method,
                    url,
                    params=query,
                    headers=headers,
                    payload=payload,
                )
                last_status, last_data = status, data
                if status in (200, 201):
                    return status, data
                if not self._is_auth_error(status, data):
                    return status, data
        except Exception as exc:
            logger.exception("9Proxy request failed: %s %s", method, path)
            return 0, {"title": "REQUEST_ERROR", "details": str(exc)}
        if self._is_auth_error(last_status, last_data):
            logger.warning("9Proxy auth rejected for %s %s (status=%s)", method, path, last_status)
        return last_status, last_data

    @staticmethod
    def _unwrap_result(data: Any) -> Any:
        if isinstance(data, dict):
            if "result" in data:
                return data.get("result")
            if "data" in data:
                return data.get("data")
        return data

    @staticmethod
    def _extract_first_float(src: dict[str, Any], keys: tuple[str, ...]) -> float:
        for key in keys:
            if key in src:
                val = _as_float(src.get(key))
                if val > 0:
                    return val
        return 0.0

    @staticmethod
    def _extract_bytes_to_gb(src: dict[str, Any]) -> float:
        val = NineProxyProvider._extract_first_float(
            src,
            (
                "amount_traffic",
                "traffic_amount",
                "traffic_balance",
                "available_traffic",
                "remaining_traffic",
                "traffic_bytes",
            ),
        )
        if val <= 0:
            return 0.0
        # Most API responses use bytes for traffic quantities.
        return val / 1_000_000_000

    @staticmethod
    def _extract_rows(data: Any) -> list[dict]:
        payload = NineProxyProvider._unwrap_result(data)
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for key in ("items", "list", "rows", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
        return []

    def _build_unlimited_offer(self, src: dict[str, Any]) -> dict[str, Any]:
        available_ips = self._extract_first_float(
            src,
            (
                "number_of_ips",
                "amount_ips",
                "available_ips",
                "remaining_ips",
                "ips",
            ),
        )
        price = self._extract_first_float(
            src,
            (
                "price",
                "unit_price",
                "price_per_ip",
                "rate",
                "cost_per_ip",
            ),
        )
        period = f"{int(available_ips)} IP available" if available_ips > 0 else "Unlimited/IP plan"
        return {
            "provider": "9proxy",
            "offer_id": "unlimited_proxy",
            "title": "Unlimited Proxy",
            "country": "Any",
            "state": "Any",
            "city": "Any",
            "period": period,
            "price": float(price),
            "raw": {
                "api_model": "client_v1_plan",
                "product_type": "unlimited_proxy",
                "source": src,
            },
        }

    def _build_traffic_offer(self, src: dict[str, Any]) -> dict[str, Any]:
        remaining_gb = self._extract_bytes_to_gb(src)
        price = self._extract_first_float(
            src,
            (
                "price",
                "unit_price",
                "price_per_gb",
                "rate",
                "cost_per_gb",
            ),
        )
        period = f"{remaining_gb:.2f} GB available" if remaining_gb > 0 else "Traffic/GB plan"
        return {
            "provider": "9proxy",
            "offer_id": "traffic_proxy_gb",
            "title": "Consumable Proxy (GB)",
            "country": "Any",
            "state": "Any",
            "city": "Any",
            "period": period,
            "price": float(price),
            "raw": {
                "api_model": "client_v1_plan",
                "product_type": "traffic_proxy_gb",
                "source": src,
            },
        }

    async def _offers_from_balance_data(self) -> list[dict[str, Any]]:
        status, data = await self._request("GET", "/client/v1/account/get-balance-data")
        if status not in (200, 201):
            return []

        payload = self._unwrap_result(data)
        if not isinstance(payload, dict):
            return []

        ip_src = {}
        traffic_src = {}

        for key in ("ip_plan_data", "ipPlanData", "ip_plan", "ip"):
            value = payload.get(key)
            if isinstance(value, dict):
                ip_src = value
                break

        for key in ("traffic_plan_data", "trafficPlanData", "traffic_plan", "traffic"):
            value = payload.get(key)
            if isinstance(value, dict):
                traffic_src = value
                break

        offers: list[dict[str, Any]] = []
        if ip_src:
            offers.append(self._build_unlimited_offer(ip_src))
        if traffic_src:
            offers.append(self._build_traffic_offer(traffic_src))
        return offers

    async def _offers_from_proxy_connection_list(self) -> list[dict[str, Any]]:
        status, data = await self._request("GET", "/client/v1/proxy-connection/get-list", params={"limit": 50, "page": 1})
        if status not in (200, 201):
            return []
        rows = self._extract_rows(data)
        if not rows:
            return []

        # Fallback mode: infer plan types from existing connection configs.
        has_ip = False
        has_traffic = False
        for row in rows:
            data_type = str(row.get("data_type") or row.get("plan") or "").lower()
            if data_type in {"1", "ip", "ips", "unlimited"}:
                has_ip = True
            if data_type in {"2", "traffic", "gb", "consumable"}:
                has_traffic = True

        offers: list[dict[str, Any]] = []
        if has_ip:
            offers.append(
                {
                    "provider": "9proxy",
                    "offer_id": "unlimited_proxy",
                    "title": "Unlimited Proxy",
                    "country": "Any",
                    "state": "Any",
                    "city": "Any",
                    "period": "Unlimited/IP plan",
                    "price": 0.0,
                    "raw": {"api_model": "client_v1_plan", "product_type": "unlimited_proxy", "source": rows},
                }
            )
        if has_traffic:
            offers.append(
                {
                    "provider": "9proxy",
                    "offer_id": "traffic_proxy_gb",
                    "title": "Consumable Proxy (GB)",
                    "country": "Any",
                    "state": "Any",
                    "city": "Any",
                    "period": "Traffic/GB plan",
                    "price": 0.0,
                    "raw": {"api_model": "client_v1_plan", "product_type": "traffic_proxy_gb", "source": rows},
                }
            )
        return offers

    async def list_offers(self) -> list[dict[str, Any]]:
        if not self._configured():
            return []

        offers = await self._offers_from_balance_data()
        if offers:
            return offers

        offers = await self._offers_from_proxy_connection_list()
        if offers:
            return offers

        return []

    @staticmethod
    def _extract_credentials(data: Any) -> dict[str, Any]:
        payload = NineProxyProvider._unwrap_result(data)
        if not isinstance(payload, dict):
            return {}

        host = payload.get("host") or payload.get("ip") or payload.get("server") or payload.get("domain")
        port = payload.get("port") or payload.get("start_port")
        endpoint = payload.get("proxy") or payload.get("endpoint")
        if not endpoint and host and port:
            endpoint = f"{host}:{port}"

        return {
            "order_id": payload.get("id") or payload.get("order_id") or payload.get("start_port"),
            "endpoint": endpoint,
            "username": payload.get("username") or payload.get("user_name") or payload.get("user"),
            "password": payload.get("password") or payload.get("use_key") or payload.get("pass"),
            "expires_at": payload.get("expire_at") or payload.get("expiry") or payload.get("expired_at"),
            "start_port": payload.get("start_port"),
        }

    async def _fetch_config_row(self, start_port: int) -> dict[str, Any]:
        params = {"limit": 20, "page": 1, "start_port": start_port}
        status, data = await self._request("GET", "/client/v1/proxy-connection/get-list", params=params)
        if status not in (200, 201):
            return {}
        rows = self._extract_rows(data)
        for row in rows:
            if _as_int(row.get("start_port")) == int(start_port):
                return row
        return rows[0] if rows else {}

    async def rent_offer(self, offer: dict[str, Any]) -> dict[str, Any]:
        if not self._configured():
            return {"success": False, "raw": {"title": "NOT_CONFIGURED"}}

        raw = offer.get("raw") if isinstance(offer.get("raw"), dict) else {}
        product_type = str(raw.get("product_type") or "").lower()
        payload = {
            "quantity": 1,
            "session_type": 1,
        }
        # product hint for APIs that expose both IP and traffic plans.
        if product_type == "unlimited_proxy":
            payload["proxy_type"] = 1
        elif product_type in {"traffic_proxy_gb", "consumption_proxy_gb"}:
            payload["proxy_type"] = 2

        country = str(offer.get("country") or "").strip()
        state = str(offer.get("state") or "").strip()
        city = str(offer.get("city") or "").strip()
        if country and country.lower() != "any":
            payload["country_code"] = country.upper()
        if state and state.lower() != "any":
            payload["state_code"] = state.upper()
        if city and city.lower() != "any":
            payload["city_code"] = city.upper()

        status, data = await self._request("POST", "/client/v1/proxy-connection/create", payload=payload)
        if status not in (200, 201):
            return {"success": False, "raw": data}

        creds = self._extract_credentials(data)
        if not (creds.get("endpoint") or creds.get("username")):
            start_port = _as_int(creds.get("start_port"))
            if start_port > 0:
                row = await self._fetch_config_row(start_port)
                row_creds = self._extract_credentials({"result": row})
                if row_creds:
                    creds = {**creds, **row_creds}

        if creds.get("endpoint") or creds.get("username"):
            return {"success": True, **creds, "raw": data}

        return {"success": False, "raw": data}

    async def refresh_proxy(self, order_data: dict[str, Any], *, with_check: bool = False) -> dict[str, Any]:
        if not self._configured():
            return {"success": False, "raw": {"title": "NOT_CONFIGURED"}}

        start_port = _as_int(order_data.get("proxy_start_port") or order_data.get("proxy_provider_start_port"))
        if start_port <= 0:
            start_port = _as_int(order_data.get("provider_order_id"))
        if start_port <= 0:
            return {"success": False, "raw": {"title": "MISSING_START_PORT"}}

        payload: dict[str, Any] = {"start_port": int(start_port)}
        if with_check:
            # Hint to rotate into short-lived session before verification.
            payload["session_type"] = 1

        status, data = await self._request("PUT", "/client/v1/proxy-connection/update", payload=payload)
        if status not in (200, 201):
            return {"success": False, "raw": data}

        creds = self._extract_credentials(data)
        if not (creds.get("endpoint") or creds.get("username")):
            row = await self._fetch_config_row(start_port)
            row_creds = self._extract_credentials({"result": row})
            if row_creds:
                creds = {**creds, **row_creds}

        if creds.get("endpoint") or creds.get("username"):
            return {"success": True, **creds, "raw": data}
        return {"success": False, "raw": data}
