from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


TWOPLACES = Decimal("0.01")
WARRANTY_MONTHS = 2
MANUAL_FULFILLMENT_PROVIDER = "lona_cards"
MANUAL_CATEGORY_PREFIX = "lona_"


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _money(value: Any) -> Decimal:
    amount = _dec(value)
    if amount < 0:
        amount = Decimal("0")
    return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _norm(text: str | None) -> str:
    raw = str(text or "").strip().lower()
    raw = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", raw)
    return " ".join(raw.split())


def _fmt_amount(amount: Any) -> str:
    value = _dec(amount).normalize()
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _pct_text(rate: Any) -> str:
    value = _dec(rate).normalize()
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"


def _product_id(category_id: str, suffix: str) -> str:
    safe = re.sub(r"[^a-z0-9_]+", "_", str(suffix).strip().lower()).strip("_")
    return f"{category_id}_{safe or 'item'}"


def _fixed(values: list[int], rate: int) -> dict[str, Any]:
    return {"values": [Decimal(str(v)) for v in values], "rate": Decimal(str(rate))}


PRICEBOOK: list[dict[str, Any]] = [
    {
        "id": "lona_itunes",
        "name": "iTunes",
        "aliases": ("itunes", "apple"),
        "fixed": [
            _fixed([10, 15, 20], 88),
            _fixed([25, 30, 40, 50, 100], 87),
            _fixed([2, 3, 4, 5], 85),
            _fixed([150, 200, 300, 400, 500], 80),
        ],
        "mixed_rate": Decimal("80"),
    },
    {
        "id": "lona_amazon_us",
        "name": "Amazon US",
        "aliases": ("amazon us", "amazon usa", "amazon united states"),
        "fixed": [
            _fixed([5], 69),
            _fixed([3, 10, 15], 70),
            _fixed([20, 25], 77),
            _fixed([30, 40, 50, 100], 81),
        ],
        "mixed_rate": Decimal("77"),
        "mixed_max": Decimal("99"),
    },
    {
        "id": "lona_amazon_uk",
        "name": "Amazon UK",
        "aliases": ("amazon uk", "amazon united kingdom"),
        "fixed": [_fixed([10, 15, 25, 30, 50, 100], 102), _fixed([5], 93)],
        "mixed_rate": Decimal("86"),
    },
    {
        "id": "lona_amazon_de",
        "name": "Amazon DE",
        "aliases": ("amazon de", "amazon germany", "amazon german", "amazon الماني", "امازون الماني"),
        "fixed": [_fixed([10, 15, 20, 25, 50], 91), _fixed([5], 82)],
        "mixed_rate": Decimal("80"),
    },
    {
        "id": "lona_amazon_fr_it_es",
        "name": "Amazon FR / IT / Spain",
        "aliases": ("amazon fr", "amazon france", "amazon it", "amazon italy", "amazon spain", "amazon es"),
        "fixed": [_fixed([10, 15, 20, 25, 50], 90)],
    },
    {
        "id": "lona_uber_uk",
        "name": "Uber UK",
        "aliases": ("uber uk",),
        "amount_rate": Decimal("96"),
        "amount_min": Decimal("1"),
    },
    {
        "id": "lona_uber_us",
        "name": "Uber US",
        "aliases": ("uber us", "uber usa"),
        "amount_rate": Decimal("74"),
        "amount_min": Decimal("1"),
    },
    {
        "id": "lona_walmart",
        "name": "Walmart",
        "aliases": ("walmart",),
        "fixed": [_fixed([55], 70)],
        "amount_rate": Decimal("73"),
        "amount_min": Decimal("1"),
        "amount_multiple_of_5": True,
        "stopped_values": [Decimal("5"), Decimal("10"), Decimal("15")],
    },
    {
        "id": "lona_nintendo",
        "name": "Nintendo",
        "aliases": ("nintendo",),
        "amount_rate": Decimal("76"),
        "amount_min": Decimal("1"),
    },
    {
        "id": "lona_razer_us",
        "name": "Razer US",
        "aliases": ("razer us", "razer usa"),
        "amount_rate": Decimal("83"),
        "amount_min": Decimal("1"),
    },
    {
        "id": "lona_razer_global",
        "name": "Razer Global",
        "aliases": ("razer global",),
        "amount_rate": Decimal("83"),
        "amount_min": Decimal("1"),
    },
    {
        "id": "lona_steam_usa",
        "name": "Steam USA",
        "aliases": ("steam usa", "steam us", "steam"),
        "fixed": [_fixed([10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 100], 88)],
    },
    {
        "id": "lona_canada",
        "name": "Canada Cards",
        "aliases": ("canada", "canada cards"),
        "fixed": [_fixed([10, 20], 58)],
    },
    {
        "id": "lona_playstation",
        "name": "PlayStation",
        "aliases": ("playstation", "psn"),
        "fixed": [_fixed([5, 10, 15, 25, 30, 50, 75, 100], 80)],
    },
    {
        "id": "lona_starbucks",
        "name": "Starbucks",
        "aliases": ("starbucks",),
        "amount_rate": Decimal("51"),
        "amount_min": Decimal("1"),
    },
    {
        "id": "lona_visa_tremendous",
        "name": "Visa Tremendous",
        "aliases": ("visa tremendous", "tremendous", "فيزا ترمندوز"),
        "amount_rate": Decimal("79"),
        "amount_min": Decimal("5"),
    },
]


