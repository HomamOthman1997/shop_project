from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Callable

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from config import settings
from database.mongo import db
from database.owner_payment_settings_repo import get_owner_exchange_rate, get_owner_payment_methods
from database.recharge_repo import create_recharge_request
from database.support_tickets_repo import create_support_ticket, has_open_support_ticket, set_ticket_delivery
from database.support_topics_repo import get_support_target
from utils.bot_menu_context import extract_bot_id_from_token
from utils.recharge_ui import owner_reseller_topup_review_kb

logger = logging.getLogger("numbers_customer_flows")

SUPPORT_CATEGORIES = ("numbers", "user_balance")
MAX_RECHARGE_PROOF_BYTES = 6 * 1024 * 1024

TextFn = Callable[[str, str, str], str]


def default_text(lang: str, en: str, ar: str) -> str:
    return ar if str(lang or "").lower().startswith("ar") else en


def support_category_label(lang: str, category: str, *, text_fn: TextFn = default_text) -> str:
    key = str(category or "").strip().lower()
    labels = {
        "numbers": ("Numbers orders", "طلبات الأرقام"),
        "user_balance": ("Balance and payments", "الرصيد والدفع"),
    }
    en, ar = labels.get(key, (key.replace("_", " ").title(), key.replace("_", " ")))
    return text_fn(lang, en, ar)


def support_categories_payload(lang: str, *, text_fn: TextFn = default_text) -> list[dict[str, str]]:
    return [{"key": key, "label": support_category_label(lang, key, text_fn=text_fn)} for key in SUPPORT_CATEGORIES]


def numbers_source_bot_id() -> int:
    return int(extract_bot_id_from_token(getattr(settings, "bot_numbers_token", "")) or 0)


def support_bridge_token() -> str:
    return str(getattr(settings, "bot_admin_token", "") or "").strip()


def currency_label(amount: Any, currency: Any) -> str:
    code = str(currency or "USD").strip().upper() or "USD"
    try:
        value = float(amount or 0.0)
    except Exception:
        value = 0.0
    if code == "USD":
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return f"${text or '0'}"
    if value.is_integer():
        text = str(int(value))
    else:
        text = f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{text} {code}"


async def recharge_per_credit(method: dict[str, Any]) -> float:
    try:
        per_credit = float(method.get("per_credit") or 0.0)
    except Exception:
        per_credit = 0.0
    if per_credit > 0:
        return per_credit

    currency = str(method.get("currency") or "USD").strip().upper()
    if currency == "USD":
        return 1.0
    try:
        rate = await get_owner_exchange_rate(currency)
    except TypeError:
        rate = await get_owner_exchange_rate()
    try:
        value = float(rate)
    except Exception:
        value = 0.0
    return value if value > 0 else 1.0


def render_recharge_instructions(method: dict[str, Any], *, rate: float) -> str:
    raw_target = str(method.get("target") or method.get("address") or "").strip()
    currency = str(method.get("currency") or "USD").strip().upper() or "USD"
    instructions = str(method.get("instructions") or "").strip()
    try:
        instructions = instructions.format(
            target=raw_target or "-",
            support=method.get("support", "@support"),
            per_credit=rate,
            rate=rate,
            currency=currency,
        )
    except Exception:
        pass
    if raw_target:
        instructions = instructions.replace(raw_target, "").strip()
    return instructions


async def recharge_method_payload(
    method: dict[str, Any],
    lang: str,
    *,
    text_fn: TextFn = default_text,
) -> dict[str, Any]:
    currency = str(method.get("currency") or "USD").strip().upper() or "USD"
    rate = await recharge_per_credit(method)
    rate_label = text_fn(lang, f"1 credit = {currency_label(rate, currency)}", f"1 كريديت = {currency_label(rate, currency)}")
    return {
        "code": str(method.get("code") or method.get("title") or method.get("_id") or "").strip(),
        "title": str(method.get("title") or method.get("name") or method.get("code") or "").strip(),
        "currency": currency,
        "target": str(method.get("target") or method.get("address") or "").strip(),
        "support": str(method.get("support") or "@support").strip(),
        "per_credit": float(rate),
        "rate": float(rate),
        "rate_label": rate_label,
        "instructions": render_recharge_instructions(method, rate=rate),
    }


