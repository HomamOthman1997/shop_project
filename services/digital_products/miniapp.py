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


def _is_pubg_game(game_id: str | None, game_name: str | None = None) -> bool:
    text = f"{_norm(game_id)} {_norm(game_name)}".strip()
    if not text:
        return False
    return any(key in text for key in ("pubg", "pubgm", "new state", "newstate"))


def _pubg_undercut_percent() -> float:
    try:
        value = float(getattr(settings, "digital_products_pubg_undercut_percent", 1.0))
    except Exception:
        value = 1.0
    return value if value > 0 else 1.0


def _resolve_game_sale_price(price: Any, markup_percent: float, *, game_id: str | None, game_name: str | None = None) -> float:
    base = _money(price)
    marked = _with_markup(base, markup_percent)
    if not _is_pubg_game(game_id, game_name):
        return marked
    cap = _money(base * (1.0 - (_pubg_undercut_percent() / 100.0)))
    if cap >= base and base > 0.01:
        cap = _money(base - 0.01)
    if cap <= 0:
        cap = base
    return min(marked, cap)


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


def _gift_service_key_legacy(name: str) -> str:
    n = _norm(name)
    if any(k in n for k in ("discord", "imo", "chat", "social", "واتس", "whatsapp", "telegram", "تلجرام")):
        return "chat_apps"
    if any(k in n for k in ("playstation", "psn", "xbox", "nintendo", "razer", "roblox", "jawaker", "yalla ludo")):
        return "games"
    if any(k in n for k in ("netflix", "spotify", "shahid", "canva", "chatgpt", "subscription", "premium", "pro", "اشتراك", "اشتراكات")):
        return "paid_subscriptions"
    return "store_cards"


def _gift_service_key(name: str) -> str:
    n = _norm(name)
    if any(
        k in n
        for k in (
            "discord",
            "imo",
            "chat",
            "social",
            "whatsapp",
            "telegram",
            "messenger",
            "viber",
            "line",
            "wechat",
            "tada",
            "bigo",
            "coco",
            "azal",
            "live",
        )
    ):
        return "chat_apps"
    if any(
        k in n
        for k in (
            "playstation",
            "psn",
            "xbox",
            "nintendo",
            "razer",
            "roblox",
            "jawaker",
            "yalla ludo",
            "pubg",
            "free fire",
            "mobile legends",
            "mlbb",
            "honor of kings",
            "clash of clans",
            "coc",
            "brawl stars",
            "brawl star",
            "blood strike",
            "delta force",
            "call of duty",
            "cod",
            "valorant",
            "fortnite",
            "genshin",
            "war robots",
            "8 ball pool",
            "game",
            "games",
        )
    ):
        return "games"
    if any(
        k in n
        for k in (
            "netflix",
            "spotify",
            "shahid",
            "canva",
            "chatgpt",
            "subscription",
            "premium",
            "pro",
        )
    ):
        return "paid_subscriptions"
    return "store_cards"


