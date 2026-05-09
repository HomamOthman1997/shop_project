from typing import Dict, Any, Optional

import asyncio
import time

from services.numbers.core.session_manager import SessionManager
from .base_provider import BaseProvider
from config import settings
from services.numbers.data import tv_area_codes
from services.numbers.data import textverified_services
from services.numbers.service_families import CANONICAL_SERVICE_KEYS, SERVICE_FAMILY_GROUPS, normalize_service_key

import logging

logger = logging.getLogger("textverified")


class TextVerifiedProvider(BaseProvider):
    BASE = "https://www.textverified.com/api"
    _services_cache_by_capability: dict[str, set[str]] = {}
    _auth_lock: asyncio.Lock | None = None
    _token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0, "fingerprint": None}
    _price_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
    _rate_limit_stats: dict[str, dict[str, Any]] = {
        "auth": {"requests": 0, "window_started_at": None, "window_429_hits": 0, "window_request_at_first_429": None},
        "pricing": {"requests": 0, "window_started_at": None, "window_429_hits": 0, "window_request_at_first_429": None},
    }
    AUTH_RETRY_DELAYS: tuple[float, ...] = (0.35, 0.9)
    PRICE_RETRY_DELAYS: tuple[float, ...] = (0.2, 0.55)
    TOKEN_TTL_SECONDS = 540.0
    PRICE_CACHE_TTL_SECONDS = 45.0
    RENTAL_DURATIONS: tuple[tuple[str, str, int], ...] = (
        ("oneDay", "1d", 24),
        ("threeDay", "3d", 72),
        ("sevenDay", "7d", 168),
        ("fourteenDay", "14d", 336),
        ("thirtyDay", "30d", 720),
        ("ninetyDay", "90d", 2160),
        ("oneYear", "365d", 8760),
    )

    @classmethod
    def _now(cls) -> float:
        return time.monotonic()

    @classmethod
    async def _sleep(cls, seconds: float) -> None:
        await asyncio.sleep(seconds)

    @classmethod
    def _ensure_auth_lock(cls) -> asyncio.Lock:
        if cls._auth_lock is None:
            cls._auth_lock = asyncio.Lock()
        return cls._auth_lock

    @classmethod
    def _credential_fingerprint(cls) -> str:
        return f"{settings.tv_user or ''}:{settings.tv_key or ''}"

    @classmethod
    def _get_cached_token(cls) -> Optional[str]:
        cached_token = str(cls._token_cache.get("token") or "").strip()
        expires_at = float(cls._token_cache.get("expires_at") or 0.0)
        fingerprint = str(cls._token_cache.get("fingerprint") or "")
        if (
            cached_token
            and fingerprint == cls._credential_fingerprint()
            and expires_at > cls._now() + 5.0
        ):
            return cached_token
        return None

    @classmethod
    def _cache_token(cls, token: str, ttl_seconds: float | None = None) -> None:
        ttl = float(ttl_seconds or cls.TOKEN_TTL_SECONDS)
        cls._token_cache = {
            "token": token,
            "expires_at": cls._now() + max(ttl, 30.0),
            "fingerprint": cls._credential_fingerprint(),
        }

    @classmethod
    def _invalidate_cached_token(cls) -> None:
        cls._token_cache = {"token": None, "expires_at": 0.0, "fingerprint": cls._credential_fingerprint()}

    @classmethod
    def _parse_retry_after(cls, headers: dict[str, Any] | None) -> float | None:
        if not isinstance(headers, dict):
            return None
        raw = headers.get("Retry-After") or headers.get("retry-after")
        try:
            if raw is None:
                return None
            value = float(raw)
            if value > 0:
                return min(value, 5.0)
        except Exception:
            return None
        return None

    @classmethod
    def _is_rate_limited(cls, status: int, payload: Any) -> bool:
        if int(status or 0) == 429:
            return True
        if not isinstance(payload, dict):
            return False
        code = str(payload.get("errorCode") or "").strip().lower()
        desc = str(payload.get("errorDescription") or payload.get("message") or "").strip().lower()
        return "too many requests" in desc or code in {"ratelimited", "too_many_requests"}

    @classmethod
    def _price_cache_key(cls, service: Any, country: Any, state: Any) -> tuple[str, str, str]:
        return (
            normalize_service_key(service),
            str(country or "").strip().upper(),
            str(state or "").strip().upper(),
        )

    @classmethod
    def _get_cached_price(cls, service: Any, country: Any, state: Any) -> Optional[dict[str, Any]]:
        key = cls._price_cache_key(service, country, state)
        cached = cls._price_cache.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if expires_at <= cls._now():
            cls._price_cache.pop(key, None)
            return None
        return dict(payload)

    @classmethod
    def _cache_price(cls, service: Any, country: Any, state: Any, payload: dict[str, Any]) -> None:
        key = cls._price_cache_key(service, country, state)
        cls._price_cache[key] = (cls._now() + cls.PRICE_CACHE_TTL_SECONDS, dict(payload))

    @classmethod
    def _masked_key_fingerprint(cls) -> str:
        key = str(settings.tv_key or "").strip()
        if len(key) < 8:
            return "***"
        return f"{key[:4]}...{key[-4:]}"

    @classmethod
    def _rate_limit_bucket(cls, scope: str) -> dict[str, Any]:
        bucket = cls._rate_limit_stats.get(scope)
        if bucket is None:
            bucket = {
                "requests": 0,
                "window_started_at": None,
                "window_429_hits": 0,
                "window_request_at_first_429": None,
            }
            cls._rate_limit_stats[scope] = bucket
        return bucket

    @classmethod
    def _mark_request(cls, scope: str) -> int:
        bucket = cls._rate_limit_bucket(scope)
        bucket["requests"] = int(bucket.get("requests") or 0) + 1
        return int(bucket["requests"])

    @classmethod
    def _record_rate_limit(cls, scope: str, *, status: int, retry_after: float | None, extra: str = "") -> None:
        bucket = cls._rate_limit_bucket(scope)
        now = cls._now()
        if not bucket.get("window_started_at"):
            bucket["window_started_at"] = now
            bucket["window_request_at_first_429"] = int(bucket.get("requests") or 0)
            bucket["window_429_hits"] = 0
        bucket["window_429_hits"] = int(bucket.get("window_429_hits") or 0) + 1
        logger.warning(
            "textverified rate_limit scope=%s status=%s request_no=%s first_429_request_no=%s hits_in_window=%s retry_after=%s key=%s%s",
            scope,
            status,
            int(bucket.get("requests") or 0),
            bucket.get("window_request_at_first_429"),
            bucket.get("window_429_hits"),
            retry_after,
            cls._masked_key_fingerprint(),
            f" {extra}" if extra else "",
        )

    @classmethod
    def _record_rate_limit_recovery(cls, scope: str, *, extra: str = "") -> None:
        bucket = cls._rate_limit_bucket(scope)
        started_at = bucket.get("window_started_at")
        if not started_at:
            return
        elapsed = max(cls._now() - float(started_at), 0.0)
        logger.info(
            "textverified rate_limit_recovered scope=%s request_no=%s first_429_request_no=%s hits_in_window=%s blocked_for_sec=%.3f key=%s%s",
            scope,
            int(bucket.get("requests") or 0),
            bucket.get("window_request_at_first_429"),
            bucket.get("window_429_hits"),
            elapsed,
            cls._masked_key_fingerprint(),
            f" {extra}" if extra else "",
        )
        bucket["window_started_at"] = None
        bucket["window_429_hits"] = 0
        bucket["window_request_at_first_429"] = None

    async def _auth(self) -> Optional[str]:
        # read credentials dynamically from settings to avoid import-time
        # caching and allow tests/env changes at runtime
        user = settings.tv_user
        key = settings.tv_key
        if not user or not key:
            logger.error("TextVerified credentials missing (tv_user/tv_key)")
            return None
        cached_token = self._get_cached_token()
        if cached_token:
            return cached_token

        lock = self._ensure_auth_lock()
        async with lock:
            cached_token = self._get_cached_token()
            if cached_token:
                return cached_token

            session = await SessionManager.get_session()
            headers = {
                "X-API-USERNAME": user,
                "X-API-KEY": key,
                "Content-Type": "application/json",
            }
            retry_delays = list(self.AUTH_RETRY_DELAYS)
            for attempt in range(len(retry_delays) + 1):
                self._mark_request("auth")
                async with session.post(
                    f"{self.BASE}/pub/v2/auth",
                    headers=headers,
                    json={},
                ) as resp:
                    if resp.status == 200:
                        try:
                            data = await resp.json()
                        except Exception:
                            logger.warning("textverified auth returned non-json payload")
                            return None
                        token = str((data or {}).get("token") or "").strip()
                        if not token:
                            logger.warning("textverified auth returned empty token")
                            return None
                        ttl = (
                            self._as_float((data or {}).get("expiresIn"))
                            or self._as_float((data or {}).get("expires_in"))
                            or self._as_float((data or {}).get("expiresInSeconds"))
                        )
                        self._cache_token(token, ttl)
                        self._record_rate_limit_recovery("auth")
                        return token

                    text = await resp.text()
                    try:
                        data = await resp.json()
                    except Exception:
                        data = {"raw_text": text}

                if self._is_rate_limited(resp.status, data) and attempt < len(retry_delays):
                    retry_after = self._parse_retry_after(dict(resp.headers))
                    self._record_rate_limit("auth", status=resp.status, retry_after=retry_after)
                    await self._sleep(retry_after if retry_after is not None else retry_delays[attempt])
                    continue
                if self._is_rate_limited(resp.status, data):
                    retry_after = self._parse_retry_after(dict(resp.headers))
                    self._record_rate_limit("auth", status=resp.status, retry_after=retry_after)

                logger.warning("textverified auth failed status %s", resp.status)
                return None
        return None

    @classmethod
    def _services_for_capability(cls, capability_name: str) -> set[str]:
        capability_filter = str(capability_name or "sms").strip().lower()
        cached = cls._services_cache_by_capability.get(capability_filter)
        if cached is not None:
            return set(cached)
        services: set[str] = set()
        for row in textverified_services.DATA:
            if not isinstance(row, dict):
                continue
            service_name = str(row.get("serviceName") or "").strip()
            capability = str(row.get("capability") or "").strip().lower()
            if not service_name:
                continue
            if capability and capability != capability_filter:
                continue
            services.add(service_name)
        cls._services_cache_by_capability[capability_filter] = set(services)
        return services

    def _service_candidates(self, service: str, *, capability: str = "sms") -> list[str]:
        base = str(service or "").strip()
        if not base:
            return []
        out: list[str] = [base]
        supported_services = self._services_for_capability(capability)
        normalized_map: dict[str, str] = {normalize_service_key(name): name for name in supported_services}

        norm = normalize_service_key(base)
        canonical = CANONICAL_SERVICE_KEYS.get(norm, norm)
        family = [canonical, *SERVICE_FAMILY_GROUPS.get(canonical, ())]
        for family_key in family:
            candidate = normalized_map.get(family_key)
            if candidate and candidate not in out:
                out.append(candidate)
        # TV commonly exposes Gmail while callers may ask for the broader Google label.
        if norm == "google":
            gmail_candidate = normalized_map.get("gmail")
            if gmail_candidate and gmail_candidate not in out:
                out.append(gmail_candidate)
        return out

    @staticmethod
    def _normalize_area_code(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) < 3:
            return None
        return digits

    @classmethod
    def _state_area_codes(cls, state_code: str | None) -> list[str]:
        state = str(state_code or "").strip().upper()
        if len(state) != 2:
            return []
        raw = tv_area_codes.DATA.get(state)
        values: list[Any]
        if isinstance(raw, (list, tuple, set)):
            values = list(raw)
        elif raw in (None, ""):
            values = []
        else:
            values = [raw]

        out: list[str] = []
        for item in values:
            normalized = cls._normalize_area_code(item)
            if normalized and normalized not in out:
                out.append(normalized)
        return out

    @staticmethod
    def _is_unavailable(status: int, payload: Any) -> bool:
        if status == 404:
            return True
        if not isinstance(payload, dict):
            return False
        code = str(payload.get("errorCode") or "").strip().lower()
        desc = str(payload.get("errorDescription") or payload.get("message") or "").strip().lower()
        if code in {"unavailable", "outofstock"}:
            return True
        return ("out of stock" in desc) or ("unavailable" in desc)

    @staticmethod
    def _is_auth_error(status: int, payload: Any) -> bool:
        if status in (401, 403):
            return True
        if not isinstance(payload, dict):
            return False
        code = str(payload.get("errorCode") or "").strip().lower()
        return code in {"unauthorized", "forbidden", "invalidtoken", "invalidapikey"}

    async def get_price(self, service, country=None, state=None):
        return await self._get_verification_price(service, country=country, state=state, capability="sms")

    async def get_voice_price(self, service, country=None, state=None):
        return await self._get_verification_price(service, country=country, state=state, capability="voice")

    async def _get_verification_price(self, service, country=None, state=None, *, capability: str = "sms"):
        capability_value = str(capability or "sms").strip().lower()
        cache_service_key = f"{capability_value}:{service}"
        cached_price = self._get_cached_price(cache_service_key, country, state)
        if cached_price is not None:
            return cached_price

        token = await self._auth()
        if not token:
            return {"success": False, "raw": "auth_failed"}
        session = await SessionManager.get_session()
        area_code = None
        if state:
            s = str(state).strip().upper()
            if len(s) == 2:
                codes = self._state_area_codes(s)
                area_code = codes[0] if codes else None

        area_flags = [bool(area_code)]
        if area_code:
            area_flags.append(False)
        elif True not in area_flags:
            area_flags.append(True)

        service_candidates = self._service_candidates(str(service), capability=capability_value)
        if not service_candidates:
            service_candidates = [str(service)]

        last_error = None
        for candidate_service in service_candidates:
            for area_flag in area_flags:
                body: dict[str, object] = {
                    "serviceName": candidate_service,
                    "numberType": "mobile",
                    "capability": capability_value,
                    "areaCode": bool(area_flag),
                    "carrier": False,
                }
                retry_delays = list(self.PRICE_RETRY_DELAYS)
                for attempt in range(len(retry_delays) + 1):
                    self._mark_request("pricing")
                    async with session.post(
                        f"{self.BASE}/pub/v2/pricing/verifications",
                        headers={"Authorization": f"Bearer {token}"},
                        json=body,
                    ) as resp:
                        text = await resp.text()
                        try:
                            data = await resp.json()
                        except Exception:
                            data = {"raw_text": text}

                    if self._is_auth_error(resp.status, data):
                        self._invalidate_cached_token()
                        if attempt == 0:
                            refreshed_token = await self._auth()
                            if refreshed_token:
                                token = refreshed_token
                                continue
                        last_error = {
                            "status": resp.status,
                            "raw": data,
                            "payload": body,
                            "attempt_service": candidate_service,
                        }
                        return {"success": False, "raw": last_error}

                    if self._is_rate_limited(resp.status, data) and attempt < len(retry_delays):
                        retry_after = self._parse_retry_after(dict(resp.headers))
                        self._record_rate_limit(
                            "pricing",
                            status=resp.status,
                            retry_after=retry_after,
                            extra=f"service={candidate_service}",
                        )
                        await self._sleep(retry_after if retry_after is not None else retry_delays[attempt])
                        continue
                    if self._is_rate_limited(resp.status, data):
                        retry_after = self._parse_retry_after(dict(resp.headers))
                        self._record_rate_limit(
                            "pricing",
                            status=resp.status,
                            retry_after=retry_after,
                            extra=f"service={candidate_service}",
                        )
                    break

                if resp.status == 200 and isinstance(data, dict):
                    price_val = self._as_float(data.get("price"))
                    if price_val is not None and price_val > 0:
                        self._record_rate_limit_recovery(
                            "pricing",
                            extra=f"service={candidate_service}",
                        )
                        result = {
                            "success": True,
                            "price": price_val,
                            "api_service_name": candidate_service,
                            "raw": data,
                        }
                        self._cache_price(cache_service_key, country, state, result)
                        return result

                last_error = {
                    "status": resp.status,
                    "raw": data,
                    "payload": body,
                    "attempt_service": candidate_service,
                }

        return {"success": False, "raw": last_error}

    async def buy_number(self, service, country=None, state=None, **kwargs):
        token = await self._auth()
        if not token:
            return {"success": False, "raw": "auth_failed"}
        session = await SessionManager.get_session()

        state_code = ""
        if state:
            s = str(state).strip().upper()
            if len(s) == 2:
                state_code = s

        requested_reuse = bool(kwargs.get("reuse_mode"))
        capability_raw = str(kwargs.get("capability") or "sms").strip()
        capability_map = {
            "sms": "sms",
            "voice": "voice",
            "smsandvoicecombo": "smsAndVoiceCombo",
        }
        capability_value = capability_map.get(capability_raw.lower(), "sms")
        if capability_value not in {"sms", "voice", "smsAndVoiceCombo"}:
            capability_value = "sms"
        service_candidates = self._service_candidates(str(service), capability=capability_value)
        if not service_candidates:
            service_candidates = [str(service)]

        state_area_codes = self._state_area_codes(state_code) if state_code else []
        if state_area_codes:
            area_candidates: list[str | None] = list(state_area_codes)
            # In single-code mode we can fallback to any area; in reuse mode keep state-locked attempts only.
            if not requested_reuse:
                area_candidates.append(None)
        elif state_code:
            # Unknown state code mapping: block strict reuse with a clean state-specific message.
            if requested_reuse:
                return {
                    "success": False,
                    "raw": {
                        "errorCode": "UNAVAILABLE_IN_STATE",
                        "errorDescription": f"Service unavailable in selected state ({state_code}).",
                        "stateCode": state_code,
                        "attemptedAreaCodes": [],
                        "requested_reuse_mode": requested_reuse,
                    },
                }
            area_candidates = [None]
        else:
            area_candidates = [None]

        attempts: list[dict[str, Any]] = []
        last_failure: dict[str, Any] | None = None
        unavailable_only = True

        for candidate_service in service_candidates:
            for candidate_area in area_candidates:
                payload: dict[str, object] = {
                    "serviceName": candidate_service,
                    "capability": capability_value,
                }
                if candidate_area:
                    payload["areaCodeSelectOption"] = [str(candidate_area)]
                if hasattr(self, "max_price") and self.max_price is not None:
                    payload["maxPrice"] = self.max_price

                async with session.post(
                    f"{self.BASE}/pub/v2/verifications",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                ) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json()
                    except Exception:
                        data = {"raw_text": text}
                    response_headers = dict(resp.headers)

                attempt_log = {
                    "status": resp.status,
                    "payload": payload,
                    "raw": data,
                    "service": candidate_service,
                    "area_code": candidate_area,
                }
                attempts.append(attempt_log)

                if resp.status not in (200, 201):
                    last_failure = {"create_response": data, "payload": payload}
                    if self._is_auth_error(resp.status, data):
                        return {"success": False, "raw": {"error": last_failure, "attempts": attempts}}
                    if not self._is_unavailable(resp.status, data):
                        unavailable_only = False
                    continue

                link = self._link_from_payload(data, headers=response_headers)
                if not link:
                    last_failure = {"create_response": data, "payload": payload}
                    unavailable_only = False
                    continue

                status, details, _headers = await self._request_link(token, link)
                if status != 200 or not isinstance(details, dict):
                    last_failure = {"create_response": data, "details": details, "payload": payload}
                    unavailable_only = False
                    continue

                order_id = str(details.get("id") or "").strip()
                number = str(details.get("number") or "").strip()
                if order_id and number:
                    return {
                        "success": True,
                        "order_id": order_id,
                        "number": number,
                        "api_service_name": candidate_service,
                        "requested_reuse_mode": requested_reuse,
                        "raw": details,
                    }
                last_failure = {"create_response": data, "details": details, "payload": payload}
                unavailable_only = False

                if not self._is_unavailable(resp.status, data):
                    continue

        attempted_services = []
        for row in attempts:
            service_name = str(row.get("service") or "").strip()
            if service_name and service_name not in attempted_services:
                attempted_services.append(service_name)
        attempted_area_codes = []
        for row in attempts:
            code = row.get("area_code")
            if code not in attempted_area_codes:
                attempted_area_codes.append(code)

        create_payload = (
            last_failure.get("create_response")
            if isinstance(last_failure, dict)
            else None
        )
        compact_error: dict[str, Any] = {
            "requested_reuse_mode": requested_reuse,
            "attemptedServices": attempted_services,
            "attemptedAreaCodes": attempted_area_codes,
        }
        if requested_reuse and state_code and state_area_codes and unavailable_only:
            compact_error["errorCode"] = "UNAVAILABLE_IN_STATE"
            compact_error["errorDescription"] = f"Service unavailable in selected state ({state_code})."
            compact_error["stateCode"] = state_code
        if isinstance(create_payload, dict):
            if create_payload.get("errorCode") is not None and not compact_error.get("errorCode"):
                compact_error["errorCode"] = create_payload.get("errorCode")
            if create_payload.get("errorDescription") is not None and not compact_error.get("errorDescription"):
                compact_error["errorDescription"] = create_payload.get("errorDescription")
            elif create_payload.get("message") is not None and not compact_error.get("errorDescription"):
                compact_error["errorDescription"] = create_payload.get("message")
        if not compact_error.get("errorCode") and last_failure is not None:
            compact_error["lastFailure"] = last_failure

        return {"success": False, "raw": compact_error}

    async def get_sms(self, activation_id):
        token = await self._auth()
        if not token:
            return {"success": False, "messages": [], "raw": "auth_failed"}

        session = await SessionManager.get_session()
        params = {"reservationId": activation_id}
        async with session.get(
            f"{self.BASE}/pub/v2/sms",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        ) as resp:
            text = await resp.text()
            try:
                data = await resp.json()
            except Exception:
                data = {"raw_text": text}
            messages: list[str] = []
            if isinstance(data, dict):
                rows = data.get("data")
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        parsed = row.get("parsedCode")
                        sms_text = row.get("smsContent")
                        if parsed:
                            messages.append(str(parsed))
                        elif sms_text:
                            messages.append(str(sms_text))
                elif data.get("sms"):
                    raw_sms = data.get("sms")
                    if isinstance(raw_sms, list):
                        messages.extend([str(x) for x in raw_sms if x not in (None, "")])
                    elif raw_sms not in (None, ""):
                        messages.append(str(raw_sms))
            return {"success": resp.status == 200, "messages": messages, "raw": data}

    async def get_calls(self, activation_id: str, to_number: str | None = None) -> dict[str, Any]:
        token = await self._auth()
        if not token:
            return {"success": False, "calls": [], "raw": "auth_failed"}

        params: dict[str, str] = {
            "reservationId": str(activation_id or "").strip(),
            "reservationType": "verification",
        }
        if to_number:
            params["to"] = str(to_number)
        session = await SessionManager.get_session()
        async with session.get(
            f"{self.BASE}/pub/v2/calls",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        ) as resp:
            text = await resp.text()
            try:
                data = await resp.json()
            except Exception:
                data = {"raw_text": text}

        calls: list[dict[str, Any]] = []
        if isinstance(data, dict):
            rows = data.get("data")
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        calls.append(dict(row))
            elif isinstance(data.get("calls"), list):
                calls.extend([dict(row) for row in data.get("calls") if isinstance(row, dict)])
        elif isinstance(data, list):
            calls.extend([dict(row) for row in data if isinstance(row, dict)])
        return {"success": resp.status == 200, "calls": calls, "raw": data}

    async def download_recording(self, recording_uri: str) -> dict[str, Any]:
        uri = str(recording_uri or "").strip()
        if not uri.lower().startswith(("http://", "https://")):
            return {"success": False, "raw": "invalid_recording_uri"}

        token = await self._auth()
        session = await SessionManager.get_session()
        attempts: list[dict[str, str]] = [{}]
        if token:
            attempts.append({"Authorization": f"Bearer {token}"})

        last_error: dict[str, Any] | str = "download_failed"
        for headers in attempts:
            async with session.get(uri, headers=headers or None) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    last_error = {"status": resp.status, "raw_text": text[:500]}
                    continue
                content = await resp.read()
                if not content:
                    last_error = {"status": resp.status, "raw": "empty_recording"}
                    continue
                content_type = str(resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                return {
                    "success": True,
                    "content": content,
                    "content_type": content_type or "application/octet-stream",
                    "raw": {"status": resp.status},
                }

        return {"success": False, "raw": last_error}

    async def cancel(self, activation_id):
        token = await self._auth()
        if not token:
            return {"success": False, "raw": "auth_failed"}

        session = await SessionManager.get_session()
        async with session.post(
            f"{self.BASE}/pub/v2/verifications/{activation_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            text = await resp.text()
            try:
                data = await resp.json()
            except Exception:
                data = {"raw_text": text}
            success = resp.status in (200, 201, 202, 204)
            if not success and isinstance(data, dict):
                code = str(data.get("errorCode") or "").strip().lower()
                desc = str(data.get("errorDescription") or data.get("message") or "").strip().lower()
                if code in {"cancelled", "canceled", "alreadycancelled", "already_canceled"}:
                    success = True
                elif any(marker in desc for marker in ("cancelled", "canceled", "already cancelled", "already canceled")):
                    success = True
            return {"success": success, "raw": data}

    async def resend(self, activation_id: str) -> dict[str, Any]:
        token = await self._auth()
        if not token:
            return {"success": False, "raw": "auth_failed"}
        verification_id = str(activation_id or "").strip()
        if not verification_id:
            return {"success": False, "raw": "missing_verification_id"}

        session = await SessionManager.get_session()
        async with session.post(
            f"{self.BASE}/pub/v2/verifications/{verification_id}/reuse",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            text = await resp.text()
            try:
                data = await resp.json()
            except Exception:
                data = {"raw_text": text}
            headers = dict(resp.headers)

        if resp.status not in (200, 201):
            return {"success": False, "raw": data}

        link = self._link_from_payload(data, headers=headers)
        if not link:
            # Some deployments may return a success without follow-up link.
            return {"success": True, "order_id": verification_id, "raw": data}

        status, details, _h = await self._request_link(token, link)
        if status != 200 or not isinstance(details, dict):
            return {"success": False, "raw": {"create_response": data, "details": details}}

        new_id = str(details.get("id") or verification_id).strip() or verification_id
        number = str(details.get("number") or "").strip()
        out: dict[str, Any] = {"success": True, "order_id": new_id, "raw": details}
        if number:
            out["number"] = number
        return out

    @classmethod
    def _duration_meta_by_key(cls, duration_key: str) -> tuple[str, int] | None:
        for key, label, hours in cls.RENTAL_DURATIONS:
            if key == duration_key:
                return label, hours
        return None

    @classmethod
    def _duration_key_from_hours(cls, hours: int) -> str:
        for key, _label, h in cls.RENTAL_DURATIONS:
            if int(h) == int(hours):
                return key
        # Fallback to one day if caller passed unknown hours.
        return "oneDay"

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _link_from_payload(data: Any, headers: dict[str, Any] | None = None) -> dict[str, str] | None:
        if isinstance(data, dict):
            href = str(data.get("href") or "").strip()
            method = str(data.get("method") or "GET").strip().upper() or "GET"
            if href:
                return {"href": href, "method": method}
        if headers:
            location = str(headers.get("Location") or headers.get("location") or "").strip()
            if location:
                return {"href": location, "method": "GET"}
        return None

    async def _request_link(self, token: str, link: dict[str, str]) -> tuple[int, Any, dict[str, Any]]:
        session = await SessionManager.get_session()
        method = str(link.get("method") or "GET").strip().upper() or "GET"
        href = str(link.get("href") or "").strip()
        if not href:
            return 0, {"raw_text": "missing_link_href"}, {}
        async with session.request(
            method,
            href,
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            text = await resp.text()
            try:
                data = await resp.json()
            except Exception:
                data = {"raw_text": text}
            return resp.status, data, dict(resp.headers)

    async def _resolve_reservation_details(
        self,
        token: str,
        reservation_id: str,
    ) -> tuple[Any, Any]:
        """Return (sale_payload, reservation_payload) best-effort for a rental reservation id."""
        probe_link = {"href": f"{self.BASE}/pub/v2/reservations/{reservation_id}", "method": "GET"}
        status, probe, headers = await self._request_link(token, probe_link)
        if status != 200:
            return probe, None

        # /reservations/{id} may return a link to the actual reservation payload.
        next_link = self._link_from_payload(probe, headers=headers)
        reservation_payload = probe
        if next_link:
            _s2, reservation_payload, _h2 = await self._request_link(token, next_link)

        sale_payload = None
        if isinstance(reservation_payload, dict):
            sale_ref = reservation_payload.get("sale")
            sale_link = None
            if isinstance(sale_ref, dict):
                sale_link = self._link_from_payload(sale_ref)
            if sale_link:
                _s3, sale_payload, _h3 = await self._request_link(token, sale_link)

        return sale_payload, reservation_payload

    async def get_rental_prices(self, service, country=None):
        token = await self._auth()
        if not token:
            return {"success": False, "options": [], "raw": "auth_failed"}

        session = await SessionManager.get_session()
        options: list[dict[str, Any]] = []
        last_error: Any = None
        for duration_key, duration_label, duration_hours in self.RENTAL_DURATIONS:
            # Try both renewable modes because support differs by service/duration.
            for is_renewable in (False, True):
                payload = {
                    "serviceName": service,
                    "areaCode": False,
                    "numberType": "mobile",
                    "capability": "sms",
                    "callForwarding": False,
                    "isRenewable": is_renewable,
                    "duration": duration_key,
                }
                async with session.post(
                    f"{self.BASE}/pub/v2/pricing/rentals",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                ) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json()
                    except Exception:
                        data = {"raw_text": text}

                if resp.status != 200 or not isinstance(data, dict):
                    last_error = {"status": resp.status, "raw": data, "payload": payload}
                    continue

                price_val = self._as_float(data.get("price"))
                if price_val is None or price_val <= 0:
                    last_error = {"status": resp.status, "raw": data, "payload": payload}
                    continue

                row = {
                    "country": str(country or "provider"),
                    "duration": int(duration_hours),
                    "duration_label": duration_label,
                    "price": float(price_val),
                    "count": 1,
                    "tv_duration_key": duration_key,
                    "tv_is_renewable": is_renewable,
                }
                options.append(row)

        order = {key: idx for idx, (key, _label, _hours) in enumerate(self.RENTAL_DURATIONS)}
        options.sort(
            key=lambda x: (
                order.get(str(x.get("tv_duration_key") or ""), 99),
                bool(x.get("tv_is_renewable")),
                float(x.get("price", 0)),
            )
        )
        if not options:
            return {"success": False, "options": [], "raw": last_error}
        return {"success": True, "options": options, "raw": {"serviceName": service}}

    async def rent_number(self, service, country=None, duration=1, **kwargs):
        token = await self._auth()
        if not token:
            return {"success": False, "raw": "auth_failed"}

        session = await SessionManager.get_session()
        with_state = bool(kwargs.get("tv_with_state"))
        state_code = str(kwargs.get("state_code") or "").strip().upper()
        area_code: str | None = None
        if with_state:
            if len(state_code) == 2:
                codes = self._state_area_codes(state_code)
                area_code = codes[0] if codes else None
            if not area_code:
                return {
                    "success": False,
                    "raw": {
                        "error_code": "state_area_unavailable",
                        "error_msg": "Selected state is not available for rental.",
                        "state_code": state_code or None,
                    },
                }

        try:
            duration_hours = int(duration)
        except Exception:
            duration_hours = 24
        duration_key = str(kwargs.get("tv_duration_key") or self._duration_key_from_hours(duration_hours)).strip()
        if not duration_key:
            duration_key = "oneDay"
        is_renewable = bool(kwargs.get("tv_is_renewable"))

        payload: dict[str, object] = {
            "allowBackOrderReservations": False,
            "serviceName": service,
            "capability": "sms",
            "numberType": "mobile",
            "duration": duration_key,
            "isRenewable": is_renewable,
        }
        if area_code:
            payload["areaCodeSelectOption"] = [str(area_code)]
        if hasattr(self, "max_price") and self.max_price is not None:
            payload["maxPrice"] = self.max_price

        async with session.post(
            f"{self.BASE}/pub/v2/reservations/rental",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        ) as resp:
            text = await resp.text()
            try:
                data = await resp.json()
            except Exception:
                data = {"raw_text": text}
            response_headers = dict(resp.headers)

        if resp.status not in (200, 201):
            return {"success": False, "raw": data}

        create_link = self._link_from_payload(data, headers=response_headers)
        if not create_link:
            return {"success": False, "raw": {"create_response": data, "payload": payload}}

        sale_status, sale_payload, sale_headers = await self._request_link(token, create_link)
        if sale_status != 200:
            return {"success": False, "raw": {"create_response": data, "sale_response": sale_payload}}

        # Some endpoints return another link layer; follow once more if needed.
        sale_link = self._link_from_payload(sale_payload, headers=sale_headers)
        if sale_link and isinstance(sale_payload, dict) and set(sale_payload.keys()) <= {"href", "method"}:
            sale_status, sale_payload, _sale_headers2 = await self._request_link(token, sale_link)
            if sale_status != 200:
                return {"success": False, "raw": {"create_response": data, "sale_response": sale_payload}}

        reservation_id = ""
        reservation_payload: Any = None
        if isinstance(sale_payload, dict):
            reservations = sale_payload.get("reservations")
            if isinstance(reservations, list) and reservations:
                first = reservations[0]
                if isinstance(first, dict):
                    reservation_id = str(first.get("id") or "").strip()
                    reservation_link = self._link_from_payload(first.get("link") if isinstance(first.get("link"), dict) else {})
                    if reservation_link:
                        res_status, reservation_payload, _res_headers = await self._request_link(token, reservation_link)
                        if res_status != 200:
                            reservation_payload = None
                        elif isinstance(reservation_payload, dict):
                            nested_reservation_link = self._link_from_payload(reservation_payload, headers=_res_headers)
                            if nested_reservation_link and set(reservation_payload.keys()) <= {"href", "method"}:
                                res_status, reservation_payload, _res_headers2 = await self._request_link(token, nested_reservation_link)
                                if res_status != 200:
                                    reservation_payload = None

        if reservation_id and reservation_payload is None:
            _sale2, reservation_payload = await self._resolve_reservation_details(token, reservation_id)

        if not reservation_id and isinstance(reservation_payload, dict):
            reservation_id = str(reservation_payload.get("id") or "").strip()
        if not reservation_id and isinstance(sale_payload, dict):
            reservation_id = str(sale_payload.get("id") or "").strip()

        number = ""
        end_date = None
        billing_cycle_id = None
        refund_can_refund = None
        refund_refundable_until = None
        if isinstance(reservation_payload, dict):
            number = str(reservation_payload.get("number") or "").strip()
            end_date = reservation_payload.get("endsAt")
            billing_cycle_id = reservation_payload.get("billingCycleId")
            refund_payload = reservation_payload.get("refund")
            if isinstance(refund_payload, dict):
                if "canRefund" in refund_payload:
                    refund_can_refund = bool(refund_payload.get("canRefund"))
                refund_refundable_until = refund_payload.get("refundableUntil")

        price_val = None
        if isinstance(sale_payload, dict):
            price_val = self._as_float(sale_payload.get("total"))
            if price_val is None:
                price_val = self._as_float(sale_payload.get("totalCost"))
        if reservation_id and number:
            return {
                "success": True,
                "order_id": reservation_id,
                "number": number,
                "price": price_val,
                "end_date": end_date,
                "tv_is_renewable": bool(is_renewable),
                "billing_cycle_id": billing_cycle_id,
                "refund_can_refund": refund_can_refund,
                "refund_refundable_until": refund_refundable_until,
                "raw": {
                    "create": data,
                    "sale": sale_payload,
                    "reservation": reservation_payload,
                },
            }
        return {
            "success": False,
            "raw": {
                "create": data,
                "sale": sale_payload,
                "reservation": reservation_payload,
                "payload": payload,
            },
        }

    async def get_rental_sms(self, activation_id: str, size: int = 20, page: int = 1) -> dict[str, Any]:
        return await self.get_sms(activation_id)

    async def get_rental_info(self, activation_id: str) -> dict[str, Any]:
        token = await self._auth()
        if not token:
            return {"success": False, "raw": "auth_failed"}

        reservation_id = str(activation_id or "").strip()
        if not reservation_id:
            return {"success": False, "raw": "missing_reservation_id"}

        sale_payload, reservation_payload = await self._resolve_reservation_details(token, reservation_id)
        if not isinstance(reservation_payload, dict):
            return {"success": False, "raw": {"sale": sale_payload, "reservation": reservation_payload}}

        refund_payload = reservation_payload.get("refund") if isinstance(reservation_payload.get("refund"), dict) else {}
        return {
            "success": True,
            "refund_can_refund": bool(refund_payload.get("canRefund")) if "canRefund" in refund_payload else None,
            "refund_refundable_until": refund_payload.get("refundableUntil"),
            "end_date": reservation_payload.get("endsAt"),
            "raw": {
                "sale": sale_payload,
                "reservation": reservation_payload,
            },
        }

    async def finish_rental(self, activation_id: str) -> dict[str, Any]:
        token = await self._auth()
        if not token:
            return {"success": False, "raw": "auth_failed"}

        reservation_id = str(activation_id or "").strip()
        if not reservation_id:
            return {"success": False, "raw": "missing_reservation_id"}

        # Best-effort: discover reservation details then use refund action link.
        sale_payload, reservation_payload = await self._resolve_reservation_details(token, reservation_id)
        session = await SessionManager.get_session()
        request_plan: list[tuple[str, str]] = []

        if isinstance(reservation_payload, dict):
            refund = reservation_payload.get("refund")
            refund_link = None
            if isinstance(refund, dict):
                refund_link = self._link_from_payload(refund.get("link") if isinstance(refund.get("link"), dict) else {})
            if refund_link:
                href = str(refund_link.get("href") or "").strip()
                method = str(refund_link.get("method") or "POST").strip().upper() or "POST"
                if href:
                    request_plan.append((method, href))
                    if method != "POST":
                        request_plan.append(("POST", href))

        # Explicit refundable endpoints.
        request_plan.extend(
            [
                ("POST", f"{self.BASE}/pub/v2/reservations/rental/nonrenewable/{reservation_id}/refund"),
                ("POST", f"{self.BASE}/pub/v2/reservations/rental/renewable/{reservation_id}/refund"),
            ]
        )

        for method, path in request_plan:
            async with session.request(method, path, headers={"Authorization": f"Bearer {token}"}) as resp:
                text = await resp.text()
                try:
                    data = await resp.json()
                except Exception:
                    data = {"raw_text": text}
                if resp.status in (200, 201, 204):
                    return {"success": True, "raw": data}

        return {"success": False, "raw": {"sale": sale_payload, "reservation": reservation_payload}}

    async def renew_rental(self, activation_id: str) -> dict[str, Any]:
        token = await self._auth()
        if not token:
            return {"success": False, "raw": "auth_failed"}
        reservation_id = str(activation_id or "").strip()
        if not reservation_id:
            return {"success": False, "raw": "missing_reservation_id"}
        session = await SessionManager.get_session()
        async with session.post(
            f"{self.BASE}/pub/v2/reservations/rental/renewable/{reservation_id}/renew",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            text = await resp.text()
            try:
                data = await resp.json()
            except Exception:
                data = {"raw_text": text}
            return {"success": resp.status in (200, 201), "raw": data}

    async def wake_rental(self, activation_id: str) -> dict[str, Any]:
        token = await self._auth()
        if not token:
            return {"success": False, "raw": "auth_failed"}
        reservation_id = str(activation_id or "").strip()
        if not reservation_id:
            return {"success": False, "raw": "missing_reservation_id"}
        session = await SessionManager.get_session()
        async with session.post(
            f"{self.BASE}/pub/v2/wake-requests",
            headers={"Authorization": f"Bearer {token}"},
            json={"reservationId": reservation_id},
        ) as resp:
            text = await resp.text()
            try:
                data = await resp.json()
            except Exception:
                data = {"raw_text": text}
            return {"success": resp.status in (200, 201), "raw": data}

    async def get_rental_notes_tags(self, activation_id: str) -> dict[str, Any]:
        token = await self._auth()
        if not token:
            return {"success": False, "raw": "auth_failed"}
        reservation_id = str(activation_id or "").strip()
        if not reservation_id:
            return {"success": False, "raw": "missing_reservation_id"}

        sale_payload, reservation_payload = await self._resolve_reservation_details(token, reservation_id)
        notes = ""
        tags: list[str] = []
        if isinstance(reservation_payload, dict):
            notes_val = reservation_payload.get("userNotes")
            if notes_val is not None:
                notes = str(notes_val)
            tags_val = reservation_payload.get("tags")
            if isinstance(tags_val, list):
                tags = [str(x) for x in tags_val if x not in (None, "")]

        if not notes:
            session = await SessionManager.get_session()
            async with session.get(
                f"{self.BASE}/pub/v2/reservations/rental/{reservation_id}/user-notes",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                text = await resp.text()
                try:
                    payload = await resp.json()
                except Exception:
                    payload = {"raw_text": text}
                if isinstance(payload, dict):
                    for key in ("userNotes", "notes", "message"):
                        if payload.get(key):
                            notes = str(payload.get(key))
                            break

        return {
            "success": True,
            "notes": notes,
            "tags": tags,
            "raw": {
                "sale": sale_payload,
                "reservation": reservation_payload,
            },
        }

    # ------------------------------------------------------------------
    # account helpers
    async def get_account(self) -> Optional[dict]:
        """Query ``/pub/v2/account/me`` and return the JSON payload.

        ``None`` is returned if authentication fails or the request errors.
        """
        token = await self._auth()
        if not token:
            return None
        session = await SessionManager.get_session()
        async with session.get(
            f"{self.BASE}/pub/v2/account/me",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            try:
                data = await resp.json()
            except Exception:
                text = await resp.text()
                data = {"raw_text": text}
            return data

    async def get_balance(self) -> Optional[float]:
        """Return the ``currentBalance`` value from :meth:`get_account`.

        May be ``None`` if the provider does not support the endpoint or if
        the response cannot be parsed as a number.
        """
        acct = await self.get_account()
        if not acct or not isinstance(acct, dict):
            return None
        bal = acct.get("currentBalance")
        try:
            return float(bal)
        except Exception:
            return None
    async def list_services(self, reservationType: str = "verification", numberType: str | None = "mobile"):
        """Return list of available services from TextVerified (live API).

        `reservationType` is required by the API (e.g. "verification").
        """
        token = await self._auth()
        if not token:
            return None

        session = await SessionManager.get_session()
        params = {"reservationType": reservationType}
        if numberType:
            params["numberType"] = numberType

        async with session.get(
            f"{self.BASE}/pub/v2/services",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        ) as resp:
            try:
                data = await resp.json()
            except Exception:
                text = await resp.text()
                logger.warning("textverified list_services non-json response: %s", text)
                return None

            # API may return a list or a dict with 'message' etc; normalize to list
            if isinstance(data, dict) and 'message' in data:
                return data.get('message', [])
            if isinstance(data, list):
                return data
            # unexpected format
            return None
