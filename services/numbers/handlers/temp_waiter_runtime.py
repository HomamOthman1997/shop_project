import asyncio
from typing import Any, Awaitable, Callable


async def send_temp_timeout_state(
    *,
    bot: Any,
    order: dict,
    lang: str,
    utc_now: Callable[[], Any],
    log_number_event_from_order: Callable[..., Awaitable[None]],
    cancel_and_refund_temp_order: Callable[..., Awaitable[dict]],
    update_order_details: Callable[..., Awaitable[None]],
    safe_edit_message: Callable[..., Awaitable[Any]],
    temp_post_refund_kb: Callable[..., Any],
    translations_t: Callable[[str, str], str],
    log_temp_event: Callable[..., Awaitable[None]],
    order_temp_timeout_sec: Callable[[dict | None], int],
    get_order: Callable[..., Awaitable[dict | None]],
    sync_temp_wait_controls: Callable[..., Awaitable[Any]],
    retry_temp_refund_until_success: Callable[..., Awaitable[Any]],
) -> None:
    now = utc_now()
    await log_number_event_from_order(
        order,
        "deadline_reached",
        payload={"source": "temp_wait_timeout"},
        number_mode="temp",
    )
    result = await cancel_and_refund_temp_order(
        order_id=order["_id"],
        order=order,
        actor_user_id=int(order.get("user_id") or 0),
        reason="timeout_auto_refund",
        require_no_sms=True,
    )
    if result.get("success"):
        await update_order_details(
            order["_id"],
            {
                "temp_wait_timeout_at": now,
                "temp_wait_state": "auto_refunded",
                "temp_replace_enabled": True,
            },
        )
        await safe_edit_message(
            bot,
            chat_id=int(order.get("temp_wait_chat_id") or 0),
            message_id=int(order.get("temp_wait_message_id") or 0),
            text=translations_t(lang, "temp_timeout_refunded_retry"),
            reply_markup=temp_post_refund_kb(str(order["_id"]), lang=lang, allow_replace=True),
        )
        await log_number_event_from_order(
            order,
            "auto_protection_triggered",
            payload={"source": "temp_wait_timeout"},
            status_after="cancelled",
            number_mode="temp",
        )
        await log_temp_event(order, "wait_timeout_auto_refunded", {"timeout_sec": order_temp_timeout_sec(order)})
        return

    await update_order_details(
        order["_id"],
        {
            "temp_wait_timeout_at": now,
            "temp_wait_state": "refund_pending",
            "temp_replace_enabled": True,
            "temp_refund_retry_last_at": now,
            "temp_refund_retry_reason": str(result.get("reason") or "provider_cancel_failed"),
        },
    )
    refreshed = await get_order(order["_id"])
    if refreshed:
        await sync_temp_wait_controls(bot, refreshed, lang)
    await log_temp_event(
        order,
        "wait_timeout",
        {
            "timeout_sec": order_temp_timeout_sec(order),
            "auto_refund_failed": True,
            "auto_refund_reason": str(result.get("reason") or ""),
        },
    )
    asyncio.create_task(
        retry_temp_refund_until_success(
            bot=bot,
            order_id=order["_id"],
            actor_user_id=int(order.get("user_id") or 0),
            lang=lang,
            source_reason="timeout_auto_refund",
        )
    )


