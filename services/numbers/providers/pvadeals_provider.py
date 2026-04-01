import asyncio
import logging
import time
from typing import Any, Optional

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST

from .base_provider import BaseProvider

logger = logging.getLogger("pvadeals")


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


class PVADealsProvider(BaseProvider):
    DEFAULT_BASE = "https://prod-v3.pvadeals.com/v3/api"
    SERVICE_CACHE_TTL_SECONDS = 600
    RETRY_DELAYS: tuple[float, ...] = (0.4, 1.0)
    RENTAL_PRICE_FIELDS: tuple[tuple[str, int, str], ...] = (
        ("LTR3price", 3, "3d"),
        ("LTR7price", 7, "7d"),
        ("LTR14price", 14, "14d"),
        ("LTR30price", 30, "30d"),
    )

    def __init__(self) -> None:
        self._services_cache: list[dict[str, Any]] = []
        self._services_cached_at: float = 0.0

    @property
    def base_url(self) -> str:
        return str(getattr(settings, "pvadeals_base_url", None) or self.DEFAULT_BASE).strip().rstrip("/")

    def _api_key(self) -> Optional[str]:
        key = str(getattr(settings, "pvadeals_key", None) or "").strip()
        return key or None

    async def _session(self):
        return await SessionManager.get_session()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, Any, dict[str, str]]:
        api_key = self._api_key()
        if not api_key:
            return 0, {"error_code": "missing_api_key", "message": "PVADEALS_KEY is not configured"}, {}

        session = await self._session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        if json_payload is not None:
            headers["Content-Type"] = "application/json"

        delays = list(self.RETRY_DELAYS)
        for attempt in range(len(delays) + 1):
            try:
                async with session.request(
                    str(method or "GET").upper(),
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=json_payload,
                    params=params,
                    timeout=20,
                ) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {"raw_text": text}
                    if resp.status != 429 or attempt >= len(delays):
                        return resp.status, data, dict(resp.headers)
                    retry_after = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
                    try:
                        delay = float(retry_after) if retry_after not in (None, "") else delays[attempt]
                    except Exception:
                        delay = delays[attempt]
                    logger.warning("pvadeals rate limited path=%s attempt=%s", path, attempt + 1)
                    await asyncio.sleep(max(0.2, min(delay, 5.0)))
            except Exception as exc:
                logger.warning("pvadeals request failed path=%s error=%s", path, exc)
                return 0, {"error_code": "request_failed", "message": str(exc)}, {}
        return 0, {"error_code": "request_failed", "message": "request_failed"}, {}

    @staticmethod
    def _response_ok(status: int, payload: Any) -> bool:
        if status not in (200, 201, 204):
            return False
        if isinstance(payload, dict) and "success" in payload:
            return bool(payload.get("success"))
        return True

    @staticmethod
    def _extract_data(payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data")
        return payload

    @staticmethod
    def _country_aliases() -> dict[str, str]:
        aliases: dict[str, str] = {}
        for row in COUNTRIES_LIST:
            code = str(row.get("code") or "").strip()
            iso = str(row.get("iso") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            if code:
                aliases[_norm(code)] = name
            if iso:
                aliases[_norm(iso)] = name
            if name:
                aliases[_norm(name)] = name
        aliases.setdefault("us", "USA")
        aliases.setdefault("usa", "USA")
        aliases.setdefault("unitedstates", "USA")
        aliases.setdefault("unitedstatesofamerica", "USA")
        return aliases

    @classmethod
    def _country_target(cls, country: Any) -> str:
        raw = str(country or "").strip()
        if not raw or raw.lower() == "none":
            return ""
        aliases = cls._country_aliases()
        return aliases.get(_norm(raw), raw)

    @classmethod
    def _country_candidates(cls, country: Any) -> set[str]:
        raw = str(country or "").strip()
        if not raw or raw.lower() == "none":
            return set()
        target = cls._country_target(raw)
        candidates = {_norm(raw), _norm(target)}
        if _norm(target) in {"unitedstates", "unitedstatesofamerica", "us", "usa"}:
            candidates.update({"us", "usa", "unitedstates", "unitedstatesofamerica"})
        if _norm(target) in {"unitedkingdom", "uk", "gb", "greatbritain"}:
            candidates.update({"uk", "gb", "unitedkingdom", "greatbritain"})
        return {item for item in candidates if item}

    @classmethod
    def _service_country_matches(cls, service_country: Any, wanted_country: Any) -> bool:
        wanted_candidates = cls._country_candidates(wanted_country)
        if not wanted_candidates:
            return True
        service_candidates = cls._country_candidates(service_country)
        if not service_candidates:
            service_candidates = {_norm(service_country)}
        return bool(service_candidates & wanted_candidates)

    async def list_services(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if (
            not force_refresh
            and self._services_cache
            and (now - self._services_cached_at) < self.SERVICE_CACHE_TTL_SECONDS
        ):
            return list(self._services_cache)

        status, payload, _headers = await self._request("GET", "/services/all")
        services: list[dict[str, Any]] = []
        data = self._extract_data(payload)
        if self._response_ok(status, payload) and isinstance(data, dict):
            raw_services = data.get("services")
            if isinstance(raw_services, list):
                services = [row for row in raw_services if isinstance(row, dict) and row.get("_id") and row.get("name")]
        if services:
            self._services_cache = services
            self._services_cached_at = now
        return list(self._services_cache)

    async def _find_service_entry(
        self,
        service_hint: Any,
        *,
        country: Any = None,
        require_temp: bool = False,
        require_rental: bool = False,
    ) -> dict[str, Any] | None:
        raw = str(service_hint or "").strip()
        if not raw:
            return None
        target = _norm(raw)
        services = await self.list_services()
        if not services:
            return None

        exact_id = next(
            (
                row
                for row in services
                if str(row.get("_id") or "").strip() == raw
                and self._service_country_matches(row.get("country"), country)
            ),
            None,
        )
        if exact_id and (not require_temp or _as_float(exact_id.get("STRprice")) not in (None, 0.0)):
            if not require_rental or any(_as_float(exact_id.get(field)) not in (None, 0.0) for field, _, _ in self.RENTAL_PRICE_FIELDS):
                return exact_id

        candidates: list[dict[str, Any]] = []
        for row in services:
            if not self._service_country_matches(row.get("country"), country):
                continue
            name = str(row.get("name") or "").strip()
            if _norm(name) != target:
                continue
            if require_temp and (_as_float(row.get("STRprice")) in (None, 0.0)):
                continue
            if require_rental and not any(_as_float(row.get(field)) not in (None, 0.0) for field, _, _ in self.RENTAL_PRICE_FIELDS):
                continue
            candidates.append(row)
        if candidates:
            return candidates[0]

        for row in services:
            if not self._service_country_matches(row.get("country"), country):
                continue
            name = str(row.get("name") or "").strip()
            if target and target in _norm(name):
                if require_temp and (_as_float(row.get("STRprice")) in (None, 0.0)):
                    continue
                if require_rental and not any(_as_float(row.get(field)) not in (None, 0.0) for field, _, _ in self.RENTAL_PRICE_FIELDS):
                    continue
                return row
        return None

    async def _find_cheapest_service_entry(
        self,
        service_hint: Any,
        *,
        require_temp: bool = False,
        require_rental: bool = False,
    ) -> dict[str, Any] | None:
        raw = str(service_hint or "").strip()
        if not raw:
            return None
        target = _norm(raw)
        services = await self.list_services()
        if not services:
            return None

        exact_id = next(
            (
                row
                for row in services
                if str(row.get("_id") or "").strip() == raw
            ),
            None,
        )
        if exact_id and (not require_temp or _as_float(exact_id.get("STRprice")) not in (None, 0.0)):
            if not require_rental or any(_as_float(exact_id.get(field)) not in (None, 0.0) for field, _, _ in self.RENTAL_PRICE_FIELDS):
                return exact_id

        matches: list[dict[str, Any]] = []
        for row in services:
            name = str(row.get("name") or "").strip()
            if _norm(name) != target:
                continue
            if require_temp and (_as_float(row.get("STRprice")) in (None, 0.0)):
                continue
            if require_rental and not any(_as_float(row.get(field)) not in (None, 0.0) for field, _, _ in self.RENTAL_PRICE_FIELDS):
                continue
            matches.append(row)

        if not matches:
            for row in services:
                name = str(row.get("name") or "").strip()
                if target and target in _norm(name):
                    if require_temp and (_as_float(row.get("STRprice")) in (None, 0.0)):
                        continue
                    if require_rental and not any(_as_float(row.get(field)) not in (None, 0.0) for field, _, _ in self.RENTAL_PRICE_FIELDS):
                        continue
                    matches.append(row)

        if not matches:
            return None

        def _price_key(row: dict[str, Any]) -> tuple[float, str]:
            if require_temp:
                price = _as_float(row.get("STRprice"))
            else:
                rental_prices = [
                    _as_float(row.get(field))
                    for field, _, _ in self.RENTAL_PRICE_FIELDS
                ]
                valid = [value for value in rental_prices if value not in (None, 0.0)]
                price = min(valid) if valid else None
            return (float(price) if price not in (None, 0.0) else float("inf"), str(row.get("country") or ""))

        matches.sort(key=_price_key)
        return matches[0]

    async def get_account(self) -> Optional[dict]:
        status, payload, _headers = await self._request("GET", "/balance")
        if not self._response_ok(status, payload):
            return None
        return payload if isinstance(payload, dict) else None

    async def get_balance(self) -> Optional[float]:
        payload = await self.get_account()
        data = self._extract_data(payload)
        if isinstance(data, dict):
            for key in ("credits", "balance", "amount"):
                parsed = _as_float(data.get(key))
                if parsed is not None:
                    return parsed
        return None

    async def resolve_service_code(self, service_hint: Any, country: Any = None) -> str | None:
        entry = await self._find_service_entry(service_hint, country=country)
        if not entry:
            return None
        return str(entry.get("_id") or "").strip() or None

    async def get_price(self, service, country=None, state=None):
        if country in (None, "", "none"):
            entry = await self._find_cheapest_service_entry(service, require_temp=True)
        else:
            entry = await self._find_service_entry(service, country=country, require_temp=True)
        if not entry:
            return {"success": False, "raw": "service_not_found"}
        price = _as_float(entry.get("STRprice"))
        if price is None or price <= 0:
            return {"success": False, "raw": entry}
        return {
            "success": True,
            "price": float(price),
            "api_service_name": str(entry.get("name") or service),
            "provider_country": str(entry.get("country") or ""),
            "raw": entry,
        }

    async def buy_number(self, service, country=None, state=None, **kwargs):
        entry = await self._find_service_entry(service, country=country, require_temp=True)
        if not entry:
            return {"success": False, "raw": "service_not_found"}

        body: dict[str, Any] = {"services": [{"serviceId": str(entry.get("_id"))}]}
        area_code = str(kwargs.get("area_code") or kwargs.get("areacode") or "").strip()
        if area_code:
            body["services"][0]["areaCode"] = area_code

        status, payload, _headers = await self._request("POST", "/purchase", json_payload=body)
        data = self._extract_data(payload)
        if not self._response_ok(status, payload):
            return {"success": False, "raw": payload}

        request_row = None
        if isinstance(data, dict):
            if isinstance(data.get("requests"), list) and data.get("requests"):
                first = data["requests"][0]
                if isinstance(first, dict):
                    request_row = first
            elif isinstance(data.get("request"), dict):
                request_row = data.get("request")
            else:
                request_row = data

        if not isinstance(request_row, dict):
            return {"success": False, "raw": payload}

        order_id = str(request_row.get("_id") or request_row.get("requestId") or "").strip()
        number = str(request_row.get("number") or "").strip()
        if not order_id or not number:
            return {"success": False, "raw": payload}
        return {"success": True, "order_id": order_id, "number": number, "raw": payload}

    @staticmethod
    def _extract_messages_from_request(data: dict[str, Any]) -> list[str]:
        messages: list[str] = []
        fields = (
            "code",
            "verificationCode",
            "lastMessage",
            "latestMessage",
            "content",
            "messageBody",
            "sms",
        )
        for key in fields:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                messages.append(value.strip())
        nested = data.get("messages")
        if isinstance(nested, list):
            for row in nested:
                if isinstance(row, str) and row.strip():
                    messages.append(row.strip())
                elif isinstance(row, dict):
                    for key in ("message", "content", "body", "code"):
                        value = row.get(key)
                        if isinstance(value, str) and value.strip():
                            messages.append(value.strip())
        # Preserve order while deduplicating.
        out: list[str] = []
        for item in messages:
            if item not in out:
                out.append(item)
        return out

    async def get_sms(self, activation_id: str):
        status, payload, _headers = await self._request("GET", f"/request/{activation_id}")
        data = self._extract_data(payload)
        if not self._response_ok(status, payload) or not isinstance(data, dict):
            return {"success": False, "messages": [], "raw": payload}
        messages = self._extract_messages_from_request(data)
        return {"success": True, "messages": messages, "raw": payload}

    async def cancel(self, activation_id: str):
        status, payload, _headers = await self._request("POST", f"/flag/{activation_id}")
        ok = self._response_ok(status, payload)
        if isinstance(payload, dict):
            data = self._extract_data(payload)
            if data is True:
                ok = True
        return {"success": ok, "raw": payload}

    async def resend(self, activation_id: str) -> bool:
        status, payload, _headers = await self._request("POST", f"/reuse/{activation_id}")
        return self._response_ok(status, payload)

    async def get_rental_prices(self, service: str, country: str | None = None) -> dict[str, Any]:
        entry = await self._find_service_entry(service, country=country, require_rental=True)
        if not entry:
            return {"success": False, "options": [], "raw": "service_not_found"}
        options: list[dict[str, Any]] = []
        for field, days, label in self.RENTAL_PRICE_FIELDS:
            price = _as_float(entry.get(field))
            if price is None or price <= 0:
                continue
            options.append(
                {
                    "country": str(entry.get("country") or country or "provider"),
                    "duration": int(days * 24),
                    "duration_days": int(days),
                    "duration_label": label,
                    "price": float(price),
                    "count": 1,
                }
            )
        return {"success": bool(options), "options": options, "raw": entry}

    async def rent_number(self, service: str, country: str | None = None, duration: int = 3, **kwargs) -> dict[str, Any]:
        days = int(kwargs.get("duration_days") or duration or 3)
        if days not in {3, 7, 14, 30}:
            days = 3
        entry = await self._find_service_entry(service, country=country, require_rental=True)
        if not entry:
            return {"success": False, "raw": "service_not_found"}

        body: dict[str, Any] = {"serviceId": str(entry.get("_id")), "duration": days}
        area_code = str(kwargs.get("area_code") or kwargs.get("areacode") or "").strip()
        if area_code:
            body["areaCode"] = area_code

        status, payload, _headers = await self._request("POST", "/purchase-ltr", json_payload=body)
        data = self._extract_data(payload)
        if not self._response_ok(status, payload):
            return {"success": False, "raw": payload}

        request_row = None
        if isinstance(data, dict):
            if isinstance(data.get("requests"), list) and data.get("requests"):
                first = data["requests"][0]
                if isinstance(first, dict):
                    request_row = first
            elif isinstance(data.get("request"), dict):
                request_row = data.get("request")
            else:
                request_row = data

        if not isinstance(request_row, dict):
            return {"success": False, "raw": payload}

        order_id = str(request_row.get("_id") or request_row.get("requestId") or "").strip()
        number = str(request_row.get("number") or "").strip()
        end_date = request_row.get("endTime")
        price = _as_float(request_row.get("amount"))
        if price is None:
            field_name = f"LTR{days}price"
            price = _as_float(entry.get(field_name))
        if not order_id or not number:
            return {"success": False, "raw": payload}
        return {
            "success": True,
            "order_id": order_id,
            "number": number,
            "price": price,
            "end_date": end_date,
            "raw": payload,
        }

    async def get_rental_sms(self, activation_id: str, size: int = 20, page: int = 1) -> dict[str, Any]:
        return await self.get_sms(activation_id)

    async def get_rental_info(self, activation_id: str) -> dict[str, Any]:
        status, payload, _headers = await self._request("GET", f"/request/{activation_id}")
        data = self._extract_data(payload)
        if not self._response_ok(status, payload) or not isinstance(data, dict):
            return {"success": False, "raw": payload}
        return {
            "success": True,
            "allow_flag": bool(data.get("allowFlag")) if "allowFlag" in data else None,
            "allow_reuse": bool(data.get("allowReuse")) if "allowReuse" in data else None,
            "end_date": data.get("endTime"),
            "status": data.get("status"),
            "raw": payload,
        }

    async def finish_rental(self, activation_id: str) -> dict[str, Any]:
        return await self.cancel(activation_id)

    async def renew_rental(self, activation_id: str) -> dict[str, Any]:
        status, payload, _headers = await self._request("POST", f"/renew-ltr/{activation_id}")
        return {"success": self._response_ok(status, payload), "raw": payload}

    async def wake_rental(self, activation_id: str) -> dict[str, Any]:
        return {"success": False, "raw": "wake_not_supported"}
