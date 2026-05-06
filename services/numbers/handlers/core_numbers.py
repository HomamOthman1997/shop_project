from contextvars import ContextVar

import asyncio
import time
from urllib.parse import unquote
from aiogram import BaseMiddleware, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import settings
from database.user_repo import get_user
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.keyboards.core_numbers_kb import (
    country_kb,
    no_availability_kb,
    number_type_kb,
    provider_choice_kb,
    rental_home_kb,
    rental_confirm_kb,
    rental_providers_kb,
    rental_options_kb,
    service_kb,
    tv_duration_kb,
    tv_renewable_kb,
    tv_state_choice_kb,
)
from services.numbers.manager import RENTAL_UNLIMITED_SERVICE_KEY, get_all_prices, get_all_rental_prices
from services.numbers.manager import TEMP_NOT_LISTED_SERVICE_KEY, provider_allows_rental
from services.numbers.handlers.core_numbers_buy import _handle_rental_exit_callback_guard
from services.numbers.service_families import normalize_service_key
from services.numbers.states.core_numbers_states import NumberFlow
from services.numbers.data import tv_area_codes
from utils.bot_menu_context import menu_for_current_bot
from utils.provider_alias import provider_public_id
from utils.translations import t
from utils.user_money import format_usd, format_usd_compact
from utils.usage_stats_manager import increment_usage

router = Router()
_CURRENT_CALLBACK: ContextVar[types.CallbackQuery | None] = ContextVar("core_numbers_current_callback", default=None)


class _CallbackContextMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        token = _CURRENT_CALLBACK.set(event if isinstance(event, types.CallbackQuery) else None)
        try:
            return await handler(event, data)
        finally:
            _CURRENT_CALLBACK.reset(token)


router.callback_query.middleware(_CallbackContextMiddleware())
_COUNTRY_ISO = {
    str(item.get("code")): str(item.get("iso") or "").upper()
    for item in COUNTRIES_LIST
    if str(item.get("code") or "").strip()
}
_VALID_COUNTRY_CODES = set(_COUNTRY_ISO.keys())
_INLINE_SERVICE_QUERY_PREFIX = "query:"
_QUICK_COUNTRY_PREFIX = "flow:quickcountry:"
_QUICK_COUNTRY_SEARCH_CALLBACK = "flow:quickcountry:search"
_CHEAP_COUNTRY_CACHE_TTL_SEC = 300
_CHEAP_COUNTRY_CACHE: dict[str, tuple[float, list[dict[str, object]]]] = {}
_CHEAP_COUNTRY_ISOS = (
    "US",
    "CA",
    "GB",
    "NL",
    "LV",
    "SE",
    "PT",
    "EE",
    "RO",
    "DK",
    "PL",
    "FR",
    "DE",
    "UA",
    "IE",
    "LT",
    "HR",
    "AT",
    "ES",
    "SI",
    "BE",
    "BG",
    "HU",
    "IT",
    "GR",
    "SK",
    "FI",
    "NO",
    "CZ",
)


async def _hide_reply_keyboard(message: types.Message, lang: str) -> None:
    try:
        await message.answer(
            t(lang, "keyboard_cleanup_placeholder"),
            reply_markup=types.ReplyKeyboardRemove(),
        )
    except Exception:
        pass


async def _safe_edit_text(
    message: types.Message,
    text: str,
    *,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
):
    try:
        return await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return message
        raise


async def _loading_text_animator(
    bot,
    *,
    chat_id: int,
    message_id: int,
    base_text: str,
    stop_event: asyncio.Event,
    max_dots: int = 10,
    interval_sec: float = 1.0,
) -> None:
    dots = 1
    while not stop_event.is_set():
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{base_text}{'.' * dots}",
                reply_markup=None,
            )
        except TelegramBadRequest:
            return
        except Exception:
            return
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
            return
        except asyncio.TimeoutError:
            dots = 1 if dots >= max_dots else dots + 1


def _start_loading_text_animator(
    bot,
    *,
    chat_id: int,
    message_id: int,
    base_text: str,
) -> tuple[asyncio.Event, asyncio.Task]:
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        _loading_text_animator(
            bot,
            chat_id=chat_id,
            message_id=message_id,
            base_text=base_text,
            stop_event=stop_event,
        )
    )
    return stop_event, task


async def _stop_loading_text_animator(stop_event: asyncio.Event | None, task: asyncio.Task | None) -> None:
    if stop_event is not None:
        stop_event.set()
    if task is None:
        return
    try:
        await task
    except Exception:
        pass


async def _safe_callback_answer(
    callback: types.CallbackQuery | str | None = None,
    text: str | None = None,
    *,
    show_alert: bool | None = None,
) -> bool:
    target_callback: types.CallbackQuery | None
    if callback is not None and hasattr(callback, "answer"):
        target_callback = callback
    else:
        target_callback = _CURRENT_CALLBACK.get()
        if isinstance(callback, str) and text is None:
            text = callback

    if target_callback is None:
        return False

    kwargs: dict[str, object] = {}
    if text is not None:
        kwargs["text"] = text
    if show_alert is not None:
        kwargs["show_alert"] = show_alert
    try:
        await target_callback.answer(**kwargs)
        return True
    except TelegramBadRequest as exc:
        msg = str(exc).lower()
        if "query is too old" in msg or "query id is invalid" in msg or "response timeout expired" in msg:
            return False
        raise


def _country_iso(country_code: str | None) -> str:
    if not country_code:
        return ""
    return _COUNTRY_ISO.get(str(country_code).strip(), "").upper()


def _normalize_service(value: str) -> str:
    return normalize_service_key(value or "")


async def _resolve_usd_to_syp_rate() -> float:
    try:
        fallback = float(getattr(settings, "numbers_usd_to_syp_fallback", 118) or 118)
    except Exception:
        fallback = 118.0
    return fallback if fallback > 0 else 118.0


async def _return_to_main_menu(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if not callback.message:
        return
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    bot_id = (await callback.bot.get_me()).id

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(t(lang, "main_menu"), reply_markup=await menu_for_current_bot(lang, bot_id))


async def _redirect_to_country_selection(
    chat_id: int,
    bot,
    state: FSMContext,
    *,
    lang: str,
    num_type: str,
    last_msg_id: int | None,
) -> None:
    text = _country_entry_text(lang, num_type)
    if last_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_msg_id,
                text=text,
                reply_markup=country_kb(lang),
            )
        except Exception:
            pass
    await state.set_state(NumberFlow.country)


def _is_unlimited_service(service_key: str) -> bool:
    return _normalize_service(service_key) == _normalize_service(RENTAL_UNLIMITED_SERVICE_KEY)


