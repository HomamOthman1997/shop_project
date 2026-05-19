from __future__ import annotations

from datetime import UTC, datetime
from bson import ObjectId

from database.mongo import db


DEFAULT_EXCHANGE_RATE = 10500.0


def _syriatel_cash_instructions() -> str:
    return (
        "حوّل المبلغ إلى رقم سيريتل كاش الظاهر أعلاه.\n"
        "بعد التحويل أرسل المبلغ الذي دفعته، ثم أرسل لقطة إثبات الدفع.\n"
        "إذا واجهت أي مشكلة تواصل مع الدعم: {support}"
    )


def _default_payment_methods(exchange_rate: float) -> list[dict]:
    syp_per_credit = float(exchange_rate)
    return [
        {
            "code": "syriatel_cash",
            "title": "Syriatel Cash",
            "currency": "SYP",
            "currency_options": ["SYP"],
            "enabled": True,
            "per_credit": syp_per_credit,
            "target": "SET_SYRIATEL_ACCOUNT",
            "support": "@support",
            "instructions": _syriatel_cash_instructions(),
        },
        {
            "code": "shamcash_syp",
            "title": "ShamCash (SYP)",
            "currency": "SYP",
            "currency_options": ["SYP"],
            "enabled": True,
            "per_credit": syp_per_credit,
            "target": "SET_SHAMCASH_SYP_ACCOUNT",
            "support": "@support",
            "instructions": (
                "حوّل المبلغ إلى حساب شام كاش الظاهر أعلاه.\n"
                "بعد التحويل أرسل المبلغ الذي دفعته، ثم أرسل لقطة إثبات الدفع."
            ),
        },
        {
            "code": "shamcash_usd",
            "title": "ShamCash ($)",
            "currency": "USD",
            "currency_options": ["USD"],
            "enabled": True,
            "per_credit": 1.0,
            "target": "SET_SHAMCASH_USD_ACCOUNT",
            "support": "@support",
            "instructions": (
                "حوّل المبلغ إلى حساب شام كاش الظاهر أعلاه.\n"
                "بعد التحويل أرسل المبلغ الذي دفعته، ثم أرسل لقطة إثبات الدفع."
            ),
        },
        {
            "code": "crypto_usdt",
            "title": "Crypto USDT",
            "currency": "USD",
            "currency_options": ["USD"],
            "enabled": True,
            "per_credit": 1.0,
            "target": "SET_USDT_BEP20_ADDRESS",
            "support": "@support",
            "instructions": (
                "أرسل USDT عبر شبكة BEP20 إلى عنوان المحفظة الظاهر أعلاه.\n"
                "بعد التحويل أرسل المبلغ الذي دفعته، ثم أرسل لقطة أو هاش إثبات الدفع."
            ),
        },
    ]




def _looks_broken_text(text: str | None) -> bool:
    s = str(text or "")
    if not s:
        return True
    if "???" in s or "Ã" in s or "�" in s:
        return True
    return False


def _is_legacy_syriatel_instructions(text: str | None) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    legacy_markers = (
        "خطوات شحن الرصيد عبر سيريتل كاش",
        "أدخل معرف العملية",
        "أدخل قيمة المبلغ المحوّل",
        "أرسل المبلغ إلى حساب سيرياتيل كاش التالي (تحويل يدوي):",
        "إذا واجهت مشكلة في الحد تواصل مع الدعم:",
        "ملاحظة: لا تُقبل عملية إرسال وحدات.",
        "Transfer manually to:",
        "For support contact:",
    )
    return any(marker in s for marker in legacy_markers)


