from aiogram import Bot, Router, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from datetime import UTC, datetime, timedelta
import logging
from time import monotonic
import asyncio

from keyboards.language_kb import language_keyboard
from keyboards.subscription_kb import subscription_keyboard
from keyboards.reseller_main_menu import reseller_main_menu
from keyboards.main_menu_kb import numbers_main_menu, numbers_miniapp_url
from utils.permissions import is_reseller
from utils.bot_menu_context import (
    extract_bot_id_from_token,
    is_card_ex_bot,
    is_digital_products_bot,
    is_numbers_bot,
    menu_for_current_bot,
    resolve_runtime_bot_id as resolve_runtime_bot_id_fast,
)

from database.user_repo import get_user, create_user, set_user_reseller_for_bot, update_user_version
from database.website_auth_repo import find_website_account_by_telegram_id
from database.bots_repo import get_bot_settings, get_reseller_id_for_bot
from database.mongo import db
from services.numbers.handlers.core_numbers_buy import _handle_rental_exit_message_guard
from services.platform.website_auth import consume_telegram_link
from utils.translations import t
from config import settings
from utils.reseller_setup_guard import get_reseller_setup_status, render_reseller_setup_notice

router = Router()
logger = logging.getLogger(__name__)
_CLEAN_KEYBOARD_COMMANDS = {"/clean_keyboard", "/clean_kb", "/rkoff"}
_TEMP_START_NOTICE_MAX_AGE = timedelta(hours=6)
_BOT_RUNTIME_ID_CACHE: dict[int, tuple[int, float]] = {}
_BOT_CONTEXT_CACHE: dict[int, tuple[dict, float]] = {}
_BOT_CONTEXT_TTL_SEC = 60.0
_BOT_ID_TTL_SEC = 300.0
_SLOW_START_FLOW_MS = 500.0


def _log_start_perf(*, started_at: float, user_id: int, bot_id: int, outcome: str, stage_ms: dict[str, float]) -> None:
    total_ms = (monotonic() - started_at) * 1000.0
    if total_ms < _SLOW_START_FLOW_MS:
        return
    logger.info(
        "perf.start slow total=%.1fms user_id=%s bot_id=%s outcome=%s %s",
        total_ms,
        user_id,
        bot_id,
        outcome,
        ", ".join(f"{k}={v:.1f}ms" for k, v in stage_ms.items()),
    )


def _reseller_setup_quick_kb(lang: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=t(lang, "open_reseller_settings_button"), callback_data="rsmenu:settings")],
            [types.InlineKeyboardButton(text=t(lang, "open_reseller_dashboard_button"), callback_data="rsmenu:dashboard")],
        ]
    )


async def _hide_reply_keyboard(message: types.Message, lang: str) -> None:
    try:
        await message.answer(
            t(lang, "keyboard_cleanup_placeholder"),
            reply_markup=types.ReplyKeyboardRemove(),
        )
    except Exception:
        pass


async def _has_active_temp_order(user_id: int) -> bool:
    cutoff = datetime.now(UTC) - _TEMP_START_NOTICE_MAX_AGE
    doc = await db.orders.find_one(
        {
            "user_id": int(user_id),
            "number_mode": "temp",
            "status": {"$in": ["success", "pending", "paid"]},
            "temp_wait_state": {"$in": ["waiting", "code_received"]},
            "created_at": {"$gte": cutoff},
        },
        {"_id": 1},
    )
    return doc is not None


async def _has_active_rental_order(user_id: int) -> bool:
    doc = await db.orders.find_one(
        {
            "user_id": int(user_id),
            "number_mode": "rental",
            "status": {"$in": ["success", "pending", "paid"]},
        },
        {"_id": 1},
    )
    return doc is not None


async def _get_active_order_flags(user_id: int) -> tuple[bool, bool]:
    has_temp = await _has_active_temp_order(user_id)
    has_rental = await _has_active_rental_order(user_id)
    return has_temp, has_rental


async def _should_run_numbers_start_guards(bot_id: int | None) -> bool:
    if not bot_id:
        return False
    if await is_digital_products_bot(bot_id):
        return False
    if await is_card_ex_bot(bot_id):
        return False
    return True


async def _should_show_active_numbers_notice(message: types.Message) -> bool:
    bot = getattr(message, "bot", None)
    if bot is None:
        return False
    bot_id = await _resolve_runtime_bot_id(bot)
    return await _should_run_numbers_start_guards(bot_id)


