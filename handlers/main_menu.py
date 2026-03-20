from datetime import UTC, datetime, timedelta
from html import escape

from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from database.bots_repo import get_reseller_id_for_bot
from database.financial_ledger import get_reseller_wallet_balance, get_user_wallet_balance
from database.mongo import db
from database.recharge_repo import create_recharge_request
from database.reseller_settings_repo import (
    get_exchange_rate_meta,
    get_exchange_routing,
    get_payment_methods,
    get_recharge_routing,
    mark_exchange_rate_reminded_today
)
from database.user_repo import get_user, get_user_reseller_for_bot, set_user_reseller_for_bot
from keyboards.balance_keyboard import balance_keyboard
from keyboards.main_menu_kb import main_menu
from keyboards.recharge_methods_keyboard import recharge_methods_keyboard
from keyboards.reseller_main_menu import reseller_main_menu
from services.numbers.handlers.core_numbers_buy import _handle_rental_exit_message_guard
from utils.permissions import is_reseller
from utils.recharge_ui import user_recharge_review_kb
from utils.translations import t

router = Router()


def _btn_values(key: str) -> set[str]:
    return {t("en", key), t("ar", key)}


def _is_btn(text: str | None, key: str) -> bool:
    return (text or "").strip() in _btn_values(key)


def _as_utc(dt: datetime | None) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _pay_nav_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "btn_back"))], [KeyboardButton(text=t(lang, "btn_cancel"))]],
        resize_keyboard=True,
    )


async def _hide_reply_keyboard(message: types.Message, lang: str) -> None:
    try:
        sent = await message.answer(
            t(lang, "keyboard_cleanup_placeholder"),
            reply_markup=types.ReplyKeyboardRemove(),
        )
        try:
            await sent.delete()
        except Exception:
            pass
    except Exception:
        pass


def _user_settings_doc(user_doc: dict | None) -> dict:
    raw = (user_doc or {}).get("user_settings")
    if isinstance(raw, dict):
        return raw
    return {}


def _language_label(language: str) -> str:
    return "Arabic" if str(language or "").strip().lower() == "ar" else "English"


def _user_settings_main_text(lang: str, user_doc: dict | None) -> str:
    user_lang = str((user_doc or {}).get("language") or "en").strip().lower()
    return (
        f"{t(lang, 'user_settings_title')}\n\n"
        f"{t(lang, 'user_settings_hint')}\n"
        f"- {t(lang, 'user_settings_lang')}: {_language_label(user_lang)}"
    )


def _user_settings_main_kb(lang: str, user_doc: dict | None) -> InlineKeyboardMarkup:
    user_lang = str((user_doc or {}).get("language") or "en").strip().lower()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{t(lang, 'user_settings_lang')}: {_language_label(user_lang)}",
                    callback_data="uset:lang",
                )
            ],
            [InlineKeyboardButton(text=t(lang, "user_settings_my_account"), callback_data="uset:profile")],
            [InlineKeyboardButton(text=t(lang, "user_settings_close"), callback_data="uset:close")],
        ]
    )


def _user_settings_lang_kb(lang: str, current_lang: str) -> InlineKeyboardMarkup:
    current = str(current_lang or "en").strip().lower()
    en_text = t(lang, "lang_en_button")
    ar_text = t(lang, "lang_ar_button")
    if current == "en":
        en_text = f"• {en_text}"
    else:
        ar_text = f"• {ar_text}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=en_text, callback_data="uset:langset:en")],
            [InlineKeyboardButton(text=ar_text, callback_data="uset:langset:ar")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="uset:open")],
        ]
    )


def _user_settings_back_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="uset:open")],
            [InlineKeyboardButton(text=t(lang, "user_settings_close"), callback_data="uset:close")],
        ]
    )