def _is_legacy_payment_instructions(code: str, text: str | None) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    if code == "syriatel_cash" and _is_legacy_syriatel_instructions(s):
        return True
    markers_by_code = {
        "shamcash_syp": (
            "أرسل المبلغ إلى حساب شام كاش التالي:",
            "ثم أرسل لقطة شاشة تأكيد العملية.",
            "( {per_credit:.0f} {currency} = 1 Credit )",
        ),
        "shamcash_usd": (
            "أرسل المبلغ إلى حساب شام كاش التالي:",
            "ثم أرسل لقطة شاشة تأكيد العملية.",
            "( {per_credit:.0f} {currency} = 1 Credit )",
        ),
        "crypto_usdt": (
            "أرسل المبلغ إلى عنوان المحفظة التالي:",
            "ملاحظة: التعامل فقط بعملة USDT عبر Bep20.",
            "( {per_credit:.2f} {currency} = 1 Credit )",
        ),
    }
    return any(marker in s for marker in markers_by_code.get(code, ()))


async def _get_settings_doc(reseller_id: int) -> dict:
    return await db.reseller_settings.find_one({"reseller_id": int(reseller_id)}) or {}


async def add_recharge_address(reseller_id, address):
    await db.reseller_settings.update_one(
        {"reseller_id": reseller_id},
        {"$push": {"addresses": {"_id": ObjectId(), "address": address, "created_at": datetime.now(UTC)}}},
        upsert=True,
    )


async def get_recharge_addresses(reseller_id):
    doc = await _get_settings_doc(reseller_id)
    return doc.get("addresses", []) if doc else []


async def delete_recharge_address(reseller_id: int, address_id):
    if not isinstance(address_id, ObjectId):
        address_id = ObjectId(address_id)
    await db.reseller_settings.update_one(
        {"reseller_id": int(reseller_id)},
        {"$pull": {"addresses": {"_id": address_id}}},
    )


async def set_recharge_routing(reseller_id: int, chat_id: int, message_thread_id: int | None = None):
    await db.reseller_settings.update_one(
        {"reseller_id": int(reseller_id)},
        {
            "$set": {
                "recharge_routing.chat_id": int(chat_id),
                "recharge_routing.message_thread_id": int(message_thread_id) if message_thread_id is not None else None,
                "recharge_routing.updated_at": datetime.now(UTC),
            }
        },
        upsert=True,
    )


async def clear_recharge_routing(reseller_id: int):
    await db.reseller_settings.update_one(
        {"reseller_id": int(reseller_id)},
        {
            "$unset": {
                "recharge_routing.chat_id": "",
                "recharge_routing.message_thread_id": "",
            },
            "$set": {"recharge_routing.updated_at": datetime.now(UTC)},
        },
        upsert=True,
    )


async def get_recharge_routing(reseller_id: int):
    doc = await _get_settings_doc(reseller_id)
    routing = doc.get("recharge_routing") or {}
    chat_id = routing.get("chat_id")
    if chat_id is None:
        return None
    return {
        "chat_id": int(chat_id),
        "message_thread_id": routing.get("message_thread_id"),
    }


async def set_exchange_routing(reseller_id: int, chat_id: int, message_thread_id: int | None = None):
    await db.reseller_settings.update_one(
        {"reseller_id": int(reseller_id)},
        {
            "$set": {
                "exchange_routing.chat_id": int(chat_id),
                "exchange_routing.message_thread_id": int(message_thread_id) if message_thread_id is not None else None,
                "exchange_routing.updated_at": datetime.now(UTC),
            }
        },
        upsert=True,
    )


async def clear_exchange_routing(reseller_id: int):
    await db.reseller_settings.update_one(
        {"reseller_id": int(reseller_id)},
        {
            "$unset": {
                "exchange_routing.chat_id": "",
                "exchange_routing.message_thread_id": "",
            },
            "$set": {"exchange_routing.updated_at": datetime.now(UTC)},
        },
        upsert=True,
    )


async def get_exchange_routing(reseller_id: int):
    doc = await _get_settings_doc(reseller_id)
    routing = doc.get("exchange_routing") or {}
    chat_id = routing.get("chat_id")
    if chat_id is None:
        return None
    return {
        "chat_id": int(chat_id),
        "message_thread_id": routing.get("message_thread_id"),
    }


