import logging
import re
import time
from typing import Any, Optional

from config import settings
from services.numbers.auto_country_policy import allows_auto_country_iso
from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST

from .base_provider import BaseProvider

logger = logging.getLogger("herosms")


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _norm(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def _norm_country(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _status_ok_string(value: str) -> bool:
    v = (value or "").strip().upper()
    return v.startswith("ACCESS_") or v.startswith("STATUS_")


class HeroSMSProvider(BaseProvider):
    DEFAULT_BASE = "https://hero-sms.com/stubs/handler_api.php"

    def __init__(self) -> None:
        self._services_cache: list[dict[str, Any]] = []
        self._services_cached_at: float = 0.0
        self._services_ttl_sec: int = 600
        self._countries_cache: list[dict[str, Any]] = []
        self._countries_cached_at: float = 0.0
        self._countries_ttl_sec: int = 3600

    @property
    def base_url(self) -> str:
        return (settings.herosms_base_url or self.DEFAULT_BASE).strip()

    def _api_key(self) -> Optional[str]:
        key = (settings.herosms_key or "").strip()
        return key or None

    async def _session(self):
        return await SessionManager.get_session()

    async def _request(self, action: str, **params) -> tuple[int, Any]:
        key = self._api_key()
        if not key:
            return 0, {"title": "MISSING_API_KEY", "details": "HEROSMS_KEY is not configured"}

        query: dict[str, Any] = {"api_key": key, "action": action}
        for k, v in params.items():
            if v is None:
                continue
            query[k] = v

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
            logger.exception("HeroSMS request failed: action=%s", action)
            return 0, {"title": "REQUEST_ERROR", "details": str(exc)}

    @staticmethod
    def _is_error_payload(data: Any) -> bool:
        if isinstance(data, dict):
            title = str(data.get("title") or "").strip().upper()
            if title:
                return title not in {"FINISHED", "REFUNDED", "CANCELED"}
            status = str(data.get("status") or "").strip().lower()
            if status == "false":
                return True
            return False
        if isinstance(data, str):
            v = data.strip().upper()
            if _status_ok_string(v):
                return False
            bad_prefixes = (
                "BAD_",
                "ERROR_",
                "NO_",
                "BANNED",
                "CHANNELS_LIMIT",
                "SQL_",
                "EARLY_CANCEL_DENIED",
                "OPERATORS_NOT_FOUND",
            )
            return v.startswith(bad_prefixes)
        return False

    @staticmethod
    def _extract_price(node: Any) -> list[float]:
        found: list[float] = []
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k).lower()
                if key in {"price", "cost", "retail_price", "activationcost"}:
                    price_val = _as_float(v)
                    if price_val is not None and price_val > 0:
                        found.append(price_val)
                else:
                    found.extend(HeroSMSProvider._extract_price(v))
        elif isinstance(node, list):
            for item in node:
                found.extend(HeroSMSProvider._extract_price(item))
        return found

    @staticmethod
    def _extract_rental_cost(data: dict[str, Any]) -> float | None:
        for key in ("cost", "activationCost", "price"):
            val = _as_float(data.get(key))
            if val is not None and val > 0:
                return val
        # Some samples contain a malformed key that visually looks like "cost".
        for k, v in data.items():
            if "ost" in str(k).lower():
                val = _as_float(v)
                if val is not None and val > 0:
                    return val
        return None

    @staticmethod
    def _parse_access_number(raw: str) -> dict[str, Any] | None:
        text = (raw or "").strip()
        upper = text.upper()
        if not upper.startswith("ACCESS_NUMBER:"):
            return None
        parts = text.split(":")
        if len(parts) < 3:
            return None
        return {"order_id": parts[1], "number": parts[2]}

    @staticmethod
    def _looks_no_numbers_error(payload: Any) -> bool:
        if isinstance(payload, str):
            text = payload.strip().upper()
            return text.startswith("NO_NUMBERS") or "NO NUMBERS" in text
        if isinstance(payload, dict):
            title = str(payload.get("title") or "").strip().upper()
            details = str(payload.get("details") or "").strip().upper()
            return title.startswith("NO_NUMBERS") or "NO NUMBERS" in details
        return False

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
        if isinstance(data, dict):
            raw = data.get("services")
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and item.get("code"):
                        services.append(item)
        if services:
            self._services_cache = services
            self._services_cached_at = now
        return list(self._services_cache)

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
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                cid = _as_int(item.get("id"))
                if cid is None or cid < 0:
                    continue
                countries.append(item)
        if countries:
            self._countries_cache = countries
            self._countries_cached_at = now
        return list(self._countries_cache)

    @staticmethod
    def _common_country_by_code() -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in COUNTRIES_LIST:
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            out[code] = row
        return out

    @staticmethod
    def _hero_country_aliases(row: dict[str, Any]) -> set[str]:
        aliases: set[str] = set()
        eng = str(row.get("eng") or "").strip()
        rus = str(row.get("rus") or "").strip()
        chn = str(row.get("chn") or "").strip()
        for value in (eng, rus, chn):
            key = _norm_country(value)
            if key:
                aliases.add(key)
        eng_key = _norm_country(eng)
        if eng_key == "usa":
            aliases.update({"unitedstates", "us", "usa", "unitedstatesofamerica"})
        if eng_key == "unitedkingdom":
            aliases.update({"uk", "gb", "britain", "greatbritain", "england"})
        return aliases

    async def _hero_country_id_to_iso(self, country_id: Any) -> str | None:
        cid = str(country_id or "").strip()
        if not cid:
            return None
        countries = await self.list_countries()
        if not countries:
            return None
        for row in countries:
            if str(_as_int(row.get("id")) or "") != cid:
                continue
            eng = str(row.get("eng") or "").strip()
            eng_key = _norm_country(eng)
            if eng_key == "palestine":
                return "PS"
            if eng_key in {"usa", "unitedstates", "unitedstatesofamerica"}:
                return "US"
            if eng_key in {"unitedkingdom", "greatbritain", "england"}:
                return "GB"
            common = self._common_country_by_code()
            for item in common.values():
                iso = str(item.get("iso") or "").strip().upper()
                name = str(item.get("name") or "").strip()
                if _norm_country(name) == eng_key and iso:
                    return iso
            if len(eng) == 2 and eng.isalpha():
                return eng.upper()
            return None
        return None

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
            cid = _as_int(row.get("id"))
            if cid is None:
                continue
            cid_s = str(cid)
            by_id[cid_s] = cid_s
            for alias in self._hero_country_aliases(row):
                by_alias.setdefault(alias, cid_s)

        # 1) interpret bot's common country codes first (critical: "1" is US in bot, not Hero).
        common = self._common_country_by_code()
        if raw in common:
            item = common[raw]
            iso = str(item.get("iso") or "").strip().lower()
            name = str(item.get("name") or "").strip()
            candidates = [_norm_country(name), _norm_country(iso)]
            if iso == "us":
                candidates.extend(["usa", "unitedstates"])
            elif iso == "gb":
                candidates.extend(["uk", "unitedkingdom"])
            for key in candidates:
                if key and key in by_alias:
                    return by_alias[key]
            return None

        # 2) allow ISO/name lookup.
        lowered = raw.lower()
        for key in (_norm_country(raw), _norm_country(lowered)):
            if key in by_alias:
                return by_alias[key]

        # 3) if caller passed Hero country id directly, keep it.
        if raw in by_id:
            return raw

        return raw

    async def resolve_service_code(self, service_hint: str) -> str | None:
        hint = (service_hint or "").strip()
        if not hint:
            return None
        # HeroSMS service codes are typically short (e.g. tg, wa, ig).
        if len(hint) <= 4 and " " not in hint and hint == hint.lower():
            return hint

        services = await self.list_services()
        if not services:
            return None

        norm_hint = _norm(hint)
        # Prefer token-aware partial matches before fuzzy scoring.
        # Example: "Google,youtube,Gmail" should map `gmail` -> `go`.
        def _tokens(name: str) -> list[str]:
            raw = (name or "")
            for sep in (",", "/", "+", "|", ";"):
                raw = raw.replace(sep, " ")
            return [_norm(tok) for tok in raw.split() if tok.strip()]

        for item in services:
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or "").strip()
            if not code:
                continue
            name_tokens = _tokens(name)
            if any(tok == norm_hint for tok in name_tokens):
                return code
            if any(norm_hint and norm_hint in tok for tok in name_tokens):
                return code

        for item in services:
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or "").strip()
            if not code:
                continue
            if _norm(code) == norm_hint or _norm(name) == norm_hint:
                return code
        return None

    async def get_price(self, service, country=None, state=None):
        params: dict[str, Any] = {"service": service}
        mapped_country = await self._resolve_country(country)
        if mapped_country is not None:
            params["country"] = mapped_country
        _status, data = await self._request("getPrices", **params)
        if self._is_error_payload(data):
            return {"success": False, "raw": data}

        prices = self._extract_price(data)
        if not prices:
            return {"success": False, "raw": data}

        provider_country_iso: str | None = None
        provider_country: str | None = None
        if mapped_country is None and isinstance(data, dict):
            best_country_id: str | None = None
            best_price: float | None = None
            for country_key, service_block in data.items():
                if not isinstance(service_block, dict):
                    continue
                country_iso = await self._hero_country_id_to_iso(country_key)
                if not allows_auto_country_iso(country_iso):
                    continue
                service_row = service_block.get(str(service))
                if not isinstance(service_row, dict):
                    continue
                cost = _as_float(service_row.get("cost"))
                if cost is None or cost <= 0:
                    continue
                if best_price is None or cost < best_price:
                    best_price = float(cost)
                    best_country_id = str(country_key)
            if best_country_id:
                provider_country = best_country_id
                provider_country_iso = await self._hero_country_id_to_iso(best_country_id)
                prices = [best_price] if best_price is not None else []
            else:
                prices = []
            if not prices:
                return {"success": False, "raw": data}

        result = {
            "success": True,
            "price": min(prices),
            "api_service_name": str(service),
            "raw": data,
        }
        if provider_country_iso:
            result["provider_country_iso"] = provider_country_iso
        if provider_country:
            result["provider_country"] = provider_country
        return result

    async def buy_number(self, service, country=None, state=None):
        mapped_country = await self._resolve_country(country)
        if mapped_country is None:
            return {"success": False, "raw": {"title": "BAD_COUNTRY", "details": "country is required"}}

        service_candidates: list[str] = [str(service or "").strip()]
        norm_service = _norm(str(service or ""))
        # Twitter sometimes appears as tw/x/twitter across mirrors.
        if norm_service in {"tw", "twitter", "x"}:
            for alias in ("tw", "x", "twitter"):
                if alias not in service_candidates:
                    service_candidates.append(alias)

        last_raw: Any = {"title": "UNKNOWN_ERROR", "details": "No response from provider"}

        async def _try_buy(service_code: str, country_code: str | None) -> tuple[bool, Any, str | None, str | None]:
            req_params = {"service": service_code}
            if country_code is not None:
                req_params["country"] = country_code

            _status, data = await self._request("getNumberV2", **req_params)
            if isinstance(data, dict) and not self._is_error_payload(data):
                order_id = str(data.get("activationId") or data.get("id") or "")
                number = str(data.get("phoneNumber") or data.get("number") or "")
                if order_id and number:
                    return True, data, order_id, number
            if isinstance(data, str):
                parsed = self._parse_access_number(data)
                if parsed:
                    return True, data, parsed["order_id"], parsed["number"]

            _status2, data2 = await self._request("getNumber", **req_params)
            if isinstance(data2, str):
                parsed = self._parse_access_number(data2)
                if parsed:
                    return True, data2, parsed["order_id"], parsed["number"]
            return False, data2, None, None

        for svc in service_candidates:
            ok, raw, order_id, number = await _try_buy(svc, mapped_country)
            if ok and order_id and number:
                return {"success": True, "order_id": order_id, "number": number, "raw": raw}
            last_raw = raw

            # Fallback: when country is temporarily exhausted, retry once without country pin.
            if mapped_country is not None and self._looks_no_numbers_error(raw):
                ok2, raw2, order_id2, number2 = await _try_buy(svc, None)
                if ok2 and order_id2 and number2:
                    return {"success": True, "order_id": order_id2, "number": number2, "raw": raw2}
                last_raw = raw2

        return {"success": False, "raw": last_raw}

    async def get_sms(self, activation_id):
        status, data = await self._request("getStatus", id=activation_id)
        if self._is_error_payload(data):
            return {"success": False, "messages": [], "raw": data}

        messages: list[str] = []
        if isinstance(data, str):
            text = data.strip()
            upper = text.upper()
            if upper.startswith("STATUS_OK:"):
                _, _, code = text.partition(":")
                code = code.strip()
                if code:
                    messages.append(code)
            elif _status_ok_string(upper):
                pass
            else:
                messages.append(text)
        elif isinstance(data, dict):
            sms = data.get("sms")
            if isinstance(sms, dict):
                code = str(sms.get("code") or "").strip()
                text = str(sms.get("text") or "").strip()
                if code:
                    messages.append(code)
                elif text:
                    messages.append(text)

        return {"success": status in (200, 204), "messages": messages, "raw": data}

    async def cancel(self, activation_id):
        # Primary cancel path for one-time activations is status=-1.
        status, data = await self._request("setStatus", id=activation_id, status=-1)
        if isinstance(data, str):
            marker = data.strip().upper()
            if marker == "ACCESS_CANCEL":
                return {"success": True, "raw": data}
            if marker == "EARLY_CANCEL_DENIED":
                return {"success": False, "raw": data, "retryable": True, "reason": "early_cancel_denied"}
        if isinstance(data, dict):
            title = str(data.get("title") or "").upper()
            if title in {"CANCELED", "REFUNDED"}:
                return {"success": True, "raw": data}

        # Legacy mirrors may only honor status=8 cancel semantics.
        status_legacy, data_legacy = await self._request("setStatus", id=activation_id, status=8)
        if isinstance(data_legacy, str):
            marker = data_legacy.strip().upper()
            if marker == "ACCESS_CANCEL":
                return {"success": True, "raw": data_legacy}
            if marker == "EARLY_CANCEL_DENIED":
                return {"success": False, "raw": data_legacy, "retryable": True, "reason": "early_cancel_denied"}
        if isinstance(data_legacy, dict):
            title = str(data_legacy.get("title") or "").upper()
            if title in {"CANCELED", "REFUNDED"}:
                return {"success": True, "raw": data_legacy}

        status2, data2 = await self._request("cancelActivation", id=activation_id)
        ok = status2 in (200, 204)
        if isinstance(data2, dict):
            title = str(data2.get("title") or "").upper()
            if title in {"CANCELED", "REFUNDED"}:
                ok = True
        retryable = False
        if isinstance(data2, str) and data2.strip().upper() == "EARLY_CANCEL_DENIED":
            retryable = True
        return {"success": ok, "raw": data2, "retryable": retryable}

    async def resend(self, activation_id: str) -> bool:
        # HeroSMS follows classic handler API patterns where status=3 requests another SMS.
        _status, data = await self._request("setStatus", id=activation_id, status=3)
        if isinstance(data, str):
            marker = data.strip().upper()
            if marker.startswith("ACCESS_") or marker.startswith("STATUS_"):
                return True
        if isinstance(data, dict):
            title = str(data.get("title") or "").upper()
            if title in {"FINISHED", "OK"}:
                return True
            if data.get("success") is True:
                return True
        return False

    async def get_balance(self) -> Optional[float]:
        _status, data = await self._request("getBalance")
        if isinstance(data, str) and data.upper().startswith("ACCESS_BALANCE:"):
            _, _, amount = data.partition(":")
            return _as_float(amount)
        if isinstance(data, dict):
            bal = _as_float(data.get("balance"))
            if bal is not None:
                return bal
        return None

    async def get_account(self) -> Optional[dict]:
        balance = await self.get_balance()
        if balance is None:
            return None
        return {"balance": balance}

    async def get_rental_prices(
        self,
        service: str,
        country: str | None = None,
        operator: str | None = None,
        currency: int | None = 840,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"service": service}
        mapped_country = await self._resolve_country(country)
        if mapped_country is not None:
            params["country"] = mapped_country
        if operator:
            params["operator"] = operator
        if currency is not None:
            params["currency"] = currency

        _status, data = await self._request("serviceCountRent", **params)
        if self._is_error_payload(data):
            return {"success": False, "options": [], "raw": data}

        wanted_country = str(mapped_country) if mapped_country is not None else None
        options: list[dict[str, Any]] = []

        if isinstance(data, dict):
            for country_key, durations in data.items():
                c_key = str(country_key)
                if wanted_country and c_key != wanted_country:
                    continue
                if not isinstance(durations, dict):
                    continue
                for duration_key, payload in durations.items():
                    if not isinstance(payload, dict):
                        continue
                    dur = _as_int(duration_key)
                    price = _as_float(payload.get("price"))
                    count = _as_int(payload.get("count")) or 0
                    if dur is None or price is None or price <= 0:
                        continue
                    options.append(
                        {
                            "country": c_key,
                            "duration": dur,
                            "price": price,
                            "count": max(0, count),
                        }
                    )

        options.sort(key=lambda x: (x["duration"], x["price"]))
        return {"success": bool(options), "options": options, "raw": data}

    async def rent_number(
        self,
        service: str,
        country: str,
        duration: int,
        operator: str | None = None,
        currency: int | None = 840,
        ref: str | None = None,
    ) -> dict[str, Any]:
        mapped_country = await self._resolve_country(country)
        if mapped_country is None:
            return {"success": False, "raw": {"title": "BAD_COUNTRY", "details": "country is required"}}
        params: dict[str, Any] = {
            "service": service,
            "country": mapped_country,
            "duration": int(duration),
        }
        if operator:
            params["operator"] = operator
        if currency is not None:
            params["currency"] = currency
        if ref:
            params["ref"] = ref

        _status, data = await self._request("getRentNumber", **params)
        if isinstance(data, dict) and not self._is_error_payload(data):
            order_id = str(data.get("id") or data.get("activationId") or "").strip()
            number = str(data.get("phoneNumber") or data.get("number") or "").strip()
            if order_id and number:
                price = self._extract_rental_cost(data)
                if price is None:
                    price = _as_float(data.get("activationCost"))
                return {
                    "success": True,
                    "order_id": order_id,
                    "number": number,
                    "price": price,
                    "end_date": data.get("endDate") or data.get("activationEndTime"),
                    "raw": data,
                }
        return {"success": False, "raw": data}

    async def get_rental_sms(self, activation_id: str, size: int = 20, page: int = 1) -> dict[str, Any]:
        _status, data = await self._request("getAllSms", id=activation_id, size=size, page=page)
        if self._is_error_payload(data):
            return {"success": False, "messages": [], "raw": data}

        messages: list[str] = []
        if isinstance(data, dict):
            rows = data.get("data")
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    code = str(row.get("code") or "").strip()
                    text = str(row.get("text") or "").strip()
                    if code:
                        messages.append(code)
                    elif text:
                        messages.append(text)

        return {"success": True, "messages": messages, "raw": data}

    async def finish_rental(self, activation_id: str) -> dict[str, Any]:
        status, data = await self._request("finishActivation", id=activation_id)
        if status in (200, 204):
            return {"success": True, "raw": data}
        if isinstance(data, dict):
            title = str(data.get("title") or "").upper()
            if title in {"FINISHED", "CANCELED", "REFUNDED"}:
                return {"success": True, "raw": data}
        return {"success": False, "raw": data}
