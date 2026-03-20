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


def proxy_search_kb(lang: str, *, country: str | None = None, state: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=t(lang, "proxy_search_country"), switch_inline_query_current_chat="proxy country ")],
    ]

    if country:
        country_tok = encode_token(country)
        rows.append(
            [InlineKeyboardButton(text=t(lang, "proxy_search_city"), switch_inline_query_current_chat=f"proxy city {country_tok} ")]
        )

    rows.append([InlineKeyboardButton(text=t(lang, "proxy_list_offers"), callback_data="proxy:list")])
    rows.append(
        [
            InlineKeyboardButton(text=t(lang, "proxy_refresh_catalog"), callback_data="proxy:refresh_catalog"),
            InlineKeyboardButton(text=t(lang, "proxy_my_orders"), callback_data="proxy:my_orders"),
        ]
    )
    rows.append([InlineKeyboardButton(text=t(lang, "proxy_switch_type"), callback_data="proxy:type_menu")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:back_main")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_offers_kb(offers: list[dict], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, offer in enumerate(offers[:20]):
        title = str(offer.get("title") or "Proxy")
        provider = provider_public_id(offer.get("provider"))
        price = float(offer.get("price") or 0.0)
        usage_count = int(offer.get("usage_count") or 0)
        success_label = _provider_success_label(lang, offer.get("success_rate", 100))
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{provider} | U:{usage_count} | {success_label} | {title[:14]} | {price:.2f}$",
                    callback_data=f"proxy:offer:{idx}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:search")])
    rows.append([InlineKeyboardButton(text=t(lang, "back_to_countries"), callback_data="proxy:search")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_offer_actions_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "proxy_rent_now"), callback_data="proxy:rent:confirm")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:list")],
            [InlineKeyboardButton(text=t(lang, "back_to_countries"), callback_data="proxy:search")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")],
        ]
    )


def proxy_order_actions_kb(order_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "proxy_change_only"), callback_data=f"proxy:order:change:{order_id}")],
            [InlineKeyboardButton(text=t(lang, "proxy_change_check"), callback_data=f"proxy:order:check:{order_id}")],
            [InlineKeyboardButton(text=t(lang, "proxy_my_orders"), callback_data="proxy:my_orders")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:search")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")],
        ]
    )


def proxy_my_orders_kb(orders: list[dict], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders[:20]:
        raw_id = str(order.get("_id") or "")
        if not raw_id:
            continue
        provider = provider_public_id(order.get("provider"))
        endpoint = str(order.get("proxy_endpoint") or "-")
        expiry = str(order.get("proxy_expires_at") or "-")
        button_text = f"{provider} | {endpoint[:18]} | {expiry[:16]}"
        rows.append(
            [InlineKeyboardButton(text=button_text, callback_data=f"proxy:order:open:{raw_id}")]
        )
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="proxy:search")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="proxy:back_main", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