async def _update_user_settings(user_id: int, patch: dict) -> None:
    updates: dict[str, object] = {}
    for key, value in (patch or {}).items():
        updates[f"user_settings.{str(key)}"] = value
    if not updates:
        return
    await db.users.update_one({"telegram_id": int(user_id)}, {"$set": updates})


def _format_joined_date(value) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return "-"


async def _user_profile_settings_text(user_doc: dict | None, *, lang: str, bot_id: int, user_id: int) -> str:
    user_doc = user_doc or {}
    reseller_id = await get_user_reseller_for_bot(user_id, bot_id)
    if not reseller_id:
        reseller_id = user_doc.get("reseller_id")
    username_raw = str(user_doc.get("username") or "").strip()
    username_display = f"@{username_raw}" if username_raw else "-"
    return t(lang, "user_settings_profile_text").format(
        user_id=int(user_id),
        username=username_display,
        language=_language_label(str(user_doc.get("language") or "en")),
        reseller_id=str(reseller_id or "-"),
        joined_at=_format_joined_date(user_doc.get("created_at")),
    )


async def _open_user_settings_message(message: types.Message, user_doc: dict | None, lang: str):
    await message.answer(
        _user_settings_main_text(lang, user_doc),
        reply_markup=_user_settings_main_kb(lang, user_doc),
    )


async def _build_reseller_stats_text(reseller_id: int) -> str:
    rid = int(reseller_id)
    main_balance = await get_reseller_wallet_balance(rid, wallet_type="main")
    earnings_balance = await get_reseller_wallet_balance(rid, wallet_type="earnings")
    pending_recharge = await db.recharge_requests.count_documents({"reseller_id": rid, "status": "pending"})
    need_more_proof = await db.recharge_requests.count_documents({"reseller_id": rid, "status": "need_more_proof"})
    return (
        "Reseller Quick Stats\n\n"
        f"Reseller ID: {rid}\n"
        f"Main wallet: ${main_balance:.2f}\n"
        f"Earnings wallet: ${earnings_balance:.2f}\n"
        f"Pending recharge requests: {pending_recharge}\n"
        f"Need-more-proof requests: {need_more_proof}"
    )


async def _maybe_send_exchange_rate_reminder(bot, reseller_id: int):
    meta = await get_exchange_rate_meta(int(reseller_id))
    updated_at = _as_utc(meta.get("updated_at"))
    if not updated_at:
        return

    now = datetime.now(UTC)
    if now - updated_at < timedelta(hours=24):
        return

    today = now.date().isoformat()
    if str(meta.get("last_reminder_date") or "") == today:
        return

    routing = await get_exchange_routing(int(reseller_id))
    if not routing:
        routing = await get_recharge_routing(int(reseller_id))
    if not routing:
        return

    text = (
        "Daily Exchange Reminder\n\n"
        "Please update today's USD/SYP rate from Reseller Settings.\n"
        "Open: Reseller Settings -> Set Exchange Rate\n"
        f"Current stored rate: 1 USD = {float(meta.get('usd_to_syp', 0)):.2f} SYP\n"
        f"Last update (UTC): {updated_at}"
    )

    try:
        kwargs = {"chat_id": int(routing["chat_id"]), "text": text}
        if routing.get("message_thread_id") is not None:
            kwargs["message_thread_id"] = int(routing["message_thread_id"])
        await bot.send_message(**kwargs)
        await mark_exchange_rate_reminded_today(int(reseller_id))
    except Exception:
        return