_RULE_BY_ID = {str(rule["id"]): rule for rule in PRICEBOOK}


def is_lona_category_id(category_id: str | None) -> bool:
    return str(category_id or "").strip() in _RULE_BY_ID


def _fixed_entries(rule: dict[str, Any]) -> list[tuple[Decimal, Decimal]]:
    rows: list[tuple[Decimal, Decimal]] = []
    for group in list(rule.get("fixed") or []):
        rate = _dec(group.get("rate"))
        for value in list(group.get("values") or []):
            rows.append((_money(value), rate))
    rows.sort(key=lambda item: item[0])
    return rows


def fixed_values_for_rule(rule: dict[str, Any]) -> set[Decimal]:
    return {value for value, _rate in _fixed_entries(rule)}


def _collapsed_fixed_amount_meta(rule: dict[str, Any]) -> dict[str, Any] | None:
    entries = _fixed_entries(rule)
    if len(entries) < 2:
        return None
    if _dec(rule.get("mixed_rate")) > 0 or _dec(rule.get("amount_rate")) > 0:
        return None
    rates = {rate for _value, rate in entries}
    if len(rates) != 1:
        return None
    values = [value for value, _rate in entries]
    return {
        "rate": next(iter(rates)),
        "min": min(values),
        "max": max(values),
        "multiple_of_5": all(_is_multiple_of_five(value) for value in values),
    }


def lona_categories() -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []
    for rule in PRICEBOOK:
        categories.append(
            {
                "id": str(rule["id"]),
                "name": str(rule["name"]),
                "clean_name": str(rule["name"]),
                "count": len(lona_products_for_category(str(rule["id"]))),
                "service_key": "store_cards",
                "raw": {"source": MANUAL_FULFILLMENT_PROVIDER},
                "lona_manual": True,
            }
        )
    return categories


