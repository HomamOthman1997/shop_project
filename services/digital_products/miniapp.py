from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl
from uuid import uuid4

from aiohttp import web
from rapidfuzz import fuzz

from config import settings
from database.digital_products_config_repo import get_digital_products_markup_percent
from database.mongo import db
from services.digital_products.catalog_service import get_catalog_snapshot, get_game_topups

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "webapp" / "digital"
_PRIORITY_GIFTCARD_BRANDS = (
    "discord",
    "imo",
    "itunes",
    "jawaker",
    "nintendo",
    "playstation",
    "razer",
    "roblox",
    "steam",
    "xbox",
    "yalla ludo",
)
_GAME_TOPUP_HINTS = ("diamond", "diamonds", "gold", "gems", "gem", "coins", "coin", "cash", "crystals", "crystal", "jade", "uc", "opals", "voucher", "vouchers", "token", "tokens", "credits", "origeometry")
_GAME_PASS_HINTS = ("prime", "pass", "monthly", "weekly", "card", "subscription", "membership", "elite", "royale", "battle pass")
_GAME_SPECIAL_HINTS = ("pack", "bundle", "box", "chest", "deal", "lucky", "material", "emblem", "skin", "value", "first purchase", "rebate")
_GAME_GROUP_OVERRIDES: dict[str, dict[str, tuple[str, ...]]] = {
    "pubgm": {"passes": ("prime", "prime plus", "elite pass"), "specials": ("weekly", "mythic", "materials", "first purchase")},
    "mlbb": {"passes": ("weekly elite", "monthly elite", "weekly", "twilight")},
    "mlbb_br": {"passes": ("weekly elite", "monthly elite", "weekly")},
    "mlbb_exclusive": {"passes": ("weekly", "twilight")},
    "hok": {"passes": ("weekly card", "weekly card plus"), "specials": ("lucky bag", "value pack", "rebate")},
    "afkjourney": {"passes": ("monthly", "gazette"), "specials": ("growth bundle",)},
}


def _money(value: Any) -> float:
    try:
        return round(float(value), 2)
    except Exception:
        return 0.0


async def _markup_percent() -> float:
    try:
        return float(await get_digital_products_markup_percent(3.0))
    except Exception:
        return 3.0


def _with_markup(price: Any, markup_percent: float) -> float:
    base = _money(price)
    if markup_percent <= 0:
        return base
    return _money(base * (1 + (markup_percent / 100.0)))


