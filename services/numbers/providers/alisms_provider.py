import logging
import re
import time
from typing import Any, Optional

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST

from .base_provider import BaseProvider

logger = logging.getLogger("alisms")

_SERVICE_HINT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "gmail": ("google", "googlegmail"),
    "googlegmail": ("google", "gmail"),
}


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _status_ok_string(value: str) -> bool:
    text = str(value or "").strip().upper()
    return text.startswith("ACCESS_") or text.startswith("STATUS_")


class AliSMSProvider(BaseProvider):
    DEFAULT_BASE = "https://api.alisms.org/stubs/handler_api.php"

    def __init__(self) -> None:
        self._services_cache: list[dict[str, Any]] = []
        self._services_cached_at: float = 0.0
        self._services_ttl_sec: int = 600
        self._countries_cache: list[dict[str, Any]] = []
        self._countries_cached_at: float = 0.0
        self._countries_ttl_sec: int = 3600

    @property
    def base_url(self) -> str:
        return str(getattr(settings, "alisms_base_url", None) or self.DEFAULT_BASE).strip()

    def _api_key(self) -> Optional[str]:
        key = str(getattr(settings, "alisms_key", None) or "").strip()
        return key or None

    async def _session(self):
        return await SessionManager.get_session()

    async def _request(self, action: str, **params) -> tuple[int, Any]:
        api_key = self._api_key()
        if not api_key:
            return 0, {"error": "missing_api_key", "message": "ALISMS_KEY is not configured"}

        query: dict[str, Any] = {"api_key": api_key, "action": action}
        for key, value in params.items():
            if value in (None, ""):
                continue
            query[key] = value

        try:
            session = await self._session()
            async with session.get(self.base_url, params=query, timeout=20) as resp:
                text = await resp.text()
                if not text:
                    return resp.status, {}
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = text.strip()
                return resp.status, data
        except Exception as exc:
            logger.warning("alisms request failed action=%s error=%s", action, exc)
            return 0, {"error": "request_failed", "message": str(exc)}

    @staticmethod
    def _common_country_by_code() -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in COUNTRIES_LIST:
            code = str(row.get("code") or "").strip()
            if code:
                out[code] = row
        return out

    @staticmethod
    def _country_aliases_from_row(row: dict[str, Any]) -> set[str]:
        aliases: set[str] = set()
        for key in ("eng", "code"):
            value = str(row.get(key) or "").strip()
            normalized = _norm(value)
            if normalized:
                aliases.add(normalized)
        eng = _norm(row.get("eng"))
        code = _norm(row.get("code"))
        if eng in {"usa", "unitedstates"} or code == "us":
            aliases.update({"us", "usa", "unitedstates", "unitedstatesofamerica"})
        if eng in {"unitedkingdom"} or code == "gb":
            aliases.update({"uk", "gb", "unitedkingdom", "greatbritain", "england"})
        return aliases

    async def list_countries(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if (
            not force_refresh
            and self._countries_cache
            and (now - self._countries_cached_at) < self._countries_ttl_sec
        ):
            return list(self._countries_cache)

        _status, data = await self._request("getCountries")
        countries: list[dict[str, Any]] = []
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, dict) and value.get("id") is not None:
                    countries.append(value)
        if countries:
            self._countries_cache = countries
            self._countries_cached_at = now
        return list(self._countries_cache)

    async def _resolve_country(self, country: str | int | None) -> str | None:
        if country in (None, "", "none"):
            return None

        raw = str(country).strip()
        if not raw:
            return None

        countries = await self.list_countries()
        if not countries:
            return raw

        by_id: dict[str, str] = {}
        by_alias: dict[str, str] = {}
        for row in countries:
            cid = str(row.get("id") or "").strip()
            if not cid:
                continue
            by_id[cid] = cid
            for alias in self._country_aliases_from_row(row):
                by_alias.setdefault(alias, cid)

        common = self._common_country_by_code()
        if raw in common:
            item = common[raw]
            iso = str(item.get("iso") or "").strip().lower()
            name = str(item.get("name") or "").strip()
            candidates = {_norm(name), _norm(iso)}
            if iso == "us":
                candidates.update({"us", "usa", "unitedstates"})
            elif iso == "gb":
                candidates.update({"gb", "uk", "unitedkingdom"})
            for candidate in candidates:
                if candidate in by_alias:
                    return by_alias[candidate]
            return None

        normalized = _norm(raw)
        if normalized in by_alias:
            return by_alias[normalized]
        if raw in by_id:
            return raw
        return raw

    async def list_services(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if (
            not force_refresh
            and self._services_cache
            and (now - self._services_cached_at) < self._services_ttl_sec
        ):
            return list(self._services_cache)

        _status, data = await self._request("getServicesList")
        services: list[dict[str, Any]] = []
        if isinstance(data, dict) and str(data.get("status") or "").lower() == "success":
            raw_services = data.get("services")
            if isinstance(raw_services, list):
                for item in raw_services:
                    if isinstance(item, dict) and item.get("code") and item.get("name"):
                        services.append(item)
        if services:
            self._services_cache = services
            self._services_cached_at = now
        return list(self._services_cache)

    async def resolve_service_code(self, service_hint: str) -> str | None:
        hint = str(service_hint or "").strip()
        if not hint:
            return None

        candidates = await self._resolve_service_code_candidates(hint)
        return candidates[0] if candidates else None

    async def _resolve_service_code_candidates(self, service_hint: str) -> list[str]:
        hint = str(service_hint or "").strip()
        if not hint:
            return []

        services = await self.list_services()
        if not services:
            return []

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
            name = str(item.get("name") or "").strip()
            if code and _norm(name) in expanded_norms:
                _push(code)

        def _tokens(value: str) -> list[str]:
            raw = str(value or "")
            for sep in (",", "/", "+", "|", ";", "(", ")", "_"):
                raw = raw.replace(sep, " ")
            return [_norm(token) for token in raw.split() if token.strip()]

        hint_tokens = set(_tokens(hint))
        for item in tuple(hint_tokens):
            hint_tokens.update(_SERVICE_HINT_SYNONYMS.get(item, ()))
        for item in services:
            code = str(item.get("code") or "").strip()
            name_tokens = set(_tokens(item.get("name") or ""))
            if code and hint_tokens and hint_tokens <= name_tokens:
                _push(code)

        for item in services:
            code = str(item.get("code") or "").strip()
            name_norm = _norm(item.get("name") or "")
            if code and any(candidate and candidate in name_norm for candidate in expanded_norms):
                _push(code)
        return ordered

    async def _select_service_code_for_country(
        self,
        service_hint: str,
        country_id: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        candidates = await self._resolve_service_code_candidates(service_hint)
        if not candidates:
            return None, None

        _status, data = await self._request("getPrices", country=country_id)
        if not isinstance(data, dict):
            return candidates[0], None

        best_code: str | None = None
        best_price: float | None = None
        for code in candidates:
            service_prices = data.get(code)
            if not isinstance(service_prices, dict):
                continue
            country_prices = service_prices.get(str(country_id))
            if not isinstance(country_prices, dict):
                continue
            prices = [_as_float(value) for value in country_prices.values()]
            prices = [value for value in prices if value is not None and value > 0]
            if not prices:
                continue
            price = float(min(prices))
            if best_price is None or price < best_price:
                best_code = code
                best_price = price

        if best_code:
            return best_code, data
        return candidates[0], data

    async def _select_service_code_any_country(
        self,
        service_hint: str,
    ) -> tuple[str | None, str | None, dict[str, Any] | None]:
        candidates = await self._resolve_service_code_candidates(service_hint)
        if not candidates:
            return None, None, None

        _status, data = await self._request("getPrices")
        if not isinstance(data, dict):
            return candidates[0], None, None

        best_code: str | None = None
        best_country_id: str | None = None
        best_price: float | None = None
        for code in candidates:
            service_prices = data.get(code)
            if not isinstance(service_prices, dict):
                continue
            for country_id, country_prices in service_prices.items():
                if not isinstance(country_prices, dict):
                    continue
                prices = [_as_float(value) for value in country_prices.values()]
                prices = [value for value in prices if value is not None and value > 0]
                if not prices:
                    continue
                price = float(min(prices))
                if best_price is None or price < best_price:
                    best_code = str(code)
                    best_country_id = str(country_id)
                    best_price = price
        if best_code:
            return best_code, best_country_id, data
        return candidates[0], None, data

    async def get_account(self) -> Optional[dict]:
        status, data = await self._request("getBalance")
        if status != 200:
            return None
        if isinstance(data, str):
            return {"raw": data}
        return data if isinstance(data, dict) else None

    async def get_balance(self) -> Optional[float]:
        status, data = await self._request("getBalance")
        if status != 200:
            return None
        if isinstance(data, str):
            match = re.search(r"ACCESS_BALANCE:([0-9]+(?:\.[0-9]+)?)", data.strip(), re.I)
            if match:
                return _as_float(match.group(1))
        if isinstance(data, dict):
            for key in ("balance", "amount", "value"):
                parsed = _as_float(data.get(key))
                if parsed is not None:
                    return parsed
        return None

    async def get_price(self, service, country=None, state=None):
        country_id = await self._resolve_country(country)
        selected_country_id = country_id
        if not country_id:
            service_code, selected_country_id, cached_prices = await self._select_service_code_any_country(str(service or ""))
        else:
            service_code, cached_prices = await self._select_service_code_for_country(str(service or ""), country_id)
        if not service_code:
            return {"success": False, "raw": "service_not_found"}
        if not selected_country_id:
            return {"success": False, "raw": "country_not_found"}

        data = cached_prices
        if not isinstance(data, dict) or service_code not in data:
            _status, data = await self._request("getPrices", service=service_code, country=selected_country_id)
        if not isinstance(data, dict):
            return {"success": False, "raw": data}

        service_prices = data.get(service_code)
        if not isinstance(service_prices, dict):
            return {"success": False, "raw": data}
        country_prices = service_prices.get(str(selected_country_id))
        if not isinstance(country_prices, dict):
            return {"success": False, "raw": data}

        prices = [_as_float(value) for value in country_prices.values()]
        prices = [value for value in prices if value is not None and value > 0]
        if not prices:
            return {"success": False, "raw": data}
        raw_slice = {service_code: {str(selected_country_id): dict(country_prices)}}

        return {
            "success": True,
            "price": float(min(prices)),
            "api_service_name": service_code,
            "provider_country": str(selected_country_id),
            "raw": raw_slice,
        }

    @staticmethod
    def _parse_access_number(raw: str) -> dict[str, Any] | None:
        text = str(raw or "").strip()
        if not text.upper().startswith("ACCESS_NUMBER:"):
            return None
        parts = text.split(":")
        if len(parts) < 3:
            return None
        return {"order_id": parts[1], "number": parts[2]}

    async def buy_number(self, service, country=None, state=None, **kwargs):
        country_id = await self._resolve_country(country)
        if not country_id:
            return {"success": False, "raw": "country_not_found"}
        service_code, _cached_prices = await self._select_service_code_for_country(str(service or ""), country_id)
        if not service_code:
            return {"success": False, "raw": "service_not_found"}

        max_price = kwargs.get("max_price")
        status, data = await self._request(
            "getNumberV2",
            service=service_code,
            country=country_id,
            maxPrice=max_price,
        )
        if status != 200:
            return {"success": False, "raw": data}
        if isinstance(data, str):
            parsed = self._parse_access_number(data)
            if parsed:
                return {"success": True, "order_id": parsed["order_id"], "number": parsed["number"], "raw": data}
        return {"success": False, "raw": data}

    async def get_sms(self, activation_id: str):
        status, data = await self._request("getStatus", id=activation_id)
        if status != 200:
            return {"success": False, "messages": [], "raw": data}
        if isinstance(data, str):
            text = data.strip()
            upper = text.upper()
            if upper == "STATUS_WAIT_CODE":
                return {"success": True, "messages": [], "raw": data}
            if upper.startswith("STATUS_OK:"):
                return {"success": True, "messages": [text.split(":", 1)[1]], "raw": data}
        return {"success": False, "messages": [], "raw": data}

    async def cancel(self, activation_id: str):
        status, data = await self._request("setStatus", id=activation_id, status=8)
        if status != 200:
            return {"success": False, "raw": data}
        if isinstance(data, str):
            text = data.strip().upper()
            ok_values = {"ACCESS_CANCEL", "ACCESS_CANCEL_ALREADY", "ACCESS_ACTIVATION"}
            if text in ok_values or text.startswith("ACCESS_") or text.startswith("STATUS_CANCEL"):
                return {"success": True, "raw": data}
        return {"success": False, "raw": data}

    async def resend(self, activation_id: str) -> bool:
        status, data = await self._request("setStatus", id=activation_id, status=3)
        if status != 200 or not isinstance(data, str):
            return False
        text = data.strip().upper()
        return _status_ok_string(text)