def _service_prompt_bold(lang: str) -> str:
    return f"<b>{t(lang, 'choose_service_prompt')}</b>"


def _country_display_name(country_code: str | None) -> str:
    raw = str(country_code or "").strip()
    if not raw:
        return "-"
    for item in COUNTRIES_LIST:
        if str(item.get("code") or "").strip() == raw:
            return str(item.get("name") or raw).strip() or raw
    return raw


def _country_code_by_iso() -> dict[str, str]:
    out: dict[str, str] = {}
    for item in COUNTRIES_LIST:
        code = str(item.get("code") or "").strip()
        iso = str(item.get("iso") or "").strip().upper()
        if code and iso and code in _VALID_COUNTRY_CODES:
            out.setdefault(iso, code)
    return out


def _cheap_country_candidate_codes() -> list[str]:
    by_iso = _country_code_by_iso()
    out: list[str] = []
    seen: set[str] = set()
    for iso in _CHEAP_COUNTRY_ISOS:
        code = by_iso.get(str(iso or "").upper())
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _best_available_country_price(prices: dict) -> float | None:
    best: float | None = None
    for info in (prices or {}).values():
        if not isinstance(info, dict):
            continue
        if not bool(info.get("available_for_buy", True)):
            continue
        try:
            price = float(info.get("price") or 0.0)
        except Exception:
            price = 0.0
        if price <= 0:
            continue
        if best is None or price < best:
            best = price
    return best


async def _cheap_country_options_for_service(service_key: str, limit: int = 10) -> list[dict[str, object]]:
    cache_key = _normalize_service(service_key)
    now_ts = time.time()
    cached = _CHEAP_COUNTRY_CACHE.get(cache_key)
    if cached and (now_ts - cached[0]) <= _CHEAP_COUNTRY_CACHE_TTL_SEC:
        return list(cached[1])[:limit]

    sem = asyncio.Semaphore(6)

    async def _fetch_country(country_code: str) -> dict[str, object] | None:
        async with sem:
            try:
                prices = await asyncio.wait_for(get_all_prices(service_key, country_code, "none"), timeout=5.0)
            except Exception:
                return None
            price = _best_available_country_price(prices)
            if price is None:
                return None
            return {
                "code": country_code,
                "name": _country_display_name(country_code),
                "price": float(price),
            }

    tasks = [_fetch_country(code) for code in _cheap_country_candidate_codes()]
    rows = [row for row in await asyncio.gather(*tasks) if row]
    rows.sort(key=lambda row: (float(row.get("price") or 0.0), str(row.get("name") or "")))
    selected = rows[:limit]
    _CHEAP_COUNTRY_CACHE[cache_key] = (now_ts, selected)
    return list(selected)


