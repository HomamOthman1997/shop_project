from __future__ import annotations

import re
from typing import Any

from config import settings
from database.custom_services_repo import (
    create_endpoint,
    create_folder,
    ensure_root_node,
    get_node,
    list_catalog_nodes,
    list_children,
    move_node_to_parent,
    update_endpoint_product_info,
    update_node_display_text,
    update_node_website_metadata,
)
from services.digital_products.custom_catalog import FAMILY_TABLE, SECTION_TABLE

CATALOG_TYPE = "website_manual"
_ACCENTS = {"green", "blue", "amber", "violet"}
_FIELD_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_CATALOG_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_MANUAL_VARIANT_PREFIX = "manual:"
EXECUTION_MODE_MANUAL = "manual"
EXECUTION_MODE_API = "api"
_SECTION_SLUG_BY_SERVICE = {
    "games": "games",
    "chat_apps": "chat-apps",
    "social_services": "social-services",
    "communications_data": "mobile-recharge",
    "numbers_services": "verification-numbers",
    "paid_subscriptions": "subscriptions",
    "store_cards": "store-cards",
    "internet_providers": "internet-providers",
    "paid_apps": "paid-apps",
}
_SECTION_ACCENT_BY_SERVICE = {
    "games": "green",
    "chat_apps": "blue",
    "social_services": "violet",
    "communications_data": "blue",
    "numbers_services": "amber",
    "paid_subscriptions": "violet",
    "store_cards": "amber",
    "internet_providers": "green",
    "paid_apps": "violet",
}


def owner_catalog_id() -> int:
    return int(getattr(settings, "owner_id", 0) or 0)


def clean_slug(value: Any) -> str:
    slug = str(value or "").strip().lower().replace("_", "-")
    return slug if re.fullmatch(r"[a-z0-9][a-z0-9-]{1,59}", slug) else ""


def clean_accent(value: Any) -> str:
    accent = str(value or "").strip().lower()
    return accent if accent in _ACCENTS else "green"


def clean_catalog_key(value: Any) -> str:
    key = str(value or "").strip().lower().replace(" ", "_")
    key = re.sub(r"[^a-z0-9_-]+", "_", key).strip("_-")
    return key if _CATALOG_KEY_RE.fullmatch(key) else ""


def clean_variant_key(value: Any) -> str:
    return clean_catalog_key(value) or "global"


def clean_execution_mode(value: Any) -> str:
    return EXECUTION_MODE_API if str(value or "").strip().lower() in {"api", "auto", "auto_api", "automatic"} else EXECUTION_MODE_MANUAL


def clean_source_kind(value: Any) -> str:
    kind = str(value or "").strip().lower()
    return kind if kind in {"game", "gift", "product"} else ""