async def recharge_methods_payload(
    lang: str = "en",
    *,
    text_fn: TextFn = default_text,
    methods: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    method_rows = methods if methods is not None else await get_owner_payment_methods()
    for method in method_rows:
        if not isinstance(method, dict) or not bool(method.get("enabled", True)):
            continue
        payload = await recharge_method_payload(method, lang, text_fn=text_fn)
        if payload["code"]:
            rows.append(payload)
    return rows


def recharge_status_label(status: Any, lang: str, *, text_fn: TextFn = default_text) -> str:
    key = str(status or "pending").strip().lower()
    labels = {
        "pending": ("Pending review", "بانتظار المراجعة"),
        "processing": ("Processing", "قيد المعالجة"),
        "need_more_proof": ("Needs another proof", "يحتاج إثبات إضافي"),
        "accepted": ("Accepted", "تم القبول"),
        "rejected": ("Rejected", "مرفوض"),
    }
    en, ar = labels.get(key, (key.replace("_", " ").title(), key.replace("_", " ")))
    return text_fn(lang, en, ar)


def recharge_request_payload(
    req: dict[str, Any],
    lang: str,
    *,
    money_fn: Callable[[Any], str],
    compact_datetime_fn: Callable[[Any], str],
    text_fn: TextFn = default_text,
) -> dict[str, Any]:
    details = req.get("details") if isinstance(req.get("details"), dict) else {}
    paid_amount = details.get("paid_amount")
    paid_currency = str(details.get("paid_currency") or "USD").strip().upper() or "USD"
    return {
        "id": str(req.get("_id") or ""),
        "method": str(req.get("method") or "-"),
        "status": str(req.get("status") or "pending"),
        "status_label": recharge_status_label(req.get("status"), lang, text_fn=text_fn),
        "credits": float(req.get("approved_amount") or req.get("amount") or 0.0),
        "credits_label": money_fn(req.get("approved_amount") or req.get("amount") or 0.0),
        "paid_label": currency_label(paid_amount, paid_currency) if paid_amount is not None else "",
        "created_at": compact_datetime_fn(req.get("created_at")),
        "updated_at": compact_datetime_fn(req.get("updated_at")),
        "delivery_ok": bool((req.get("delivery") or {}).get("delivered")),
    }


async def recent_recharge_requests_payload(
    user_id: int,
    lang: str,
    *,
    limit: int = 6,
    money_fn: Callable[[Any], str],
    compact_datetime_fn: Callable[[Any], str],
    text_fn: TextFn = default_text,
) -> list[dict[str, Any]]:
    rows = await db.recharge_requests.find(
        {"user_id": int(user_id), "wallet_type": "user"},
        sort=[("created_at", -1)],
        limit=int(limit),
    ).to_list(int(limit))
    return [
        recharge_request_payload(row, lang, money_fn=money_fn, compact_datetime_fn=compact_datetime_fn, text_fn=text_fn)
        for row in rows
    ]


def _auth_profile(auth: dict[str, Any], user_doc: dict[str, Any] | None = None) -> dict[str, str]:
    tg_user = auth.get("user") if isinstance(auth.get("user"), dict) else {}
    username = str((user_doc or {}).get("username") or tg_user.get("username") or "").strip()
    first_name = str(tg_user.get("first_name") or "").strip()
    last_name = str(tg_user.get("last_name") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part).strip()
    if not full_name:
        full_name = str((user_doc or {}).get("full_name") or "").strip()
    return {"username": username, "full_name": full_name}


def recharge_review_caption(
    *,
    request_id: str,
    auth: dict[str, Any],
    user_doc: dict[str, Any] | None,
    req: dict[str, Any],
    method: dict[str, Any],
    source_label: str,
) -> str:
    profile = _auth_profile(auth, user_doc)
    username = f"@{profile['username']}" if profile.get("username") else "-"
    full_name = profile.get("full_name") or "-"
    details = req.get("details") if isinstance(req.get("details"), dict) else {}
    return (
        "Manual Payment Request\n\n"
        f"Request ID: {request_id}\n"
        f"User ID: {int(auth['user_id'])}\n"
        f"Username: {username}\n"
        f"Full name: {full_name}\n"
        f"Source: {source_label}\n"
        f"Method: {method.get('title') or method.get('code') or req.get('method') or '-'}\n"
        f"Paid Amount: {float(details.get('paid_amount') or 0.0):.4f} {details.get('paid_currency') or 'USD'}\n"
        f"Credits Unit: $ credits\n"
        f"Credited To User: {float(req.get('amount') or 0.0):.4f}\n"
        f"Created At: {req.get('created_at')}"
    )


async def notify_recharge_review(
    *,
    auth: dict[str, Any],
    user_doc: dict[str, Any],
    req: dict[str, Any],
    method: dict[str, Any],
    proof_bytes: bytes,
    proof_filename: str,
    proof_content_type: str,
    source_label: str,
) -> tuple[bool, str, int | None, int | None, int | None]:
    token = support_bridge_token()
    target = await db.system_settings.find_one({"_id": "owner_notifications"}) or {}
    chat_id = target.get("chat_id")
    if not token or not isinstance(chat_id, int):
        return False, "owner_notifications_not_configured", None, None, None

    thread_id = target.get("message_thread_id")
    kwargs: dict[str, Any] = {
        "chat_id": int(chat_id),
        "reply_markup": owner_reseller_topup_review_kb(str(req.get("_id"))),
    }
    if thread_id is not None:
        kwargs["message_thread_id"] = int(thread_id)

    caption = recharge_review_caption(
        request_id=str(req.get("_id")),
        auth=auth,
        user_doc=user_doc,
        req=req,
        method=method,
        source_label=source_label,
    )
    bot = Bot(token=token)
    try:
        upload = BufferedInputFile(proof_bytes, filename=proof_filename or "recharge-proof.jpg")
        if str(proof_content_type or "").lower().startswith("image/"):
            try:
                sent = await bot.send_photo(photo=upload, caption=caption, **kwargs)
            except Exception:
                upload = BufferedInputFile(proof_bytes, filename=proof_filename or "recharge-proof.jpg")
                sent = await bot.send_document(document=upload, caption=caption, **kwargs)
        else:
            sent = await bot.send_document(document=upload, caption=caption, **kwargs)
        return (
            True,
            "owner_topic",
            int(getattr(sent, "message_id", 0) or 0),
            int(chat_id),
            int(thread_id) if thread_id is not None else None,
        )
    except Exception as exc:
        logger.exception("numbers recharge review delivery failed request=%s", req.get("_id"))
        return False, f"owner_topic_send_failed:{exc}", None, None, None
    finally:
        await bot.session.close()


async def submit_recharge_request(
    *,
    auth: dict[str, Any],
    user_doc: dict[str, Any],
    lang: str,
    fields: dict[str, str],
    proof_bytes: bytes,
    proof_filename: str,
    proof_content_type: str,
    source: str,
    source_label: str,
    text_fn: TextFn = default_text,
    money_fn: Callable[[Any], str],
    compact_datetime_fn: Callable[[Any], str],
) -> dict[str, Any]:
    method_code = str(fields.get("method_code") or "").strip()
    if not method_code:
        return {"ok": False, "code": "missing_method", "message": text_fn(lang, "Choose a payment method.", "اختر طريقة دفع.")}

    method_rows = [row for row in await get_owner_payment_methods() if bool(row.get("enabled", True))]
    method = next((row for row in method_rows if str(row.get("code") or "").strip() == method_code), None)
    if not method:
        return {
            "ok": False,
            "code": "invalid_method",
            "message": text_fn(lang, "Choose a valid payment method.", "اختر طريقة دفع صحيحة."),
        }

    if not proof_bytes:
        return {"ok": False, "code": "missing_proof", "message": text_fn(lang, "Upload the payment proof image.", "ارفع صورة إثبات الدفع.")}

    try:
        paid_amount = float(str(fields.get("paid_amount") or "").replace(",", "."))
    except Exception:
        return {"ok": False, "code": "invalid_amount", "message": text_fn(lang, "Enter a valid paid amount.", "اكتب مبلغ الدفع بشكل صحيح.")}

    if paid_amount <= 0:
        return {
            "ok": False,
            "code": "invalid_amount",
            "message": text_fn(lang, "Paid amount must be greater than zero.", "مبلغ الدفع يجب أن يكون أكبر من صفر."),
        }

    rate = await recharge_per_credit(method)
    credits = round(float(paid_amount) / float(rate or 1.0), 6)
    user_id = int(auth["user_id"])
    req = await create_recharge_request(
        user_id=user_id,
        method=str(method.get("title") or method.get("code") or "payment"),
        amount=credits,
        proof_file_id="",
        reseller_id=user_id,
        details={
            "method_code": method.get("code"),
            "paid_amount": float(paid_amount),
            "paid_currency": str(method.get("currency") or "USD").upper(),
            "per_credit": float(rate),
            "credits": float(credits),
            "wallet_scope": "main_bot",
            "source": source,
            "source_bot_id": numbers_source_bot_id(),
            "proof_filename": proof_filename,
            "proof_content_type": proof_content_type,
            "proof_size_bytes": len(proof_bytes),
        },
        wallet_type="user",
    )

    delivered, route, msg_id, chat_id, thread_id = await notify_recharge_review(
        auth=auth,
        user_doc=user_doc,
        req=req,
        method=method,
        proof_bytes=proof_bytes,
        proof_filename=proof_filename,
        proof_content_type=proof_content_type,
        source_label=source_label,
    )
    await db.recharge_requests.update_one(
        {"_id": req["_id"]},
        {
            "$set": {
                "delivery.delivered": bool(delivered),
                "delivery.route": route,
                "delivery.message_id": msg_id,
                "delivery.chat_id": chat_id,
                "delivery.message_thread_id": thread_id,
                "delivery.updated_at": datetime.now(UTC),
            }
        },
    )
    refreshed = await db.recharge_requests.find_one({"_id": req["_id"]}) or req
    message = text_fn(lang, "Recharge request submitted. We will review it soon.", "تم إرسال طلب الشحن. سنراجعه قريباً.")
    if not delivered:
        message = text_fn(
            lang,
            "Recharge request was saved, but delivery to review queue failed. Support can still follow it.",
            "تم حفظ طلب الشحن، لكن تعذر إرساله لقائمة المراجعة. يمكن للدعم متابعته.",
        )
    return {
        "ok": True,
        "message": message,
        "request": recharge_request_payload(
            refreshed,
            lang,
            money_fn=money_fn,
            compact_datetime_fn=compact_datetime_fn,
            text_fn=text_fn,
        ),
        "delivery_ok": bool(delivered),
    }


def support_ticket_header_text(
    *,
    lang: str,
    ticket_no: int,
    category: str,
    user_id: int,
    username: str,
    full_name: str,
    source_label: str,
    text_fn: TextFn = default_text,
) -> str:
    username_display = f"@{username}" if username else "-"
    full_name_display = full_name or "-"
    category_label = support_category_label(lang, category, text_fn=text_fn)
    if str(lang or "").lower().startswith("ar"):
        return (
            f"تذكرة دعم #{int(ticket_no or 0)}\n"
            f"القسم: {category_label}\n"
            f"المصدر: {source_label}\n"
            f"User ID: {int(user_id)}\n"
            f"Username: {username_display}\n"
            f"Name: {full_name_display}"
        )
    return (
        f"Support ticket #{int(ticket_no or 0)}\n"
        f"Category: {category_label}\n"
        f"Source: {source_label}\n"
        f"User ID: {int(user_id)}\n"
        f"Username: {username_display}\n"
        f"Name: {full_name_display}"
    )


def support_ticket_action_markup(ticket_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Reply", callback_data=f"support:reply_ticket:{ticket_id}"),
                InlineKeyboardButton(text="Solved", callback_data=f"support:solve_ticket:{ticket_id}"),
            ]
        ]
    )


