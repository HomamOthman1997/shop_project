import logging
import re
import time
from difflib import SequenceMatcher
from typing import Any, Optional

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST

from .base_provider import BaseProvider

logger = logging.getLogger("smsman")


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _norm(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def _norm_country(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _tokenize(value: str) -> list[str]:
    return [_norm(token) for token in re.split(r"[^A-Za-z0-9]+", value or "") if _norm(token)]


class SMSManProvider(BaseProvider):
    DEFAULT_BASE = "https://api.sms-man.com/control"

    def __init__(self) -> None:
        self._services_cache: list[dict[str, Any]] = []
        self._services_cached_at: float = 0.0
        self._services_ttl_sec: int = 900
        self._countries_cache: list[dict[str, Any]] = []
        self._countries_cached_at: float = 0.0
        self._countries_ttl_sec: int = 3600

    @property
    def base_url(self) -> str:
        return (settings.smsman_base_url or self.DEFAULT_BASE).strip().rstrip("/")

    def _api_key(self) -> Optional[str]:
        key = (settings.smsman_key or "").strip()
        return key or None

    @staticmethod
    def _normalize_price_to_usd(raw_price: float) -> float:
        mode = str(getattr(settings, "smsman_price_currency", "RUB") or "RUB").strip().upper()
        if raw_price <= 0:
            return 0.0
        if mode == "USD":
            return float(raw_price)
        if mode == "CENTS_USD":
            return float(raw_price) / 100.0
        # Default: SMS-Man prices are interpreted as RUB and converted to USD.
        rate = _as_float(getattr(settings, "smsman_rub_to_usd_rate", 0.0112))
        if rate is None or rate <= 0:
            rate = 0.0112
        return float(raw_price) * float(rate)

    async def _session(self):
        return await SessionManager.get_session()

    async def _request(self, endpoint: str, **params) -> tuple[int, Any]:
        key = self._api_key()
        if not key:
            return 0, {"success": False, "error_code": "missing_api_key", "error_msg": "SMSMAN_KEY is not configured"}

        query: dict[str, Any] = {"token": key}
        for k, v in params.items():
            if v is None:
                continue
            query[k] = v

        url = f"{self.base_url}/{str(endpoint).strip().lstrip('/')}"
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
            logger.exception("SMS-Man request failed: endpoint=%s", endpoint)
            return 0, {"success": False, "error_code": "request_error", "error_msg": str(exc)}

    async def _limits_available(self, *, country_id: str | None, application_id: str) -> tuple[bool | None, Any]:
        """Return availability from /limits.

        Returns:
            (True, raw)  -> available
            (False, raw) -> explicitly unavailable
            (None, raw)  -> unknown (do not block buy)
        """
        params: dict[str, Any] = {"application_id": int(application_id)}
        if country_id is not None and str(country_id).isdigit():
            params["country_id"] = int(country_id)
        _status, data = await self._request("limits", **params)
        if self._is_error_payload(data):
            return None, data
        rows: list[dict[str, Any]] = []
        if isinstance(data, list):
            rows = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            # Some variants can return map-like payloads.
            rows = [item for item in data.values() if isinstance(item, dict)]

        if not rows:
            return None, data

        total = 0
        for row in rows:
            app = str(row.get("application_id") or "")
            c_id = str(row.get("country_id") or "")
            if app and app != str(application_id):
                continue
            if country_id is not None and c_id and c_id != str(country_id):
                continue
            total += int(_as_int(row.get("numbers")) or 0)
        return (total > 0), data

    @staticmethod
    def _is_error_payload(data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        if data.get("success") is False:
            return True
        error_code = str(data.get("error_code") or "").strip().lower()
        if error_code and error_code != "wait_sms":
            return True
        return False

    @staticmethod
    def _common_country_by_code() -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in COUNTRIES_LIST:
            code = str(row.get("code") or "").strip()
            if code:
                out[code] = row
        return out

    @staticmethod
    def _smsman_country_aliases(row: dict[str, Any]) -> set[str]:
        aliases: set[str] = set()
        title = str(row.get("title") or "").strip()
        title_key = _norm_country(title)
        if title_key:
            aliases.add(title_key)
        if title_key in {"usa", "unitedstates", "unitedstatesofamerica"}:
            aliases.update({"us", "usa", "unitedstates", "unitedstatesofamerica"})
        if title_key in {"uk", "unitedkingdom", "greatbritain", "britain"}:
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

        _status, data = await self._request("countries")
        countries: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            # New API variants return object keyed by country id.
            items = [item for item in data.values() if isinstance(item, dict)]
        for item in items:
            cid = _as_int(item.get("id"))
            if cid is None:
                continue
            countries.append({"id": cid, "title": str(item.get("title") or "").strip()})

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
            return raw if raw.isdigit() else None

        by_id: dict[str, str] = {}
        by_alias: dict[str, str] = {}
        for row in countries:
            cid = _as_int(row.get("id"))
            if cid is None:
                continue
            cid_s = str(cid)
            by_id[cid_s] = cid_s
            for alias in self._smsman_country_aliases(row):
                by_alias.setdefault(alias, cid_s)

        common = self._common_country_by_code()
        if raw in common:
            item = common[raw]
            iso = str(item.get("iso") or "").strip().lower()
            name = str(item.get("name") or "").strip()
            candidates = [_norm_country(name), _norm_country(iso), _norm_country(raw)]
            if iso == "us":
                candidates.extend(["us", "usa", "unitedstates", "unitedstatesofamerica"])
            if iso == "gb":
                candidates.extend(["gb", "uk", "unitedkingdom", "greatbritain", "england"])
            for candidate in candidates:
                if candidate and candidate in by_alias:
                    return by_alias[candidate]

        if raw in by_id:
            return by_id[raw]

        raw_norm = _norm_country(raw)
        if raw_norm in by_alias:
            return by_alias[raw_norm]

        if raw.isdigit():
            return raw
        return None

    async def list_services(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if (
            not force_refresh
            and self._services_cache
            and (now - self._services_cached_at) < self._services_ttl_sec
        ):
            return list(self._services_cache)

        _status, data = await self._request("applications")
        services: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            # New API variants return object keyed by application id.
            items = [item for item in data.values() if isinstance(item, dict)]
        for item in items:
            sid = _as_int(item.get("id"))
            if sid is None:
                continue
            services.append(
                {
                    "id": sid,
                    "code": str(item.get("code") or "").strip(),
                    # Older docs used "name"; current payload often uses "title".
                    "name": str(item.get("name") or item.get("title") or "").strip(),
                }
            )

        if services:
            self._services_cache = services
            self._services_cached_at = now
        return list(self._services_cache)

    async def resolve_service_code(self, service_key: str | int) -> str | None:
        raw = str(service_key or "").strip()
        if not raw:
            return None

        services = await self.list_services()
        if not services:
            return raw if raw.isdigit() else None

        by_id: dict[str, str] = {}
        by_code: dict[str, str] = {}
        by_name: dict[str, str] = {}
        token_hits: list[tuple[str, str]] = []
        for item in services:
            sid = str(item.get("id") or "").strip()
            if not sid:
                continue
            by_id[sid] = sid
            code = _norm(str(item.get("code") or ""))
            name = _norm(str(item.get("name") or ""))
            if code:
                by_code.setdefault(code, sid)
            if name:
                by_name.setdefault(name, sid)
            for token in _tokenize(str(item.get("name") or "")):
                token_hits.append((token, sid))

        if raw in by_id:
            return by_id[raw]

        raw_norm = _norm(raw)
        if raw_norm in by_code:
            return by_code[raw_norm]
        if raw_norm in by_name:
            return by_name[raw_norm]

        for token, sid in token_hits:
            if raw_norm and raw_norm == token:
                return sid

        best_sid = None
        best_score = 0.0
        for name_norm, sid in by_name.items():
            score = SequenceMatcher(None, raw_norm, name_norm).ratio()
            if score > best_score:
                best_score = score
                best_sid = sid
        if best_sid and best_score >= 0.72:
            return best_sid
        return None

    async def get_price(self, service, country=None, state=None):
        app_id = str(service or "").strip()
        if not app_id:
            return {"success": False, "raw": "missing_service"}
        if not app_id.isdigit():
            resolved = await self.resolve_service_code(app_id)
            if not resolved:
                return {"success": False, "raw": "service_not_found"}
            app_id = str(resolved)

        country_id = await self._resolve_country(country)
        params: dict[str, Any] = {}
        if country_id is not None:
            params["country_id"] = country_id

        _status, data = await self._request("get-prices", **params)
        if self._is_error_payload(data):
            return {"success": False, "raw": data}
        if not isinstance(data, dict):
            return {"success": False, "raw": data}

        candidates: list[dict[str, Any]] = []
        # SMS-Man may return one of two payload shapes for get-prices:
        # 1) {country_id: {application_id: {cost,count,...}}}
        # 2) {application_id: {cost,count,country_id,...}} (when country_id is passed)
        for top_key, top_payload in data.items():
            if not isinstance(top_payload, dict):
                continue

            app_payload: dict[str, Any] | None = None
            payload_country_id: str = str(top_key)

            nested_app_payload = top_payload.get(str(app_id))
            if isinstance(nested_app_payload, dict):
                # Shape (1): country -> apps map.
                app_payload = nested_app_payload
            elif str(top_key) == str(app_id) and "cost" in top_payload:
                # Shape (2): direct app payload map.
                app_payload = top_payload
                payload_country_id = str(top_payload.get("country_id") or country_id or "")

            if not isinstance(app_payload, dict):
                continue

            if country_id is not None and payload_country_id and str(payload_country_id) != str(country_id):
                continue

            price = _as_float(app_payload.get("cost"))
            count = _as_int(app_payload.get("count")) or 0
            if price is None or price <= 0:
                continue
            price_usd = self._normalize_price_to_usd(float(price))
            if price_usd <= 0:
                continue
            candidates.append(
                {
                    "price": price_usd,
                    "provider_price_raw": float(price),
                    "count": count,
                    "country_id": str(payload_country_id or country_id or ""),
                }
            )

        if not candidates:
            return {"success": False, "raw": data}

        chosen = min(candidates, key=lambda x: float(x.get("price") or 0))
        return {
            "success": True,
            "price": round(float(chosen["price"]), 4),
            "count": int(chosen.get("count") or 0),
            "api_service_name": app_id,
            "provider_price_raw": float(chosen.get("provider_price_raw") or 0),
            "provider_price_currency": str(getattr(settings, "smsman_price_currency", "RUB") or "RUB").upper(),
            "raw": data,
        }

    async def buy_number(self, service, country=None, state=None, **kwargs):
        app_id = str(service or "").strip()
        if not app_id:
            return {"success": False, "raw": "missing_service"}
        if not app_id.isdigit():
            resolved = await self.resolve_service_code(app_id)
            if not resolved:
                return {"success": False, "raw": "service_not_found"}
            app_id = str(resolved)

        country_id = await self._resolve_country(country)
        has_limits, limits_raw = await self._limits_available(country_id=country_id, application_id=app_id)
        if has_limits is False:
            return {
                "success": False,
                "raw": {
                    "success": False,
                    "error_code": "NO_NUMBERS",
                    "error_msg": "No numbers available by limits precheck",
                    "limits": limits_raw,
                },
            }
        params: dict[str, Any] = {
            "country_id": int(country_id) if str(country_id or "").isdigit() else 0,
            "application_id": int(app_id),
        }
        # Reuse mode asks SMS-Man for multi-sms capable numbers.
        if bool(kwargs.get("reuse_mode")):
            params["hasMultipleSms"] = "True"
        if hasattr(self, "max_price") and self.max_price is not None:
            max_price = _as_float(self.max_price)
            if max_price is not None and max_price > 0:
                params["maxPrice"] = max_price
                params["currency"] = "USD"

        _status, data = await self._request("get-number", **params)
        if self._is_error_payload(data):
            return {"success": False, "raw": data}
        if not isinstance(data, dict):
            return {"success": False, "raw": data}

        order_id = str(data.get("request_id") or "").strip()
        number = str(data.get("number") or "").strip()
        if not order_id or not number:
            return {"success": False, "raw": data}
        return {
            "success": True,
            "order_id": order_id,
            "number": number,
            "can_resend": bool(kwargs.get("reuse_mode")),
            "raw": data,
        }

    async def get_sms(self, activation_id: str):
        _status, data = await self._request("get-sms", request_id=activation_id)
        if isinstance(data, dict):
            err_code = str(data.get("error_code") or "").strip().lower()
            if err_code == "wait_sms":
                return {"success": True, "messages": [], "raw": data}
            if self._is_error_payload(data):
                return {"success": False, "messages": [], "raw": data}

            messages: list[str] = []
            sms_code = str(data.get("sms_code") or "").strip()
            if sms_code:
                messages.append(sms_code)
            return {"success": True, "messages": messages, "raw": data}

        return {"success": False, "messages": [], "raw": data}

    async def cancel(self, activation_id: str):
        # try refund-like path first, then hard close.
        for status_value in ("reject", "close"):
            _status, data = await self._request("set-status", request_id=activation_id, status=status_value)
            if isinstance(data, dict) and data.get("success") is True:
                return {"success": True, "raw": data}
        return {"success": False, "raw": data if "data" in locals() else "cancel_failed"}

    async def resend(self, activation_id: str) -> bool:
        # SMS-Man uses `ready` to continue receiving additional SMS on the same request.
        _status, data = await self._request("set-status", request_id=activation_id, status="ready")
        return isinstance(data, dict) and data.get("success") is True

    async def get_balance(self) -> Optional[float]:
        _status, data = await self._request("get-balance")
        if isinstance(data, dict):
            return _as_float(data.get("balance"))
        return None

    async def get_account(self) -> Optional[dict]:
        balance = await self.get_balance()
        if balance is None:
            return None
        return {"balance": balance}
