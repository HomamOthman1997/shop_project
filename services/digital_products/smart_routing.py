from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from config import settings
from services.digital_products.catalog_service import _product_compare_key, get_game_topups
from services.digital_products.fulfillment_rules import (
    AUTO_TOPUP_MODE,
    MANUAL_TOPUP_MODE,
    game_default_unit,
    game_family_key,
    offer_compare_key,
    offer_region_label,
)
from services.digital_products.mangerr_client import MangerrClient
from services.digital_products.static_taxonomy import guess_family

ROUTE_AUTO_API = "auto_api"
ROUTE_FUTURE = "future"
ROUTE_MANUAL_REVIEW = "manual_review"
SMART_ALLOWED_PROVIDERS = {"g2bulk", "mangerr"}

_TWOPLACES = Decimal("0.01")


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _clean_provider(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_future_offer(offer: dict[str, Any]) -> bool:
    provider = _clean_provider(offer.get("provider"))
    source = str(offer.get("source") or "").strip().lower()
    source_name = str(offer.get("source_product_name") or offer.get("product_name") or "").strip().lower()
    return provider == "g2bulk" and (source == "future" or "future" in source_name)


def _is_auto_offer(offer: dict[str, Any]) -> bool:
    mode = str(offer.get("fulfillment_mode") or AUTO_TOPUP_MODE).strip()
    if mode == MANUAL_TOPUP_MODE:
        return False
    if str(offer.get("source_url") or "").strip():
        return False
    return True


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(candidate.get("provider") or "").strip().lower(),
        str(candidate.get("route") or "").strip().lower(),
        str(candidate.get("ref_id") or "").strip(),
    )


def _dedupe_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = _candidate_key(row)
        if not all(key):
            continue
        old = deduped.get(key)
        if not old or _money(row.get("cost_price") or row.get("price") or 0) < _money(old.get("cost_price") or old.get("price") or 0):
            deduped[key] = dict(row)
    out = list(deduped.values())
    out.sort(key=lambda item: (_money(item.get("cost_price") or item.get("price") or 0) if _money(item.get("cost_price") or item.get("price") or 0) > 0 else Decimal("9999999"), str(item.get("provider") or "")))
    return out


def manual_quote_compare_key(quote: dict[str, Any]) -> str:
    explicit = str((quote or {}).get("compare_key") or "").strip()
    if explicit:
        return explicit
    source_kind = str((quote or {}).get("source_kind") or "").strip().lower()
    game_id = str((quote or {}).get("game_id") or "").strip()
    game_name = str((quote or {}).get("game_name") or (quote or {}).get("product_name") or "").strip()
    item_name = str((quote or {}).get("item_name") or "").strip()
    if source_kind != "game" or not item_name:
        return ""
    family_key = str((quote or {}).get("manual_family_key") or "").strip()
    if not family_key:
        family_key = game_family_key(game_id, game_name)
    if not family_key:
        family_key, _label = guess_family("games", game_name or item_name, [item_name])
    if not family_key or family_key == "other":
        return ""
    variant_name = str((quote or {}).get("manual_variant_name") or "").strip()
    return offer_compare_key(
        family_key=family_key,
        region=offer_region_label(f"{variant_name} {game_name} {item_name}", default=variant_name or "Global"),
        offer_name=item_name,
        default_unit=game_default_unit(game_id, game_name),
    )


def smart_routing_applicable(quote: dict[str, Any]) -> bool:
    if str((quote or {}).get("source_kind") or "").strip().lower() != "game":
        return False
    if not str((quote or {}).get("game_id") or "").strip():
        return False
    return bool(manual_quote_compare_key(quote))


def _g2bulk_candidate_from_offer(row: dict[str, Any], offer: dict[str, Any], *, compare_key: str, game_id: str, game_name: str) -> dict[str, Any] | None:
    provider = _clean_provider(offer.get("provider"))
    ref_id = str(offer.get("ref_id") or offer.get("provider_ref_id") or "").strip()
    cost_price = float(_money(offer.get("price") or row.get("price") or 0))
    if provider != "g2bulk" or not ref_id or cost_price <= 0 or not bool(offer.get("available", True)):
        return None
    if _is_future_offer(offer):
        route = ROUTE_FUTURE
        fulfillment_mode = MANUAL_TOPUP_MODE
    elif _is_auto_offer(offer):
        route = ROUTE_AUTO_API
        fulfillment_mode = AUTO_TOPUP_MODE
    else:
        return None
    return {
        "provider": "g2bulk",
        "route": route,
        "ref_id": ref_id,
        "cost_price": cost_price,
        "price": cost_price,
        "compare_key": compare_key,
        "fulfillment_mode": fulfillment_mode,
        "game_id": game_id,
        "game_name": game_name,
        "catalogue_name": str(row.get("catalogue_name") or row.get("name") or "").strip(),
        "source_product_name": str(offer.get("source_product_name") or game_name or row.get("name") or "").strip(),
        "source_denomination_name": str(offer.get("source_denomination_name") or row.get("name") or "").strip(),
        "source": str(offer.get("source") or ("future" if route == ROUTE_FUTURE else "game")).strip(),
    }


