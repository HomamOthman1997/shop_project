from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.proxies.catalog_cache import encode_token
from utils.provider_alias import provider_public_id
from utils.translations import t


def _format_success_rate(value: float | int | str | None) -> str:
    try:
        rate = float(value if value is not None else 100.0)
    except Exception:
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


def proxy_type_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "proxy_type_unlimited"), callback_data="proxy:type:unlimited")],
            [InlineKeyboardButton(text=t(lang, "proxy_type_consumptive"), callback_data="proxy:type:consumptive")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:back_main")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")],
        ]
    )


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
        options = [(str(label).strip(), str(value).strip()) for label, value in (quick_country_options or []) if str(label).strip() and str(value).strip()]
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
                    switch_inline_query_current_chat=f'proxy city "{country}" ',
                    style="primary",
                )
            ]
        )
    elif not protocol:
        options = [(str(label).strip(), str(value).strip()) for label, value in (protocol_options or []) if str(label).strip() and str(value).strip()]
        options.sort(key=lambda item: (0 if item[1].strip().lower() == "http" else 1, item[0].lower()))
        for label, value in options[:20]:
            rows.append([InlineKeyboardButton(text=label, callback_data=f"proxy:set_protocol:{encode_token(value)}")])
    elif not provider:
        options = [(str(label).strip(), str(value).strip()) for label, value in (provider_options or []) if str(label).strip() and str(value).strip()]
        for label, value in options[:20]:
            rows.append([InlineKeyboardButton(text=label, callback_data=f"proxy:set_provider:{encode_token(value)}")])
    elif not period:
        options = [(str(label).strip(), str(value).strip()) for label, value in (period_options or []) if str(label).strip() and str(value).strip()]
        for label, value in options[:20]:
            rows.append([InlineKeyboardButton(text=label, callback_data=f"proxy:set_period:{encode_token(value)}")])
    elif not duration and any((duration_options or [])):
        options = [(str(label).strip(), str(value).strip()) for label, value in (duration_options or []) if str(label).strip() and str(value).strip()]
        for idx in range(0, min(len(options), 20), 2):
            pair = options[idx : idx + 2]
            rows.append(
                [
                    InlineKeyboardButton(text=label, callback_data=f"proxy:set_duration:{encode_token(value)}")
                    for label, value in pair
                ]
            )
    elif can_list:
        rows.append([InlineKeyboardButton(text=t(lang, "proxy_list_offers"), callback_data="proxy:list")])

    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:back_main")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_provider_kb(provider_codes: list[str], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for provider_code in provider_codes[:20]:
        token = encode_token(provider_code)
        rows.append([InlineKeyboardButton(text=str(provider_code), callback_data=f"proxy:set_provider:{token}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:search")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_period_kb(periods: list[str], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for period in periods[:30]:
        token = encode_token(period)
        rows.append([InlineKeyboardButton(text=str(period), callback_data=f"proxy:set_period:{token}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:search")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_offers_kb(offers: list[dict], lang: str, protocol: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    buttons: list[InlineKeyboardButton] = []
    for idx, offer in enumerate(offers[:20]):
        raw = offer.get("raw") if isinstance(offer.get("raw"), dict) else {}
        wanted_protocol = str(protocol or offer.get("protocol") or "http").strip().lower()
        port_value = raw.get("socks_port") if wanted_protocol == "socks" else raw.get("http_port")
        port_text = str(port_value or offer.get("offer_id") or "-").strip()
        buttons.append(InlineKeyboardButton(text=f"Port: {port_text}", callback_data=f"proxy:offer:{idx}"))
    for idx in range(0, len(buttons), 2):
        rows.append(buttons[idx : idx + 2])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:search")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_offer_actions_kb(lang: str, *, confirm_callback: str = "proxy:rent:confirm", confirm_text_key: str = "proxy_rent_now") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, confirm_text_key), callback_data=confirm_callback)],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:list")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")],
        ]
    )


def proxy_offer_duration_kb(duration_options: list[tuple[str, str]], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    options = [(str(label).strip(), str(value).strip()) for label, value in duration_options if str(label).strip() and str(value).strip()]
    for idx in range(0, min(len(options), 20), 2):
        pair = options[idx : idx + 2]
        rows.append(
            [
                InlineKeyboardButton(text=label, callback_data=f"proxy:offer_duration:{encode_token(value)}")
                for label, value in pair
            ]
        )
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:list")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")])
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
    rows.extend(
        [
            [InlineKeyboardButton(text=t(lang, "proxy_my_orders"), callback_data="proxy:my_orders")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:my_orders")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")],
        ]
    )
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
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:back_main")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
