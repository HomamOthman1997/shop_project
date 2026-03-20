from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import re

from config import settings
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.manager import RENTAL_UNLIMITED_SERVICE_KEY
from utils.provider_alias import provider_public_id
from utils.services_keyboard import build_services_keyboard
from utils.translations import t

_COUNTRY_CODE_TO_ISO = {
    str(item.get("code")): str(item.get("iso") or "").upper()
    for item in COUNTRIES_LIST
    if str(item.get("code") or "").strip()
}


def _icon(icon_id: str | None) -> str | None:
    value = str(icon_id or "").strip()
    return value or None


_ICON_TEMP_NUMBERS = _icon(getattr(settings, "tg_icon_temp_numbers", None))
_ICON_RENTAL_NUMBERS = _icon(getattr(settings, "tg_icon_rental_numbers", None))
_ICON_CONFIRM = _icon(getattr(settings, "tg_icon_confirm", None))
_ICON_CANCEL = _icon(getattr(settings, "tg_icon_cancel", None))
_SUCCESS_RATE_DISPLAY_MIN_ATTEMPTS = max(
    1,
    int(getattr(settings, "numbers_success_rate_display_min_attempts", 5) or 5),
)


def _format_success_rate(value: float | int | str | None, attempts: int | None = None) -> str:
    try:
        attempts_val = int(attempts or 0)
    except Exception:
        attempts_val = 0
    if attempts_val < _SUCCESS_RATE_DISPLAY_MIN_ATTEMPTS:
        return "-"
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


def _provider_success_rate_label(
    lang: str,
    value: float | int | str | None = None,
    attempts: int | None = None,
) -> str:
    return f"{t(lang, 'success_rate_short')}: {_format_success_rate(value, attempts=attempts)}"


def _provider_sort_key(provider_code: str | None) -> tuple[int, str, str]:
    code = str(provider_code or "").strip().lower()
    public_id = provider_public_id(code)
    rank = 9999
    if public_id.startswith("S"):
        suffix = public_id[1:]
        if suffix.isdigit():
            rank = int(suffix)
    return (rank, public_id, code)


def _country_iso(country_code: str | None) -> str:
    if not country_code:
        return ""
    return _COUNTRY_CODE_TO_ISO.get(str(country_code).strip(), "").upper()


def _duration_label_compact(hours: int) -> str:
    if hours > 0 and hours % 24 == 0:
        return f"{hours // 24}D"
    return f"{hours}H"


def _normalize_duration_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    # 1d -> 1D, 12h -> 12H
    text = re.sub(r"(\d+)\s*([dh])\b", lambda m: f"{m.group(1)}{m.group(2).upper()}", text, flags=re.IGNORECASE)
    return text


def _duration_price_label(duration_text: str, price: float) -> str:
    return f"{_normalize_duration_text(duration_text)} | {float(price):.2f}$"


def _price_dual_label(price_usd: float, usd_to_syp: float | None = None) -> str:
    usd_text = f"{float(price_usd):.2f}$"
    try:
        rate = float(usd_to_syp or 0)
    except Exception:
        rate = 0.0
    if rate <= 0:
        return usd_text
    syp_value = float(price_usd) * rate
    return f"{usd_text} ({syp_value:.1f} SYP)"


def _can_show_unlimited(country_code: str | None) -> bool:
    return _country_iso(country_code) in {"US", "CA", "GB"}


def number_type_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "temp_numbers"),
                    callback_data="flow:type:temp",
                    style="primary",
                    icon_custom_emoji_id=_ICON_TEMP_NUMBERS,
                ),
                InlineKeyboardButton(
                    text=t(lang, "rental_numbers"),
                    callback_data="flow:type:rental",
                    style="success",
                    icon_custom_emoji_id=_ICON_RENTAL_NUMBERS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "cancel"),
                    callback_data="flow:cancel",
                    style="danger",
                    icon_custom_emoji_id=_ICON_CANCEL,
                )
            ],
        ]
    )


def rental_home_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "rental_add_number"), callback_data="flow:rental:add", style="success")],
            [InlineKeyboardButton(text=t(lang, "rental_my_numbers"), callback_data="flow:rental:my", style="primary")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:main:back")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)],
        ]
    )


def country_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "search_country"), switch_inline_query_current_chat="country ", style="primary")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:country:entry_back")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)],
        ]
    )


def state_kb(country_code: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "no_state"), callback_data=f"flow:state:{country_code}:none")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:country:back")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)],
        ]
    )