def _norm(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _natural_key(text: str) -> list[Any]:
    parts = re.split(r"(\d+)", _norm(text))
    out: list[Any] = []
    for part in parts:
        if not part:
            continue
        out.append((0, int(part)) if part.isdigit() else (1, part))
    return out


def _find_game_name(snapshot: dict[str, Any], game_id: str) -> str:
    for game in list(snapshot.get("games") or []):
        if str(game.get("id") or "").strip() == str(game_id).strip():
            return str(game.get("name") or game_id or "-").strip()
    return str(game_id or "-").strip()


def _classify_game_item(game_id: str, item: dict[str, Any]) -> str:
    raw_name = str(item.get("clean_name") or item.get("name") or item.get("catalogue_name") or "")
    name = _norm(raw_name)
    override = _GAME_GROUP_OVERRIDES.get(str(game_id)) or {}
    for group_key, keywords in override.items():
        if keywords and any(keyword in name for keyword in keywords):
            return group_key
    if any(key in name for key in _GAME_PASS_HINTS):
        return "passes"
    if any(key in name for key in _GAME_SPECIAL_HINTS):
        return "specials"
    if _is_numeric_topup_name(raw_name) or any(key in name for key in _GAME_TOPUP_HINTS):
        return "topup"
    if str(game_id) in {"pubgm", "mlbb", "mla", "mlbb_br", "mlbb_exclusive", "hok"}:
        return "topup"
    return "specials"


def _is_numeric_topup_name(raw_name: str) -> bool:
    compact = str(raw_name or "").replace(",", "").replace("+", " ").strip()
    if not compact:
        return False
    return bool(re.fullmatch(r"[\d\s]+", compact) or re.match(r"^\d+(\s+[A-Za-z]+.*)?$", compact))


def _normalize_game_item_name(name: str) -> str:
    text = " ".join(str(name or "").strip().split())
    replacements = {
        "Activation Pass Bundle": "Bundle",
        "Activation Pass": "Pass",
        "Monthly Advanced Battle Pass": "Advanced Battle Pass",
        "Monthly Premium Battle Pass": "Premium Battle Pass",
        "Premium Spiritual Jade": "Jade",
        "Prime Plus": "Prime+",
        "First Purchase Pack": "First Purchase",
        "Weekly Deal Pack": "Weekly Deal",
        "Value Pack": "Value",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _display_game_item_name(item: dict[str, Any], group_key: str = "topup") -> str:
    name = _normalize_game_item_name(str(item.get("clean_name") or item.get("name") or "-").strip())
    if group_key == "topup":
        compact = name.replace(",", "").strip()
        if re.fullmatch(r"\d+", compact):
            return compact
        match = re.match(r"^(\d+)\s*([A-Za-z].*)$", name)
        if match:
            unit = match.group(2).strip()
            if len(unit) > 10:
                unit = unit.split()[0]
            return f"{match.group(1)} {unit}".strip()
    return name


def _gift_group_key(name: str) -> str:
    n = _norm(name)
    if any(brand in n for brand in _PRIORITY_GIFTCARD_BRANDS):
        return "popular"
    if any(k in n for k in ("playstation", "psn", "steam", "xbox", "nintendo", "razer", "roblox", "yalla ludo", "jawaker")):
        return "gaming"
    if any(k in n for k in ("itunes", "apple", "google", "discord", "imo")):
        return "apps"
    return "other"


def _gift_group_label(key: str) -> dict[str, str]:
    labels = {
        "popular": {"en": "Popular", "ar": "الأكثر طلبا"},
        "gaming": {"en": "Gaming", "ar": "الألعاب"},
        "apps": {"en": "Apps", "ar": "التطبيقات"},
        "other": {"en": "Other", "ar": "أخرى"},
    }
    return labels.get(key, labels["other"])


def _game_group_label(key: str) -> dict[str, str]:
    labels = {
        "topup": {"en": "Top Up", "ar": "شحن"},
        "passes": {"en": "Passes", "ar": "باسات"},
        "specials": {"en": "Specials", "ar": "عروض"},
    }
    return labels.get(key, labels["specials"])


def _game_root_group_key(name: str) -> str:
    n = _norm(name)
    if any(k in n for k in ("pubg", "mobile legends", "free fire", "honor of kings", "new state")):
        return "popular"
    if any(k in n for k in ("roblox", "fortnite", "valorant", "call of duty", "cod", "genshin")):
        return "global"
    return "all"


def _game_root_group_label(key: str) -> dict[str, str]:
    labels = {
        "popular": {"en": "Popular", "ar": "الأكثر طلبا"},
        "global": {"en": "Global Games", "ar": "ألعاب عالمية"},
        "all": {"en": "More Games", "ar": "ألعاب إضافية"},
    }
    return labels.get(key, labels["all"])


def _verify_init_data(init_data: str) -> dict[str, Any]:
    raw = str(init_data or "").strip()
    if not raw:
        raise web.HTTPUnauthorized(text="missing initData")
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = str(pairs.pop("hash", "") or "")
    if not received_hash:
        raise web.HTTPUnauthorized(text="missing hash")
    token = str(getattr(settings, "bot_digital_products_token", "") or "").strip()
    if not token:
        raise web.HTTPUnauthorized(text="bot token not configured")
    check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    calculated = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise web.HTTPUnauthorized(text="bad initData")
    user_raw = pairs.get("user")
    user = json.loads(user_raw) if user_raw else {}
    user_id = int(user.get("id") or 0)
    if user_id <= 0:
        raise web.HTTPUnauthorized(text="missing user")
    return {"user_id": user_id, "user": user}


def _try_verify_init_data(init_data: str) -> dict[str, Any] | None:
    try:
        return _verify_init_data(init_data)
    except web.HTTPUnauthorized:
        return None


async def _catalog_payload() -> dict[str, Any]:
    snapshot = await get_catalog_snapshot(force=False)
    markup = await _markup_percent()
    categories = []
    seen_category_names: set[str] = set()
    for cat in list(snapshot.get("gift_categories") or []):
        cat_id = str(cat.get("id") or "").strip()
        if not cat_id:
            continue
        name = str(cat.get("clean_name") or cat.get("name") or "-").strip()
        norm_name = _norm(name)
        if not norm_name or any(k in norm_name for k in ("test", "demo", "sample")) or norm_name in seen_category_names:
            continue
        seen_category_names.add(norm_name)
        categories.append(
            {
                "id": cat_id,
                "name": name,
                "count": int(cat.get("count") or 0),
                "group_key": _gift_group_key(name),
            }
        )
    gift_group_order = {"popular": 0, "gaming": 1, "apps": 2, "other": 3}
    categories.sort(key=lambda row: (gift_group_order.get(str(row.get("group_key")), 9), _natural_key(str(row.get("name") or ""))))
    games = [
        {
            "id": str(game.get("id") or ""),
            "name": str(game.get("name") or "-"),
            "group_key": _game_root_group_key(str(game.get("name") or "-")),
        }
        for game in list(snapshot.get("games") or [])
        if str(game.get("id") or "").strip()
    ]
    game_group_order = {"popular": 0, "global": 1, "all": 2}
    games.sort(key=lambda row: (game_group_order.get(str(row.get("group_key")), 9), _natural_key(str(row.get("name") or ""))))
    gift_groups = [
        {"key": key, "label": _gift_group_label(key)}
        for key in ("popular", "gaming", "apps", "other")
        if any(str(row.get("group_key")) == key for row in categories)
    ]
    game_groups = [
        {"key": key, "label": _game_root_group_label(key)}
        for key in ("popular", "global", "all")
        if any(str(row.get("group_key")) == key for row in games)
    ]
    return {
        "enabled": bool(snapshot.get("enabled")),
        "markup_percent": markup,
        "gift_categories": categories,
        "gift_groups": gift_groups,
        "games": games[:80],
        "game_groups": game_groups,
    }


async def _gift_products(category_id: str, query: str = "") -> list[dict[str, Any]]:
    snapshot = await get_catalog_snapshot(force=False)
    markup = await _markup_percent()
    rows = list((snapshot.get("products_by_category") or {}).get(str(category_id), []) or [])
    q = _norm(query)
    out: list[dict[str, Any]] = []
    for item in rows:
        name = str(item.get("clean_name") or item.get("name") or "-")
        if q and fuzz.partial_ratio(q, name.lower()) < 45:
            continue
        price = _with_markup(item.get("price"), markup)
        out.append(
            {
                "kind": "gift",
                "id": str(item.get("id") or ""),
                "category_id": str(category_id),
                "name": name,
                "price_usd": price,
                "stock": int(item.get("stock") or 0),
                "stock_label": "In stock" if int(item.get("stock") or 0) > 0 else "Out of stock",
            }
        )
    out.sort(key=lambda row: _natural_key(str(row.get("name") or "")))
    return out[:100]


async def _game_items(game_id: str, query: str = "") -> dict[str, Any]:
    snapshot = await get_catalog_snapshot(force=False)
    markup = await _markup_percent()
    rows = await get_game_topups(str(game_id))
    q = _norm(query)
    items: list[dict[str, Any]] = []
    for item in rows:
        group = _classify_game_item(game_id, item)
        name = _display_game_item_name(item, group)
        if q and fuzz.partial_ratio(q, name.lower()) < 45:
            continue
        items.append(
            {
                "kind": "game",
                "id": str(item.get("id") or ""),
                "game_id": str(game_id),
                "group_key": group,
                "name": name,
                "price_usd": _with_markup(item.get("price"), markup),
                "requires_server": bool(item.get("requires_server")),
            }
        )
    group_order = {"topup": 0, "passes": 1, "specials": 2}
    items.sort(key=lambda row: (group_order.get(str(row.get("group_key") or ""), 9), _money(row.get("price_usd")), _natural_key(str(row.get("name") or ""))))
    groups = [
        {"key": key, "label": _game_group_label(key)}
        for key in ("topup", "passes", "specials")
        if any(str(row.get("group_key")) == key for row in items)
    ]
    return {"game_id": str(game_id), "game_name": _find_game_name(snapshot, str(game_id)), "groups": groups, "items": items[:120]}


async def _create_selection(user_id: int | None, payload: dict[str, Any]) -> str:
    token = uuid4().hex
    now = datetime.now(UTC)
    await db.digital_product_miniapp_selections.insert_one(
        {
            "_id": token,
            "user_id": int(user_id) if user_id else None,
            "payload": payload,
            "status": "new",
            "created_at": now,
            "expires_at": now + timedelta(minutes=15),
        }
    )
    return token


async def consume_selection(token: str, user_id: int) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    doc = await db.digital_product_miniapp_selections.find_one_and_update(
        {
            "_id": str(token or "").strip(),
            "$or": [{"user_id": int(user_id)}, {"user_id": None}],
            "status": "new",
            "expires_at": {"$gt": now},
        },
        {"$set": {"status": "used", "used_at": now}},
    )
    if not doc:
        return None
    payload = doc.get("payload")
    return payload if isinstance(payload, dict) else None


async def bootstrap_miniapp_indexes() -> None:
    await db.digital_product_miniapp_selections.create_index("expires_at", expireAfterSeconds=0, background=True)
    await db.digital_product_miniapp_selections.create_index([("user_id", 1), ("status", 1), ("created_at", -1)], background=True)


async def index(_request: web.Request) -> web.Response:
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    return web.Response(text=html, content_type="text/html")


async def static_file(request: web.Request) -> web.Response:
    name = str(request.match_info.get("name") or "")
    path = (_STATIC / name).resolve()
    if _STATIC.resolve() not in path.parents:
        raise web.HTTPNotFound()
    if not path.exists() or not path.is_file():
        raise web.HTTPNotFound()
    content_type = "text/css" if path.suffix == ".css" else "application/javascript"
    return web.Response(body=path.read_bytes(), content_type=content_type)


async def catalog(_request: web.Request) -> web.Response:
    return web.json_response(await _catalog_payload())


async def gift_products(request: web.Request) -> web.Response:
    return web.json_response({"items": await _gift_products(request.match_info["category_id"], request.query.get("q", ""))})


async def game_items(request: web.Request) -> web.Response:
    return web.json_response(await _game_items(request.match_info["game_id"], request.query.get("q", "")))


async def create_selection(request: web.Request) -> web.Response:
    auth = _try_verify_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    body = await request.json()
    kind = str(body.get("kind") or "").strip().lower()
    if kind == "gift":
        category_id = str(body.get("category_id") or "").strip()
        product_id = str(body.get("product_id") or "").strip()
        if not category_id or not product_id:
            raise web.HTTPBadRequest(text="missing gift selection")
        payload = {"kind": "gift", "category_id": category_id, "product_id": product_id}
    elif kind == "game":
        game_id = str(body.get("game_id") or "").strip()
        item_id = str(body.get("item_id") or "").strip()
        group_key = str(body.get("group_key") or "topup").strip() or "topup"
        if not game_id or not item_id:
            raise web.HTTPBadRequest(text="missing game selection")
        payload = {"kind": "game", "game_id": game_id, "item_id": item_id, "group_key": group_key}
    else:
        raise web.HTTPBadRequest(text="invalid selection")
    token = await _create_selection(int(auth["user_id"]) if auth else None, payload)
    return web.json_response({"token": token})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/mini/digital", index)
    app.router.add_get("/mini/digital/static/{name}", static_file)
    app.router.add_get("/mini/digital/api/catalog", catalog)
    app.router.add_get("/mini/digital/api/gifts/{category_id}", gift_products)
    app.router.add_get("/mini/digital/api/games/{game_id}", game_items)
    app.router.add_post("/mini/digital/api/selection", create_selection)
    return app


async def start_miniapp_server() -> tuple[web.AppRunner, web.TCPSite] | None:
    if not bool(getattr(settings, "digital_products_miniapp_enabled", False)):
        return None
    await bootstrap_miniapp_indexes()
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        str(getattr(settings, "digital_products_miniapp_host", "0.0.0.0") or "0.0.0.0"),
        int(getattr(settings, "digital_products_miniapp_port", 8080) or 8080),
    )
    await site.start()
    return runner, site
