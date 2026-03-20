#!/usr/bin/env python3
r"""List reseller accounts and their current deposits.

Run from project root with the virtualenv interpreter, e.g.::

    .\.venv\Scripts\python scripts/list_resellers.py

The script queries both the ``users`` collection (to discover which
users have a ``reseller_id``) and the current ``wallets`` collection
for any additional IDs that have financial records but no corresponding
user record.
"""
import os
import sys

# ensure project root on path
root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if root not in sys.path:
    sys.path.insert(0, root)

import asyncio
from database.financial_ledger import get_reseller_wallet_balance
from database.mongo import db


async def main():
    # collect ids from users table
    users = await db.users.find({}, {'reseller_id': 1, 'telegram_id': 1}).to_list(None)
    ids = set()
    for u in users:
        rid = u.get('reseller_id') or u.get('telegram_id')
        if rid is not None:
            ids.add(rid)
    # also include any ids appearing in current wallet storage
    wallet_ids = await db.wallets.distinct('owner_id', {"owner_type": "reseller"})
    for rid in wallet_ids:
        ids.add(rid)

    if not ids:
        print('No reseller accounts found.')
        return

    for rid in sorted(ids):
        bal = await get_reseller_wallet_balance(int(rid), wallet_type='main')
        print(f"{rid}: {bal:.2f}")


if __name__ == '__main__':
    asyncio.run(main())
