"""Central pricing engine for the website wholesale-reseller tier system.

Everything here is PURE (no DB, no I/O) so it's trivially testable and the single
source of truth for how a price is formed. Callers pass the product cost, the
section, and (for a reseller) the current tier; they get back a rounded USD price.

Design (agreed with Homam 2026-07-04):
  - Margins are always applied over the COST (provider/base price), never over retail.
  - Retail (normal customer) margin is fixed per section; the reseller margin
    shrinks as the reseller's monthly purchase volume climbs the tiers.
  - Tiers by monthly PURCHASE volume: bronze $1-500, silver $500-1000,
    gold $1000-2000, platinum $2000+.
  - Games + store cards: cost * (1 + margin).  numbers: 20% for everyone (no
    reseller discount).  topup/charging lines: admin sets retail directly and the
    reseller gets a flat discount off it.  esim: cost + margin like games, own value.

Nothing here is wired into the live catalog yet — this is the foundation the later
phases build on.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# Ordered worst -> best. "none" means a normal (non-reseller) customer.
TIERS: tuple[str, ...] = ("bronze", "silver", "gold", "platinum")

# Sections priced as cost * (1 + margin). Everything else has bespoke handling.
COST_MARGIN_SECTIONS: frozenset[str] = frozenset({"games", "store_cards", "esim"})


def _round2(value: float) -> float:
    try:
        return round(float(value or 0.0) + 1e-9, 2)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class PricingConfig:
    """All the editable knobs. Defaults match the agreed numbers; the admin config
    surface (later phase) overrides these from system_settings."""

    # Reseller margin % over cost, per tier (games/store_cards/esim).
    tier_margins: dict[str, float] = field(
        default_factory=lambda: {"bronze": 5.0, "silver": 4.0, "gold": 3.0, "platinum": 2.5}
    )
    # Lower bound (inclusive) of monthly purchase USD for each tier.
    tier_thresholds: dict[str, float] = field(
        default_factory=lambda: {"bronze": 0.0, "silver": 500.0, "gold": 1000.0, "platinum": 2000.0}
    )
    # Normal-customer margin % over cost, per section.
    retail_margins: dict[str, float] = field(
        default_factory=lambda: {"games": 7.0, "store_cards": 7.0, "esim": 15.0, "numbers": 20.0}
    )
    # Flat USD the reseller saves on charging-lines/topup (retail - this).
    topup_reseller_discount_usd: float = 1.5

    def with_overrides(self, **overrides: object) -> "PricingConfig":
        clean = {key: value for key, value in overrides.items() if value is not None}
        return replace(self, **clean) if clean else self


DEFAULT_CONFIG = PricingConfig()


def tier_for_monthly_sales(total_usd: float, cfg: PricingConfig = DEFAULT_CONFIG) -> str:
    """The tier a reseller earns for a given monthly purchase volume (>= $1 = bronze)."""
    total = max(0.0, float(total_usd or 0.0))
    earned = "bronze"
    for tier in TIERS:
        if total >= float(cfg.tier_thresholds.get(tier, 0.0)):
            earned = tier
    return earned


def retail_price(cost: float, section: str, cfg: PricingConfig = DEFAULT_CONFIG) -> float:
    """Price a normal (non-reseller) customer pays, for a cost-based section."""
    margin = float(cfg.retail_margins.get(section, 0.0))
    return _round2(float(cost or 0.0) * (1.0 + margin / 100.0))


def wholesale_price(
    section: str,
    tier: str,
    *,
    cost: float = 0.0,
    retail: float = 0.0,
    cfg: PricingConfig = DEFAULT_CONFIG,
) -> float:
    """Price a reseller of `tier` pays.

    - games/store_cards/esim: cost * (1 + tier_margin)
    - numbers: no reseller discount -> same as retail (20% over cost)
    - topup/charging lines: retail (admin-set) minus the flat reseller discount
    """
    tier = tier if tier in TIERS else "bronze"
    if section in COST_MARGIN_SECTIONS:
        margin = float(cfg.tier_margins.get(tier, cfg.tier_margins["bronze"]))
        return _round2(float(cost or 0.0) * (1.0 + margin / 100.0))
    if section == "numbers":
        # Numbers are always 20% for everyone; the reseller gets no discount.
        return retail_price(cost, "numbers", cfg) if cost else _round2(retail)
    # topup / charging lines and anything else priced manually.
    discounted = float(retail or 0.0) - float(cfg.topup_reseller_discount_usd or 0.0)
    return _round2(max(0.0, discounted))


def wholesale_from_retail(
    section: str,
    tier: str,
    retail: float,
    cfg: PricingConfig = DEFAULT_CONFIG,
) -> float:
    """Reseller price derived from the stored RETAIL price (what's on the catalog
    node) — no separate cost field needed. For a cost-margin section this is exact:
    retail = cost*(1+retail_margin), so retail*(1+tier)/(1+retail_margin) = cost*(1+tier).

    - games/store_cards/esim: retail * (1 + tier_margin) / (1 + retail_margin)
    - topup: retail - flat discount
    - numbers / unknown sections: retail unchanged (reseller gets no discount)
    """
    tier = tier if tier in TIERS else "bronze"
    retail = float(retail or 0.0)
    if section in COST_MARGIN_SECTIONS:
        tier_m = float(cfg.tier_margins.get(tier, cfg.tier_margins["bronze"]))
        retail_m = float(cfg.retail_margins.get(section, 0.0))
        return _round2(retail * (1.0 + tier_m / 100.0) / (1.0 + retail_m / 100.0))
    if section == "topup":
        return _round2(max(0.0, retail - float(cfg.topup_reseller_discount_usd or 0.0)))
    return _round2(retail)  # numbers + unspecified sections: no reseller discount


def price_for_viewer(
    section: str,
    *,
    tier: str | None = None,
    cost: float = 0.0,
    retail: float = 0.0,
    cfg: PricingConfig = DEFAULT_CONFIG,
) -> float:
    """Single entry point. `tier=None` -> normal customer; a tier name -> reseller."""
    if not tier:
        if section in COST_MARGIN_SECTIONS or section == "numbers":
            return retail_price(cost, section, cfg)
        return _round2(retail)  # topup: admin-set retail as-is
    return wholesale_price(section, tier, cost=cost, retail=retail, cfg=cfg)


def tier_index(tier: str) -> int:
    return TIERS.index(tier) if tier in TIERS else -1


def review_tier(
    current_tier: str,
    monthly_sales: float,
    miss_streak: int,
    cfg: PricingConfig = DEFAULT_CONFIG,
) -> tuple[str, int, bool]:
    """Monthly tier review. Given a reseller's current tier, their COMPLETED-month
    purchase volume, and their consecutive-miss streak, return
    (new_tier, new_miss_streak, changed).

    - Meeting a tier's threshold promotes/keeps them at the earned tier and resets
      the streak (hitting the target = full protection).
    - Falling below the current tier's threshold is a "miss": the first is
      forgiven (protection), a second consecutive miss demotes ONE level
      (floor = bronze — a reseller never drops out) and resets the streak.
    """
    cur = tier_index(current_tier)
    if cur < 0:
        cur = 0
    earned = tier_index(tier_for_monthly_sales(monthly_sales, cfg))
    if earned >= cur:
        return TIERS[earned], 0, earned != cur
    streak = int(miss_streak or 0) + 1
    if streak >= 2:
        demoted = max(0, cur - 1)
        return TIERS[demoted], 0, True
    return TIERS[cur], streak, False


def reseller_discount_labels(cfg: PricingConfig = DEFAULT_CONFIG) -> dict[str, float]:
    """Motivational "discount %" shown to the reseller per tier — the margin-point
    difference from bronze (bronze = 0). Hides the real margins; never expose the
    absolute tier margins to resellers."""
    base = float(cfg.tier_margins.get("bronze", 0.0))
    return {tier: _round2(base - float(cfg.tier_margins.get(tier, base))) for tier in TIERS}
