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

    if not family_key:
        return {}

    region = "Global"
    if re.search(r"\b(usa|us)\b", text):
        region = "USA"
    elif "saudi" in text or "ksa" in text:
        region = "KSA"
    elif "global" in text or family_key in {"pubg", "new_state", "yalla_ludo", "jawaker"}:
        region = "Global"

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
    unit_pattern = r"uc|nc|diamonds?|gems?|coins?|tokens?|robux|vp|rp|usd"
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
        default = _UNIT_ALIASES.get(norm_text(default_unit), "")
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        amount = _money_amount(match.group(1)) if match else ""
        return (amount, default) if amount and default else ("", "")

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


def game_default_unit(game_id: str | None, game_name: str | None = None) -> str:
    text = norm_text(f"{game_id or ''} {game_name or ''}")
    if "pubg" in text or "pubgm" in text:
        return "uc"
    if "newstate" in text or "new state" in text:
        return "nc"
    if "valorant" in text:
        return "vp"
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
    return ""