async def _notify_active_temp_order_if_any(message: types.Message, lang: str) -> None:
    if not await _should_show_active_numbers_notice(message):
        return
    has_temp, has_rental = await _get_active_order_flags(message.from_user.id)
    if not has_temp and not has_rental:
        return
    if has_temp and has_rental:
        kind = t(lang, "start_active_numbers_both")
    elif has_temp:
        kind = t(lang, "start_active_numbers_temp")
    else:
        kind = t(lang, "start_active_numbers_rental")
    text = f"{kind}\n{t(lang, 'start_active_numbers_continue_note')}"
    rows: list[list[types.InlineKeyboardButton]] = []
    miniapp_url = numbers_miniapp_url()
    if bool(getattr(settings, "numbers_miniapp_enabled", False)) and miniapp_url:
        rows.append(
            [
                types.InlineKeyboardButton(
                    text="Open Numbers App" if not str(lang or "").lower().startswith("ar") else "فتح تطبيق الأرقام",
                    web_app=types.WebAppInfo(url=miniapp_url),
                )
            ]
        )
    await message.answer(
        text,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
    )


def _notify_active_temp_order_background(message: types.Message, lang: str) -> None:
    async def _runner() -> None:
        try:
            await _notify_active_temp_order_if_any(message, lang)
        except Exception:
            pass

    asyncio.create_task(_runner())


async def _refresh_numbers_reply_keyboard(message: types.Message, *, lang: str) -> None:
    try:
        await _hide_reply_keyboard(message, lang)
        await message.answer(t(lang, "numbers_keyboard_ready"), reply_markup=numbers_main_menu(lang))
    except Exception:
        pass


async def _open_numbers_start_menu(message: types.Message, state: FSMContext, *, lang: str) -> None:
    await _refresh_numbers_reply_keyboard(message, lang=lang)


async def _start_create_bot_flow(message: types.Message, state: FSMContext, *, lang: str) -> None:
    from handlers.verify_reseller import (
        FLOW_REF_KEY,
        INTRO_MSG_ID_KEY,
        VerifyReseller,
        _hide_reply_keyboard as _hide_verify_reply_keyboard,
        _intro_rest_text,
        _new_flow_ref,
        _set_or_edit_prompt,
        _verify_intro_kb,
    )

    await state.update_data(**{INTRO_MSG_ID_KEY: None, FLOW_REF_KEY: _new_flow_ref(), "lang": lang})
    await _hide_verify_reply_keyboard(message.bot, message.chat.id, state)
    await _set_or_edit_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        state=state,
        text=_intro_rest_text(lang),
        reply_markup=_verify_intro_kb(lang),
    )
    await state.set_state(VerifyReseller.waiting_for_intro)


async def _open_digital_products_start_payload(message: types.Message, *, lang: str, payload: str) -> None:
    payload_text_map = {
        "hub": t(lang, "digital_products_start_hub_text"),
        "games": t(lang, "digital_products_start_games_text"),
        "topup": t(lang, "digital_products_start_topups_text"),
        "esim": t(lang, "digital_products_start_esim_text"),
    }
    text = payload_text_map.get(payload)
    await _hide_reply_keyboard(message, lang)
    await message.answer(
        t(lang, "main_menu"),
        reply_markup=await menu_for_current_bot(lang, int(await _resolve_runtime_bot_id(message.bot) or 0), user_id=message.from_user.id),
    )
    if text:
        await message.answer(text)
    _notify_active_temp_order_background(message, lang)


async def _resolve_admin_bot_id() -> int | None:
    return extract_bot_id_from_token(getattr(settings, "bot_admin_token", ""))


async def _resolve_main_bot_id() -> int | None:
    return extract_bot_id_from_token(getattr(settings, "bot_main_token", ""))


async def _handle_admin_start(message: types.Message) -> None:
    text = "Owner Control Panel\n\nUse inline categories to run owner operations."
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Open Owner Panel", callback_data="owner_panel:open")]
        ]
    )
    try:
        sent = await message.answer("...", reply_markup=types.ReplyKeyboardRemove())
        try:
            await sent.delete()
        except Exception:
            pass
    except Exception:
        pass
    await message.answer(text, reply_markup=keyboard)


