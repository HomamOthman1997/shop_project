from __future__ import annotations

from datetime import UTC, datetime

from database.mongo import db


DEFAULT_OWNER_EXCHANGE_RATE = 10500.0


def _method_per_credit(currency: str, exchange_rate: float) -> float:
    return float(exchange_rate) if str(currency or "USD").upper() == "SYP" else 1.0


def _owner_syriatel_cash_instructions() -> str:
    return (
        "حوّل المبلغ إلى رقم سيريتل كاش الظاهر أعلاه.\n"
        "بعد التحويل أرسل المبلغ الذي دفعته، ثم أرسل لقطة إثبات الدفع.\n"
        "إذا واجهت أي مشكلة تواصل مع الدعم: {support}"
    )


def _default_owner_payment_methods(exchange_rate: float) -> list[dict]:
    syp_rate = float(exchange_rate)
    return [
        {
            "code": "owner_syriatel_cash",
            "title": "Syriatel Cash",
            "currency": "SYP",
            "currency_options": ["SYP"],
            "enabled": True,
            "per_credit": syp_rate,
            "target": "SET_OWNER_SYRIATEL_ACCOUNT",
            "support": "@support",
            "instructions": _owner_syriatel_cash_instructions(),
        },
        {
            "code": "owner_shamcash_syp",
            "title": "ShamCash (SYP)",
            "currency": "SYP",
            "currency_options": ["SYP"],
            "enabled": True,
            "per_credit": syp_rate,
            "target": "SET_OWNER_SHAMCASH_SYP_ACCOUNT",
            "support": "@support",
            "instructions": (
                "Send the payment to the ShamCash account shown above.\n"
                "After sending, enter the amount you paid, then upload the payment proof screenshot."
            ),
        },
        {
            "code": "owner_shamcash_usd",
            "title": "ShamCash ($)",
            "currency": "USD",
            "currency_options": ["USD"],
            "enabled": True,
            "per_credit": 1.0,
            "target": "SET_OWNER_SHAMCASH_USD_ACCOUNT",
            "support": "@support",
            "instructions": (
                "Send the payment to the ShamCash account shown above.\n"
                "After sending, enter the amount you paid, then upload the payment proof screenshot."
            ),
        },
        {
            "code": "owner_crypto_usdt",
            "title": "USDT (BEP20)",
            "currency": "USD",
            "currency_options": ["USD"],
            "enabled": True,
            "per_credit": 1.0,
            "target": "SET_OWNER_USDT_BEP20_ADDRESS",
            "support": "@support",
            "instructions": (
                "Send USDT over BEP20 to the wallet address shown above.\n"
                "After sending, enter the amount you paid, then upload the payment proof screenshot or transaction hash."
            ),
        },
    ]


def _looks_broken_text(text: str | None) -> bool:
    value = str(text or "")
    if not value:
        return True
    return ("???" in value) or ("Ã" in value) or ("�" in value)


def _is_legacy_owner_syriatel_instructions(text: str | None) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    legacy_markers = (
        "خطوات شحن الرصيد عبر سيريتل كاش",
        "أدخل معرف العملية",
        "أدخل قيمة المبلغ المحوّل",
        "Transfer manually to:",
        "For support contact:",
        "أرسل المبلغ إلى حساب سيرياتيل كاش التالي (تحويل يدوي):",
        "إذا واجهت مشكلة في الحد تواصل مع الدعم:",
        "ملاحظة: لا تُقبل عملية إرسال وحدات.",
    )
    return any(marker in s for marker in legacy_markers)


def _is_legacy_owner_payment_instructions(code: str, text: str | None) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    if code == "owner_syriatel_cash" and _is_legacy_owner_syriatel_instructions(s):
        return True
    markers_by_code = {
        "owner_shamcash_syp": ("Send payment to:", "Rate: {per_credit:.0f} {currency} = 1 credit"),
        "owner_shamcash_usd": ("Send payment to:", "Rate: {per_credit:.2f} {currency} = 1 credit"),
        "owner_crypto_usdt": ("Send USDT (BEP20) to:", "Rate: {per_credit:.2f} {currency} = 1 credit"),
    }
    return any(marker in s for marker in markers_by_code.get(code, ()))


async def _get_doc() -> dict:
    return await db.system_settings.find_one({"_id": "owner_payment_settings"}) or {}


async def get_owner_exchange_rate() -> float:
    doc = await _get_doc()
    value = (doc.get("exchange_rate") or {}).get("usd_to_syp")
    return float(value) if value else DEFAULT_OWNER_EXCHANGE_RATE


async def set_owner_exchange_rate(usd_to_syp: float) -> None:
    now = datetime.now(UTC)
    await db.system_settings.update_one(
        {"_id": "owner_payment_settings"},
        {
            "$set": {
                "exchange_rate.usd_to_syp": float(usd_to_syp),
                "exchange_rate.updated_at": now,
            }
        },
        upsert=True,
    )


