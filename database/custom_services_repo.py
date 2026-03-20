from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from bson import ObjectId
from pymongo import ReturnDocument

from database.mongo import db

_CUSTOM_GRID_COLUMNS = 3


def _to_oid(value) -> Optional[ObjectId]:
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return value
    return ObjectId(str(value))


def _norm_catalog_type(catalog_type: str | None) -> str:
    raw = str(catalog_type or "").strip().lower()
    if raw in {"idinfo", "id_info", "id-info", "id info"}:
        return "id_info"
    return "custom"


async def bootstrap_custom_services_indexes() -> None:
    await db.custom_services.create_index([("reseller_id", 1), ("parent_id", 1), ("is_active", 1)], background=True)
    await db.custom_services.create_index([("reseller_id", 1), ("node_type", 1), ("is_active", 1)], background=True)
    await db.custom_services.create_index([("reseller_id", 1), ("name", 1)], background=True)
    await db.custom_services.create_index([("reseller_id", 1), ("catalog_type", 1), ("parent_id", 1), ("is_active", 1)], background=True)


async def ensure_root_node(reseller_id: int, *, catalog_type: str = "custom") -> dict:
    catalog = _norm_catalog_type(catalog_type)
    now = datetime.now(UTC)
    root = await db.custom_services.find_one(
        {
            "reseller_id": reseller_id,
            "catalog_type": catalog,
            "parent_id": None,
            "node_type": "folder",
            "is_root": True,
        }
    )
    if root:
        return root
    doc = {
        "reseller_id": reseller_id,
        "catalog_type": catalog,
        "name": "ID INFO" if catalog == "id_info" else "Services",
        "node_type": "folder",
        "parent_id": None,
        "is_root": True,
        "is_active": True,
        "position": 0,
        "created_at": now,
        "updated_at": now,
    }
    res = await db.custom_services.insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


async def get_node(node_id, reseller_id: Optional[int] = None, *, catalog_type: Optional[str] = None) -> Optional[dict]:
    query = {"_id": _to_oid(node_id), "is_active": True}
    if reseller_id is not None:
        query["reseller_id"] = reseller_id
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)
    return await db.custom_services.find_one(query)


async def list_children(reseller_id: int, parent_id=None, *, catalog_type: str = "custom") -> list[dict]:
    return await db.custom_services.find(
        {
            "reseller_id": reseller_id,
            "catalog_type": _norm_catalog_type(catalog_type),
            "parent_id": _to_oid(parent_id),
            "is_active": True,
        }
    ).sort("position", 1).to_list(None)


async def _next_position(reseller_id: int, parent_id=None, *, catalog_type: str = "custom") -> int:
    node = await db.custom_services.find_one(
        {
            "reseller_id": reseller_id,
            "catalog_type": _norm_catalog_type(catalog_type),
            "parent_id": _to_oid(parent_id),
        },
        sort=[("position", -1)],
    )
    return int(node.get("position", -1) + 1) if node else 0


async def create_folder(reseller_id: int, parent_id, name: str, *, catalog_type: str = "custom") -> dict:
    catalog = _norm_catalog_type(catalog_type)
    now = datetime.now(UTC)
    doc = {
        "reseller_id": reseller_id,
        "catalog_type": catalog,
        "name": name.strip(),
        "node_type": "folder",
        "parent_id": _to_oid(parent_id),
        "is_root": False,
        "is_active": True,
        "position": await _next_position(reseller_id, parent_id, catalog_type=catalog),
        "created_at": now,
        "updated_at": now,
    }
    res = await db.custom_services.insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


