from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from config import settings
from utils.translations import t

from .g2bulk_client import G2BulkClient

_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_CACHE_LOCK = asyncio.Lock()
_DEFAULT_TOP_GAMES = ("pubg", "mobile legends", "free fire", "honor of kings", "new state")


def _norm(text: str | None) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _looks_game(name: str | None) -> bool:
    n = _norm(name)
    if not n:
        return False
    keys = (
        "pubg",
        "uc",
        "mobile legends",
        "free fire",
        "honor of kings",
        "new state",
        "cod",
        "call of duty",
        "game",
        "top up",
        "top-up",
    )
    return any(k in n for k in keys)


def _clean_gift_name(name: str | None) -> str:
    label = str(name or "").strip()
    if not label:
        return "-"
    label = re.sub(r"\([^)]*\)", " ", label, flags=re.IGNORECASE)
    label = re.sub(r"\b(gift\s*cards?|giftcards?|vouchers?|voucher|accounts?)\b", " ", label, flags=re.IGNORECASE)
    label = re.sub(r"\s+", " ", label).strip(" -|/")
    return label or str(name or "").strip()


def _best_id(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        raw = str(value).strip()
        if raw:
            return raw
    return ""


async def get_catalog_snapshot(force: bool = False) -> dict[str, Any]:
    ttl = max(10, int(getattr(settings, "g2bulk_catalog_cache_ttl_sec", 120) or 120))
    now = time.time()
    if not force and _CACHE.get("data") and (now - float(_CACHE.get("ts") or 0.0)) < ttl:
        return dict(_CACHE["data"])

    async with _CACHE_LOCK:
        now = time.time()
        if not force and _CACHE.get("data") and (now - float(_CACHE.get("ts") or 0.0)) < ttl:
            return dict(_CACHE["data"])

        client = G2BulkClient()
        if not client.configured():
            snapshot = {"enabled": False, "gift_categories": [], "games": [], "products_by_category": {}, "topups_by_game": {}}
            _CACHE["ts"] = now
            _CACHE["data"] = snapshot
            return dict(snapshot)

        raw_categories, raw_products, raw_games = await asyncio.gather(
            client.get_categories(),
            client.get_products(),
            client.get_games(),
        )

    products_by_category: dict[str, list[dict[str, Any]]] = {}
    for row in raw_products:
        product_id = _best_id(row, "id", "product_id", "ID")
        if not product_id:
            continue
        cat_id = _best_id(row, "category_id", "cat_id", "categoryId")
        if not cat_id:
            continue
        name = str(row.get("name") or row.get("title") or row.get("product_name") or t("en", "catalog_fallback_product").format(product_id=product_id))
        price = _to_float(row.get("price") or row.get("unit_price") or row.get("buyer_price") or row.get("sell_price"))
        stock = _to_int(row.get("stock") or row.get("quantity") or row.get("available"))
        products_by_category.setdefault(cat_id, []).append(
            {
                "id": product_id,
                "name": name,
                "clean_name": _clean_gift_name(name),
                "price": price,
                "stock": stock,
                "raw": row,
            }
        )

    gift_categories: list[dict[str, Any]] = []
    for row in raw_categories:
        cat_id = _best_id(row, "id", "category_id", "ID")
        if not cat_id:
            continue
        name = str(row.get("name") or row.get("title") or t("en", "catalog_fallback_category").format(cat_id=cat_id))
        if _looks_game(name):
            continue
        count = len(products_by_category.get(cat_id) or [])
        gift_categories.append({"id": cat_id, "name": name, "clean_name": _clean_gift_name(name), "count": count, "raw": row})
    gift_categories.sort(key=lambda x: (_norm(x.get("clean_name")), str(x.get("id"))))

    games: list[dict[str, Any]] = []
    for row in raw_games:
        game_code = _best_id(row, "code", "game_code")
        game_id = game_code or _best_id(row, "id", "game_id", "ID")
        if not game_id:
            continue
        name = str(row.get("name") or row.get("title") or row.get("game_name") or t("en", "catalog_fallback_game").format(game_id=game_id))
        bias = 0
        n = _norm(name)
        for idx, key in enumerate(_DEFAULT_TOP_GAMES):
            if key in n:
                bias = len(_DEFAULT_TOP_GAMES) - idx
                break
        games.append({"id": game_id, "code": game_code or game_id, "name": name, "bias": bias, "raw": row})
    games.sort(key=lambda x: (-int(x.get("bias") or 0), _norm(x.get("name"))))

    snapshot = {
        "enabled": True,
        "gift_categories": gift_categories,
        "games": games,
        "products_by_category": products_by_category,
        "topups_by_game": {},
    }
    _CACHE["ts"] = now
    _CACHE["data"] = snapshot
    return dict(snapshot)


async def get_game_topups(game_id: str) -> list[dict[str, Any]]:
    snapshot = await get_catalog_snapshot(force=False)
    topup_map = dict(snapshot.get("topups_by_game") or {})
    if str(game_id) in topup_map:
        return list(topup_map.get(str(game_id)) or [])

    client = G2BulkClient()
    rows = await client.get_game_catalogue(game_id)
    normalized: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        product_id = _best_id(row, "id", "product_id", "ID")
        name = str(row.get("name") or row.get("title") or row.get("product_name") or t("en", "catalog_fallback_pack").format(item_id=product_id or game_id))
        if not product_id:
            product_id = f"{game_id}_{idx+1}"
        price = _to_float(row.get("price") or row.get("amount") or row.get("unit_price") or row.get("buyer_price") or row.get("sell_price"))
        normalized.append(
            {
                "id": product_id,
                "name": name,
                "catalogue_name": str(row.get("name") or row.get("title") or "").strip() or name,
                "price": price,
                "requires_server": bool(row.get("requires_server") or row.get("need_server")),
                "raw": row,
            }
        )
    normalized.sort(key=lambda x: (float(x.get("price") or 0), _norm(x.get("name"))))

    fresh = await get_catalog_snapshot(force=False)
    fresh_topups = dict(fresh.get("topups_by_game") or {})
    fresh_topups[str(game_id)] = normalized
    fresh["topups_by_game"] = fresh_topups
    _CACHE["data"] = fresh
    return list(normalized)
