from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from config import settings
from utils.translations import t

from .g2bulk_client import G2BulkClient
from .za3em_client import Za3emClient

_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_ZA3EM_CACHE: dict[str, Any] = {"ts": 0.0, "rows": []}
_CACHE_LOCK = asyncio.Lock()
_ZA3EM_LOCK = asyncio.Lock()
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


def _first_number(text: str) -> int | None:
    match = re.search(r"(\d+)", str(text or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _service_key(text: str) -> str | None:
    n = _norm(text)
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("pubg", ("pubg", "pubgm", "uc", "robot", "\u0628\u0628\u062c\u064a", "\u0634\u062f\u0629", "\u0634\u062f\u0627\u062a", "\u0631\u0648\u0628\u0648\u062a")),
        ("mlbb", ("mobile legends", "mobile legend", "mlbb", "diamonds", "\u0645\u0648\u0628\u0627\u064a\u0644 \u0644\u064a\u062c\u0646\u062f")),
        ("free_fire", ("free fire", "\u0641\u0631\u064a \u0641\u0627\u064a\u0631")),
        ("hok", ("honor of kings", "honor of king", "hok")),
        ("steam", ("steam", "\u0633\u062a\u064a\u0645")),
        ("itunes", ("itunes", "apple", "\u0627\u064a\u062a\u0648\u0646\u0632")),
        ("playstation", ("playstation", "psn", "\u0628\u0644\u0627\u064a \u0633\u062a\u064a\u0634\u0646")),
        ("xbox", ("xbox",)),
        ("nintendo", ("nintendo",)),
        ("roblox", ("roblox", "\u0631\u0648\u0628\u0644\u0648\u0643\u0633")),
        ("razer", ("razer", "\u0631\u064a\u0632\u0631")),
        ("discord", ("discord", "\u062f\u064a\u0633\u0643\u0648\u0631\u062f")),
        ("imo", ("imo",)),
        ("jawaker", ("jawaker", "\u062c\u0648\u0627\u0643\u0631")),
        ("yalla_ludo", ("yalla ludo", "\u064a\u0644\u0627 \u0644\u0648\u062f\u0648")),
    ]
    for key, keys in rules:
        if any(token in n for token in keys):
            return key
    return None

def _currency_variant(text: str) -> str:
    n = _norm(text)
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("usd", (" usd", "us$", "$", "دولار", "usa", "american", "امريكي")),
        ("sar", ("sar", "ksa", "سعود", "ريال")),
        ("eur", ("eur", "€", "euro", "الماني", "germany", "german")),
        ("myr", ("myr",)),
        ("hkd", ("hkd",)),
        ("try", ("try", "تركي", "turkish", "turkey")),
        ("global", ("global", "عالمي")),
    ]
    for key, tokens in rules:
        if any(token in n for token in tokens):
            return key
    return "generic"


def _game_variant(text: str) -> str:
    n = _norm(text)
    compact = re.sub(r"[\s,]+", "", n)
    tags: list[str] = []
    if any(k in n for k in ("month", "months", "شهر", "شهور")):
        tags.append("month")
    if any(k in n for k in ("weekly", "week", "اسبوع")):
        tags.append("weekly")
    if any(k in n for k in ("prime", "برايم")):
        tags.append("prime")
    if any(k in n for k in ("plus", "بلس", "+")):
        tags.append("plus")
    if any(k in n for k in ("normal", "ordinary", "عادي")):
        tags.append("normal")
    if any(k in n for k in ("pass", "elite", "باس")):
        tags.append("pass")
    if any(k in n for k in ("pack", "bundle", "حزمة")):
        tags.append("pack")
    if any(k in n for k in ("discount", "خصم")):
        tags.append("discount")
    if any(k in n for k in ("uc", "شدة", "شدات", "diamond", "diamonds", "جواهر")) or compact.isdigit():
        tags.append("topup")
    return "|".join(sorted(set(tags))) if tags else "generic"


