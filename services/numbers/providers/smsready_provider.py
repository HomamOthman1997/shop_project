import logging
import time
from typing import Any, Optional

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST

from .base_provider import BaseProvider

logger = logging.getLogger("smsready")


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


class SMSReadyProvider(BaseProvider):
    DEFAULT_BASE = "https://api.sms-ready.com/api"
    SERVICE_CACHE_TTL_SECONDS = 600
    COUNTRY_CACHE_TTL_SECONDS = 3600

    def __init__(self) -> None:
        self._services_cache: list[str] = []
        self._services_cached_at: float = 0.0
        self._rental_services_cache: dict[str, dict[str, Any]] = {}
        self._rental_services_cached_at: float = 0.0
        self._countries_cache: list[str] = []
        self._countries_cached_at: float = 0.0
        self._rental_countries_cache: list[str] = []
        self._rental_countries_cached_at: float = 0.0

    @property
    def base_url(self) -> str:
        return str(getattr(settings, "smsready_base_url", None) or self.DEFAULT_BASE).strip().rstrip("/")

    def _api_key(self) -> Optional[str]:
        key = str(getattr(settings, "smsready_key", None) or "").strip()
        return key or None

    async def _session(self):
        return await SessionManager.get_session()

    async def _request(self, method: str, endpoint: str, **params: Any) -> tuple[int, Any]:
        key = self._api_key()
        if not key:
            return 0, {"status": "error", "message": "SMSREADY_KEY is not configured"}

        clean_params: dict[str, Any] = {"api_key": key}
        for k, v in params.items():
            if v not in (None, ""):
                clean_params[k] = v

        url = f"{self.base_url}/{str(endpoint).strip().lstrip('/')}"
        try:
            session = await self._session()
            method_upper = str(method or "GET").upper()
            if method_upper == "POST":
                request_ctx = session.post(url, data=clean_params, timeout=20)
            else:
                request_ctx = session.get(url, params=clean_params, timeout=20)
            async with request_ctx as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = {"raw_text": text.strip()}
                return resp.status, data
        except Exception as exc:
            logger.warning("smsready request failed endpoint=%s error=%s", endpoint, exc)
            return 0, {"status": "error", "message": str(exc)}

    @staticmethod
    def _ok(status: int, payload: Any) -> bool:
        if status not in (200, 201, 204):
            return False
        if isinstance(payload, dict) and "status" in payload:
            return str(payload.get("status") or "").strip().lower() == "ok"
        return True

    @staticmethod
    def _message(payload: Any) -> Any:
        if isinstance(payload, dict) and "message" in payload:
            return payload.get("message")
        return payload

    @staticmethod
    def _country_aliases() -> dict[str, str]:
        aliases: dict[str, str] = {}
        for row in COUNTRIES_LIST:
            code = str(row.get("code") or "").strip()
            iso = str(row.get("iso") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            if code and name:
                aliases[_norm(code)] = name
            if iso and name:
                aliases[_norm(iso)] = name
            if name:
                aliases[_norm(name)] = name
        aliases.update(
            {
                "usa": "United States",
                "us": "United States",
                "unitedstates": "United States",
                "unitedstatesofamerica": "United States",
                "uk": "United Kingdom",
                "gb": "United Kingdom",
                "greatbritain": "United Kingdom",
            }
        )
        return aliases

    async def _provider_country(self, country: Any, *, rental: bool = False) -> str:
        raw = str(country or "").strip()
        if not raw or raw.lower() == "none":
            return "United States"
        target = self._country_aliases().get(_norm(raw), raw)
        countries = await self.list_countries(rental=rental)
        if not countries:
            return target
        target_norm = _norm(target)
        for item in countries:
            if _norm(item) == target_norm:
                return item
        if target_norm in {"unitedstates", "usa", "us"}:
            for item in countries:
                if _norm(item) in {"unitedstates", "usa", "us"}:
                    return item
        if target_norm in {"unitedkingdom", "uk", "gb", "greatbritain"}:
            for item in countries:
                if _norm(item) in {"unitedkingdom", "uk", "gb", "greatbritain"}:
                    return item
        return target

    @staticmethod
    def _service_names(raw: Any) -> list[str]:
        names: list[str] = []
        if isinstance(raw, list):
            for row in raw:
                if isinstance(row, dict):
                    name = str(row.get("service_name") or row.get("name") or row.get("service") or "").strip()
                else:
                    name = str(row or "").strip()
                if name and name not in names:
                    names.append(name)
        return names

    async def list_services(self, force_refresh: bool = False) -> list[str]:
        now = time.time()
        if (
            not force_refresh
            and self._services_cache
            and (now - self._services_cached_at) < self.SERVICE_CACHE_TTL_SECONDS
        ):
            return list(self._services_cache)

        status, payload = await self._request("GET", "get-services-for-one-time-numbers/")
        services = self._service_names(self._message(payload)) if self._ok(status, payload) else []
        if services:
            self._services_cache = services
            self._services_cached_at = now
        return list(self._services_cache)

    async def list_countries(self, force_refresh: bool = False, *, rental: bool = False) -> list[str]:
        cache = self._rental_countries_cache if rental else self._countries_cache
        cached_at = self._rental_countries_cached_at if rental else self._countries_cached_at
        now = time.time()
        if not force_refresh and cache and (now - cached_at) < self.COUNTRY_CACHE_TTL_SECONDS:
            return list(cache)

        endpoint = "get-countries-for-long-term/" if rental else "get-countries-for-one-time-numbers/"
        status, payload = await self._request("GET", endpoint)
        countries = [str(item).strip() for item in self._message(payload) or [] if str(item or "").strip()] if self._ok(status, payload) else []
        if countries:
            if rental:
                self._rental_countries_cache = countries
                self._rental_countries_cached_at = now
            else:
                self._countries_cache = countries
                self._countries_cached_at = now
        return list(self._rental_countries_cache if rental else self._countries_cache)

    async def list_rental_services(self, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
        now = time.time()
        if (
            not force_refresh
            and self._rental_services_cache
            and (now - self._rental_services_cached_at) < self.SERVICE_CACHE_TTL_SECONDS
        ):
            return dict(self._rental_services_cache)

        status, payload = await self._request("GET", "get-services-ltr/")
        message = self._message(payload)
        services = message if isinstance(message, dict) else {}
        if services:
            self._rental_services_cache = {str(k): v for k, v in services.items() if str(k).strip()}
            self._rental_services_cached_at = now
        return dict(self._rental_services_cache)

    @staticmethod
    def _match_service(service_hint: Any, services: list[str]) -> str | None:
        raw = str(service_hint or "").strip()
        if not raw:
            return None
        target = _norm(raw)
        for name in services:
            if _norm(name) == target:
                return name
        for name in services:
            norm_name = _norm(name)
            if target and (target in norm_name or norm_name in target):
                return name
        return raw

    async def resolve_service_code(self, service_hint: Any, country: Any = None) -> str | None:
        services = await self.list_services()
        return self._match_service(service_hint, services)

    async def resolve_rental_service_code(self, service_hint: Any) -> str | None:
        services = await self.list_rental_services()
        return self._match_service(service_hint, list(services.keys()))

    async def get_price(self, service, country=None, state=None):
        service_name = await self.resolve_service_code(service)
        if not service_name:
            return {"success": False, "raw": "service_not_found"}
        country_name = await self._provider_country(country)
        status, payload = await self._request(
            "GET",
            "get-price-one-time-number/",
            service=service_name,
            country=country_name,
        )
        message = self._message(payload)
        price = _as_float(message.get("price")) if isinstance(message, dict) else None
        if not self._ok(status, payload) or price is None or price <= 0:
            return {"success": False, "raw": payload}
        return {
            "success": True,
            "price": float(price),
            "api_service_name": service_name,
            "provider_country": country_name,
            "raw": payload,
        }

    async def buy_number(self, service, country=None, state=None, **kwargs):
        service_name = await self.resolve_service_code(service)
        if not service_name:
            return {"success": False, "raw": "service_not_found"}
        country_name = await self._provider_country(country)
        status, payload = await self._request(
            "POST",
            "order-one-time-number/",
            service=service_name,
            country=country_name,
        )
        message = self._message(payload)
        if not self._ok(status, payload) or not isinstance(message, dict):
            return {"success": False, "raw": payload}
        order_id = str(message.get("order_id") or "").strip()
        number = str(message.get("phone_number") or message.get("number") or "").strip()
        if not order_id or not number:
            return {"success": False, "raw": payload}
        return {
            "success": True,
            "order_id": order_id,
            "number": number,
            "price": _as_float(message.get("cost")),
            "raw": payload,
        }

    async def get_sms(self, activation_id: str):
        return {"success": True, "messages": [], "raw": "smsready_webhook_only"}

    async def get_balance(self) -> Optional[float]:
        # SMSReady's supplied API reference has no account balance endpoint.
        return None

    async def cancel(self, activation_id: str):
        status, payload = await self._request("POST", "refund-one-time-order/", order_id=activation_id)
        return {"success": self._ok(status, payload), "raw": payload}

    async def resend(self, activation_id: str) -> dict[str, Any]:
        status, payload = await self._request("POST", "resend-one-time-order/", order_id=activation_id)
        message = self._message(payload)
        if not self._ok(status, payload):
            return {"success": False, "raw": payload}
        if isinstance(message, dict):
            return {
                "success": True,
                "order_id": str(message.get("order_id") or activation_id),
                "number": str(message.get("phone_number") or message.get("number") or "").strip(),
                "raw": payload,
            }
        return {"success": True, "order_id": activation_id, "raw": payload}

    async def get_rental_prices(self, service: str, country: str | None = None) -> dict[str, Any]:
        service_name = await self.resolve_rental_service_code(service)
        if not service_name:
            return {"success": False, "options": [], "raw": "service_not_found"}
        country_name = await self._provider_country(country, rental=True)
        status, payload = await self._request(
            "GET",
            "get-order-info-ltr/",
            service=service_name,
            country=country_name,
        )
        message = self._message(payload)
        if not self._ok(status, payload) or not isinstance(message, dict):
            return {"success": False, "options": [], "raw": payload}
        options: list[dict[str, Any]] = []
        for raw_duration, raw_price in message.items():
            price = _as_float(raw_price)
            if price is None or price <= 0:
                continue
            duration_text = str(raw_duration or "").strip()
            if _norm(duration_text) == "perday":
                days = 1
                duration_param = "per day"
                label = "per day"
            else:
                try:
                    days = int(float(duration_text))
                except Exception:
                    continue
                duration_param = str(days)
                label = f"{days}d"
            options.append(
                {
                    "country": country_name,
                    "duration": int(days * 24),
                    "duration_days": int(days),
                    "duration_label": label,
                    "provider_duration": duration_param,
                    "price": float(price),
                    "count": 1,
                }
            )
        return {"success": bool(options), "options": options, "raw": payload}

    async def rent_number(self, service: str, country: str | None = None, duration: int = 3, **kwargs) -> dict[str, Any]:
        service_name = await self.resolve_rental_service_code(service)
        if not service_name:
            return {"success": False, "raw": "service_not_found"}
        country_name = await self._provider_country(country, rental=True)
        provider_duration = str(kwargs.get("provider_duration") or "").strip()
        if not provider_duration:
            days = int(kwargs.get("duration_days") or 0)
            if days <= 0:
                days = int(duration / 24) if int(duration or 0) > 31 else int(duration or 3)
            provider_duration = str(days)
        params: dict[str, Any] = {
            "service": service_name,
            "country": country_name,
            "duration": provider_duration,
        }
        mdn = str(kwargs.get("mdn") or "").strip()
        if mdn:
            params["mdn"] = mdn
        status, payload = await self._request("POST", "order-ltr/", **params)
        message = self._message(payload)
        if not self._ok(status, payload) or not isinstance(message, dict):
            return {"success": False, "raw": payload}
        order_id = str(message.get("order_id") or "").strip()
        number = str(message.get("phone_number") or message.get("number") or "").strip()
        if not order_id or not number:
            return {"success": False, "raw": payload}
        return {
            "success": True,
            "order_id": order_id,
            "number": number,
            "price": _as_float(message.get("cost")),
            "end_date": message.get("expires_at"),
            "raw": payload,
        }

    async def get_rental_sms(self, activation_id: str, size: int = 20, page: int = 1) -> dict[str, Any]:
        return await self.get_sms(activation_id)

    async def finish_rental(self, activation_id: str) -> dict[str, Any]:
        status, payload = await self._request("POST", "release-ltr/", order_id=activation_id)
        return {"success": self._ok(status, payload), "raw": payload}

    async def wake_rental(self, activation_id: str) -> dict[str, Any]:
        status, payload = await self._request("POST", "activate-ltr/", order_id=activation_id)
        return {"success": self._ok(status, payload), "raw": payload}

    async def renew_rental(self, activation_id: str) -> dict[str, Any]:
        status, payload = await self._request("POST", "autorenew-ltr/", order_id=activation_id)
        return {"success": self._ok(status, payload), "raw": payload}
