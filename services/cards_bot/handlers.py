from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import settings
from database.user_repo import create_user, get_user
from services.cards_bot.keyboards import (
    admin_review_actions_kb,
    admin_withdraw_actions_kb,
    cards_main_menu,
    confirm_submit_kb,
    currency_kb,
    denomination_kb,
    region_kb,
    submit_brand_kb,
    submit_brand_results_kb,
    withdraw_confirm_kb,
    withdraw_currency_kb,
)
from services.cards_bot.service import (
    accept_card,
    create_pricing_rule,
    create_withdrawal,
    ensure_user_from_telegram,
    get_wallet_snapshot,
    list_cards_for_review,
    list_cards_for_user,
    list_missing_pricing,
    list_open_withdrawals,
    list_top_card_brands,
    list_withdrawals_for_user,
    parse_decimal,
    reject_card,
    search_card_brands,
    submit_card,
    update_withdrawal_status,
)
from services.cards_bot.states import CardsSubmitFlow, CardsWithdrawFlow
from utils.user_money import format_usd

router = Router()


def _is_owner(user_id: int) -> bool:
    return int(user_id) == int(getattr(settings, "owner_id", 0) or 0)


def _is_btn(text: str | None, expected: str) -> bool:
    return str(text or "").strip().lower() == expected.strip().lower()


def _lang(user_doc: dict | None) -> str:
    return str((user_doc or {}).get("language") or "en")


def _t(lang: str, en: str, ar: str) -> str:
    return ar if str(lang).lower().startswith("ar") else en


async def _ensure_global_user(message: types.Message) -> dict:
    user = await get_user(int(message.from_user.id))
    if user:
        return user
    return await create_user(
        int(message.from_user.id),
        str(message.from_user.username or "").strip(),
        reseller_id=None,
    )


async def _ensure_card_user(actor) -> tuple[dict, dict]:
    user_doc = await get_user(int(actor.id))
    if not user_doc:
        user_doc = await create_user(int(actor.id), str(actor.username or "").strip(), reseller_id=None)
    card_user = await ensure_user_from_telegram(actor)
    return user_doc, card_user


def _fmt_money(value) -> str:
    return format_usd(value)


def _fmt_card_line(row: dict) -> str:
    return (
        f"{row.get('_id')} | {row.get('brand')} | {float(row.get('denomination') or 0):.2f} "
        f"{row.get('currency')} | {row.get('region')} | {row.get('status')}"
    )


def _card_summary_text(lang: str, data: dict) -> str:
    return _t(
        lang,
        (
            "Confirm card submission\n\n"
            f"Brand: {data.get('brand')}\n"
            f"Value: {data.get('denomination')} {data.get('currency')}\n"
            f"Region: {data.get('region')}\n"
            f"Code: {data.get('code')}\n"
            f"PIN: {data.get('pin') or '-'}"
        ),
        (
            "تأكيد إرسال البطاقة\n\n"
            f"النوع: {data.get('brand')}\n"
            f"القيمة: {data.get('denomination')} {data.get('currency')}\n"
            f"المنطقة: {data.get('region')}\n"
            f"الكود: {data.get('code')}\n"
            f"الـ PIN: {data.get('pin') or '-'}"
        ),
    )


async def _open_brand_picker(message: types.Message, *, lang: str) -> None:
    brands = await list_top_card_brands(limit=8)
    await message.answer(
        _t(lang, "Choose card brand", "اختر نوع البطاقة"),
        reply_markup=submit_brand_kb(brands),
    )


@router.message(F.text.func(lambda text: _is_btn(text, "Sell Card")))
async def open_sell_card(message: types.Message, state: FSMContext) -> None:
    user_doc = await _ensure_global_user(message)
    lang = _lang(user_doc)
    await state.clear()
    await state.set_state(CardsSubmitFlow.waiting_brand)
    await _open_brand_picker(message, lang=lang)


