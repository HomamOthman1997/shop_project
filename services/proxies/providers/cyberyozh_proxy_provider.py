from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST

from .base_provider import BaseProxyProvider

logger = logging.getLogger("proxy_cyberyozh")

_ISO_TO_COUNTRY = {
    str(item.get("iso") or "").strip().upper(): str(item.get("name") or "").strip()
    for item in COUNTRIES_LIST
    if str(item.get("iso") or "").strip() and str(item.get("name") or "").strip()
}


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _duration_label(days: int) -> str:
    if days == 30:
        return "1 Month"
    if days == 14:
        return "2 Week"
    if days == 7:
        return "1 Week"
    if days == 1:
        return "1 Day"
    return f"{days} Day"


def _country_name_from_iso(iso_code: str) -> str:
    code = str(iso_code or "").strip().upper()
    return _ISO_TO_COUNTRY.get(code, code or "Any")


def _flatten_credential_strings(payload: Any) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for value in payload.values():
            values.extend(_flatten_credential_strings(value))
        return values
    if isinstance(payload, list):
        for value in payload:
            values.extend(_flatten_credential_strings(value))
        return values
    if isinstance(payload, str):
        for part in payload.splitlines():
            text = part.strip()
            if text:
                values.append(text)
    return values


def _parse_credential_line(line: str) -> dict[str, str]:
    text = str(line or "").strip()
    if not text:
        return {}

    parsed = urlsplit(text)
    if parsed.scheme and parsed.hostname and parsed.port:
        return {
            "endpoint": f"{parsed.hostname}:{parsed.port}",
            "username": parsed.username or "",
            "password": parsed.password or "",
        }

    if "@" in text:
        left, right = text.rsplit("@", 1)
        if ":" in left and ":" in right:
            username, password = left.split(":", 1)
            return {
                "endpoint": right.strip(),
                "username": username.strip(),
                "password": password.strip(),
            }

    parts = [part.strip() for part in text.split(":")]
    if len(parts) >= 4:
        host = parts[0]
        port = parts[1]
        username = parts[2]
        password = ":".join(parts[3:])
        if host and port and username:
            return {
                "endpoint": f"{host}:{port}",
                "username": username,
                "password": password,
            }
    return {}


