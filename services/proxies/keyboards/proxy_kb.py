from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.proxies.catalog_cache import encode_token
from utils.provider_alias import provider_public_id
from utils.translations import t


def _format_success_rate(value: float | int | str | None) -> str:
    try:
        rate = float(value if value is not None else 100.0)
    except (TypeError, ValueError):
        rate = 100.0
    if rate < 0:
        rate = 0.0
    if rate > 100:
        rate = 100.0
    if rate.is_integer():
        return f"{int(rate)}%"
    return f"{rate:.1f}%"


def _provider_success_label(lang: str, value: float | int | str | None = None) -> str:
    return f"{t(lang, 'success_rate_short')}: {_format_success_rate(value)}"


def _nav_rows(lang: str, *, back_callback: str) -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text=t(lang, "back"), callback_data=back_callback)],
        [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")],
    ]


def _clean_labeled_options(options: list[tuple[str, str]] | None) -> list[tuple[str, str]]:
    return [
        (str(label).strip(), str(value).strip())
        for label, value in (options or [])
        if str(label).strip() and str(value).strip()
    ]


def proxy_type_kb(
    lang: str,
    *,
    show_unlimited: bool = True,
    show_consumptive: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if show_unlimited:
        rows.append([InlineKeyboardButton(text=t(lang, "proxy_type_unlimited"), callback_data="proxy:type:unlimited")])
    if show_consumptive:
        rows.append([InlineKeyboardButton(text=t(lang, "proxy_type_consumptive"), callback_data="proxy:type:consumptive")])
    rows.extend(_nav_rows(lang, back_callback="proxy:back_step"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_entry_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t(lang, "proxy_buy_now"), callback_data="proxy:type_menu"),
                InlineKeyboardButton(text=t(lang, "proxy_my_orders"), callback_data="proxy:my_orders"),
            ],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:back_main")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")],
        ]
    )


def proxy_search_kb(
    lang: str,
    *,
    country: str | None = None,
    state: str | None = None,
    city: str | None = None,
    protocol: str | None = None,
    provider: str | None = None,
    period: str | None = None,
    duration: str | None = None,
    require_state: bool = False,
    require_city: bool = False,
    can_list: bool = False,
    protocol_options: list[tuple[str, str]] | None = None,
    provider_options: list[tuple[str, str]] | None = None,
    period_options: list[tuple[str, str]] | None = None,
    duration_options: list[tuple[str, str]] | None = None,
    quick_country_options: list[tuple[str, str]] | None = None,
    quick_location_options: list[tuple[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if not country:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "proxy_search_country"),
                    switch_inline_query_current_chat="proxy country ",
                    style="primary",
                )
            ]
        )
        options = _clean_labeled_options(quick_country_options)
        for idx in range(0, min(len(options), 4), 2):
            pair = options[idx : idx + 2]
            rows.append([InlineKeyboardButton(text=label, callback_data=value) for label, value in pair])
    elif require_state and not state:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "proxy_search_state_city"),
                    switch_inline_query_current_chat=f'proxy state "{country}" ',
                    style="primary",
                )
            ]
        )
    elif require_city and not city:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "proxy_search_state_city"),
                    switch_inline_query_current_chat=f'proxy state "{country}" ',
                    style="primary",
                )
            ]
        )
    elif can_list:
        rows.append([InlineKeyboardButton(text=t(lang, "proxy_list_offers"), callback_data="proxy:list")])

    rows.extend(_nav_rows(lang, back_callback="proxy:back_main"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_provider_kb(provider_codes: list[str], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for provider_code in provider_codes[:20]:
        token = encode_token(provider_code)
        rows.append([InlineKeyboardButton(text=str(provider_code), callback_data=f"proxy:set_provider:{token}")])
    rows.extend(_nav_rows(lang, back_callback="proxy:back_step"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_period_kb(periods: list[str], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for period in periods[:30]:
        token = encode_token(period)
        rows.append([InlineKeyboardButton(text=str(period), callback_data=f"proxy:set_period:{token}")])
    rows.extend(_nav_rows(lang, back_callback="proxy:search"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_offers_kb(offers: list[dict], lang: str, protocol: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, offer in enumerate(offers[:20]):
        raw = offer.get("raw") if isinstance(offer.get("raw"), dict) else {}
        button_text = str(raw.get("button_label") or offer.get("title") or offer.get("offer_id") or "-").strip()
        rows.append([InlineKeyboardButton(text=button_text, callback_data=f"proxy:offer:{idx}")])
    rows.extend(_nav_rows(lang, back_callback="proxy:back_step"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_offer_actions_kb(lang: str, *, confirm_callback: str = "proxy:rent:confirm", confirm_text_key: str = "proxy_rent_now") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, confirm_text_key), callback_data=confirm_callback)],
            *_nav_rows(lang, back_callback="proxy:list"),
        ]
    )


def proxy_offer_duration_kb(duration_options: list[tuple[str, str]], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    options = _clean_labeled_options(duration_options)
    for idx in range(0, min(len(options), 20), 2):
        pair = options[idx : idx + 2]
        rows.append(
            [
                InlineKeyboardButton(text=label, callback_data=f"proxy:offer_duration:{encode_token(value)}")
                for label, value in pair
            ]
        )
    rows.extend(_nav_rows(lang, back_callback="proxy:list"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_password_input_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:password_back")],
        ]
    )


def proxy_order_actions_kb(order_id: str, lang: str, *, can_reconfigure: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t(lang, "proxy_change_only"), callback_data=f"proxy:order:change:{order_id}")],
        [InlineKeyboardButton(text=t(lang, "proxy_change_check"), callback_data=f"proxy:order:check:{order_id}")],
    ]
    if can_reconfigure:
        rows.append([InlineKeyboardButton(text=t(lang, "proxy_change_location_protocol"), callback_data=f"proxy:order:reconfigure:{order_id}")])
    rows.append([InlineKeyboardButton(text=t(lang, "proxy_my_orders"), callback_data="proxy:my_orders")])
    rows.extend(_nav_rows(lang, back_callback="proxy:my_orders"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_my_orders_kb(orders: list[dict], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders[:20]:
        raw_id = str(order.get("_id") or "")
        order_id = raw_id if raw_id else str(order.get("order_id") or "")
        provider = provider_public_id(order.get("provider"))
        status = str(order.get("status") or "-")
        label = f"{provider} | {status} | {order_id[:12]}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"proxy:order:open:{order_id}")])
    rows.extend(_nav_rows(lang, back_callback="proxy:back_main"))
    return InlineKeyboardMarkup(inline_keyboard=rows)
