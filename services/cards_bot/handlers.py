from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile

from config import settings
from database.user_repo import create_user, get_user
from services.cards_bot.keyboards import (
    admin_missing_pricing_kb,
    cards_admin_panel_kb,
    admin_review_actions_kb,
    admin_withdraw_actions_kb,
    cards_main_menu,
    confirm_submit_kb,
    currency_kb,
    denomination_kb,
    region_kb,
    submit_brand_kb,
    submit_brand_results_kb,
    submit_code_prompt_kb,
    submit_pin_prompt_kb,
    withdraw_confirm_kb,
    withdraw_currency_kb,
)
from services.cards_bot.service import (
    accept_card,
    create_pricing_rule,
    create_withdrawal,
    ensure_user_from_telegram,
    get_missing_pricing,
    get_wallet_snapshot,
    list_cards_for_daily_export,
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
from services.cards_bot.states import CardsAdminFlow, CardsSubmitFlow, CardsWithdrawFlow
from utils.user_money import format_usd

router = Router()
CUSTOM_DEN_KEY = "cardx_custom_denominations"
logger = logging.getLogger(__name__)


def _is_owner(user_id: int) -> bool:
    return int(user_id) == int(getattr(settings, "owner_id", 0) or 0)


def _cards_admin_ids() -> set[int]:
    raw = str(getattr(settings, "cardex_admin_ids", "") or "").strip()
    values: set[int] = set()
    for chunk in raw.split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            values.add(int(text))
        except Exception:
            continue
    owner_id = int(getattr(settings, "owner_id", 0) or 0)
    if owner_id > 0:
        values.add(owner_id)
    return values


def _is_cards_admin(user_id: int) -> bool:
    return int(user_id) in _cards_admin_ids()


def _is_btn(text: str | None, expected: str) -> bool:
    return str(text or "").strip().lower() == expected.strip().lower()


_CARD_MENU_ALIASES: dict[str, tuple[str, ...]] = {
    "Sell Card": ("Sell Card", "بيع كرت"),
    "Wallet": ("Wallet", "المحفظة"),
    "My Cards": ("My Cards", "بطاقاتي"),
    "Withdraw": ("Withdraw", "طلب سحب"),
    "My Withdrawals": ("My Withdrawals", "سحوباتي"),
    "Support": ("Support", "الدعم"),
}


def _is_menu_btn(text: str | None, action: str) -> bool:
    candidates = _CARD_MENU_ALIASES.get(action, (action,))
    raw = str(text or "").strip().lower()
    return any(raw == candidate.strip().lower() for candidate in candidates)


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


def _cards_menu(lang: str, user_id: int):
    return cards_main_menu(lang, is_admin=_is_cards_admin(user_id))


def _fmt_money(value) -> str:
    return format_usd(value)


def _operation_failed_text(lang: str) -> str:
    return _t(
        lang,
        "The request could not be completed right now. Please try again later.",
        "تعذر تنفيذ الطلب الآن. يرجى المحاولة لاحقًا.",
    )


def _fmt_card_line(row: dict) -> str:
    return (
        f"{row.get('_id')} | {row.get('brand')} | {float(row.get('denomination') or 0):.2f} "
        f"{row.get('currency')} | {row.get('region')} | {row.get('status')}"
    )


def _decimal_label(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _get_custom_dens(data: dict | None) -> list[str]:
    raw = (data or {}).get(CUSTOM_DEN_KEY, [])
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _remember_custom_den(data: dict, value: Decimal) -> None:
    values = _get_custom_dens(data)
    label = _decimal_label(value)
    if label in values:
        data[CUSTOM_DEN_KEY] = values
        return
    values.append(label)
    try:
        values.sort(key=lambda x: Decimal(x))
    except Exception:
        pass
    data[CUSTOM_DEN_KEY] = values[-20:]


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


@router.message(F.text.func(lambda text: _is_menu_btn(text, "Sell Card")))
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


@router.callback_query(F.data == "cardx:back:brand")
async def submit_back_brand(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    await state.set_state(CardsSubmitFlow.waiting_brand)
    if callback.message:
        await callback.message.answer(
            _t(lang, "Choose card brand", "Choose card brand"),
            reply_markup=submit_brand_kb(await list_top_card_brands(limit=8)),
        )
    await callback.answer()


@router.callback_query(F.data == "cardx:back:den")
async def submit_back_den(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    data = await state.get_data()
    await state.set_state(CardsSubmitFlow.waiting_denomination)
    if callback.message:
        await callback.message.answer(
            _t(lang, "Choose denomination", "Choose denomination"),
            reply_markup=denomination_kb(_get_custom_dens(data)),
        )
    await callback.answer()


@router.callback_query(F.data == "cardx:back:cur")
async def submit_back_cur(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    await state.set_state(CardsSubmitFlow.waiting_currency)
    if callback.message:
        await callback.message.answer(_t(lang, "Choose currency", "Choose currency"), reply_markup=currency_kb())
    await callback.answer()


@router.callback_query(F.data == "cardx:back:region")
async def submit_back_region(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    await state.set_state(CardsSubmitFlow.waiting_region)
    if callback.message:
        await callback.message.answer(_t(lang, "Choose region", "Choose region"), reply_markup=region_kb())
    await callback.answer()


@router.callback_query(F.data == "cardx:back:code")
@router.callback_query(F.data == "cardx:edit:code")
async def submit_back_code(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    await state.set_state(CardsSubmitFlow.waiting_code)
    if callback.message:
        await callback.message.answer(
            _t(lang, "Send the card code", "Send the card code"),
            reply_markup=submit_code_prompt_kb(),
        )
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
    data = await state.get_data()
    await state.update_data(brand=brand)
    await state.set_state(CardsSubmitFlow.waiting_denomination)
    if callback.message:
        await callback.message.answer(
            _t(lang, "Choose denomination", "اختر القيمة"),
            reply_markup=denomination_kb(_get_custom_dens(data)),
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
    data[CUSTOM_DEN_KEY] = _get_custom_dens(data)
    _remember_custom_den(data, value)
    await state.update_data(
        denomination=str(value),
        expect_manual_den=False,
        **{CUSTOM_DEN_KEY: data[CUSTOM_DEN_KEY]},
    )
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
        await callback.message.answer(
            _t(lang, "Send the card code", "Send the card code"),
            reply_markup=submit_code_prompt_kb(),
        )
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
    await message.answer(
        _t(lang, "Send PIN or '-' to skip", "Send PIN or '-' to skip"),
        reply_markup=submit_pin_prompt_kb(),
    )


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
                reply_markup=_cards_menu(lang, callback.from_user.id),
            )
        else:
            await callback.message.answer(
                _t(
                    lang,
                    "This card price is not configured yet. It has been queued for owner pricing review.",
                    "تسعير هذه البطاقة غير مضبوط بعد. تمت إضافتها لقائمة التسعير عند الأونر.",
                ),
                reply_markup=_cards_menu(lang, callback.from_user.id),
            )
    await callback.answer()


@router.callback_query(F.data == "cardx:cancel")
async def cancel_card_flow(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    await state.clear()
    if callback.message:
        await callback.message.answer(_t(lang, "Cancelled.", "تم الإلغاء."), reply_markup=_cards_menu(lang, callback.from_user.id))
    await callback.answer()


@router.message(F.text.func(lambda text: _is_menu_btn(text, "Wallet")))
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


@router.message(F.text.func(lambda text: _is_menu_btn(text, "My Cards")))
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


@router.message(F.text.func(lambda text: _is_menu_btn(text, "Withdraw")))
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
    except Exception:
        logger.exception("card-ex withdrawal request failed user_id=%s", callback.from_user.id)
        await callback.answer(_operation_failed_text(lang), show_alert=True)
        return
    await state.clear()
    if callback.message:
        await callback.message.answer(
            _t(
                lang,
                f"Withdrawal request created.\nReference: {row.get('_id')}",
                f"تم إنشاء طلب السحب.\nالمرجع: {row.get('_id')}",
            ),
            reply_markup=_cards_menu(lang, callback.from_user.id),
        )
    await callback.answer()


@router.message(F.text.func(lambda text: _is_menu_btn(text, "My Withdrawals")))
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


@router.message(F.text.func(lambda text: _is_menu_btn(text, "Support")))
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


def _admin_panel_text(lang: str) -> str:
    return _t(
        lang,
        "Cards Admin Panel\n\nChoose the management section.",
        "لوحة إدارة البطاقات\n\nاختر القسم الذي تريد إدارته.",
    )


def _missing_pricing_line(row: dict) -> str:
    return f"{row.get('brand')} | {float(row.get('denomination') or 0):.2f} {row.get('currency')} | {row.get('region')}"


def _card_export_filename(brand: str, day: datetime) -> str:
    safe_brand = re.sub(r"[^A-Za-z0-9_-]+", "_", str(brand or "cards").strip().upper()).strip("_") or "CARDS"
    return f"cardex_{day.strftime('%Y-%m-%d')}_{safe_brand}.txt"


def _card_export_line(row: dict) -> str:
    parts = [
        str(row.get("code") or "").strip(),
        str(row.get("pin") or "").strip() or "-",
        f"{float(row.get('denomination') or 0):.2f} {row.get('currency')}",
        str(row.get("region") or "GLOBAL"),
        str(row.get("status") or "-"),
        str(row.get("_id") or "-"),
    ]
    return " | ".join(parts)


def _group_cards_export_files(rows: list[dict], *, day: datetime) -> list[tuple[str, str, int]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("brand") or "UNKNOWN").upper().strip() or "UNKNOWN"].append(row)

    files: list[tuple[str, str, int]] = []
    for brand in sorted(grouped):
        brand_rows = grouped[brand]
        lines = [
            f"Card-EX daily export",
            f"Date: {day.strftime('%Y-%m-%d')}",
            f"Brand: {brand}",
            f"Count: {len(brand_rows)}",
            "",
            "CODE | PIN | VALUE | REGION | STATUS | REF",
        ]
        lines.extend(_card_export_line(row) for row in brand_rows)
        files.append((_card_export_filename(brand, day), "\n".join(lines) + "\n", len(brand_rows)))
    return files


def _count_by(rows: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        label = str(row.get(key) or "UNKNOWN").upper().strip() or "UNKNOWN"
        counts[label] += 1
    return dict(sorted(counts.items()))


def _cards_today_report_text(
    lang: str,
    *,
    day: datetime,
    rows: list[dict],
    pending_reviews: int,
    missing_pricing: int,
    open_withdrawals: int,
) -> str:
    by_status = _count_by(rows, "status")
    by_brand = _count_by(rows, "brand")
    status_lines = "\n".join(f"- {key}: {value}" for key, value in by_status.items()) or "- none"
    brand_lines = "\n".join(f"- {key}: {value}" for key, value in by_brand.items()) or "- none"
    if str(lang or "").lower().startswith("ar"):
        return (
            f"تقرير بطاقات اليوم\n\n"
            f"التاريخ: {day.strftime('%Y-%m-%d')} UTC\n"
            f"إجمالي بطاقات اليوم: {len(rows)}\n"
            f"بانتظار المراجعة: {pending_reviews}\n"
            f"تسعير ناقص: {missing_pricing}\n"
            f"طلبات سحب مفتوحة: {open_withdrawals}\n\n"
            f"حسب الحالة:\n{status_lines}\n\n"
            f"حسب النوع:\n{brand_lines}"
        )
    return (
        f"Card-EX Today Report\n\n"
        f"Date: {day.strftime('%Y-%m-%d')} UTC\n"
        f"Today's cards: {len(rows)}\n"
        f"Pending review: {pending_reviews}\n"
        f"Missing pricing: {missing_pricing}\n"
        f"Open withdrawals: {open_withdrawals}\n\n"
        f"By status:\n{status_lines}\n\n"
        f"By type:\n{brand_lines}"
    )


def _today_utc_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    start = datetime.combine(current.date(), time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


async def _open_cards_admin_panel(target, *, lang: str) -> None:
    text = _admin_panel_text(lang)
    if isinstance(target, types.CallbackQuery):
        if target.message:
            await target.message.answer(text, reply_markup=cards_admin_panel_kb(lang))
        await target.answer()
    else:
        await target.answer(text, reply_markup=cards_admin_panel_kb(lang))


@router.message(Command("cards_admin"))
@router.message(F.text.func(lambda text: _is_btn(text, "Admin Panel") or _is_btn(text, "لوحة الإدارة")))
async def open_cards_admin_panel_message(message: types.Message, state: FSMContext) -> None:
    if not _is_cards_admin(message.from_user.id):
        return
    user_doc = await _ensure_global_user(message)
    await state.clear()
    await _open_cards_admin_panel(message, lang=_lang(user_doc))


@router.callback_query(F.data == "cardx:panel:open")
async def open_cards_admin_panel_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_cards_admin(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    user_doc, _ = await _ensure_card_user(callback.from_user)
    await state.clear()
    await _open_cards_admin_panel(callback, lang=_lang(user_doc))


@router.callback_query(F.data == "cardx:panel:missing_pricing")
async def open_missing_pricing_panel(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_cards_admin(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    await state.clear()
    rows = await list_missing_pricing(limit=20)
    if not rows:
        await callback.answer(_t(lang, "No missing pricing rows.", "لا توجد عناصر تسعير ناقصة."), show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            _t(lang, "Choose a pricing row to set rates.", "اختر عنصر التسعير الذي تريد ضبطه."),
            reply_markup=admin_missing_pricing_kb(rows, lang),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("cardx:pricepick:"))
async def pick_missing_pricing_row(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_cards_admin(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    missing_id = str(callback.data or "").split(":")[-1].strip()
    row = await get_missing_pricing(missing_id)
    if not row:
        await callback.answer(_t(lang, "Pricing row not found.", "تعذر العثور على عنصر التسعير."), show_alert=True)
        return
    await state.set_state(CardsAdminFlow.waiting_pricing_rates)
    await state.update_data(cardx_missing_pricing_id=missing_id)
    prompt = _t(
        lang,
        f"Set rates for:\n{_missing_pricing_line(row)}\n\nSend:\nCUSTOMER|TRADER\nExample: 80|78\nOr send a single value like 80 to use it for both.",
        f"ضبط التسعير لـ:\n{_missing_pricing_line(row)}\n\nأرسل:\nCUSTOMER|TRADER\nمثال: 80|78\nأو أرسل قيمة واحدة مثل 80 ليتم اعتمادها لكلا النسبتين.",
    )
    if callback.message:
        await callback.message.answer(prompt)
    await callback.answer()


@router.message(CardsAdminFlow.waiting_pricing_rates)
async def save_missing_pricing_rates(message: types.Message, state: FSMContext) -> None:
    if not _is_cards_admin(message.from_user.id):
        return
    user_doc = await _ensure_global_user(message)
    lang = _lang(user_doc)
    payload = str(message.text or "").strip()
    parts = [part.strip() for part in payload.split("|") if part.strip()]
    try:
        if len(parts) == 1:
            customer_rate = parse_decimal(parts[0])
            trader_rate = customer_rate
        elif len(parts) == 2:
            customer_rate = parse_decimal(parts[0])
            trader_rate = parse_decimal(parts[1])
        else:
            raise ValueError("invalid pricing format")
    except Exception:
        await message.answer(
            _t(
                lang,
                "Invalid format. Send CUSTOMER|TRADER or a single value.",
                "تنسيق غير صالح. أرسل CUSTOMER|TRADER أو قيمة واحدة.",
            )
        )
        return
    data = await state.get_data()
    missing_id = str(data.get("cardx_missing_pricing_id") or "").strip()
    row = await get_missing_pricing(missing_id)
    if not row:
        await state.clear()
        await message.answer(_t(lang, "Pricing row no longer exists.", "عنصر التسعير لم يعد موجودًا."))
        return
    created = await create_pricing_rule(
        actor_user_id=str(message.from_user.id),
        brand=str(row.get("brand") or ""),
        denomination=parse_decimal(str(row.get("denomination") or "")),
        currency=str(row.get("currency") or "USD"),
        region=str(row.get("region") or "GLOBAL"),
        customer_buy_rate_percent=customer_rate,
        trader_rate_percent=trader_rate,
    )
    await state.clear()
    await message.answer(
        _t(
            lang,
            f"Pricing saved:\n{_missing_pricing_line(created)}\nCustomer: {created.get('customer_buy_rate_percent')}\nTrader: {created.get('trader_rate_percent')}",
            f"تم حفظ التسعير:\n{_missing_pricing_line(created)}\nالعميل: {created.get('customer_buy_rate_percent')}\nالتاجر: {created.get('trader_rate_percent')}",
        ),
        reply_markup=cards_admin_panel_kb(lang),
    )


@router.callback_query(F.data == "cardx:panel:reviews")
async def open_cards_reviews_panel(callback: types.CallbackQuery) -> None:
    if not _is_cards_admin(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    rows = await list_cards_for_review(limit=10)
    if not rows:
        await callback.answer("No cards pending review.", show_alert=True)
        return
    for row in rows:
        if callback.message:
            await callback.message.answer(_fmt_card_line(row), reply_markup=admin_review_actions_kb(str(row.get("_id"))))
    await callback.answer()


@router.callback_query(F.data == "cardx:panel:withdrawals")
async def open_cards_withdrawals_panel(callback: types.CallbackQuery) -> None:
    if not _is_cards_admin(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    rows = await list_open_withdrawals(limit=10)
    if not rows:
        await callback.answer("No open withdrawals.", show_alert=True)
        return
    for row in rows:
        text = (
            f"{row.get('_id')} | user={row.get('user_id')} | {_fmt_money(row.get('requested_usd_amount'))} "
            f"| {row.get('payout_currency')} | {row.get('status')}\n{row.get('notes') or '-'}"
        )
        if callback.message:
            await callback.message.answer(text, reply_markup=admin_withdraw_actions_kb(str(row.get("_id"))))
    await callback.answer()


@router.callback_query(F.data == "cardx:panel:today_report")
async def open_cards_today_report(callback: types.CallbackQuery) -> None:
    if not _is_cards_admin(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    since, until = _today_utc_window()
    rows = await list_cards_for_daily_export(since=since, until=until, limit=2000)
    pending_reviews = len(await list_cards_for_review(limit=200))
    missing_pricing = len(await list_missing_pricing(limit=200))
    open_withdrawals = len(await list_open_withdrawals(limit=200))
    if callback.message:
        await callback.message.answer(
            _cards_today_report_text(
                lang,
                day=since,
                rows=rows,
                pending_reviews=pending_reviews,
                missing_pricing=missing_pricing,
                open_withdrawals=open_withdrawals,
            ),
            reply_markup=cards_admin_panel_kb(lang),
        )
    await callback.answer()


@router.callback_query(F.data == "cardx:panel:export_today")
async def export_today_cards_panel(callback: types.CallbackQuery) -> None:
    if not _is_cards_admin(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    user_doc, _ = await _ensure_card_user(callback.from_user)
    lang = _lang(user_doc)
    since, until = _today_utc_window()
    rows = await list_cards_for_daily_export(since=since, until=until, limit=2000)
    if not rows:
        await callback.answer(_t(lang, "No cards to export today.", "لا توجد بطاقات للتصدير اليوم."), show_alert=True)
        return
    files = _group_cards_export_files(rows, day=since)
    if callback.message:
        await callback.message.answer(
            _t(
                lang,
                f"Exporting {len(rows)} cards in {len(files)} files.",
                f"جاري تصدير {len(rows)} بطاقة ضمن {len(files)} ملف.",
            )
        )
        for filename, content, count in files:
            document = BufferedInputFile(content.encode("utf-8"), filename=filename)
            await callback.message.answer_document(
                document=document,
                caption=_t(lang, f"{filename} ({count} cards)", f"{filename} ({count} بطاقة)"),
            )
    await callback.answer("Exported")


@router.callback_query(F.data.startswith("cardx:admin:accept:"))
async def owner_accept_card(callback: types.CallbackQuery) -> None:
    if not _is_cards_admin(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    card_id = str(callback.data or "").split(":")[-1].strip()
    try:
        row = await accept_card(card_id, actor_user_id=str(callback.from_user.id))
        await callback.answer("Accepted", show_alert=False)
        if callback.message:
            await callback.message.answer(f"Accepted: {_fmt_card_line(row)}")
    except Exception:
        logger.exception("card-ex admin accept failed card_id=%s actor_id=%s", card_id, callback.from_user.id)
        await callback.answer("Action failed. Check logs.", show_alert=True)


@router.callback_query(F.data.startswith("cardx:admin:reject:"))
async def owner_reject_card(callback: types.CallbackQuery) -> None:
    if not _is_cards_admin(callback.from_user.id):
        await callback.answer("No permission", show_alert=True)
        return
    card_id = str(callback.data or "").split(":")[-1].strip()
    try:
        row = await reject_card(card_id, actor_user_id=str(callback.from_user.id))
        await callback.answer("Rejected", show_alert=False)
        if callback.message:
            await callback.message.answer(f"Rejected: {_fmt_card_line(row)}")
    except Exception:
        logger.exception("card-ex admin reject failed card_id=%s actor_id=%s", card_id, callback.from_user.id)
        await callback.answer("Action failed. Check logs.", show_alert=True)


@router.callback_query(F.data.startswith("cardx:admin:w"))
async def owner_withdraw_action(callback: types.CallbackQuery) -> None:
    if not _is_cards_admin(callback.from_user.id):
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
    except Exception:
        logger.exception(
            "card-ex admin withdrawal update failed withdrawal_id=%s status=%s actor_id=%s",
            withdrawal_id,
            status,
            callback.from_user.id,
        )
        await callback.answer("Action failed. Check logs.", show_alert=True)