def _family_rules_for_service(service_key: str) -> list[tuple[str, str, tuple[str, ...]]]:
    if service_key == "games":
        return [
            ("pubg", "PUBG", ("pubg", "pubgm", "uc", "new state", "شدات", "شدة")),
            ("mobile_legends", "Mobile Legends", ("mobile legends", "mlbb", "موبايل ليجند")),
            ("free_fire", "Free Fire", ("free fire", "garena free fire", "فري فاير")),
            ("honor_of_kings", "Honor of Kings", ("honor of kings", "hok")),
            ("yalla_ludo", "Yalla Ludo", ("yalla ludo", "يلا لودو")),
            ("jawaker", "Jawaker", ("jawaker", "جواكر")),
            ("clash_of_clans", "Clash of Clans", ("clash of clans", "coc")),
            ("brawl_stars", "Brawl Stars", ("brawl stars", "brawl star")),
            ("cod", "Call of Duty", ("call of duty", "cod")),
            ("fortnite", "Fortnite", ("fortnite",)),
            ("valorant", "Valorant", ("valorant",)),
            ("genshin", "Genshin", ("genshin",)),
            ("roblox", "Roblox", ("roblox", "روبلوكس")),
            ("playstation", "PlayStation", ("playstation", "psn", "بلاي ستيشن")),
            ("xbox", "Xbox", ("xbox",)),
            ("nintendo", "Nintendo", ("nintendo",)),
        ]
    if service_key == "chat_apps":
        return [
            ("discord", "Discord", ("discord", "ديسكورد")),
            ("imo", "IMO", ("imo", "ايمو")),
            ("telegram", "Telegram", ("telegram", "تلجرام")),
            ("whatsapp", "WhatsApp", ("whatsapp", "واتساب")),
            ("messenger", "Messenger", ("messenger", "facebook")),
        ]
    if service_key == "paid_subscriptions":
        return [
            ("netflix", "Netflix", ("netflix",)),
            ("spotify", "Spotify", ("spotify",)),
            ("shahid", "Shahid", ("shahid",)),
            ("chatgpt", "ChatGPT", ("chatgpt",)),
            ("canva", "Canva", ("canva",)),
            ("subscriptions", "Subscriptions", ("subscription", "premium", "اشتراك")),
        ]
    if service_key == "store_cards":
        return [
            ("steam", "Steam", ("steam", "ستيم")),
            ("google_play", "Google Play", ("google play", "google", "جوجل")),
            ("apple_itunes", "Apple / iTunes", ("itunes", "apple", "ايتونز", "ابل")),
            ("playstation", "PlayStation", ("playstation", "psn", "بلاي ستيشن")),
            ("xbox", "Xbox", ("xbox",)),
            ("nintendo", "Nintendo", ("nintendo",)),
            ("razer", "Razer Gold", ("razer",)),
            ("roblox", "Roblox", ("roblox", "روبلوكس")),
            ("gift_cards", "Gift Cards", ("gift", "voucher", "card", "بطاقة", "قسيمة")),
        ]
    if service_key == "communications_data":
        return [
            ("mtn", "MTN", ("mtn",)),
            ("syriatel", "Syriatel", ("syriatel",)),
            ("sawa", "SAWA", ("sawa",)),
            ("telecom", "Telecom & Data", ("data", "topup", "telecom", "اتصالات", "بيانات")),
        ]
    if service_key == "numbers_services":
        return [
            ("sms_otp", "SMS & OTP", ("sms", "otp", "number", "numbers", "رقم", "ارقام")),
        ]
    return []


def _chat_family_from_product_name(name: str) -> tuple[str, str]:
    n = _norm(name)
    rules: list[tuple[str, str, tuple[str, ...]]] = [
        ("discord", "Discord", ("discord",)),
        ("imo", "IMO", ("imo",)),
        ("telegram", "Telegram", ("telegram",)),
        ("whatsapp", "WhatsApp", ("whatsapp",)),
        ("messenger", "Messenger", ("messenger", "facebook")),
        ("viber", "Viber", ("viber",)),
        ("line", "LINE", ("line",)),
        ("wechat", "WeChat", ("wechat",)),
        ("bigo_live", "Bigo Live", ("bigo",)),
        ("coco_live", "Coco Live", ("coco",)),
        ("azal_live", "Azal Live", ("azal",)),
        ("tada_chat", "Tada Chat", ("tada",)),
        ("fancy_life", "Fancy Life", ("fancy life",)),
    ]
    for key, label, tokens in rules:
        if any(tok in n for tok in tokens):
            return key, label
    cleaned = re.sub(r"\s+", " ", str(name or "").strip())
    if cleaned:
        key = re.sub(r"[^a-z0-9]+", "_", _norm(cleaned)).strip("_") or "chat_misc"
        return key, cleaned
    return "chat_misc", "More Chat Apps"


def _is_generic_chat_category(name: str) -> bool:
    n = _norm(name)
    if not n:
        return True
    generic_tokens = (
        "chat apps",
        "chat app",
        "social",
        "applications",
        "apps section",
        "قسم التطبيقات",
        "تطبيقات",
        "تطبيقات الدردشة",
    )
    return any(tok in n for tok in generic_tokens)