def _quick_country_keyboard(lang: str, options: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx in range(0, len(options), 2):
        chunk = options[idx : idx + 2]
        button_row: list[InlineKeyboardButton] = []
        for option in chunk:
            code = str(option.get("code") or "").strip()
            if not code:
                continue
            label = f"{option.get('name') or code} | {format_usd(float(option.get('price') or 0.0))}"
            button_row.append(InlineKeyboardButton(text=label, callback_data=f"{_QUICK_COUNTRY_PREFIX}{code}"))
        if button_row:
            rows.append(button_row)
    rows.append([InlineKeyboardButton(text=t(lang, "search_country"), callback_data=_QUICK_COUNTRY_SEARCH_CALLBACK, style="primary")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:country:entry_back")])
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_preselected_temp_service_countries(
    message: types.Message,
    state: FSMContext,
    *,
    lang: str,
    service_key: str,
    service_label: str | None = None,
) -> None:
    label = str(service_label or service_key or "").strip()
    loading = _compose_numbers_screen(
        t(lang, "choose_country_or_search"),
        [f"{t(lang, 'service_label')}: {label}", f"{t(lang, 'temp_mode_label')}: {t(lang, 'temp_numbers')}"] if label else [],
        trailing_lines=[_numbers_text(lang, "Loading available countries...", "جار جلب الدول المتاحة...")],
    )
    sent = await message.answer(loading)
    await state.update_data(last_msg_id=getattr(sent, "message_id", None))
    options = await _cheap_country_options_for_service(service_key, limit=6)
    if not options:
        await _safe_edit_text(
            sent,
            _country_entry_text(lang, "temp") if not label else _compose_numbers_screen(
                t(lang, "choose_country_or_search"),
                [f"{t(lang, 'service_label')}: {label}", f"{t(lang, 'temp_mode_label')}: {t(lang, 'temp_numbers')}"],
                trailing_lines=[t(lang, "numbers_country_search_hint")],
            ),
            reply_markup=country_kb(lang),
        )
        await state.set_state(NumberFlow.country)
        return
    text = _compose_numbers_screen(
        _numbers_text(lang, "Choose a country or search.", "اختر دولة أو ابحث."),
        [f"{t(lang, 'service_label')}: {label}", f"{t(lang, 'temp_mode_label')}: {t(lang, 'temp_numbers')}"] if label else [],
    )
    await _safe_edit_text(sent, text, reply_markup=_quick_country_keyboard(lang, options))
    await state.set_state(NumberFlow.country)


def _has_valid_country_selection(country_code: str | None) -> bool:
    code = str(country_code or "").strip()
    if not code or code.lower() == "none":
        return False
    return code in _VALID_COUNTRY_CODES


def _state_display_name(lang: str, state_code: str | None) -> str:
    raw = str(state_code or "").strip()
    if not raw or raw.lower() == "none":
        return t(lang, "state_any")
    return raw


def _numbers_context_lines(
    lang: str,
    *,
    service: str | None = None,
    country_code: str | None = None,
    state_code: str | None = None,
    provider_code: str | None = None,
) -> list[str]:
    lines: list[str] = []
    if service:
        lines.append(f"{t(lang, 'service_label')}: {service}")
    if country_code:
        lines.append(f"{t(lang, 'country_label')}: {_country_display_name(country_code)}")
    if state_code is not None and country_code == "1":
        lines.append(f"{t(lang, 'state_label')}: {_state_display_name(lang, state_code)}")
    if provider_code:
        lines.append(f"{t(lang, 'provider_label')}: {provider_public_id(provider_code)}")
    return lines


def _compose_numbers_screen(title: str, context_lines: list[str] | None = None, *, trailing_lines: list[str] | None = None) -> str:
    lines = [title]
    context = [str(line).strip() for line in (context_lines or []) if str(line).strip()]
    if context:
        lines.extend(["", *context])
    extra = [str(line).strip() for line in (trailing_lines or []) if str(line).strip()]
    if extra:
        lines.extend(["", *extra])
    return "\n".join(lines)


def _provider_screen_padding(prices: dict[str, dict] | None = None) -> list[str]:
    return []


def _numbers_mode_name(lang: str, num_type: str | None) -> str:
    return t(lang, "rental_numbers") if str(num_type or "").strip().lower() == "rental" else t(lang, "temp_numbers")


def _numbers_text(lang: str, en: str, ar: str) -> str:
    return ar if str(lang or "").lower().startswith("ar") else en


def _country_entry_text(lang: str, num_type: str) -> str:
    return _compose_numbers_screen(
        t(lang, "choose_country_or_search"),
        [f"{t(lang, 'temp_mode_label')}: {_numbers_mode_name(lang, num_type)}"],
        trailing_lines=[t(lang, "numbers_country_search_hint")],
    )


def _rental_home_text(lang: str) -> str:
    return _compose_numbers_screen(
        t(lang, "rental_menu_title"),
        trailing_lines=[t(lang, "rental_home_context_hint")],
    )


def _numbers_unavailable_text(
    lang: str,
    *,
    title: str,
    service: str | None = None,
    country_code: str | None = None,
    state_code: str | None = None,
) -> str:
    return _compose_numbers_screen(
        title,
        _numbers_context_lines(
            lang,
            service=service,
            country_code=country_code,
            state_code=state_code,
        ),
        trailing_lines=[t(lang, "numbers_try_other_choice_hint")],
    )


def _rental_provider_period_title(lang: str, *, unlimited_mode: bool = False) -> str:
    if unlimited_mode:
        return t(lang, "rental_unlimited_provider_period_title")
    return t(lang, "rental_provider_period_title")


def _us_state_prompt(lang: str) -> str:
    return t(lang, "numbers_us_state_prompt")


_AVG_COMPARE_HOURS = (24, 72, 168, 336, 720)  # 1d, 3d, 7d, 14d, 30d


def _avg_price(options: list[dict]) -> tuple[float, int, bool]:
    all_prices: list[float] = []
    scoped_min: dict[int, float] = {}
    for row in options:
        try:
            price = float(row.get("price") or 0)
        except Exception:
            price = 0.0
        if price <= 0:
            continue
        all_prices.append(price)
        try:
            duration = int(row.get("duration") or 0)
        except Exception:
            duration = 0
        if duration in _AVG_COMPARE_HOURS:
            current = scoped_min.get(duration)
            if current is None or price < current:
                scoped_min[duration] = price

    scoped_prices = [scoped_min[h] for h in _AVG_COMPARE_HOURS if h in scoped_min]
    if len(scoped_prices) == len(_AVG_COMPARE_HOURS):
        # AVG comparison target: (1d + 3d + 7d + 14d + 30d) / 5
        return (sum(scoped_prices) / float(len(_AVG_COMPARE_HOURS)), len(scoped_prices), True)
    if scoped_prices:
        # Fallback if provider is missing one of target durations.
        return (sum(scoped_prices) / len(scoped_prices), len(scoped_prices), True)
    if all_prices:
        return (sum(all_prices) / len(all_prices), len(all_prices), False)
    return (0.0, 0, False)


def _monthly_price(options: list[dict]) -> tuple[float, bool]:
    """Return monthly price (30d=720h) when present.

    Returns:
        (price, True) if direct 30-day price is available.
        (0.0, False) otherwise.
    """
    monthly_prices: list[float] = []
    for row in options:
        try:
            duration = int(row.get("duration") or 0)
            price = float(row.get("price") or 0)
        except Exception:
            continue
        if duration == 720 and price > 0:
            monthly_prices.append(price)
    if not monthly_prices:
        return (0.0, False)
    return (min(monthly_prices), True)


def _duration_compact(hours: int) -> str:
    if hours > 0 and hours % 24 == 0:
        return f"{hours // 24}d"
    return f"{hours}h"


def _format_provider_rental_snapshot(provider_options: dict[str, list[dict]], lang: str) -> str:
    """Build a compact unified preview for rental providers and durations."""
    if not provider_options:
        return ""

    def _provider_rank(code: str) -> tuple[int, str]:
        pid = provider_public_id(code)
        if pid.startswith("S") and pid[1:].isdigit():
            return (int(pid[1:]), pid)
        return (9999, pid)

    blocks: list[str] = []
    has_tv = False

    for provider_code in sorted(provider_options.keys(), key=lambda c: _provider_rank(str(c))):
        code = str(provider_code or "").strip().lower()
        public_id = provider_public_id(code)
        options = provider_options.get(provider_code) or []
        if not options:
            continue
        if code == "textverified":
            has_tv = True

        # Keep one cheapest entry per duration.
        best_by_duration: dict[int, float] = {}
        for row in options:
            try:
                dur = int(row.get("duration") or 0)
                price = float(row.get("price") or 0)
            except Exception:
                continue
            if dur <= 0 or price <= 0:
                continue
            prev = best_by_duration.get(dur)
            if prev is None or price < prev:
                best_by_duration[dur] = price

        if not best_by_duration:
            continue

        durations = sorted(best_by_duration.keys())
        lines: list[str] = []

        # Show all returned packages for each provider, wrapped across lines.
        tokens = [f"{_duration_compact(d)} {format_usd(best_by_duration[d])}" for d in durations]
        chunk_size = 5
        for i in range(0, len(tokens), chunk_size):
            lines.append(", ".join(tokens[i : i + chunk_size]))

        blocks.append("\n".join([f"<b>{public_id}</b>", *lines]))

    if not blocks:
        return ""

    text = "\n\n".join(blocks)
    if has_tv:
        if str(lang or "").lower().startswith("ar"):
            text += f"\n\nملاحظة: في S2 إذا اخترت ولاية، السعر يزيد +{format_usd_compact(2)}."
        else:
            text += f"\n\nNote: for S2, selecting a state adds +{format_usd_compact(2)}."
    return text


_TV_DURATION_ORDER = (
    "oneDay",
    "threeDay",
    "sevenDay",
    "fourteenDay",
    "thirtyDay",
    "ninetyDay",
    "oneYear",
)


def _tv_duration_index(duration_key: str) -> int:
    try:
        return _TV_DURATION_ORDER.index(str(duration_key or "").strip())
    except Exception:
        return 99


def _prepare_tv_duration_rows(options: list[dict]) -> list[dict]:
    allowed_keys = {"oneDay", "threeDay", "sevenDay", "fourteenDay", "thirtyDay", "ninetyDay", "oneYear"}
    grouped: dict[str, dict] = {}
    for row in options:
        key = str(row.get("tv_duration_key") or "").strip()
        if not key or key not in allowed_keys:
            continue
        try:
            price = float(row.get("price") or 0)
        except Exception:
            price = 0.0
        if price <= 0:
            continue
        entry = grouped.setdefault(
            key,
            {
                "tv_duration_key": key,
                "duration_label": str(row.get("duration_label") or "").strip() or key,
                "duration": int(row.get("duration") or 0),
                "price": price,
                "nonrenew_price": None,
                "renew_price": None,
            },
        )
        if price < float(entry.get("price") or price):
            entry["price"] = price
        if bool(row.get("tv_is_renewable")):
            current = entry.get("renew_price")
            if current is None or price < float(current):
                entry["renew_price"] = price
        else:
            current = entry.get("nonrenew_price")
            if current is None or price < float(current):
                entry["nonrenew_price"] = price

    rows = list(grouped.values())
    rows.sort(key=lambda x: _tv_duration_index(str(x.get("tv_duration_key") or "")))
    return rows


def _pick_tv_option(options: list[dict], duration_key: str, is_renewable: bool) -> dict | None:
    candidates: list[dict] = []
    for row in options:
        if str(row.get("tv_duration_key") or "").strip() != str(duration_key or "").strip():
            continue
        if bool(row.get("tv_is_renewable")) != bool(is_renewable):
            continue
        candidates.append(dict(row))
    if not candidates:
        return None
    candidates.sort(key=lambda x: float(x.get("price") or 0))
    return candidates[0]


def _build_rental_confirm_text(
    service_name: str,
    country: str,
    option: dict,
    lang: str,
    usd_to_syp: float | None = None,
) -> str:
    duration_label = str(option.get("duration_label") or "").strip()
    if not duration_label:
        try:
            duration_label = f"{int(option.get('duration') or 0)}h"
        except Exception:
            duration_label = t(lang, "provider_duration")
    renewable = bool(option.get("tv_is_renewable"))
    renewable_label = t(lang, "tv_renewable") if renewable else t(lang, "tv_non_renewable")
    lines = [
        f"{t(lang, 'service_label')}: {service_name}",
        f"{t(lang, 'country_label')}: {country}",
        f"{t(lang, 'rental_duration_label')}: {duration_label}",
        f"{t(lang, 'rental_renewable_label')}: {renewable_label}",
    ]
    if renewable:
        lines.append(f"{t(lang, 'rental_billing_cycle_label')}: {t(lang, 'tv_billing_cycle_auto_new')}")
    price_usd = float(option.get("price") or 0)
    lines.append(f"{t(lang, 'price_label')}: {format_usd(price_usd)}")
    lines.append("")
    if str(lang or "").lower().startswith("ar"):
        lines.append("⚠️ تنويه مهم:")
        lines.append("• Alpha قد يوفّر مددًا بالساعات أو بالأيام حسب التوفر.")
        lines.append(f"• Bravo يضيف +{format_usd_compact(2)} عند اختيار ولاية.")
        lines.append("• Echo يعرض حالياً مددًا يومية.")
    else:
        lines.append("⚠️ Important notice:")
        lines.append("• Alpha may offer hourly or daily durations depending on availability.")
        lines.append(f"• Bravo adds +{format_usd_compact(2)} when a state is selected.")
        lines.append("• Echo currently shows day-based durations.")
    lines.append("")
    lines.append(t(lang, "confirm_purchase_question"))
    return "\n".join(lines)


@router.message(lambda msg: bool(msg.text) and ((msg.text or "").strip() in {t("en", "btn_numbers"), t("ar", "btn_numbers")}))
async def numbers_menu(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user.get("language", "en") if user else "en"
    await state.clear()
    await state.update_data(lang=lang)
    await _hide_reply_keyboard(message, lang)
    note = t(lang, "temp_numbers_type_note")
    await message.answer(
        _compose_numbers_screen(t(lang, "choose_number_type"), trailing_lines=[note]),
        reply_markup=number_type_kb(lang),
    )
    await state.set_state(NumberFlow.num_type)


@router.callback_query(lambda c: c.data in {"flow:type:temp", "flow:type:rental", "flow:type:perm"})
async def choose_number_type(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    num_type = callback.data.split(":")[-1]
    if num_type == "perm":
        num_type = "rental"
    await state.update_data(num_type=num_type)
    if num_type == "rental":
        sent = await _safe_edit_text(callback.message, 
            _rental_home_text(lang),
            reply_markup=rental_home_kb(lang),
        )
        await state.update_data(last_msg_id=sent.message_id)
        await state.set_state(NumberFlow.rental_home)
        return
    sent = await _safe_edit_text(
        callback.message,
        _country_entry_text(lang, "temp"),
        reply_markup=country_kb(lang),
    )
    await state.update_data(last_msg_id=sent.message_id)
    await state.set_state(NumberFlow.country)


@router.callback_query(lambda c: c.data == "flow:rental:add")
async def rental_add_number(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    sent = await _safe_edit_text(
        callback.message,
        _country_entry_text(lang, "rental"),
        reply_markup=country_kb(lang),
    )
    await state.update_data(last_msg_id=sent.message_id, num_type="rental")
    await state.set_state(NumberFlow.country)


@router.callback_query(lambda c: c.data == "flow:rental:menu")
async def rental_menu(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    await _safe_edit_text(callback.message, _rental_home_text(lang), reply_markup=rental_home_kb(lang))
    await state.set_state(NumberFlow.rental_home)


@router.callback_query(lambda c: c.data == "flow:country:entry_back")
async def back_from_country_entry(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    if data.get("num_type") == "rental":
        await _safe_edit_text(
            callback.message,
            _rental_home_text(lang),
            reply_markup=rental_home_kb(lang),
        )
        await state.set_state(NumberFlow.rental_home)
    else:
        await _safe_edit_text(
            callback.message,
            t(lang, "choose_number_type"),
            reply_markup=number_type_kb(lang),
        )
        await state.set_state(NumberFlow.num_type)


@router.callback_query(lambda c: c.data == "flow:country:back")
async def back_to_country(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    if data.get("num_type") == "rental":
        await _safe_edit_text(callback.message, _rental_home_text(lang), reply_markup=rental_home_kb(lang))
        await state.set_state(NumberFlow.rental_home)
        return
    await _safe_edit_text(callback.message, _country_entry_text(lang, "temp"), reply_markup=country_kb(lang))
    await state.set_state(NumberFlow.country)


@router.callback_query(lambda c: c.data == "flow:service:back")
async def back_to_service(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    num_type = data.get("num_type", "temp")
    country_code = data.get("country")
    await _safe_edit_text(callback.message, 
        _compose_numbers_screen(
            _service_prompt_bold(lang),
            _numbers_context_lines(
                lang,
                country_code=country_code,
                state_code=data.get("state"),
            ),
        ),
        reply_markup=service_kb(lang, num_type=num_type, country_code=country_code),
        parse_mode="HTML",
    )
    await state.set_state(NumberFlow.service)


@router.callback_query(lambda c: c.data == "flow:rental_providers:back")
async def back_to_rental_providers(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    provider_rows = data.get("rental_provider_rows") or []
    if not provider_rows:
        return await _safe_callback_answer(t(lang, "no_rental_options"), show_alert=True)
    provider_options = data.get("rental_provider_options") or {}
    usd_to_syp_rate = float(data.get("usd_to_syp_rate") or 0)
    unlimited_mode = any(str(row.get("pricing_mode") or "").strip().lower() == "monthly" for row in provider_rows)
    text = _compose_numbers_screen(
        _rental_provider_period_title(lang, unlimited_mode=unlimited_mode),
        _numbers_context_lines(
            lang,
            service=str(data.get("service") or ""),
            country_code=str(data.get("country") or ""),
            state_code=str(data.get("state") or ""),
        ),
    )
    await _safe_edit_text(callback.message, 
        text,
        reply_markup=rental_providers_kb(provider_rows, lang=lang, provider_options=provider_options, usd_to_syp=usd_to_syp_rate),
    )
    await state.set_state(NumberFlow.rental_providers)


@router.callback_query(lambda c: c.data == _QUICK_COUNTRY_SEARCH_CALLBACK)
async def quick_country_search(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    label = str(data.get("numbers_preselected_service_label") or data.get("service") or "").strip()
    text = _country_entry_text(lang, "temp")
    if label:
        text = _compose_numbers_screen(
            t(lang, "choose_country_or_search"),
            [f"{t(lang, 'service_label')}: {label}", f"{t(lang, 'temp_mode_label')}: {t(lang, 'temp_numbers')}"],
            trailing_lines=[t(lang, "numbers_country_search_hint")],
        )
    await _safe_edit_text(callback.message, text, reply_markup=country_kb(lang))
    await state.set_state(NumberFlow.country)
    await _safe_callback_answer()


@router.callback_query(lambda c: c.data and c.data.startswith(_QUICK_COUNTRY_PREFIX))
async def choose_quick_country(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    country_code = str(callback.data or "").replace(_QUICK_COUNTRY_PREFIX, "", 1).strip()
    if country_code not in _VALID_COUNTRY_CODES:
        return await _safe_callback_answer(_numbers_text(lang, "Invalid country.", "الدولة غير صالحة."), show_alert=True)
    await state.update_data(country=country_code, state="none")
    preselected_service = str(data.get("service") or "").strip()
    if preselected_service and bool(data.get("numbers_preselected_service")):
        await state.update_data(numbers_preselected_service=False)
        await _load_service_prices(callback.message.chat.id, callback.message.bot, state, preselected_service)
        return await _safe_callback_answer()
    text = _compose_numbers_screen(
        _service_prompt_bold(lang),
        _numbers_context_lines(lang, country_code=country_code),
    )
    await _safe_edit_text(callback.message, text, reply_markup=service_kb(lang, country_code=country_code), parse_mode="HTML")
    await state.set_state(NumberFlow.service)
    await _safe_callback_answer()


@router.message(F.text.startswith("/select_country_"))
async def handle_inline_country_selection(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    num_type = data.get("num_type", "temp")
    country_code = message.text.replace("/select_country_", "")
    if country_code.lower() in {"any", "all", "*", "0"}:
        country_code = "none"
    await message.delete()
    last_msg_id = data.get("last_msg_id")
    await state.update_data(country=country_code)

    if num_type == "rental":
        await state.update_data(state="none")
        text = _compose_numbers_screen(
            _service_prompt_bold(lang),
            _numbers_context_lines(lang, country_code=country_code),
        )
        kb = service_kb(lang, num_type="rental", country_code=country_code)
        next_state = NumberFlow.service
    elif country_code == "1":
        text = _compose_numbers_screen(
            _us_state_prompt(lang),
            _numbers_context_lines(lang, country_code=country_code),
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "search_state_prompt"), switch_inline_query_current_chat="state ", style="primary")],
                [InlineKeyboardButton(text=t(lang, "back"), callback_data="flow:country:back")],
            ]
        )
        next_state = NumberFlow.state
    else:
        await state.update_data(state="none")
        preselected_service = str(data.get("service") or "").strip()
        if preselected_service and bool(data.get("numbers_preselected_service")):
            await state.update_data(numbers_preselected_service=False)
            await _load_service_prices(message.chat.id, message.bot, state, preselected_service)
            return
        text = _compose_numbers_screen(
            _service_prompt_bold(lang),
            _numbers_context_lines(lang, country_code=country_code),
        )
        kb = service_kb(lang, country_code=country_code)
        next_state = NumberFlow.service

    if last_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=last_msg_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
            await state.set_state(next_state)
            return
        except Exception:
            pass
    sent = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=sent.message_id)
    await state.set_state(next_state)


@router.message(F.text.startswith("/select_state_"))
async def handle_inline_state_selection(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    num_type = data.get("num_type", "temp")
    state_code = message.text.replace("/select_state_", "")
    await message.delete()
    last_msg_id = data.get("last_msg_id")

    if bool(data.get("awaiting_tv_state")):
        base = data.get("tv_selected_option_base") or {}
        if not base:
            return
        state_code = str(state_code or "").strip().upper()
        if state_code not in tv_area_codes.DATA:
            await message.answer(t(lang, "tv_state_not_supported"))
            return
        option = dict(base)
        try:
            base_price = float(option.get("price") or 0)
        except Exception:
            base_price = 0.0
        option["tv_with_state"] = True
        option["state_code"] = state_code
        option["price"] = float(base_price + 2.0)
        await state.update_data(
            selected_rental_option=option,
            awaiting_tv_state=False,
            state=state_code,
        )
        service_name = str(data.get("service") or "")
        country = str(option.get("country") or data.get("country") or "")
        text = _build_rental_confirm_text(
            service_name=service_name,
            country=country,
            option=option,
            lang=lang,
            usd_to_syp=float(data.get("usd_to_syp_rate") or 0),
        )
        if last_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=last_msg_id,
                    text=text,
                    reply_markup=rental_confirm_kb(lang),
                )
                await state.set_state(NumberFlow.rental_confirm)
                return
            except Exception:
                pass
        sent = await message.answer(text, reply_markup=rental_confirm_kb(lang))
        await state.update_data(last_msg_id=sent.message_id)
        await state.set_state(NumberFlow.rental_confirm)
        return

    await state.update_data(state=state_code if num_type == "temp" else "none")
    country_code = data.get("country")
    preselected_service = str(data.get("service") or "").strip()
    if preselected_service and bool(data.get("numbers_preselected_service")):
        await state.update_data(numbers_preselected_service=False)
        await _load_service_prices(message.chat.id, message.bot, state, preselected_service)
        return
    text = _compose_numbers_screen(
        _service_prompt_bold(lang),
        _numbers_context_lines(lang, country_code=country_code, state_code=state_code),
    )
    kb = service_kb(lang, num_type=num_type, country_code=country_code)

    if last_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=last_msg_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
            await state.set_state(NumberFlow.service)
            return
        except Exception:
            pass
    sent = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=sent.message_id)
    await state.set_state(NumberFlow.service)


@router.callback_query(lambda c: c.data == "flow:state:any")
async def choose_any_state(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    num_type = data.get("num_type", "temp")
    last_msg_id = data.get("last_msg_id")
    country_code = data.get("country")

    await state.update_data(state="none" if num_type == "temp" else "none")
    preselected_service = str(data.get("service") or "").strip()
    if preselected_service and bool(data.get("numbers_preselected_service")):
        await state.update_data(numbers_preselected_service=False)
        await _load_service_prices(callback.message.chat.id, callback.message.bot, state, preselected_service)
        return await _safe_callback_answer()
    text = _compose_numbers_screen(
        _service_prompt_bold(lang),
        _numbers_context_lines(lang, country_code=country_code, state_code="none"),
    )
    kb = service_kb(lang, num_type=num_type, country_code=country_code)

    if last_msg_id:
        try:
            await callback.message.bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=last_msg_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
            await state.set_state(NumberFlow.service)
            return await _safe_callback_answer()
        except Exception:
            pass
    sent = await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=sent.message_id)
    await state.set_state(NumberFlow.service)
    await _safe_callback_answer()


@router.message(F.text.startswith("/select_service_"))
async def handle_inline_service_selection(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    service_key = message.text.replace("/select_service_", "", 1)
    lookup_not_listed = False
    if service_key.startswith(_INLINE_SERVICE_QUERY_PREFIX):
        service_key = unquote(service_key.split(":", 1)[1]).strip()
        lookup_not_listed = True
    await state.update_data(service_lookup_not_listed=lookup_not_listed)
    await message.delete()
    await _load_service_prices(message.chat.id, message.bot, state, service_key)


@router.callback_query(lambda c: c.data and c.data.startswith("flow:service:"))
async def choose_service(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    service_name = callback.data.split(":", 2)[2]
    current_message_id = getattr(getattr(callback, "message", None), "message_id", None)
    if not data.get("last_msg_id") and current_message_id:
        await state.update_data(last_msg_id=current_message_id)
    await state.update_data(service_lookup_not_listed=False)
    await _load_service_prices(callback.message.chat.id, callback.message.bot, state, service_name)


async def _load_service_prices(chat_id: int, bot, state: FSMContext, service_name: str):
    data = await state.get_data()
    lang = data.get("lang", "en")
    num_type = data.get("num_type", "temp")
    lookup_not_listed = bool(data.get("service_lookup_not_listed"))
    await state.update_data(service=service_name)
    country = data.get("country")
    state_code = data.get("state")
    last_msg_id = data.get("last_msg_id")
    if not last_msg_id:
        current_callback = _CURRENT_CALLBACK.get()
        current_message = getattr(current_callback, "message", None)
        current_message_id = getattr(current_message, "message_id", None)
        if current_message_id:
            last_msg_id = current_message_id
            await state.update_data(last_msg_id=last_msg_id)
    if not _has_valid_country_selection(country):
        await _redirect_to_country_selection(
            chat_id,
            bot,
            state,
            lang=lang,
            num_type="rental" if num_type == "rental" else "temp",
            last_msg_id=last_msg_id,
        )
        return
    usd_to_syp_rate = await _resolve_usd_to_syp_rate()

    if num_type == "rental":
        loading_stop = None
        loading_task = None
        if last_msg_id:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=last_msg_id, text=t(lang, "loading_prices"), reply_markup=None)
                loading_stop, loading_task = _start_loading_text_animator(
                    bot,
                    chat_id=chat_id,
                    message_id=last_msg_id,
                    base_text=t(lang, "loading_prices"),
                )
            except Exception:
                pass
        try:
            rent_prices = await get_all_rental_prices(service_name, country)
        finally:
            await _stop_loading_text_animator(loading_stop, loading_task)
        pricing_service_key = service_name
        if not rent_prices and lookup_not_listed and not _is_unlimited_service(service_name):
            pricing_service_key = RENTAL_UNLIMITED_SERVICE_KEY
            rent_prices = await get_all_rental_prices(pricing_service_key, country)
        if not rent_prices:
            if last_msg_id:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=last_msg_id,
                    text=_numbers_unavailable_text(
                        lang,
                        title=t(lang, "no_rental_options"),
                        service=service_name,
                        country_code=str(country or ""),
                        state_code=str(state_code or ""),
                    ),
                    reply_markup=no_availability_kb(lang),
                )
            return

        unlimited_mode = _is_unlimited_service(pricing_service_key)
        country_label = _country_iso(str(country) if country is not None else None) or str(country or "").strip().upper()
        show_all_for_testing = bool(getattr(settings, "numbers_show_all_providers_for_testing", False))

        provider_options: dict[str, list[dict]] = {}
        provider_rows: list[dict] = []
        for provider_code, info in rent_prices.items():
            if not provider_allows_rental(
                provider_code,
                service_key=pricing_service_key,
                country_iso=_country_iso(country),
                state_selected=bool(state_code and str(state_code).strip().lower() != "none"),
            ):
                continue
            rows: list[dict] = []
            for option in info.get("options", []):
                row = dict(option) if isinstance(option, dict) else {}
                row.update(
                    {
                        "provider": provider_code,
                        "api_service_name": info.get("api_service_name"),
                        "country": row.get("country") or country,
                        "duration": row.get("duration"),
                        "price": row.get("price"),
                        "count": row.get("count", 0),
                    }
                )
                rows.append(row)
            if not rows and not (show_all_for_testing and bool(info.get("testing_visible"))):
                continue
            provider_options[provider_code] = rows
            avg_price, _avg_basis_count, _avg_is_target = _avg_price(rows)
            monthly_price, has_monthly = _monthly_price(rows)
            summary_price = monthly_price if (unlimited_mode and has_monthly and monthly_price > 0) else avg_price
            provider_rows.append(
                {
                    "provider": provider_code,
                    "avg_price": summary_price,
                    "pricing_mode": "monthly" if unlimited_mode else "avg",
                    "country_label": country_label,
                    "success_rate": info.get("success_rate", 100.0),
                    "success_attempts": info.get("success_attempts", 0),
                    "available_for_buy": bool(info.get("available_for_buy", bool(rows))),
                    "testing_visible": bool(info.get("testing_visible")),
                    "provider_reason": str(info.get("provider_reason") or ""),
                }
            )

        provider_options = {
            code: rows
            for code, rows in provider_options.items()
            if any(str(row.get("provider") or "").strip().lower() == code for row in provider_rows)
        }

        if not provider_options or not provider_rows:
            if last_msg_id:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=last_msg_id,
                    text=_numbers_unavailable_text(
                        lang,
                        title=t(lang, "no_rental_options"),
                        service=service_name,
                        country_code=str(country or ""),
                        state_code=str(state_code or ""),
                    ),
                    reply_markup=no_availability_kb(lang),
                )
            return

        provider_rows.sort(key=lambda x: float(x.get("avg_price") or 0))
        await state.update_data(
            rental_provider_options=provider_options,
            rental_provider_rows=provider_rows,
            selected_rental_provider=None,
            rental_options=[],
            selected_rental_option=None,
            usd_to_syp_rate=usd_to_syp_rate,
        )
        text = _compose_numbers_screen(
            _rental_provider_period_title(lang, unlimited_mode=unlimited_mode),
            _numbers_context_lines(
                lang,
                service=service_name,
                country_code=str(country or ""),
                state_code=str(state_code or ""),
            ),
        )
        if last_msg_id:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_msg_id,
                text=text,
                reply_markup=rental_providers_kb(provider_rows, lang=lang, provider_options=provider_options, usd_to_syp=usd_to_syp_rate),
            )
        await state.set_state(NumberFlow.rental_providers)
        return

    # Unified temp flow: go directly to provider list.
    loading_stop = None
    loading_task = None
    if last_msg_id:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=last_msg_id, text=t(lang, "loading_prices"))
            loading_stop, loading_task = _start_loading_text_animator(
                bot,
                chat_id=chat_id,
                message_id=last_msg_id,
                base_text=t(lang, "loading_prices"),
            )
        except Exception:
            pass
    try:
        prices = await get_all_prices(service_name, country, state_code)
    finally:
        await _stop_loading_text_animator(loading_stop, loading_task)
    if not prices and lookup_not_listed:
        prices = await get_all_prices(TEMP_NOT_LISTED_SERVICE_KEY, country, state_code)
    if not prices:
        if last_msg_id:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_msg_id,
                text=_numbers_unavailable_text(
                    lang,
                    title=t(lang, "no_prices_available"),
                    service=service_name,
                    country_code=str(country or ""),
                    state_code=str(state_code or ""),
                ),
                reply_markup=no_availability_kb(lang),
            )
        await state.set_state(NumberFlow.service)
        return
    try:
        increment_usage(service_name)
    except Exception:
        pass
    show_all_for_testing = bool(getattr(settings, "numbers_show_all_providers_for_testing", False))
    prices = {
        code: info
        for code, info in prices.items()
        if (
            (
                bool(info.get("available_for_buy", True))
                and bool(str(info.get("api_service_name") or "").strip())
                and float(info.get("price", 0) or 0) > 0
            )
            or (show_all_for_testing and bool(info.get("testing_visible")))
        )
    }
    if not prices:
        if last_msg_id:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_msg_id,
                text=_numbers_unavailable_text(
                    lang,
                    title=t(lang, "no_prices_available"),
                    service=service_name,
                    country_code=str(country or ""),
                    state_code=str(state_code or ""),
                ),
                reply_markup=no_availability_kb(lang),
            )
        await state.set_state(NumberFlow.service)
        return
    await state.update_data(available_prices=prices)
    if last_msg_id:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=last_msg_id,
            text=_compose_numbers_screen(
                t(lang, "choose_provider_prompt"),
                _numbers_context_lines(
                    lang,
                    service=service_name,
                    country_code=str(country or ""),
                    state_code=str(state_code or ""),
                ),
                trailing_lines=_provider_screen_padding(prices),
            ),
            reply_markup=provider_choice_kb(prices, lang=lang, usd_to_syp=usd_to_syp_rate),
        )
    await state.set_state(NumberFlow.confirm_buy)


@router.callback_query(lambda c: c.data in {"flow:main:back", "flow:cancel"})
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")
    if await _handle_rental_exit_callback_guard(callback, state, target="main", lang=lang):
        return
    await _return_to_main_menu(callback, state)
    await _safe_callback_answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rentprov:"))
async def choose_rental_provider(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    provider_code = callback.data.split(":", 1)[1].strip().lower()
    provider_map = data.get("rental_provider_options") or {}
    options = provider_map.get(provider_code) or []
    usd_to_syp_rate = float(data.get("usd_to_syp_rate") or 0)
    if not options:
        return await _safe_callback_answer(t(lang, "no_rental_options"), show_alert=True)

    await state.update_data(
        selected_rental_provider=provider_code,
        rental_options=options,
        selected_rental_option=None,
    )

    if provider_code == "textverified":
        duration_rows = _prepare_tv_duration_rows(options)
        if not duration_rows:
            return await _safe_callback_answer(t(lang, "no_rental_options"), show_alert=True)
        await state.update_data(tv_duration_rows=duration_rows, tv_selected_duration=None, tv_selected_option_base=None)
        await _safe_edit_text(callback.message, 
            _compose_numbers_screen(
                t(lang, "tv_choose_duration"),
                _numbers_context_lines(
                    lang,
                    service=str(data.get("service") or ""),
                    country_code=str(data.get("country") or ""),
                    provider_code=provider_code,
                ),
            ),
            reply_markup=tv_duration_kb(duration_rows, lang=lang, usd_to_syp=usd_to_syp_rate),
        )
        await state.set_state(NumberFlow.rental_tv_duration)
        return

    await _safe_edit_text(callback.message, 
        _compose_numbers_screen(
            t(lang, "choose_rental_option"),
            _numbers_context_lines(
                lang,
                service=str(data.get("service") or ""),
                country_code=str(data.get("country") or ""),
                provider_code=provider_code,
            ),
        ),
        reply_markup=rental_options_kb(options, lang=lang, usd_to_syp=usd_to_syp_rate),
    )
    await state.set_state(NumberFlow.rental_options)


@router.callback_query(lambda c: c.data and c.data.startswith("rtv:dur:"))
async def tv_choose_duration(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    duration_key = callback.data.split(":", 2)[2].strip()
    options = data.get("rental_options") or []
    usd_to_syp_rate = float(data.get("usd_to_syp_rate") or 0)
    selected = [row for row in options if str(row.get("tv_duration_key") or "").strip() == duration_key]
    if not selected:
        return await _safe_callback_answer(t(lang, "no_rental_options"), show_alert=True)

    nonrenew_price = None
    renew_price = None
    for row in selected:
        try:
            price = float(row.get("price") or 0)
        except Exception:
            price = 0.0
        if price <= 0:
            continue
        if bool(row.get("tv_is_renewable")):
            renew_price = price if renew_price is None else min(renew_price, price)
        else:
            nonrenew_price = price if nonrenew_price is None else min(nonrenew_price, price)

    await state.update_data(tv_selected_duration=duration_key, awaiting_tv_state=False)
    await _safe_edit_text(callback.message, 
        _compose_numbers_screen(
            t(lang, "tv_choose_renew_mode"),
            _numbers_context_lines(
                lang,
                service=str(data.get("service") or ""),
                country_code=str(data.get("country") or ""),
                provider_code="textverified",
            ),
        ),
        reply_markup=tv_renewable_kb(nonrenew_price=nonrenew_price, renew_price=renew_price, lang=lang, usd_to_syp=usd_to_syp_rate),
    )
    await state.set_state(NumberFlow.rental_tv_renew)


@router.callback_query(lambda c: c.data == "rtv:ren:back")
async def tv_renew_back(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    rows = data.get("tv_duration_rows") or []
    usd_to_syp_rate = float(data.get("usd_to_syp_rate") or 0)
    if not rows:
        return await _safe_callback_answer(t(lang, "no_rental_options"), show_alert=True)
    await state.update_data(awaiting_tv_state=False)
    await _safe_edit_text(callback.message, 
        _compose_numbers_screen(
            t(lang, "tv_choose_duration"),
            _numbers_context_lines(
                lang,
                service=str(data.get("service") or ""),
                country_code=str(data.get("country") or ""),
                provider_code="textverified",
            ),
        ),
        reply_markup=tv_duration_kb(rows, lang=lang, usd_to_syp=usd_to_syp_rate),
    )
    await state.set_state(NumberFlow.rental_tv_duration)


@router.callback_query(lambda c: c.data and c.data.startswith("rtv:ren:"))
async def tv_choose_renew_mode(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    mode = callback.data.split(":", 2)[2].strip()
    is_renewable = mode == "1"
    duration_key = str(data.get("tv_selected_duration") or "").strip()
    options = data.get("rental_options") or []
    usd_to_syp_rate = float(data.get("usd_to_syp_rate") or 0)
    selected = _pick_tv_option(options, duration_key, is_renewable)
    if not selected:
        return await _safe_callback_answer(t(lang, "no_rental_options"), show_alert=True)
    selected["tv_is_renewable"] = bool(is_renewable)
    if is_renewable:
        selected["rental_billing_cycle_label"] = t(lang, "tv_billing_cycle_auto_new")
    await state.update_data(tv_selected_option_base=selected, awaiting_tv_state=False)
    await _safe_edit_text(callback.message, 
        _compose_numbers_screen(
            t(lang, "tv_choose_state_mode"),
            _numbers_context_lines(
                lang,
                service=str(data.get("service") or ""),
                country_code=str(data.get("country") or ""),
                provider_code="textverified",
            ),
        ),
        reply_markup=tv_state_choice_kb(base_price=float(selected.get("price") or 0), lang=lang, usd_to_syp=usd_to_syp_rate),
    )
    await state.set_state(NumberFlow.rental_tv_state_choice)


@router.callback_query(lambda c: c.data == "rtv:state:back")
async def tv_state_back(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    duration_key = str(data.get("tv_selected_duration") or "").strip()
    options = data.get("rental_options") or []
    usd_to_syp_rate = float(data.get("usd_to_syp_rate") or 0)
    selected = [row for row in options if str(row.get("tv_duration_key") or "").strip() == duration_key]
    if not selected:
        return await _safe_callback_answer(t(lang, "no_rental_options"), show_alert=True)
    nonrenew_price = None
    renew_price = None
    for row in selected:
        try:
            price = float(row.get("price") or 0)
        except Exception:
            price = 0.0
        if price <= 0:
            continue
        if bool(row.get("tv_is_renewable")):
            renew_price = price if renew_price is None else min(renew_price, price)
        else:
            nonrenew_price = price if nonrenew_price is None else min(nonrenew_price, price)
    await state.update_data(awaiting_tv_state=False)
    await _safe_edit_text(callback.message, 
        _compose_numbers_screen(
            t(lang, "tv_choose_renew_mode"),
            _numbers_context_lines(
                lang,
                service=str(data.get("service") or ""),
                country_code=str(data.get("country") or ""),
                provider_code="textverified",
            ),
        ),
        reply_markup=tv_renewable_kb(nonrenew_price=nonrenew_price, renew_price=renew_price, lang=lang, usd_to_syp=usd_to_syp_rate),
    )
    await state.set_state(NumberFlow.rental_tv_renew)


@router.callback_query(lambda c: c.data == "rtv:state:with")
async def tv_state_with(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    base = data.get("tv_selected_option_base") or {}
    if not base:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    await state.update_data(awaiting_tv_state=True)
    await _safe_edit_text(callback.message, 
        _compose_numbers_screen(
            t(lang, "tv_choose_state_prompt"),
            _numbers_context_lines(
                lang,
                service=str(data.get("service") or ""),
                country_code=str(data.get("country") or ""),
                provider_code="textverified",
            ),
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "search_state_prompt"), switch_inline_query_current_chat="tvstate ")],
                [InlineKeyboardButton(text=t(lang, "back"), callback_data="rtv:state:back")],
                [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="flow:cancel")],
            ]
        ),
    )
    await state.set_state(NumberFlow.state)


@router.callback_query(lambda c: c.data == "rtv:state:none")
async def tv_state_none(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    base = data.get("tv_selected_option_base") or {}
    usd_to_syp_rate = float(data.get("usd_to_syp_rate") or 0)
    if not base:
        return await _safe_callback_answer(t(lang, "invalid_order_info"), show_alert=True)
    option = dict(base)
    option["tv_with_state"] = False
    option["state_code"] = "none"
    await state.update_data(selected_rental_option=option, awaiting_tv_state=False, state="none")
    service_name = str(data.get("service") or "")
    country = str(option.get("country") or data.get("country") or "")
    text = _build_rental_confirm_text(service_name=service_name, country=country, option=option, lang=lang, usd_to_syp=usd_to_syp_rate)
    await _safe_edit_text(callback.message, text, reply_markup=rental_confirm_kb(lang))
    await state.set_state(NumberFlow.rental_confirm)