def service_kb(lang: str = "en", num_type: str = "temp", country_code: str | None = None) -> InlineKeyboardMarkup:
    base_kb = build_services_keyboard()
    search_button = InlineKeyboardButton(text=t(lang, "search_service"), switch_inline_query_current_chat="service ", style="primary")
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    kb.inline_keyboard.append([search_button])
    if num_type == "rental" and _can_show_unlimited(country_code):
        kb.inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "unlimited_rental_service"),
                    callback_data=f"flow:service:{RENTAL_UNLIMITED_SERVICE_KEY}",
                )
            ]
        )
    for row in base_kb.inline_keyboard:
        kb.inline_keyboard.append(row)
    kb.inline_keyboard.append([InlineKeyboardButton(text=t(lang, "back_to_countries"), callback_data="flow:country:back")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)])
    return kb


def provider_choice_kb(prices: dict, lang: str = "en", usd_to_syp: float | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for provider_code, info in sorted(prices.items(), key=lambda kv: _provider_sort_key(kv[0])):
        price_val = float(info.get("price", 0) or 0)
        can_buy = bool(info.get("available_for_buy", True)) and bool(str(info.get("api_service_name") or "").strip()) and price_val > 0
        success_rate_label = _format_success_rate(
            info.get("success_rate", 100),
            attempts=info.get("success_attempts", 0),
        )
        price_label = _price_dual_label(price_val, usd_to_syp=usd_to_syp) if can_buy else "N/A"
        kb.inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{provider_public_id(provider_code)} | {price_label}",
                    callback_data=f"buy_provider:{provider_code}",
                ),
                InlineKeyboardButton(
                    text=f"⭐ {success_rate_label}",
                    callback_data=f"buy_provider:{provider_code}",
                ),
            ]
        )
    kb.inline_keyboard.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:service:back")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)])
    return kb