async def _handle_website_link_payload(
    message: types.Message,
    *,
    payload: str,
    current_bot_id: int,
    main_bot_id: int | None,
    lang: str,
) -> bool:
    if not str(payload or "").startswith("link_"):
        return False
    if not isinstance(main_bot_id, int) or int(current_bot_id) != int(main_bot_id):
        await message.answer("Please open this link with the main Phantom bot.")
        return True
    result = await consume_telegram_link(payload, telegram_id=int(message.from_user.id))
    if result.get("ok"):
        text = "تم ربط حساب Telegram بحساب الموقع بنجاح." if str(lang).startswith("ar") else "Telegram was linked to your website account."
    else:
        text = "رابط الربط منتهي أو مستخدم أو الحساب مربوط مسبقاً." if str(lang).startswith("ar") else "This link expired, was already used, or the account is already linked."
    await message.answer(text)
    return True


def _website_login_url() -> str:
    base = (
        str(getattr(settings, "digital_products_miniapp_public_url", "") or "")
        or str(getattr(settings, "numbers_miniapp_public_url", "") or "")
        or "https://phantom-app.net"
    ).rstrip("/")
    return f"{base}/login"


async def _require_website_account_gate(
    message: types.Message,
    *,
    current_bot_id: int,
    main_bot_id: int | None,
    is_numbers_runtime_bot: bool,
    is_digital_products_runtime_bot: bool,
    is_card_ex_runtime_bot: bool,
    lang: str,
) -> bool:
    protected = (
        (isinstance(main_bot_id, int) and int(current_bot_id) == int(main_bot_id))
        or is_numbers_runtime_bot
        or is_digital_products_runtime_bot
        or is_card_ex_runtime_bot
    )
    if not protected:
        return False
    account = await find_website_account_by_telegram_id(int(message.from_user.id))
    if account:
        return False
    url = _website_login_url()
    text = (
        "صار تسجيل الحساب من الموقع إلزامي قبل استخدام الخدمات.\n"
        "افتح الموقع وسجّل دخول أو أنشئ حساب. ربط Telegram اختياري للتنبيهات والدخول الأسرع."
        if str(lang).startswith("ar")
        else "Website registration is required before using services.\nOpen the website and sign in or create an account. Linking Telegram is optional for notifications and faster access."
    )
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="فتح الموقع" if str(lang).startswith("ar") else "Open website", url=url)]]
    )
    await message.answer(text, reply_markup=keyboard)
    return True


async def _resolve_runtime_bot_id(bot: Bot) -> int:
    key = id(bot)
    now_ts = monotonic()
    cached = _BOT_RUNTIME_ID_CACHE.get(key)
    if cached and (now_ts - float(cached[1])) <= _BOT_ID_TTL_SEC:
        return int(cached[0])
    bot_id = int(await resolve_runtime_bot_id_fast(bot) or 0)
    _BOT_RUNTIME_ID_CACHE[key] = (bot_id, now_ts)
    return bot_id


async def _get_bot_context(bot_id: int) -> dict:
    now_ts = monotonic()
    cached = _BOT_CONTEXT_CACHE.get(int(bot_id))
    if cached and (now_ts - float(cached[1])) <= _BOT_CONTEXT_TTL_SEC:
        return dict(cached[0])
    bot_settings = await get_bot_settings(bot_id)
    inferred_reseller_id = await get_reseller_id_for_bot(bot_id)
    context = {
        "bot_settings": dict(bot_settings or {}),
        "subscription_channel": (bot_settings or {}).get("subscription_channel"),
        "reseller_id": inferred_reseller_id,
    }
    _BOT_CONTEXT_CACHE[int(bot_id)] = (context, now_ts)
    return dict(context)


async def _should_show_channel_setup_warning(*, user_id: int, bot_id: int, inferred_reseller_id: int | None) -> bool:
    if int(user_id) == int(getattr(settings, "owner_id", 0) or 0):
        return True
    if inferred_reseller_id and int(user_id) == int(inferred_reseller_id):
        return True
    try:
        return await is_reseller(user_id, bot_id=bot_id)
    except Exception:
        return False


