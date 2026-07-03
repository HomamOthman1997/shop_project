"""Soft-deactivate (or restore) whole website_manual catalog sections.

Homam's 2026-07 catalog slim-down: chat apps / social services / store cards /
internet providers / paid apps are retired from the customer catalog. Their
nodes stay in Mongo but get is_active=False so no catalog query loads them.

Every node we touch is stamped with `website_bulk_hidden: <tag>` so `restore`
only reactivates nodes this script deactivated (never ones the admin deleted).

Usage:
    python scripts/toggle_hidden_catalog_sections.py hide [--dry-run] [--sections a,b]
    python scripts/toggle_hidden_catalog_sections.py restore [--dry-run] [--sections a,b]
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from database.mongo import db

CATALOG_TYPE = "website_manual"
# store_cards was hidden then brought back (2026-07-02) — keep it out of the default set.
HIDDEN_SECTION_KEYS = ("chat_apps", "social_services", "internet_providers", "paid_apps")
BULK_TAG = "slim-2026-07"


async def hide(dry_run: bool, sections: list[str]) -> None:
    query = {
        "catalog_type": CATALOG_TYPE,
        "is_active": True,
        "website_section_key": {"$in": sections},
    }
    count = await db.custom_services.count_documents(query)
    print(f"nodes to deactivate: {count}")
    if dry_run:
        return
    result = await db.custom_services.update_many(
        query, {"$set": {"is_active": False, "website_bulk_hidden": BULK_TAG}}
    )
    print(f"deactivated: {result.modified_count}")


async def restore(dry_run: bool, sections: list[str]) -> None:
    query = {
        "catalog_type": CATALOG_TYPE,
        "is_active": False,
        "website_bulk_hidden": BULK_TAG,
        "website_section_key": {"$in": sections},
    }
    count = await db.custom_services.count_documents(query)
    print(f"nodes to restore: {count}")
    if dry_run:
        return
    result = await db.custom_services.update_many(
        query, {"$set": {"is_active": True}, "$unset": {"website_bulk_hidden": ""}}
    )
    print(f"restored: {result.modified_count}")


def _sections_arg(args: list[str]) -> list[str]:
    for arg in args:
        if arg.startswith("--sections="):
            return [part.strip() for part in arg.split("=", 1)[1].split(",") if part.strip()]
        if arg == "--sections":
            index = args.index(arg)
            if index + 1 < len(args):
                return [part.strip() for part in args[index + 1].split(",") if part.strip()]
    return list(HIDDEN_SECTION_KEYS)


async def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"hide", "restore"}:
        raise SystemExit(__doc__)
    dry_run = "--dry-run" in sys.argv[2:]
    sections = _sections_arg(sys.argv[2:])
    if sys.argv[1] == "hide":
        await hide(dry_run, sections)
    else:
        await restore(dry_run, sections)


if __name__ == "__main__":
    asyncio.run(main())