async def start_temp_waiter(
    *,
    bot: Any,
    order: dict,
    lang: str,
    is_second_code: bool,
    poll_interval_for_provider: Callable[[str], int],
    utc_now: Callable[[], Any],
    update_order_details: Callable[..., Awaitable[None]],
    log_temp_event: Callable[..., Awaitable[None]],
    order_temp_timeout_sec: Callable[[dict | None], int],
    get_order: Callable[..., Awaitable[dict | None]],
    fetch_provider_sms: Callable[[str, str], Awaitable[dict]],
    extract_new_sms_code: Callable[[list, set[str]], str | None],
    seconds_between: Callable[[Any, Any], int | None],
    maybe_send_purchase_charge_confirmed_notice: Callable[..., Awaitable[Any]],
    safe_edit_message: Callable[..., Awaitable[Any]],
    temp_code_received_text: Callable[[str, str, dict | None], str],
    temp_code_received_kb: Callable[..., Any],
    send_temp_timeout_state_cb: Callable[..., Awaitable[None]],
    sync_temp_wait_controls: Callable[..., Awaitable[Any]],
) -> None:
    order_id = order.get("_id")
    if not order_id:
        return
    provider_code = str(order.get("provider") or "").lower()
    provider_order_id = str(order.get("provider_order_id") or "")
    chat_id = int(order.get("temp_wait_chat_id") or 0)
    msg_id = int(order.get("temp_wait_message_id") or 0)
    if not provider_code or not provider_order_id or not chat_id or not msg_id:
        return

    interval = poll_interval_for_provider(provider_code)
    started_at = utc_now()
    await update_order_details(
        order_id,
        {
            "temp_wait_state": "waiting",
            "temp_wait_started_at": started_at,
            "temp_wait_interval_sec": interval,
        },
    )
    await log_temp_event(order, "wait_started", {"interval_sec": interval, "second_code": bool(is_second_code)})

    deadline = started_at.timestamp() + order_temp_timeout_sec(order)
    while utc_now().timestamp() < deadline:
        current = await get_order(order_id)
        if not current:
            return
        if str(current.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
            return
        if str(current.get("provider_order_id") or "") != provider_order_id:
            return

        seen_codes = set(str(x) for x in (current.get("temp_codes") or []) if x not in (None, ""))
        sms_data = await fetch_provider_sms(provider_code, provider_order_id)
        messages = sms_data.get("messages") or []
        code = extract_new_sms_code(messages, seen_codes)
        if code:
            now = utc_now()
            codes = list(seen_codes)
            codes.append(code)
            patch = {
                "temp_wait_state": "code_received",
                "temp_last_sms_at": now,
                "temp_last_code": code,
                "temp_codes": codes,
                "temp_codes_count": len(codes),
            }
            if not current.get("temp_first_sms_at"):
                patch["temp_first_sms_at"] = now
                seconds_to_first_sms = seconds_between(now, current.get("created_at"))
                if seconds_to_first_sms is not None:
                    patch["temp_seconds_to_first_sms"] = seconds_to_first_sms
            await update_order_details(order_id, patch)
            seconds_since_purchase = seconds_between(now, current.get("created_at"))
            await log_temp_event(
                current,
                "code_received",
                {
                    "code_len": len(code),
                    "seconds_since_purchase": seconds_since_purchase,
                    "second_code": bool(is_second_code),
                },
            )
            updated_order = await get_order(order_id) or current
            await maybe_send_purchase_charge_confirmed_notice(
                bot=bot,
                chat_id=chat_id,
                order=updated_order,
                lang=lang,
                code=code,
            )
            await safe_edit_message(
                bot,
                chat_id=chat_id,
                message_id=msg_id,
                text=temp_code_received_text(lang, code, updated_order),
                reply_markup=temp_code_received_kb(str(order_id), lang=lang),
                parse_mode="HTML",
            )
            return

        await sync_temp_wait_controls(bot, current, lang)
        await asyncio.sleep(interval)

    refreshed = await get_order(order_id)
    if refreshed:
        await send_temp_timeout_state_cb(bot=bot, order=refreshed, lang=lang)


async def queue_temp_waiter(
    *,
    bot: Any,
    order: dict,
    lang: str,
    is_second_code: bool,
    start_temp_waiter_cb: Callable[..., Awaitable[None]],
    logger_obj: Any,
) -> None:
    task = asyncio.create_task(
        start_temp_waiter_cb(
            bot=bot,
            order=order,
            lang=lang,
            is_second_code=is_second_code,
        )
    )

    def _done(t: asyncio.Task) -> None:
        try:
            _ = t.exception()
        except asyncio.CancelledError:
            return
        except Exception:
            logger_obj.exception("temp waiter task failed unexpectedly")

    task.add_done_callback(_done)
