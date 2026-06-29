from __future__ import annotations

import logging
from typing import Any

from services.digital_products.catalog_sources.base import CatalogOffer, parse_compare_key

logger = logging.getLogger("catalog_sources.g2bulk")


class G2BulkCatalogSource:
    """Normalizes the existing G2Bulk-backed catalog tree into CatalogOffers.

    Reuses the miniapp catalog helpers (family grouping, region detection,
    compare_key, topup/passes/specials sub-typing) rather than re-deriving them,
    so staging stays consistent with the live import path.
    """

    provider_code = "g2bulk"

    async def fetch_offers(self) -> list[CatalogOffer]:
        # Imported lazily: miniapp is a heavy module and this avoids import cycles.
        from services.digital_products.miniapp import (
            _catalog_payload,
            _game_import_fields,
            _game_items,
            _gift_import_fields,
            _gift_products,
            _import_item_price,
            _import_variant_name,
        )

        payload = await _catalog_payload()
        offers: list[CatalogOffer] = []
        seen_games: set[str] = set()
        seen_gifts: set[str] = set()

        for service in list(payload.get("service_tree") or []):
            service_key = str(service.get("key") or "").strip()
            for family in list(service.get("families") or []):
                family_key = str(family.get("family_key") or "").strip()
                family_name = str(family.get("name") or family_key)
                for variant in list(family.get("variants") or []):
                    default_variant = str(variant.get("name") or "Global").strip() or "Global"

                    for game_id in list(variant.get("game_ids") or []):
                        gid = str(game_id).strip()
                        if not gid or gid in seen_games:
                            continue
                        seen_games.add(gid)
                        try:
                            data = await _game_items(gid)
                        except Exception as exc:  # one game failing must not abort the import
                            logger.warning("g2bulk game_items failed game=%s err=%s", gid, exc)
                            continue
                        for item in list(data.get("items") or []):
                            offer = _game_offer(item, service_key, family_key, family_name, _game_import_fields)
                            if offer:
                                offers.append(offer)

                    for category_id in list(variant.get("gift_category_ids") or []):
                        cid = str(category_id).strip()
                        if not cid or cid in seen_gifts:
                            continue
                        seen_gifts.add(cid)
                        try:
                            items = await _gift_products(cid, "", str(variant.get("offer_mode") or "all"))
                        except Exception as exc:
                            logger.warning("g2bulk gift_products failed cat=%s err=%s", cid, exc)
                            continue
                        for item in list(items or []):
                            offer = _gift_offer(
                                item,
                                service_key,
                                family_key,
                                family_name,
                                default_variant,
                                _gift_import_fields,
                                _import_item_price,
                                _import_variant_name,
                            )
                            if offer:
                                offers.append(offer)

        logger.info("g2bulk catalog source produced %d offers", len(offers))
        return offers


def _game_offer(item: dict[str, Any], service_key: str, family_key: str, family_name: str, fields_fn) -> CatalogOffer | None:
    item_id = str(item.get("id") or "").strip()
    game_id = str(item.get("game_id") or "").strip()
    price = float(item.get("price_usd") or 0.0)
    if not item_id or not game_id or price <= 0:
        return None
    compare_key = str(item.get("compare_key") or "").strip()
    _fam, region, _amount, unit = parse_compare_key(compare_key)
    return CatalogOffer(
        provider="g2bulk",
        ref_id=item_id,
        source_key=f"game:{game_id}:{item_id}",
        service_key=service_key,
        family_key=family_key,
        family_name=family_name,
        sub_category=str(item.get("group_key") or "topup").strip() or "topup",
        region=region or "global",
        compare_key=compare_key,
        unit_kind=unit,
        package_name=str(item.get("name") or item_id),
        price_usd=price,
        requires_server=bool(item.get("requires_server")),
        input_fields=fields_fn(item),
        raw=dict(item),
    )


def _gift_offer(
    item: dict[str, Any],
    service_key: str,
    family_key: str,
    family_name: str,
    default_variant: str,
    fields_fn,
    price_fn,
    variant_fn,
) -> CatalogOffer | None:
    item_id = str(item.get("id") or "").strip()
    price = float(price_fn(item) or 0.0)
    if not item_id or price <= 0:
        return None
    category_id = str(item.get("category_id") or "").strip()
    category_name = str(item.get("category_name") or "").strip()
    package_name = str(item.get("name") or item_id)
    compare_key = str(item.get("compare_key") or "").strip()
    _fam, region, _amount, unit = parse_compare_key(compare_key)
    if str(service_key) == "games":
        # A game-currency voucher (e.g. PUBG UC voucher) is just the *future* route of
        # the same product the auto top-up serves — the route is a backend/smart-routing
        # detail (merged via compare_key), never a customer-facing category. So it joins
        # the game's "topup" bucket (matching _game_offer's default) instead of a region
        # bucket, so the customer sees the currency once — not split across topup/Global.
        sub_category = str(item.get("group_key") or "topup").strip() or "topup"
    else:
        # Real gift cards (Steam/Razer/…) — region is the meaningful axis.
        sub_category = variant_fn(
            service_key=service_key,
            family_key=family_key,
            family_name=family_name,
            default_variant_name=default_variant,
            source_id=f"{category_id} {item_id}",
            source_text=category_name,
            item_name=package_name,
        )
    return CatalogOffer(
        provider="g2bulk",
        ref_id=item_id,
        source_key=f"gift:{category_id}:{item_id}",
        service_key=service_key,
        family_key=family_key,
        family_name=family_name,
        sub_category=str(sub_category or "General").strip() or "General",
        region=region or "global",
        compare_key=compare_key,
        unit_kind=unit,
        package_name=package_name,
        price_usd=price,
        requires_server=False,
        input_fields=fields_fn(item),
        raw=dict(item),
    )
