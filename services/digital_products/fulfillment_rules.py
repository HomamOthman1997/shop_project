from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from services.digital_products.static_taxonomy import norm_text


MANUAL_TOPUP_MODE = "manual_topup"
AUTO_TOPUP_MODE = "auto_topup"
VOUCHER_DELIVERY_MODE = "voucher_delivery"

_FAMILY_LABELS: dict[str, str] = {
    "pubg": "PUBG",
    "new_state": "New State Mobile",
    "yalla_ludo": "Yalla Ludo",
    "jawaker": "Jawaker",
    "roblox": "Roblox",
    "valorant": "Valorant",
    "free_fire": "Free Fire",
}

_UNIT_ALIASES: dict[str, str] = {
    "uc": "uc",
    "nc": "nc",
    "diamond": "diamond",
    "diamonds": "diamond",
    "gem": "gem",
    "gems": "gem",
    "coin": "coin",
    "coins": "coin",
    "token": "token",
    "tokens": "token",
    "crystal": "crystal",
    "crystals": "crystal",
    "star": "star",
    "stars": "star",
    "bean": "bean",
    "beans": "bean",
    "coupon": "coupon",
    "coupons": "coupon",
    "robux": "robux",
    "vp": "vp",
    "rp": "rp",
    "usd": "usd",
    "$": "usd",
}

_UNIT_PRIORITY: tuple[str, ...] = (
    "uc",
    "nc",
    "robux",
    "diamond",
    "gem",
    "coin",
    "token",
    "crystal",
    "star",
    "bean",
    "coupon",
    "vp",
    "rp",
    "usd",
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm_text(value)).strip("_")


def _money_amount(value: str) -> str:
    try:
        dec = Decimal(str(value).replace(",", "")).normalize()
    except (InvalidOperation, ValueError):
        return ""
    if dec == dec.to_integral():
        return str(int(dec))
    return format(dec, "f").rstrip("0").rstrip(".")


def offer_region_label(text: str | None, *, default: str = "Global") -> str:
    normalized = norm_text(text)
    if not normalized:
        return default
    paren_regions = re.findall(r"\(([^)]+)\)", str(text or ""))
    candidates = [norm_text(item) for item in paren_regions if norm_text(item)]
    candidates.append(normalized)
    for candidate in candidates:
        if re.search(r"\b(global|worldwide|intl|international)\b", candidate):
            return "Global"
        if re.search(r"\b(latam|latin america|latin american)\b", candidate):
            return "LATAM"
        if re.search(r"\b(sea|southeast asia|south east asia)\b", candidate):
            return "SEA"
        if re.search(r"\b(us|usa|united states|america|american)\b", candidate):
            return "USA"
        if re.search(r"\b(ksa|saudi|saudi arabia)\b", candidate) or candidate == "sa":
            return "KSA"
        if re.search(r"\b(kw|kuwait)\b", candidate):
            return "KW"
        if re.search(r"\b(ae|uae|united arab emirates)\b", candidate):
            return "UAE"
        if re.search(r"\b(uk|united kingdom|gb)\b", candidate):
            return "UK"
        if re.search(r"\b(eu|europe)\b", candidate):
            return "EU"
        if re.search(r"\b(tr|turkey|turkiye)\b", candidate):
            return "TR"
        if re.search(r"\b(ru|russia|russian)\b", candidate):
            return "RU"
        if re.search(r"\b(ca|canada)\b", candidate):
            return "CA"
        if re.search(r"\b(jp|japan)\b", candidate):
            return "JP"
        if re.search(r"\b(kr|korea|korean|south korea)\b", candidate):
            return "KR"
        if re.search(r"\b(tw|taiwan)\b", candidate):
            return "TW"
        if re.search(r"\b(hk|hong kong)\b", candidate):
            return "HK"
        if re.search(r"\b(sg|singapore)\b", candidate):
            return "SG"
        if re.search(r"\b(my|malaysia)\b", candidate):
            return "MY"
        if re.search(r"\b(ph|philippines|philippine)\b", candidate):
            return "PH"
        if re.search(r"\b(kh|cambodia)\b", candidate):
            return "KH"
        if re.search(r"\b(id|indonesia)\b", candidate):
            return "ID"
        if re.search(r"\b(th|thailand)\b", candidate):
            return "TH"
        if re.search(r"\b(vn|vietnam)\b", candidate):
            return "VN"
        if re.search(r"\b(bd|bangladesh)\b", candidate):
            return "BD"
        if re.search(r"\b(br|brazil)\b", candidate):
            return "BR"
        if re.search(r"\b(mx|mexico)\b", candidate):
            return "MX"
    return default


def manual_feature_info(category_name: str | None, product_name: str | None = None) -> dict[str, str]:
    text = norm_text(f"{category_name or ''} {product_name or ''}")
    if not text:
        return {}

    family_key = ""
    if "new state" in text or "newstate" in text:
        family_key = "new_state"
    elif "pubg" in text or "pubgm" in text:
        family_key = "pubg"
    elif "yalla ludo" in text or "yalla" in text:
        family_key = "yalla_ludo"
    elif "jawaker" in text:
        family_key = "jawaker"
    elif "roblox" in text:
        family_key = "roblox"
    elif "valorant" in text:
        family_key = "valorant"
    elif "free fire" in text or "freefire" in text:
        family_key = "free_fire"

    if not family_key:
        return {}

    region = offer_region_label(text, default="Global")

    return {
        "family_key": family_key,
        "family_label": _FAMILY_LABELS.get(family_key, family_key.replace("_", " ").title()),
        "region": region,
    }


