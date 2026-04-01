# Wishlist (Deferred / Not Near-Term)

Last updated: 2026-03-24
Status policy: ideas below are intentionally deferred and will not be implemented in the near term.

## Deferred Proxy Product Ideas

- [ ] Hourly fairness scheduler with queue ownership per lock key.
Status: Deferred (not near-term).

- [ ] Lock key by `(provider, location, target_site)` to enforce fairness for same-site demand (example: `livepoint`).
Status: Deferred (not near-term).

- [ ] Customer session extension flow:
10-minute warning before hour end + "I am inside survey" button + effective 10-minute extra runtime (20 minutes from warning point total).
Status: Deferred (not near-term).

- [ ] Disallow user-triggered IP changes; only bot-controlled rotation at cycle boundaries.
Status: Deferred (not near-term).

- [ ] Mandatory start-of-cycle health gate before delivery (speed/connectivity/reputation checks).
Status: Deferred (not near-term).

- [ ] Password rotation at handover to revoke previous holder access.
Status: Deferred (not near-term).

- [ ] State locking per cycle and optional state voting/selection logic.
Status: Deferred (not near-term).

- [ ] Shared-modem scheduling policy for multi-user usage with site isolation rules.
Status: Deferred (not near-term).

- [ ] Pay-as-you-go with deposit hold and no-show penalty policy engine.
Status: Deferred (not near-term).

- [ ] Dynamic penalty tiers (25% then 50%) and anti-abuse controls.
Status: Deferred (not near-term).

- [ ] Full package/bundle pricing engine (hour/day/week/month plans) for proxy service.
Status: Deferred (not near-term).

- [ ] Auto-optimizer based on location load percentage in API responses.
Status: Deferred (not near-term) because current public API does not expose reliable load metrics endpoint.

## Current Near-Term Direction (Intentional Scope)

- Keep proxy launch simple:
single short-duration offer, minimal UX complexity, and operational stability first.

- Defer advanced scheduling/fairness/rotation economics until demand and real usage patterns are validated.

## Deferred Digital Products Bot Ideas

- [ ] eSIM Auto-Selector:
accept live location or port name, map it to country/region, then recommend the cheapest available eSIM package from `eSIM Access`.
Status: Deferred (planned after `main_bot` closure and core `digital_products_bot` implementation).

- [ ] eSIM / digital top-up low-balance reminder:
monitor remaining data and notify user when package reaches low threshold (example: `100MB`) with one-tap renewal CTA.
Status: Deferred (depends on completed eSIM purchase + usage polling flow).

- [ ] Referral / affiliate system with bonus credit reward:
referrer earns platform bonus credit after the invited user completes a qualifying paid order; bonus is spendable across shared-wallet platform bots.
Status: Deferred (planned as shared wallet / platform reward feature, not eSIM-specific reward).
