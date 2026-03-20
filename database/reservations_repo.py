from datetime import UTC, datetime, timedelta
from .mongo import db


async def create_reservation(order_id, user_id, amount, ledger_entry_id=None, chat_id=None, message_id=None):
    entry = {
        "order_id": order_id,
        "user_id": user_id,
        "amount": float(amount),
        "ledger_entry_id": ledger_entry_id,
        "status": "reserved",
        "created_at": datetime.now(UTC),
        "cancel_at": datetime.now(UTC) + timedelta(seconds=300),
        "expire_at": datetime.now(UTC) + timedelta(seconds=900),
        "chat_id": chat_id,
        "message_id": message_id,
    }
    res = await db.reservations.insert_one(entry)
    entry["_id"] = res.inserted_id
    return entry


async def get_reservation_by_order(order_id):
    return await db.reservations.find_one({"order_id": order_id})


async def get_reservation_by_message(chat_id, message_id):
    return await db.reservations.find_one({"chat_id": chat_id, "message_id": message_id})


async def update_reservation_status(order_id, status):
    await db.reservations.update_one({"order_id": order_id}, {"$set": {"status": status}})


async def release_reservation(order_id):
    # mark released
    await update_reservation_status(order_id, "released")


async def finalize_reservation(order_id):
    await update_reservation_status(order_id, "finalized")


