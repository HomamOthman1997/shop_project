from __future__ import annotations

import re
from typing import Any

from config import settings
from database.custom_services_repo import get_node, list_catalog_nodes, list_children

CATALOG_TYPE = "website_manual"
_ACCENTS = {"green", "blue", "amber", "violet"}
_FIELD_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def owner_catalog_id() -> int:
    return int(getattr(settings, "owner_id", 0) or 0)


def clean_slug(value: Any) -> str:
    slug = str(value or "").strip().lower().replace("_", "-")
    return slug if re.fullmatch(r"[a-z0-9][a-z0-9-]{1,59}", slug) else ""


def clean_accent(value: Any) -> str:
    accent = str(value or "").strip().lower()
    return accent if accent in _ACCENTS else "green"


def clean_input_fields(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        field_id = str(row.get("id") or "").strip().lower()
        label = str(row.get("label") or "").strip()
        if not _FIELD_ID_RE.fullmatch(field_id) or not label or field_id in seen:
            continue
        seen.add(field_id)
        cleaned.append(
            {
                "id": field_id,
                "label": label[:80],
                "required": bool(row.get("required", True)),
                "type": "number" if str(row.get("type") or "").strip().lower() == "number" else "text",
            }
        )
    return cleaned


def parse_input_fields_text(value: Any) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for raw_line in str(value or "").splitlines():
        parts = [part.strip() for part in raw_line.split("|")]
        if len(parts) < 2:
            continue
        field_id, label = parts[:2]
        required = len(parts) < 3 or parts[2].lower() not in {"optional", "false", "0", "no"}
        field_type = parts[3].lower() if len(parts) > 3 else "text"
        fields.append({"id": field_id, "label": label, "required": required, "type": field_type})
    return clean_input_fields(fields)


def input_fields_text(fields: Any) -> str:
    rows = []
    for field in clean_input_fields(fields):
        required = "required" if field["required"] else "optional"
        rows.append(f'{field["id"]}|{field["label"]}|{required}|{field["type"]}')
    return "\n".join(rows)


def node_level(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    if bool(row.get("is_root")):
        return "root"
    return str(row.get("website_level") or "").strip().lower()


def expected_child(level: str) -> tuple[str, str] | None:
    return {
        "root": ("section", "folder"),
        "section": ("family", "folder"),
        "family": ("variant", "folder"),
        "variant": ("product", "endpoint"),
    }.get(str(level or "").strip().lower())


async def public_sections(owner_id: int | None = None) -> list[dict[str, Any]]:
    catalog_owner_id = int(owner_id or owner_catalog_id())
    if catalog_owner_id <= 0:
        return []
    nodes = await list_catalog_nodes(catalog_owner_id, catalog_type=CATALOG_TYPE)
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for row in nodes:
        by_parent.setdefault(str(row.get("parent_id") or ""), []).append(row)

    root = next((row for row in nodes if node_level(row) == "root"), None)
    if not root:
        return []

    sections: list[dict[str, Any]] = []
    for section in by_parent.get(str(root.get("_id") or ""), []):
        if node_level(section) != "section":
            continue
        section_slug = clean_slug(section.get("website_slug"))
        if not section_slug:
            continue
        categories = []
        for family in by_parent.get(str(section.get("_id") or ""), []):
            if node_level(family) != "family":
                continue
            variants = [row for row in by_parent.get(str(family.get("_id") or ""), []) if node_level(row) == "variant"]
            product_count = sum(
                1
                for variant in variants
                for product in by_parent.get(str(variant.get("_id") or ""), [])
                if node_level(product) == "product"
                and float(product.get("price") or 0) > 0
                and bool(clean_input_fields(product.get("input_fields")))
            )
            if product_count <= 0:
                continue
            family_id = str(family.get("_id") or "")
            categories.append(
                {
                    "slug": f"manual-{family_id}",
                    "title": str(family.get("name") or ""),
                    "subtitle": str(family.get("display_text") or f"{product_count} منتجات تنفيذ يدوي."),
                    "search_terms": str(family.get("name") or ""),
                    "generated": True,
                    "service_key": CATALOG_TYPE,
                    "family_key": family_id,
                    "manual": True,
                }
            )
        if categories:
            sections.append(
                {
                    "slug": section_slug,
                    "title": str(section.get("name") or section_slug),
                    "subtitle": str(section.get("display_text") or "خدمات ومنتجات يضيفها الأدمن وتنفذ يدوياً."),
                    "accent": clean_accent(section.get("website_accent")),
                    "service": "digital",
                    "enabled": True,
                    "status": "",
                    "categories": categories,
                    "categories_count": len(categories),
                }
            )
    return sections


async def family_packages(family_id: str, *, variant_id: str = "", owner_id: int | None = None) -> dict[str, Any] | None:
    catalog_owner_id = int(owner_id or owner_catalog_id())
    family = await get_node(family_id, reseller_id=catalog_owner_id, catalog_type=CATALOG_TYPE)
    if not family or node_level(family) != "family":
        return None
    variants = [row for row in await list_children(catalog_owner_id, family["_id"], catalog_type=CATALOG_TYPE) if node_level(row) == "variant"]
    public_variants = [
        {
            "id": str(row.get("_id") or ""),
            "name": str(row.get("name") or "Global"),
            "variant_kind": "region",
            "entry_kind": "manual",
            "image_url": "",
        }
        for row in variants
    ]
    selected = None
    if variant_id:
        selected = next((row for row in variants if str(row.get("_id") or "") == str(variant_id)), None)
        if not selected:
            return {"variant_not_found": True}
    elif len(variants) == 1:
        selected = variants[0]

    payload = {
        "ok": True,
        "service_key": CATALOG_TYPE,
        "family_key": str(family.get("_id") or ""),
        "family_name": str(family.get("name") or ""),
        "selection_kind": "general" if len(variants) <= 1 else "region",
        "requires_variant_selection": len(variants) > 1 and selected is None,
        "variants": public_variants,
        "selected_variant_id": str((selected or {}).get("_id") or ""),
        "selected_variant_name": str((selected or {}).get("name") or ""),
        "packages": [],
    }
    if not selected:
        return payload

    products = [
        row
        for row in await list_children(catalog_owner_id, selected["_id"], catalog_type=CATALOG_TYPE)
        if node_level(row) == "product" and float(row.get("price") or 0) > 0
    ]
    payload["packages"] = [public_product(row, family=family, variant=selected) for row in products]
    return payload


def public_product(row: dict[str, Any], *, family: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    price = float(row.get("price") or 0)
    return {
        "kind": "manual",
        "id": str(row.get("_id") or ""),
        "name": str(row.get("name") or ""),
        "item_name": str(row.get("name") or ""),
        "price_usd": price,
        "price_label": f"${price:.2f}",
        "provider": "manual_catalog",
        "duration": str(row.get("product_info_text") or ""),
        "input_fields": clean_input_fields(row.get("input_fields")),
        "manual_catalog": {
            "family_name": str(family.get("name") or ""),
            "variant_name": str(variant.get("name") or ""),
        },
    }


async def fresh_quote_payload(endpoint_id: str, *, owner_id: int | None = None) -> dict[str, Any] | None:
    catalog_owner_id = int(owner_id or owner_catalog_id())
    endpoint = await get_node(endpoint_id, reseller_id=catalog_owner_id, catalog_type=CATALOG_TYPE)
    if not endpoint or node_level(endpoint) != "product":
        return None
    price = float(endpoint.get("price") or 0)
    fields = clean_input_fields(endpoint.get("input_fields"))
    if price <= 0 or not fields:
        return None
    variant = await get_node(endpoint.get("parent_id"), reseller_id=catalog_owner_id, catalog_type=CATALOG_TYPE)
    family = await get_node((variant or {}).get("parent_id"), reseller_id=catalog_owner_id, catalog_type=CATALOG_TYPE)
    if node_level(variant) != "variant" or node_level(family) != "family":
        return None
    endpoint_ref = str(endpoint.get("_id") or "")
    return {
        "kind": "manual",
        "product_id": str(family.get("_id") or ""),
        "product_name": str(family.get("name") or ""),
        "item_id": endpoint_ref,
        "item_name": str(endpoint.get("name") or ""),
        "manual_variant_id": str(variant.get("_id") or ""),
        "manual_variant_name": str(variant.get("name") or ""),
        "input_fields": fields,
        "sale_price": price,
        "cost_price": price,
        "provider": "manual_catalog",
        "provider_ref_id": endpoint_ref,
        "provider_offers": [
            {
                "provider": "manual_catalog",
                "ref_id": endpoint_ref,
                "price": price,
                "available": True,
                "fulfillment_mode": "manual_topup",
                "source_product_name": str(family.get("name") or ""),
                "source_denomination_name": str(endpoint.get("name") or ""),
            }
        ],
    }