async def _notify_recharge_request_to_reseller_topic(
    message: types.Message, req: dict, user_doc: dict | None
) -> tuple[bool, str, int | None, int | None, int | None]:
    reseller_id = req.get("reseller_id")
    if not reseller_id:
        return False, "missing_reseller_id", None, None, None

    await _maybe_send_exchange_rate_reminder(message.bot, int(reseller_id))

    username = "@" + user_doc.get("username") if user_doc and user_doc.get("username") else "-"
    full_name = " ".join(filter(None, [message.from_user.first_name, message.from_user.last_name])) or "-"
    request_id = str(req.get("_id", "-"))
    details = req.get("details") or {}
    paid_amount = float(details.get("paid_amount", 0))
    paid_currency = str(details.get("paid_currency", "USD"))
    credits = float(req.get("amount", 0))
    caption = (
        "Manual Payment Request\n\n"
        f"Request ID: {request_id}\n"
        f"User ID: {message.from_user.id}\n"
        f"Username: {username}\n"
        f"Name: {full_name}\n"
        f"Method: {req.get('method', '-')}\n"
        f"Paid: {paid_amount:.2f} {paid_currency}\n"
        f"Requested Credits: {credits:.4f}\n"
        "Credits Unit: USD credits\n"
        f"Approved: Pending\n"
        f"Credited To User: Pending\n"
        f"Created At: {req.get('created_at')}"
    )

    kb = user_recharge_review_kb(request_id)

    async def _send_to_target(chat_id: int, message_thread_id: int | None = None):
        prev = req.get("delivery") or {}
        prev_chat = prev.get("chat_id")
        prev_msg = prev.get("message_id")
        prev_thread = prev.get("message_thread_id")

        # avoid duplicate request cards: remove old delivery message first when possible
        if prev_chat is not None and prev_msg is not None:
            same_chat = int(prev_chat) == int(chat_id)
            same_thread = int(prev_thread) if prev_thread is not None else None
            now_thread = int(message_thread_id) if message_thread_id is not None else None
            if same_chat and same_thread == now_thread:
                try:
                    await message.bot.delete_message(chat_id=int(chat_id), message_id=int(prev_msg))
                except Exception:
                    pass

        kwargs = {"chat_id": int(chat_id), "reply_markup": kb}
        if message_thread_id is not None:
            kwargs["message_thread_id"] = int(message_thread_id)

        proof_file_id = req.get("proof_file_id")
        if proof_file_id:
            sent = await message.bot.send_photo(photo=proof_file_id, caption=caption, **kwargs)
        else:
            sent = await message.bot.send_message(text=caption, **kwargs)
        return sent

    errors: list[str] = []
    routing = await get_recharge_routing(int(reseller_id))
    if routing:
        try:
            sent = await _send_to_target(int(routing["chat_id"]), routing.get("message_thread_id"))
            return (
                True,
                "topic",
                int(getattr(sent, "message_id", 0) or 0),
                int(routing["chat_id"]),
                int(routing.get("message_thread_id")) if routing.get("message_thread_id") is not None else None,
            )
        except Exception as exc:
            errors.append(f"topic_send_failed:{exc}")

    try:
        sent = await _send_to_target(int(reseller_id), None)
        return True, "reseller_dm_fallback", int(getattr(sent, "message_id", 0) or 0), int(reseller_id), None
    except Exception as exc:
        errors.append(f"dm_send_failed:{exc}")

    return False, " | ".join(errors) if errors else "delivery_failed", None, None, None


class RechargeFlow(StatesGroup):
    waiting_method = State()
    waiting_amount = State()
    waiting_proof = State()


async def _resolve_user_reseller(user_doc: dict | None, *, bot_id: int, user_id: int) -> int | None:
    reseller_id = await get_user_reseller_for_bot(user_id, bot_id)
    if reseller_id:
        return int(reseller_id)

    inferred = await get_reseller_id_for_bot(bot_id)
    if inferred:
        await set_user_reseller_for_bot(user_id, bot_id, int(inferred))
        return int(inferred)
    return None


async def _return_main_menu(message: types.Message, user_id: int) -> None:
    bot_id = (await message.bot.get_me()).id
    user = await get_user(user_id)
    lang = user.get("language", "en") if user else "en"
    if await is_reseller(user_id, bot_id=bot_id):
        await _hide_reply_keyboard(message, lang)
        await message.answer(t(lang, "main_menu"), reply_markup=reseller_main_menu(lang))
    else:
        await message.answer(t(lang, "main_menu"), reply_markup=main_menu(lang))


