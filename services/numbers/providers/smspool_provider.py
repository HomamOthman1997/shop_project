import logging
import re
from typing import Any

from config import settings
from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST

from .base_provider import BaseProvider

logger = logging.getLogger("smspool")


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


def _norm_country(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


class SMSPoolProvider(BaseProvider):
    BASE = "https://api.smspool.net"
    RENTAL_TYPE_EXTENDABLE = 1

    async def _session(self):
        return await SessionManager.get_session()

    async def _post_with_fallback(
        self,
        *,
        paths: list[str],
        payload: dict[str, Any],
        use_json: bool = False,
    ) -> tuple[int, Any]:
        """Try multiple SMSPool endpoints in order (new first, legacy fallback)."""
        session = await self._session()
        last_status = 0
        last_data: Any = None
        for path in paths:
            try:
                if use_json:
                    async with session.post(f"{self.BASE}{path}", json=payload) as resp:
                        text = await resp.text()
                        try:
                            data = await resp.json(content_type=None)
                        except Exception:
                            data = {"raw_text": text}
                else:
                    async with session.post(f"{self.BASE}{path}", data=payload) as resp:
                        text = await resp.text()
                        try:
                            data = await resp.json(content_type=None)
                        except Exception:
                            data = {"raw_text": text}
                last_status = int(resp.status)
                last_data = data
                if resp.status == 200:
                    return resp.status, data
            except Exception as exc:
                last_status = 0
                last_data = {"error": str(exc), "path": path}
                continue
        return last_status, last_data

    async def _request_form(self, *, path: str, payload: dict[str, Any]) -> tuple[int, Any]:
        """Send form request with POST first, GET fallback for compatibility stubs/tests."""
        session = await self._session()
        # Prefer POST (documented behavior).
        if hasattr(session, "post"):
            try:
                async with session.post(f"{self.BASE}{path}", data=payload) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {"raw_text": text}
                    return int(resp.status), data
            except Exception:
                pass
        # Compatibility fallback for old stubs / mocked sessions.
        if hasattr(session, "get"):
            try:
                async with session.get(f"{self.BASE}{path}", params=payload) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {"raw_text": text}
                    return int(resp.status), data
            except Exception as exc:
                return 0, {"error": str(exc), "path": path}
        return 0, {"error": "session_has_no_http_methods", "path": path}

    @staticmethod
    def _country_by_code() -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in COUNTRIES_LIST:
            code = str(row.get("code") or "").strip()
            if code:
                out[code] = row
        return out

    @classmethod
    def _country_hints(cls, country: str | None) -> set[str]:
        if not country:
            return set()
        raw = str(country).strip()
        if not raw:
            return set()
        hints = {_norm_country(raw)}
        by_code = cls._country_by_code()
        if raw in by_code:
            row = by_code[raw]
            iso = str(row.get("iso") or "").strip().lower()
            name = str(row.get("name") or "").strip()
            if iso:
                hints.add(_norm_country(iso))
            if name:
                hints.add(_norm_country(name))
            if iso == "us":
                hints.update({"us", "usa", "unitedstates", "unitedstatesofamerica"})
            if iso == "gb":
                hints.update({"uk", "gb", "unitedkingdom"})
        return {hint for hint in hints if hint}

    @classmethod
    def _row_matches_country(cls, row: dict[str, Any], country: str | None) -> bool:
        hints = cls._country_hints(country)
        if not hints:
            return True
        name = _norm_country(str(row.get("name") or ""))
        tag = _norm_country(str(row.get("tag") or ""))
        for hint in hints:
            if hint and (hint in name or hint in tag):
                return True
        return False

    async def get_price(self, service, country=None, state=None):
        # ensure the key is configured; otherwise aiohttp will blow up with None
        key = settings.smspool_key
        if not key:
            logger.error("SMSPool API key is missing (smspool_key setting)")
            return {"success": False, "raw": "missing_api_key"}

        try:
            session = await self._session()

            # hit the documented pricing endpoint (POST form data) rather than the
            # old /request/prices path which returns 404.
            async with session.post(
                f"{self.BASE}/request/pricing",
                data={"key": key},
            ) as response:

                # handle non-200 responses early so we don't attempt to decode HTML
                if response.status != 200:
                    text = await response.text()
                    logger.error(
                        "SMSPool returned unexpected status %s: %s",
                        response.status,
                        text,
                    )
                    return {"success": False, "raw": f"status {response.status}"}

                try:
                    data = await response.json()
                except Exception:
                    body = await response.text()
                    logger.error(
                        "SMSPool returned non-JSON body: %s",
                        body,
                    )
                    return {"success": False, "raw": "invalid_response"}

                # the pricing endpoint returns a list of dicts.
                if not isinstance(data, list):
                    return {"success": False, "raw": data}

                svc_key = str(service)
                candidates = [item for item in data if str(item.get("service")) == svc_key]

                # optionally narrow by country
                if country and candidates:
                    lower_country = str(country).strip().lower()
                    filtered = []
                    for item in candidates:
                        if str(item.get("country")).lower() == lower_country:
                            filtered.append(item)
                        elif str(item.get("short_name", "")).lower() == lower_country:
                            filtered.append(item)
                    if filtered:
                        candidates = filtered

                if not candidates:
                    return {"success": False, "raw": data}

                # pick the lowest nonzero price from candidates
                prices = []
                for item in candidates:
                    try:
                        prices.append(float(item.get("price", 0) or 0))
                    except Exception:
                        continue
                price_val = min(prices) if prices else 0.0

                return {
                    "success": True,
                    "price": price_val,
                    "api_service_name": service,
                    "raw": data,
                }

        except Exception as e:
            logger.exception("SMSPool get_price error")
            return {"success": False, "raw": str(e)}

    async def buy_number(self, service, country=None, state=None, **kwargs):
        # ensure key is present
        key = settings.smspool_key
        if not key:
            logger.error("SMSPool API key is missing (smspool_key setting)")
            return {"success": False, "raw": "missing_api_key"}

        try:
            session = await self._session()

            payload: dict[str, Any] = {
                "key": key,
                "service": service,
                "country": country,
            }
            # Best-effort state targeting for providers/endpoints that accept it.
            if state and str(state).strip().lower() != "none":
                payload["state"] = str(state).strip().upper()
            # Reuse mode: explicitly request Foxtrot pool.
            if bool(kwargs.get("reuse_mode")):
                payload["pool"] = "foxtrot"

            async with session.post(
                f"{self.BASE}/purchase/sms",
                data=payload,
            ) as resp:

                data = await resp.json()

                if resp.status != 200:
                    return {"success": False, "raw": data}

                selected_pool = str(
                    data.get("pool")
                    or data.get("pool_name")
                    or data.get("selected_pool")
                    or payload.get("pool")
                    or ""
                ).strip()

                return {
                    "success": True,
                    "order_id": data.get("order_id"),
                    "number": data.get("number"),
                    "pool": selected_pool or None,
                    "raw": data,
                }

        except Exception as e:
            logger.exception("SMSPool buy_number error")
            return {"success": False, "raw": str(e)}

    async def get_balance(self) -> float | None:
        key = settings.smspool_key
        if not key:
            return None

        try:
            session = await self._session()
            # SMSPool balance endpoint accepts API key and returns numeric balance.
            async with session.post(
                f"{self.BASE}/request/balance",
                data={"key": key},
            ) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = None

            if isinstance(data, (int, float, str)):
                return _as_float(data)
            if isinstance(data, dict):
                return _as_float(data.get("balance") or data.get("Balance") or data.get("amount"))
            return _as_float(text)
        except Exception:
            return None

    async def get_sms(self, activation_id):
        key = settings.smspool_key
        status, data = await self._post_with_fallback(
            paths=["/sms/check", "/request/check"],
            payload={"key": key, "orderid": activation_id},
            use_json=False,
        )
        messages: list[str] = []
        if isinstance(data, dict):
            sms_rows = data.get("sms") or data.get("messages") or []
            if isinstance(sms_rows, list):
                messages = [str(x) for x in sms_rows if x not in (None, "")]
            elif sms_rows not in (None, ""):
                messages = [str(sms_rows)]
        return {
            "success": status == 200,
            "messages": messages,
            "raw": data,
        }

    async def cancel(self, activation_id):
        key = settings.smspool_key
        status, data = await self._post_with_fallback(
            paths=["/sms/cancel", "/request/cancel"],
            payload={"key": key, "orderid": activation_id},
            use_json=False,
        )
        return {
            "success": status == 200,
            "raw": data,
        }

    async def _fetch_rental_catalog(self) -> dict[str, Any]:
        key = settings.smspool_key
        if not key:
            return {"success": False, "raw": "missing_api_key"}

        status, data = await self._request_form(
            path="/rental/retrieve_all",
            payload={"key": key, "type": self.RENTAL_TYPE_EXTENDABLE},
        )
        ok = bool(status == 200 and isinstance(data, dict) and str(data.get("success")) in {"1", "True", "true"})
        return {"success": ok, "raw": data}

    async def get_rental_prices(self, service, country=None):
        catalog = await self._fetch_rental_catalog()
        payload = catalog.get("raw")
        if not catalog.get("success") or not isinstance(payload, dict):
            return {"success": False, "options": [], "raw": payload}

        rows = payload.get("data")
        if not isinstance(rows, list):
            return {"success": False, "options": [], "raw": payload}

        options: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not self._row_matches_country(row, country):
                continue

            rental_id = _as_int(row.get("ID") or row.get("id"))
            pricing = row.get("pricing")
            if rental_id is None or not isinstance(pricing, dict):
                continue

            pool_count = _as_int(row.get("pool")) or 0
            country_name = str(row.get("name") or "").strip()
            tag = str(row.get("tag") or country_name).strip()

            for days_raw, price_raw in pricing.items():
                days = _as_int(days_raw)
                price = _as_float(price_raw)
                if days is None or days <= 0 or price is None or price <= 0:
                    continue
                options.append(
                    {
                        "country": str(country or country_name or "unknown"),
                        "country_name": country_name,
                        "duration": int(days * 24),
                        "duration_days": int(days),
                        "duration_label": f"{days}d",
                        "price": float(price),
                        "count": max(0, pool_count),
                        "rental_id": str(rental_id),
                        "provider_note": tag,
                    }
                )

        options.sort(key=lambda x: (float(x.get("price", 0)), int(x.get("duration", 0))))
        return {"success": bool(options), "options": options, "raw": payload}

    async def rent_number(
        self,
        service,
        country=None,
        duration=24,
        rental_id: str | int | None = None,
        duration_days: int | str | None = None,
        country_name: str | None = None,
    ):
        key = settings.smspool_key
        if not key:
            return {"success": False, "raw": "missing_api_key"}

        selected_rental_id = str(rental_id or "").strip()
        selected_days = _as_int(duration_days)
        if selected_days is None:
            # Keep conversion strict without rounding up (floor to whole days).
            selected_days = max(1, int(int(duration) // 24))

        # If selected option metadata is missing, pick cheapest available option.
        if not selected_rental_id:
            catalog = await self.get_rental_prices(service, country=country)
            opts = catalog.get("options") or []
            if not opts:
                return {"success": False, "raw": catalog.get("raw", "no_rental_options")}
            exact = [o for o in opts if int(o.get("duration_days") or 0) == selected_days]
            chosen = exact[0] if exact else opts[0]
            selected_rental_id = str(chosen.get("rental_id") or "").strip()
            selected_days = int(chosen.get("duration_days") or selected_days or 1)
            country_name = str(chosen.get("country_name") or country_name or "")
            if not selected_rental_id:
                return {"success": False, "raw": "missing_rental_id"}

        session = await self._session()
        async with session.post(
            f"{self.BASE}/purchase/rental",
            data={"key": key, "id": selected_rental_id, "days": selected_days},
        ) as resp:
            text = await resp.text()
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {"raw_text": text}

        if resp.status != 200:
            return {"success": False, "raw": data}

        if isinstance(data, dict) and str(data.get("success")) in {"1", "True", "true"}:
            payload = data.get("data") if isinstance(data.get("data"), dict) else data
            order_id = str(
                payload.get("rental_code")
                or payload.get("order_id")
                or payload.get("id")
                or payload.get("code")
                or ""
            ).strip()
            number = str(
                payload.get("number")
                or payload.get("phone_number")
                or payload.get("phone")
                or payload.get("msisdn")
                or ""
            ).strip()
            price_val = _as_float(payload.get("price") or payload.get("cost") or payload.get("amount"))
            end_date = payload.get("expires_at") or payload.get("expiration") or payload.get("end_date")
            if order_id and number:
                return {
                    "success": True,
                    "order_id": order_id,
                    "number": number,
                    "price": price_val,
                    "end_date": end_date,
                    "raw": data,
                    "country_name": country_name,
                }

        return {"success": False, "raw": data}

    async def get_rental_sms(self, activation_id: str, size: int = 20, page: int = 1) -> dict[str, Any]:
        key = settings.smspool_key
        if not key:
            return {"success": False, "messages": [], "raw": "missing_api_key"}

        status, data = await self._request_form(
            path="/rental/retrieve_messages",
            payload={"key": key, "rental_code": activation_id},
        )
        if status != 200:
            return {"success": False, "messages": [], "raw": data}

        messages: list[str] = []
        if isinstance(data, dict):
            rows = data.get("messages") or data.get("data") or data.get("sms") or []
            if isinstance(rows, list):
                for row in rows[: max(1, size)]:
                    if isinstance(row, dict):
                        msg = (
                            row.get("message")
                            or row.get("text")
                            or row.get("sms")
                            or row.get("code")
                            or row.get("otp")
                        )
                        if msg:
                            messages.append(str(msg))
                    elif row:
                        messages.append(str(row))
            elif rows:
                messages.append(str(rows))

        return {"success": True, "messages": messages, "raw": data}

    async def get_rental_info(self, activation_id: str) -> dict[str, Any]:
        key = settings.smspool_key
        if not key:
            return {"success": False, "raw": "missing_api_key"}

        status, data = await self._post_with_fallback(
            paths=["/rental/info", "/rental/retrieve"],
            payload={"key": key, "rental_code": activation_id},
            use_json=False,
        )
        if status != 200:
            return {"success": False, "raw": data}

        payload = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
        if not isinstance(payload, dict):
            return {"success": True, "raw": data}

        refund_can_refund = None
        for key_name in ("can_refund", "canRefund", "refundable"):
            if key_name in payload:
                try:
                    refund_can_refund = bool(payload.get(key_name))
                except Exception:
                    refund_can_refund = None
                break

        refund_refundable_until = None
        for key_name in ("refundable_until", "refund_until", "refund_expires_at", "refund_expiration"):
            value = payload.get(key_name)
            if value not in (None, ""):
                refund_refundable_until = value
                break

        end_date = None
        for key_name in ("expires_at", "expiration", "end_date", "ends_at"):
            value = payload.get(key_name)
            if value not in (None, ""):
                end_date = value
                break

        return {
            "success": True,
            "refund_can_refund": refund_can_refund,
            "refund_refundable_until": refund_refundable_until,
            "end_date": end_date,
            "raw": data,
        }

    async def finish_rental(self, activation_id: str) -> dict[str, Any]:
        key = settings.smspool_key
        if not key:
            return {"success": False, "raw": "missing_api_key"}

        status, data = await self._post_with_fallback(
            paths=["/rental/refund", "/rental/refund.php"],
            payload={"key": key, "rental_code": activation_id},
            use_json=False,
        )
        if status != 200:
            return {"success": False, "raw": data}

        if isinstance(data, dict):
            if str(data.get("success")) in {"1", "True", "true"}:
                return {"success": True, "raw": data}
            message = str(data.get("message") or "").lower()
            if "already" in message or "expired" in message:
                return {"success": True, "raw": data}

        return {"success": False, "raw": data}