class CyberYozhProxyProvider(BaseProxyProvider):
    @property
    def base_url(self) -> str:
        return str(settings.cyberyozh_proxy_base_url or "").strip().rstrip("/")

    @property
    def api_key(self) -> str:
        return str(settings.cyberyozh_proxy_key or "").strip()

    def _configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any = None,
    ) -> tuple[int, Any]:
        if not self._configured():
            return 0, {"title": "NOT_CONFIGURED", "details": "CyberYozh provider settings are missing"}

        session = await SessionManager.get_session()
        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "application/json",
            "X-API-KEY": self.api_key,
        }
        try:
            if method.upper() == "POST":
                async with session.post(url, params=params or {}, json=payload, headers=headers, timeout=30) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = text
                    return resp.status, data
            async with session.get(url, params=params or {}, headers=headers, timeout=30) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = text
                return resp.status, data
        except Exception as exc:
            logger.exception("CyberYozh request failed: %s %s", method, path)
            return 0, {"title": "REQUEST_ERROR", "details": str(exc)}

    async def _fetch_credentials_snapshot(self, protocol: str) -> set[str]:
        protocol_value = "socks5" if str(protocol or "").strip().lower() == "socks" else "http"
        status, data = await self._request(
            "GET",
            "/proxies/proxy-credentials/",
            params={
                "type_format": "ip_port_user_pass",
                "protocol": protocol_value,
            },
        )
        if status != 200 or not isinstance(data, dict):
            return set()
        credentials = ((data.get("results") or {}).get("credentials") or {}) if isinstance(data, dict) else {}
        return {value for value in _flatten_credential_strings(credentials) if value}

    @staticmethod
    def _build_duration_options(days: int, price_usd: float) -> list[dict[str, Any]]:
        if days <= 0 or price_usd <= 0:
            return []
        return [
            {
                "value": str(days),
                "label": _duration_label(days),
                "days": days,
                "hours": 0,
                "price": round(price_usd, 4),
            }
        ]

    @staticmethod
    def _extract_buy_success(payload: Any) -> bool:
        if isinstance(payload, list):
            return True
        if not isinstance(payload, dict):
            return False
        for key in ("success", "ok"):
            value = payload.get(key)
            if isinstance(value, bool):
                return value
        if isinstance(payload.get("results"), list) and payload.get("results"):
            return True
        if isinstance(payload.get("data"), list) and payload.get("data"):
            return True
        errors = payload.get("errors")
        return not errors

    @staticmethod
    def _extract_order_id(payload: Any, fallback_offer_id: str) -> str:
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                for key in ("id", "uuid", "order_id", "proxy_id"):
                    value = str(first.get(key) or "").strip()
                    if value:
                        return value
        if isinstance(payload, dict):
            for key in ("id", "uuid", "order_id", "proxy_id"):
                value = str(payload.get(key) or "").strip()
                if value:
                    return value
            for branch in ("results", "data"):
                value = payload.get(branch)
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    for key in ("id", "uuid", "order_id", "proxy_id"):
                        nested = str(value[0].get(key) or "").strip()
                        if nested:
                            return nested
        return fallback_offer_id

    async def list_offers(self) -> list[dict[str, Any]]:
        if not self._configured():
            return []

        page = 1
        offers: list[dict[str, Any]] = []
        while True:
            status, data = await self._request(
                "GET",
                "/proxies/shop/",
                params={
                    "proxy_category": "residential_static",
                    "page": page,
                    "page_size": 100,
                },
            )
            if status != 200 or not isinstance(data, dict):
                break
            groups = data.get("results") or []
            if not isinstance(groups, list) or not groups:
                break
            for group in groups:
                if not isinstance(group, dict):
                    continue
                access_type = str(group.get("access_type") or "").strip().lower()
                for product in group.get("proxy_products") or []:
                    if not isinstance(product, dict):
                        continue
                    offer_id = str(product.get("id") or "").strip()
                    if not offer_id:
                        continue
                    if str(product.get("stock_status") or "").strip().lower() not in {"in_stock", "available", ""}:
                        continue
                    country_code = str(product.get("location_country_code") or "").strip().upper()
                    title = str(product.get("title") or f"Static {country_code}").strip() or f"Static {country_code}"
                    price_usd = _as_float(product.get("price_usd"))
                    days = _as_int(product.get("days")) or 30
                    raw = dict(product)
                    raw["protocol_options"] = ["http", "socks"]
                    raw["duration_options"] = self._build_duration_options(days, price_usd)
                    raw["access_type"] = access_type
                    raw["button_label"] = title
                    offers.append(
                        {
                            "provider": "cyberyozh",
                            "offer_id": offer_id,
                            "title": title,
                            "carrier": "CyberYozh Static",
                            "country": _country_name_from_iso(country_code),
                            "state": "Any",
                            "city": "Any",
                            "period": "Static",
                            "price": round(price_usd, 4),
                            "success_rate": 100.0,
                            "raw": raw,
                        }
                    )
            next_page = data.get("nextPage")
            next_url = data.get("next")
            if next_page:
                page = int(next_page)
                continue
            if next_url:
                page += 1
                continue
            break
        return offers

    async def rent_offer(self, offer: dict[str, Any]) -> dict[str, Any]:
        if not self._configured():
            return {"success": False, "raw": {"title": "NOT_CONFIGURED"}}

        offer_id = str(offer.get("offer_id") or "").strip()
        if not offer_id:
            return {"success": False, "raw": {"title": "INVALID_OFFER_ID"}}

        protocol = str(offer.get("protocol") or "http").strip().lower() or "http"
        before_credentials = await self._fetch_credentials_snapshot(protocol)
        status, data = await self._request(
            "POST",
            "/proxies/shop/buy_proxies/",
            payload=[{"id": offer_id, "auto_renew": False}],
        )
        if status not in (200, 201):
            return {"success": False, "raw": data}
        if not self._extract_buy_success(data):
            return {"success": False, "raw": data}

        after_credentials = await self._fetch_credentials_snapshot(protocol)
        added = sorted(after_credentials - before_credentials)
        if not added and after_credentials:
            added = sorted(after_credentials)

        credential_line = added[0] if added else ""
        parsed = _parse_credential_line(credential_line)
        if not parsed.get("endpoint"):
            return {
                "success": False,
                "raw": {
                    "title": "CREDENTIALS_NOT_READY",
                    "details": "Purchase succeeded but proxy credentials were not returned yet.",
                    "provider_response": data,
                },
            }

        days = _as_int((offer.get("raw") or {}).get("days")) or 30
        return {
            "success": True,
            "order_id": self._extract_order_id(data, offer_id),
            "provider_order_id": self._extract_order_id(data, offer_id),
            "endpoint": parsed.get("endpoint") or "",
            "username": parsed.get("username") or "",
            "password": parsed.get("password") or "",
            "expires_at": f"{days}d",
            "raw": data,
        }
