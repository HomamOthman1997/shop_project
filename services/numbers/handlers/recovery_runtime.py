from contextlib import suppress
from typing import Any, Awaitable, Callable


async def run_temp_wait_recovery_sweep(
    *,
    bot: Any,
    limit: int,
    utc_now: Callable[[], Any],
    list_open_temp_orders_for_recovery: Callable[..., Awaitable[list]],
    order_bot_id: Callable[[dict | None], int | None],
    get_order: Callable[..., Awaitable[dict | None]],
    get_user: Callable[..., Awaitable[dict | None]],
    cancel_and_refund_temp_order: Callable[..., Awaitable[dict]],
    safe_edit_message: Callable[..., Awaitable[Any]],
    temp_post_refund_kb: Callable[..., Any],
    translations_t: Callable[[str, str], str],
    fetch_provider_sms: Callable[[str, str], Awaitable[dict]],
    extract_new_sms_code: Callable[[list, set[str]], str | None],
    safe_code_text: Callable[[str], str],
    seconds_between: Callable[[Any, Any], int | None],
    update_order_details: Callable[..., Awaitable[None]],
    log_temp_event: Callable[..., Awaitable[None]],
    temp_code_received_text: Callable[[str, str, dict | None], str],
    temp_code_received_kb: Callable[..., Any],
    order_temp_timeout_sec: Callable[[dict | None], int],
    send_temp_timeout_state: Callable[..., Awaitable[None]],
    sync_temp_wait_controls: Callable[..., Awaitable[Any]],
) -> dict[str, Any]:
    stats = {
        "checked": 0,
        "synced": 0,
        "code_received": 0,
        "timed_out": 0,
        "refund_retries": 0,
    }
    if bot is None:
        return stats

    try:
        bot_id = int(getattr(bot, "_cached_bot_id", 0) or 0)
        if bot_id <= 0:
            me = await bot.get_me()
            bot_id = int(me.id)
            setattr(bot, "_cached_bot_id", bot_id)
    except Exception:
        bot_id = 0

    orders = await list_open_temp_orders_for_recovery(limit=int(limit))
    now_dt = utc_now()
    for order in orders:
        stats["checked"] += 1
        order_id = order.get("_id")
        if not order_id:
            continue
        current_bot_id = order_bot_id(order)
        if bot_id and current_bot_id and current_bot_id != bot_id:
            continue

        latest = await get_order(order_id)
        if not latest:
            continue
        if str(latest.get("status") or "").lower() in {"cancelled", "failed", "refunded", "expired"}:
            continue

        user = await get_user(int(latest.get("user_id") or 0))
        lang = (user or {}).get("language", "en")
        wait_state = str(latest.get("temp_wait_state") or "").strip().lower()

        if wait_state == "refund_pending":
            result = await cancel_and_refund_temp_order(
                order_id=order_id,
                order=latest,
                actor_user_id=int(latest.get("user_id") or 0),
                reason="global_temp_recovery_retry",
                require_no_sms=True,
            )
            if result.get("success"):
                stats["refund_retries"] += 1
                with suppress(Exception):
                    await safe_edit_message(
                        bot,
                        chat_id=int(latest.get("temp_wait_chat_id") or 0),
                        message_id=int(latest.get("temp_wait_message_id") or 0),
                        text=translations_t(lang, "temp_timeout_refunded_retry"),
                        reply_markup=temp_post_refund_kb(str(order_id), lang=lang, allow_replace=True),
                    )
            continue

        if wait_state == "code_received":
            continue

        provider = str(latest.get("provider") or "").strip()
        provider_order_id = str(latest.get("provider_order_id") or "").strip()
        if not provider or not provider_order_id:
            continue

        seen_codes = set(str(x) for x in (latest.get("temp_codes") or []) if x not in (None, ""))
        sms_data = await fetch_provider_sms(provider, provider_order_id)
        code = extract_new_sms_code((sms_data or {}).get("messages") or [], seen_codes)
        if code:
            code = safe_code_text(code)
            code_now = utc_now()
            updated_codes = list(seen_codes)
            updated_codes.append(code)
            patch = {
                "temp_wait_state": "code_received",
                "temp_last_sms_at": code_now,
                "temp_last_code": code,
                "temp_codes": updated_codes,
                "temp_codes_count": len(updated_codes),
            }
            if not latest.get("temp_first_sms_at"):
                patch["temp_first_sms_at"] = code_now
                seconds_to_first_sms = seconds_between(code_now, latest.get("created_at"))
                if seconds_to_first_sms is not None:
                    patch["temp_seconds_to_first_sms"] = seconds_to_first_sms
            await update_order_details(order_id, patch)
            await log_temp_event(latest, "code_received_recovery", {"code_len": len(code)})
            with suppress(Exception):
                await safe_edit_message(
                    bot,
                    chat_id=int(latest.get("temp_wait_chat_id") or 0),
                    message_id=int(latest.get("temp_wait_message_id") or 0),
                    text=temp_code_received_text(lang, code, latest),
                    reply_markup=temp_code_received_kb(str(order_id), lang=lang),
                    parse_mode="HTML",
                )
            stats["code_received"] += 1
            continue

        started_at = latest.get("temp_wait_started_at") or latest.get("created_at") or now_dt
        timeout_sec = order_temp_timeout_sec(latest)
        try:
            started_ts = started_at.timestamp()
        except Exception:
            started_ts = now_dt.timestamp()
        if now_dt.timestamp() >= (started_ts + timeout_sec):
            await send_temp_timeout_state(bot, latest, lang)
            stats["timed_out"] += 1
            continue

        await sync_temp_wait_controls(bot, latest, lang)
        stats["synced"] += 1

    return stats