def _variant_key(service_key: str | None, text: str) -> str:
    if service_key in {"pubg", "mlbb", "free_fire", "hok"}:
        return _game_variant(text)
    return _currency_variant(text)


def _build_offer(provider: str, ref_id: str, price: float, available: bool, *, source: str = "", **extra: Any) -> dict[str, Any]:
    payload = {
        "provider": str(provider),
        "ref_id": str(ref_id),
        "price": round(float(price or 0.0), 6),
        "available": bool(available),
        "source": str(source or ""),
    }
    for key, value in extra.items():
        payload[str(key)] = value
    return payload


def _choose_best_offer(offers: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [row for row in offers if bool(row.get("available")) and float(row.get("price") or 0.0) > 0]
    if not valid:
        return None
    valid.sort(key=lambda row: float(row.get("price") or 0.0))
    return dict(valid[0])


def _za3em_offer_meta(row: dict[str, Any]) -> dict[str, Any]:
    params = [str(item).strip() for item in list(row.get("params") or []) if str(item).strip()]
    qty_values = row.get("qty_values") if isinstance(row.get("qty_values"), dict) else {}
    qty_min = _to_int((qty_values or {}).get("min") or 0)
    qty_max = _to_int((qty_values or {}).get("max") or 0)
    if qty_min <= 0:
        qty_min = 1
    if qty_max <= 0:
        qty_max = max(1, qty_min)
    product_type = str(row.get("product_type") or "").strip().lower()
    return {
        "za3em_params": params,
        "za3em_product_type": product_type,
        "za3em_qty_min": int(qty_min),
        "za3em_qty_max": int(qty_max),
        "za3em_requires_input": bool(params) or product_type == "amount" or qty_max > 1,
    }


async def _get_za3em_products(force: bool = False) -> list[dict[str, Any]]:
    ttl = max(15, int(getattr(settings, "za3em_catalog_cache_ttl_sec", 120) or 120))
    now = time.time()
    if not force and (now - float(_ZA3EM_CACHE.get("ts") or 0.0)) < ttl:
        return list(_ZA3EM_CACHE.get("rows") or [])
    async with _ZA3EM_LOCK:
        now = time.time()
        if not force and (now - float(_ZA3EM_CACHE.get("ts") or 0.0)) < ttl:
            return list(_ZA3EM_CACHE.get("rows") or [])
        client = Za3emClient()
        rows = await client.get_products() if client.configured() else []
        _ZA3EM_CACHE["ts"] = now
        _ZA3EM_CACHE["rows"] = list(rows or [])
        return list(rows or [])


def _build_za3em_index(rows: list[dict[str, Any]]) -> dict[tuple[str, int, str], list[dict[str, Any]]]:
    index: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for row in rows:
        name = str(row.get("name") or "").strip()
        category_name = str(row.get("category_name") or "").strip()
        key = _service_key(f"{name} {category_name}")
        if not key:
            continue
        amount = _first_number(name) or _first_number(category_name)
        if not amount:
            continue
        variant = _variant_key(key, f"{name} {category_name}")
        offer = _build_offer(
            "za3em",
            str(row.get("id") or ""),
            _to_float(row.get("price")),
            bool(row.get("available")),
            source=str(row.get("product_type") or "product"),
            **_za3em_offer_meta(row),
        )
        index.setdefault((key, int(amount), variant), []).append(offer)
    for k in list(index.keys()):
        index[k].sort(key=lambda item: float(item.get("price") or 0.0))
    return index


def _find_matching_za3em_offers(
    za_index: dict[tuple[str, int, str], list[dict[str, Any]]],
    *,
    service_key: str | None,
    amount: int | None,
    variant: str,
) -> list[dict[str, Any]]:
    if not service_key or not amount:
        return []
    exact = list(za_index.get((service_key, int(amount), variant)) or [])
    if exact:
        return exact
    if variant != "generic":
        fallback = list(za_index.get((service_key, int(amount), "generic")) or [])
        if fallback:
            return fallback
    return []


def _section_service_key(text: str | None) -> str:
    n = _norm(text)
    if not n:
        return "store_cards"
    if any(
        token in n
        for token in (
            "otp",
            "number",
            "numbers",
            "sms",
            "virtual number",
            "\u0627\u0631\u0642\u0627\u0645",
            "\u0631\u0642\u0645",
        )
    ):
        return "numbers_services"
    if any(
        token in n
        for token in (
            "netflix",
            "spotify",
            "shahid",
            "youtube",
            "chatgpt",
            "subscription",
            "subscriptions",
            "premium",
            "\u0627\u0634\u062a\u0631\u0627\u0643",
            "\u0627\u0634\u062a\u0631\u0627\u0643\u0627\u062a",
        )
    ):
        return "paid_subscriptions"
    if any(
        token in n
        for token in (
            "sim",
            "topup",
            "top up",
            "telecom",
            "data",
            "mtn",
            "syriatel",
            "sawa",
            "\u0631\u0635\u064a\u062f",
            "\u0628\u064a\u0627\u0646\u0627\u062a",
            "\u0627\u062a\u0635\u0627\u0644\u0627\u062a",
        )
    ):
        return "communications_data"
    if any(
        token in n
        for token in (
            "discord",
            "imo",
            "chat",
            "telegram",
            "whatsapp",
            "messenger",
            "viber",
            "line",
            "wechat",
            "\u062f\u0631\u062f\u0634\u0629",
            "\u062a\u0644\u063a\u0631\u0627\u0645",
            "\u0648\u0627\u062a\u0633\u0627\u0628",
            "\u062f\u064a\u0633\u0643\u0648\u0631\u062f",
            "\u0627\u064a\u0645\u0648",
        )
    ):
        return "chat_apps"
    if any(
        token in n
        for token in (
            "pubg",
            "free fire",
            "mobile legends",
            "mlbb",
            "honor of kings",
            "game",
            "games",
            "playstation",
            "xbox",
            "nintendo",
            "razer",
            "roblox",
            "jawaker",
            "yalla ludo",
            "\u0627\u0644\u0639\u0627\u0628",
            "\u0628\u0628\u062c\u064a",
            "\u0641\u0631\u064a \u0641\u0627\u064a\u0631",
            "\u0645\u0648\u0628\u0627\u064a\u0644 \u0644\u064a\u062c\u0646\u062f",
            "\u062c\u0648\u0627\u0643\u0631",
            "\u064a\u0644\u0627 \u0644\u0648\u062f\u0648",
            "\u0628\u0644\u0627\u064a \u0633\u062a\u064a\u0634\u0646",
            "\u0631\u0648\u0628\u0644\u0648\u0643\u0633",
        )
    ):
        return "games"
    return "store_cards"


def _is_za3em_supported_product(row: dict[str, Any]) -> bool:
    product_type = _norm(str(row.get("product_type") or ""))
    if product_type not in {"package", "amount"}:
        return False
    return bool(str(row.get("id") or "").strip())


def _za3em_category_id(row: dict[str, Any]) -> str:
    parent_id = str(row.get("parent_id") or "").strip()
    if parent_id:
        return f"za3emc_{parent_id}"
    return f"za3emc_{str(row.get('id') or '').strip()}"


def _normalize_offers(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    uniq: dict[tuple[str, str], dict[str, Any]] = {}
    for item in offers:
        provider = str(item.get("provider") or "").strip().lower()
        ref_id = str(item.get("ref_id") or "").strip()
        if not provider or not ref_id:
            continue
        key = (provider, ref_id)
        existing = uniq.get(key)
        if not existing:
            uniq[key] = dict(item)
            continue
        old_price = _to_float(existing.get("price"))
        new_price = _to_float(item.get("price"))
        if new_price > 0 and (old_price <= 0 or new_price < old_price):
            uniq[key] = dict(item)
        elif bool(item.get("available")) and not bool(existing.get("available")):
            uniq[key] = dict(item)
    rows = list(uniq.values())
    rows.sort(key=lambda item: (0 if bool(item.get("available")) else 1, _to_float(item.get("price")) if _to_float(item.get("price")) > 0 else 9999999))
    return rows


def _is_pubg_topup_row(name: str) -> bool:
    n = _norm(name)
    if not n:
        return False
    if _first_number(n) is None:
        return False
    # Keep top-up values and skip pass/special package rows.
    blockers = (
        "pass",
        "prime",
        "weekly",
        "month",
        "elite",
        "mythic",
        "pack",
        "bundle",
        "materials",
        "first purchase",
    )
    return not any(token in n for token in blockers)


def _dedupe_pubg_topups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_amount: dict[int, dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name") or "")
        if not _is_pubg_topup_row(name):
            passthrough.append(row)
            continue
        amount = _first_number(name)
        if amount is None:
            passthrough.append(row)
            continue
        current = by_amount.get(int(amount))
        if not current:
            by_amount[int(amount)] = dict(row)
            continue
        merged_offers = _normalize_offers(
            list(current.get("provider_offers") or []) + list(row.get("provider_offers") or [])
        )
        best_offer = _choose_best_offer(merged_offers)
        keep = dict(current)
        # Keep the cheaper base label (usually discounted) for cleaner UI.
        if _to_float(row.get("price")) > 0 and (
            _to_float(current.get("price")) <= 0 or _to_float(row.get("price")) < _to_float(current.get("price"))
        ):
            keep = dict(row)
        keep["provider_offers"] = merged_offers
        if best_offer:
            keep["price"] = float(best_offer.get("price") or keep.get("price") or 0.0)
            keep["best_provider"] = str(best_offer.get("provider") or keep.get("best_provider") or "")
            keep["best_provider_ref_id"] = str(best_offer.get("ref_id") or keep.get("best_provider_ref_id") or "")
        by_amount[int(amount)] = keep
    merged = list(by_amount.values()) + passthrough
    merged.sort(key=lambda x: (float(x.get("price") or 0), _norm(x.get("name"))))
    return merged


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
        if client.configured():
            raw_categories, raw_products, raw_games, za3em_rows = await asyncio.gather(
                client.get_categories(),
                client.get_products(),
                client.get_games(),
                _get_za3em_products(force=force),
            )
        else:
            raw_categories, raw_products, raw_games, za3em_rows = [], [], [], await _get_za3em_products(force=force)

    za_index = _build_za3em_index(za3em_rows)
    cat_name_by_id = {str(_best_id(row, "id", "category_id", "ID")): str(row.get("name") or row.get("title") or "") for row in raw_categories}

    products_by_category: dict[str, list[dict[str, Any]]] = {}
    matched_za3em_ref_ids: set[str] = set()
    for row in raw_products:
        product_id = _best_id(row, "id", "product_id", "ID")
        if not product_id:
            continue
        cat_id = _best_id(row, "category_id", "cat_id", "categoryId")
        if not cat_id:
            continue
        name = str(row.get("name") or row.get("title") or row.get("product_name") or t("en", "catalog_fallback_product").format(product_id=product_id))
        clean_name = _clean_gift_name(name)
        service_key = _service_key(f"{clean_name} {cat_name_by_id.get(cat_id, '')}")
        amount = _first_number(clean_name) or _first_number(cat_name_by_id.get(cat_id, ""))
        variant = _variant_key(service_key, f"{clean_name} {cat_name_by_id.get(cat_id, '')}") if service_key else "generic"
        g2_offer = _build_offer(
            "g2bulk",
            product_id,
            _to_float(row.get("price") or row.get("unit_price") or row.get("buyer_price") or row.get("sell_price")),
            _to_int(row.get("stock") or row.get("quantity") or row.get("available")) > 0,
            source="gift",
        )
        offers = [g2_offer]
        offers.extend(_find_matching_za3em_offers(za_index, service_key=service_key, amount=amount, variant=variant))
        for offer in offers:
            if str(offer.get("provider") or "").strip().lower() == "za3em":
                ref_id = str(offer.get("ref_id") or "").strip()
                if ref_id:
                    matched_za3em_ref_ids.add(ref_id)
        best_offer = _choose_best_offer(offers)
        products_by_category.setdefault(cat_id, []).append(
            {
                "id": product_id,
                "name": name,
                "clean_name": clean_name,
                "price": float((best_offer or g2_offer).get("price") or 0.0),
                "stock": _to_int(row.get("stock") or row.get("quantity") or row.get("available")),
                "provider_offers": offers,
                "best_provider": str((best_offer or g2_offer).get("provider") or "g2bulk"),
                "best_provider_ref_id": str((best_offer or g2_offer).get("ref_id") or product_id),
                "raw": row,
            }
        )

    # Add standalone Za3em products not matched to G2Bulk by amount/variant.
    # Keep them visible as direct buy options.
    for row in za3em_rows:
        if not _is_za3em_supported_product(row):
            continue
        ref_id = str(row.get("id") or "").strip()
        if not ref_id or ref_id in matched_za3em_ref_ids:
            continue
        cat_id = _za3em_category_id(row)
        name = str(row.get("name") or t("en", "catalog_fallback_product").format(product_id=ref_id)).strip()
        clean_name = _clean_gift_name(name)
        available = bool(row.get("available"))
        meta = _za3em_offer_meta(row)
        za_offer = _build_offer(
            "za3em",
            ref_id,
            _to_float(row.get("price")),
            available,
            source=str(row.get("product_type") or "product"),
            **meta,
        )
        products_by_category.setdefault(cat_id, []).append(
            {
                "id": f"za3emp_{ref_id}",
                "name": name,
                "clean_name": clean_name,
                "price": float(za_offer.get("price") or 0.0),
                "stock": 1 if available else 0,
                "provider_offers": [za_offer],
                "best_provider": "za3em",
                "best_provider_ref_id": ref_id,
                "za3em_product_type": str(meta.get("za3em_product_type") or ""),
                "za3em_params": list(meta.get("za3em_params") or []),
                "za3em_qty_min": int(meta.get("za3em_qty_min") or 1),
                "za3em_qty_max": int(meta.get("za3em_qty_max") or 1),
                "za3em_requires_input": bool(meta.get("za3em_requires_input")),
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
        gift_categories.append(
            {
                "id": cat_id,
                "name": name,
                "clean_name": _clean_gift_name(name),
                "count": count,
                "service_key": _section_service_key(name),
                "raw": row,
            }
        )
    # Add Za3em-only synthetic categories built from parent/category names.
    for row in za3em_rows:
        if not _is_za3em_supported_product(row):
            continue
        cat_id = _za3em_category_id(row)
        if not (products_by_category.get(cat_id) or []):
            continue
        category_name = str(row.get("category_name") or "").strip()
        parent_id = str(row.get("parent_id") or "").strip()
        name = category_name or (t("en", "catalog_fallback_category").format(cat_id=parent_id or cat_id))
        if any(str(cat.get("id") or "") == cat_id for cat in gift_categories):
            continue
        gift_categories.append(
            {
                "id": cat_id,
                "name": name,
                "clean_name": _clean_gift_name(name),
                "count": len(products_by_category.get(cat_id) or []),
                "service_key": _section_service_key(f"{name} {str(row.get('name') or '')}"),
                "raw": row,
            }
        )
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
        "enabled": bool(raw_categories or raw_games or gift_categories),
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
    game_name = ""
    for game in list(snapshot.get("games") or []):
        if str(game.get("id") or "").strip() == str(game_id).strip():
            game_name = str(game.get("name") or "").strip()
            break
    service_key = _service_key(f"{game_id} {game_name}")
    if str(game_id) in topup_map:
        cached_rows = list(topup_map.get(str(game_id)) or [])
        if service_key == "pubg":
            deduped = _dedupe_pubg_topups(cached_rows)
            if len(deduped) != len(cached_rows):
                topup_map[str(game_id)] = deduped
                snapshot["topups_by_game"] = topup_map
                _CACHE["data"] = snapshot
            return deduped
        return cached_rows
    za_index = _build_za3em_index(await _get_za3em_products(force=False))

    client = G2BulkClient()
    rows = await client.get_game_catalogue(game_id)
    normalized: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        product_id = _best_id(row, "id", "product_id", "ID")
        name = str(row.get("name") or row.get("title") or row.get("product_name") or t("en", "catalog_fallback_pack").format(item_id=product_id or game_id))
        if not product_id:
            product_id = f"{game_id}_{idx+1}"
        amount = _first_number(name)
        variant = _variant_key(service_key, name) if service_key else "generic"
        g2_offer = _build_offer(
            "g2bulk",
            product_id,
            _to_float(row.get("price") or row.get("amount") or row.get("unit_price") or row.get("buyer_price") or row.get("sell_price")),
            True,
            source="game",
        )
        offers = [g2_offer]
        offers.extend(_find_matching_za3em_offers(za_index, service_key=service_key, amount=amount, variant=variant))
        best_offer = _choose_best_offer(offers)
        normalized.append(
            {
                "id": product_id,
                "name": name,
                "catalogue_name": str(row.get("name") or row.get("title") or "").strip() or name,
                "price": float((best_offer or g2_offer).get("price") or 0.0),
                "requires_server": bool(row.get("requires_server") or row.get("need_server")),
                "provider_offers": offers,
                "best_provider": str((best_offer or g2_offer).get("provider") or "g2bulk"),
                "best_provider_ref_id": str((best_offer or g2_offer).get("ref_id") or product_id),
                "raw": row,
            }
        )
    normalized.sort(key=lambda x: (float(x.get("price") or 0), _norm(x.get("name"))))
    if service_key == "pubg":
        normalized = _dedupe_pubg_topups(normalized)

    fresh = await get_catalog_snapshot(force=False)
    fresh_topups = dict(fresh.get("topups_by_game") or {})
    fresh_topups[str(game_id)] = normalized
    fresh["topups_by_game"] = fresh_topups
    _CACHE["data"] = fresh
    return list(normalized)


def extract_provider_offers(row: dict[str, Any], *, fallback_provider: str, fallback_ref_id: str, fallback_price: float) -> list[dict[str, Any]]:
    offers = [item for item in list(row.get("provider_offers") or []) if isinstance(item, dict)]
    if not offers:
        offers = [
            _build_offer(
                fallback_provider,
                fallback_ref_id,
                fallback_price,
                True,
                source="fallback",
            )
        ]
    uniq: dict[tuple[str, str], dict[str, Any]] = {}
    for item in offers:
        provider = str(item.get("provider") or "").strip().lower()
        ref_id = str(item.get("ref_id") or "").strip()
        if not provider or not ref_id:
            continue
        key = (provider, ref_id)
        existing = uniq.get(key)
        if not existing:
            uniq[key] = dict(item)
            continue
        old_price = _to_float(existing.get("price"))
        new_price = _to_float(item.get("price"))
        if new_price > 0 and (old_price <= 0 or new_price < old_price):
            uniq[key] = dict(item)
        elif bool(item.get("available")) and not bool(existing.get("available")):
            uniq[key] = dict(item)
    rows = list(uniq.values())
    rows.sort(key=lambda item: (0 if bool(item.get("available")) else 1, _to_float(item.get("price")) if _to_float(item.get("price")) > 0 else 9999999))
    return rows