async def set_support_routing(reseller_id: int, category: str, chat_id: int, message_thread_id: int | None = None):
    cat = str(category or "").strip().lower()
    await db.reseller_settings.update_one(
        {"reseller_id": int(reseller_id)},
        {
            "$set": {
                f"support_routing.{cat}.chat_id": int(chat_id),
                f"support_routing.{cat}.message_thread_id": int(message_thread_id) if message_thread_id is not None else None,
                f"support_routing.{cat}.updated_at": datetime.now(UTC),
            }
        },
        upsert=True,
    )


async def get_support_routing(reseller_id: int, category: str):
    cat = str(category or "").strip().lower()
    doc = await _get_settings_doc(reseller_id)
    routing = ((doc.get("support_routing") or {}).get(cat)) or {}
    chat_id = routing.get("chat_id")
    if chat_id is None:
        return None
    return {
        "chat_id": int(chat_id),
        "message_thread_id": routing.get("message_thread_id"),
    }


async def get_all_support_routing(reseller_id: int) -> dict[str, dict]:
    doc = await _get_settings_doc(reseller_id)
    raw = doc.get("support_routing") or {}
    result: dict[str, dict] = {}
    for category in ("proxies", "numbers", "services", "user_balance"):
        row = raw.get(category) or {}
        if row.get("chat_id") is None:
            result[category] = {}
            continue
        result[category] = {
            "chat_id": int(row["chat_id"]),
            "message_thread_id": row.get("message_thread_id"),
        }
    return result


async def set_exchange_rate(reseller_id: int, usd_to_syp: float):
    now = datetime.now(UTC)
    await db.reseller_settings.update_one(
        {"reseller_id": int(reseller_id)},
        {
            "$set": {
                "exchange_rate.usd_to_syp": float(usd_to_syp),
                "exchange_rate.updated_at": now,
                "exchange_rate.last_reminder_date": None,
            }
        },
        upsert=True,
    )


async def get_exchange_rate(reseller_id: int) -> float:
    doc = await _get_settings_doc(reseller_id)
    rate_obj = doc.get("exchange_rate") or {}
    rate = rate_obj.get("usd_to_syp")
    return float(rate) if rate else DEFAULT_EXCHANGE_RATE


async def get_exchange_rate_meta(reseller_id: int) -> dict:
    doc = await _get_settings_doc(reseller_id)
    rate_obj = doc.get("exchange_rate") or {}
    value = rate_obj.get("usd_to_syp")
    return {
        "usd_to_syp": float(value) if value else DEFAULT_EXCHANGE_RATE,
        "updated_at": rate_obj.get("updated_at"),
        "last_reminder_date": rate_obj.get("last_reminder_date"),
    }


async def mark_exchange_rate_reminded_today(reseller_id: int):
    today = datetime.now(UTC).date().isoformat()
    await db.reseller_settings.update_one(
        {"reseller_id": int(reseller_id)},
        {"$set": {"exchange_rate.last_reminder_date": today}},
        upsert=True,
    )


