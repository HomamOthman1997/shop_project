# database/services_repo.py

from datetime import UTC, datetime
from .mongo import db


# -----------------------------
# Ø¥Ø¶Ø§ÙØ© Ø®Ø¯Ù…Ø© Ø¬Ø¯ÙŠØ¯Ø©
# -----------------------------
async def add_service(name: str, type: str, base_price: float, active=True):
    service = {
        "name": name,
        "type": type,  # core | custom
        "base_price": float(base_price),
        "active": active,
        "created_at": datetime.now(UTC)
    }
    result = await db.services.insert_one(service)
    service["_id"] = result.inserted_id
    return service


# -----------------------------
# Ø¬Ù„Ø¨ Ø®Ø¯Ù…Ø© Ø­Ø³Ø¨ Ø§Ù„Ø§Ø³Ù…
# -----------------------------
async def get_service(name: str):
    return await db.services.find_one({"name": name})


# -----------------------------
# Ø¬Ù„Ø¨ ÙƒÙ„ Ø§Ù„Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ø£Ø³Ø§Ø³ÙŠØ©
# -----------------------------
async def get_core_services():
    return await db.services.find({"type": "core"}).to_list(None)


# -----------------------------
# ØªØ­Ø¯ÙŠØ« Ø³Ø¹Ø± Ø§Ù„Ø®Ø¯Ù…Ø©
# -----------------------------
async def update_service_price(name: str, new_price: float):
    await db.services.update_one(
        {"name": name},
        {"$set": {"base_price": float(new_price)}}
    )


# -----------------------------
# ØªÙØ¹ÙŠÙ„ / ØªØ¹Ø·ÙŠÙ„ Ø®Ø¯Ù…Ø©
# -----------------------------
async def set_service_status(name: str, active: bool):
    await db.services.update_one(
        {"name": name},
        {"$set": {"active": active}}
    )