@router.message(lambda msg: _is_btn(msg.text, "btn_balance") or _is_btn(msg.text, "btn_reseller_balance") or ((msg.text or "").startswith("/balance")))
async def balance_handler(message: types.Message):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    bot_id = (await message.bot.get_me()).id

    if await is_reseller(message.from_user.id, bot_id=bot_id):
        main_balance = await get_reseller_wallet_balance(message.from_user.id, wallet_type="main")
        earnings_balance = await get_reseller_wallet_balance(message.from_user.id, wallet_type="earnings")
        await message.answer(
            t(lang, "deposit_info").format(deposit=main_balance)
            + f"\nEarnings wallet: ${earnings_balance:.2f}."
            + "\nMain wallet covers provider/base costs."
            + "\nEarnings wallet is your accumulated profit before settlement."
        )
        return

    reseller_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)
    if not reseller_id:
        return await message.answer("No reseller link found for this account.")
    balance = await get_user_wallet_balance(message.from_user.id, int(reseller_id))
    text = t(lang, "balance_info").format(balance=balance)
    text += "\nThis is your available wallet balance for purchases on this reseller bot."
    await message.answer(text, reply_markup=balance_keyboard(lang))


@router.message(lambda msg: _is_btn(msg.text, "btn_add_balance"))
async def show_recharge_methods(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    bot_id = (await message.bot.get_me()).id
    reseller_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)

    if not reseller_id:
        return await message.answer("No reseller link found for this account.")

    methods = [m for m in (await get_payment_methods(int(reseller_id))) if bool(m.get("enabled", True))]
    if not methods:
        return await message.answer(
            "No payment methods are currently enabled by your reseller.\nPlease contact support."
        )
    view = [(m.get("title", m.get("code")), m.get("code")) for m in methods]
    await state.update_data(
        recharge_reseller_id=int(reseller_id),
        recharge_methods=methods,
        recharge_method_map={m.get("title", m.get("code")): m.get("code") for m in methods},
        recharge_lang=lang,
    )
    await state.set_state(RechargeFlow.waiting_method)
    await message.answer(t(lang, "recharge_choose_method"), reply_markup=recharge_methods_keyboard(view, lang=lang))


@router.message(RechargeFlow.waiting_method)
async def ask_recharge_amount(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    data = await state.get_data()

    if _is_btn(text, "btn_cancel") or _is_btn(text, "btn_back_main"):
        await state.clear()
        return await _return_main_menu(message, message.from_user.id)

    if _is_btn(text, "btn_balance"):
        await state.clear()
        user = await get_user(message.from_user.id)
        bot_id = (await message.bot.get_me()).id
        reseller_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)
        if not reseller_id:
            await state.clear()
            return await message.answer("No reseller link found for this account.")
        bal = await get_user_wallet_balance(message.from_user.id, int(reseller_id))
        return await message.answer(f"Your balance is ${bal:.2f}.", reply_markup=balance_keyboard((user or {}).get("language", "en")))

    if _is_btn(text, "btn_back"):
        await state.clear()
        return await _return_main_menu(message, message.from_user.id)

    methods = data.get("recharge_methods") or []
    title_to_code = data.get("recharge_method_map") or {}
    selected_code = title_to_code.get(text)
    selected = None
    for m in methods:
        if m.get("code") == selected_code:
            selected = m
            break

    if not selected:
        return await message.answer("Choose one payment method from keyboard.")

    raw_target = str(selected.get("target") or "").strip()
    target_lines = [line.strip() for line in raw_target.replace("\r", "\n").split("\n") if line.strip()]
    if not target_lines and raw_target:
        target_lines = [raw_target]
    targets_block = "\n".join(f"<code>{escape(line)}</code>" for line in target_lines) if target_lines else "<code>-</code>"

    rendered_instructions = str(selected.get("instructions") or "")
    try:
        rendered_instructions = rendered_instructions.format(
            target=raw_target or "-",
            support=selected.get("support", "@support"),
            per_credit=float(selected.get("per_credit", 1.0)),
            currency=str(selected.get("currency", "USD")).upper(),
        )
    except Exception:
        pass
    if raw_target:
        rendered_instructions = rendered_instructions.replace(raw_target, "").strip()

    instructions = (
        f"<b>{escape(str(selected.get('title') or selected.get('code') or 'Payment'))}</b>\n"
        f"Currency: <b>{escape(str(selected.get('currency', 'USD')).upper())}</b>\n"
        f"Rate: <b>{float(selected.get('per_credit', 1.0)):.4f} {escape(str(selected.get('currency', 'USD')).upper())}</b> = 1 credit\n\n"
        "Targets (copy each line separately):\n"
        f"{targets_block}\n\n"
        f"{escape(rendered_instructions)}"
    ).strip()

    await state.update_data(recharge_method=selected)
    await state.set_state(RechargeFlow.waiting_amount)
    flow_lang = data.get("recharge_lang", "en")
    await message.answer(instructions, reply_markup=_pay_nav_kb(flow_lang), parse_mode="HTML")
    await message.answer("Send amount now.")