@router.message(Command("start"))
async def start_cmd(
    message: types.Message,
    state: FSMContext,
    command: CommandObject | None = None,
    cached_user: dict | None = None,
    lang: str | None = None,
):
    started_at = monotonic()
    stage_ms: dict[str, float] = {}
    current_bot_id = await _resolve_runtime_bot_id(message.bot)
    admin_bot_id = await _resolve_admin_bot_id()
    main_bot_id = await _resolve_main_bot_id()
    if isinstance(admin_bot_id, int) and current_bot_id == admin_bot_id:
        if int(message.from_user.id) != int(getattr(settings, "owner_id", 0) or 0):
            await message.answer(t("en", "no_permission"))
            return
        await state.clear()
        await _handle_admin_start(message)
        return

    stage_started = monotonic()
    user = cached_user or await get_user(message.from_user.id)
    stage_ms["user_initial"] = (monotonic() - stage_started) * 1000.0
    lang = str(lang or (user or {}).get("language", "en") or "en")
    if (
        user
        and await _should_run_numbers_start_guards(current_bot_id)
        and await _handle_rental_exit_message_guard(message, state, target="start", lang=lang)
    ):
        return
    await state.clear()
    user_id = message.from_user.id
    if not user:
        stage_started = monotonic()
        user = await get_user(user_id)
        stage_ms["user_second"] = (monotonic() - stage_started) * 1000.0

    bot_id = current_bot_id
    raw_payload = str((command.args if command else "") or "").strip()
    payload = raw_payload.lower()
    stage_started = monotonic()
    is_digital_products_runtime_bot = await is_digital_products_bot(bot_id)
    is_card_ex_runtime_bot = await is_card_ex_bot(bot_id)
    is_numbers_runtime_bot = await is_numbers_bot(bot_id)
    stage_ms["bot_kind"] = (monotonic() - stage_started) * 1000.0
    stage_started = monotonic()
    bot_context = await _get_bot_context(bot_id)
    stage_ms["bot_context"] = (monotonic() - stage_started) * 1000.0
    subscription_channel = bot_context.get("subscription_channel")
    inferred_reseller_id = bot_context.get("reseller_id")

    # Ù…Ø³ØªØ®Ø¯Ù… Ø¬Ø¯ÙŠØ¯ â†’ Ù†Ø·Ù„Ø¨ Ù…Ù†Ù‡ Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„Ù„ØºØ©
    if not user:
        username = message.from_user.username or ""
        user = await create_user(user_id, username, reseller_id=None)
        if inferred_reseller_id:
            await set_user_reseller_for_bot(user_id, bot_id, inferred_reseller_id)

        if await _handle_website_link_payload(
            message,
            payload=raw_payload,
            current_bot_id=current_bot_id,
            main_bot_id=main_bot_id,
            lang=lang,
        ):
            return
        if await _require_website_account_gate(
            message,
            current_bot_id=current_bot_id,
            main_bot_id=main_bot_id,
            is_numbers_runtime_bot=is_numbers_runtime_bot,
            is_digital_products_runtime_bot=is_digital_products_runtime_bot,
            is_card_ex_runtime_bot=is_card_ex_runtime_bot,
            lang=lang,
        ):
            return
        _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome="new_user_language", stage_ms=stage_ms)
        return await message.answer(
            t("en", "choose_language"),
            reply_markup=language_keyboard("en", show_nav=False)
        )

    if await _handle_website_link_payload(
        message,
        payload=raw_payload,
        current_bot_id=current_bot_id,
        main_bot_id=main_bot_id,
        lang=lang,
    ):
        return

    if await _require_website_account_gate(
        message,
        current_bot_id=current_bot_id,
        main_bot_id=main_bot_id,
        is_numbers_runtime_bot=is_numbers_runtime_bot,
        is_digital_products_runtime_bot=is_digital_products_runtime_bot,
        is_card_ex_runtime_bot=is_card_ex_runtime_bot,
        lang=lang,
    ):
        return

    if inferred_reseller_id and user.get("reseller_id") != inferred_reseller_id:
        await set_user_reseller_for_bot(user_id, bot_id, inferred_reseller_id)
        user["reseller_id"] = inferred_reseller_id

    lang = user.get("language", "en")

    if payload == "create_bot" and isinstance(main_bot_id, int) and current_bot_id == main_bot_id:
        _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome="create_bot", stage_ms=stage_ms)
        return await _start_create_bot_flow(message, state, lang=lang)

    if is_digital_products_runtime_bot and payload in {"hub", "games", "topup", "esim"}:
        _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome=f"digital_payload:{payload}", stage_ms=stage_ms)
        return await _open_digital_products_start_payload(message, lang=lang, payload=payload)

    if (
        (isinstance(main_bot_id, int) and current_bot_id == main_bot_id)
        or is_numbers_runtime_bot
        or is_digital_products_runtime_bot
        or is_card_ex_runtime_bot
    ):
        if is_numbers_runtime_bot:
            await _open_numbers_start_menu(message, state, lang=lang)
            _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome="numbers_start_menu", stage_ms=stage_ms)
            return
        if is_card_ex_runtime_bot or is_digital_products_runtime_bot:
            await _hide_reply_keyboard(message, lang)
        stage_started = monotonic()
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=await menu_for_current_bot(lang, bot_id, user_id=message.from_user.id)
        )
        stage_ms["send_main_menu"] = (monotonic() - stage_started) * 1000.0
        stage_ms["active_order_notice"] = 0.0
        _notify_active_temp_order_background(message, lang)
        _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome="direct_menu", stage_ms=stage_ms)
        return

    # Ø§Ù„ØªØ­Ù‚Ù‚ Ù…Ù† ÙˆØ¬ÙˆØ¯ Ù‚Ù†Ø§Ø© Ø§Ø´ØªØ±Ø§Ùƒ
    if not subscription_channel:
        if await _should_show_channel_setup_warning(
            user_id=user_id,
            bot_id=bot_id,
            inferred_reseller_id=inferred_reseller_id,
        ):
            _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome="no_channel", stage_ms=stage_ms)
            return await message.answer(
                t(lang, "no_channel_set")
            )
        stage_started = monotonic()
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=await menu_for_current_bot(lang, bot_id, user_id=message.from_user.id)
        )
        stage_ms["send_main_menu"] = (monotonic() - stage_started) * 1000.0
        stage_ms["active_order_notice"] = 0.0
        _notify_active_temp_order_background(message, lang)
        _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome="no_channel_public_bypass", stage_ms=stage_ms)
        return

    # Ø§Ù„ØªØ­Ù‚Ù‚ Ù…Ù† Ø§Ù„Ø§Ø´ØªØ±Ø§Ùƒ
    try:
        stage_started = monotonic()
        member = await message.bot.get_chat_member(subscription_channel, user_id)
        stage_ms["get_chat_member"] = (monotonic() - stage_started) * 1000.0

        if member.status in ("member", "administrator", "creator"):
            # If user is a reseller, show reseller menu instead
            if (not is_digital_products_runtime_bot) and await is_reseller(user_id, bot_id=bot_id):
                await _hide_reply_keyboard(message, lang)
                stage_started = monotonic()
                await message.answer(
                    t(lang, "main_menu"),
                    reply_markup=reseller_main_menu(lang)
                )
                stage_ms["send_reseller_menu"] = (monotonic() - stage_started) * 1000.0
                stage_ms["active_order_notice"] = 0.0
                _notify_active_temp_order_background(message, lang)
                status = await get_reseller_setup_status(user_id)
                if not bool(status.get("ready")):
                    await message.answer(
                        render_reseller_setup_notice(lang, status),
                        reply_markup=_reseller_setup_quick_kb(lang),
                    )
                _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome="member_reseller", stage_ms=stage_ms)
                return
            if is_digital_products_runtime_bot:
                await _hide_reply_keyboard(message, lang)
            stage_started = monotonic()
            await message.answer(
                t(lang, "main_menu"),
                reply_markup=await menu_for_current_bot(lang, bot_id, user_id=message.from_user.id)
            )
            stage_ms["send_main_menu"] = (monotonic() - stage_started) * 1000.0
            stage_ms["active_order_notice"] = 0.0
            _notify_active_temp_order_background(message, lang)
            _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome="member_menu", stage_ms=stage_ms)
            return

        _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome="join_channel", stage_ms=stage_ms)
        return await message.answer(
            t(lang, "join_channel"),
            reply_markup=subscription_keyboard(subscription_channel, lang)
        )

    except Exception:
        _log_start_perf(started_at=started_at, user_id=user_id, bot_id=bot_id, outcome="join_channel_exception", stage_ms=stage_ms)
        return await message.answer(
            t(lang, "join_channel"),
            reply_markup=subscription_keyboard(subscription_channel, lang)
        )