def lona_products_for_category(category_id: str) -> list[dict[str, Any]]:
    rule = _RULE_BY_ID.get(str(category_id or "").strip())
    if not rule:
        return []
    products: list[dict[str, Any]] = []
    collapsed = _collapsed_fixed_amount_meta(rule)
    if collapsed:
        rate = _dec(collapsed.get("rate"))
        name = f"{rule['name']} Custom Amount"
        products.append(
            {
                "id": _product_id(str(rule["id"]), "amount"),
                "name": name,
                "clean_name": name,
                "price": 0.0,
                "stock": 1,
                "lona_manual": True,
                "manual_card": {
                    "kind": "amount",
                    "category_id": str(rule["id"]),
                    "rate_percent": float(rate),
                    "warranty_months": WARRANTY_MONTHS,
                    "amount_min": float(_money(collapsed.get("min"))),
                    "amount_max": float(_money(collapsed.get("max"))),
                    "amount_multiple_of_5": bool(collapsed.get("multiple_of_5")),
                    "collapse_fixed_values": True,
                },
            }
        )
    else:
        for value, rate in _fixed_entries(rule):
            name = f"{rule['name']} ${_fmt_amount(value)}"
            products.append(
                {
                    "id": _product_id(str(rule["id"]), _fmt_amount(value)),
                    "name": name,
                    "clean_name": name,
                    "price": float(_money(value * rate / Decimal("100"))),
                    "stock": 1,
                    "lona_manual": True,
                    "manual_card": {
                        "kind": "fixed",
                        "category_id": str(rule["id"]),
                        "face_value": float(value),
                        "rate_percent": float(rate),
                        "warranty_months": WARRANTY_MONTHS,
                    },
                }
            )
    if _dec(rule.get("mixed_rate")) > 0:
        rate = _dec(rule.get("mixed_rate"))
        name = f"{rule['name']} Mixed"
        products.append(
            {
                "id": _product_id(str(rule["id"]), "mixed"),
                "name": name,
                "clean_name": name,
                "price": 0.0,
                "stock": 1,
                "lona_manual": True,
                "manual_card": {
                    "kind": "mixed",
                    "category_id": str(rule["id"]),
                    "rate_percent": float(rate),
                    "warranty_months": WARRANTY_MONTHS,
                },
            }
        )
    if _dec(rule.get("amount_rate")) > 0:
        rate = _dec(rule.get("amount_rate"))
        name = f"{rule['name']} Custom Amount"
        products.append(
            {
                "id": _product_id(str(rule["id"]), "amount"),
                "name": name,
                "clean_name": name,
                "price": 0.0,
                "stock": 1,
                "lona_manual": True,
                "manual_card": {
                    "kind": "amount",
                    "category_id": str(rule["id"]),
                    "rate_percent": float(rate),
                    "warranty_months": WARRANTY_MONTHS,
                    "amount_min": float(_money(rule.get("amount_min") or 1)),
                    "amount_max": float(_money(rule.get("amount_max") or 0)),
                    "amount_multiple_of_5": bool(rule.get("amount_multiple_of_5")),
                },
            }
        )
    return products


def find_lona_product(category_id: str, product_id: str) -> dict[str, Any] | None:
    for product in lona_products_for_category(category_id):
        if str(product.get("id") or "").strip() == str(product_id or "").strip():
            return product
    return None


def is_lona_managed_category_name(name: str | None) -> bool:
    n = _norm(name)
    if not n:
        return False
    for rule in PRICEBOOK:
        aliases = [str(rule.get("name") or ""), *list(rule.get("aliases") or [])]
        for alias in aliases:
            a = _norm(alias)
            if a and (a == n or a in n or n in a):
                return True
    return False


def parse_face_value(text: str | None) -> Decimal | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = raw.replace("$", "")
    if "," in raw and "." not in raw:
        comma_decimal = re.search(r",\d{1,2}(?!\d)", raw)
        raw = raw.replace(",", "." if comma_decimal else "")
    else:
        raw = raw.replace(",", "")
    match = re.search(r"\d+(?:\.\d{1,2})?", raw)
    if not match:
        return None
    amount = _money(match.group(0))
    return amount if amount > 0 else None


def _is_multiple_of_five(value: Decimal) -> bool:
    if value <= 0:
        return False
    return (value % Decimal("5")) == 0