def temp_wait_timeout_kb(
    order_id: str,
    lang: str = "en",
    *,
    allow_refresh: bool = True,
    allow_cancel: bool = True,
    allow_replace: bool = False,
    refresh_cooldown_sec: int = 0,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if allow_refresh:
        if int(refresh_cooldown_sec or 0) > 0:
            refresh_text = t(lang, "temp_refresh_wait").format(seconds=int(refresh_cooldown_sec))
        else:
            refresh_text = t(lang, "temp_refresh_now")
        rows.append([InlineKeyboardButton(text=refresh_text, callback_data=f"temp:refresh:{order_id}")])
    if allow_cancel:
        rows.append([InlineKeyboardButton(text=t(lang, "temp_cancel_refund"), callback_data=f"temp:cancel:{order_id}", style="danger", icon_custom_emoji_id=_ICON_CANCEL)])
    if allow_replace:
        rows.append([InlineKeyboardButton(text=t(lang, "temp_request_another"), callback_data=f"temp:replace:{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def temp_code_received_kb(order_id: str, lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "temp_second_code"), callback_data=f"temp:second:{order_id}")],
            [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="flow:main:back")],
        ]
    )


def rental_providers_kb(
    provider_rows: list[dict],
    lang: str = "en",
    provider_options: dict[str, list[dict]] | None = None,
    usd_to_syp: float | None = None,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    provider_options = provider_options or {}
    unlimited_mode = any(str(row.get("pricing_mode") or "").strip().lower() == "monthly" for row in provider_rows)

    if unlimited_mode:
        # Unlimited view: force provider ordering so S3 appears first.
        provider_order = {"s3": 0, "s2": 1, "s1": 2, "s4": 3, "s5": 4}
        ordered_rows = sorted(
            provider_rows,
            key=lambda item: (
                provider_order.get(str(item.get("provider") or "").strip().lower(), 99),
                _provider_sort_key(item.get("provider")),
            ),
        )
    else:
        ordered_rows = sorted(provider_rows, key=lambda item: _provider_sort_key(item.get("provider")))

    for row in ordered_rows:
        provider_code = str(row.get("provider") or "").strip().lower()
        if not provider_code:
            continue
        public_id = provider_public_id(provider_code)
        options = provider_options.get(provider_code) or []
        pricing_mode = str(row.get("pricing_mode") or "").strip().lower()
        avg_price = float(row.get("avg_price") or 0.0)
        country_label = str(row.get("country_label") or "").strip() or "US"

        header_text = public_id
        header_style = None
        has_monthly_summary = bool((not options) and pricing_mode == "monthly" and avg_price > 0)
        if has_monthly_summary:
            header_text = f"{public_id} | Monthly price ({country_label}): {avg_price:.2f}$"
        if has_monthly_summary:
            header_style = "success" if public_id == "S2" else None
        elif unlimited_mode and provider_code == "s3":
            header_text = "Server 1"
            header_style = "success"
        elif public_id == "S1":
            header_text = "Server 1"
            header_style = "primary"
        elif public_id == "S2":
            header_text = "Server 2"
            header_style = "success"

        # Header button (display grouping for provider).
        kb.inline_keyboard.append(
            [InlineKeyboardButton(text=header_text, callback_data=f"renthead:{provider_code}", style=header_style)]
        )

        best_by_duration: dict[int, float] = {}
        for opt in options:
            try:
                dur = int(opt.get("duration") or 0)
                price = float(opt.get("price") or 0)
            except Exception:
                continue
            if dur <= 0 or price <= 0:
                continue
            prev = best_by_duration.get(dur)
            if prev is None or price < prev:
                best_by_duration[dur] = price

        def _mk_btn(dur: int) -> InlineKeyboardButton | None:
            if dur not in best_by_duration:
                return None
            label = f"{_normalize_duration_text(_duration_label_compact(dur))} | {_price_dual_label(best_by_duration[dur], usd_to_syp=usd_to_syp)}"
            return InlineKeyboardButton(
                text=label,
                callback_data=f"rentpick:{provider_code}:{dur}",
            )

        if unlimited_mode and provider_code == "s3":
            # Unlimited: expose only 1D / 7D / 28D for S3.
            fixed_durations = (24, 168, 672)
            row_buttons = [btn for btn in (_mk_btn(d) for d in fixed_durations) if btn is not None]
            if row_buttons:
                kb.inline_keyboard.append(row_buttons)
        elif public_id == "S1":
            # Keep hours on first row, and move day-based durations to following rows.
            hour_row: list[InlineKeyboardButton] = []
            for d in (2, 4, 12):
                btn = _mk_btn(d)
                if btn is not None:
                    hour_row.append(btn)
            if hour_row:
                kb.inline_keyboard.append(hour_row)

            day_durations = [d for d in sorted(best_by_duration.keys()) if d >= 24 and d % 24 == 0]
            for i in range(0, len(day_durations), 3):
                row_buttons = [btn for btn in (_mk_btn(d) for d in day_durations[i : i + 3]) if btn is not None]
                if row_buttons:
                    kb.inline_keyboard.append(row_buttons)

            # Any non-day extras (uncommon durations) after day rows.
            covered = {2, 4, 12, *day_durations}
            extras = [d for d in sorted(best_by_duration.keys()) if d not in covered]
            for i in range(0, len(extras), 3):
                row_buttons = [btn for btn in (_mk_btn(d) for d in extras[i : i + 3]) if btn is not None]
                if row_buttons:
                    kb.inline_keyboard.append(row_buttons)
        elif public_id == "S2":
            # Keep 30D strictly in the second row.
            first_row_durations = [24, 72, 168, 336]  # 1d, 3d, 7d, 14d
            second_row_durations = [720, 2160, 8760]  # 30d, 90d, 365d

            main_buttons: list[InlineKeyboardButton] = []
            for d in first_row_durations:
                if d not in best_by_duration:
                    continue
                btn = _mk_btn(d)
                if btn is not None:
                    main_buttons.append(btn)
            if main_buttons:
                for i in range(0, len(main_buttons), 3):
                    kb.inline_keyboard.append(main_buttons[i : i + 3])

            # Second row: show 30d/90d/365d (live if available, placeholder otherwise for long durations).
            long_row: list[InlineKeyboardButton] = []
            if 720 in best_by_duration:
                btn = _mk_btn(720)
                if btn is not None:
                    long_row.append(btn)
            for d in (2160, 8760):
                if d in best_by_duration:
                    btn = _mk_btn(d)
                    if btn is not None:
                        long_row.append(btn)
                else:
                    long_row.append(
                        InlineKeyboardButton(
                            text=f"{_duration_label_compact(d)} | XX.X$",
                            callback_data=f"rentna:{provider_code}:{d}",
                        )
                    )
            if long_row:
                kb.inline_keyboard.append(long_row)
        else:
            durations = sorted(best_by_duration.keys())
            for i in range(0, len(durations), 3):
                row_buttons = [btn for btn in (_mk_btn(d) for d in durations[i : i + 3]) if btn is not None]
                if row_buttons:
                    kb.inline_keyboard.append(row_buttons)

    kb.inline_keyboard.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:service:back")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)])
    return kb


def confirm_buy_kb(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data="buy:confirm", style="success", icon_custom_emoji_id=_ICON_CONFIRM)],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:service:back")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="buy:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)],
        ]
    )