def is_manual_feature(category_name: str | None, product_name: str | None = None) -> bool:
    return bool(manual_feature_info(category_name, product_name))


def _extract_amount_unit(name: str | None, *, default_unit: str = "") -> tuple[str, str]:
    text = norm_text(name).replace(",", "")
    if not text:
        return "", ""

    candidates: list[tuple[str, str]] = []
    unit_pattern = r"uc|nc|diamonds?|gems?|coins?|tokens?|crystals?|stars?|beans?|coupons?|robux|vp|rp|usd"
    bonus_candidates: list[tuple[str, str]] = []
    for match in re.finditer(rf"(\d+(?:\.\d+)?)(?:\s*\+\s*|\s+)\d+(?:\.\d+)?\s*({unit_pattern})(?:\b|$)", text):
        amount = _money_amount(match.group(1))
        unit = _UNIT_ALIASES.get(match.group(2).lower(), "")
        if amount and unit:
            bonus_candidates.append((amount, unit))
    if bonus_candidates:
        bonus_candidates.sort(key=lambda row: _UNIT_PRIORITY.index(row[1]) if row[1] in _UNIT_PRIORITY else 999)
        return bonus_candidates[0]
    for match in re.finditer(rf"(\d+(?:\.\d+)?)\s*({unit_pattern})(?:\b|$)", text):
        amount = _money_amount(match.group(1))
        unit = _UNIT_ALIASES.get(match.group(2).lower(), "")
        if amount and unit:
            candidates.append((amount, unit))
    for match in re.finditer(r"\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*\$", text):
        amount = _money_amount(match.group(1) or match.group(2) or "")
        if amount:
            candidates.append((amount, "usd"))

    if not candidates:
        # Don't force the default currency unit onto products that aren't a bare currency
        # amount. e.g. "Prime (1 Month)" or "Weekly Deal Pack 1" must NOT become "1 uc"
        # (which collides with other products and wrongly merges them). These get an empty
        # key and stay distinct products (matched by source_key, fulfilled on their own).
        if re.search(
            r"\b(month|months|week|weekly|year|years|day|days|prime|pass|passes|membership|"
            r"subscription|sub|pack|packs|bundle|deal|deals|season|tier|combo|gift)\b",
            text,
        ):
            return "", ""
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        amount = _money_amount(match.group(1)) if match else ""
        if not amount:
            return "", ""
        # "G Coins" is a distinct currency — don't fold it into the family's UC default
        # (so "PUBG G Coins - 100" -> 100:gcoin, never collides with 100:uc).
        if re.search(r"\bg\s*coins?\b", text):
            return amount, "gcoin"
        default = _UNIT_ALIASES.get(norm_text(default_unit), "")
        return (amount, default) if default else ("", "")

    candidates.sort(key=lambda row: _UNIT_PRIORITY.index(row[1]) if row[1] in _UNIT_PRIORITY else 999)
    return candidates[0]


def offer_compare_key(
    *,
    family_key: str | None,
    region: str | None,
    offer_name: str | None,
    default_unit: str = "",
) -> str:
    family = _slug(family_key or "")
    if not family:
        return ""
    amount, unit = _extract_amount_unit(offer_name, default_unit=default_unit)
    if not amount or not unit:
        return ""
    region_key = _slug(region or "global") or "global"
    return f"{family}:{region_key}:{amount}:{unit}"


def manual_feature_compare_key(category_name: str | None, product_name: str | None = None) -> str:
    info = manual_feature_info(category_name, product_name)
    if not info:
        return ""
    return offer_compare_key(
        family_key=info.get("family_key"),
        region=info.get("region") or "Global",
        offer_name=product_name or category_name or "",
    )


# In-game currencies that are NOT the game's main top-up currency and must live
# in their OWN catalog variant so customers never mistake them for it (Homam
# 2026-07-09: PUBG "G Coins" is a different currency than UC).
CURRENCY_SPLIT_SUBCATEGORIES: dict[str, str] = {"gcoin": "G Coins"}


def unit_subcategory(unit: str | None, default: str = "topup") -> str:
    """The catalog sub-category (variant) a game offer belongs to, by its
    compare_key unit: split currencies get their own named bucket, everything
    else keeps the provider grouping/default."""
    return CURRENCY_SPLIT_SUBCATEGORIES.get(str(unit or "").strip().lower(), str(default or "topup").strip() or "topup")


def game_default_unit(game_id: str | None, game_name: str | None = None) -> str:
    text = norm_text(f"{game_id or ''} {game_name or ''}")
    if "pubg" in text or "pubgm" in text:
        return "uc"
    if "newstate" in text or "new state" in text:
        return "nc"
    if "valorant" in text:
        return "vp"
    if "free fire" in text or "freefire" in text:
        return "diamond"
    return ""


def game_family_key(game_id: str | None, game_name: str | None = None) -> str:
    text = norm_text(f"{game_id or ''} {game_name or ''}")
    if "newstate" in text or "new state" in text:
        return "new_state"
    if "pubg" in text or "pubgm" in text:
        return "pubg"
    if "yalla_ludo" in text or "yalla ludo" in text:
        return "yalla_ludo"
    if "jawaker" in text:
        return "jawaker"
    if "roblox" in text:
        return "roblox"
    if "valorant" in text:
        return "valorant"
    if "free fire" in text or "freefire" in text:
        return "free_fire"
    return ""
