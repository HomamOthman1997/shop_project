#!/usr/bin/env python3
"""Grant a user the reseller_id corresponding to a bot.

Usage:
  ./.venv/Scripts/python scripts/grant_reseller.py <telegram_id> <bot_id>

This sets the user's `reseller_id` to the bot id and marks the bot as verified
reseller (so it appears in reseller listings).
"""
import os
import sys
import asyncio
from datetime import UTC, datetime

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if root not in sys.path:
    sys.path.insert(0, root)

from database.mongo import db
from database.bots_repo import verify_bot

async def main(user_id: int, bot_id: int):
    # ensure user exists
    u = await db.users.find_one({'telegram_id': user_id})
    if not u:
        await db.users.insert_one({'telegram_id': user_id, 'language': 'en', 'created_at': datetime.now(UTC)})
    await db.users.update_one({'telegram_id': user_id}, {'$set': {'reseller_id': bot_id}})
    # mark bot as verified reseller if present
    await verify_bot(bot_id)
    print(f"Granted reseller_id={bot_id} to user {user_id} and verified bot {bot_id}")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Usage: grant_reseller.py <telegram_id> <bot_id>')
        raise SystemExit(1)
    asyncio.run(main(int(sys.argv[1]), int(sys.argv[2])))