async def _g2bulk_candidates(*, quote: dict[str, Any], compare_key: str, diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    game_id = str(quote.get("game_id") or "").strip()
    game_name = str(quote.get("game_name") or quote.get("product_name") or "").strip()
    if not game_id:
        return []
    try:
        rows = await get_game_topups(game_id, force=True)
    except Exception as exc:
        diagnostics["g2bulk"] = {"ok": False, "error": str(exc)[:200]}
        return []
    out: list[dict[str, Any]] = []
    matched_rows = 0
    for row in list(rows or []):
        if not isinstance(row, dict) or str(row.get("compare_key") or "").strip() != compare_key:
            continue
        matched_rows += 1
        for offer in list(row.get("provider_offers") or []):
            if not isinstance(offer, dict):
                continue
            candidate = _g2bulk_candidate_from_offer(row, offer, compare_key=compare_key, game_id=game_id, game_name=game_name)
            if candidate:
                out.append(candidate)
    diagnostics["g2bulk"] = {"ok": True, "matched_rows": matched_rows, "candidates": len(out)}
    return out


def _mangerr_candidate_from_item(item: dict[str, Any], *, compare_key: str, game_id: str, game_name: str) -> dict[str, Any] | None:
    if not bool(item.get("available", True)):
        return None
    ref_id = str(item.get("id") or "").strip()
    cost_price = float(_money(item.get("price") or 0))
    if not ref_id or cost_price <= 0:
        return None
    product_name = str(item.get("name") or "").strip()
    category_name = str(item.get("category_name") or game_name or "").strip()
    item_key = _product_compare_key(category_name=category_name, product_name=product_name)
    if item_key != compare_key:
        return None
    params = [str(value).strip() for value in list(item.get("params") or []) if str(value).strip()]
    return {
        "provider": "mangerr",
        "route": ROUTE_AUTO_API,
        "ref_id": ref_id,
        "cost_price": cost_price,
        "price": cost_price,
        "compare_key": compare_key,
        "fulfillment_mode": AUTO_TOPUP_MODE,
        "game_id": game_id,
        "game_name": game_name,
        "catalogue_name": product_name,
        "source_product_name": category_name,
        "source_denomination_name": product_name,
        "source": "mangerr",
        "params": params,
    }


async def _mangerr_candidates(*, quote: dict[str, Any], compare_key: str, diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    client = MangerrClient()
    if not client.configured():
        diagnostics["mangerr"] = {"ok": False, "status": 0, "error": "MANGERR_NOT_CONFIGURED"}
        return []
    status, payload = await client.get_products_response()
    if status != 200 or not isinstance(payload, list):
        diagnostics["mangerr"] = {"ok": False, "status": int(status or 0), "error": str(payload)[:300]}
        return []
    game_id = str(quote.get("game_id") or "").strip()
    game_name = str(quote.get("game_name") or quote.get("product_name") or "").strip()
    out = [
        candidate
        for candidate in (
            _mangerr_candidate_from_item(item, compare_key=compare_key, game_id=game_id, game_name=game_name)
            for item in payload
            if isinstance(item, dict)
        )
        if candidate
    ]
    diagnostics["mangerr"] = {"ok": True, "status": status, "candidates": len(out)}
    return out


async def _with_timeout(coro, *, timeout_sec: float, diagnostics: dict[str, Any], key: str) -> list[dict[str, Any]]:
    try:
        return await asyncio.wait_for(coro, timeout=timeout_sec)
    except asyncio.TimeoutError:
        diagnostics[key] = {"ok": False, "error": "timeout"}
    except Exception as exc:
        diagnostics[key] = {"ok": False, "error": str(exc)[:200]}
    return []


async def resolve_smart_game_routing(quote: dict[str, Any], *, sale_price: float) -> dict[str, Any]:
    compare_key = manual_quote_compare_key(quote)
    if not smart_routing_applicable({**dict(quote or {}), "compare_key": compare_key}):
        return {"enabled": False, "compare_key": compare_key, "sale_price": float(_money(sale_price)), "candidates": [], "diagnostics": {"reason": "not_applicable"}}

    diagnostics: dict[str, Any] = {}
    timeout_sec = max(2.0, float(getattr(settings, "digital_smart_routing_timeout_sec", 6.0) or 6.0))
    g2_task = _with_timeout(
        _g2bulk_candidates(quote=quote, compare_key=compare_key, diagnostics=diagnostics),
        timeout_sec=timeout_sec,
        diagnostics=diagnostics,
        key="g2bulk",
    )
    mangerr_task = _with_timeout(
        _mangerr_candidates(quote=quote, compare_key=compare_key, diagnostics=diagnostics),
        timeout_sec=timeout_sec,
        diagnostics=diagnostics,
        key="mangerr",
    )
    g2_rows, mangerr_rows = await asyncio.gather(g2_task, mangerr_task)
    candidates = _dedupe_candidates([*g2_rows, *mangerr_rows])
    return {
        "enabled": True,
        "compare_key": compare_key,
        "sale_price": float(_money(sale_price)),
        "candidates": candidates,
        "diagnostics": diagnostics,
    }


def quote_like_from_order(order: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the minimal quote shape smart routing needs from a stored order.

    Used by the admin retry surfaces, where the original quote is gone but the
    order already carries the compare_key and game identifiers.
    """
    order = order or {}
    return {
        "kind": "manual",
        "source_kind": str(order.get("website_source_kind") or "").strip(),
        "game_id": str(order.get("game_id") or "").strip(),
        "game_name": str(order.get("manual_game_name") or "").strip(),
        "product_name": str(order.get("manual_product_name") or "").strip(),
        "item_name": str(order.get("manual_item_name") or "").strip(),
        "manual_variant_name": str(order.get("manual_variant_name") or "").strip(),
        "compare_key": str(order.get("compare_key") or "").strip(),
    }


def profitable_candidates(plan: dict[str, Any], sale_price: float) -> list[dict[str, Any]]:
    sale = _money(sale_price)
    rows: list[dict[str, Any]] = []
    for row in list((plan or {}).get("candidates") or []):
        if not isinstance(row, dict):
            continue
        cost = _money(row.get("cost_price") or row.get("price") or 0)
        if cost > 0 and cost <= sale:
            rows.append(dict(row))
    rows.sort(key=lambda item: _money(item.get("cost_price") or item.get("price") or 0))
    return rows