def rental_options_kb(options: list[dict], lang: str = "en", usd_to_syp: float | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[])

    def _duration_label(hours: int) -> str:
        if hours > 0 and hours % 24 == 0:
            return f"{hours // 24}D"
        return f"{hours}H"

    def _build_option_label(option: dict, compact: bool = False) -> str:
        duration_label = str(option.get("duration_label") or "").strip()
        if duration_label:
            duration_text = _normalize_duration_text(duration_label)
        else:
            duration_hours = int(option.get("duration", 0) or 0)
            duration_text = _duration_label(duration_hours) if duration_hours > 0 else t(lang, "provider_duration")
        price_dual = _price_dual_label(float(option.get("price", 0) or 0), usd_to_syp=usd_to_syp)
        if compact:
            return f"{duration_text} | {price_dual}"
        label = f"{duration_text} | {price_dual} | #{int(option.get('count', 0))}"
        return label

    provider_code = str((options[0] if options else {}).get("provider") or "").strip().lower()
    if provider_code == "herosms":
        indexed = list(enumerate(options))
        indexed.sort(
            key=lambda item: (
                int(item[1].get("duration", 0) or 0),
                float(item[1].get("price", 0) or 0),
            )
        )
        row: list[InlineKeyboardButton] = []
        for idx, option in indexed:
            row.append(
                InlineKeyboardButton(
                    text=_build_option_label(option, compact=True),
                    callback_data=f"rentopt:{idx}",
                )
            )
            if len(row) >= 2:
                kb.inline_keyboard.append(row)
                row = []
        if row:
            kb.inline_keyboard.append(row)
    else:
        for idx, option in enumerate(options):
            label = _build_option_label(option, compact=False)
            kb.inline_keyboard.append([InlineKeyboardButton(text=label, callback_data=f"rentopt:{idx}")])

    kb.inline_keyboard.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:rental_providers:back")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)])
    return kb


def rental_confirm_kb(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data="rent:confirm", style="success", icon_custom_emoji_id=_ICON_CONFIRM)],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:rental_providers:back")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="rent:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)],
        ]
    )


def rental_warning_kb(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data="rent:confirm:final", style="success", icon_custom_emoji_id=_ICON_CONFIRM)],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="rent:confirm:back")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="rent:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)],
        ]
    )


def tv_duration_kb(duration_rows: list[dict], lang: str = "en", usd_to_syp: float | None = None) -> InlineKeyboardMarkup:
    order = (
        "oneDay",
        "threeDay",
        "sevenDay",
        "fourteenDay",
        "thirtyDay",
        "ninetyDay",
        "oneYear",
    )
    by_key = {str(row.get("tv_duration_key") or "").strip(): row for row in duration_rows}
    row1: list[InlineKeyboardButton] = []
    row2: list[InlineKeyboardButton] = []
    for idx, key in enumerate(order):
        row = by_key.get(key)
        if not row:
            continue
        label = _normalize_duration_text(str(row.get("duration_label") or "").strip() or key)
        try:
            price = float(row.get("price") or 0.0)
        except Exception:
            price = 0.0
        btn = InlineKeyboardButton(
            text=f"{_normalize_duration_text(label)} | {_price_dual_label(price, usd_to_syp=usd_to_syp)}",
            callback_data=f"rtv:dur:{key}",
        )
        if idx <= 3:
            row1.append(btn)
        else:
            row2.append(btn)

    keyboard_rows: list[list[InlineKeyboardButton]] = []
    if row1:
        keyboard_rows.append(row1)
    if row2:
        keyboard_rows.append(row2)
    keyboard_rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:rental_providers:back")])
    keyboard_rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def tv_renewable_kb(
    nonrenew_price: float | None,
    renew_price: float | None,
    lang: str = "en",
    usd_to_syp: float | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if nonrenew_price is not None and nonrenew_price > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{t(lang, 'tv_non_renewable')} - {_price_dual_label(float(nonrenew_price), usd_to_syp=usd_to_syp)}",
                    callback_data="rtv:ren:0",
                )
            ]
        )
    if renew_price is not None and renew_price > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{t(lang, 'tv_renewable')} - {_price_dual_label(float(renew_price), usd_to_syp=usd_to_syp)}",
                    callback_data="rtv:ren:1",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="rtv:ren:back")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tv_state_choice_kb(base_price: float, lang: str = "en", usd_to_syp: float | None = None) -> InlineKeyboardMarkup:
    continue_without_state = InlineKeyboardButton(
        text=f"{t(lang, 'tv_continue_without_state')} - {_price_dual_label(float(base_price), usd_to_syp=usd_to_syp)}",
        callback_data="rtv:state:none",
    )
    select_state = InlineKeyboardButton(
        text=f"{t(lang, 'tv_select_state_plus2')} - {_price_dual_label(float(base_price + 2.0), usd_to_syp=usd_to_syp)}",
        callback_data="rtv:state:with",
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [select_state],
            [continue_without_state],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data="rtv:state:back")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger", icon_custom_emoji_id=_ICON_CANCEL)],
        ]
    )