async def get_owner_payment_methods() -> list[dict]:
    doc = await _get_doc()
    methods = doc.get("payment_methods")
    rate = await get_owner_exchange_rate()

    if not methods:
        methods = _default_owner_payment_methods(rate)
        await db.system_settings.update_one(
            {"_id": "owner_payment_settings"},
            {"$set": {"payment_methods": methods, "updated_at": datetime.now(UTC)}},
            upsert=True,
        )

    defaults = _default_owner_payment_methods(rate)
    defaults_by_code = {row.get("code"): row for row in defaults}
    allowed_codes = set(defaults_by_code.keys())
    changed = False

    # One-time migration: legacy single ShamCash method -> two methods (SYP + USD).
    has_old_shamcash = any(str(x.get("code") or "") == "owner_shamcash" for x in methods)
    has_new_shamcash = any(
        str(x.get("code") or "") in {"owner_shamcash_syp", "owner_shamcash_usd"} for x in methods
    )
    if has_old_shamcash and not has_new_shamcash:
        old = next((x for x in methods if str(x.get("code") or "") == "owner_shamcash"), {})
        target = str(old.get("target") or "").strip()
        if not target:
            target = "SET_OWNER_SHAMCASH_SYP_ACCOUNT"
        migrated = [x for x in methods if str(x.get("code") or "") != "owner_shamcash"]
        migrated.extend(
            [
                {
                    **defaults_by_code["owner_shamcash_syp"],
                    "target": target,
                    "enabled": bool(old.get("enabled", True)),
                },
                {
                    **defaults_by_code["owner_shamcash_usd"],
                    "target": target,
                    "enabled": bool(old.get("enabled", True)),
                },
            ]
        )
        methods = migrated
        changed = True

    normalized: list[dict] = []
    for method in methods:
        item = dict(method)
        code = str(item.get("code") or "")
        if code not in allowed_codes:
            changed = True
            continue
        fallback = defaults_by_code.get(code, {})

        if _looks_broken_text(item.get("title")):
            item["title"] = fallback.get("title", code)
            changed = True
        if _looks_broken_text(item.get("instructions")) or _is_legacy_owner_payment_instructions(code, item.get("instructions")):
            item["instructions"] = fallback.get("instructions", "")
            changed = True
        if "enabled" not in item:
            item["enabled"] = bool(fallback.get("enabled", True))
            changed = True
        if "currency_options" not in item:
            fallback_opts = fallback.get("currency_options") or [str(item.get("currency", "USD")).upper()]
            item["currency_options"] = [str(x).upper() for x in fallback_opts if str(x).strip()]
            changed = True

        currency = str(item.get("currency", "USD")).upper()
        normalized_per_credit = _method_per_credit(currency, rate)
        if float(item.get("per_credit") or 0.0) != float(normalized_per_credit):
            item["per_credit"] = float(normalized_per_credit)
            changed = True

        normalized.append(item)

    order_index = {code: idx for idx, code in enumerate([row.get("code") for row in defaults])}
    normalized.sort(key=lambda item: order_index.get(str(item.get("code") or ""), 999))

    if changed:
        await db.system_settings.update_one(
            {"_id": "owner_payment_settings"},
            {"$set": {"payment_methods": normalized, "updated_at": datetime.now(UTC)}},
            upsert=True,
        )

    return normalized


async def update_owner_payment_method(
    method_code: str,
    *,
    title: str | None = None,
    target: str | None = None,
    support: str | None = None,
    instructions: str | None = None,
    currency: str | None = None,
    enabled: bool | None = None,
) -> bool:
    methods = await get_owner_payment_methods()
    rate = await get_owner_exchange_rate()
    changed = False
    for method in methods:
        if str(method.get("code")) != str(method_code):
            continue
        if title is not None:
            method["title"] = str(title)
        if target is not None:
            method["target"] = str(target)
        if support is not None:
            method["support"] = str(support)
        if instructions is not None:
            method["instructions"] = str(instructions)
        if currency is not None:
            c = str(currency).upper().strip()
            if c in {"USD", "SYP"}:
                method["currency"] = c
        method["per_credit"] = _method_per_credit(str(method.get("currency", "USD")), rate)
        if enabled is not None:
            method["enabled"] = bool(enabled)
        changed = True
        break

    if not changed:
        return False

    await db.system_settings.update_one(
        {"_id": "owner_payment_settings"},
        {"$set": {"payment_methods": methods, "updated_at": datetime.now(UTC)}},
        upsert=True,
    )
    return True


def render_owner_method_instructions(method: dict) -> str:
    currency = str(method.get("currency", "USD")).upper()
    per_credit = float(method.get("per_credit", 1.0))
    return str(method.get("instructions", "")).format(
        target=method.get("target", "-"),
        support=method.get("support", "@support"),
        per_credit=per_credit,
        currency=currency,
    )
