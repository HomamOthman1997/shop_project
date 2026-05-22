import base64
import json
import logging
import re
import time
from typing import Any, Optional

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST

from .base_provider import BaseProvider

logger = logging.getLogger("pvapins")


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _strip_service_suffix(value: Any) -> str:
    return re.sub(r"\d+$", "", _norm(value))


class PVAPinsProvider(BaseProvider):
    DEFAULT_BASE = "https://api.pvapins.com/user/api"
    CACHE_TTL_SECONDS = 600
    COUNTRY_CACHE_TTL_SECONDS = 3600

    _TEMP_ERROR_MARKERS = (
        "customer not found",
        "app not found",
        "country not found",
        "number not found",
        "not able",
        "cant rejected",
        "can't rejected",
        "error 102",
        "registration in progress",
        "balance is expired",
        "not enough balance",
        "no number found",
        "not possible",
        "too many requests",
    )
    _EMPTY_SMS_MARKERS = ("you have not received any code yet", "check back later")

    def __init__(self) -> None:
        self._countries_cache: dict[bool, list[dict[str, Any]]] = {}
        self._countries_cached_at: dict[bool, float] = {}
        self._apps_cache: dict[tuple[bool, str], list[dict[str, Any]]] = {}
        self._apps_cached_at: dict[tuple[bool, str], float] = {}

    @property
    def base_url(self) -> str:
        return str(getattr(settings, "pvapins_base_url", None) or self.DEFAULT_BASE).strip().rstrip("/")

    def _api_key(self) -> Optional[str]:
        key = str(getattr(settings, "pvapins_key", None) or "").strip()
        return key or None

    async def _session(self):
        return await SessionManager.get_session()

    async def _request(self, endpoint: str, *, auth: bool = True, **params: Any) -> tuple[int, Any]:
        clean_params: dict[str, Any] = {}
        if auth:
            key = self._api_key()
            if not key:
                return 0, {"error": "PVAPINS_KEY is not configured"}
            clean_params["customer"] = key
        for k, v in params.items():
            if v not in (None, ""):
                clean_params[k] = v

        url = f"{self.base_url}/{str(endpoint).strip().lstrip('/')}"
        try:
            session = await self._session()
            async with session.get(url, params=clean_params, timeout=20) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = {"raw_text": text.strip()}
                return resp.status, data
        except Exception as exc:
            logger.warning("pvapins request failed endpoint=%s error=%s", endpoint, exc)
            return 0, {"error": str(exc)}

    @classmethod
    def _is_error_payload(cls, payload: Any) -> bool:
        text = cls._payload_text(payload).lower()
        return any(marker in text for marker in cls._TEMP_ERROR_MARKERS)

    @classmethod
    def _is_empty_sms_payload(cls, payload: Any) -> bool:
        text = cls._payload_text(payload).lower()
        return any(marker in text for marker in cls._EMPTY_SMS_MARKERS)

    @staticmethod
    def _payload_text(payload: Any) -> str:
        if isinstance(payload, dict):
            values = []
            for key in ("error", "message", "data", "raw_text"):
                value = payload.get(key)
                if isinstance(value, str):
                    values.append(value)
            return " ".join(values)
        if isinstance(payload, str):
            return payload
        return str(payload or "")

    @staticmethod
    def _country_aliases() -> dict[str, str]:
        aliases: dict[str, str] = {
            "us": "USA",
            "usa": "USA",
            "unitedstates": "USA",
            "unitedstatesofamerica": "USA",
            "uk": "UK",
            "gb": "UK",
            "greatbritain": "UK",
            "unitedkingdom": "UK",
        }
        for row in COUNTRIES_LIST:
            code = str(row.get("code") or "").strip()
            iso = str(row.get("iso") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            provider_name = "USA" if iso == "US" else "UK" if iso == "GB" else name
            if code:
                aliases[_norm(code)] = provider_name
            if iso:
                aliases[_norm(iso)] = provider_name
            aliases[_norm(name)] = provider_name
        return aliases

    @classmethod
    def _country_target(cls, country: Any) -> str:
        raw = str(country or "").strip()
        if not raw or raw.lower() == "none":
            return "USA"
        return cls._country_aliases().get(_norm(raw), raw)

    @staticmethod
    def _country_name(row: dict[str, Any]) -> str:
        return str(row.get("full_name") or row.get("name") or row.get("country") or "").strip()

    async def list_countries(self, force_refresh: bool = False, *, rental: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        cached = self._countries_cache.get(rental)
        cached_at = float(self._countries_cached_at.get(rental) or 0.0)
        if not force_refresh and cached and (now - cached_at) < self.COUNTRY_CACHE_TTL_SECONDS:
            return list(cached)

        params = {"is_rent": 1} if rental else {}
        status, payload = await self._request("load_countries.php", auth=False, **params)
        rows = payload if isinstance(payload, list) else []
        countries = [dict(row) for row in rows if isinstance(row, dict) and self._country_name(row)]
        if status == 200 and countries:
            self._countries_cache[rental] = countries
            self._countries_cached_at[rental] = now
        return list(self._countries_cache.get(rental) or [])

    async def _country_entry(self, country: Any, *, rental: bool = False) -> dict[str, Any]:
        target = self._country_target(country)
        countries = await self.list_countries(rental=rental)
        target_norm = _norm(target)
        for row in countries:
            name = self._country_name(row)
            if _norm(name) == target_norm:
                return row
        return {"id": "", "full_name": target}

    async def list_apps_for_country(
        self,
        country: Any = None,
        *,
        rental: bool = False,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        country_row = await self._country_entry(country, rental=rental)
        country_name = self._country_name(country_row) or self._country_target(country)
        country_id = str(country_row.get("id") or "").strip()
        if not country_id:
            return []

        cache_key = (rental, country_id)
        now = time.time()
        cached = self._apps_cache.get(cache_key)
        cached_at = float(self._apps_cached_at.get(cache_key) or 0.0)
        if not force_refresh and cached and (now - cached_at) < self.CACHE_TTL_SECONDS:
            return list(cached)

        params: dict[str, Any] = {"country_id": country_id}
        if rental:
            params["is_rent"] = 1
        status, payload = await self._request("load_apps.php", auth=False, **params)
        rows = payload if isinstance(payload, list) else []
        apps: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            app_name = self._app_name(row)
            if not app_name:
                continue
            item = dict(row)
            item["_country_name"] = country_name
            apps.append(item)
        if status == 200 and apps:
            self._apps_cache[cache_key] = apps
            self._apps_cached_at[cache_key] = now
        return list(self._apps_cache.get(cache_key) or [])

    async def list_services(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        return await self.list_apps_for_country("USA", force_refresh=force_refresh)

    @staticmethod
    def _split_operator(service: Any) -> tuple[str, str | None]:
        raw = str(service or "").strip()
        for sep in ("::", "|"):
            if sep in raw:
                app, operator = raw.split(sep, 1)
                app = app.strip()
                operator = operator.strip()
                if app and operator:
                    return app, operator
        return raw, None

    @staticmethod
    def _service_token(app_name: str, operator: str | None = None) -> str:
        app = str(app_name or "").strip()
        op = str(operator or "").strip()
        return f"{app}::{op}" if op else app

    @staticmethod
    def _app_name(row: dict[str, Any]) -> str:
        return str(row.get("full_name") or row.get("app_name") or row.get("app") or row.get("name") or "").strip()

    @classmethod
    def _find_app(cls, service_hint: Any, apps: list[dict[str, Any]]) -> dict[str, Any] | None:
        app_hint, _operator = cls._split_operator(service_hint)
        target = _norm(app_hint)
        target_base = _strip_service_suffix(app_hint)
        if not target:
            return None

        def price(row: dict[str, Any]) -> float:
            parsed = _as_float(row.get("deduct") or row.get("rate") or row.get("price"))
            return parsed if parsed is not None else 999999.0

        exact: list[dict[str, Any]] = []
        loose: list[dict[str, Any]] = []
        for row in apps:
            name = cls._app_name(row)
            name_norm = _norm(name)
            name_base = _strip_service_suffix(name)
            if not name_norm:
                continue
            if name_norm == target or name_base == target_base:
                exact.append(row)
            elif target in name_norm or (target_base and target_base in name_base):
                loose.append(row)
        candidates = exact or loose
        if not candidates:
            return None
        return sorted(candidates, key=lambda row: (price(row), cls._app_name(row).lower()))[0]

    async def resolve_service_code(self, service_hint: Any, country: Any = None) -> str | None:
        app, operator = self._split_operator(service_hint)
        app = str(app or "").strip()
        if not app:
            return None
        if country not in (None, "", "none"):
            apps = await self.list_apps_for_country(country)
            match = self._find_app(app, apps)
            if match:
                app = self._app_name(match)
        return self._service_token(app, operator)

    @staticmethod
    def _rates_entries(payload: Any) -> list[dict[str, Any]]:
        data = payload
        if isinstance(payload, dict):
            data = payload.get("data") if "data" in payload else payload.get("rates")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        return []

    async def _rate_fallback(self, service: Any, country_name: str) -> tuple[float | None, str | None, Any]:
        status, payload = await self._request("get_rates.php", country=country_name)
        if status != 200 or self._is_error_payload(payload):
            return None, None, payload
        app, operator = self._split_operator(service)
        rows = self._rates_entries(payload)
        match = self._find_app(app, rows)
        if not match:
            return None, None, payload
        price = _as_float(match.get("rate") or match.get("deduct") or match.get("price"))
        name = self._app_name(match) or str(match.get("business_code") or app)
        return price, self._service_token(name, operator), payload

    async def get_price(self, service, country=None, state=None):
        country_row = await self._country_entry(country)
        country_name = self._country_name(country_row) or self._country_target(country)
        apps = await self.list_apps_for_country(country_name)
        app, operator = self._split_operator(service)
        match = self._find_app(app, apps)
        raw: Any = match
        if match:
            price = _as_float(match.get("deduct") or match.get("rate") or match.get("price"))
            app_name = self._app_name(match)
        else:
            price, app_name, raw = await self._rate_fallback(service, country_name)
        if price is None or price <= 0 or not app_name:
            return {"success": False, "raw": raw or "service_not_found"}
        return {
            "success": True,
            "price": float(price),
            "api_service_name": self._service_token(app_name, operator),
            "provider_country": country_name,
            "raw": raw,
        }

    @staticmethod
    def _pack_activation(*, number: str, country: str, app: str, operator: str | None = None, rental: bool = False) -> str:
        payload = {
            "number": str(number or "").strip(),
            "country": str(country or "").strip(),
            "app": str(app or "").strip(),
            "operator": str(operator or "").strip(),
            "rental": bool(rental),
        }
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return "pvapins:" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _unpack_activation(activation_id: Any) -> dict[str, Any] | None:
        raw = str(activation_id or "").strip()
        if not raw.startswith("pvapins:"):
            return None
        token = raw.split(":", 1)[1]
        try:
            padded = token + ("=" * (-len(token) % 4))
            data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    @classmethod
    def _extract_number(cls, payload: Any) -> str | None:
        if cls._is_error_payload(payload):
            return None
        if isinstance(payload, dict):
            for key in ("number", "phone", "phone_number"):
                value = str(payload.get(key) or "").strip()
                if re.fullmatch(r"\+?\d{6,}", value):
                    return value
            for key in ("data", "message", "result"):
                value = payload.get(key)
                if isinstance(value, dict):
                    found = cls._extract_number(value)
                    if found:
                        return found
                if isinstance(value, str):
                    found = cls._extract_number(value)
                    if found:
                        return found
            value = str(payload.get("raw_text") or "").strip()
            if value:
                return cls._extract_number(value)
            return None
        text = str(payload or "").strip()
        if not text or cls._is_error_payload(text):
            return None
        if "|" in text:
            text = text.split("|", 1)[0].strip()
        match = re.search(r"\+?\d{6,}", text)
        return match.group(0) if match else None

    async def buy_number(self, service, country=None, state=None, **kwargs):
        country_name = self._country_name(await self._country_entry(country)) or self._country_target(country)
        app, operator = self._split_operator(service)
        if not app:
            return {"success": False, "raw": "service_not_found"}
        params: dict[str, Any] = {"app": app, "country": country_name}
        if operator:
            params["operator"] = operator
        reuse_number = str(kwargs.get("number") or kwargs.get("reuse_number") or "").strip()
        if reuse_number:
            params["number"] = reuse_number
        status, payload = await self._request("get_number.php", **params)
        number = self._extract_number(payload)
        if status != 200 or not number:
            return {"success": False, "raw": payload}
        return {
            "success": True,
            "order_id": self._pack_activation(number=number, country=country_name, app=app, operator=operator),
            "number": number,
            "raw": payload,
        }

    @classmethod
    def _extract_messages(cls, payload: Any) -> list[str]:
        if cls._is_empty_sms_payload(payload):
            return []
        messages: list[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    visit(item)
                return
            if isinstance(node, dict):
                for key in ("message", "sms", "code", "full_sms", "text", "body", "data", "raw_text"):
                    value = node.get(key)
                    if isinstance(value, (dict, list)):
                        visit(value)
                    elif isinstance(value, str) and value.strip() and not cls._is_error_payload(value):
                        messages.append(value.strip())
                return
            if isinstance(node, str) and node.strip() and not cls._is_error_payload(node):
                messages.append(node.strip())

        visit(payload)
        out: list[str] = []
        for item in messages:
            if item not in out:
                out.append(item)
        return out

    async def get_sms(self, activation_id: str):
        ctx = self._unpack_activation(activation_id)
        if not ctx:
            return {"success": False, "messages": [], "raw": "invalid_pvapins_activation"}
        params = {
            "number": str(ctx.get("number") or "").strip(),
            "country": str(ctx.get("country") or "").strip(),
            "app": str(ctx.get("app") or "").strip(),
        }
        operator = str(ctx.get("operator") or "").strip()
        if operator:
            params["operator"] = operator
        if not params["number"] or not params["country"] or not params["app"]:
            return {"success": False, "messages": [], "raw": "invalid_pvapins_activation"}
        status, payload = await self._request("get_sms.php", **params)
        if status != 200:
            return {"success": False, "messages": [], "raw": payload}
        if self._is_empty_sms_payload(payload):
            return {"success": True, "messages": [], "raw": payload}
        if self._is_error_payload(payload):
            return {"success": False, "messages": [], "raw": payload}
        return {"success": True, "messages": self._extract_messages(payload), "raw": payload}

    async def cancel(self, activation_id: str):
        ctx = self._unpack_activation(activation_id)
        if not ctx:
            return {"success": False, "raw": "invalid_pvapins_activation"}
        params = {
            "number": str(ctx.get("number") or "").strip(),
            "country": str(ctx.get("country") or "").strip(),
            "app": str(ctx.get("app") or "").strip(),
        }
        operator = str(ctx.get("operator") or "").strip()
        if operator:
            params["operator"] = operator
        status, payload = await self._request("get_reject_number.php", **params)
        text = self._payload_text(payload).lower()
        if isinstance(payload, dict) and payload.get("code") not in (None, ""):
            success = str(payload.get("code") or "") == "100"
        else:
            success = status == 200 and (
                "number rejected" in text
                or text.strip() == "rejected"
                or ("rejected" in text and "cant rejected" not in text and "can't rejected" not in text)
                or not self._is_error_payload(payload)
            )
        return {"success": success, "raw": payload}

    async def resend(self, activation_id: str) -> dict[str, Any]:
        ctx = self._unpack_activation(activation_id)
        if not ctx:
            return {"success": False, "raw": "invalid_pvapins_activation"}
        res = await self.buy_number(
            self._service_token(str(ctx.get("app") or ""), str(ctx.get("operator") or "") or None),
            country=str(ctx.get("country") or ""),
            number=str(ctx.get("number") or ""),
        )
        if not res.get("success"):
            return res
        return {"success": True, "order_id": res.get("order_id") or activation_id, "number": res.get("number"), "raw": res.get("raw")}

    async def get_balance(self) -> Optional[float]:
        status, payload = await self._request("get_balance.php")
        if status != 200 or self._is_error_payload(payload):
            return None
        if isinstance(payload, dict):
            for key in ("balance", "data", "amount", "wallet"):
                value = payload.get(key)
                if isinstance(value, dict):
                    nested = _as_float(value.get("balance") or value.get("amount"))
                    if nested is not None:
                        return nested
                parsed = _as_float(value)
                if parsed is not None:
                    return parsed
            parsed = _as_float(payload.get("raw_text"))
            if parsed is not None:
                return parsed
        return _as_float(payload)

    async def get_rental_prices(self, service: str, country: str | None = None) -> dict[str, Any]:
        country_row = await self._country_entry(country, rental=True)
        country_name = self._country_name(country_row) or self._country_target(country)
        apps = await self.list_apps_for_country(country_name, rental=True)
        app, operator = self._split_operator(service)
        match = self._find_app(app, apps)
        if not match:
            return {"success": False, "options": [], "raw": "service_not_found"}
        price = _as_float(match.get("deduct") or match.get("rate") or match.get("price"))
        if price is None or price <= 0:
            return {"success": False, "options": [], "raw": match}
        app_name = self._app_name(match)
        return {
            "success": True,
            "options": [
                {
                    "country": country_name,
                    "duration": 72,
                    "duration_days": 3,
                    "duration_label": "3d",
                    "price": float(price),
                    "count": 1,
                    "provider_app": self._service_token(app_name, operator),
                }
            ],
            "raw": match,
        }

    async def rent_number(self, service: str, country: str | None = None, duration: int = 72, **kwargs) -> dict[str, Any]:
        country_name = self._country_name(await self._country_entry(country, rental=True)) or self._country_target(country)
        app, operator = self._split_operator(str(kwargs.get("provider_app") or service))
        if not app:
            return {"success": False, "raw": "service_not_found"}
        params: dict[str, Any] = {"app": app, "country": country_name}
        if operator:
            params["operator"] = operator
        status, payload = await self._request("rent.php", **params)
        number = self._extract_number(payload)
        if status != 200 or not number:
            return {"success": False, "raw": payload}
        return {
            "success": True,
            "order_id": self._pack_activation(number=number, country=country_name, app=app, operator=operator, rental=True),
            "number": number,
            "raw": payload,
        }

    async def get_rental_sms(self, activation_id: str, size: int = 20, page: int = 1) -> dict[str, Any]:
        ctx = self._unpack_activation(activation_id)
        if not ctx:
            return {"success": False, "messages": [], "raw": "invalid_pvapins_activation"}
        params = {
            "number": str(ctx.get("number") or "").strip(),
            "country": str(ctx.get("country") or "").strip(),
            "app": str(ctx.get("app") or "").strip(),
        }
        status, payload = await self._request("load_rent_code.php", **params)
        if status != 200 or self._is_error_payload(payload):
            return {"success": False, "messages": [], "raw": payload}
        return {"success": True, "messages": self._extract_messages(payload), "raw": payload}

    async def get_rental_info(self, activation_id: str) -> dict[str, Any]:
        ctx = self._unpack_activation(activation_id)
        if not ctx:
            return {"success": False, "raw": "invalid_pvapins_activation"}
        status, payload = await self._request("load_rent.php")
        if status != 200 or not isinstance(payload, list):
            return {"success": False, "raw": payload}
        number = str(ctx.get("number") or "").strip()
        for row in payload:
            if isinstance(row, dict) and str(row.get("number") or "").strip() == number:
                return {
                    "success": True,
                    "end_date": row.get("expiry"),
                    "status": "released" if int(row.get("is_released") or 0) else "active",
                    "raw": row,
                }
        return {"success": False, "raw": payload}

    async def finish_rental(self, activation_id: str) -> dict[str, Any]:
        ctx = self._unpack_activation(activation_id)
        if not ctx:
            return {"success": False, "raw": "invalid_pvapins_activation"}
        params = {
            "number": str(ctx.get("number") or "").strip(),
            "country": str(ctx.get("country") or "").strip(),
            "app": str(ctx.get("app") or "").strip(),
        }
        status, payload = await self._request("reject_rent.php", **params)
        text = self._payload_text(payload).lower()
        if isinstance(payload, dict) and payload.get("code") not in (None, ""):
            success = str(payload.get("code") or "") == "100"
        else:
            success = status == 200 and "rejected" in text and "cant rejected" not in text and "can't rejected" not in text
        return {"success": success, "raw": payload}

    async def renew_rental(self, activation_id: str) -> dict[str, Any]:
        ctx = self._unpack_activation(activation_id)
        if not ctx:
            return {"success": False, "raw": "invalid_pvapins_activation"}
        params = {
            "number": str(ctx.get("number") or "").strip(),
            "country": str(ctx.get("country") or "").strip(),
            "app": str(ctx.get("app") or "").strip(),
        }
        status, payload = await self._request("rent_renew_number.php", **params)
        success = status == 200 and (
            (isinstance(payload, dict) and str(payload.get("code") or "") == "100")
            or "status updated" in self._payload_text(payload).lower()
        )
        return {"success": success, "raw": payload}

    async def wake_rental(self, activation_id: str) -> dict[str, Any]:
        return {"success": False, "raw": "wake_not_supported"}
