from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl
from uuid import uuid4

from aiohttp import web
from rapidfuzz import fuzz

from config import settings
from database.digital_products_config_repo import get_digital_products_markup_percent
from database.mongo import db
from services.digital_products.catalog_service import (
    digital_provider_enabled,
    get_catalog_snapshot,
    get_game_topups,
    za3em_provider_enabled,
)
from services.digital_products.custom_catalog import FAMILY_TABLE as CUSTOM_FAMILY_TABLE, SECTION_TABLE
from services.digital_products.fulfillment_rules import (
    AUTO_TOPUP_MODE,
    MANUAL_TOPUP_MODE,
    VOUCHER_DELIVERY_MODE,
    game_default_unit,
    game_family_key,
    is_manual_feature,
    manual_feature_compare_key,
    manual_feature_info,
    offer_compare_key,
)
from services.numbers.core.session_manager import SessionManager
from services.digital_products.static_taxonomy import (
    REGION_TOKENS,
    clean_family_text,
    detect_service_key,
    guess_family as taxonomy_guess_family,
    norm_text as taxonomy_norm_text,
    provider_label as taxonomy_provider_label,
)

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "webapp" / "digital"
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
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
_INVALID_DISPLAY_NAMES = {"", "-", "null", "none", "n/a", "na", "undefined"}
_HIDDEN_GAME_VARIANT_IDS = {"valorant", "league_of_legends_instant", "onepunchworld"}
_CATALOG_PAYLOAD_CACHE: dict[str, Any] = {"ts": 0.0, "data": None, "provider_state": {}}
_REGION_LABEL_MAP: dict[str, str] = {
    "my": "Malaysia",
    "sg": "Singapore",
    "sgmy": "SGMY",
    "ph": "Philippines",
    "kh": "Cambodia",
    "vn": "Vietnam",
    "ksa": "KSA",
    "uae": "UAE",
    "usa": "USA",
    "us": "USA",
    "eu": "Europe",
    "na": "North America",
    "naeu": "NAEU",
    "latam": "LATAM",
    "mena": "MENA",
    "sea": "SEA",
    "global": "Global",
    "middle east": "Middle East",
    "hong kong": "Hong Kong",
    "german": "Germany",
    "الماني": "Germany",
    "اماراتي": "UAE",
    "امريكي": "USA",
    "اوربي": "Europe",
    "سعودي": "KSA",
    "كندي": "Canada",
    "تركية": "Turkey",
    "تركي": "Turkey",
    "بطاقات عالمي": "Global",
    "عالمي": "Global",
    "mobile": "Global",
    "اضافات": "Add-ons",
    "memberships": "Memberships",
    "special": "Special",
    "limited promo": "Limited Promo",
    "exclusive": "Exclusive",
    "adventure": "Adventure",
    "infinite": "Infinite",
    "garena": "Garena",
}
_GAME_ID_REGION_SUFFIXES: dict[str, str] = {
    "bd": "Bangladesh",
    "br": "Brazil",
    "eu": "Europe",
    "global": "Global",
    "id": "Indonesia",
    "latam": "LATAM",
    "me": "Middle East",
    "sg": "Singapore",
    "sgmy": "SGMY",
    "tw": "Taiwan",
    "th": "Thailand",
    "vn": "Vietnam",
    "kh": "Cambodia",
    "ca": "Canada",
    "hk": "Hong Kong",
    "my": "Malaysia",
    "mx": "Mexico",
    "ph": "Philippines",
    "us": "USA",
    "tr": "Turkey",
    "ru": "Russia",
    "europa": "Europe",
}
_GAME_DEFAULT_TOPUP_UNIT: dict[str, str] = {
    "pubgm": "UC",
    "newstate": "NC",
    "new_state": "NC",
}
_KNOWN_REGION_LABELS: set[str] = {
    "general",
    "global",
    "usa",
    "uk",
    "ksa",
    "uae",
    "europe",
    "north america",
    "naeu",
    "latam",
    "mena",
    "sea",
    "middle east",
    "hong kong",
    "germany",
    "turkey",
    "canada",
    "brazil",
    "bangladesh",
    "indonesia",
    "taiwan",
    "thailand",
    "vietnam",
    "singapore",
    "malaysia",
    "philippines",
    "cambodia",
    "mexico",
    "japan",
    "korea",
    "russia",
}
_KNOWN_OPTION_LABELS: set[str] = {
    "add-ons",
    "memberships",
    "special",
    "limited promo",
    "exclusive",
    "adventure",
    "infinite",
    "garena",
}
_GAME_REGION_ALLOWLIST: set[str] = {
    "global",
    "europe",
    "mena",
    "middle east",
    "usa",
    "north america",
    "naeu",
    "germany",
    "turkey",
    "general",
    "top up",
    "add-ons",
}


def _money(value: Any) -> float:
    try:
        return round(float(value), 2)
    except Exception:
        return 0.0


