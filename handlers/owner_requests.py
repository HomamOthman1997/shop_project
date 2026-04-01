from datetime import UTC, datetime
import logging

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramNetworkError
from bson import ObjectId

from config import OWNER_ID
from database.bots_repo import add_bot, update_bot_channel, update_reseller_info, verify_bot
from database.mongo import db
from utils.translations import t

router = Router()
logger = logging.getLogger("owner_requests")


def _approval_packet_text(lang: str, payload: dict) -> str:
    return t(lang, "request_approved_packet").format(
        bot_title=payload.get("bot_title") or "-",
        bot_username=(f"@{payload.get('bot_username')}" if payload.get("bot_username") else "-"),
        bot_id=payload.get("bot_id") or "-",
        channel=payload.get("channel") or "-",
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


@router.callback_query(lambda c: c.data and c.data.startswith("verify_owner:"))
async def owner_review_callback(callback: types.CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return await callback.answer(t("en", "no_permission"), show_alert=True)

    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        return await callback.answer(t("en", "invalid_action"), show_alert=True)

    action = parts[1]
    req_id = parts[2]
    try:
        oid = ObjectId(req_id)
    except Exception:
        return await callback.answer(t("en", "owner_request_not_found"), show_alert=True)

    req = await db.bot_creation_requests.find_one({"_id": oid, "status": "pending"})
    if not req:
        return await callback.answer(t("en", "owner_request_not_found"), show_alert=True)

    payload = req.get("payload", {})
    requester_lang = req.get("requester_lang", "en")

    if action == "approve":
        try:
            exists = await db.bots.find_one({"bot_id": payload.get("bot_id"), "active": True})
            if exists:
                raise RuntimeError("Bot ID already registered")

            await add_bot(payload["bot_token"], req.get("requester_id"), payload["bot_id"])
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
            logger.exception("owner approve failed for request=%s: %s", req_id, exc)
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
                "reviewed_by": callback.from_user.id,
                "reviewed_by_username": callback.from_user.username or "",
                "reviewed_from_chat_id": callback.message.chat.id if callback.message else None,
                "reviewed_from_message_id": callback.message.message_id if callback.message else None,
                "reviewed_from_thread_id": getattr(callback.message, "message_thread_id", None) if callback.message else None,
                "audit": {
                    "action": action,
                    "source": "owner_requests_router",
                    "reviewed_bot_id": (await callback.bot.get_me()).id,
                    "payload_snapshot": safe_payload,
                },
            }
        },
    )

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.answer(owner_msg, show_alert=True)
    await _notify_requester(req, user_msg)