@router.callback_query(F.data == "cardx:brandtop")
async def show_brand_top(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    await state.set_state(CardsSubmitFlow.waiting_brand)
    if callback.message:
        await callback.message.answer(
            _t(lang, "Choose card brand", "اختر نوع البطاقة"),
            reply_markup=submit_brand_kb(await list_top_card_brands(limit=8)),
        )
    await callback.answer()


@router.callback_query(F.data == "cardx:brandsearch")
async def start_brand_search(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    await state.set_state(CardsSubmitFlow.waiting_brand_search)
    if callback.message:
        await callback.message.answer(_t(lang, "Type card brand", "اكتب اسم نوع البطاقة"))
    await callback.answer()


@router.message(CardsSubmitFlow.waiting_brand_search)
async def handle_brand_search(message: types.Message, state: FSMContext) -> None:
    user_doc = await _ensure_global_user(message)
    lang = _lang(user_doc)
    brands = await search_card_brands(message.text or "", limit=20)
    if not brands:
        await message.answer(_t(lang, "No brands found. Try again.", "لم يتم العثور على أنواع. جرّب مرة أخرى."))
        return
    await state.set_state(CardsSubmitFlow.waiting_brand)
    await message.answer(
        _t(lang, "Select brand", "اختر النوع"),
        reply_markup=submit_brand_results_kb(brands),
    )


@router.callback_query(F.data.startswith("cardx:brand:"))
async def choose_brand(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    brand = str(callback.data or "").split(":", 2)[-1].strip().upper()
    await state.update_data(brand=brand)
    await state.set_state(CardsSubmitFlow.waiting_denomination)
    if callback.message:
        await callback.message.answer(
            _t(lang, "Choose denomination", "اختر القيمة"),
            reply_markup=denomination_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("cardx:den:"))
async def choose_denomination(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    value = str(callback.data or "").split(":", 2)[-1].strip()
    if value == "manual":
        await state.set_state(CardsSubmitFlow.waiting_denomination)
        await state.update_data(expect_manual_den=True)
        if callback.message:
            await callback.message.answer(_t(lang, "Enter denomination amount", "أدخل قيمة البطاقة"))
        await callback.answer()
        return

    await state.update_data(denomination=value, expect_manual_den=False)
    await state.set_state(CardsSubmitFlow.waiting_currency)
    if callback.message:
        await callback.message.answer(
            _t(lang, "Choose currency", "اختر العملة"),
            reply_markup=currency_kb(),
        )
    await callback.answer()


@router.message(CardsSubmitFlow.waiting_denomination)
async def handle_manual_denomination(message: types.Message, state: FSMContext) -> None:
    user_doc = await _ensure_global_user(message)
    lang = _lang(user_doc)
    data = await state.get_data()
    if not bool(data.get("expect_manual_den")):
        await message.answer(_t(lang, "Use the buttons above.", "استخدم الأزرار أعلاه."))
        return
    try:
        value = parse_decimal(message.text or "")
    except ValueError:
        await message.answer(_t(lang, "Invalid denomination value.", "القيمة غير صالحة."))
        return
    await state.update_data(denomination=str(value), expect_manual_den=False)
    await state.set_state(CardsSubmitFlow.waiting_currency)
    await message.answer(
        _t(lang, "Choose currency", "اختر العملة"),
        reply_markup=currency_kb(),
    )


@router.callback_query(F.data.startswith("cardx:cur:"))
async def choose_currency(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    currency = str(callback.data or "").split(":")[-1].strip().upper()
    await state.update_data(currency=currency)
    await state.set_state(CardsSubmitFlow.waiting_region)
    if callback.message:
        await callback.message.answer(
            _t(lang, "Choose region", "اختر المنطقة"),
            reply_markup=region_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("cardx:reg:"))
async def choose_region(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    region = str(callback.data or "").split(":")[-1].strip().upper()
    await state.update_data(region=region)
    await state.set_state(CardsSubmitFlow.waiting_code)
    if callback.message:
        await callback.message.answer(_t(lang, "Send the card code", "أرسل كود البطاقة"))
    await callback.answer()


@router.message(CardsSubmitFlow.waiting_code)
async def handle_card_code(message: types.Message, state: FSMContext) -> None:
    user_doc = await _ensure_global_user(message)
    lang = _lang(user_doc)
    code = str(message.text or "").strip()
    if len(code) < 4:
        await message.answer(_t(lang, "Card code is too short.", "كود البطاقة قصير جدًا."))
        return
    await state.update_data(code=code)
    await state.set_state(CardsSubmitFlow.waiting_pin)
    await message.answer(_t(lang, "Send PIN or '-' to skip", "أرسل الـ PIN أو اكتب - للتخطي"))


@router.message(CardsSubmitFlow.waiting_pin)
async def handle_card_pin(message: types.Message, state: FSMContext) -> None:
    user_doc = await _ensure_global_user(message)
    lang = _lang(user_doc)
    pin_raw = str(message.text or "").strip()
    pin = None if pin_raw in {"-", "skip", "SKIP"} else pin_raw
    await state.update_data(pin=pin)
    data = await state.get_data()
    await message.answer(_card_summary_text(lang, data), reply_markup=confirm_submit_kb())


@router.callback_query(F.data == "cardx:confirm")
async def confirm_card_submission(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, card_user = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    data = await state.get_data()
    try:
        denomination = parse_decimal(str(data.get("denomination") or ""))
    except ValueError:
        await callback.answer(_t(lang, "Invalid denomination.", "القيمة غير صالحة."), show_alert=True)
        return
    card, queued = await submit_card(
        actor_user_id=str(card_user.get("_id")),
        brand=str(data.get("brand") or ""),
        denomination=denomination,
        currency=str(data.get("currency") or "USD"),
        region=str(data.get("region") or "GLOBAL"),
        code=str(data.get("code") or ""),
        pin=data.get("pin"),
    )
    await state.clear()
    if callback.message:
        if card:
            await callback.message.answer(
                _t(
                    lang,
                    f"Card submitted successfully.\nReference: {card.get('_id')}",
                    f"تم إرسال البطاقة بنجاح.\nالمرجع: {card.get('_id')}",
                ),
                reply_markup=cards_main_menu(lang),
            )
        else:
            await callback.message.answer(
                _t(
                    lang,
                    "This card price is not configured yet. It has been queued for owner pricing review.",
                    "تسعير هذه البطاقة غير مضبوط بعد. تمت إضافتها لقائمة التسعير عند الأونر.",
                ),
                reply_markup=cards_main_menu(lang),
            )
    await callback.answer()


@router.callback_query(F.data == "cardx:cancel")
async def cancel_card_flow(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    await state.clear()
    if callback.message:
        await callback.message.answer(_t(lang, "Cancelled.", "تم الإلغاء."), reply_markup=cards_main_menu(lang))
    await callback.answer()


@router.message(F.text.func(lambda text: _is_btn(text, "Wallet")))
async def open_wallet(message: types.Message) -> None:
    user_doc, card_user = await _ensure_card_user(message.from_user)
    lang = _lang(user_doc)
    wallet = await get_wallet_snapshot(str(card_user.get("_id")))
    await message.answer(
        _t(
            lang,
            (
                "Card Wallet\n\n"
                f"Available: {_fmt_money(wallet.get('available_usd'))}\n"
                f"Pending: {_fmt_money(wallet.get('pending_usd'))}\n"
                f"Locked: {_fmt_money(wallet.get('locked_usd'))}"
            ),
            (
                "محفظة البطاقات\n\n"
                f"المتاح: {_fmt_money(wallet.get('available_usd'))}\n"
                f"المعلّق: {_fmt_money(wallet.get('pending_usd'))}\n"
                f"المقفل: {_fmt_money(wallet.get('locked_usd'))}"
            ),
        )
    )


@router.message(F.text.func(lambda text: _is_btn(text, "My Cards")))
async def open_my_cards(message: types.Message) -> None:
    user_doc, card_user = await _ensure_card_user(message.from_user)
    lang = _lang(user_doc)
    rows = await list_cards_for_user(str(card_user.get("_id")), limit=20)
    if not rows:
        await message.answer(_t(lang, "No cards submitted yet.", "لا توجد بطاقات مرسلة بعد."))
        return
    text = "\n".join(_fmt_card_line(row) for row in rows)
    await message.answer(
        _t(lang, f"My Cards\n\n{text}", f"بطاقاتي\n\n{text}")
    )


@router.message(F.text.func(lambda text: _is_btn(text, "Withdraw")))
async def start_withdraw(message: types.Message, state: FSMContext) -> None:
    user_doc = await _ensure_global_user(message)
    lang = _lang(user_doc)
    await state.clear()
    await state.set_state(CardsWithdrawFlow.waiting_amount)
    await message.answer(_t(lang, "Enter USD amount to withdraw", "أدخل مبلغ السحب بالدولار"))


@router.message(CardsWithdrawFlow.waiting_amount)
async def handle_withdraw_amount(message: types.Message, state: FSMContext) -> None:
    user_doc = await _ensure_global_user(message)
    lang = _lang(user_doc)
    try:
        amount = parse_decimal(message.text or "")
    except ValueError:
        await message.answer(_t(lang, "Invalid amount.", "المبلغ غير صالح."))
        return
    await state.update_data(withdraw_amount=str(amount))
    await state.set_state(CardsWithdrawFlow.waiting_currency)
    await message.answer(_t(lang, "Choose payout currency", "اختر عملة السحب"), reply_markup=withdraw_currency_kb())


@router.callback_query(F.data.startswith("cardx:wcur:"))
async def choose_withdraw_currency(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    currency = str(callback.data or "").split(":")[-1].strip().upper()
    await state.update_data(withdraw_currency=currency)
    await state.set_state(CardsWithdrawFlow.waiting_destination)
    if callback.message:
        await callback.message.answer(
            _t(lang, "Send payout details / wallet / note", "أرسل تفاصيل الاستلام أو المحفظة أو الملاحظة")
        )
    await callback.answer()


@router.message(CardsWithdrawFlow.waiting_destination)
async def handle_withdraw_destination(message: types.Message, state: FSMContext) -> None:
    user_doc = await _ensure_global_user(message)
    lang = _lang(user_doc)
    note = str(message.text or "").strip()
    if len(note) < 3:
        await message.answer(_t(lang, "Payout details are too short.", "تفاصيل الاستلام قصيرة جدًا."))
        return
    await state.update_data(withdraw_note=note)
    data = await state.get_data()
    text = _t(
        lang,
        (
            "Confirm withdrawal\n\n"
            f"Amount: {data.get('withdraw_amount')} USD\n"
            f"Payout currency: {data.get('withdraw_currency')}\n"
            f"Details: {data.get('withdraw_note')}"
        ),
        (
            "تأكيد السحب\n\n"
            f"المبلغ: {data.get('withdraw_amount')} USD\n"
            f"عملة الاستلام: {data.get('withdraw_currency')}\n"
            f"التفاصيل: {data.get('withdraw_note')}"
        ),
    )
    await message.answer(text, reply_markup=withdraw_confirm_kb())


@router.callback_query(F.data == "cardx:wconfirm")
async def confirm_withdraw(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, card_user = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    data = await state.get_data()
    try:
        amount = parse_decimal(str(data.get("withdraw_amount") or ""))
        row = await create_withdrawal(
            user_id=str(card_user.get("_id")),
            requested_usd_amount=amount,
            payout_currency=str(data.get("withdraw_currency") or "USD"),
            notes=str(data.get("withdraw_note") or ""),
        )
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await state.clear()
    if callback.message:
        await callback.message.answer(
            _t(
                lang,
                f"Withdrawal request created.\nReference: {row.get('_id')}",
                f"تم إنشاء طلب السحب.\nالمرجع: {row.get('_id')}",
            ),
            reply_markup=cards_main_menu(lang),
        )
    await callback.answer()


@router.message(F.text.func(lambda text: _is_btn(text, "My Withdrawals")))
async def open_my_withdrawals(message: types.Message) -> None:
    user_doc, card_user = await _ensure_card_user(message.from_user)
    lang = _lang(user_doc)
    rows = await list_withdrawals_for_user(str(card_user.get("_id")), limit=20)
    if not rows:
        await message.answer(_t(lang, "No withdrawals yet.", "لا توجد طلبات سحب بعد."))
        return
    lines = [
        f"{row.get('_id')} | {_fmt_money(row.get('requested_usd_amount'))} | {row.get('payout_currency')} | {row.get('status')}"
        for row in rows
    ]
    await message.answer(_t(lang, "My Withdrawals\n\n" + "\n".join(lines), "طلبات السحب\n\n" + "\n".join(lines)))


@router.message(F.text.func(lambda text: _is_btn(text, "Support")))
async def open_support(message: types.Message) -> None:
    user_doc = await _ensure_global_user(message)
    lang = _lang(user_doc)
    await message.answer(
        _t(
            lang,
            "Support\n\nFor cards, pricing, withdrawal, or payout issues, send a detailed message to support.",
            "الدعم\n\nلمشاكل البطاقات أو التسعير أو السحب، أرسل رسالة مفصلة إلى الدعم.",
        )
    )


@router.message(Command("cards_reviews"))
async def owner_cards_reviews(message: types.Message) -> None:
    if not _is_owner(message.from_user.id):
        return
    rows = await list_cards_for_review(limit=10)
    if not rows:
        await message.answer("No cards pending review.")
        return
    for row in rows:
        await message.answer(_fmt_card_line(row), reply_markup=admin_review_actions_kb(str(row.get("_id"))))


@router.message(Command("cards_missing_pricing"))
async def owner_missing_pricing(message: types.Message) -> None:
    if not _is_owner(message.from_user.id):
        return
    rows = await list_missing_pricing(limit=20)
    if not rows:
        await message.answer("No missing pricing rows.")
        return
    lines = [
        f"{row.get('brand')} | {float(row.get('denomination') or 0):.2f} {row.get('currency')} | {row.get('region')} | seen={row.get('seen_count')}"
        for row in rows
    ]
    await message.answer("Missing pricing\n\n" + "\n".join(lines))


@router.message(Command("cards_price"))
async def owner_set_price(message: types.Message) -> None:
    if not _is_owner(message.from_user.id):
        return
    payload = str(message.text or "").split(maxsplit=1)
    if len(payload) < 2:
        await message.answer("Usage: /cards_price BRAND|DEN|CUR|REG|CUSTOMER_RATE|TRADER_RATE")
        return
    parts = [part.strip() for part in payload[1].split("|")]
    if len(parts) != 6:
        await message.answer("Usage: /cards_price BRAND|DEN|CUR|REG|CUSTOMER_RATE|TRADER_RATE")
        return
    brand, den, cur, reg, customer_rate, trader_rate = parts
    try:
        row = await create_pricing_rule(
            actor_user_id=str(message.from_user.id),
            brand=brand,
            denomination=parse_decimal(den),
            currency=cur,
            region=reg,
            customer_buy_rate_percent=parse_decimal(customer_rate),
            trader_rate_percent=parse_decimal(trader_rate),
        )
    except Exception as exc:
        await message.answer(f"Failed: {exc}")
        return
    await message.answer(f"Pricing rule created: {row.get('brand')} {row.get('denomination')} {row.get('currency')} {row.get('region')}")


@router.message(Command("cards_withdrawals"))
async def owner_open_withdrawals(message: types.Message) -> None:
    if not _is_owner(message.from_user.id):
        return
    rows = await list_open_withdrawals(limit=10)
    if not rows:
        await message.answer("No open withdrawals.")
        return
    for row in rows:
        text = (
            f"{row.get('_id')} | user={row.get('user_id')} | {_fmt_money(row.get('requested_usd_amount'))} "
            f"| {row.get('payout_currency')} | {row.get('status')}\n{row.get('notes') or '-'}"
        )
        await message.answer(text, reply_markup=admin_withdraw_actions_kb(str(row.get("_id"))))


@router.callback_query(F.data.startswith("cardx:admin:accept:"))
async def owner_accept_card(callback: types.CallbackQuery) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    card_id = str(callback.data or "").split(":")[-1].strip()
    try:
        row = await accept_card(card_id, actor_user_id=str(callback.from_user.id))
        await callback.answer("Accepted", show_alert=False)
        if callback.message:
            await callback.message.answer(f"Accepted: {_fmt_card_line(row)}")
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("cardx:admin:reject:"))
async def owner_reject_card(callback: types.CallbackQuery) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    card_id = str(callback.data or "").split(":")[-1].strip()
    try:
        row = await reject_card(card_id, actor_user_id=str(callback.from_user.id))
        await callback.answer("Rejected", show_alert=False)
        if callback.message:
            await callback.message.answer(f"Rejected: {_fmt_card_line(row)}")
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("cardx:admin:w"))
async def owner_withdraw_action(callback: types.CallbackQuery) -> None:
    if not _is_owner(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    raw = str(callback.data or "")
    parts = raw.split(":")
    if len(parts) < 4:
        await callback.answer("Invalid action", show_alert=True)
        return
    action = parts[2]
    withdrawal_id = parts[3].strip()
    status_map = {
        "wapprove": "approved",
        "wreject": "rejected",
        "wpaid": "paid",
    }
    status = status_map.get(action)
    if not status:
        await callback.answer("Invalid action", show_alert=True)
        return
    try:
        row = await update_withdrawal_status(
            withdrawal_id,
            status=status,
            actor_user_id=str(callback.from_user.id),
        )
        await callback.answer(status.title(), show_alert=False)
        if callback.message:
            await callback.message.answer(f"Withdrawal updated: {row.get('_id')} -> {status}")
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
