from __future__ import annotations

from datetime import UTC, datetime
from bson import ObjectId

from database.mongo import db


DEFAULT_EXCHANGE_RATE = 10500.0


def _default_payment_methods(exchange_rate: float) -> list[dict]:
    syp_per_credit = float(exchange_rate)
    return [
        {
            "code": "shamcash",
            "title": "ShamCash",
            "currency": "SYP",
            "currency_options": ["SYP", "USD"],
            "enabled": True,
            "per_credit": syp_per_credit,
            "target": "SET_SHAMCASH_ACCOUNT",
            "support": "@support",
            "instructions": (
                "أرسل المبلغ إلى حساب شام كاش التالي:\n\n"
                "{target}\n\n"
                "ثم أرسل لقطة شاشة تأكيد العملية.\n"
                "( {per_credit:.0f} {currency} = 1 Credit )"
            ),
        },
        {
            "code": "syriatel_cash",
            "title": "Syriatel Cash",
            "currency": "SYP",
            "currency_options": ["SYP"],
            "enabled": True,
            "per_credit": syp_per_credit,
            "target": "SET_SYRIATEL_ACCOUNT",
            "support": "@support",
            "instructions": (
                "أرسل المبلغ إلى حساب سيرياتيل كاش التالي (تحويل يدوي):\n\n"
                "{target}\n\n"
                "إذا واجهت مشكلة في الحد تواصل مع الدعم: {support}\n"
                "( {per_credit:.0f} {currency} = 1 Credit )\n"
                "ملاحظة: لا تُقبل عملية إرسال وحدات."
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
                "أرسل المبلغ إلى عنوان المحفظة التالي:\n\n"
                "{target}\n\n"
                "ملاحظة: التعامل فقط بعملة USDT عبر Bep20.\n"
                "( {per_credit:.2f} {currency} = 1 Credit )\n"
                "قد تستغرق العملية من 10 إلى 20 دقيقة لتأكيد الشبكة."
            ),
        },
        {
            "code": "manual_usd",
            "title": "Manual USD",
            "currency": "USD",
            "currency_options": ["USD"],
            "enabled": True,
            "per_credit": 1.0,
            "target": "SET_USD_ACCOUNT",
            "support": "@support",
            "instructions": (
                "أرسل المبلغ إلى الحساب التالي:\n\n"
                "{target}\n\n"
                "ثم أرسل إثبات الدفع.\n"
                "( {per_credit:.2f} {currency} = 1 Credit )"
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


async def get_reseller_rates(reseller_id: int):
    doc = await _get_settings_doc(reseller_id)
    if not doc:
        return {"core_commission": 0.05, "owner_fee": 0.10}
    return {
        "core_commission": float(doc.get("core_commission", 0.05)),
        "owner_fee": float(doc.get("owner_fee", 0.10)),
    }


async def update_reseller_rates(reseller_id: int, core_commission: float, owner_fee: float):
    await db.reseller_settings.update_one(
        {"reseller_id": int(reseller_id)},
        {"$set": {"core_commission": float(core_commission), "owner_fee": float(owner_fee)}},
        upsert=True,
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

    defaults_by_code = {x.get("code"): x for x in _default_payment_methods(rate)}
    normalized = []
    changed = False
    for m in methods:
        item = dict(m)
        code = item.get("code")
        fallback = defaults_by_code.get(code, {})

        if _looks_broken_text(item.get("instructions")):
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



