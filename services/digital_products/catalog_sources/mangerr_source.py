from __future__ import annotations

import logging
import re
from typing import Any

from services.digital_products.catalog_sources.base import CatalogOffer, parse_compare_key
from services.digital_products.mangerr_client import MangerrClient

logger = logging.getLogger("catalog_sources.mangerr")


class MangerrCatalogSource:
    """Normalizes Mangerr's product list into CatalogOffers.

    Mangerr is resilient by contract: if it is not configured or returns a
    non-200 (e.g. Cloudflare 526), this yields an empty list so sibling sources
    still import. Smart routing also re-checks Mangerr live at order time, so a
    Mangerr-only catalog gap here is recoverable.
    """

    provider_code = "mangerr"

    async def fetch_offers(self) -> list[CatalogOffer]:
        client = MangerrClient()
        if not client.configured():
            logger.info("mangerr catalog source skipped: not configured")
            return []
        status, payload = await client.get_products_response()
        if status != 200 or not isinstance(payload, list):
            logger.warning("mangerr catalog source unavailable status=%s", status)
            return []

        # Imported lazily to avoid heavy/circular imports at module load.
        from services.digital_products.catalog_service import _product_compare_key
        from services.digital_products.miniapp import _gift_service_key, _markup_percent, _round_sale_price

        markup = await _markup_percent()
        offers: list[CatalogOffer] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            offer = _mangerr_offer(item, markup, _product_compare_key, _gift_service_key, _round_sale_price)
            if offer:
                offers.append(offer)
        logger.info("mangerr catalog source produced %d offers", len(offers))
        return offers


def _mangerr_offer(item: dict[str, Any], markup: float, compare_key_fn, service_fn, round_fn) -> CatalogOffer | None:
    if not bool(item.get("available", True)):
        return None
    ref_id = str(item.get("id") or "").strip()
    cost = float(item.get("price") or 0.0)
    name = str(item.get("name") or "").strip()
    category_name = str(item.get("category_name") or "").strip()
    if not ref_id or cost <= 0 or not name:
        return None

    compare_key = str(compare_key_fn(category_name=category_name, product_name=name) or "").strip()
    family_key, region, _amount, unit = parse_compare_key(compare_key)
    service_key = str(service_fn(f"{name} {category_name}") or "games").strip() or "games"
    sale_price = float(round_fn(cost * (1.0 + float(markup or 0.0) / 100.0)))
    if sale_price <= 0:
        return None

    params = [str(value).strip() for value in list(item.get("params") or []) if str(value).strip()]
    input_fields = _fields_from_params(params)
    requires_server = any("server" in param.lower() for param in params)

    return CatalogOffer(
        provider="mangerr",
        ref_id=ref_id,
        source_key=f"mangerr:{ref_id}",
        service_key=service_key,
        family_key=family_key or "",
        family_name=category_name or family_key or name,
        sub_category="topup",
        region=region or "global",
        compare_key=compare_key,
        unit_kind=unit,
        package_name=name,
        price_usd=sale_price,
        requires_server=requires_server,
        input_fields=input_fields,
        raw=dict(item),
    )


def _fields_from_params(params: list[str]) -> list[dict[str, Any]]:
    if not params:
        return [{"id": "player_id", "label": "Player ID", "required": True, "type": "text"}]
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for param in params[:8]:
        field_id = re.sub(r"[^a-z0-9_]+", "_", param.strip().lower()).strip("_")[:40] or "details"
        if field_id in seen:
            continue
        seen.add(field_id)
        fields.append({"id": field_id, "label": param.replace("_", " ").title(), "required": True, "type": "text"})
    return fields
