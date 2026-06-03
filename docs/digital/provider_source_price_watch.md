# Digital Provider Sources and Price Watch

## Goal

Add BitTopup as a provider source for digital products without duplicating products already available from G2Bulk or other providers.

The customer should see one product/package. Internally, the same package can have multiple provider sources with different fulfillment modes:

- `g2bulk` with `auto_topup` when the API can fulfill directly.
- `g2bulk` with `manual_topup` for feature/add-on/manual cases.
- `g2bulk` or other API providers with `voucher_delivery` for delivered codes.
- `bittopup` with `manual_topup`, fulfilled by the admin.

BitTopup prices can be checked every 12 hours and auto-applied only within strict guardrails. Larger or suspicious changes go to admin review.

## Current Code Foundation

The Mini App already exposes the concepts we need:

- `services/digital_products/fulfillment_rules.py`
  - Defines `AUTO_TOPUP_MODE`, `MANUAL_TOPUP_MODE`, `VOUCHER_DELIVERY_MODE`.
  - Builds package identity via `offer_compare_key(...)` and `manual_feature_compare_key(...)`.
- `services/digital_products/catalog_service.py`
  - Builds catalog rows with `provider_offers`, `best_provider`, and `best_provider_ref_id`.
  - Merges provider offers and chooses the cheapest enabled source.
- `services/digital_products/miniapp.py`
  - Gift rows expose `best_provider_code`, `providers_count`, `fulfillment_mode`, and `compare_key`.
  - Game rows expose `best_provider_code`, `providers_count`, `fulfillment_mode`, and `compare_key`.
  - Selection quotes are rechecked server-side before storing a Mini App selection.

The existing compare key is the right identity layer:

- `pubg:global:60:uc`
- `pubg:global:8100:uc`
- `roblox:usa:10:usd`
- `yalla_ludo:global:5150:diamond`

## Product Model

Use three layers.

### Product Family

The customer-facing family/group:

- PUBG
- Roblox
- Free Fire
- Yalla Ludo
- Store Cards
- Chat Apps

This maps to existing family logic in `static_taxonomy.py` and `fulfillment_rules.py`.

### Offer Package

The specific package shown to the customer:

- PUBG 60 UC
- PUBG Elite Pass
- Roblox 10 USD
- Poppo 1000 Coins

The stable identifier is `compare_key`. If there is no reliable compare key, the offer must be queued as unmapped.

### Provider Source

A source option for that package:

```json
{
  "provider": "bittopup",
  "ref_id": "https://bittopup.com/goods/pubg-uc#60-uc",
  "source_url": "https://bittopup.com/goods/pubg-uc",
  "price": 0.90,
  "available": true,
  "fulfillment_mode": "manual_topup",
  "compare_key": "pubg:global:60:uc",
  "observed_at": "2026-06-03T00:00:00Z",
  "price_status": "active"
}
```

## Fulfillment Rules

Provider source selection should be deterministic.

1. Prefer `auto_topup` if available and enabled.
2. Use `voucher_delivery` when the product is a code/card and delivery is supported.
3. Use `manual_topup` when no automated option is available, or when the package is explicitly marked manual.
4. Never show provider names to customers unless we intentionally add a public provider label later.

Suggested mode mapping:

| Provider | Source type | Fulfillment mode |
| --- | --- | --- |
| G2Bulk game top-up API | direct game catalogue | `auto_topup` |
| G2Bulk feature/add-on/manual product | product catalogue/manual feature | `manual_topup` |
| G2Bulk gift card/code | product catalogue code delivery | `voucher_delivery` |
| BitTopup | public product page | `manual_topup` |

## BitTopup Scraper Scope

Scrape only for internal catalog and price monitoring.

Initial scope:

- Product listing pages for discovery.
- Product detail pages for denominations/prices.
- No login.
- No checkout automation.
- No cart/payment automation.
- No customer-visible provider details.

The scraper output should be normalized into `provider_offers`, not directly into customer products.

## BitTopup Normalization

Each scraped denomination needs:

- `source_url`
- `source_product_slug`
- `source_product_name`
- `denomination_name`
- `current_price_usd`
- `old_price_usd` if present
- `discount_percent` if present
- `category_hint`
- `fulfillment_mode = manual_topup`
- `compare_key`
- `parse_confidence`

If `compare_key` is empty or confidence is low, queue it for admin mapping.

## Price Watch Guardrails

The 12-hour watcher may auto-update only if all checks pass:

1. Matched offer has a non-empty `compare_key`.
2. Existing source is already linked to the same `compare_key`.
3. New price is greater than zero.
4. New price is not lower than a configured absolute minimum.
5. Relative change is `<= 10%`.
6. The same price is observed in two consecutive successful scrapes, or the previous scrape for that source was successful and the parser version did not change.
7. Page parse confidence is high.
8. The page is not a Cloudflare/error/captcha/maintenance page.
9. The denomination text still matches the same amount/unit.

