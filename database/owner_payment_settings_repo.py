from __future__ import annotations

from datetime import UTC, datetime

from database.mongo import db


DEFAULT_OWNER_EXCHANGE_RATE = 10500.0


def _default_owner_payment_methods(exchange_rate: float) -> list[dict]:
    syp_rate = float(exchange_rate)
    return [
        {
            "code": "owner_shamcash",
            "title": "ShamCash",
            "currency": "SYP",
            "currency_options": ["SYP", "USD"],
            "enabled": True,
            "per_credit": syp_rate,
            "target": "SET_OWNER_SHAMCASH_ACCOUNT",
            "support": "@support",
            "instructions": (
                "Send payment to:\n{target}\n\n"
                "Then send proof screenshot.\n"
                "Rate: {per_credit:.0f} {currency} = 1 credit"
            ),
        },
        {
            "code": "owner_syriatel_cash",
            "title": "Syriatel Cash",
            "currency": "SYP",
            "currency_options": ["SYP"],
            "enabled": True,
            "per_credit": syp_rate,
            "target": "SET_OWNER_SYRIATEL_ACCOUNT",
            "support": "@support",
            "instructions": (
                "Transfer manually to:\n{target}\n\n"
                "For support contact: {support}\n"
                "Rate: {per_credit:.0f} {currency} = 1 credit"
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
                "Send USDT (BEP20) to:\n{target}\n\n"
                "Then send proof screenshot.\n"
                "Rate: {per_credit:.2f} {currency} = 1 credit"
            ),
        },
        {
            "code": "owner_manual_usd",
            "title": "Manual USD",
            "currency": "USD",
            "currency_options": ["USD"],
            "enabled": True,
            "per_credit": 1.0,
            "target": "SET_OWNER_USD_ACCOUNT",
            "support": "@support",
            "instructions": (
                "Send payment to:\n{target}\n\n"
                "Then send proof screenshot.\n"
                "Rate: {per_credit:.2f} {currency} = 1 credit"
            ),
        },
    ]


def _looks_broken_text(text: str | None) -> bool:
    value = str(text or "")
    if not value:
        return True
    return ("???" in value) or ("Ã" in value) or ("�" in value)


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

    defaults_by_code = {row.get("code"): row for row in _default_owner_payment_methods(rate)}
    normalized: list[dict] = []
    changed = False
    for method in methods:
        item = dict(method)
        code = str(item.get("code") or "")
        fallback = defaults_by_code.get(code, {})

        if _looks_broken_text(item.get("title")):
            item["title"] = fallback.get("title", code)
            changed = True
        if _looks_broken_text(item.get("instructions")):
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
        if currency == "SYP":
            if not item.get("per_credit") or float(item.get("per_credit")) <= 0:
                item["per_credit"] = float(rate)
                changed = True
        else:
            if not item.get("per_credit") or float(item.get("per_credit")) <= 0:
                item["per_credit"] = 1.0
                changed = True

        normalized.append(item)

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
    per_credit: float | None = None,
    currency: str | None = None,
    enabled: bool | None = None,
) -> bool:
    methods = await get_owner_payment_methods()
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
        if per_credit is not None and float(per_credit) > 0:
            method["per_credit"] = float(per_credit)
        if currency is not None:
            c = str(currency).upper().strip()
            if c in {"USD", "SYP"}:
                method["currency"] = c
                if c == "USD" and float(method.get("per_credit", 0) or 0) > 100:
                    method["per_credit"] = 1.0
                if c == "SYP" and float(method.get("per_credit", 0) or 0) < 100:
                    method["per_credit"] = float(await get_owner_exchange_rate())
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
    return str(method.get("instructions", "")).format(
        target=method.get("target", "-"),
        support=method.get("support", "@support"),
        per_credit=float(method.get("per_credit", 1.0)),
        currency=str(method.get("currency", "USD")).upper(),
    )