async def _forced_start_flow(message: types.Message, state: FSMContext):
    bot_id = await _resolve_runtime_bot_id(message.bot)
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    if (
        user
        and await _should_run_numbers_start_guards(bot_id)
        and await _handle_rental_exit_message_guard(message, state, target="start", lang=lang)
    ):
        return
    await state.clear()
    is_digital_products_runtime_bot = await is_digital_products_bot(bot_id)
    is_numbers_runtime_bot = await is_numbers_bot(bot_id)
    bot_context = await _get_bot_context(bot_id)
    if not user:
        username = message.from_user.username or ""
        inferred_reseller_id = bot_context.get("reseller_id")
        user = await create_user(message.from_user.id, username, reseller_id=None)
        if inferred_reseller_id:
            await set_user_reseller_for_bot(message.from_user.id, bot_id, inferred_reseller_id)

    main_bot_id = await _resolve_main_bot_id()
    is_card_ex_runtime_bot = await is_card_ex_bot(bot_id)
    inferred_reseller_id = bot_context.get("reseller_id")
    if inferred_reseller_id and user.get("reseller_id") != inferred_reseller_id:
        await set_user_reseller_for_bot(message.from_user.id, bot_id, inferred_reseller_id)
        user["reseller_id"] = inferred_reseller_id
    lang = user.get("language", "en")

    # âœ”ï¸ ØªØ­Ø¯ÙŠØ« Ù†Ø³Ø®Ø© Ø§Ù„Ø¨ÙˆØª Ù„Ù„Ù…Ø³ØªØ®Ø¯Ù…
    await update_user_version(message.from_user.id, settings.bot_version)

    if is_numbers_runtime_bot:
        await _open_numbers_start_menu(message, state, lang=lang)
        return

    if (isinstance(main_bot_id, int) and bot_id == main_bot_id) or is_digital_products_runtime_bot or is_card_ex_runtime_bot:
        if is_card_ex_runtime_bot or is_digital_products_runtime_bot:
            await _hide_reply_keyboard(message, lang)
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=await menu_for_current_bot(lang, bot_id, user_id=message.from_user.id)
        )
        _notify_active_temp_order_background(message, lang)
        return

    # Show reseller menu for resellers
    if (not is_digital_products_runtime_bot) and await is_reseller(message.from_user.id, bot_id=bot_id):
        await _hide_reply_keyboard(message, lang)
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=reseller_main_menu(lang)
        )
        _notify_active_temp_order_background(message, lang)
        status = await get_reseller_setup_status(message.from_user.id)
        if not bool(status.get("ready")):
            await message.answer(
                render_reseller_setup_notice(lang, status),
                reply_markup=_reseller_setup_quick_kb(lang),
            )
    else:
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=await menu_for_current_bot(lang, bot_id, user_id=message.from_user.id)
        )
        _notify_active_temp_order_background(message, lang)