@router.message(RechargeFlow.waiting_amount)
async def receive_recharge_amount(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    if _is_btn(raw, "btn_cancel") or _is_btn(raw, "btn_back_main"):
        await state.clear()
        return await _return_main_menu(message, message.from_user.id)
    if _is_btn(raw, "btn_balance"):
        await state.clear()
        user = await get_user(message.from_user.id)
        bot_id = (await message.bot.get_me()).id
        reseller_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)
        if not reseller_id:
            await state.clear()
            return await message.answer("No reseller link found for this account.")
        bal = await get_user_wallet_balance(message.from_user.id, int(reseller_id))
        return await message.answer(f"Your balance is ${bal:.2f}.", reply_markup=balance_keyboard((user or {}).get("language", "en")))

    if _is_btn(raw, "btn_back"):
        data = await state.get_data()
        methods = data.get("recharge_methods") or []
        view = [(m.get("title", m.get("code")), m.get("code")) for m in methods]
        await state.set_state(RechargeFlow.waiting_method)
        lang = (await state.get_data()).get("recharge_lang", "en")
        return await message.answer("Choose recharge method:", reply_markup=recharge_methods_keyboard(view, lang=lang))

    try:
        paid_amount = float(raw)
    except Exception:
        return await message.answer("Invalid amount. Send numeric value.")

    if paid_amount <= 0:
        return await message.answer("Amount must be greater than zero.")

    data = await state.get_data()
    method = data.get("recharge_method") or {}
    per_credit = float(method.get("per_credit", 1.0) or 1.0)
    if per_credit <= 0:
        per_credit = 1.0
    credits = paid_amount / per_credit

    await state.update_data(
        recharge_paid_amount=paid_amount,
        recharge_credits=float(round(credits, 6)),
    )
    await state.set_state(RechargeFlow.waiting_proof)
    flow_lang = data.get("recharge_lang", "en")
    await message.answer("Send payment proof screenshot now.", reply_markup=_pay_nav_kb(flow_lang))


