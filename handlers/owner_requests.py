from datetime import UTC, datetime
import logging

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramNetworkError
from bson import ObjectId

from config import OWNER_ID, settings
from database.bots_repo import add_bot, update_bot_channel, update_reseller_info, verify_bot
from database.financial_ledger import get_reseller_wallet_balance
from database.mongo import db
from services.subscriptions.bot_subscription_service import sync_bot_subscription
from utils.translations import t
from utils.user_money import format_usd

router = Router()
logger = logging.getLogger("owner_requests")


def _approval_packet_text(lang: str, payload: dict) -> str:
    return t(lang, "request_approved_packet").format(
        bot_title=payload.get("bot_title") or "-",
        bot_username=(f"@{payload.get('bot_username')}" if payload.get("bot_username") else "-"),
        bot_id=payload.get("bot_id") or "-",
        channel=payload.get("channel") or "-",
    )


def _trial_price() -> float:
    try:
        value = float(getattr(settings, "reseller_bot_trial_price_usd", 1.0) or 1.0)
    except Exception:
        value = 1.0
    return value if value > 0 else 1.0


def _subscription_activation_collected(subscription: dict) -> bool:
    status = str((subscription or {}).get("status") or "").strip().lower()
    return status in {"trial_active", "active"}


def _insufficient_trial_balance_error(lang: str, required: float, current: float) -> str:
    if str(lang or "").lower().startswith("ar"):
        return (
            "الرصيد غير كافٍ لتفعيل أول شهر تجريبي مدفوع.\n"
            f"المطلوب: {format_usd(required)}\n"
            f"الرصيد الحالي: {format_usd(current)}\n\n"
            "اشحن رصيدك في البوت المركزي ثم أعد المحاولة."
        )
    return (
        "Your balance is not enough to activate the paid trial month.\n"
        f"Required: {format_usd(required)}\n"
        f"Current balance: {format_usd(current)}\n\n"
        "Top up your balance in the main bot and try again."
    )


async def _notify_requester(req: dict, text: str) -> None:
    requester_id = req.get("requester_id")
    token = req.get("source_bot_token")
    if not requester_id or not token:
        return

    bot = None
    try:
        bot = Bot(token=token)
        for attempt in range(3):
            try:
                await bot.send_message(requester_id, text, request_timeout=20)
                return
            except TelegramNetworkError:
                if attempt == 2:
                    return
    except Exception:
        return
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass


async def review_bot_creation_request(
    *,
    request_id: str,
    action: str,
    reviewer_id: int,
    reviewer_username: str = "",
    source: str = "website_owner_api",
    chat_id: int | None = None,
    message_id: int | None = None,
    thread_id: int | None = None,
    reviewed_bot_id: int | None = None,
    notify_requester: bool = True,
) -> tuple[dict | None, str, str]:
    try:
        oid = ObjectId(str(request_id))
    except Exception:
        return None, "not_found", t("en", "owner_request_not_found")

    action = str(action or "").strip().lower()
    if action not in {"approve", "reject"}:
        return None, "invalid_action", t("en", "invalid_action")

    req = await db.bot_creation_requests.find_one({"_id": oid, "status": "pending"})
    if not req:
        return None, "not_found", t("en", "owner_request_not_found")

    payload = req.get("payload", {})
    requester_lang = req.get("requester_lang", "en")

    if action == "approve":
        try:
            exists = await db.bots.find_one({"bot_id": payload.get("bot_id"), "active": True})
            if exists:
                raise RuntimeError("Bot ID already registered")

            requester_id = int(req.get("requester_id") or 0)
            trial_price = _trial_price()
            current_balance = await get_reseller_wallet_balance(requester_id, wallet_type="main")
            if current_balance + 1e-9 < trial_price:
                raise RuntimeError(_insufficient_trial_balance_error(requester_lang, trial_price, current_balance))

            await add_bot(payload["bot_token"], req.get("requester_id"), payload["bot_id"])
            subscription = await sync_bot_subscription(int(payload["bot_id"]), collect_due=True)
            if not _subscription_activation_collected(subscription):
                await db.bots.delete_one({"bot_id": payload["bot_id"], "owner_id": requester_id})
                retry_balance = await get_reseller_wallet_balance(requester_id, wallet_type="main")
                raise RuntimeError(_insufficient_trial_balance_error(requester_lang, trial_price, retry_balance))

            await update_bot_channel(payload["bot_id"], payload["channel"])
            await update_reseller_info(payload["bot_id"], payload["fullname"], payload["phone"], payload["address"])
            await verify_bot(payload["bot_id"])
            new_status = "approved"
            owner_msg = t("en", "owner_request_approved")
            user_msg = (
                f"{t(requester_lang, 'request_approved_user_details')}\n\n"
                f"{_approval_packet_text(requester_lang, payload)}\n\n"
                f"{t(requester_lang, 'reseller_setup_post_approval')}"
            )
        except Exception as exc:
            logger.exception("owner approve failed for request=%s: %s", request_id, exc)
            new_status = "failed"
            owner_msg = t("en", "owner_approve_failed").format(error=exc)
            user_msg = t(requester_lang, "owner_approve_request_failed_user").format(error=exc)
    else:
        new_status = "rejected"
        owner_msg = t("en", "owner_request_rejected")
        user_msg = t(requester_lang, "request_rejected_user")

    safe_payload = {k: v for k, v in payload.items() if k != "bot_token"}
    await db.bot_creation_requests.update_one(
        {"_id": oid},
        {
            "$set": {
                "status": new_status,
                "reviewed_at": datetime.now(UTC),
                "reviewed_by": int(reviewer_id),
                "reviewed_by_username": reviewer_username or "",
                "reviewed_from_chat_id": chat_id,
                "reviewed_from_message_id": message_id,
                "reviewed_from_thread_id": thread_id,
                "audit": {
                    "action": action,
                    "source": source,
                    "reviewed_bot_id": reviewed_bot_id,
                    "payload_snapshot": safe_payload,
                },
            }
        },
    )
    reviewed = dict(req)
    reviewed.update(
        {
            "status": new_status,
            "reviewed_at": datetime.now(UTC),
            "reviewed_by": int(reviewer_id),
            "reviewed_by_username": reviewer_username or "",
            "reviewed_from_chat_id": chat_id,
            "reviewed_from_message_id": message_id,
            "reviewed_from_thread_id": thread_id,
            "audit": {
                "action": action,
                "source": source,
                "reviewed_bot_id": reviewed_bot_id,
                "payload_snapshot": safe_payload,
            },
        }
    )
    if notify_requester:
        await _notify_requester(req, user_msg)
    return reviewed, new_status, owner_msg


@router.callback_query(lambda c: c.data and c.data.startswith("verify_owner:"))
async def owner_review_callback(callback: types.CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return await callback.answer(t("en", "no_permission"), show_alert=True)

    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        return await callback.answer(t("en", "invalid_action"), show_alert=True)

    action = parts[1]
    req_id = parts[2]
    me = await callback.bot.get_me()
    reviewed, _status, owner_msg = await review_bot_creation_request(
        request_id=req_id,
        action=action,
        reviewer_id=callback.from_user.id,
        reviewer_username=callback.from_user.username or "",
        source="owner_requests_router",
        chat_id=callback.message.chat.id if callback.message else None,
        message_id=callback.message.message_id if callback.message else None,
        thread_id=getattr(callback.message, "message_thread_id", None) if callback.message else None,
        reviewed_bot_id=me.id,
    )
    if not reviewed:
        return await callback.answer(owner_msg, show_alert=True)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.answer(owner_msg, show_alert=True)



