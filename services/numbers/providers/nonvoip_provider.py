import json
import logging
import re
import time
from typing import Any, Optional

from config import settings
from services.numbers.core.session_manager import SessionManager

from .base_provider import BaseProvider

logger = logging.getLogger("nonvoip")


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _norm(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def _strip_tail_variant(value: str) -> str:
    # "yahoo5" -> "yahoo", "yahoo4uk" keeps as-is (not pure numeric suffix).
    return re.sub(r"\d+$", "", _norm(value))


class NonVoipProvider(BaseProvider):
    """Non-VoIP reseller provider adapter."""

    DEFAULT_BASE = "https://www.non-voip.com/api/reseller"

    def __init__(self) -> None:
        self._services_cache: list[dict[str, Any]] = []
        self._services_cached_at: float = 0.0
        self._services_ttl_sec: int = 300

    @property
    def base_url(self) -> str:
        base = settings.nonvoip_base_url or self.DEFAULT_BASE
        normalized = str(base).strip().rstrip("/")
        if normalized.startswith("https://non-voip.com/"):
            return normalized.replace("https://non-voip.com/", "https://www.non-voip.com/", 1)
        if normalized == "https://non-voip.com":
            return "https://www.non-voip.com"
        return normalized

    def _api_key(self) -> Optional[str]:
        key = settings.nonvoip_key or ""
        key = str(key).strip()
        return key or None

    def _email(self) -> Optional[str]:
        email = str(getattr(settings, "nonvoip_email", None) or "").strip()
        return email or None

    async def _session(self):
        return await SessionManager.get_session()

    async def _request(
        self,
        command: str,
        payload: dict[str, Any] | None = None,
        **params: Any,
    ) -> tuple[int, Any]:
        key = self._api_key()
        if not key:
            return 0, {"code": "400", "message": "missing_api_key"}
        email = self._email()
        if not email:
            return 0, {"code": "400", "message": "missing_email"}

        payload = dict(payload or {})
        payload.update({k: v for k, v in params.items() if v is not None})
        url = f"{self.base_url}/{command}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "email": email,
            "api_key": key,
            "x-non-api-key": key,
            "x-api-key": key,
            "authorization": key,
        }

        try:
            session = await self._session()
            async with session.post(url, json=payload, headers=headers, timeout=20) as resp:
                status = int(resp.status)

                # Some variants send result in "api-result" header.
                hdr_result = resp.headers.get("api-result")
                if hdr_result:
                    try:
                        return status, json.loads(hdr_result)
                    except Exception:
                        pass

                text = await resp.text()
                if not text:
                    return status, {}
                try:
                    return status, await resp.json(content_type=None)
                except Exception:
                    return status, {"raw_text": text}
        except Exception as exc:
            logger.warning("nonvoip request failed: %s %s", command, exc)
            return 0, {"code": "400", "message": str(exc)}

    @staticmethod
    def _is_error(data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        code = str(data.get("code") or "").strip()
        if code and code != "200":
            return True
        msg = str(data.get("message") or "").strip().lower()
        if msg in {"not sufficient", "error", "failed"}:
            return True
        return False

    @staticmethod
    def _request_ok(data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        if str(data.get("code") or "").strip() == "200":
            return True
        return bool(data.get("success"))

    async def _request_compat(self, command: str, **params: Any) -> tuple[int, Any]:
        try:
            return await self._request(command, **params)
        except TypeError:
            return await self._request(command, params)

    async def _resolve_country(self, country: Any) -> str | None:
        raw = str(country or "").strip()
        return raw or None

    async def list_services(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if (
            not force_refresh
            and self._services_cache
            and (now - self._services_cached_at) < self._services_ttl_sec
        ):
            return list(self._services_cache)

        _status, data = await self._request("get_service_list", {})
        rows: list[dict[str, Any]] = []

        if isinstance(data, list):
            rows = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            if isinstance(data.get("data"), list):
                rows = [x for x in data.get("data", []) if isinstance(x, dict)]
            elif all(isinstance(v, dict) for v in data.values()):
                rows = [v for v in data.values() if isinstance(v, dict)]
            elif {"service_id", "service_name"} <= set(data.keys()):
                rows = [data]

        normalized: list[dict[str, Any]] = []
        for row in rows:
            sid = str(row.get("service_id") or row.get("id") or "").strip()
            if not sid:
                continue
            normalized.append(
                {
                    "id": sid,
                    "name": str(row.get("service_name") or row.get("name") or sid).strip(),
                    "price": _as_float(row.get("price") or 0) or 0.0,
                    "raw": row,
                }
            )

        if normalized:
            self._services_cache = normalized
            self._services_cached_at = now

        return list(self._services_cache)

    async def resolve_service_code(self, service_key: str | int) -> str | None:
        raw = str(service_key or "").strip()
        if not raw:
            return None
        services = await self.list_services()
        if raw.isdigit():
            for item in services:
                if str(item.get("id")) == raw:
                    return raw
            # Numeric id provided but not available in current catalog.
            return None
        target = _norm(raw)
        for item in services:
            name_norm = _norm(str(item.get("name") or ""))
            if name_norm == target:
                return str(item.get("id"))
            # Allow "yahoo" to match provider variants like "yahoo4"/"yahoo5".
            if name_norm.startswith(target):
                suffix = name_norm[len(target):]
                if suffix.isdigit():
                    return str(item.get("id"))

        return None

    async def get_price_variants(
        self,
        service: str | int,
        country=None,
        state=None,
        *,
        limit: int = 2,
    ) -> list[dict[str, Any]]:
        raw = str(service or "").strip()
        if not raw:
            return []

        services = await self.list_services()
        if not services:
            return []

        target = _norm(raw)
        target_base = _strip_tail_variant(raw)
        picks: list[tuple[float, dict[str, Any]]] = []

        if raw.isdigit():
            direct = next((x for x in services if str(x.get("id")) == raw), None)
            if direct:
                price = _as_float(direct.get("price")) or 0.0
                if price > 0:
                    return [
                        {
                            "success": True,
                            "price": float(price),
                            "api_service_name": str(direct.get("id")),
                            "raw": direct.get("raw", direct),
                        }
                    ]
            return []

        for item in services:
            name = str(item.get("name") or "")
            name_norm = _norm(name)
            if not name_norm:
                continue

            matched = False
            if name_norm == target:
                matched = True
            elif name_norm.startswith(target):
                matched = True
            elif _strip_tail_variant(name_norm) == target_base and target_base:
                matched = True
            if not matched:
                continue

            price = _as_float(item.get("price")) or 0.0
            if price <= 0:
                continue
            picks.append((float(price), item))

        picks.sort(key=lambda x: (x[0], str(x[1].get("id") or "")))
        out: list[dict[str, Any]] = []
        for price, item in picks[: max(1, int(limit or 1))]:
            out.append(
                {
                    "success": True,
                    "price": float(price),
                    "api_service_name": str(item.get("id") or ""),
                    "raw": item.get("raw", item),
                }
            )
        return out

    async def get_price(self, service, country=None, state=None):
        raw = str(service or "").strip()
        if raw.isdigit() and country not in (None, "", "none"):
            country_id = await self._resolve_country(country)
            status, data = await self._request_compat("get-prices", country_id=country_id)
            if status == 200 and isinstance(data, dict):
                country_rows = data.get(str(country_id)) or data.get(country_id) or {}
                if isinstance(country_rows, dict):
                    row = country_rows.get(raw) or {}
                    if isinstance(row, dict):
                        price = _as_float(row.get("cost") or row.get("price") or 0)
                        count = int(float(row.get("count") or 0)) if row.get("count") not in (None, "") else 0
                        if price is not None and price > 0:
                            return {
                                "success": True,
                                "price": float(price),
                                "count": count,
                                "api_service_name": raw,
                                "raw": data,
                            }
        variants = await self.get_price_variants(service, country=country, state=state, limit=1)
        if not variants:
            return {"success": False, "raw": "service_not_found"}
        return variants[0]

    async def buy_number(
        self,
        service,
        country=None,
        state=None,
        mdn: Optional[str] = None,
        areacode: Optional[str] = None,
        markup: Optional[int] = None,
    ):
        raw_service = str(service or "").strip()
        if raw_service.isdigit() and country not in (None, "", "none"):
            country_id = await self._resolve_country(country)
            _status, limits = await self._request_compat("limits", country_id=country_id)
            if isinstance(limits, list):
                match = None
                for row in limits:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("application_id") or "") == raw_service and str(row.get("country_id") or "") == str(country_id):
                        match = row
                        break
                if match is not None:
                    available = int(float(match.get("numbers") or 0)) if match.get("numbers") not in (None, "") else 0
                    if available <= 0:
                        return {
                            "success": False,
                            "raw": {"error_code": "NO_NUMBERS", "message": "no_numbers_available"},
                        }
                    _status, data = await self._request_compat(
                        "get-number",
                        application_id=raw_service,
                        country_id=country_id,
                    )
                    if isinstance(data, dict):
                        order_id = str(data.get("request_id") or data.get("order_id") or "").strip()
                        number = str(data.get("number") or "").strip()
                        if order_id and number:
                            return {
                                "success": True,
                                "order_id": order_id,
                                "number": number,
                                "raw": data,
                            }
                        return {"success": False, "raw": data}

        sid = await self.resolve_service_code(service)
        if not sid:
            return {"success": False, "raw": "service_not_found"}

        _status, data = await self._request_compat("order_number", service_id=str(sid))
        if self._is_error(data):
            return {"success": False, "raw": data}

        if not isinstance(data, dict):
            return {"success": False, "raw": data}

        order_id = str(data.get("order_id") or data.get("id") or "").strip()
        number = str(data.get("number") or "").strip()
        if not order_id or not number:
            return {"success": False, "raw": data}

        return {
            "success": True,
            "order_id": order_id,
            "number": number,
            "raw": data,
        }

    async def get_sms(self, activation_id) -> dict[str, Any]:
        try:
            _status, data = await self._request_compat("get-sms", request_id=str(activation_id))
        except Exception:
            _status, data = await self._request_compat("get_messages", order_id=str(activation_id))
        if isinstance(data, dict):
            old_code = str(data.get("error_code") or "").strip().lower()
            if old_code == "wait_sms":
                return {"success": True, "messages": [], "raw": data}
            sms_code = str(data.get("sms_code") or "").strip()
            if sms_code:
                return {
                    "success": True,
                    "code": sms_code,
                    "messages": [sms_code],
                    "raw": data,
                }
        if self._is_error(data):
            return {"success": False, "messages": [], "raw": data}

        if not isinstance(data, dict):
            return {"success": False, "messages": [], "raw": data}

        text = str(data.get("text") or data.get("message") or "").strip()
        code = str(data.get("code") or "").strip()
        messages: list[str] = []
        if text:
            messages.append(text)
        elif code:
            messages.append(code)

        return {
            "success": bool(messages),
            "code": code,
            "messages": messages,
            "raw": data,
        }

    async def cancel(self, activation_id) -> dict[str, Any]:
        compat_ok = False
        compat_data: Any = None
        for status_name in ("reject", "close"):
            try:
                _status, compat_data = await self._request_compat("set-status", id=str(activation_id), status=status_name)
            except Exception:
                compat_data = None
                break
            if self._request_ok(compat_data):
                compat_ok = True
                break
        if compat_ok:
            return {"success": True, "raw": compat_data}

        _status, data = await self._request_compat("refund_number", id=str(activation_id))
        if not isinstance(data, dict):
            return {"success": False, "raw": data}
        ok = str(data.get("code") or "").strip() == "200" or bool(data.get("success"))
        return {"success": ok, "raw": data}

    async def get_balance(self) -> Optional[float]:
        try:
            _status, data = await self._request_compat("get-balance")
        except Exception:
            data = None
        if isinstance(data, dict):
            for key in ("balance", "amount", "value"):
                parsed = _as_float(data.get(key))
                if parsed is not None:
                    return parsed
        return None
