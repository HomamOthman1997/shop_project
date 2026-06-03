from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.numbers.provider_factory import ProviderFactory
from services.numbers.providers.error_normalizer import normalize_provider_error


_SENSITIVE_RE = re.compile(r"([A-Za-z0-9_\-]{24,})")


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _scrub(val)
            for key, val in value.items()
            if str(key).lower() not in {"api_key", "x-api-key", "x-non-api-key", "authorization", "email", "customer"}
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value[:25]]
    if isinstance(value, str):
        return _SENSITIVE_RE.sub(lambda match: match.group(0)[:4] + "..." + match.group(0)[-4:], value)
    return value


def _emit(event: str, **payload: Any) -> None:
    print(json.dumps({"event": event, **_scrub(payload)}, ensure_ascii=True, default=str))


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _sample_catalog(catalog: Any, limit: int = 10) -> Any:
    if isinstance(catalog, list):
        return catalog[:limit]
    if isinstance(catalog, dict):
        return {key: catalog[key] for key in list(catalog.keys())[:limit]}
    return catalog


def _country_iso(value: Any) -> str:
    raw = str(value or "").strip().upper()
    aliases = {"1": "US", "US": "US", "USA": "US", "2": "GB", "UK": "GB", "GB": "GB"}
    return aliases.get(raw, raw if len(raw) == 2 else "")


def _pick_candidate(
    rows: Any,
    *,
    country: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
) -> dict[str, Any] | None:
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        return None
    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        service = str(
            row.get("service_id")
            or row.get("id")
            or row.get("serviceName")
            or row.get("service_name")
            or row.get("name")
            or row.get("description")
            or row.get("full_name")
            or row.get("app_name")
            or ""
        ).strip()
        if not service:
            continue
        wanted_country = _country_iso(country)
        row_country = _country_iso(row.get("provider_country_iso") or row.get("country_iso") or row.get("short_name"))
        if wanted_country and row_country and row_country != wanted_country:
            continue
        price = (
            _as_float(row.get("price"))
            or _as_float(row.get("STRprice"))
            or _as_float(row.get("deduct"))
            or _as_float(row.get("rate"))
            or _as_float(row.get("cost"))
            or 0.0
        )
        if price <= 0:
            continue
        if max_price is not None and price > max_price:
            continue
        if min_price is not None and price < min_price:
            continue
        candidates.append((price, {"service": service, "price": price, "raw": row}))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], str(item[1]["service"])))
    return candidates[0][1]


async def _maybe(provider: Any, method_name: str, *args: Any, timeout: float = 20.0, **kwargs: Any) -> tuple[bool, Any]:
    if not hasattr(provider, method_name):
        return False, {"reason": "method_missing"}
    try:
        result = await asyncio.wait_for(getattr(provider, method_name)(*args, **kwargs), timeout=timeout)
        return True, result
    except Exception as exc:
        return False, {"reason": type(exc).__name__, "message": str(exc)}


async def verify_provider(args: argparse.Namespace) -> int:
    provider = ProviderFactory.get(args.provider)
    _emit("start", provider=args.provider, purchase=bool(args.purchase), service=args.service, country=args.country)

    ok, balance = await _maybe(provider, "get_balance", timeout=args.timeout)
    _emit("balance", provider=args.provider, ok=ok, result=balance)

    catalog: Any = None
    ok, catalog = await _maybe(provider, "list_services", timeout=args.timeout)
    _emit(
        "service_catalog",
        provider=args.provider,
        ok=ok,
        count=len(catalog) if isinstance(catalog, (list, dict)) else None,
        sample=_sample_catalog(catalog),
    )

    service = args.service
    if not service:
        candidate = _pick_candidate(catalog, country=args.country, max_price=args.max_price)
        if candidate:
            service = str(candidate["service"])
            _emit("selected_candidate", provider=args.provider, candidate=candidate)
    if not service:
        _emit("stop", provider=args.provider, reason="no_service_candidate")
        return 2

    ok, price = await _maybe(provider, "get_price", service, country=args.country, timeout=args.timeout)
    price_success = bool(isinstance(price, dict) and price.get("success"))
    _emit(
        "price",
        provider=args.provider,
        ok=ok,
        service=service,
        country=args.country,
        result=price,
        normalized_error=None if price_success else normalize_provider_error(price.get("raw") if isinstance(price, dict) else price),
    )

    if not args.purchase:
        _emit("stop", provider=args.provider, reason="dry_run_complete")
        return 0

    ok, order = await _maybe(provider, "buy_number", service, country=args.country, timeout=args.timeout)
    order_success = bool(isinstance(order, dict) and order.get("success"))
    normalized = None if order_success else normalize_provider_error(order.get("raw") if isinstance(order, dict) else order)
    _emit("purchase", provider=args.provider, ok=ok, service=service, country=args.country, result=order, normalized_error=normalized)

    order_id = str(order.get("order_id") or order.get("id") or "").strip() if isinstance(order, dict) else ""
    if order_id and not args.no_auto_cancel:
        ok, cancel = await _maybe(provider, "cancel", order_id, timeout=args.timeout)
        cancel_success = bool(isinstance(cancel, dict) and cancel.get("success"))
        _emit(
            "auto_cancel",
            provider=args.provider,
            ok=ok,
            order_id=order_id,
            result=cancel,
            normalized_error=None if cancel_success else normalize_provider_error(cancel.get("raw") if isinstance(cancel, dict) else cancel),
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Live smoke verifier for one Numbers provider.")
    parser.add_argument("provider", help="Provider code, e.g. nonvoip, smsready, pvadeals")
    parser.add_argument("--service", default="", help="Provider service id/name to test. If omitted, a cheap catalog candidate is used.")
    parser.add_argument("--country", default="US", help="Country hint passed to get_price/buy_number.")
    parser.add_argument("--max-price", type=float, default=1.0, help="Max candidate price when auto-selecting from catalog.")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--purchase", action="store_true", help="Actually call buy_number. Default is dry-run only.")
    parser.add_argument("--no-auto-cancel", action="store_true", help="Do not call cancel if purchase returns an order id.")
    args = parser.parse_args()
    return asyncio.run(verify_provider(args))


if __name__ == "__main__":
    raise SystemExit(main())
