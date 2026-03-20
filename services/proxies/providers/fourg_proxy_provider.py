import json
import logging
import time
from typing import Any

from config import settings
from services.numbers.core.session_manager import SessionManager

from .base_provider import BaseProxyProvider

logger = logging.getLogger("proxy_4g")


def _as_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _as_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0


class FourGProxyProvider(BaseProxyProvider):
    def __init__(self) -> None:
        self._cached_login_token: str = ""
        self._cached_login_expiry: float = 0.0
        self._cached_history_price: float = 0.0
        self._cached_history_price_at: float = 0.0
        self._history_price_ttl_sec: int = 300

    @property
    def base_url(self) -> str:
        return str(settings.fourg_proxy_base_url or "").strip().rstrip("/")

    @property
    def api_key(self) -> str:
        return str(settings.fourg_proxy_key or "").strip()

    @property
    def api_token(self) -> str:
        return str(settings.fourg_proxy_token or "").strip()

    @property
    def email(self) -> str:
        return str(settings.fourg_proxy_email or "").strip()

    @property
    def password(self) -> str:
        return str(settings.fourg_proxy_password or "").strip()

    def _has_login_auth(self) -> bool:
        return bool(self.email and self.password)

    def _configured(self) -> bool:
        return bool(self.base_url and (self.api_key or self.api_token or self._has_login_auth()))

    @staticmethod
    def _extract_token(data: Any) -> str:
        if not isinstance(data, dict):
            return ""

        for key in ("token", "access_token", "api_token", "jwt", "bearer"):
            value = data.get(key)
            if value:
                return str(value).strip()

        for branch in ("data", "result", "message"):
            nested = data.get(branch)
            if isinstance(nested, dict):
                for key in ("token", "access_token", "api_token", "jwt", "bearer"):
                    value = nested.get(key)
                    if value:
                        return str(value).strip()
        return ""

    @staticmethod
    def _extract_expires_seconds(data: Any) -> float:
        if not isinstance(data, dict):
            return 0.0

        def _pick(src: dict[str, Any]) -> float:
            for key in ("expires_in", "expires", "expiresIn", "ttl"):
                value = src.get(key)
                try:
                    n = float(value)
                    if n > 0:
                        return n
                except Exception:
                    continue
            return 0.0

        direct = _pick(data)
        if direct > 0:
            return direct

        for branch in ("data", "result", "message"):
            nested = data.get(branch)
            if isinstance(nested, dict):
                nested_ttl = _pick(nested)
                if nested_ttl > 0:
                    return nested_ttl
        return 0.0

    async def _login_for_token(self, *, force_refresh: bool = False) -> str:
        if not self._has_login_auth():
            return ""

        now = time.monotonic()
        if not force_refresh and self._cached_login_token and now < self._cached_login_expiry:
            return self._cached_login_token

        session = await SessionManager.get_session()
        login_paths = (
            "/api/v2/login",
            "/api/login",
            "/login",
            "/api/v2/auth/login",
            "/auth/login",
        )
        login_payloads = (
            {"email": self.email, "password": self.password},
            {"username": self.email, "password": self.password},
            {"user": self.email, "password": self.password},
        )

        for path in login_paths:
            url = f"{self.base_url}{path}"
            for payload in login_payloads:
                try:
                    async with session.post(
                        url,
                        json=payload,
                        headers={"Accept": "application/json"},
                        timeout=20,
                    ) as resp:
                        text = await resp.text()
                        try:
                            data = await resp.json(content_type=None)
                        except Exception:
                            data = text

                    if resp.status not in (200, 201):
                        continue

                    token = self._extract_token(data)
                    if token:
                        ttl = self._extract_expires_seconds(data) or 3600.0
                        self._cached_login_token = token
                        self._cached_login_expiry = time.monotonic() + max(60.0, ttl - 30.0)
                        return token
                except Exception:
                    logger.exception("4G login failed: %s", path)
                    continue
        return ""

    async def _resolve_auth_token(self, *, force_refresh_login: bool = False) -> str:
        if self.api_token:
            return self.api_token
        if self.api_key:
            return self.api_key
        return await self._login_for_token(force_refresh=force_refresh_login)

    async def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        session = await SessionManager.get_session()
        try:
            if method.upper() == "POST":
                async with session.post(url, params=params, headers=headers, json=payload or {}, timeout=20) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = text
                    return resp.status, data
            async with session.get(url, params=params, headers=headers, timeout=20) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = text
                return resp.status, data
        except Exception as exc:
            logger.exception("4G request failed: %s %s", method, url)
            return 0, {"title": "REQUEST_ERROR", "details": str(exc)}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        if not self._configured():
            return 0, {"title": "NOT_CONFIGURED", "details": "4G provider settings are missing"}

        url = f"{self.base_url}{path}"
        q = dict(params or {})
        if self.api_key:
            q.setdefault("api_key", self.api_key)
            q.setdefault("key", self.api_key)

        token = await self._resolve_auth_token()
        if not token and not self.api_key:
            return 0, {"title": "AUTH_FAILED", "details": "4G auth token/key not available"}

        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["X-API-KEY"] = self.api_key or token
        elif self.api_key:
            headers["X-API-KEY"] = self.api_key

        status, data = await self._send(method, url, params=q, headers=headers, payload=payload)
        if status in (401, 403) and self._has_login_auth() and not self.api_token and not self.api_key:
            refreshed = await self._resolve_auth_token(force_refresh_login=True)
            if refreshed:
                retry_headers = {
                    "Accept": "application/json",
                    "Authorization": f"Bearer {refreshed}",
                    "X-API-KEY": refreshed,
                }
                return await self._send(method, url, params=q, headers=retry_headers, payload=payload)
        return status, data

    @staticmethod
    def _extract_rows(data: Any) -> list[dict]:
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("data", "list", "items", "result", "packages", "message", "transactions"):
                value = data.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
            if all(isinstance(v, dict) for v in data.values()):
                return [v for v in data.values() if isinstance(v, dict)]
        return []

    def _package_price_overrides(self) -> dict[str, float]:
        raw = str(getattr(settings, "fourg_proxy_package_prices", "") or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("Invalid FOURG_PROXY_PACKAGE_PRICES JSON; ignoring overrides")
            return {}
        if not isinstance(parsed, dict):
            return {}

        out: dict[str, float] = {}
        for key, value in parsed.items():
            price = _as_float(value)
            if price > 0:
                out[str(key).strip().lower()] = round(price, 4)
        return out

    @staticmethod
    def _extract_package_name(pkg: dict[str, Any]) -> str:
        return str(pkg.get("package_name") or pkg.get("name") or pkg.get("title") or "").strip()

    async def _estimate_history_price(self) -> float:
        now = time.monotonic()
        if (now - self._cached_history_price_at) < self._history_price_ttl_sec:
            return self._cached_history_price

        status, data = await self._request("GET", "/customer-transactions", params={"offset": 0})
        amounts: list[float] = []
        if status in (200, 201):
            rows = self._extract_rows(data)
            for row in rows[:150]:
                if str(row.get("op_type") or "").upper() != "NEW_PROXY":
                    continue
                amount = _as_float(row.get("amount"))
                if amount > 0:
                    amounts.append(amount)

        price = round(sum(amounts) / len(amounts), 4) if amounts else 0.0
        self._cached_history_price = price
        self._cached_history_price_at = now
        return price

    async def _fetch_packages(self) -> list[dict[str, Any]]:
        for path in ("/packages", "/api/v2/packages"):
            status, data = await self._request("GET", path)
            if status not in (200, 201):
                continue
            rows = self._extract_rows(data)
            if rows:
                return rows
        return []

    async def _fetch_parent_proxies(self, package_id: int) -> list[dict[str, Any]]:
        params = {"pkg_id": int(package_id), "offset": 0}
        for path in ("/parent-proxies", "/api/v2/parent-proxies"):
            status, data = await self._request("GET", path, params=params)
            if status not in (200, 201):
                continue
            rows = self._extract_rows(data)
            if rows:
                return rows
        return []

    @staticmethod
    def _is_available_parent(row: dict[str, Any]) -> bool:
        if not isinstance(row, dict):
            return False
        status = str(row.get("status") or "").strip().upper()
        if status and status not in {"ACTIVE", "AVAILABLE"}:
            return False
        flag = row.get("is_available")
        if flag is False:
            return False
        if isinstance(flag, str) and flag.strip().lower() in {"0", "false", "no"}:
            return False
        return True

    def _resolve_offer_price(
        self,
        row: dict[str, Any],
        *,
        package_id: int,
        package_name: str,
        package_overrides: dict[str, float],
        history_fallback: float,
    ) -> float:
        direct = _as_float(
            row.get("price")
            or row.get("cost")
            or row.get("amount")
            or row.get("package_price")
            or row.get("monthly_price")
        )
        if direct > 0:
            return round(direct, 4)

        pkg_key = str(package_id).strip().lower()
        if pkg_key in package_overrides:
            return package_overrides[pkg_key]

        pkg_name_key = package_name.strip().lower()
        if pkg_name_key and pkg_name_key in package_overrides:
            return package_overrides[pkg_name_key]

        if history_fallback > 0:
            return round(history_fallback, 4)

        default_price = _as_float(getattr(settings, "fourg_proxy_default_price", 0.0))
        if default_price > 0:
            return round(default_price, 4)
        return 0.0

    @staticmethod
    def _rotation_period(row: dict[str, Any]) -> str:
        rotation = _as_int(row.get("rotation_time"))
        if rotation > 0:
            return f"Rotation {rotation}s"
        usage = _as_int(row.get("usage"))
        if usage == -1:
            return "Unlimited usage"
        if usage > 0:
            return f"Usage {usage}%"
        return "-"

    def _build_parent_offer(
        self,
        row: dict[str, Any],
        *,
        package_id: int,
        package_name: str,
        package_overrides: dict[str, float],
        history_fallback: float,
    ) -> dict[str, Any] | None:
        if not self._is_available_parent(row):
            return None

        parent_proxy_id = _as_int(row.get("id") or row.get("parent_proxy_id"))
        if parent_proxy_id <= 0:
            return None

        country = str(row.get("country_name") or row.get("country") or "Any").strip() or "Any"
        city = str(row.get("city_name") or row.get("city") or "Any").strip() or "Any"
        state = str(row.get("state_name") or row.get("state") or "Any").strip() or "Any"
        provider_name = str(row.get("service_provider_name") or "").strip()
        technology = str(row.get("technology") or "").strip()

        title_parts = [part for part in (package_name, provider_name, technology) if part]
        title = " | ".join(title_parts) if title_parts else f"Package {package_id}"
        price = self._resolve_offer_price(
            row,
            package_id=package_id,
            package_name=package_name,
            package_overrides=package_overrides,
            history_fallback=history_fallback,
        )

        raw = dict(row)
        raw["package_id"] = package_id
        raw["pkg_id"] = package_id
        raw["parent_proxy_id"] = parent_proxy_id
        raw["package_name"] = package_name

        return {
            "provider": "4g",
            "offer_id": f"{package_id}:{parent_proxy_id}",
            "title": title,
            "country": country,
            "state": state,
            "city": city,
            "period": self._rotation_period(row),
            "price": price,
            "raw": raw,
        }

    async def list_offers(self) -> list[dict[str, Any]]:
        if not self._configured():
            return []

        package_overrides = self._package_price_overrides()
        history_fallback = await self._estimate_history_price()
        packages = await self._fetch_packages()

        offers: list[dict[str, Any]] = []
        for pkg in packages:
            package_id = _as_int(pkg.get("id") or pkg.get("package_id"))
            if package_id <= 0:
                continue
            package_name = self._extract_package_name(pkg) or f"Package {package_id}"
            parent_rows = await self._fetch_parent_proxies(package_id)

            if parent_rows:
                for row in parent_rows:
                    offer = self._build_parent_offer(
                        row,
                        package_id=package_id,
                        package_name=package_name,
                        package_overrides=package_overrides,
                        history_fallback=history_fallback,
                    )
                    if offer:
                        offers.append(offer)
                continue

            fallback_price = self._resolve_offer_price(
                {},
                package_id=package_id,
                package_name=package_name,
                package_overrides=package_overrides,
                history_fallback=history_fallback,
            )
            offers.append(
                {
                    "provider": "4g",
                    "offer_id": f"{package_id}:0",
                    "title": package_name,
                    "country": "Any",
                    "state": "Any",
                    "city": "Any",
                    "period": "-",
                    "price": fallback_price,
                    "raw": {
                        "package_id": package_id,
                        "pkg_id": package_id,
                        "parent_proxy_id": 0,
                        "package_name": package_name,
                    },
                }
            )

        dedup: dict[tuple[str, str], dict[str, Any]] = {}
        for offer in offers:
            key = (str(offer.get("offer_id") or ""), str(offer.get("title") or ""))
            if key[0]:
                dedup[key] = offer
        return list(dedup.values())

    @staticmethod
    def _extract_credentials(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        src = data
        for k in ("data", "result", "message"):
            if isinstance(data.get(k), dict):
                src = data[k]
                break

        host = src.get("host") or src.get("ip") or src.get("server")
        port = src.get("port")
        endpoint = src.get("proxy") or src.get("endpoint")
        if not endpoint and host and port:
            endpoint = f"{host}:{port}"

        return {
            "order_id": src.get("id") or src.get("order_id") or src.get("account_id"),
            "endpoint": endpoint,
            "username": src.get("username") or src.get("user"),
            "password": src.get("password") or src.get("pass"),
            "expires_at": src.get("expire_at") or src.get("expiry") or src.get("expired_at"),
        }

    @staticmethod
    def _parse_offer_ids(offer: dict[str, Any]) -> tuple[int, int]:
        raw = offer.get("raw") if isinstance(offer.get("raw"), dict) else {}
        package_id = _as_int(raw.get("package_id") or raw.get("pkg_id"))
        parent_proxy_id = _as_int(raw.get("parent_proxy_id") or raw.get("id"))

        if package_id <= 0 or parent_proxy_id <= 0:
            offer_id = str(offer.get("offer_id") or "").strip()
            if ":" in offer_id:
                left, right = offer_id.split(":", 1)
                if package_id <= 0:
                    package_id = _as_int(left)
                if parent_proxy_id <= 0:
                    parent_proxy_id = _as_int(right)
            elif package_id <= 0:
                package_id = _as_int(offer_id)
        return package_id, parent_proxy_id

    async def rent_offer(self, offer: dict[str, Any]) -> dict[str, Any]:
        if not self._configured():
            return {"success": False, "raw": {"title": "NOT_CONFIGURED"}}

        package_id, parent_proxy_id = self._parse_offer_ids(offer)
        if package_id <= 0:
            return {"success": False, "raw": {"title": "INVALID_PACKAGE_ID"}}

        raw = offer.get("raw") if isinstance(offer.get("raw"), dict) else {}
        payload = {
            "package_id": package_id,
            "pkg_id": package_id,
            "parent_proxy_id": parent_proxy_id,
            "id": parent_proxy_id,
            "service_provider_id": raw.get("service_provider_id"),
            "service_provider_city_id": raw.get("service_provider_city_id"),
            "country_id": raw.get("country_id"),
            "city_id": raw.get("city_id"),
        }
        payload = {k: v for k, v in payload.items() if v not in (None, "", "Any", 0)}

        attempts = [
            "/api/v2/proxy-accounts",
            "/proxy-accounts",
            "/api/v2/create-proxy-account",
        ]

        last_raw: Any = None
        for path in attempts:
            status, data = await self._request("POST", path, payload=payload)
            last_raw = data
            if status in (200, 201):
                creds = self._extract_credentials(data)
                if creds.get("endpoint") or creds.get("username"):
                    return {"success": True, **creds, "raw": data}

        return {"success": False, "raw": last_raw}

    async def refresh_proxy(self, order_data: dict[str, Any], *, with_check: bool = False) -> dict[str, Any]:
        if not self._configured():
            return {"success": False, "raw": {"title": "NOT_CONFIGURED"}}

        account_id = (
            order_data.get("provider_order_id")
            or order_data.get("proxy_provider_order_id")
            or order_data.get("proxy_account_id")
        )
        if not account_id:
            return {"success": False, "raw": {"title": "MISSING_ACCOUNT_ID"}}

        payload = {"account_id": account_id, "id": account_id}

        refresh_paths = [
            "/api/v2/proxy-accounts/refresh",
            "/proxy-accounts/refresh",
            "/api/v2/proxy-accounts/redial",
            "/proxy-accounts/redial",
        ]

        last_raw: Any = None
        for path in refresh_paths:
            status, data = await self._request("POST", path, payload=payload)
            last_raw = data
            if status not in (200, 201):
                continue
            creds = self._extract_credentials(data)
            if creds.get("endpoint") or creds.get("username"):
                return {"success": True, **creds, "raw": data}

        info_paths = [
            f"/api/v2/proxy-accounts/{account_id}",
            f"/proxy-accounts/{account_id}",
        ]
        for path in info_paths:
            status, data = await self._request("GET", path)
            last_raw = data
            if status not in (200, 201):
                continue
            creds = self._extract_credentials(data)
            if creds.get("endpoint") or creds.get("username"):
                return {"success": True, **creds, "raw": data}

        return {"success": False, "raw": last_raw}