# âœ”ï¸ Ø¥ØµÙ„Ø§Ø­ Ø²Ø± Start Ù„ÙŠØ¹Ù…Ù„ Ø¨ÙƒÙ„ Ø§Ù„Ù„ØºØ§Øª
@router.message(lambda msg: msg.text and msg.text.startswith("🔄"))
async def forced_start(message: types.Message, state: FSMContext):
    await _forced_start_flow(message, state)


@router.message(lambda msg: (msg.text or "").strip().lower() in _CLEAN_KEYBOARD_COMMANDS)
async def clean_keyboard_command(message: types.Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    bot_id = await _resolve_runtime_bot_id(message.bot)

    await message.answer(t(lang, "keyboard_cleaned"), reply_markup=types.ReplyKeyboardRemove())
    if await is_reseller(message.from_user.id, bot_id=bot_id):
        await message.answer(t(lang, "main_menu"), reply_markup=reseller_main_menu(lang))
    else:
        await message.answer(t(lang, "main_menu"), reply_markup=await menu_for_current_bot(lang, bot_id, user_id=message.from_user.id))


@router.callback_query(lambda c: c.data == "force_start")
async def forced_start_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.message:
        await _forced_start_flow(callback.message, state)


@router.callback_query(lambda c: c.data == "update:cancel")
async def update_cancel_callback(callback: types.CallbackQuery):
    await callback.answer()
    if not callback.message:
        return
    try:
        await callback.message.delete()
    except Exception:
        pass