If any check fails:

- Do not update the active source price.
- Set the source status to `under_review`.
- Store the observed price and reason.
- Notify admin.

## Review Cases

Move to `under_review` when:

- Price difference is greater than 10%.
- The package disappeared from the source page.
- The page parser returns low confidence.
- The compare key changed.
- The source page returns an error or anti-bot page.
- A new BitTopup package has no local match.

Admin actions:

- `Approve price`
- `Reject observed price`
- `Map to existing package`
- `Create new manual package`
- `Disable source`

## Suggested Collections

### `digital_provider_sources`

Stores source offers by provider and compare key.

Important fields:

- `_id`
- `provider`
- `compare_key`
- `source_url`
- `source_ref`
- `source_product_name`
- `source_denomination_name`
- `fulfillment_mode`
- `active_price`
- `observed_price`
- `previous_observed_price`
- `available`
- `price_status`: `active`, `under_review`, `disabled`, `unmapped`
- `review_reason`
- `parse_confidence`
- `last_seen_at`
- `last_success_at`
- `last_error`
- `parser_version`

Indexes:

- unique: `provider + source_ref`
- lookup: `compare_key + provider`
- review queue: `price_status + last_seen_at`

### `digital_price_watch_runs`

Stores watcher run stats:

- `provider`
- `started_at`
- `finished_at`
- `status`
- `pages_checked`
- `offers_seen`
- `auto_updated`
- `under_review`
- `unmapped`
- `errors`

## Integration Points

### Catalog Build

`get_catalog_snapshot()` should merge BitTopup source offers into existing `provider_offers`.

Do not make BitTopup a separate customer-facing category. It should become another provider offer for the same package when `compare_key` matches.

### Mini App Payload

Keep current customer payload shape:

- `best_provider_code`
- `providers_count`
- `fulfillment_mode`
- `compare_key`

Do not expose source URL or scraper review state to the customer.

### Order Creation

When the selected source is:

- `auto_topup`: bot executes provider API.
- `voucher_delivery`: bot delivers code or polls delivery.
- `manual_topup`: bot creates a paid pending order and notifies admin with fulfillment details.

For BitTopup manual orders, admin message should include:

- product/package
- customer input fields
- source URL
- source price observed
- sale price charged
- buttons: `Completed`, `Refund`, `Ask user`

## 12-Hour Watcher Flow

1. Load enabled BitTopup source pages.
2. Fetch pages with timeout and low rate.
3. Parse product denominations.
4. Normalize each denomination to compare key.
5. Upsert source offers.
6. Auto-update prices only when guardrails pass.
7. Mark suspicious changes as `under_review`.
8. Send one admin summary, not one message per offer unless critical.

Admin summary example:

```text
BitTopup price watch completed

Pages checked: 18
Offers seen: 246
Auto-updated: 31
Under review: 4
New unmapped: 12
Errors: 1
```

## Implementation Phases

### Phase 1: Data and Parser

- Add BitTopup scraper/parser service.
- Add provider source storage.
- Add unit tests using saved HTML fixtures.
- Parse homepage/listing/detail pages into normalized offers.

### Phase 2: Matching and Review

- Generate compare keys for BitTopup offers.
- Queue unmapped offers.
- Add under-review guardrails.
- Add admin review commands/buttons.

### Phase 3: Catalog Merge

- Merge approved BitTopup source offers into `provider_offers`.
- Ensure customer sees one package.
- Ensure `manual_topup` is selected only when appropriate.

### Phase 4: Watcher

- Add 12-hour watcher job.
- Add run stats.
- Add admin summary notification.
- Add automatic disable on repeated parse failures.

### Phase 5: Manual Fulfillment UX

- Improve admin order notification for manual provider sources.
- Add `Completed`, `Refund`, and `Ask user`.
- Store source/provider fields internally on the order.

## Non-Goals

- No automatic purchase on BitTopup.
- No login/session automation.
- No checkout/payment automation.
- No customer-visible provider routing.
- No blind price updates without guardrails.

## Open Questions

- Should auto-update change only provider source cost, or also customer sale price?
- Should customer sale price keep a fixed global markup, or per-family markup?
- Should `under_review` pause the source only, or the whole package when no other provider exists?
- Should BitTopup discovery scan the whole site, or only admin-approved source URLs after initial import?

Recommended answer for the first version:

- Auto-update source cost only.
- Recompute sale price from configured markup.
- If source goes under review and no other source exists, keep the last approved customer price but mark internal source as needing review.
- After the initial full scrape, watch only approved source URLs.
