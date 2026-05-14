from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def cards_main_menu(lang: str | None = None, *, is_admin: bool = False) -> ReplyKeyboardMarkup:
    is_ar = str(lang or "").lower().startswith("ar")
    sell = "بيع كرت" if is_ar else "Sell Card"
    wallet = "المحفظة" if is_ar else "Wallet"
    my_cards = "بطاقاتي" if is_ar else "My Cards"
    withdraw = "طلب سحب" if is_ar else "Withdraw"
    my_withdrawals = "سحوباتي" if is_ar else "My Withdrawals"
    support = "الدعم" if is_ar else "Support"
    admin_panel = "لوحة الإدارة" if is_ar else "Admin Panel"

    if is_admin:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=admin_panel)]],
            resize_keyboard=True,
        )

    keyboard = [
        [KeyboardButton(text=sell)],
        [KeyboardButton(text=wallet), KeyboardButton(text=my_cards)],
        [KeyboardButton(text=withdraw), KeyboardButton(text=my_withdrawals)],
        [KeyboardButton(text=support)],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def submit_brand_kb(top_brands: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for brand in top_brands:
        row.append(InlineKeyboardButton(text=brand, callback_data=f"cardx:brand:{brand}"))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Search Type", callback_data="cardx:brandsearch")])
    rows.append([InlineKeyboardButton(text="Cancel", callback_data="cardx:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def submit_brand_results_kb(brands: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for brand in brands:
        row.append(InlineKeyboardButton(text=brand, callback_data=f"cardx:brand:{brand}"))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Back", callback_data="cardx:brandtop")])
    rows.append([InlineKeyboardButton(text="Cancel", callback_data="cardx:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def denomination_kb(values: list[str] | None = None) -> InlineKeyboardMarkup:
    base = ["1", "2", "3", "4", "5", "6", "10", "15", "20", "25", "30", "40", "50", "100"]
    current = []
    seen = set()
    for item in (base + (values or [])):
        text = str(item).strip()
        if not text or text in seen:
            continue
        current.append(text)
        seen.add(text)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for value in current:
        row.append(InlineKeyboardButton(text=value, callback_data=f"cardx:den:{value}"))
        if len(row) >= 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Manual Value", callback_data="cardx:den:manual")])
    rows.append([InlineKeyboardButton(text="Back", callback_data="cardx:back:brand")])
    rows.append([InlineKeyboardButton(text="Cancel", callback_data="cardx:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def currency_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="USD", callback_data="cardx:cur:USD"),
                InlineKeyboardButton(text="EUR", callback_data="cardx:cur:EUR"),
                InlineKeyboardButton(text="GBP", callback_data="cardx:cur:GBP"),
            ],
            [InlineKeyboardButton(text="Back", callback_data="cardx:back:den")],
            [InlineKeyboardButton(text="Cancel", callback_data="cardx:cancel")],
        ]
    )


def region_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="USA", callback_data="cardx:reg:USA"),
                InlineKeyboardButton(text="UK", callback_data="cardx:reg:UK"),
                InlineKeyboardButton(text="CA", callback_data="cardx:reg:CA"),
            ],
            [
                InlineKeyboardButton(text="EU", callback_data="cardx:reg:EU"),
                InlineKeyboardButton(text="GLOBAL", callback_data="cardx:reg:GLOBAL"),
            ],
            [
                InlineKeyboardButton(text="Skip", callback_data="cardx:reg:GLOBAL"),
                InlineKeyboardButton(text="Back", callback_data="cardx:back:cur"),
            ],
            [InlineKeyboardButton(text="Cancel", callback_data="cardx:cancel")],
        ]
    )


def confirm_submit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Confirm", callback_data="cardx:confirm"),
                InlineKeyboardButton(text="Edit Code", callback_data="cardx:edit:code"),
            ],
            [
                InlineKeyboardButton(text="Edit Type", callback_data="cardx:back:brand"),
                InlineKeyboardButton(text="Cancel", callback_data="cardx:cancel"),
            ]
        ]
    )


def submit_code_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Back", callback_data="cardx:back:region")],
            [InlineKeyboardButton(text="Cancel", callback_data="cardx:cancel")],
        ]
    )


def submit_pin_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Back", callback_data="cardx:back:code")],
            [InlineKeyboardButton(text="Cancel", callback_data="cardx:cancel")],
        ]
    )


def withdraw_currency_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="USD", callback_data="cardx:wcur:USD"),
                InlineKeyboardButton(text="Local", callback_data="cardx:wcur:SYP"),
            ],
            [InlineKeyboardButton(text="Cancel", callback_data="cardx:cancel")],
        ]
    )


def withdraw_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Confirm", callback_data="cardx:wconfirm"),
                InlineKeyboardButton(text="Cancel", callback_data="cardx:cancel"),
            ]
        ]
    )


def admin_review_actions_kb(card_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Accept", callback_data=f"cardx:admin:accept:{card_id}"),
                InlineKeyboardButton(text="Reject", callback_data=f"cardx:admin:reject:{card_id}"),
            ]
        ]
    )


def admin_withdraw_actions_kb(withdrawal_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Approve", callback_data=f"cardx:admin:wapprove:{withdrawal_id}"),
                InlineKeyboardButton(text="Reject", callback_data=f"cardx:admin:wreject:{withdrawal_id}"),
            ],
            [
                InlineKeyboardButton(text="Paid", callback_data=f"cardx:admin:wpaid:{withdrawal_id}"),
            ],
        ]
    )


def cards_admin_panel_kb(lang: str | None = None) -> InlineKeyboardMarkup:
    is_ar = str(lang or "").lower().startswith("ar")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="تقرير اليوم" if is_ar else "Today's Report",
                    callback_data="cardx:panel:today_report",
                ),
                InlineKeyboardButton(
                    text="تصدير بطاقات اليوم" if is_ar else "Export Today's Cards",
                    callback_data="cardx:panel:export_today",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="تسعير ناقص" if is_ar else "Missing Pricing",
                    callback_data="cardx:panel:missing_pricing",
                ),
                InlineKeyboardButton(
                    text="بطاقات للمراجعة" if is_ar else "Cards Review",
                    callback_data="cardx:panel:reviews",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="طلبات السحب" if is_ar else "Withdrawals",
                    callback_data="cardx:panel:withdrawals",
                ),
            ],
        ]
    )


def admin_missing_pricing_kb(rows: list[dict], lang: str | None = None) -> InlineKeyboardMarkup:
    is_ar = str(lang or "").lower().startswith("ar")
    keyboard: list[list[InlineKeyboardButton]] = []
    for row in rows:
        label = f"{row.get('brand')} | {float(row.get('denomination') or 0):.2f} {row.get('currency')} | {row.get('region')}"
        keyboard.append([InlineKeyboardButton(text=label[:64], callback_data=f"cardx:pricepick:{row.get('_id')}")])
    keyboard.append(
        [
            InlineKeyboardButton(
                text="العودة للوحة" if is_ar else "Back to Panel",
                callback_data="cardx:panel:open",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