@router.message(RechargeFlow.waiting_proof, lambda msg: msg.photo)
async def receive_recharge_proof(message: types.Message, state: FSMContext):
    data = await state.get_data()
    paid_amount = float(data.get("recharge_paid_amount") or 0)
    credits = float(data.get("recharge_credits") or 0)
    method = data.get("recharge_method") or {}
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"

    reseller_id = data.get("recharge_reseller_id")
    if not reseller_id:
        bot_id = (await message.bot.get_me()).id
        reseller_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)

    if not reseller_id:
        await state.clear()
        return await message.answer("Recharge failed: user is not linked to a reseller.")

    req = await create_recharge_request(
        user_id=message.from_user.id,
        method=method.get("title") or method.get("code") or "payment",
        amount=credits,
        proof_file_id=message.photo[-1].file_id,
        reseller_id=int(reseller_id),
        details={
            "method_code": method.get("code"),
            "paid_amount": paid_amount,
            "paid_currency": str(method.get("currency", "USD")).upper(),
            "per_credit": float(method.get("per_credit", 1.0)),
            "credits": credits,
        },
        wallet_type="user",
    )
    delivered, route, msg_id, chat_id, thread_id = await _notify_recharge_request_to_reseller_topic(message, req, user)
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
    await state.clear()
    if delivered:
        if req.get("_reused"):
            await message.answer("Recharge request updated and re-submitted to reseller review.", reply_markup=types.ReplyKeyboardRemove())
        else:
            await message.answer(t(lang, "recharge_submitted"), reply_markup=types.ReplyKeyboardRemove())
    else:
        await message.answer(
            "Recharge request saved, but delivery to reseller queue failed. "
            "Your reseller can still process it from pending requests.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
    await _return_main_menu(message, message.from_user.id)



@router.message(RechargeFlow.waiting_proof)
async def receive_recharge_proof_text(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    data = await state.get_data()
    flow_lang = data.get("recharge_lang", "en")

    if _is_btn(raw, "btn_cancel") or _is_btn(raw, "btn_back_main"):
        await state.clear()
        return await _return_main_menu(message, message.from_user.id)

    if _is_btn(raw, "btn_balance"):
        await state.clear()
        user = await get_user(message.from_user.id)
        bot_id = (await message.bot.get_me()).id
        reseller_id = await _resolve_user_reseller(user, bot_id=bot_id, user_id=message.from_user.id)
        if not reseller_id:
            return await message.answer("No reseller link found for this account.")
        bal = await get_user_wallet_balance(message.from_user.id, int(reseller_id))
        return await message.answer(
            f"Your balance is ${bal:.2f}.",
            reply_markup=balance_keyboard((user or {}).get("language", "en")),
        )

    if _is_btn(raw, "btn_back"):
        await state.set_state(RechargeFlow.waiting_amount)
        return await message.answer("Send amount now.", reply_markup=_pay_nav_kb(flow_lang))

    return await message.answer(
        "Send payment proof screenshot now, or press Back/Cancel.",
        reply_markup=_pay_nav_kb(flow_lang),
    )


@router.message(lambda msg: _is_btn(msg.text, "btn_resend_proof"))
async def resend_proof_shortcut(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    req = await db.recharge_requests.find_one(
        {
            "user_id": int(message.from_user.id),
            "status": "need_more_proof",
        },
        sort=[("needs_more_proof_at", -1)],
    )
    if not req:
        await state.clear()
        return await message.answer(
            t(lang, "resend_proof_no_pending"),
            reply_markup=main_menu(lang),
        )

    # Keep same business flow: user only needs to send a new screenshot in private chat.
    await state.clear()
    return await message.answer(
        t(lang, "resend_proof_prompt"),
        reply_markup=types.ReplyKeyboardRemove(),
    )


@router.message(lambda msg: bool(msg.photo) and bool(getattr(msg, "chat", None)) and msg.chat.type == "private")
async def receive_replacement_proof(message: types.Message, state: FSMContext):
    # Keep this catch-all narrow: only private chat and only when no active FSM state.
    if await state.get_state():
        return
    req = await db.recharge_requests.find_one(
        {
            "user_id": int(message.from_user.id),
            "status": "need_more_proof",
        },
        sort=[("needs_more_proof_at", -1)],
    )
    if not req:
        return

    await db.recharge_requests.update_one(
        {"_id": req["_id"], "status": "need_more_proof"},
        {
            "$set": {
                "status": "pending",
                "proof_file_id": message.photo[-1].file_id,
                "proof_replaced_at": datetime.now(UTC),
                "decision_note": "proof_replaced_after_need_more_proof",
            }
        },
    )

    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    refreshed = await db.recharge_requests.find_one({"_id": req["_id"]})
    delivered, route, msg_id, chat_id, thread_id = await _notify_recharge_request_to_reseller_topic(message, refreshed, user)
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
    await message.answer(
        t(lang, "resend_proof_updated"),
        reply_markup=types.ReplyKeyboardRemove(),
    )



@router.message(
    lambda msg: msg.text and (msg.text.lower() in {"reseller menu", "/reseller_menu"} or "????????" in msg.text)
)
async def show_reseller_menu(message: types.Message):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    bot_id = (await message.bot.get_me()).id

    if await is_reseller(message.from_user.id, bot_id=bot_id):
        await _hide_reply_keyboard(message, lang)
        await message.answer(t(lang, "reseller_menu_title"), reply_markup=reseller_main_menu(lang))
    else:
        await message.answer(t(lang, "reseller_only_command"))










def _norm_text(text: str | None) -> str:
    return (text or "").strip().lower()


@router.message(lambda msg: _is_btn(msg.text, "btn_back_main") or _is_btn(msg.text, "btn_cancel"))
async def back_to_main_menu_handler(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if await _handle_rental_exit_message_guard(message, state, target="main", lang=lang):
        return
    await state.clear()
    await _return_main_menu(message, message.from_user.id)


@router.message(lambda msg: _is_btn(msg.text, "btn_settings") or _is_btn(msg.text, "btn_reseller_stats") or _is_btn(msg.text, "btn_support"))
async def simple_menu_placeholders(message: types.Message):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    if _is_btn(message.text, "btn_support"):
        return await message.answer(t(lang, "support"))
    if _is_btn(message.text, "btn_settings"):
        await _hide_reply_keyboard(message, lang)
        return await _open_user_settings_message(message, user, lang)
    if _is_btn(message.text, "btn_reseller_stats"):
        bot_id = (await message.bot.get_me()).id
        if not await is_reseller(message.from_user.id, bot_id=bot_id):
            return await message.answer(t(lang, "reseller_only_command"))
        return await message.answer(await _build_reseller_stats_text(message.from_user.id))


@router.callback_query(lambda c: c.data == "uset:open")
async def user_settings_open_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    await callback.message.edit_text(
        _user_settings_main_text(lang, user),
        reply_markup=_user_settings_main_kb(lang, user),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "uset:lang")
async def user_settings_language_menu(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    current_lang = str((user or {}).get("language") or "en")
    await callback.message.edit_text(
        t(lang, "user_settings_choose_lang"),
        reply_markup=_user_settings_lang_kb(lang, current_lang),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("uset:langset:"))
async def user_settings_language_set(callback: types.CallbackQuery):
    selected = callback.data.split(":", 2)[2].strip().lower()
    if selected not in {"en", "ar"}:
        return await callback.answer("Invalid language", show_alert=True)
    await db.users.update_one({"telegram_id": int(callback.from_user.id)}, {"$set": {"language": selected}})
    user = await get_user(callback.from_user.id)
    lang = selected
    await callback.message.edit_text(
        _user_settings_main_text(lang, user),
        reply_markup=_user_settings_main_kb(lang, user),
    )
    await callback.answer(t(lang, "user_settings_saved"), show_alert=True)


@router.callback_query(lambda c: c.data == "uset:profile")
async def user_settings_profile(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    bot_id = (await callback.bot.get_me()).id
    profile_text = await _user_profile_settings_text(
        user,
        lang=lang,
        bot_id=bot_id,
        user_id=callback.from_user.id,
    )
    await callback.message.edit_text(profile_text, reply_markup=_user_settings_back_kb(lang))
    await callback.answer()


@router.callback_query(lambda c: c.data == "uset:close")
async def user_settings_close(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()





