async def get_payment_methods(reseller_id: int) -> list[dict]:
    doc = await _get_settings_doc(reseller_id)
    methods = doc.get("payment_methods")
    rate = await get_exchange_rate(reseller_id)

    if not methods:
        methods = _default_payment_methods(rate)
        await db.reseller_settings.update_one(
            {"reseller_id": int(reseller_id)},
            {"$set": {"payment_methods": methods}},
            upsert=True,
        )

    defaults = _default_payment_methods(rate)
    defaults_by_code = {x.get("code"): x for x in defaults}
    allowed_codes = set(defaults_by_code.keys())
    changed = False

    # One-time migration: legacy single shamcash -> shamcash_syp + shamcash_usd
    has_old_shamcash = any(str(x.get("code") or "") == "shamcash" for x in methods)
    has_new_shamcash = any(str(x.get("code") or "") in {"shamcash_syp", "shamcash_usd"} for x in methods)
    if has_old_shamcash and not has_new_shamcash:
        old = next((x for x in methods if str(x.get("code") or "") == "shamcash"), {})
        syp_target = str(old.get("target") or "SET_SHAMCASH_SYP_ACCOUNT")
        usd_target = syp_target
        old_cur = str(old.get("currency") or "").upper()
        if old_cur == "USD":
            usd_target = str(old.get("target") or "SET_SHAMCASH_USD_ACCOUNT")
            syp_target = usd_target

        migrated = [x for x in methods if str(x.get("code") or "") != "shamcash"]
        migrated.extend(
            [
                {
                    **defaults_by_code["shamcash_syp"],
                    "target": syp_target,
                    "enabled": bool(old.get("enabled", True)),
                },
                {
                    **defaults_by_code["shamcash_usd"],
                    "target": usd_target,
                    "enabled": bool(old.get("enabled", True)),
                },
            ]
        )
        methods = migrated
        changed = True

    normalized = []
    for m in methods:
        item = dict(m)
        code = str(item.get("code") or "")
        if code not in allowed_codes:
            changed = True
            continue
        fallback = defaults_by_code.get(code, {})

        if _looks_broken_text(item.get("instructions")) or _is_legacy_payment_instructions(code, item.get("instructions")):
            item["instructions"] = fallback.get("instructions", item.get("instructions", ""))
            changed = True
        if _looks_broken_text(item.get("title")):
            item["title"] = fallback.get("title", item.get("title", code))
            changed = True
        if "enabled" not in item:
            item["enabled"] = bool(fallback.get("enabled", True))
            changed = True
        if "currency_options" not in item:
            fallback_opts = fallback.get("currency_options") or [str(item.get("currency", "USD")).upper()]
            item["currency_options"] = [str(x).upper() for x in fallback_opts if str(x).strip()]
            changed = True

        if str(item.get("currency", "USD")).upper() == "SYP":
            if not item.get("per_credit") or float(item.get("per_credit")) <= 0:
                item["per_credit"] = float(rate)
                changed = True
        else:
            if not item.get("per_credit") or float(item.get("per_credit")) <= 0:
                item["per_credit"] = 1.0
                changed = True
        normalized.append(item)

    order_index = {code: idx for idx, code in enumerate([row.get("code") for row in defaults])}
    normalized.sort(key=lambda item: order_index.get(str(item.get("code") or ""), 999))

    if changed:
        await db.reseller_settings.update_one(
            {"reseller_id": int(reseller_id)},
            {"$set": {"payment_methods": normalized, "payment_methods_fixed_at": datetime.now(UTC)}},
            upsert=True,
        )

    return normalized


async def update_payment_method(
    reseller_id: int,
    method_code: str,
    *,
    target: str | None = None,
    instructions: str | None = None,
    title: str | None = None,
    support: str | None = None,
    per_credit: float | None = None,
    currency: str | None = None,
    enabled: bool | None = None,
):
    methods = await get_payment_methods(reseller_id)
    changed = False
    for m in methods:
        if m.get("code") == method_code:
            if target is not None:
                m["target"] = str(target)
            if instructions is not None:
                m["instructions"] = str(instructions)
            if title is not None:
                m["title"] = str(title)
            if support is not None:
                m["support"] = str(support)
            if per_credit is not None and float(per_credit) > 0:
                m["per_credit"] = float(per_credit)
            if currency is not None:
                c = str(currency).upper().strip()
                if c in {"USD", "SYP"}:
                    m["currency"] = c
                    # Keep rates sane when switching currency mode.
                    if c == "USD" and float(m.get("per_credit", 0) or 0) > 100:
                        m["per_credit"] = 1.0
                    if c == "SYP" and float(m.get("per_credit", 0) or 0) < 100:
                        m["per_credit"] = float(await get_exchange_rate(reseller_id))
            if enabled is not None:
                m["enabled"] = bool(enabled)
            changed = True
            break

    if not changed:
        return False

    await db.reseller_settings.update_one(
        {"reseller_id": int(reseller_id)},
        {"$set": {"payment_methods": methods, "payment_methods_updated_at": datetime.now(UTC)}},
        upsert=True,
    )
    return True


def render_method_instructions(method: dict) -> str:
    return str(method.get("instructions", "")).format(
        target=method.get("target", "-"),
        support=method.get("support", "@support"),
        per_credit=float(method.get("per_credit", 1.0)),
        currency=str(method.get("currency", "USD")).upper(),
    )



