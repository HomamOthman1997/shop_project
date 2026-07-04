"""Persistence for the reseller/pricing config (the editable knobs of
services.digital_products.reseller_pricing). One system_settings doc; the admin
config surface (later phase) reads/writes it. Falls back to code defaults so the
engine works before anything is ever saved."""

from __future__ import annotations

from datetime import UTC, datetime

from database.mongo import db
from services.digital_products.reseller_pricing import DEFAULT_CONFIG, TIERS, PricingConfig

_DOC_ID = "reseller_pricing_settings"


def _clean_percent(value: object, fallback: float) -> float:
    try:
        return max(0.0, min(500.0, float(value)))
    except (TypeError, ValueError):
        return float(fallback)


def _clean_usd(value: object, fallback: float) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return float(fallback)


def _merge_percent_map(saved: object, defaults: dict[str, float]) -> dict[str, float]:
    saved = saved if isinstance(saved, dict) else {}
    return {key: _clean_percent(saved.get(key), default) for key, default in defaults.items()}


async def get_pricing_config() -> PricingConfig:
    doc = await db.system_settings.find_one({"_id": _DOC_ID}) or {}
    return PricingConfig(
        tier_margins=_merge_percent_map(doc.get("tier_margins"), DEFAULT_CONFIG.tier_margins),
        tier_thresholds={
            tier: _clean_usd((doc.get("tier_thresholds") or {}).get(tier), DEFAULT_CONFIG.tier_thresholds[tier])
            for tier in TIERS
        },
        retail_margins=_merge_percent_map(doc.get("retail_margins"), DEFAULT_CONFIG.retail_margins),
        topup_reseller_discount_usd=_clean_usd(
            doc.get("topup_reseller_discount_usd"), DEFAULT_CONFIG.topup_reseller_discount_usd
        ),
    )


async def save_pricing_config(cfg: PricingConfig) -> None:
    await db.system_settings.update_one(
        {"_id": _DOC_ID},
        {
            "$set": {
                "tier_margins": dict(cfg.tier_margins),
                "tier_thresholds": dict(cfg.tier_thresholds),
                "retail_margins": dict(cfg.retail_margins),
                "topup_reseller_discount_usd": float(cfg.topup_reseller_discount_usd),
                "updated_at": datetime.now(UTC),
            }
        },
        upsert=True,
    )