def clean_api_source(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out = dict(value)
    offers = [dict(row) for row in list(out.get("provider_offers") or []) if isinstance(row, dict)]
    if offers:
        out["provider_offers"] = offers[:10]
    elif "provider_offers" in out:
        out["provider_offers"] = []
    return out


def service_section_slug(service_key: str) -> str:
    return _SECTION_SLUG_BY_SERVICE.get(str(service_key or "").strip(), clean_slug(service_key))


def service_accent(service_key: str) -> str:
    return _SECTION_ACCENT_BY_SERVICE.get(str(service_key or "").strip(), "green")


def service_label(service_key: str) -> str:
    key = str(service_key or "").strip()
    row = next((item for item in SECTION_TABLE if str(item.get("key") or "").strip() == key), None)
    label = dict((row or {}).get("label") or {})
    return str(label.get("ar") or label.get("en") or key or "Catalog")


def family_label(service_key: str, family_key: str) -> str:
    service = str(service_key or "").strip()
    family = str(family_key or "").strip()
    for row in FAMILY_TABLE.get(service, ()):
        if str(row.get("key") or "").strip() == family:
            return str(row.get("label") or family)
    return family.replace("_", " ").strip().title()


def is_builtin_family(service_key: str, family_key: str) -> bool:
    service = str(service_key or "").strip()
    family = str(family_key or "").strip()
    return any(str(row.get("key") or "").strip() == family for row in FAMILY_TABLE.get(service, ()))


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


def _node_id(row: dict[str, Any] | None) -> str:
    return str((row or {}).get("_id") or "")


def _parent_id(row: dict[str, Any] | None) -> str:
    return str((row or {}).get("parent_id") or "")


def _by_parent(nodes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for row in nodes:
        by_parent.setdefault(_parent_id(row), []).append(row)
    return by_parent


def _same_variant_name(left: Any, right: Any) -> bool:
    left_key = clean_variant_key(left)
    right_key = clean_variant_key(right)
    if {left_key, right_key} <= {"general", "global"}:
        return True
    return left_key == right_key


def _manual_variant_public_id(row: dict[str, Any]) -> str:
    return f"{_MANUAL_VARIANT_PREFIX}{_node_id(row)}"


def _static_family_nodes(
    nodes: list[dict[str, Any]],
    service_key: str,
    family_key: str,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    service = clean_catalog_key(service_key)
    family = clean_catalog_key(family_key)
    by_parent = _by_parent(nodes)
    sections = [
        row
        for row in nodes
        if node_level(row) == "section"
        and (
            str(row.get("website_section_key") or "").strip() == service
            or (
                not str(row.get("website_section_key") or "").strip()
                and clean_slug(row.get("website_slug")) == service_section_slug(service)
            )
        )
    ]
    section_ids = {_node_id(row) for row in sections}
    families = [
        row
        for section_id in section_ids
        for row in by_parent.get(section_id, [])
        if node_level(row) == "family" and str(row.get("website_family_key") or "").strip() == family
    ]
    return families, by_parent


async def ensure_static_family_path(
    owner_id: int,
    *,
    service_key: str,
    family_key: str,
    family_name: str = "",
    variant_name: str = "Global",
) -> dict[str, dict[str, Any]]:
    catalog_owner_id = int(owner_id or owner_catalog_id())
    service = clean_catalog_key(service_key)
    family = clean_catalog_key(family_key)
    if catalog_owner_id <= 0 or not service or not family:
        raise ValueError("invalid catalog path")

    root = await ensure_root_node(catalog_owner_id, catalog_type=CATALOG_TYPE)
    nodes = await list_catalog_nodes(catalog_owner_id, catalog_type=CATALOG_TYPE)
    by_parent = _by_parent(nodes)
    section = next(
        (
            row
            for row in by_parent.get(_node_id(root), [])
            if node_level(row) == "section" and str(row.get("website_section_key") or "").strip() == service
        ),
        None,
    )
    if not section:
        section = await create_folder(catalog_owner_id, root["_id"], service_label(service), catalog_type=CATALOG_TYPE)
    section = await update_node_website_metadata(
        section["_id"],
        catalog_owner_id,
        website_level="section",
        website_slug=service_section_slug(service),
        website_accent=service_accent(service),
        website_section_key=service,
        catalog_type=CATALOG_TYPE,
    ) or section

    nodes = await list_catalog_nodes(catalog_owner_id, catalog_type=CATALOG_TYPE)
    by_parent = _by_parent(nodes)
    family_node = next(
        (
            row
            for row in by_parent.get(_node_id(section), [])
            if node_level(row) == "family" and str(row.get("website_family_key") or "").strip() == family
        ),
        None,
    )
    if not family_node:
        family_node = await create_folder(catalog_owner_id, section["_id"], family_name or family_label(service, family), catalog_type=CATALOG_TYPE)
    family_node = await update_node_website_metadata(
        family_node["_id"],
        catalog_owner_id,
        website_level="family",
        website_section_key=service,
        website_family_key=family,
        catalog_type=CATALOG_TYPE,
    ) or family_node

    nodes = await list_catalog_nodes(catalog_owner_id, catalog_type=CATALOG_TYPE)
    by_parent = _by_parent(nodes)
    variant_display = " ".join(str(variant_name or "Global").strip().split()) or "Global"
    variant_key = clean_variant_key(variant_display)
    variant = next(
        (
            row
            for row in by_parent.get(_node_id(family_node), [])
            if node_level(row) == "variant"
            and (
                str(row.get("website_variant_key") or "").strip() == variant_key
                or _same_variant_name(row.get("name"), variant_display)
            )
        ),
        None,
    )
    if not variant:
        variant = await create_folder(catalog_owner_id, family_node["_id"], variant_display, catalog_type=CATALOG_TYPE)
    variant = await update_node_website_metadata(
        variant["_id"],
        catalog_owner_id,
        website_level="variant",
        website_section_key=service,
        website_family_key=family,
        website_variant_key=variant_key,
        catalog_type=CATALOG_TYPE,
    ) or variant
    return {"root": root, "section": section, "family": family_node, "variant": variant}


async def create_static_manual_product(
    owner_id: int,
    *,
    service_key: str,
    family_key: str,
    product_name: str,
    price: float,
    input_fields: list[dict[str, Any]],
    family_name: str = "",
    variant_name: str = "Global",
    product_info_text: str = "",
    execution_mode: str = EXECUTION_MODE_MANUAL,
    source_kind: str = "",
    source_key: str = "",
    api_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog_owner_id = int(owner_id or owner_catalog_id())
    name = " ".join(str(product_name or "").strip().split())
    clean_fields = clean_input_fields(input_fields)
    if len(name) < 2 or len(name) > 100:
        raise ValueError("invalid product name")
    if float(price or 0) <= 0:
        raise ValueError("invalid product price")
    if not clean_fields:
        raise ValueError("invalid input fields")
    path = await ensure_static_family_path(
        catalog_owner_id,
        service_key=service_key,
        family_key=family_key,
        family_name=family_name,
        variant_name=variant_name,
    )
    return await _create_static_manual_product_at_variant(
        catalog_owner_id,
        path["variant"],
        service_key=service_key,
        family_key=family_key,
        product_name=name,
        price=price,
        input_fields=clean_fields,
        variant_name=variant_name,
        product_info_text=product_info_text,
        execution_mode=execution_mode,
        source_kind=source_kind,
        source_key=source_key,
        api_source=api_source,
    )


async def _create_static_manual_product_at_variant(
    catalog_owner_id: int,
    variant: dict[str, Any],
    *,
    service_key: str,
    family_key: str,
    product_name: str,
    price: float,
    input_fields: list[dict[str, Any]],
    variant_name: str,
    product_info_text: str,
    execution_mode: str,
    source_kind: str,
    source_key: str,
    api_source: dict[str, Any] | None,
) -> dict[str, Any]:
    product = await create_endpoint(catalog_owner_id, variant["_id"], product_name, float(price), 0, 1, catalog_type=CATALOG_TYPE)
    product = await update_node_website_metadata(
        product["_id"],
        catalog_owner_id,
        website_level="product",
        website_section_key=clean_catalog_key(service_key),
        website_family_key=clean_catalog_key(family_key),
        website_variant_key=clean_variant_key(variant_name),
        website_execution_mode=clean_execution_mode(execution_mode),
        website_source_kind=clean_source_kind(source_kind),
        website_source_key=str(source_key or "").strip(),
        website_api_source=clean_api_source(api_source),
        input_fields=clean_input_fields(input_fields),
        catalog_type=CATALOG_TYPE,
    ) or product
    if product_info_text:
        product = await update_endpoint_product_info(product["_id"], catalog_owner_id, product_info_text, catalog_type=CATALOG_TYPE) or product
    return product


async def upsert_static_manual_product(
    owner_id: int,
    *,
    service_key: str,
    family_key: str,
    product_name: str,
    price: float,
    input_fields: list[dict[str, Any]],
    source_key: str,
    source_kind: str,
    api_source: dict[str, Any] | None = None,
    family_name: str = "",
    variant_name: str = "Global",
    product_info_text: str = "",
    execution_mode: str = EXECUTION_MODE_MANUAL,
    import_cache: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    catalog_owner_id = int(owner_id or owner_catalog_id())
    clean_source = str(source_key or "").strip()
    if not clean_source:
        raise ValueError("invalid source key")
    cache = import_cache if isinstance(import_cache, dict) else None
    path_cache_key = (catalog_owner_id, clean_catalog_key(service_key), clean_catalog_key(family_key), clean_variant_key(variant_name))
    path = (cache or {}).get("paths", {}).get(path_cache_key) if cache is not None else None
    if not path:
        path = await ensure_static_family_path(
            catalog_owner_id,
            service_key=service_key,
            family_key=family_key,
            family_name=family_name,
            variant_name=variant_name,
        )
        if cache is not None:
            cache.setdefault("paths", {})[path_cache_key] = path
    source_products = None
    if cache is not None:
        if "source_products" not in cache:
            nodes = await list_catalog_nodes(catalog_owner_id, catalog_type=CATALOG_TYPE)
            cache["source_products"] = {
                (_parent_id(row), str(row.get("website_source_key") or "").strip()): row
                for row in nodes
                if node_level(row) == "product" and str(row.get("website_source_key") or "").strip()
            }
            cache["source_products_by_key"] = {
                str(row.get("website_source_key") or "").strip(): row
                for row in nodes
                if node_level(row) == "product" and str(row.get("website_source_key") or "").strip()
            }
        source_products = cache["source_products"]
        existing = source_products.get((_node_id(path["variant"]), clean_source))
        if not existing:
            existing = cache.get("source_products_by_key", {}).get(clean_source)
            if existing and _parent_id(existing) != _node_id(path["variant"]):
                moved = await move_node_to_parent(existing["_id"], catalog_owner_id, path["variant"]["_id"], catalog_type=CATALOG_TYPE)
                if moved:
                    source_products.pop((_parent_id(existing), clean_source), None)
                    existing = moved
                    source_products[(_node_id(path["variant"]), clean_source)] = existing
                    cache["source_products_by_key"][clean_source] = existing
    else:
        nodes = await list_catalog_nodes(catalog_owner_id, catalog_type=CATALOG_TYPE)
        existing = next(
            (
                row
                for row in nodes
                if node_level(row) == "product"
                and _parent_id(row) == _node_id(path["variant"])
                and str(row.get("website_source_key") or "").strip() == clean_source
            ),
            None,
        )
    if existing:
        updates: dict[str, Any] = {
            "website_level": "product",
            "website_section_key": clean_catalog_key(service_key),
            "website_family_key": clean_catalog_key(family_key),
            "website_variant_key": clean_variant_key(variant_name),
            "website_source_kind": clean_source_kind(source_kind),
            "website_source_key": clean_source,
            "website_api_source": clean_api_source(api_source),
        }
        if not str(existing.get("website_execution_mode") or "").strip():
            updates["website_execution_mode"] = clean_execution_mode(execution_mode)
        existing = await update_node_website_metadata(
            existing["_id"],
            catalog_owner_id,
            catalog_type=CATALOG_TYPE,
            **updates,
        ) or existing
        return existing, False

    name = " ".join(str(product_name or "").strip().split())
    clean_fields = clean_input_fields(input_fields)
    if len(name) < 2 or len(name) > 100:
        raise ValueError("invalid product name")
    if float(price or 0) <= 0:
        raise ValueError("invalid product price")
    if not clean_fields:
        raise ValueError("invalid input fields")
    product = await _create_static_manual_product_at_variant(
        catalog_owner_id,
        path["variant"],
        service_key=service_key,
        family_key=family_key,
        product_name=name,
        price=price,
        input_fields=clean_fields,
        variant_name=variant_name,
        product_info_text=product_info_text,
        execution_mode=execution_mode,
        source_kind=source_kind,
        source_key=clean_source,
        api_source=api_source,
    )
    if isinstance(source_products, dict):
        source_products[(_node_id(path["variant"]), clean_source)] = product
        if cache is not None:
            cache.setdefault("source_products_by_key", {})[clean_source] = product
    return product, True


async def public_sections(
    owner_id: int | None = None,
    *,
    include_empty: bool = False,
    include_builtin: bool = False,
) -> list[dict[str, Any]]:
    catalog_owner_id = int(owner_id or owner_catalog_id())
    if catalog_owner_id <= 0:
        return []
    nodes = await list_catalog_nodes(catalog_owner_id, catalog_type=CATALOG_TYPE)
    by_parent = _by_parent(nodes)

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
            if product_count <= 0 and not include_empty:
                continue
            family_id = str(family.get("_id") or "")
            service_key = str(family.get("website_section_key") or section.get("website_section_key") or "").strip()
            family_key = str(family.get("website_family_key") or "").strip()
            if not include_builtin and service_key and family_key and is_builtin_family(service_key, family_key):
                continue
            categories.append(
                {
                    "slug": family_key or f"manual-{family_id}",
                    "title": str(family.get("name") or ""),
                    "subtitle": str(family.get("display_text") or f"{product_count} منتجات تنفيذ يدوي."),
                    "search_terms": str(family.get("name") or ""),
                    "generated": True,
                    "service_key": service_key or CATALOG_TYPE,
                    "family_key": family_key or family_id,
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


async def static_family_packages(
    service_key: str,
    family_key: str,
    *,
    variant_id: str = "",
    variant_name: str = "",
    owner_id: int | None = None,
) -> dict[str, Any] | None:
    catalog_owner_id = int(owner_id or owner_catalog_id())
    if catalog_owner_id <= 0:
        return None
    service = clean_catalog_key(service_key)
    family_key_clean = clean_catalog_key(family_key)
    if not service or not family_key_clean:
        return None
    nodes = await list_catalog_nodes(catalog_owner_id, catalog_type=CATALOG_TYPE)
    families, by_parent = _static_family_nodes(nodes, service, family_key_clean)
    if not families:
        return None

    variants: list[dict[str, Any]] = []
    for family in families:
        variants.extend(row for row in by_parent.get(_node_id(family), []) if node_level(row) == "variant")
    variants.sort(key=lambda row: (0 if clean_variant_key(row.get("name")) == "global" else 1, str(row.get("name") or "").lower()))
    public_variants = [
        {
            "id": _manual_variant_public_id(row),
            "name": str(row.get("name") or "Global"),
            "variant_kind": "region",
            "entry_kind": "manual",
            "image_url": "",
            "manual": True,
        }
        for row in variants
    ]

    selected_rows: list[dict[str, Any]] = []
    requested_variant = str(variant_id or "").strip()
    if requested_variant:
        raw_id = requested_variant[len(_MANUAL_VARIANT_PREFIX):] if requested_variant.startswith(_MANUAL_VARIANT_PREFIX) else requested_variant
        selected_rows = [
            row
            for row in variants
            if _node_id(row) == raw_id or str(row.get("website_variant_key") or "").strip() == raw_id
        ]
        if not selected_rows:
            return {"variant_not_found": True}
    elif str(variant_name or "").strip():
        selected_rows = [row for row in variants if _same_variant_name(row.get("name"), variant_name)]
    elif len(variants) == 1:
        selected_rows = [variants[0]]

    family_name = str((families[0] or {}).get("name") or family_label(service, family_key_clean))
    payload = {
        "ok": True,
        "service_key": service,
        "family_key": family_key_clean,
        "family_name": family_name,
        "selection_kind": "general" if len(variants) <= 1 else "region",
        "requires_variant_selection": len(variants) > 1 and not selected_rows,
        "variants": public_variants,
        "selected_variant_id": _manual_variant_public_id(selected_rows[0]) if len(selected_rows) == 1 else "",
        "selected_variant_name": str((selected_rows[0] if len(selected_rows) == 1 else {}).get("name") or ""),
        "packages": [],
    }
    if not selected_rows:
        return payload

    products = [
        row
        for variant in selected_rows
        for row in by_parent.get(_node_id(variant), [])
        if node_level(row) == "product" and float(row.get("price") or 0) > 0
    ]
    variant_by_id = {_node_id(row): row for row in selected_rows}
    family_by_id = {_node_id(row): row for row in families}
    out = []
    for product in products:
        variant = variant_by_id.get(_parent_id(product)) or selected_rows[0]
        family = family_by_id.get(_parent_id(variant)) or families[0]
        out.append(public_product(product, family=family, variant=variant))
    payload["packages"] = out
    return payload


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
    api_source = clean_api_source(row.get("website_api_source"))
    source_kind = clean_source_kind(row.get("website_source_kind"))
    api_supported = bool(api_source) and source_kind == "game"
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
        "execution_mode": clean_execution_mode(row.get("website_execution_mode")),
        "api_source_available": bool(api_source),
        "api_execution_supported": api_supported,
        "source_kind": source_kind,
        "source_key": str(row.get("website_source_key") or ""),
        "manual_catalog": {
            "family_name": str(family.get("name") or ""),
            "variant_name": str(variant.get("name") or ""),
        },
    }


def _manual_provider_offer(endpoint: dict[str, Any], family: dict[str, Any], *, price: float) -> dict[str, Any]:
    endpoint_ref = str(endpoint.get("_id") or "")
    return {
        "provider": "manual_catalog",
        "ref_id": endpoint_ref,
        "price": price,
        "available": True,
        "fulfillment_mode": "manual_topup",
        "source_product_name": str(family.get("name") or ""),
        "source_denomination_name": str(endpoint.get("name") or ""),
    }


def _api_provider_offers(endpoint: dict[str, Any], *, price: float) -> list[dict[str, Any]]:
    source = clean_api_source(endpoint.get("website_api_source"))
    offers = [dict(row) for row in list(source.get("provider_offers") or []) if isinstance(row, dict)]
    out: list[dict[str, Any]] = []
    for offer in offers[:10]:
        provider = str(offer.get("provider") or source.get("provider") or "").strip().lower()
        ref_id = str(offer.get("ref_id") or offer.get("provider_ref_id") or source.get("provider_ref_id") or source.get("item_id") or "").strip()
        if not provider or not ref_id:
            continue
        row = dict(offer)
        row["provider"] = provider
        row["ref_id"] = ref_id
        row["available"] = bool(row.get("available", True))
        row["price"] = float(row.get("price") or source.get("source_price_usd") or price)
        row["fulfillment_mode"] = str(row.get("fulfillment_mode") or "auto_topup").strip() or "auto_topup"
        row.setdefault("source_product_name", str(source.get("game_name") or source.get("product_name") or ""))
        row.setdefault("source_denomination_name", str(endpoint.get("name") or source.get("item_name") or ""))
        out.append(row)
    return out


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
    execution_mode = clean_execution_mode(endpoint.get("website_execution_mode"))
    source_kind = clean_source_kind(endpoint.get("website_source_kind"))
    api_source = clean_api_source(endpoint.get("website_api_source"))
    api_supported = bool(api_source) and source_kind == "game"
    api_offers = _api_provider_offers(endpoint, price=price) if api_supported else []
    manual_offer = _manual_provider_offer(endpoint, family, price=price)
    provider_offers = (api_offers + [manual_offer]) if execution_mode == EXECUTION_MODE_API and api_offers else ([manual_offer] + api_offers)
    selected_offer = provider_offers[0]
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
        "provider": str(selected_offer.get("provider") or "manual_catalog"),
        "provider_ref_id": str(selected_offer.get("ref_id") or endpoint_ref),
        "provider_offers": provider_offers,
        "execution_mode": execution_mode,
        "api_source_available": bool(api_source),
        "api_execution_supported": api_supported,
        "source_kind": source_kind,
        "source_key": str(endpoint.get("website_source_key") or ""),
        "game_id": str(api_source.get("game_id") or "") if api_supported else "",
        "game_name": str(api_source.get("game_name") or family.get("name") or "") if api_supported else "",
        "requires_server": bool(api_source.get("requires_server")) if api_supported else False,
        "api_player_field": str(api_source.get("player_field") or "player_id"),
        "api_server_field": str(api_source.get("server_field") or "server_id"),
    }