async def create_endpoint(
    reseller_id: int,
    parent_id,
    name: str,
    price: float,
    available_qty: int,
    min_qty: int = 1,
    *,
    catalog_type: str = "custom",
) -> dict:
    catalog = _norm_catalog_type(catalog_type)
    now = datetime.now(UTC)
    doc = {
        "reseller_id": reseller_id,
        "catalog_type": catalog,
        "name": name.strip(),
        "node_type": "endpoint",
        "parent_id": _to_oid(parent_id),
        "is_root": False,
        "is_active": True,
        "position": await _next_position(reseller_id, parent_id, catalog_type=catalog),
        "price": float(price),
        "available_qty": int(available_qty),
        "inventory_items": [],
        "product_info_text": "",
        "min_qty": max(1, int(min_qty)),
        "created_at": now,
        "updated_at": now,
    }
    res = await db.custom_services.insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


async def update_endpoint(
    node_id,
    reseller_id: int,
    *,
    price: float,
    available_qty: int,
    min_qty: int,
    catalog_type: Optional[str] = None,
    ) -> Optional[dict]:
    query = {
        "_id": _to_oid(node_id),
        "reseller_id": reseller_id,
        "node_type": "endpoint",
        "is_active": True,
    }
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)

    current = await db.custom_services.find_one(query)
    if not current:
        return None
    inv_items = list(current.get("inventory_items") or [])
    next_available = len(inv_items) if inv_items else int(available_qty)

    return await db.custom_services.find_one_and_update(
        query,
        {
            "$set": {
                "price": float(price),
                "available_qty": int(next_available),
                "min_qty": max(1, int(min_qty)),
                "updated_at": datetime.now(UTC),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


async def update_endpoint_delivery(
    node_id,
    reseller_id: int,
    *,
    delivery_type: str,
    delivery_text: str | None = None,
    delivery_file_id: str | None = None,
    delivery_caption: str | None = None,
    delivery_filename: str | None = None,
    catalog_type: Optional[str] = None,
) -> Optional[dict]:
    query = {
        "_id": _to_oid(node_id),
        "reseller_id": int(reseller_id),
        "node_type": "endpoint",
        "is_active": True,
    }
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)

    dtype = str(delivery_type or "").strip().lower()
    if dtype not in {"text", "photo", "document"}:
        return None

    payload = {
        "delivery_type": dtype,
        "updated_at": datetime.now(UTC),
    }
    if dtype == "text":
        payload["delivery_text"] = str(delivery_text or "").strip()
        payload["delivery_file_id"] = None
        payload["delivery_caption"] = None
        payload["delivery_filename"] = None
    else:
        payload["delivery_text"] = None
        payload["delivery_file_id"] = str(delivery_file_id or "").strip()
        payload["delivery_caption"] = str(delivery_caption or "").strip()
        payload["delivery_filename"] = str(delivery_filename or "").strip()

    return await db.custom_services.find_one_and_update(
        query,
        {"$set": payload},
        return_document=ReturnDocument.AFTER,
    )


async def update_endpoint_product_info(
    node_id,
    reseller_id: int,
    product_info_text: str | None,
    *,
    catalog_type: Optional[str] = None,
) -> Optional[dict]:
    query = {
        "_id": _to_oid(node_id),
        "reseller_id": int(reseller_id),
        "node_type": "endpoint",
        "is_active": True,
    }
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)

    return await db.custom_services.find_one_and_update(
        query,
        {
            "$set": {
                "product_info_text": str(product_info_text or "").strip(),
                "updated_at": datetime.now(UTC),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


async def set_endpoint_inventory(
    node_id,
    reseller_id: int,
    *,
    inventory_items: list[str],
    catalog_type: Optional[str] = None,
) -> Optional[dict]:
    query = {
        "_id": _to_oid(node_id),
        "reseller_id": int(reseller_id),
        "node_type": "endpoint",
        "is_active": True,
    }
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)

    cleaned = [str(item or "").strip() for item in (inventory_items or [])]
    cleaned = [item for item in cleaned if item]

    payload = {
        "inventory_items": cleaned,
        "available_qty": len(cleaned),
        "delivery_type": "inventory",
        "delivery_text": None,
        "delivery_file_id": None,
        "delivery_caption": None,
        "delivery_filename": None,
        "updated_at": datetime.now(UTC),
    }
    return await db.custom_services.find_one_and_update(
        query,
        {"$set": payload},
        return_document=ReturnDocument.AFTER,
    )


async def rename_node(
    node_id,
    reseller_id: int,
    new_name: str,
    *,
    catalog_type: Optional[str] = None,
) -> Optional[dict]:
    query = {
        "_id": _to_oid(node_id),
        "reseller_id": int(reseller_id),
        "is_active": True,
    }
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)
    return await db.custom_services.find_one_and_update(
        query,
        {
            "$set": {
                "name": str(new_name or "").strip(),
                "updated_at": datetime.now(UTC),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


async def update_node_display_text(
    node_id,
    reseller_id: int,
    display_text: str | None,
    *,
    catalog_type: Optional[str] = None,
) -> Optional[dict]:
    query = {
        "_id": _to_oid(node_id),
        "reseller_id": int(reseller_id),
        "is_active": True,
    }
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)

    set_payload = {"updated_at": datetime.now(UTC)}
    update_payload: dict = {"$set": set_payload}
    text = str(display_text or "").strip()
    if text:
        set_payload["display_text"] = text
    else:
        update_payload["$unset"] = {"display_text": ""}

    return await db.custom_services.find_one_and_update(
        query,
        update_payload,
        return_document=ReturnDocument.AFTER,
    )


async def deactivate_node(node_id, reseller_id: int, *, catalog_type: Optional[str] = None) -> int:
    root_id = _to_oid(node_id)
    if root_id is None:
        return 0

    # Soft-delete full subtree to avoid leaving active orphan nodes.
    pending = [root_id]
    collected: list[ObjectId] = []
    visited: set[ObjectId] = set()
    while pending:
        current = pending.pop(0)
        if current in visited:
            continue
        visited.add(current)
        collected.append(current)
        query = {
            "reseller_id": int(reseller_id),
            "parent_id": current,
            "is_active": True,
        }
        if catalog_type is not None:
            query["catalog_type"] = _norm_catalog_type(catalog_type)
        children = await db.custom_services.find(
            query,
            {"_id": 1},
        ).to_list(None)
        pending.extend([row["_id"] for row in children if row.get("_id") is not None])

    if not collected:
        return 0

    update_query = {"reseller_id": int(reseller_id), "_id": {"$in": collected}}
    if catalog_type is not None:
        update_query["catalog_type"] = _norm_catalog_type(catalog_type)
    result = await db.custom_services.update_many(
        update_query,
        {"$set": {"is_active": False, "updated_at": datetime.now(UTC)}},
    )
    return int(result.modified_count or 0)


async def reserve_endpoint_stock(node_id, reseller_id: int, qty: int, *, catalog_type: Optional[str] = None) -> Optional[dict]:
    query = {
        "_id": _to_oid(node_id),
        "reseller_id": reseller_id,
        "node_type": "endpoint",
        "is_active": True,
        "available_qty": {"$gte": int(qty)},
    }
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)
    return await db.custom_services.find_one_and_update(
        query,
        {"$inc": {"available_qty": -int(qty)}, "$set": {"updated_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )


async def claim_endpoint_inventory(
    node_id,
    reseller_id: int,
    qty: int,
    *,
    catalog_type: Optional[str] = None,
) -> Optional[dict]:
    qty_i = max(1, int(qty))
    query = {
        "_id": _to_oid(node_id),
        "reseller_id": int(reseller_id),
        "node_type": "endpoint",
        "is_active": True,
        "available_qty": {"$gte": qty_i},
        "$expr": {"$gte": [{"$size": {"$ifNull": ["$inventory_items", []]}}, qty_i]},
    }
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)

    before = await db.custom_services.find_one_and_update(
        query,
        [
            {
                "$set": {
                    "inventory_items": {"$slice": [{"$ifNull": ["$inventory_items", []]}, qty_i, 1000000]},
                    "available_qty": {"$subtract": [{"$ifNull": ["$available_qty", 0]}, qty_i]},
                    "updated_at": datetime.now(UTC),
                }
            }
        ],
        return_document=ReturnDocument.BEFORE,
    )
    if not before:
        return None

    items = [str(x or "").strip() for x in list(before.get("inventory_items") or [])[:qty_i]]
    items = [x for x in items if x]
    if len(items) < qty_i:
        return None

    remaining_qty = max(0, int(before.get("available_qty") or 0) - qty_i)
    return {
        "endpoint_before": before,
        "claimed_items": items,
        "remaining_qty": remaining_qty,
    }


async def release_endpoint_stock(
    node_id,
    reseller_id: int,
    qty: int,
    *,
    catalog_type: Optional[str] = None,
    claimed_items: Optional[list[str]] = None,
) -> None:
    query = {
        "_id": _to_oid(node_id),
        "reseller_id": reseller_id,
        "node_type": "endpoint",
        "is_active": True,
    }
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)
    now = datetime.now(UTC)
    cleaned = [str(item or "").strip() for item in (claimed_items or [])]
    cleaned = [item for item in cleaned if item]
    if cleaned:
        await db.custom_services.update_one(
            query,
            {
                "$inc": {"available_qty": len(cleaned)},
                "$push": {"inventory_items": {"$each": cleaned, "$position": 0}},
                "$set": {"updated_at": now},
            },
        )
        return

    await db.custom_services.update_one(
        query,
        {"$inc": {"available_qty": int(qty)}, "$set": {"updated_at": now}},
    )


async def move_node_in_parent(
    node_id,
    reseller_id: int,
    direction: str,
    *,
    catalog_type: Optional[str] = None,
) -> tuple[bool, str]:
    oid = _to_oid(node_id)
    if oid is None:
        return False, "invalid_node"

    query = {"_id": oid, "reseller_id": int(reseller_id), "is_active": True}
    if catalog_type is not None:
        query["catalog_type"] = _norm_catalog_type(catalog_type)
    node = await db.custom_services.find_one(query)
    if not node:
        return False, "node_not_found"

    parent_id = node.get("parent_id")
    if parent_id is None:
        return False, "root_not_movable"

    siblings_query = {
        "reseller_id": int(reseller_id),
        "parent_id": parent_id,
        "is_active": True,
    }
    if catalog_type is not None:
        siblings_query["catalog_type"] = _norm_catalog_type(catalog_type)
    siblings = await db.custom_services.find(siblings_query).sort("position", 1).to_list(None)
    if not siblings:
        return False, "no_siblings"

    index_by_id = {str(item.get("_id")): idx for idx, item in enumerate(siblings)}
    idx = index_by_id.get(str(oid))
    if idx is None:
        return False, "node_not_in_parent"

    current_pos = int(node.get("position", idx))
    col = int(current_pos % _CUSTOM_GRID_COLUMNS)

    step_by_direction = {
        "left": -1,
        "right": 1,
        "up": -_CUSTOM_GRID_COLUMNS,
        "down": _CUSTOM_GRID_COLUMNS,
    }
    direction_norm = str(direction or "").strip().lower()
    step = step_by_direction.get(direction_norm)
    if step is None:
        return False, "invalid_direction"
    if direction_norm == "left" and col == 0:
        return False, "edge"
    if direction_norm == "right" and col == (_CUSTOM_GRID_COLUMNS - 1):
        return False, "edge"
    if direction_norm == "up" and current_pos < _CUSTOM_GRID_COLUMNS:
        return False, "edge"

    target_pos = current_pos + step
    if target_pos < 0:
        return False, "edge"

    now = datetime.now(UTC)
    occupied_positions = {int(item.get("position", i)) for i, item in enumerate(siblings) if str(item.get("_id")) != str(oid)}

    # Keep visual grid gaps when moving into an occupied slot:
    # shift a range of siblings, then place the moved node.
    if target_pos in occupied_positions:
        shift_query = {
            "reseller_id": int(reseller_id),
            "is_active": True,
            "parent_id": parent_id,
            "_id": {"$ne": oid},
            "position": {"$gte": target_pos},
        }
        if catalog_type is not None:
            shift_query["catalog_type"] = _norm_catalog_type(catalog_type)
        await db.custom_services.update_many(
            shift_query,
            {"$inc": {"position": 1}, "$set": {"updated_at": now}},
        )

    await db.custom_services.update_one(
        {"_id": oid, "reseller_id": int(reseller_id)},
        {"$set": {"position": target_pos, "updated_at": now}},
    )
    return True, "ok"


async def clone_catalog_from_reseller_template(
    *,
    source_reseller_id: int,
    target_reseller_id: int,
    catalog_type: str = "custom",
) -> dict:
    source_reseller_id = int(source_reseller_id)
    target_reseller_id = int(target_reseller_id)
    catalog = _norm_catalog_type(catalog_type)
    if source_reseller_id <= 0 or target_reseller_id <= 0:
        return {"success": False, "reason": "invalid_reseller_id"}
    if source_reseller_id == target_reseller_id:
        return {"success": False, "reason": "same_reseller"}

    source_root = await ensure_root_node(source_reseller_id, catalog_type=catalog)
    target_root = await ensure_root_node(target_reseller_id, catalog_type=catalog)

    # Do not overwrite existing reseller custom structure.
    target_children = await list_children(target_reseller_id, target_root["_id"], catalog_type=catalog)
    if target_children:
        return {"success": False, "reason": "target_not_empty", "copied": 0}

    now = datetime.now(UTC)
    copied = 0
    queue: list[tuple[ObjectId, ObjectId]] = [(source_root["_id"], target_root["_id"])]
    while queue:
        src_parent_id, dst_parent_id = queue.pop(0)
        src_children = await db.custom_services.find(
            {
                "reseller_id": source_reseller_id,
                "catalog_type": catalog,
                "parent_id": src_parent_id,
                "is_active": True,
            }
        ).sort("position", 1).to_list(None)

        for src in src_children:
            clone_doc = {
                "reseller_id": target_reseller_id,
                "catalog_type": catalog,
                "name": str(src.get("name") or "").strip() or "Unnamed",
                "node_type": str(src.get("node_type") or "folder"),
                "parent_id": dst_parent_id,
                "is_root": False,
                "is_active": True,
                "position": int(src.get("position") or 0),
                "created_at": now,
                "updated_at": now,
            }
            if str(src.get("node_type") or "") == "endpoint":
                clone_doc["price"] = float(src.get("price") or 0.0)
                clone_doc["available_qty"] = int(src.get("available_qty") or 0)
                clone_doc["min_qty"] = max(1, int(src.get("min_qty") or 1))
                clone_doc["inventory_items"] = list(src.get("inventory_items") or [])
                clone_doc["product_info_text"] = str(src.get("product_info_text") or "").strip()
                clone_doc["delivery_type"] = str(src.get("delivery_type") or "").strip().lower()
                clone_doc["delivery_text"] = str(src.get("delivery_text") or "").strip()
                clone_doc["delivery_file_id"] = str(src.get("delivery_file_id") or "").strip()
                clone_doc["delivery_caption"] = str(src.get("delivery_caption") or "").strip()
                clone_doc["delivery_filename"] = str(src.get("delivery_filename") or "").strip()
            display_text = str(src.get("display_text") or "").strip()
            if display_text:
                clone_doc["display_text"] = display_text

            ins = await db.custom_services.insert_one(clone_doc)
            copied += 1
            if clone_doc["node_type"] == "folder":
                queue.append((src["_id"], ins.inserted_id))

    return {"success": True, "reason": "ok", "copied": copied}