def _guess_family(service_key: str, category_name: str, sample_names: list[str]) -> tuple[str, str]:
    text = _norm(" ".join([category_name] + list(sample_names or [])))
    for key, label, tokens in _family_rules_for_service(service_key):
        if any(token in text for token in tokens):
            return key, label
    base = _norm(category_name) or _norm(" ".join(sample_names[:2]))
    cleaned = re.sub(r"(gift\s*cards?|giftcards?|vouchers?|voucher|cards?)", " ", base, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "other", "Other"
    key = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_") or "other"
    label = " ".join(part.capitalize() for part in cleaned.split()[:4]) or "Other"
    return key, label


def _grouped_gift_categories(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    grouped: dict[str, dict[str, Any]] = {}
    source_map: dict[str, set[str]] = {}
    products_by_category = dict(snapshot.get("products_by_category") or {})
    for cat in list(snapshot.get("gift_categories") or []):
        cat_id = str(cat.get("id") or "").strip()
        if not cat_id:
            continue
        category_name = str(cat.get("clean_name") or cat.get("name") or "-").strip()
        service_key = str(cat.get("service_key") or _gift_service_key(category_name))
        product_rows = list(products_by_category.get(cat_id) or [])
        sample_rows = product_rows[:6]
        sample_names = [str(row.get("name") or row.get("clean_name") or "") for row in sample_rows]

        if service_key == "chat_apps" and _is_generic_chat_category(category_name):
            for row in product_rows:
                row_name = str(row.get("clean_name") or row.get("name") or "").strip()
                family_key, family_label = _chat_family_from_product_name(row_name)
                group_id = f"grp:g:{service_key}:{family_key}"
                if group_id not in grouped:
                    grouped[group_id] = {
                        "id": group_id,
                        "name": family_label,
                        "count": 0,
                        "group_key": _gift_group_key(family_label),
                        "service_key": service_key,
                    }
                    source_map[group_id] = set()
                grouped[group_id]["count"] = int(grouped[group_id]["count"] or 0) + 1
                source_map[group_id].add(cat_id)
            continue

        family_key, family_label = _guess_family(service_key, category_name, sample_names)
        group_id = f"grp:g:{service_key}:{family_key}"
        if group_id not in grouped:
            grouped[group_id] = {
                "id": group_id,
                "name": family_label,
                "count": 0,
                "group_key": _gift_group_key(family_label),
                "service_key": service_key,
            }
            source_map[group_id] = set()
        grouped[group_id]["count"] = int(grouped[group_id]["count"] or 0) + int(cat.get("count") or 0)
        source_map[group_id].add(cat_id)
    gift_group_order = {"popular": 0, "gaming": 1, "apps": 2, "other": 3}
    categories = list(grouped.values())
    categories.sort(key=lambda row: (gift_group_order.get(str(row.get("group_key")), 9), _natural_key(str(row.get("name") or ""))))
    return categories, {gid: sorted(list(ids)) for gid, ids in source_map.items()}


def _grouped_games(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    grouped: dict[str, dict[str, Any]] = {}
    source_map: dict[str, set[str]] = {}
    for game in list(snapshot.get("games") or []):
        game_id = str(game.get("id") or "").strip()
        if not game_id:
            continue
        game_name = str(game.get("name") or "-").strip()
        family_key, family_label = _guess_family("games", game_name, [])
        group_id = f"grp:gm:{family_key}"
        if group_id not in grouped:
            grouped[group_id] = {
                "id": group_id,
                "name": family_label,
                "group_key": _game_root_group_key(family_label),
                "service_key": "games",
            }
            source_map[group_id] = set()
        source_map[group_id].add(game_id)
    game_group_order = {"popular": 0, "global": 1, "all": 2}
    games = list(grouped.values())
    games.sort(key=lambda row: (game_group_order.get(str(row.get("group_key")), 9), _natural_key(str(row.get("name") or ""))))
    return games, {gid: sorted(list(ids)) for gid, ids in source_map.items()}


def _gift_group_label(key: str) -> dict[str, str]:
    labels = {
        "popular": {"en": "Popular", "ar": "الأكثر طلبا"},
        "gaming": {"en": "Gaming", "ar": "الألعاب"},
        "apps": {"en": "Apps", "ar": "التطبيقات"},
        "other": {"en": "Other", "ar": "أخرى"},
    }
    return labels.get(key, labels["other"])


def _provider_label(provider_code: str, *, lang: str) -> str:
    code = _norm(provider_code)
    if code == "za3em":
        return "الزعيم" if lang == "ar" else "Za3em"
    if code == "g2bulk":
        return "جي تو بالك" if lang == "ar" else "G2Bulk"
    return provider_code or ("غير محدد" if lang == "ar" else "Unknown")


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
    categories, _gift_source_map = _grouped_gift_categories(snapshot)
    games, _game_source_map = _grouped_games(snapshot)
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
    game_rows = list(snapshot.get("games") or [])
    chat_games_count = sum(1 for row in game_rows if _gift_service_key(str(row.get("name") or "")) == "chat_apps")
    real_games_count = sum(1 for row in game_rows if _gift_service_key(str(row.get("name") or "")) == "games")
    chat_apps_count = sum(1 for row in categories if str(row.get("service_key")) == "chat_apps") + chat_games_count
    paid_subscriptions_count = sum(1 for row in categories if str(row.get("service_key")) == "paid_subscriptions")
    store_cards_count = sum(1 for row in categories if str(row.get("service_key")) == "store_cards")
    games_count = real_games_count + sum(1 for row in categories if str(row.get("service_key")) == "games")
    comm_enabled = bool(getattr(settings, "zendit_api_token", "") or "") or (
        bool(getattr(settings, "esim_access_code", "") or "")
        and bool(getattr(settings, "esim_access_secret_key", "") or "")
    )
    numbers_enabled = any(
        bool(getattr(settings, key, "") or "")
        for key in (
            "smspool_key",
            "smsman_key",
            "nonvoip_key",
            "herosms_key",
            "pvadeals_key",
            "alisms_key",
            "vaksms_key",
        )
    )
    services = [
        {
            "key": "games",
            "label": {"en": "Games", "ar": "قسم الألعاب"},
            "count": games_count,
            "enabled": games_count > 0,
        },
        {
            "key": "chat_apps",
            "label": {"en": "Chat Apps", "ar": "قسم تطبيقات الدردشة"},
            "count": chat_apps_count,
            "enabled": chat_apps_count > 0,
        },
        {
            "key": "communications_data",
            "label": {"en": "Telecom & Data", "ar": "قسم الاتصالات والبيانات"},
            "count": 2 if comm_enabled else 0,
            "enabled": comm_enabled,
        },
        {
            "key": "numbers_services",
            "label": {"en": "Numbers Services", "ar": "قسم خدمات الأرقام"},
            "count": 1 if numbers_enabled else 0,
            "enabled": numbers_enabled,
        },
        {
            "key": "paid_subscriptions",
            "label": {"en": "Paid Subscriptions", "ar": "قسم الاشتراكات المدفوعة"},
            "count": paid_subscriptions_count,
            "enabled": paid_subscriptions_count > 0,
        },
        {
            "key": "store_cards",
            "label": {"en": "Store Cards", "ar": "قسم بطاقات متاجر"},
            "count": store_cards_count,
            "enabled": store_cards_count > 0,
        },
    ]
    return {
        "enabled": bool(snapshot.get("enabled")),
        "markup_percent": markup,
        "services": services,
        "gift_categories": categories,
        "gift_groups": gift_groups,
        "games": games[:120],
        "game_groups": game_groups,
    }


async def _gift_products(category_id: str, query: str = "") -> list[dict[str, Any]]:
    snapshot = await get_catalog_snapshot(force=False)
    markup = await _markup_percent()
    products_by_category = dict(snapshot.get("products_by_category") or {})
    _, source_map = _grouped_gift_categories(snapshot)
    source_ids = list(source_map.get(str(category_id), [])) if str(category_id).startswith("grp:g:") else [str(category_id)]
    rows: list[tuple[str, dict[str, Any]]] = []
    for sid in source_ids:
        for row in list(products_by_category.get(str(sid), []) or []):
            if isinstance(row, dict):
                rows.append((str(sid), row))
    dedup_rows: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    for sid, row in rows:
        pid = str(row.get("id") or "").strip()
        if not pid:
            continue
        key = (sid, pid)
        if key not in dedup_rows:
            dedup_rows[key] = (sid, row)
    rows = list(dedup_rows.values())
    q = _norm(query)
    out: list[dict[str, Any]] = []
    for sid, item in rows:
        name = str(item.get("clean_name") or item.get("name") or "-")
        if q and fuzz.partial_ratio(q, name.lower()) < 45:
            continue
        unit_price = float(item.get("price") or 0.0)
        offers = [row for row in list(item.get("provider_offers") or []) if isinstance(row, dict)]
        za3em_offers = [
            row
            for row in offers
            if str(row.get("provider") or "").strip().lower() == "za3em" and bool(row.get("available"))
        ]
        za3em_offers.sort(key=lambda row: _money(row.get("price") or 0.0) if _money(row.get("price") or 0.0) > 0 else 9999999)
        za_offer = za3em_offers[0] if za3em_offers else {}
        za_params = [str(v).strip() for v in list(za_offer.get("za3em_params") or []) if str(v).strip()]
        za_qty_min = max(1, int(za_offer.get("za3em_qty_min") or 1)) if za_offer else 1
        za_qty_max = max(za_qty_min, int(za_offer.get("za3em_qty_max") or za_qty_min)) if za_offer else 1
        requires_input = bool(za_offer.get("za3em_requires_input")) if za_offer else False
        unit_sale_price = unit_price * (1 + (float(markup or 0.0) / 100.0))
        display_quantity = za_qty_min if requires_input else 1
        display_sale_price = _money(unit_sale_price * display_quantity)
        out.append(
            {
                "kind": "gift",
                "id": str(item.get("id") or ""),
                "category_id": str(item.get("raw", {}).get("category_id") or item.get("raw", {}).get("cat_id") or item.get("raw", {}).get("categoryId") or sid),
                "name": name,
                "price_usd": display_sale_price,
                "unit_price_usd": round(float(unit_sale_price), 6),
                "stock": int(item.get("stock") or 0),
                "stock_label": "In stock" if int(item.get("stock") or 0) > 0 else "Out of stock",
                "best_provider_code": str(item.get("best_provider") or "g2bulk"),
                "providers_count": len(list(item.get("provider_offers") or [])),
                "za3em_requires_input": requires_input,
                "za3em_params": za_params,
                "za3em_qty_min": za_qty_min,
                "za3em_qty_max": za_qty_max,
                "display_quantity": int(display_quantity),
            }
        )
    out.sort(key=lambda row: _natural_key(str(row.get("name") or "")))
    return out[:100]


async def _game_items(game_id: str, query: str = "") -> dict[str, Any]:
    snapshot = await get_catalog_snapshot(force=False)
    markup = await _markup_percent()
    grouped_games, game_source_map = _grouped_games(snapshot)
    source_game_ids = list(game_source_map.get(str(game_id), [])) if str(game_id).startswith("grp:gm:") else [str(game_id)]
    game_name = str(game_id)
    if str(game_id).startswith("grp:gm:"):
        for row in grouped_games:
            if str(row.get("id") or "") == str(game_id):
                game_name = str(row.get("name") or game_id)
                break
    else:
        game_name = _find_game_name(snapshot, str(game_id))
    rows_with_game: list[tuple[str, dict[str, Any]]] = []
    for source_game_id in source_game_ids:
        source_rows = await get_game_topups(str(source_game_id))
        for row in source_rows:
            rows_with_game.append((str(source_game_id), row))
    q = _norm(query)
    items: list[dict[str, Any]] = []
    for source_game_id, item in rows_with_game:
        group = _classify_game_item(source_game_id, item)
        name = _display_game_item_name(item, group)
        if q and fuzz.partial_ratio(q, name.lower()) < 45:
            continue
        items.append(
            {
                "kind": "game",
                "id": str(item.get("id") or ""),
                "game_id": str(source_game_id),
                "group_key": group,
                "name": name,
                "price_usd": _resolve_game_sale_price(
                    item.get("price"),
                    markup,
                    game_id=str(source_game_id),
                    game_name=_find_game_name(snapshot, str(source_game_id)),
                ),
                "requires_server": bool(item.get("requires_server")),
                "best_provider_code": str(item.get("best_provider") or "g2bulk"),
                "providers_count": len(list(item.get("provider_offers") or [])),
            }
        )
    group_order = {"topup": 0, "passes": 1, "specials": 2}
    items.sort(key=lambda row: (group_order.get(str(row.get("group_key") or ""), 9), _money(row.get("price_usd")), _natural_key(str(row.get("name") or ""))))
    groups = [
        {"key": key, "label": _game_group_label(key)}
        for key in ("topup", "passes", "specials")
        if any(str(row.get("group_key")) == key for row in items)
    ]
    return {"game_id": str(game_id), "game_name": game_name, "groups": groups, "items": items[:120]}


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
        quantity_raw = body.get("quantity")
        try:
            quantity = max(1, int(quantity_raw)) if quantity_raw is not None else 1
        except Exception:
            quantity = 1
        extra_params = body.get("extra_params") if isinstance(body.get("extra_params"), dict) else {}
        quoted_price_usd = _money(body.get("quoted_price_usd") or 0.0)
        payload = {
            "kind": "gift",
            "category_id": category_id,
            "product_id": product_id,
            "quantity": quantity,
            "extra_params": extra_params,
            "quoted_price_usd": quoted_price_usd,
        }
    elif kind == "game":
        game_id = str(body.get("game_id") or "").strip()
        item_id = str(body.get("item_id") or "").strip()
        group_key = str(body.get("group_key") or "topup").strip() or "topup"
        if not game_id or not item_id:
            raise web.HTTPBadRequest(text="missing game selection")
        payload = {
            "kind": "game",
            "game_id": game_id,
            "item_id": item_id,
            "group_key": group_key,
            "player_id": str(body.get("player_id") or "").strip(),
            "server_id": str(body.get("server_id") or "").strip(),
            "quoted_price_usd": _money(body.get("quoted_price_usd") or 0.0),
        }
    elif kind == "simtopup":
        section = str(body.get("section") or "").strip().lower()
        if section not in {"balance", "data"}:
            raise web.HTTPBadRequest(text="invalid sim section")
        payload = {"kind": "simtopup", "section": section}
    elif kind == "esim":
        payload = {"kind": "esim"}
    elif kind == "numbers_services":
        payload = {"kind": "numbers_services"}
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