def _round_sale_price(value: Any) -> float:
    amount = _money(value)
    if amount <= 0:
        return 0.0
    rounded = (
        (Decimal(str(amount)) * Decimal("2")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / Decimal("2")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(rounded)


async def _markup_percent() -> float:
    try:
        return float(await get_digital_products_markup_percent(0.0))
    except Exception:
        return 0.0


def _with_markup(price: Any, markup_percent: float) -> float:
    base = _money(price)
    if markup_percent <= 0:
        return _round_sale_price(base)
    return _round_sale_price(base * (1 + (markup_percent / 100.0)))


def _norm(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _is_invalid_display_name(name: str | None) -> bool:
    return _norm(name) in _INVALID_DISPLAY_NAMES


def _is_valid_gift_row(row: dict[str, Any]) -> bool:
    name = str(row.get("clean_name") or row.get("name") or "").strip()
    if _is_invalid_display_name(name):
        return False
    try:
        return float(row.get("price") or 0.0) > 0 and int(row.get("stock") or 0) > 0
    except Exception:
        return False


def _provider_offers(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in list(row.get("provider_offers") or [])
        if isinstance(item, dict) and digital_provider_enabled(str(item.get("provider") or ""))
    ]


def _best_enabled_offer(row: dict[str, Any]) -> dict[str, Any]:
    offers = [
        item
        for item in _provider_offers(row)
        if bool(item.get("available")) and _money(item.get("price") or 0.0) > 0
    ]
    offers.sort(key=lambda item: _money(item.get("price") or 0.0))
    return dict(offers[0]) if offers else {}


def _offer_requires_identity(offer: dict[str, Any]) -> bool:
    params = [taxonomy_norm_text(str(value or "")) for value in list(offer.get("za3em_params") or []) if str(value or "").strip()]
    if not params:
        return False
    identity_tokens = (
        "id",
        "uid",
        "player",
        "account",
        "email",
        "mail",
        "character",
        "nickname",
        "user",
        "login",
        "الايدي",
        "ايدي",
        "ايميل",
        "الاميل",
        "البريد",
        "اسم الشخصية",
        "اسم الحساب",
        "اسم اللاعب",
        "معرف",
    )
    return any(any(token in param for token in identity_tokens) for param in params)


def _row_requires_identity(row: dict[str, Any]) -> bool:
    offers = _provider_offers(row)
    return any(_offer_requires_identity(offer) for offer in offers)


def _offer_requires_quantity_input(offer: dict[str, Any]) -> bool:
    qty_min = max(1, int(offer.get("za3em_qty_min") or 1))
    qty_max = max(qty_min, int(offer.get("za3em_qty_max") or qty_min))
    source = str(offer.get("source") or "").strip().lower()
    return source == "amount" and qty_max > 1


def _looks_topup_product_name(name: str | None) -> bool:
    n = taxonomy_norm_text(name)
    compact = re.sub(r"[\s,]+", "", n)
    if not n:
        return False
    if re.fullmatch(r"\d+(?:\s*(?:uc|nc|cp|vp|rp|diamonds?|gems?|coins?|cash|crystals?))?", compact):
        return True
    if re.search(r"\bv\s*\d+\b", n) or re.search(r"بطاقة\s*v?\s*\d+", str(name or ""), flags=re.IGNORECASE):
        return True
    topup_tokens = (
        "uc",
        "nc",
        "cp",
        "vp",
        "rp",
        "vbucks",
        "v-bucks",
        "diamond",
        "diamonds",
        "gem",
        "gems",
        "coin",
        "coins",
        "cash",
        "crystal",
        "crystals",
        "jade",
        "token",
        "tokens",
        "credit",
        "credits",
        "voucher",
        "vouchers",
        "جوهرة",
        "جواهر",
        "شدة",
        "شدات",
        "عملة",
        "عملات",
        "كاش",
        "كوين",
        "كوينز",
        "كريستال",
        "كريستالات",
    )
    return any(token in n for token in topup_tokens)


def _split_game_gift_rows(rows: list[dict[str, Any]], *, family_has_auto_topup: bool, category_name: str = "") -> dict[str, list[dict[str, Any]]]:
    split = {"topup": [], "addons": []}
    for row in rows:
        name = str(row.get("clean_name") or row.get("name") or "").strip()
        if not name:
            continue
        if is_manual_feature(category_name, name):
            split["topup"].append(row)
            continue
        requires_identity = _row_requires_identity(row)
        is_topup = _looks_topup_product_name(name)
        if requires_identity:
            split["topup" if is_topup else "addons"].append(row)
            continue
        if is_topup:
            # Future-like currency cards/codes never belong in top-up.
            if family_has_auto_topup:
                continue
            continue
        # Keep non-currency extras without identity only as add-ons.
        split["addons"].append(row)
    return split


def _gift_image_url(category_row: dict[str, Any], product_rows: list[dict[str, Any]]) -> str:
    raw = category_row.get("raw")
    if isinstance(raw, dict):
        direct = str(raw.get("category_img") or raw.get("image_url") or raw.get("image") or "").strip()
        if direct:
            return direct
    for row in product_rows:
        if not isinstance(row, dict):
            continue
        row_raw = row.get("raw")
        if not isinstance(row_raw, dict):
            continue
        direct = str(row_raw.get("category_img") or row_raw.get("image_url") or row_raw.get("image") or "").strip()
        if direct:
            return direct
    return ""


def _is_pubg_game(game_id: str | None, game_name: str | None = None) -> bool:
    text = f"{_norm(game_id)} {_norm(game_name)}".strip()
    if not text:
        return False
    return any(key in text for key in ("pubg", "pubgm", "new state", "newstate"))


def _resolve_game_sale_price(price: Any, markup_percent: float, *, game_id: str | None, game_name: str | None = None) -> float:
    base = _money(price)
    marked = _with_markup(base, markup_percent)
    return marked


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


def _display_manual_feature_name(name: str) -> str:
    text = " ".join(str(name or "").strip().split())
    if " - " in text:
        tail = text.rsplit(" - ", 1)[-1].strip()
        if tail:
            text = tail
    text = re.sub(r"\b(gift\s*cards?|giftcards?|vouchers?|voucher|cards?)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -")
    text = re.sub(r"\bUc\b", "UC", text)
    return text or str(name or "-").strip()


def _display_game_item_name(item: dict[str, Any], group_key: str = "topup", game_id: str = "") -> str:
    name = _normalize_game_item_name(str(item.get("clean_name") or item.get("name") or "-").strip())
    if group_key == "topup":
        compact = name.replace(",", "").strip()
        if re.fullmatch(r"\d+", compact):
            unit = _GAME_DEFAULT_TOPUP_UNIT.get(str(game_id or "").strip().lower())
            return f"{compact} {unit}".strip() if unit else compact
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
    return detect_service_key(name)
    n = _norm(name)
    if ("telegram" in n or "تلغرام" in n) and any(
        k in n
        for k in (
            "premium",
            "subscription",
            "subscriptions",
            "star",
            "stars",
            "اشتراك",
            "اشتراكات",
            "بريميوم",
        )
    ):
        return "paid_subscriptions"
    if any(
        k in n
        for k in (
            "discord",
            "imo",
            "chat",
            "social",
            "apps",
            "applications",
            "قسم التطبيقات",
            "تطبيقات",
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
            "android amt",
            "dft pro",
            "eft pro",
            "unlock tool",
            "unlock",
            "انلوك",
            "amt",
        )
    ):
        return "paid_apps"
    if any(
        k in n
        for k in (
            "internet",
            "internet provider",
            "wifi",
            "wi-fi",
            "fiber",
            "broadband",
            "مزود",
            "مزودات",
            "انترنت",
            "hifi net",
            "lazer net",
            "pro net",
            "sama net",
            "view net",
            "party star",
            "mts",
        )
    ):
        return "internet_providers"
    if any(
        k in n
        for k in (
            "steam",
            "itunes",
            "apple",
            "google play",
            "google",
            "playstation",
            "psn",
            "xbox",
            "nintendo",
            "razer",
            "roblox",
            "gift card",
            "gift cards",
            "voucher",
            "vouchers",
            "cards",
        )
    ):
        return "store_cards"
    if any(
        k in n
        for k in (
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
            ("pubg", "PUBG", ("ببجي", "اضافات ببجي")),
            ("mobile_legends", "Mobile Legends", ("mobile legends", "mlbb", "موبايل ليجند")),
            ("free_fire", "Free Fire", ("free fire", "garena free fire", "فري فاير")),
            ("honor_of_kings", "Honor of Kings", ("honor of kings", "hok")),
            ("league_of_legends", "League of Legends", ("league of legends", "lol", "riot", "riot points", "league")),
            ("yalla_ludo", "Yalla Ludo", ("yalla ludo", "يلا لودو")),
            ("jawaker", "Jawaker", ("jawaker", "جواكر")),
            ("clash_of_clans", "Clash of Clans", ("clash of clans", "coc")),
            ("brawl_stars", "Brawl Stars", ("brawl stars", "brawl star")),
            ("cod", "Call of Duty", ("call of duty", "cod")),
            ("fortnite", "Fortnite", ("fortnite",)),
            ("valorant", "Valorant", ("valorant",)),
            ("genshin", "Genshin", ("genshin",)),
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
    if service_key == "paid_apps":
        return [
            ("android_amt", "Android AMT", ("android amt", "amt")),
            ("dft_pro", "DFT Pro", ("dft pro",)),
            ("eft_pro", "EFT Pro", ("eft pro",)),
            ("unlock_tool", "Unlock Tool", ("unlock tool", "unlock", "انلوك")),
            ("paid_apps", "Paid Apps", ("pro", "tool", "app", "apps")),
        ]
    if service_key == "internet_providers":
        return [
            ("hifi_net", "Hifi Net", ("hifi net",)),
            ("lazer_net", "Lazer Net", ("lazer net",)),
            ("pro_net", "Pro Net", ("pro net",)),
            ("sama_net", "Sama Net", ("sama net",)),
            ("view_net", "View Net", ("view net",)),
            ("mts", "MTS", ("mts",)),
            ("internet_providers", "Internet Providers", ("internet", "wifi", "fiber", "مزود", "انترنت")),
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
            ("league_of_legends", "League of Legends", ("league of legends", "lol", "riot", "riot points", "league")),
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
    mapped_key, mapped_label = taxonomy_guess_family("chat_apps", str(name or ""), [])
    if mapped_key and mapped_key != "other":
        return mapped_key, mapped_label
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


def _subscription_family_from_product_name(name: str) -> tuple[str, str]:
    n = _norm(name)
    rules: list[tuple[str, str, tuple[str, ...]]] = [
        ("netflix", "Netflix", ("netflix", "نت فلكس")),
        ("shahid", "Shahid", ("shahid", "شاهد")),
        ("canva", "Canva", ("canva", "كانفا")),
        ("chatgpt", "ChatGPT", ("chatgpt",)),
        ("spotify", "Spotify", ("spotify",)),
        ("snapchat_plus", "Snapchat+", ("snapchat", "سناب")),
        ("shamna", "Shamna", ("شامنا", "shamna")),
        ("unlock_tool", "Unlock Tool", ("unlock tool", "انلوك")),
        ("youtube", "YouTube", ("youtube", "يوتيوب")),
    ]
    for key, label, tokens in rules:
        if any(tok in n for tok in tokens):
            return key, label
    cleaned = re.sub(r"\s+", " ", str(name or "").strip())
    if cleaned:
        key = re.sub(r"[^a-z0-9]+", "_", _norm(cleaned)).strip("_") or "subscriptions_misc"
        return key, cleaned
    return "subscriptions_misc", "More Subscriptions"


def _is_generic_subscription_category(name: str) -> bool:
    n = _norm(name)
    if not n:
        return True
    generic_tokens = (
        "subscriptions",
        "subscription",
        "premium",
        "اشتراك",
        "اشتراكات",
    )
    return any(tok in n for tok in generic_tokens)


def _guess_family(service_key: str, category_name: str, sample_names: list[str]) -> tuple[str, str]:
    return taxonomy_guess_family(service_key, category_name, list(sample_names or []))
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
        product_rows = [row for row in list(products_by_category.get(cat_id) or []) if isinstance(row, dict) and _is_valid_gift_row(row)]
        if not product_rows:
            continue
        for row in product_rows:
            row_name = str(row.get("clean_name") or row.get("name") or "").strip()
            row_service = _gift_service_key(f"{row_name} {category_name}")
            manual_info = manual_feature_info(category_name, row_name)
            if manual_info:
                row_service = "games"
                family_key = str(manual_info.get("family_key") or "")
                family_label = str(manual_info.get("family_label") or family_key or "Games")
            elif row_service == "chat_apps":
                family_key, family_label = _chat_family_from_product_name(row_name)
            elif row_service == "paid_subscriptions":
                family_key, family_label = _subscription_family_from_product_name(row_name)
            else:
                family_key, family_label = _guess_family(row_service, category_name, [row_name])
            group_id = f"grp:g:{row_service}:{family_key}"
            if group_id not in grouped:
                grouped[group_id] = {
                    "id": group_id,
                    "name": family_label,
                    "count": 0,
                    "group_key": _gift_group_key(family_label),
                    "service_key": row_service,
                }
                source_map[group_id] = set()
            grouped[group_id]["count"] = int(grouped[group_id]["count"] or 0) + 1
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
        if _norm(game_id) in _HIDDEN_GAME_VARIANT_IDS:
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
                "count": 0,
                "variants": [],
                "image_url": "",
            }
            source_map[group_id] = set()
        source_map[group_id].add(game_id)
        image_url = str(game.get("image_url") or "").strip()
        if image_url and not str(grouped[group_id].get("image_url") or "").strip():
            grouped[group_id]["image_url"] = image_url
        grouped[group_id]["count"] = int(grouped[group_id].get("count") or 0) + 1
        grouped[group_id]["variants"].append(
            {
                "id": game_id,
                "name": game_name,
                "entry_kind": "game",
                "game_ids": [game_id],
                "gift_category_ids": [],
                "image_url": image_url,
            }
        )
    game_group_order = {"popular": 0, "global": 1, "all": 2}
    games = list(grouped.values())
    for row in games:
        variants = [item for item in list(row.get("variants") or []) if isinstance(item, dict)]
        uniq: dict[str, dict[str, Any]] = {}
        for item in variants:
            key = str(item.get("id") or "").strip()
            if key and key not in uniq:
                uniq[key] = item
        ordered = list(uniq.values())
        ordered.sort(key=lambda item: _natural_key(str(item.get("name") or "")))
        row["variants"] = ordered
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
    return taxonomy_provider_label(provider_code, lang=lang)


def _miniapp_provider_state() -> dict[str, bool]:
    return {"za3em_enabled": za3em_provider_enabled()}


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


async def _catalog_payload() -> dict[str, Any]:
    provider_state = _miniapp_provider_state()
    snapshot = await get_catalog_snapshot(force=False)
    markup = await _markup_percent()
    categories, gift_source_map = _grouped_gift_categories(snapshot)
    grouped_games, game_source_map = _grouped_games(snapshot)
    service_tree = _build_service_tree(snapshot, grouped_games, game_source_map, categories, gift_source_map)
    tree_counts = {
        str(row.get("key") or "").strip(): len(list(row.get("families") or []))
        for row in list(service_tree or [])
        if isinstance(row, dict)
    }
    gift_groups = [
        {"key": key, "label": _gift_group_label(key)}
        for key in ("popular", "gaming", "apps", "other")
        if any(str(row.get("group_key")) == key for row in categories)
    ]
    game_groups = [
        {"key": key, "label": _game_root_group_label(key)}
        for key in ("popular", "global", "all")
        if any(str(row.get("group_key")) == key for row in grouped_games)
    ]
    game_rows = list(snapshot.get("games") or [])
    chat_games_count = sum(1 for row in game_rows if _gift_service_key(str(row.get("name") or "")) == "chat_apps")
    real_games_count = sum(1 for row in game_rows if _gift_service_key(str(row.get("name") or "")) == "games")
    chat_apps_count = sum(1 for row in categories if str(row.get("service_key")) == "chat_apps") + chat_games_count
    paid_apps_count = sum(1 for row in categories if str(row.get("service_key")) == "paid_apps")
    social_services_count = sum(1 for row in categories if str(row.get("service_key")) == "social_services")
    internet_providers_count = sum(1 for row in categories if str(row.get("service_key")) == "internet_providers")
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
    service_counts = {
        "games": int(tree_counts.get("games", games_count) or 0),
        "chat_apps": int(tree_counts.get("chat_apps", chat_apps_count) or 0),
        "social_services": int(tree_counts.get("social_services", social_services_count) or 0),
        "communications_data": 2 if comm_enabled else 0,
        "internet_providers": int(tree_counts.get("internet_providers", internet_providers_count) or 0),
        "paid_apps": int(tree_counts.get("paid_apps", paid_apps_count) or 0),
        "numbers_services": 1 if numbers_enabled else 0,
        "paid_subscriptions": int(tree_counts.get("paid_subscriptions", paid_subscriptions_count) or 0),
        "store_cards": int(tree_counts.get("store_cards", store_cards_count) or 0),
    }
    services = [
        {
            "key": str(row.get("key") or "").strip(),
            "label": dict(row.get("label") or {}),
            "count": int(service_counts.get(str(row.get("key") or "").strip(), 0) or 0),
            "enabled": int(service_counts.get(str(row.get("key") or "").strip(), 0) or 0) > 0,
        }
        for row in SECTION_TABLE
        if str(row.get("key") or "").strip()
    ]
    payload = {
        "enabled": bool(snapshot.get("enabled")),
        "markup_percent": markup,
        "providers": dict(snapshot.get("providers") or {}),
        "services": services,
        "gift_categories": categories,
        "gift_groups": gift_groups,
        "games": grouped_games[:300],
        "game_groups": game_groups,
        "service_tree": service_tree,
    }
    _CATALOG_PAYLOAD_CACHE["data"] = dict(payload)
    _CATALOG_PAYLOAD_CACHE["provider_state"] = provider_state
    return payload


async def _gift_products(category_id: str, query: str = "", offer_mode: str = "") -> list[dict[str, Any]]:
    snapshot = await get_catalog_snapshot(force=False)
    markup = await _markup_percent()
    products_by_category = dict(snapshot.get("products_by_category") or {})
    categories_by_id = {
        str(row.get("id") or "").strip(): str(row.get("clean_name") or row.get("name") or "").strip()
        for row in list(snapshot.get("gift_categories") or [])
        if isinstance(row, dict)
    }
    _, source_map = _grouped_gift_categories(snapshot)
    source_ids = list(source_map.get(str(category_id), [])) if str(category_id).startswith("grp:g:") else [str(category_id)]
    expected_service = ""
    expected_family = ""
    if str(category_id).startswith("grp:g:"):
        parts = str(category_id).split(":", 4)
        if len(parts) >= 5:
            expected_service = str(parts[3] or "").strip()
            expected_family = str(parts[4] or "").strip()
    rows: list[tuple[str, dict[str, Any]]] = []
    for sid in source_ids:
        category_name = str(categories_by_id.get(str(sid), ""))
        for row in list(products_by_category.get(str(sid), []) or []):
            if isinstance(row, dict):
                if expected_service and expected_family:
                    row_name = str(row.get("clean_name") or row.get("name") or "").strip()
                    row_service = _gift_service_key(f"{row_name} {category_name}")
                    manual_info = manual_feature_info(category_name, row_name)
                    if manual_info:
                        row_service = "games"
                        row_family = str(manual_info.get("family_key") or "")
                    elif row_service == "chat_apps":
                        row_family, _ = _chat_family_from_product_name(row_name)
                    elif row_service == "paid_subscriptions":
                        row_family, _ = _subscription_family_from_product_name(row_name)
                    else:
                        row_family, _ = _guess_family(row_service, category_name, [row_name])
                    if row_service != expected_service or row_family != expected_family:
                        continue
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
    offer_mode = _norm(offer_mode)
    out: list[dict[str, Any]] = []
    for sid, item in rows:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        name = str(item.get("clean_name") or item.get("name") or "-")
        if _is_invalid_display_name(name):
            continue
        category_name = str(categories_by_id.get(str(sid), ""))
        row_service = _gift_service_key(f"{name} {category_name}")
        manual_info = manual_feature_info(category_name, name)
        if manual_info:
            row_service = "games"
        if row_service == "games" and offer_mode in {"topup", "addons"}:
            split_kind = _split_game_gift_rows([item], family_has_auto_topup=True, category_name=category_name)
            if offer_mode == "topup" and not split_kind["topup"]:
                continue
            if offer_mode == "addons" and not split_kind["addons"]:
                continue
        if q and fuzz.partial_ratio(q, name.lower()) < 45:
            continue
        raw_offers = [row for row in list(item.get("provider_offers") or []) if isinstance(row, dict)]
        offers = _provider_offers(item)
        if raw_offers and not offers:
            continue
        best_offer = _best_enabled_offer(item)
        if offers and not best_offer:
            continue
        unit_price = float((best_offer or {}).get("price") or item.get("price") or 0.0)
        if unit_price <= 0:
            continue
        if int(item.get("stock") or 0) <= 0:
            continue
        za3em_offers = []
        for row in offers:
            if str(row.get("provider") or "").strip().lower() != "za3em":
                continue
            if bool(row.get("available")) or str(row.get("source") or "").strip().lower() == "amount":
                za3em_offers.append(row)
        za3em_offers.sort(key=lambda row: _money(row.get("price") or 0.0) if _money(row.get("price") or 0.0) > 0 else 9999999)
        za_offer = za3em_offers[0] if za3em_offers else {}
        za_params = [str(v).strip() for v in list(za_offer.get("za3em_params") or []) if str(v).strip()]
        za_qty_min = max(1, int(za_offer.get("za3em_qty_min") or 1)) if za_offer else 1
        za_qty_max = max(za_qty_min, int(za_offer.get("za3em_qty_max") or za_qty_min)) if za_offer else 1
        requires_identity = True if manual_info else (_offer_requires_identity(za_offer) if za_offer else False)
        requires_quantity_input = False if manual_info else (_offer_requires_quantity_input(za_offer) if za_offer else False)
        if manual_info:
            za_params = ["player_id"]
            za_qty_min = 1
            za_qty_max = 1
        compare_key = manual_feature_compare_key(category_name, name) if manual_info else ""
        display_name = _display_manual_feature_name(name) if manual_info else name
        unit_sale_price = _round_sale_price(unit_price * (1 + (float(markup or 0.0) / 100.0)))
        display_quantity = za_qty_min if requires_quantity_input else 1
        display_sale_price = _round_sale_price(unit_sale_price * display_quantity)
        if display_sale_price <= 0:
            continue
        out.append(
            {
                "kind": "gift",
                "id": item_id,
                "category_id": str(item.get("raw", {}).get("category_id") or item.get("raw", {}).get("cat_id") or item.get("raw", {}).get("categoryId") or sid),
                "name": display_name,
                "price_usd": display_sale_price,
                "unit_price_usd": round(float(unit_sale_price), 6),
                "stock": int(item.get("stock") or 0),
                "stock_label": "In stock" if int(item.get("stock") or 0) > 0 else "Out of stock",
                "best_provider_code": str((best_offer or {}).get("provider") or item.get("best_provider") or "g2bulk"),
                "providers_count": len(offers),
                "fulfillment_mode": MANUAL_TOPUP_MODE if manual_info else VOUCHER_DELIVERY_MODE,
                "compare_key": compare_key,
                "group_key": "topup" if manual_info else ("topup" if _looks_topup_product_name(name) else "addons"),
                "za3em_requires_input": bool(za_offer.get("za3em_requires_input")) if za_offer else False,
                "requires_identity": requires_identity,
                "requires_quantity_input": requires_quantity_input,
                "za3em_params": za_params,
                "za3em_qty_min": za_qty_min,
                "za3em_qty_max": za_qty_max,
                "display_quantity": int(display_quantity),
            }
        )
    dedup: dict[tuple[str, float, bool, tuple[str, ...], int, int], dict[str, Any]] = {}
    for row in out:
        key = (
            _norm(str(row.get("name") or "")),
            float(row.get("unit_price_usd") or 0.0),
            bool(row.get("requires_identity")),
            bool(row.get("requires_quantity_input")),
            tuple(sorted(str(v) for v in list(row.get("za3em_params") or []))),
            int(row.get("za3em_qty_min") or 1),
            int(row.get("za3em_qty_max") or 1),
        )
        existing = dedup.get(key)
        if not existing or int(row.get("stock") or 0) > int(existing.get("stock") or 0):
            dedup[key] = row
    out = list(dedup.values())
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
        try:
            source_rows = await get_game_topups(str(source_game_id), force=True)
        except Exception:
            source_rows = []
        for row in source_rows:
            rows_with_game.append((str(source_game_id), row))
    q = _norm(query)
    items: list[dict[str, Any]] = []
    for source_game_id, item in rows_with_game:
        group = _classify_game_item(source_game_id, item)
        name = _display_game_item_name(item, group, str(source_game_id))
        if q and fuzz.partial_ratio(q, name.lower()) < 45:
            continue
        raw_offers = [row for row in list(item.get("provider_offers") or []) if isinstance(row, dict)]
        offers = _provider_offers(item)
        if raw_offers and not offers:
            continue
        best_offer = _best_enabled_offer(item)
        if offers and not best_offer:
            continue
        provider_price = (best_offer or {}).get("price") or item.get("price")
        if _money(provider_price) <= 0:
            continue
        resolved_game_name = _find_game_name(snapshot, str(source_game_id))
        family_key = game_family_key(str(source_game_id), resolved_game_name)
        if not family_key:
            family_key, _family_label = _guess_family("games", resolved_game_name, [name])
        region_label = _region_from_game_id(str(source_game_id), resolved_game_name, "Global")
        compare_key = offer_compare_key(
            family_key=family_key,
            region=region_label,
            offer_name=name,
            default_unit=game_default_unit(str(source_game_id), resolved_game_name),
        )
        items.append(
            {
                "kind": "game",
                "id": str(item.get("id") or ""),
                "game_id": str(source_game_id),
                "group_key": group,
                "name": name,
                "price_usd": _resolve_game_sale_price(
                    provider_price,
                    markup,
                    game_id=str(source_game_id),
                    game_name=resolved_game_name,
                ),
                "requires_server": bool(item.get("requires_server")),
                "best_provider_code": str((best_offer or {}).get("provider") or item.get("best_provider") or "g2bulk"),
                "providers_count": len(offers),
                "fulfillment_mode": AUTO_TOPUP_MODE,
                "compare_key": compare_key,
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


async def _server_quote_gift_selection(category_id: str, product_id: str, quantity: int) -> float:
    rows = await _gift_products(category_id)
    for row in rows:
        if str(row.get("id") or "").strip() != str(product_id or "").strip():
            continue
        unit_price = float(row.get("unit_price_usd") or row.get("price_usd") or 0.0)
        if unit_price <= 0:
            break
        return _round_sale_price(unit_price * max(1, int(quantity or 1)))
    raise web.HTTPBadRequest(text="gift selection unavailable")


async def _server_quote_game_selection(game_id: str, item_id: str, group_key: str) -> float:
    data = await _game_items(game_id)
    expected_group = str(group_key or "").strip()
    for row in list(data.get("items") or []):
        if str(row.get("id") or "").strip() != str(item_id or "").strip():
            continue
        if expected_group and str(row.get("group_key") or "").strip() != expected_group:
            continue
        price = float(row.get("price_usd") or 0.0)
        if price > 0:
            return _round_sale_price(price)
    raise web.HTTPBadRequest(text="game selection unavailable")


async def bootstrap_miniapp_indexes() -> None:
    await db.digital_product_miniapp_selections.create_index("expires_at", expireAfterSeconds=0, background=True)
    await db.digital_product_miniapp_selections.create_index([("user_id", 1), ("status", 1), ("created_at", -1)], background=True)


async def index(_request: web.Request) -> web.Response:
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    return web.Response(text=html, content_type="text/html", headers=dict(_NO_STORE_HEADERS))


async def static_file(request: web.Request) -> web.Response:
    name = str(request.match_info.get("name") or "")
    path = (_STATIC / name).resolve()
    if _STATIC.resolve() not in path.parents:
        raise web.HTTPNotFound()
    if not path.exists() or not path.is_file():
        raise web.HTTPNotFound()
    content_type = "text/css" if path.suffix == ".css" else "application/javascript"
    return web.Response(body=path.read_bytes(), content_type=content_type, headers=dict(_NO_STORE_HEADERS))


async def catalog(_request: web.Request) -> web.Response:
    try:
        payload = await _catalog_payload()
    except Exception:
        provider_state = _miniapp_provider_state()
        cached = _CATALOG_PAYLOAD_CACHE.get("data")
        if isinstance(cached, dict) and cached and _CATALOG_PAYLOAD_CACHE.get("provider_state") == provider_state:
            payload = dict(cached)
        else:
            payload = {
                "enabled": False,
                "markup_percent": 0.0,
                "services": [],
                "gift_categories": [],
                "gift_groups": [],
                "games": [],
                "game_groups": [],
                "error": "store_temporarily_unavailable",
            }
    return web.json_response(payload, headers=dict(_NO_STORE_HEADERS))


async def gift_products(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "items": await _gift_products(
                request.match_info["category_id"],
                request.query.get("q", ""),
                request.query.get("mode", ""),
            )
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def game_items(request: web.Request) -> web.Response:
    return web.json_response(
        await _game_items(request.match_info["game_id"], request.query.get("q", "")),
        headers=dict(_NO_STORE_HEADERS),
    )


async def create_selection(request: web.Request) -> web.Response:
    auth = _verify_init_data(request.headers.get("X-Telegram-Init-Data", ""))
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
        quoted_price_usd = await _server_quote_gift_selection(category_id, product_id, quantity)
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
        quoted_price_usd = await _server_quote_game_selection(game_id, item_id, group_key)
        payload = {
            "kind": "game",
            "game_id": game_id,
            "item_id": item_id,
            "group_key": group_key,
            "player_id": str(body.get("player_id") or "").strip(),
            "server_id": str(body.get("server_id") or "").strip(),
            "quoted_price_usd": quoted_price_usd,
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
    token = await _create_selection(int(auth["user_id"]), payload)
    return web.json_response({"token": token}, headers=dict(_NO_STORE_HEADERS))


async def _cleanup_app(_app: web.Application) -> None:
    await SessionManager.close()


def create_app() -> web.Application:
    app = web.Application()
    app.on_cleanup.append(_cleanup_app)
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
def _title_case_region(value: str) -> str:
    text = " ".join(str(value or "").strip().split()).strip("()[]{}")
    if not text:
        return ""
    mapped = _REGION_LABEL_MAP.get(text.lower())
    if mapped:
        return mapped
    upper_map = {"usa", "us", "uk", "eu", "mena", "na", "sa", "latam", "ksa", "uae", "sg", "my", "sgmy", "ph", "kh", "vn", "naeu"}
    words = []
    for part in text.split():
        p = part.strip()
        mapped_part = _REGION_LABEL_MAP.get(p.lower())
        if mapped_part:
            words.append(mapped_part)
        else:
            words.append(p.upper() if p.lower() in upper_map else p.capitalize())
    return " ".join(words)


def _extract_region_label(value: str, family_label: str = "") -> str:
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return "General"
    normalized = taxonomy_norm_text(raw)
    family_base = clean_family_text(family_label)
    text_base = clean_family_text(raw)
    if family_base and text_base == family_base:
        paren = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", raw.strip(), flags=re.IGNORECASE)
        if paren:
            region = paren.group(2).strip()
            return _title_case_region(region) or "General"
        escaped = [re.escape(token) for token in REGION_TOKENS]
        suffix = re.match(rf"^(.*?)(?:\s*[-/|]\s*|\s+)({'|'.join(escaped)})$", normalized, flags=re.IGNORECASE)
        if suffix:
            return _title_case_region(str(suffix.group(2) or "").strip()) or "General"
        return "General"
    paren = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", raw.strip(), flags=re.IGNORECASE)
    if paren and clean_family_text(paren.group(1)) == family_base:
        return _title_case_region(paren.group(2)) or "General"
    escaped = [re.escape(token) for token in REGION_TOKENS]
    suffix = re.match(rf"^(.*?)(?:\s*[-/|]\s*|\s+)({'|'.join(escaped)})$", normalized, flags=re.IGNORECASE)
    if suffix and clean_family_text(suffix.group(1)) == family_base:
        return _title_case_region(str(suffix.group(2) or "").strip()) or "General"
    if family_base and normalized != family_base:
        tail = raw.strip()
        prefix_patterns = [
            rf"^{re.escape(family_label)}\s*[-/|]?\s*",
            rf"^{re.escape(clean_family_text(family_label))}\s*[-/|]?\s*",
        ]
        for pattern in prefix_patterns:
            tail = re.sub(pattern, "", tail, flags=re.IGNORECASE).strip()
        return _title_case_region(tail) or "General"
    return "General"


def _family_aliases(service_key: str, family_key: str, family_label: str) -> list[str]:
    aliases: list[str] = []
    for row in CUSTOM_FAMILY_TABLE.get(service_key, ()):
        if str(row.get("key") or "").strip() == family_key:
            aliases.extend(str(alias or "").strip() for alias in tuple(row.get("aliases") or ()) if str(alias or "").strip())
            break
    aliases.append(family_label)
    aliases.append(clean_family_text(family_label))
    uniq: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        key = taxonomy_norm_text(alias)
        if key and key not in seen:
            seen.add(key)
            uniq.append(alias)
    return uniq


def _resolve_region_label(service_key: str, family_key: str, family_label: str, source_text: str, sample_names: list[str] | None = None) -> str:
    if service_key in {"chat_apps", "social_services", "communications_data", "numbers_services", "paid_apps", "paid_subscriptions"}:
        return "General"
    sample_names = list(sample_names or [])
    guessed_key, _ = _guess_family(service_key, source_text, sample_names)
    raw = " ".join(str(source_text or "").strip().split())
    if guessed_key != family_key:
        return _extract_region_label(raw, family_label)
    aliases = _family_aliases(service_key, family_key, family_label)
    remainder = raw
    for alias in aliases:
        remainder = re.sub(rf"^{re.escape(alias)}\s*[-/|]?\s*", "", remainder, flags=re.IGNORECASE).strip()
        remainder = re.sub(rf"\b{re.escape(alias)}\b", " ", remainder, flags=re.IGNORECASE).strip()
    remainder = re.sub(r"\b(gift\s*cards?|giftcards?|vouchers?|voucher|cards?)\b", " ", remainder, flags=re.IGNORECASE).strip()
    remainder = re.sub(r"\s+", " ", remainder).strip(" -|/")
    if not remainder:
        return "General"
    if taxonomy_norm_text(remainder) in {taxonomy_norm_text(alias) for alias in aliases if alias}:
        return "General"
    remainder_norm = taxonomy_norm_text(remainder)
    if remainder_norm in {"garena sgmy", "global garena sgmy", "mobile garena sgmy"}:
        return "SGMY"
    return _title_case_region(remainder)


def _region_from_game_id(game_id: str, family_label: str, fallback_label: str) -> str:
    gid = taxonomy_norm_text(game_id).strip()
    if not gid:
        return fallback_label
    parts = [part for part in re.split(r"[^a-z0-9]+", gid) if part]
    for token in reversed(parts):
        mapped = _GAME_ID_REGION_SUFFIXES.get(token)
        if mapped:
            return mapped
    if fallback_label == "General":
        return "Global"
    return fallback_label


def _variant_kind(service_key: str, label: str) -> str:
    if service_key in {"chat_apps", "social_services", "communications_data", "numbers_services", "paid_apps", "paid_subscriptions"}:
        return "general"
    n = taxonomy_norm_text(label)
    if n in _KNOWN_OPTION_LABELS:
        return "option"
    if n in _KNOWN_REGION_LABELS:
        return "region"
    if n in {taxonomy_norm_text(v) for v in _REGION_LABEL_MAP.values()}:
        return "option" if n in _KNOWN_OPTION_LABELS else "region"
    return "option"


def _is_allowed_game_variant(row: dict[str, Any]) -> bool:
    label = taxonomy_norm_text(str(row.get("name") or ""))
    kind = str(row.get("variant_kind") or "")
    if kind == "option":
        return label in _GAME_REGION_ALLOWLIST
    if kind == "region":
        return label in _GAME_REGION_ALLOWLIST
    return label in _GAME_REGION_ALLOWLIST


def _merge_named_variant(variants: list[dict[str, Any]], source_name: str, target_name: str) -> list[dict[str, Any]]:
    source = next((row for row in variants if str(row.get("name") or "") == source_name), None)
    target = next((row for row in variants if str(row.get("name") or "") == target_name), None)
    if not source or not target or source is target:
        return variants
    target["game_ids"] = sorted(set(list(target.get("game_ids") or []) + list(source.get("game_ids") or [])))
    target["gift_category_ids"] = sorted(set(list(target.get("gift_category_ids") or []) + list(source.get("gift_category_ids") or [])))
    if str(target.get("entry_kind") or "") != str(source.get("entry_kind") or ""):
        target["entry_kind"] = "mixed"
    if str(target.get("variant_kind") or "") != str(source.get("variant_kind") or ""):
        target["variant_kind"] = "option"
    return [row for row in variants if row is not source]


def _build_service_tree(snapshot: dict[str, Any], grouped_games: list[dict[str, Any]], game_source_map: dict[str, list[str]], grouped_gifts: list[dict[str, Any]], gift_source_map: dict[str, list[str]]) -> list[dict[str, Any]]:
    products_by_category = dict(snapshot.get("products_by_category") or {})
    gift_categories_by_id = {
        str(row.get("id") or "").strip(): row
        for row in list(snapshot.get("gift_categories") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    tree_by_service: dict[str, dict[str, Any]] = {}
    game_family_keys = {
        str(group.get("id") or "").split(":")[-1]
        for group in grouped_games
        if isinstance(group, dict) and str(group.get("id") or "").strip()
    }

    def ensure_service(service_key: str) -> dict[str, Any]:
        existing = tree_by_service.get(service_key)
        if existing:
            return existing
        label = next((dict(row.get("label") or {}) for row in SECTION_TABLE if str(row.get("key") or "").strip() == service_key), {"en": service_key, "ar": service_key})
        existing = {"key": service_key, "label": label, "families": []}
        tree_by_service[service_key] = existing
        return existing

    def ensure_family(service_key: str, family_key: str, family_label: str) -> dict[str, Any]:
        service_node = ensure_service(service_key)
        for row in service_node["families"]:
            if str(row.get("family_key") or "") == family_key:
                return row
        row = {
            "id": f"tree:{service_key}:{family_key}",
            "family_key": family_key,
            "name": family_label,
            "entry_kind": "group",
            "variants": [],
            "count": 0,
            "meta_label": "",
            "image_url": "",
        }
        service_node["families"].append(row)
        return row

    def upsert_region(parent: dict[str, Any], region_label: str, payload: dict[str, Any]) -> None:
        label = region_label or "General"
        existing = None
        for row in parent["variants"]:
            if str(row.get("name") or "") == label:
                existing = row
                break
        if not existing:
            existing = {
                "id": str(payload.get("id") or ""),
                "name": label,
                "entry_kind": str(payload.get("entry_kind") or "gift"),
                "game_ids": list(payload.get("game_ids") or []),
                "gift_category_ids": list(payload.get("gift_category_ids") or []),
                "meta_label": "",
                "variant_kind": str(payload.get("variant_kind") or "general"),
                "image_url": str(payload.get("image_url") or ""),
                "offer_mode": str(payload.get("offer_mode") or "all"),
            }
            parent["variants"].append(existing)
        else:
            existing_kind = str(existing.get("entry_kind") or "gift")
            incoming_kind = str(payload.get("entry_kind") or "gift")
            if existing_kind != incoming_kind:
                existing["entry_kind"] = "mixed"
            if str(existing.get("variant_kind") or "") != str(payload.get("variant_kind") or ""):
                existing["variant_kind"] = "option"
            existing["game_ids"] = sorted(set(list(existing.get("game_ids") or []) + list(payload.get("game_ids") or [])))
            existing["gift_category_ids"] = sorted(set(list(existing.get("gift_category_ids") or []) + list(payload.get("gift_category_ids") or [])))
            if not existing.get("id"):
                existing["id"] = str(payload.get("id") or "")
            if not str(existing.get("image_url") or "").strip():
                existing["image_url"] = str(payload.get("image_url") or "")
            existing_offer_mode = str(existing.get("offer_mode") or "all")
            incoming_offer_mode = str(payload.get("offer_mode") or "all")
            if existing_offer_mode != incoming_offer_mode:
                existing["offer_mode"] = "all"

    for group in grouped_games:
        family_key = str(group.get("id") or "").split(":")[-1]
        family_label = str(group.get("name") or "-")
        parent = ensure_family("games", family_key, family_label)
        for variant in list(group.get("variants") or []):
            game_name = str(variant.get("name") or "").strip()
            region_label = _resolve_region_label("games", family_key, family_label, game_name, [game_name])
            region_label = _region_from_game_id(str(variant.get("id") or ""), family_label, region_label)
            image_url = str(variant.get("image_url") or group.get("image_url") or "").strip()
            if image_url and not str(parent.get("image_url") or "").strip():
                parent["image_url"] = image_url
            upsert_region(
                parent,
                region_label,
                {
                    "id": str(variant.get("id") or ""),
                    "entry_kind": "game",
                    "game_ids": list(variant.get("game_ids") or [str(variant.get("id") or "")]),
                    "gift_category_ids": [],
                    "variant_kind": _variant_kind("games", region_label),
                    "image_url": image_url,
                    "offer_mode": "topup",
                },
            )

    for group in grouped_gifts:
        service_key = str(group.get("service_key") or "").strip()
        if not service_key:
            continue
        family_key = str(group.get("id") or "").split(":")[-1]
        family_label = str(group.get("name") or "-")
        parent = ensure_family(service_key, family_key, family_label)
        for source_id in list(gift_source_map.get(str(group.get("id") or ""), []) or []):
            category_row = gift_categories_by_id.get(str(source_id)) or {}
            category_name = str(category_row.get("clean_name") or category_row.get("name") or family_label).strip()
            product_rows = [row for row in list(products_by_category.get(str(source_id)) or []) if isinstance(row, dict) and _is_valid_gift_row(row)]
            if not product_rows:
                continue
            image_url = _gift_image_url(category_row, product_rows)
            if image_url and not str(parent.get("image_url") or "").strip():
                parent["image_url"] = image_url
            names = [str(row.get("clean_name") or row.get("name") or "").strip() for row in product_rows if str(row.get("clean_name") or row.get("name") or "").strip()]
            if service_key == "games":
                family_has_auto_topup = family_key in game_family_keys
                split_rows = _split_game_gift_rows(product_rows, family_has_auto_topup=family_has_auto_topup, category_name=category_name)
                has_id_topup = bool(split_rows["topup"])
                if has_id_topup:
                    family_has_auto_topup = True
                if split_rows["topup"]:
                    region_label = _resolve_region_label(service_key, family_key, family_label, category_name, names)
                    if family_key in game_family_keys and (
                        region_label in {"General", "Global", "Top Up"} or _variant_kind(service_key, region_label) == "option"
                    ):
                        region_label = "Global"
                    elif split_rows["addons"] and region_label in {"General", "Global"}:
                        region_label = "Top Up"
                    elif _variant_kind(service_key, region_label) == "option":
                        region_label = "Top Up"
                    upsert_region(
                        parent,
                        region_label,
                        {
                            "id": f"{source_id}:topup",
                            "entry_kind": "gift",
                            "game_ids": [],
                            "gift_category_ids": [str(source_id)],
                            "variant_kind": _variant_kind(service_key, region_label),
                            "offer_mode": "topup",
                            "image_url": image_url,
                        },
                    )
                if split_rows["addons"]:
                    upsert_region(
                        parent,
                        "Add-ons",
                        {
                            "id": f"{source_id}:addons",
                            "entry_kind": "gift",
                            "game_ids": [],
                            "gift_category_ids": [str(source_id)],
                            "variant_kind": "option",
                            "offer_mode": "addons",
                            "image_url": image_url,
                        },
                    )
                continue
            region_label = _resolve_region_label(service_key, family_key, family_label, category_name, names)
            upsert_region(
                parent,
                region_label,
                {
                    "id": str(source_id),
                    "entry_kind": "gift",
                    "game_ids": [],
                    "gift_category_ids": [str(source_id)],
                    "variant_kind": _variant_kind(service_key, region_label),
                    "offer_mode": "all",
                    "image_url": image_url,
                },
            )

    service_rows = []
    for section in SECTION_TABLE:
        service_key = str(section.get("key") or "").strip()
        if not service_key:
            continue
        node = tree_by_service.get(service_key)
        if not node:
            service_rows.append({"key": service_key, "label": dict(section.get("label") or {}), "families": []})
            continue
        families = list(node.get("families") or [])
        for family in families:
            variants = list(family.get("variants") or [])
            if not variants:
                continue
            if any(str(row.get("name") or "") == "General" for row in variants) and any(str(row.get("name") or "") == "Global" for row in variants):
                variants = _merge_named_variant(variants, "General", "Global")
            has_option = any(str(row.get("variant_kind") or "") == "option" for row in variants)
            if not has_option:
                has_global = any(str(row.get("name") or "") == "Global" for row in variants)
                for row in variants:
                    if str(row.get("name") or "") == "General":
                        row["name"] = "Global" if not has_global else "General"
                        has_global = True
                if has_global:
                    dedup: dict[str, dict[str, Any]] = {}
                    for row in variants:
                        if str(row.get("name") or "") == "General":
                            continue
                        key = str(row.get("name") or "")
                        existing = dedup.get(key)
                        if not existing:
                            dedup[key] = row
                            continue
                        existing["game_ids"] = sorted(set(list(existing.get("game_ids") or []) + list(row.get("game_ids") or [])))
                        existing["gift_category_ids"] = sorted(set(list(existing.get("gift_category_ids") or []) + list(row.get("gift_category_ids") or [])))
                        if str(existing.get("entry_kind") or "") != str(row.get("entry_kind") or ""):
                            existing["entry_kind"] = "mixed"
                    variants = list(dedup.values())
            if service_key == "games":
                variants = [row for row in variants if _is_allowed_game_variant(row)]
                if not variants:
                    family["variants"] = []
                    family["count"] = 0
                    continue
            has_option = any(str(row.get("variant_kind") or "") == "option" for row in variants)
            variants.sort(key=lambda row: (0 if str(row.get("name") or "") in {"General", "Global"} else 1, _natural_key(str(row.get("name") or ""))))
            family["variants"] = variants
            family["count"] = len(variants)
            if service_key == "games" and len(variants) == 1 and str(variants[0].get("name") or "") == "Add-ons":
                family["variants"] = []
                family["count"] = 0
                continue
            if len(variants) == 1:
                family["selection_kind"] = "general"
            else:
                family["selection_kind"] = "option" if has_option else "region"
            if len(variants) == 1:
                family["meta_label"] = "1 offer"
            elif has_option:
                family["meta_label"] = f"{len(variants)} options" if len(variants) != 1 else "1 option"
            else:
                family["meta_label"] = f"{len(variants)} regions" if len(variants) != 1 else "1 region"
        families = [row for row in families if list(row.get("variants") or [])]
        families.sort(key=lambda row: _natural_key(str(row.get("name") or "")))
        service_rows.append({"key": service_key, "label": dict(section.get("label") or {}), "families": families})
    return service_rows
