import asyncio
import os
import sys

# Add project root so `database` imports work when running as a script.
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root not in sys.path:
    sys.path.insert(0, root)

from database.mongo import db


async def delete_all_bots_resellers_users():
    await db.bots.delete_many({})
    await db.users.delete_many({})
    await db.wallets.delete_many({})
    await db.ledger_entries.delete_many({})
    print("Deleted bots, users, and financial wallet/ledger data.")


if __name__ == "__main__":
    asyncio.run(delete_all_bots_resellers_users())
