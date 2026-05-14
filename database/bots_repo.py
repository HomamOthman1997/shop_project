from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from config import settings
from database.mongo import db
from services.subscriptions.bot_subscription_service import (
    activate_bot_subscription,
    bot_subscription_is_blocked,
    build_initial_subscription_for_owner,
    get_bot_subscription,
    get_bot_subscription_status,
    get_subscription_plan_options,
    mark_bot_subscription_grace_notice,
    run_bot_subscription_sweep,
    set_bot_subscription_plan,
    sync_bot_subscription,
)


class BotAlreadyRegisteredError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def bootstrap_bot_indexes() -> None:
    await db.bots.create_index(
        [("bot_id", 1)],
        unique=True,
        partialFilterExpression={"active": True},
        name="active_bot_id_unique",
        background=True,
    )
    await db.bots.create_index([("owner_id", 1), ("active", 1)], name="owner_active_lookup", background=True)
    await db.bot_creation_requests.create_index(
        [("status", 1), ("payload.bot_id", 1), ("created_at", -1)],
        background=True,
    )


async def add_bot(token: str, owner_id: int, bot_id: int):
    now = _utc_now()
    subscription = await build_initial_subscription_for_owner(int(owner_id), now=now)
    try:
        await db.bots.insert_one(
            {
                "bot_id": bot_id,
                "token": token,
                "owner_id": owner_id,
                "active": True,
                "created_at": now,
                "webhook_url": None,
                "subscription": subscription,
                "provisioning": {
                    "status": "creating",
                    "started_at": now,
                    "updated_at": now,
                    "source": "create_bot_flow",
                },
                "settings": {
                    "language": "en",
                    "subscription_channel": None,
                    "version": settings.bot_version,
                },
            }
        )
    except DuplicateKeyError as exc:
        raise BotAlreadyRegisteredError(f"bot_id {int(bot_id)} already exists") from exc
    await sync_bot_subscription(int(bot_id), collect_due=True)


async def mark_bot_provisioning_status(
    bot_id: int,
    status: str,
    *,
    active: bool | None = None,
    error: str | None = None,
) -> None:
    now = _utc_now()
    update = {
        "provisioning.status": str(status or "").strip() or "unknown",
        "provisioning.updated_at": now,
    }
    if active is not None:
        update["active"] = bool(active)
    if error:
        update["provisioning.error"] = str(error)[:500]
    elif status == "active":
        update["provisioning.error"] = ""
    await db.bots.update_one({"bot_id": int(bot_id)}, {"$set": update})


async def get_active_bots():
    return await db.bots.find({"active": True}).to_list(None)


async def deactivate_bot(bot_id: int):
    await db.bots.update_one({"bot_id": bot_id}, {"$set": {"active": False}})


async def get_bot_settings(bot_id: int):
    bot = await db.bots.find_one({"bot_id": bot_id})
    if not bot:
        return {}
    return bot.get("settings", {})


async def update_bot_channel(bot_id: int, channel: str):
    await db.bots.update_one({"bot_id": bot_id}, {"$set": {"settings.subscription_channel": channel}})


async def get_verified_bots():
    return await db.bots.find({"active": True, "reseller.verified": True}).to_list(None)


async def get_bot_token(bot_id: int):
    bot = await db.bots.find_one({"bot_id": bot_id})
    return bot["token"]


async def get_bot_by_id(bot_id: int):
    return await db.bots.find_one({"bot_id": bot_id, "active": True})


async def get_reseller_id_for_bot(bot_id: int):
    bot = await get_bot_by_id(bot_id)
    if not bot:
        return None
    return bot.get("owner_id")


def _configured_platform_bot_ids() -> set[int]:
    values: set[int] = set()
    for attr in ("bot_main_token", "bot_digital_products_token", "bot_card_ex_token"):
        try:
            value = int(str(getattr(settings, attr, "") or "").split(":", 1)[0] or 0)
        except Exception:
            value = 0
        if value > 0:
            values.add(value)
    return values


async def get_store_owner_scope_for_bot(bot_id: int):
    owner_id = await get_reseller_id_for_bot(bot_id)
    if owner_id:
        return owner_id
    if int(bot_id) in _configured_platform_bot_ids():
        platform_owner_id = int(getattr(settings, "owner_id", 0) or 0)
        return platform_owner_id or None
    return None


async def update_reseller_info(bot_id, fullname, phone, address):
    await db.bots.update_one(
        {"bot_id": bot_id},
        {
            "$set": {
                "reseller.full_name": fullname,
                "reseller.phone": phone,
                "reseller.address": address,
            }
        },
    )


async def verify_bot(bot_id):
    await db.bots.update_one({"bot_id": bot_id}, {"$set": {"reseller.verified": True}})