async def run_unprovisioned_number_order_recovery_sweep(
    *,
    limit: int,
    grace_sec: int,
    utc_now: Callable[[], Any],
    list_paid_number_orders_missing_provider: Callable[..., Awaitable[list]],
    to_utc_datetime: Callable[[Any], Any],
    extract_order_amounts: Callable[[dict], tuple[float, float]],
    financial_manager: Any,
    update_order_status: Callable[..., Awaitable[None]],
    update_order_details: Callable[..., Awaitable[None]],
    log_number_event_from_order: Callable[..., Awaitable[None]],
) -> dict[str, Any]:
    stats = {"checked": 0, "refunded": 0, "refund_failures": 0, "skipped_recent": 0}
    now_dt = utc_now()
    orders = await list_paid_number_orders_missing_provider(limit=int(limit))
    for order in orders:
        stats["checked"] += 1
        order_id = order.get("_id")
        if not order_id:
            continue
        charged_at = to_utc_datetime(order.get("provisioning_charged_at")) or to_utc_datetime(order.get("created_at"))
        if not charged_at or (now_dt - charged_at).total_seconds() < int(grace_sec):
            stats["skipped_recent"] += 1
            continue

        sale_price, cost_price = extract_order_amounts(order)
        refund_ok, refund_msg = await financial_manager.refund_core_purchase(
            int(order.get("user_id") or 0),
            order_id,
            sale_price,
            cost_price,
            reseller_id=int(order.get("reseller_id") or order.get("user_id") or 0),
        )
        if refund_ok:
            await update_order_status(order_id, "refunded")
            await update_order_details(
                order_id,
                {
                    "provisioning_state": "recovered_refunded_unprovisioned",
                    "provisioning_recovered_at": now_dt,
                    "provisioning_recovery_reason": "missing_provider_order_id",
                },
            )
            await log_number_event_from_order(
                order,
                "refund_success",
                payload={"source": "unprovisioned_recovery"},
                status_after="refunded",
                number_mode=str(order.get("number_mode") or ""),
            )
            stats["refunded"] += 1
            continue

        await update_order_details(
            order_id,
            {
                "provisioning_state": "recovery_refund_failed",
                "provisioning_recovery_last_at": now_dt,
                "provisioning_recovery_last_error": str(refund_msg or "unknown_error"),
            },
        )
        await log_number_event_from_order(
            order,
            "refund_failed",
            payload={"source": "unprovisioned_recovery", "raw": str(refund_msg or "unknown_error")},
            status_after=str(order.get("status") or "paid"),
            number_mode=str(order.get("number_mode") or ""),
        )
        stats["refund_failures"] += 1
    return stats
