from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from database.digital_catalog_staging_repo import staging_status_counts, upsert_staging_items
from services.digital_products.catalog_sources import CatalogOffer, enabled_catalog_sources
from services.digital_products.fulfillment_rules import offer_region_label

logger = logging.getLogger("catalog_staging")

# Rule 1: keep only these regions (USA + Europe + Global). Everything else is
# imported but flagged `dropped` so the admin can still see what was filtered.
ALLOWED_REGIONS = {"global", "usa", "uk", "eu", ""}

# Families whose vouchers at the same source are cheaper than the API top-up,
# so their orders go the voucher/manual route instead of smart auto-routing.
VOUCHER_FIRST_FAMILIES = {"pubg", "free_fire"}


def _round2(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _effective_region(offer: CatalogOffer) -> str:
    """Resolve the region for the rule-1 filter.

    The compare_key region can wrongly default to 'global' when the upstream
    game_id carries no region suffix. The package name is a second signal: if it
    names a region (e.g. 'Free Fire Diamonds LATAM'), prefer that so a regional
    product cannot leak through as global.
    """
    name_region = str(offer_region_label(offer.package_name, default="") or "").strip().lower()
    key_region = str(offer.region or "").strip().lower()
    return name_region or key_region or "global"


def _has_game_source(item: dict[str, Any]) -> bool:
    return any(str(o.get("source_key") or "").startswith("game:") for o in item.get("provider_offers") or [])


def _offer_brief(offer: CatalogOffer) -> dict[str, Any]:
    return {
        "provider": offer.provider,
        "ref_id": offer.ref_id,
        "source_key": offer.source_key,
        "price_usd": _round2(offer.price_usd),
        "requires_server": bool(offer.requires_server),
    }


def build_staging_items(offers: list[CatalogOffer], *, margin_factor: float = 1.0) -> tuple[list[dict[str, Any]], int]:
    """Apply the catalog rules to raw offers and return (staged_items, dropped_count).

    Rules: region filter (1), dedup/merge by compare_key (4), default execution
    policy = api (5). Family/service reclassification (2) and sub-type split (3)
    are already carried on each offer by the source layer.

    `margin_factor` (1 + markup%/100) turns the cheapest provider **cost** into the
    suggested **selling** price. The raw cost is kept in `cost_price_usd` so the
    no-loss guard / provider lanes still compare against the true cost.
    """
    factor = float(margin_factor) if margin_factor and margin_factor > 0 else 1.0
    staged: dict[str, dict[str, Any]] = {}
    dropped = 0
    for offer in offers:
        staging_key = (offer.compare_key or "").strip() or (offer.source_key or "").strip()
        if not staging_key:
            continue
        region = _effective_region(offer)
        brief = _offer_brief(offer)
        item = staged.get(staging_key)
        if item is None:
            region_ok = region in ALLOWED_REGIONS
            if not region_ok:
                dropped += 1
            cost = _round2(offer.price_usd)
            staged[staging_key] = {
                "staging_key": staging_key,
                "compare_key": offer.compare_key,
                "service_key": offer.service_key,
                "family_key": offer.family_key,
                "family_name": offer.family_name,
                "sub_category": offer.sub_category,
                "source_kind": "game" if offer.service_key == "games" else "gift",
                "region": region or "global",
                "unit_kind": offer.unit_kind,
                "package_name": offer.package_name,
                "source_key": offer.source_key,
                "provider_offers": [brief],
                "cost_price_usd": cost,
                "suggested_price_usd": _round2(cost * factor),
                "execution_policy": "api",
                "input_fields": list(offer.input_fields or []),
                "requires_server": bool(offer.requires_server),
                "status": "new" if region_ok else "dropped",
                "drop_reason": "" if region_ok else f"region_{region or 'unknown'}",
            }
            continue
        # Merge another provider's offer for the same package (rule 4 dedup).
        if not any(o["provider"] == brief["provider"] and o["ref_id"] == brief["ref_id"] for o in item["provider_offers"]):
            item["provider_offers"].append(brief)
        if _round2(offer.price_usd) < _round2(item.get("cost_price_usd") or item["suggested_price_usd"]):
            item["cost_price_usd"] = _round2(offer.price_usd)
            item["suggested_price_usd"] = _round2(_round2(offer.price_usd) * factor)
            item["source_key"] = offer.source_key
            item["requires_server"] = bool(offer.requires_server)
            item["input_fields"] = list(offer.input_fields or [])

    # Smart routing needs a G2Bulk game_id; items with no game source (Mangerr-only
    # games, or gift/voucher products) can't auto-route, so default them to manual
    # instead of silently labelling them "api" and sending every order to review.
    for item in staged.values():
        if not _has_game_source(item) or str(item.get("family_key") or "") in VOUCHER_FIRST_FAMILIES:
            item["execution_policy"] = "manual"
    return list(staged.values()), dropped


def staged_api_source(item: dict[str, Any]) -> dict[str, Any]:
    """Build the `website_api_source` dict for a live product from a staged item.

    Pulls `game_id` from a G2Bulk offer (smart routing's G2Bulk lane needs it),
    keeps `compare_key` as the cross-provider identity, and lists every merged
    provider offer so the live product advertises all execution options.
    """
    offers = list(item.get("provider_offers") or [])
    game_id = ""
    item_ref = ""
    for offer in offers:
        source_key = str(offer.get("source_key") or "")
        if source_key.startswith("game:"):
            parts = source_key.split(":")
            game_id = parts[1] if len(parts) > 1 else ""
            item_ref = parts[2] if len(parts) > 2 else ""
            break
    primary = min(offers, key=lambda o: float(o.get("price_usd") or 0.0)) if offers else {}
    compare_key = str(item.get("compare_key") or "")
    return {
        "kind": str(item.get("source_kind") or "game"),
        "game_id": game_id,
        "game_name": str(item.get("family_name") or ""),
        "item_id": item_ref or str(primary.get("ref_id") or ""),
        "compare_key": compare_key,
        "provider": str(primary.get("provider") or "g2bulk"),
        "provider_ref_id": str(primary.get("ref_id") or ""),
        "requires_server": bool(item.get("requires_server")),
        "player_field": "player_id",
        "server_field": "server_id",
        "variant_name": str(item.get("sub_category") or "Global"),
        "source_price_usd": _round2(item.get("cost_price_usd") if item.get("cost_price_usd") is not None else item.get("suggested_price_usd")),
        "provider_offers": [
            {
                "provider": str(offer.get("provider") or ""),
                "ref_id": str(offer.get("ref_id") or ""),
                "price": _round2(offer.get("price_usd")),
                "available": True,
                "fulfillment_mode": "auto_topup",
                "compare_key": compare_key,
            }
            for offer in offers
        ],
    }


def staged_product_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Map a staged item to `upsert_static_manual_product` kwargs for going live."""
    api_source = staged_api_source(item)
    execution_mode = "api" if str(item.get("execution_policy") or "api").strip().lower() == "api" else "manual"
    # Smart routing is impossible without a game_id; never ship such a product as "api".
    if execution_mode == "api" and not str(api_source.get("game_id") or "").strip():
        execution_mode = "manual"
    return {
        "service_key": str(item.get("service_key") or "games"),
        "family_key": str(item.get("family_key") or ""),
        "family_name": str(item.get("family_name") or ""),
        "variant_name": str(item.get("sub_category") or "Global"),
        "product_name": str(item.get("package_name") or ""),
        "price": _round2(item.get("suggested_price_usd")),
        "input_fields": list(item.get("input_fields") or []),
        "source_key": str(item.get("source_key") or ""),
        "source_kind": str(item.get("source_kind") or "game"),
        "api_source": api_source,
        "execution_mode": execution_mode,
        "product_info_text": "",
    }


async def run_staging_import(owner_id: int, *, sources: list[Any] | None = None) -> dict[str, Any]:
    """Pull every enabled provider catalog, apply rules, and write to staging.

    Idempotent and live-safe: writes only to `digital_catalog_staging`, never to
    the live `website_manual` catalog. A failing provider is isolated.
    """
    active_sources = sources if sources is not None else enabled_catalog_sources()
    run_id = uuid4().hex
    by_provider: dict[str, Any] = {}
    all_offers: list[CatalogOffer] = []
    for source in active_sources:
        code = getattr(source, "provider_code", "unknown")
        try:
            fetched = await source.fetch_offers()
        except Exception as exc:  # one provider down must not abort the run
            logger.warning("catalog source %s failed: %s", code, exc)
            by_provider[code] = {"ok": False, "offers": 0, "error": str(exc)[:200]}
            continue
        by_provider[code] = {"ok": True, "offers": len(fetched)}
        all_offers.extend(fetched)

    try:
        from database.digital_products_config_repo import get_digital_products_markup_percent

        markup_pct = float(await get_digital_products_markup_percent())
    except Exception:
        markup_pct = 0.0
    margin_factor = 1.0 + max(0.0, markup_pct) / 100.0
    items, dropped = build_staging_items(all_offers, margin_factor=margin_factor)
    upsert = await upsert_staging_items(owner_id, run_id, items)
    counts = await staging_status_counts(owner_id)
    return {
        "ok": True,
        "run_id": run_id,
        "by_provider": by_provider,
        "fetched": len(all_offers),
        "staged": len(items),
        "dropped_region": dropped,
        "upsert": upsert,
        "status_counts": counts,
    }