async def submit_support_ticket(
    *,
    auth: dict[str, Any],
    user_doc: dict[str, Any],
    lang: str,
    category: str,
    message: str,
    source_label: str,
    text_fn: TextFn = default_text,
) -> dict[str, Any]:
    category = str(category or "").strip().lower()
    if category not in SUPPORT_CATEGORIES:
        return {"ok": False, "code": "invalid_category", "message": text_fn(lang, "Choose a valid support category.", "اختر قسم دعم صحيح.")}

    message = " ".join(str(message or "").strip().split())
    if len(message) < 3:
        return {"ok": False, "code": "empty_message", "message": text_fn(lang, "Write a short message for support.", "اكتب رسالة قصيرة للدعم.")}
    if len(message) > 3500:
        message = message[:3500]

    source_bot_id = numbers_source_bot_id()
    bridge_token = support_bridge_token()
    target = await get_support_target(category)
    if source_bot_id <= 0 or not bridge_token or not target or not target.get("chat_id"):
        return {"ok": False, "code": "support_not_configured", "message": text_fn(lang, "Support is not configured yet.", "الدعم غير مضبوط حالياً.")}

    user_id = int(auth["user_id"])
    if await has_open_support_ticket(scope="platform", owner_id=None, user_id=user_id, category=category):
        return {
            "ok": False,
            "code": "open_ticket_exists",
            "message": text_fn(lang, "You already have an open support ticket in this category.", "عندك تذكرة دعم مفتوحة بهذا القسم."),
        }

    profile = _auth_profile(auth, user_doc)
    ticket = await create_support_ticket(
        scope="platform",
        owner_id=None,
        source_bot_id=source_bot_id,
        chat_id=user_id,
        user_id=user_id,
        username=profile["username"],
        full_name=profile["full_name"],
        category=category,
        payload_count=1,
    )
    kwargs: dict[str, Any] = {"chat_id": int(target["chat_id"])}
    if target.get("message_thread_id") is not None:
        kwargs["message_thread_id"] = int(target["message_thread_id"])

    ticket_id = str(ticket["_id"])
    bridge_bot = Bot(token=bridge_token)
    try:
        header = await bridge_bot.send_message(
            text=support_ticket_header_text(
                lang=lang,
                ticket_no=int(ticket.get("ticket_no") or 0),
                category=category,
                user_id=user_id,
                username=profile["username"],
                full_name=profile["full_name"],
                source_label=source_label,
                text_fn=text_fn,
            ),
            reply_markup=support_ticket_action_markup(ticket_id),
            **kwargs,
        )
        await bridge_bot.send_message(text=message, **kwargs)
        await set_ticket_delivery(
            ticket_id,
            target_chat_id=int(target["chat_id"]),
            target_thread_id=int(target["message_thread_id"]) if target.get("message_thread_id") is not None else None,
            header_message_id=int(header.message_id),
        )
    finally:
        await bridge_bot.session.close()

    return {
        "ok": True,
        "ticket_id": ticket_id,
        "ticket_no": int(ticket.get("ticket_no") or 0),
        "message": text_fn(lang, "Support ticket sent.", "تم إرسال تذكرة الدعم."),
    }
