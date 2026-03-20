#!/usr/bin/env python3
r"""Simple CLI to credit a reseller account.

Run this from the project root using the virtual environment's interpreter, e.g.:::

    .\.venv\Scripts\python scripts/topup_reseller.py <username> <amount>

or, once the venv is activated and on your path, use the module form::

    python -m scripts.topup_reseller <username> <amount>

The script adds the project root to ``sys.path`` so that the ``database``
package can be imported even when the script lives in the ``scripts/``
subfolder.  If you see ``ModuleNotFoundError`` for a dependency, you're
probably running the system Python instead of the virtualenv.
"""
import asyncio
import os
import sys

# when executed as a script the default sys.path[0] is the scripts/ directory,
# which means sibling packages such as `database` are not importable.  Insert
# the project root so imports work regardless of how the script is invoked.
root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if root not in sys.path:
    sys.path.insert(0, root)

from database.financial_ledger import credit_reseller_main_wallet, get_reseller_wallet_balance
from database.mongo import db

async def main(username: str, amount: float):
    # find user by username
    user = await db.users.find_one({"username": username})
    if not user:
        print('User not found')
        return
    reseller_id = user.get('reseller_id') or user.get('telegram_id')
    await credit_reseller_main_wallet(
        reseller_id=int(reseller_id),
        amount=float(amount),
        reason='script_reseller_deposit',
        actor_id=int(reseller_id),
    )
    new_balance = await get_reseller_wallet_balance(int(reseller_id), wallet_type='main')
    print(f'Added deposit to reseller {int(reseller_id)}. New main balance: {new_balance:.2f}')

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print('Usage: topup_reseller.py USERNAME AMOUNT')
        raise SystemExit(1)
    asyncio.run(main(sys.argv[1].lstrip('@'), float(sys.argv[2])))