def validate_lona_amount(category_id: str, product_id: str, amount: Decimal) -> tuple[bool, str]:
    rule = _RULE_BY_ID.get(str(category_id or "").strip())
    product = find_lona_product(category_id, product_id)
    if not rule or not product:
        return False, "not_found"
    meta = dict(product.get("manual_card") or {})
    kind = str(meta.get("kind") or "")
    amount = _money(amount)
    if amount <= 0:
        return False, "invalid_amount"
    fixed_values = fixed_values_for_rule(rule)
    stopped_values = {_money(v) for v in list(rule.get("stopped_values") or [])}
    if amount in stopped_values:
        return False, "stopped"
    if kind == "mixed":
        if amount in fixed_values:
            return False, "fixed_value"
        mixed_max = _dec(rule.get("mixed_max"))
        if mixed_max > 0 and amount > mixed_max:
            return False, "above_max"
        if _is_multiple_of_five(amount):
            return False, "multiple_of_five"
    elif kind == "amount":
        min_value = _dec(meta.get("amount_min") or rule.get("amount_min")) or Decimal("1")
        max_value = _dec(meta.get("amount_max") or rule.get("amount_max"))
        if amount < min_value:
            return False, "below_min"
        if max_value > 0 and amount > max_value:
            return False, "above_max"
        if bool(meta.get("amount_multiple_of_5") or rule.get("amount_multiple_of_5")) and not _is_multiple_of_five(amount):
            return False, "not_multiple_of_five"
        if amount in fixed_values and not bool(meta.get("collapse_fixed_values")):
            return False, "fixed_value"
    elif kind == "fixed":
        expected = _money((product.get("manual_card") or {}).get("face_value"))
        if amount != expected:
            return False, "fixed_value"
    return True, ""


def quote_lona_product(category_id: str, product_id: str, amount: Decimal | None = None) -> dict[str, Any] | None:
    rule = _RULE_BY_ID.get(str(category_id or "").strip())
    product = find_lona_product(category_id, product_id)
    if not rule or not product:
        return None
    meta = dict(product.get("manual_card") or {})
    kind = str(meta.get("kind") or "")
    if kind == "fixed":
        face_value = _money(meta.get("face_value"))
    else:
        if amount is None:
            return None
        face_value = _money(amount)
        ok, _reason = validate_lona_amount(category_id, product_id, face_value)
        if not ok:
            return None
    rate = _dec(meta.get("rate_percent"))
    price = _money(face_value * rate / Decimal("100"))
    return {
        "category_id": str(rule["id"]),
        "category_name": str(rule["name"]),
        "product_id": str(product["id"]),
        "product_name": str(product["name"]),
        "kind": kind,
        "face_value": float(face_value),
        "rate_percent": float(rate),
        "rate_text": _pct_text(rate),
        "price": float(price),
        "warranty_months": WARRANTY_MONTHS,
    }


def lona_validation_message(reason: str, *, category_id: str, product_id: str, lang: str = "en") -> str:
    is_ar = str(lang or "").lower().startswith("ar")
    product = find_lona_product(category_id, product_id)
    rule = _RULE_BY_ID.get(str(category_id or "").strip()) or {}
    meta = dict((product or {}).get("manual_card") or {})
    if reason == "fixed_value":
        return (
            "هذه القيمة موجودة كفئة جاهزة. اخترها من القائمة بدل المكسر."
            if is_ar
            else "This value already has a direct option. Choose it from the list instead of Mixed."
        )
    if reason == "multiple_of_five":
        return (
            "المكسر يقبل فقط القيم غير الموجودة بالقائمة وغير المضاعفة للعدد 5."
            if is_ar
            else "Mixed accepts only values not listed and not divisible by 5."
        )
    if reason == "not_multiple_of_five":
        return (
            "هذه الخانة تقبل فئات صحيحة من مضاعفات 5 فقط."
            if is_ar
            else "This option accepts standard values divisible by 5 only."
        )
    if reason == "stopped":
        return "هذه الفئة متوقفة حالياً." if is_ar else "This denomination is currently stopped."
    if reason == "below_min":
        minimum = _fmt_amount(meta.get("amount_min") or rule.get("amount_min") or 1)
        return (f"أقل قيمة مسموحة هي ${minimum}." if is_ar else f"Minimum allowed value is ${minimum}.")
    if reason == "above_max":
        maximum = _fmt_amount(meta.get("amount_max") or rule.get("amount_max") or rule.get("mixed_max") or 0)
        return (f"أعلى قيمة مسموحة هنا هي ${maximum}." if is_ar else f"Maximum allowed value here is ${maximum}.")
    if str(meta.get("kind") or "") == "mixed":
        return (
            "أرسل قيمة رقمية للمكسر، ويجب ألا تكون من الفئات الجاهزة أو مضاعفات 5."
            if is_ar
            else "Send a numeric Mixed value; it must not be a listed value or divisible by 5."
        )
    return "أرسل قيمة رقمية صحيحة." if is_ar else "Send a valid numeric value."
