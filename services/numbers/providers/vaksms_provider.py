import logging
import re
import time
from typing import Any, Optional

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST

from .base_provider import BaseProvider

logger = logging.getLogger("vaksms")

_SERVICE_HINT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "gmail": ("google", "googlegmail"),
    "googlegmail": ("google", "gmail"),
}

_FALLBACK_SERVICES: tuple[dict[str, str], ...] = (
    {"code": "wa", "name": "WhatsApp"},
    {"code": "tg", "name": "Telegram"},
    {"code": "gl", "name": "Google"},
    {"code": "gf", "name": "GoogleVoice"},
    {"code": "ig", "name": "Instagram"},
    {"code": "fb", "name": "Facebook"},
    {"code": "tk", "name": "Tiktok"},
    {"code": "tw", "name": "Twitter"},
    {"code": "dc", "name": "Discord"},
    {"code": "pp", "name": "PayPal"},
    {"code": "ms", "name": "Microsoft"},
    {"code": "dr", "name": "OpenAI"},
)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


class VAKSMSProvider(BaseProvider):
    DEFAULT_BASE = "https://vak-sms.com/api"
    DEFAULT_DOCS_URL = "https://vak-sms.com/api/vak/"
    DEFAULT_SITE_BASE = "https://vak-sms.com/backend"

    def __init__(self) -> None:
        self._services_cache: list[dict[str, Any]] = []
        self._services_cached_at: float = 0.0
        self._services_ttl_sec: int = 3600
        self._countries_cache: list[dict[str, Any]] = []
        self._countries_cached_at: float = 0.0
        self._countries_ttl_sec: int = 3600

    @property
    def base_url(self) -> str:
        return str(getattr(settings, "vaksms_base_url", None) or self.DEFAULT_BASE).strip().rstrip("/")

    @property
    def docs_url(self) -> str:
        return str(getattr(settings, "vaksms_docs_url", None) or self.DEFAULT_DOCS_URL).strip()

    @property
    def site_base_url(self) -> str:
        return str(getattr(settings, "vaksms_site_base_url", None) or self.DEFAULT_SITE_BASE).strip().rstrip("/")

    def _api_key(self) -> Optional[str]:
        key = str(getattr(settings, "vaksms_key", None) or "").strip()
        return key or None

    async def _session(self):
        return await SessionManager.get_session()

    async def _request(self, endpoint: str, *, include_key: bool = True, **params) -> tuple[int, Any]:
        api_key = self._api_key()
        if include_key and not api_key:
            return 0, {"error": "missing_api_key", "message": "VAKSMS_KEY is not configured"}

        query: dict[str, Any] = {}
        if include_key:
            query["apiKey"] = api_key
        for key, value in params.items():
            if value in (None, ""):
                continue
            query[key] = value

        url = f"{self.base_url}/{str(endpoint).strip('/')}/"
        try:
            session = await self._session()
            async with session.get(url, params=query, timeout=20) as resp:
                text = await resp.text()
                if not text:
                    return resp.status, {}
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = text.strip()
                return resp.status, data
        except Exception as exc:
            logger.warning("vaksms request failed endpoint=%s error=%s", endpoint, exc)
            return 0, {"error": "request_failed", "message": str(exc)}

    async def _site_request(self, endpoint: str, **params) -> tuple[int, Any]:
        query = {key: value for key, value in params.items() if value not in (None, "")}
        url = f"{self.site_base_url}/{str(endpoint).strip('/')}"
        try:
            session = await self._session()
            async with session.get(url, params=query, timeout=20) as resp:
                text = await resp.text()
                if not text:
                    return resp.status, {}
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = text.strip()
                return resp.status, data
        except Exception as exc:
            logger.warning("vaksms site request failed endpoint=%s error=%s", endpoint, exc)
            return 0, {"error": "request_failed", "message": str(exc)}

    @staticmethod
    def _country_iso_from_common(country: str | int | None) -> str | None:
        if country in (None, "", "none"):
            return None
        raw = str(country).strip()
        if not raw:
            return None
        aliases = {
            "1": "us",
            "us": "us",
            "usa": "us",
            "unitedstates": "us",
            "2": "gb",
            "gb": "gb",
            "uk": "gb",
            "unitedkingdom": "gb",
        }
        normalized = _norm(raw)
        if normalized in aliases:
            return aliases[normalized]
        if len(raw) == 2 and raw.isalpha():
            return raw.lower()
        for row in COUNTRIES_LIST:
            if str(row.get("code") or "") == raw:
                iso = str(row.get("iso") or "").strip().lower()
                return iso or None
        return raw.lower()

    async def list_countries(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if (
            not force_refresh
            and self._countries_cache
            and (now - self._countries_cached_at) < self._countries_ttl_sec
        ):
            return list(self._countries_cache)

        status, data = await self._request("getCountryList", include_key=False)
        countries: list[dict[str, Any]] = []
        if status == 200 and isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("countryCode"):
                    countries.append(item)
        if countries:
            self._countries_cache = countries
            self._countries_cached_at = now
        return list(self._countries_cache)

    async def _resolve_country(self, country: str | int | None) -> str | None:
        iso = self._country_iso_from_common(country)
        if not iso:
            return None
        countries = await self.list_countries()
        if not countries:
            return iso
        available = {str(row.get("countryCode") or "").strip().lower() for row in countries}
        return iso if iso in available else iso

    async def list_services(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if (
            not force_refresh
            and self._services_cache
            and (now - self._services_cached_at) < self._services_ttl_sec
        ):
            return list(self._services_cache)

        services: list[dict[str, Any]] = []
        try:
            session = await self._session()
            async with session.get(self.docs_url, timeout=30) as resp:
                text = await resp.text()
            marker = 'id="serviceCodeList1"'
            idx = text.find(marker)
            chunk = text[idx:] if idx >= 0 else text
            tbody_start = chunk.find("<tbody>")
            tbody_end = chunk.find("</tbody>")
            if tbody_start >= 0 and tbody_end > tbody_start:
                tbody = chunk[tbody_start:tbody_end]
                row_pattern = re.compile(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", re.S | re.I)
                for raw_name, raw_code in row_pattern.findall(tbody):
                    name = _strip_html(raw_name)
                    code = _strip_html(raw_code)
                    if name and code:
                        services.append({"code": code, "name": name})
        except Exception as exc:
            logger.warning("vaksms service catalog fetch failed: %s", exc)

        if not services:
            services = [dict(item) for item in _FALLBACK_SERVICES]
        self._services_cache = services
        self._services_cached_at = now
        return list(self._services_cache)

    async def resolve_service_code(self, service_hint: str) -> str | None:
        candidates = await self._resolve_service_code_candidates(service_hint)
        return candidates[0] if candidates else None

    async def _resolve_service_code_candidates(self, service_hint: str) -> list[str]:
        hint = str(service_hint or "").strip()
        if not hint:
            return []
        services = await self.list_services()
        hint_norm = _norm(hint)
        expanded_norms = {hint_norm}
        expanded_norms.update(_SERVICE_HINT_SYNONYMS.get(hint_norm, ()))
        ordered: list[str] = []

        def _push(code: Any) -> None:
            value = str(code or "").strip()
            if value and value not in ordered:
                ordered.append(value)

        for item in services:
            code = str(item.get("code") or "").strip()
            if code and _norm(code) == hint_norm:
                _push(code)
        for item in services:
            code = str(item.get("code") or "").strip()
            name_norm = _norm(item.get("name") or "")
            if code and name_norm in expanded_norms:
                _push(code)
        for item in services:
            code = str(item.get("code") or "").strip()
            name_norm = _norm(item.get("name") or "")
            if code and any(candidate and candidate in name_norm for candidate in expanded_norms):
                _push(code)
        return ordered

    async def get_account(self) -> Optional[dict]:
        status, data = await self._request("getBalance")
        if status != 200:
            return None
        return data if isinstance(data, dict) else {"raw": data}

    async def get_balance(self) -> Optional[float]:
        status, data = await self._request("getBalance")
        if status != 200:
            return None
        if isinstance(data, dict):
            return _as_float(data.get("balance"))
        return None

    async def _site_country_stats(self, service_code: str, country_code: str | None) -> dict[str, Any] | None:
        if not service_code or not country_code:
            return None
        status, data = await self._site_request("country/stats", serviceId=service_code)
        if status != 200 or not isinstance(data, list):
            return None
        target = str(country_code or "").strip().lower()
        for item in data:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip().lower() == target:
                return item
        return None

    async def get_price(self, service, country=None, state=None):
        service_code = await self.resolve_service_code(str(service or ""))
        if not service_code:
            return {"success": False, "raw": "service_not_found"}
        country_code = await self._resolve_country(country)
        status, data = await self._request("getCountNumber", service=service_code, country=country_code, price=1)
        if status != 200 or not isinstance(data, dict):
            return {"success": False, "raw": data}
        count = int(data.get(service_code) or data.get(str(service_code).upper()) or 0)
        api_price = _as_float(data.get("price"))
        site_stats = None
        if count <= 0 and country_code:
            site_stats = await self._site_country_stats(service_code, country_code)
            site_count = int(site_stats.get("count") or 0) if isinstance(site_stats, dict) else 0
            if site_count > 0:
                count = site_count
                api_price = _as_float(site_stats.get("apiPrice")) or api_price or _as_float(site_stats.get("minPrice"))
        if count <= 0 or api_price is None or api_price <= 0:
            return {"success": False, "raw": data}
        return {
            "success": True,
            "price": round(api_price, 4),
            "api_service_name": service_code,
            "provider_country": country_code or "ru",
            "provider_country_iso": str(country_code or "ru").upper(),
            "raw": {"api": data, "site": site_stats} if site_stats else data,
        }

    async def buy_number(self, service, country=None, state=None, **kwargs):
        service_code = await self.resolve_service_code(str(service or ""))
        if not service_code:
            service_code = str(service or "").strip()
        if not service_code:
            return {"success": False, "raw": "service_not_found"}
        country_code = await self._resolve_country(country)
        status, data = await self._request("getNumber", service=service_code, country=country_code)
        if status != 200 or not isinstance(data, dict):
            return {"success": False, "raw": data}
        if data.get("error"):
            return {"success": False, "raw": data}
        order_id = str(data.get("idNum") or "").strip()
        number = str(data.get("tel") or "").strip()
        if not order_id or not number:
            return {"success": False, "raw": data}
        return {"success": True, "order_id": order_id, "number": number, "raw": data}

    async def get_sms(self, activation_id: str):
        status, data = await self._request("getSmsCode", idNum=activation_id)
        if status != 200:
            return {"success": False, "messages": [], "raw": data}
        if isinstance(data, dict):
            value = data.get("smsCode")
            if value is None:
                return {"success": True, "messages": [], "raw": data}
            if isinstance(value, list):
                return {"success": True, "messages": [str(item) for item in value if str(item).strip()], "raw": data}
            return {"success": True, "messages": [str(value)], "raw": data}
        return {"success": False, "messages": [], "raw": data}

    async def cancel(self, activation_id: str):
        status, data = await self._request("setStatus", idNum=activation_id, status="end")
        if status != 200:
            return {"success": False, "raw": data}
        if isinstance(data, dict):
            return {"success": str(data.get("status") or "").lower() in {"update", "smsreceived"}, "raw": data}
        return {"success": False, "raw": data}

    async def resend(self, activation_id: str) -> bool:
        status, data = await self._request("setStatus", idNum=activation_id, status="send")
        if status != 200 or not isinstance(data, dict):
            return False
        return str(data.get("status") or "").lower() == "ready"
