from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

sys.path.insert(0, os.getcwd())

from config import OWNER_ID
from database.custom_services_repo import (
    bootstrap_custom_services_indexes,
    create_endpoint,
    create_folder,
    ensure_root_node,
    get_node,
    list_children,
    set_endpoint_inventory,
)
from handlers.custom_services import _execute_buy


class _SmokeState:
    def __init__(self, data: dict):
        self._data = dict(data)
        self.cleared = False
        self.state = None

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def set_state(self, value):
        self.state = value

    async def clear(self):
        self.cleared = True


class _SmokeBot:
    async def get_me(self):
        return SimpleNamespace(id=0)

    async def send_message(self, chat_id: int, text: str, **kwargs):
        return SimpleNamespace(chat_id=chat_id, text=text, kwargs=kwargs)


class _SmokeMessage:
    def __init__(self, user_id: int):
        self.from_user = SimpleNamespace(id=int(user_id))
        self.bot = _SmokeBot()
        self.answers: list[dict] = []
        self.edits: list[dict] = []

    async def answer(self, text: str, **kwargs):
        self.answers.append({"text": str(text), "kwargs": kwargs})
        return SimpleNamespace(message_id=len(self.answers))

    async def edit_text(self, text: str, **kwargs):
        self.edits.append({"text": str(text), "kwargs": kwargs})
        return SimpleNamespace(message_id=len(self.edits))


async def _find_or_create_smoke_folder(catalog_owner_id: int):
    root = await ensure_root_node(catalog_owner_id, catalog_type="custom")
    children = await list_children(catalog_owner_id, root["_id"], catalog_type="custom")
    for child in children:
        if str(child.get("name") or "") == "[SMOKE] Custom Services":
            return child
    return await create_folder(catalog_owner_id, root["_id"], "[SMOKE] Custom Services", catalog_type="custom")


async def run_smoke(*, buyer_id: int, catalog_owner_id: int, price: float, qty: int) -> dict:
    await bootstrap_custom_services_indexes()
    folder = await _find_or_create_smoke_folder(catalog_owner_id)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    endpoint = await create_endpoint(
        catalog_owner_id,
        folder["_id"],
        f"[SMOKE] Inventory {stamp}",
        float(price),
        0,
        1,
        catalog_type="custom",
    )
    stock_items = [
        f"Email: smoke-{stamp}-1@example.test\nPassword: pass-1\nRecovery: smoke",
        f"Email: smoke-{stamp}-2@example.test\nPassword: pass-2\nRecovery: smoke",
        f"Email: smoke-{stamp}-3@example.test\nPassword: pass-3\nRecovery: smoke",
    ]
    endpoint = await set_endpoint_inventory(
        endpoint["_id"],
        catalog_owner_id,
        inventory_items=stock_items,
        raw_payload="\n---\n".join(stock_items),
        catalog_type="custom",
    )
    if not endpoint:
        raise RuntimeError("failed_to_seed_endpoint_inventory")

    state = _SmokeState(
        {
            "buy_endpoint_id": str(endpoint["_id"]),
            "buy_catalog_owner_id": int(catalog_owner_id),
            "buy_wallet_scope_id": int(buyer_id),
            "buy_catalog_type": "custom",
            "buy_pending_qty": int(qty),
            "buy_min_qty": 1,
            "buy_unit_price": float(price),
            "buy_service_name": str(endpoint.get("name") or "Smoke Inventory"),
            "buy_financial_mode": "custom",
            "buy_return_node_id": str(folder["_id"]),
        }
    )
    message = _SmokeMessage(buyer_id)
    await _execute_buy(message, state, buyer_id, result_message=message)
    refreshed = await get_node(endpoint["_id"], reseller_id=catalog_owner_id, catalog_type="custom")

    return {
        "ok": bool(message.edits or message.answers),
        "buyer_id": int(buyer_id),
        "catalog_owner_id": int(catalog_owner_id),
        "folder_id": str(folder["_id"]),
        "endpoint_id": str(endpoint["_id"]),
        "endpoint_name": str(endpoint.get("name") or ""),
        "price": float(price),
        "qty_bought": int(qty),
        "stock_before": len(stock_items),
        "stock_after": int((refreshed or {}).get("available_qty") or 0),
        "state_cleared": bool(state.cleared),
        "answers": [row["text"] for row in message.answers],
        "edits": [row["text"] for row in message.edits],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and buy a disposable Custom Services smoke product.")
    parser.add_argument("--buyer-id", type=int, default=int(OWNER_ID or 0))
    parser.add_argument("--catalog-owner-id", type=int, default=int(OWNER_ID or 0))
    parser.add_argument("--price", type=float, default=0.0)
    parser.add_argument("--qty", type=int, default=1)
    args = parser.parse_args()
    if args.buyer_id <= 0 or args.catalog_owner_id <= 0:
        raise SystemExit("buyer-id and catalog-owner-id are required")
    report = asyncio.run(
        run_smoke(
            buyer_id=args.buyer_id,
            catalog_owner_id=args.catalog_owner_id,
            price=max(0.0, float(args.price)),
            qty=max(1, int(args.qty)),
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
