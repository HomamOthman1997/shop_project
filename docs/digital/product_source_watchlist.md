# Digital Product Source Watchlist

## Goal

Keep a small operator-approved product list, then attach provider sources and price-watch links to those products.

The catalog should be demand-driven, not provider-driven. We do not import a whole marketplace just because a provider exposes it.

## Product Cap

Target fewer than 100 public products/families. Each product can have many packages or durations.

Examples:

- PUBG Mobile can have many UC packages.
- Netflix can have 1-month and 12-month options.
- Apple Gift Card can have many USD denominations.

## Source Priority

Provider choice must follow this order:

1. If the exact product/package exists in G2Bulk, use G2Bulk only.
2. If G2Bulk does not cover it, use the approved external source for that product.
3. If the product is a marketplace product, fetch candidates on demand and keep the chosen links only.
4. If the product is indirect, label it as indirect in the customer flow.

This prevents duplicate provider routes for the same product and keeps admin execution predictable.

## Watchlist File

The seed watchlist lives in:

`data/digital_product_watchlist.csv`

Important columns:

- `product_key`: stable internal key.
- `category`: `games`, `chat_apps`, `gift_cards`, `subscriptions`, `software`.
- `priority`: operator priority bucket.
- `display_name`: customer/admin label.
- `region_policy`: allowed or expected regions.
- `default_duration`: default subscription duration when relevant.
- `unit_kind`: UC, diamond, USD, subscription, license, Apple balance, etc.
- `preferred_provider`: `g2bulk`, `bittopup`, or `external`.
- `sourcing_policy`: `g2bulk_first`, `external_manual`, `on_demand`, or `indirect_apple`.
- `g2bulk_hint`: search/category hint for G2Bulk.
- `bittopup_slug`: approved BitTopup goods slug when used.
- `g2g_search_query`: query to use for on-demand marketplace checks.
- `public_note`: user-facing caveat or operator note.
- `active`: whether this product is in scope.

The loader is:

`services/digital_products/product_watchlist.py`

## Source Policies

### `g2bulk_first`

Use G2Bulk as the only active source when the package exists there. External links can be kept for reference, but they should not become customer-visible alternatives.

### `external_manual`

Use an approved non-G2Bulk source as a manual admin route. This is appropriate for BitTopup chat-app products where G2Bulk has no exact package.

### `on_demand`

Do not scan the whole provider. Search only when:

- the product is requested by customers,
- the operator asks for it,
- or the product is already on the watchlist and needs a price refresh.

This is the right mode for large marketplaces such as G2G.

### `indirect_apple`

The customer receives an Apple Gift Card, not a direct subscription.

Examples:

- ChatGPT via Apple Gift Card
- Canva via Apple Gift Card
- CapCut via Apple Gift Card

The customer copy must say that activation depends on the user's Apple ID region and App Store eligibility.

## Price Update Rule

Run source price checks every 12 hours for approved links only.

Apply automatic source-cost updates only when:

- product key and compare key still match,
- parsed price is greater than zero,
- change is within 10%,
- provider page is not an error/captcha page,
- package amount/unit/duration still matches,
- parser confidence is high.

If the price difference is more than 10%, mark the source `under_review` and keep the last approved active price.

## Admin Workflow

1. Operator edits the watchlist or adds a product.
2. The source finder checks only that product against candidate providers.
3. The chosen source URL is saved as a provider source.
4. The 12-hour watcher updates observed prices.
5. Admin reviews only changed, unmapped, or suspicious rows.

## Current Seed Scope

The first watchlist includes:

- Mobile games: PUBG, Free Fire, Mobile Legends, Honor of Kings, Roblox, Valorant, Yalla Ludo, Jawaker, New State.
- Chat apps: Discord, IMO, Likee, Bigo Live, Nimo TV, Poppo Live, Soul Chill, SUGO, Chamet, Xena, YoHo, Tango, ChillChat.
- Gift cards: Apple/iTunes, PlayStation, Steam, Xbox, Nintendo, Razer.
- Subscriptions: Netflix, Shahid, Telegram Premium.
- Indirect Apple flows: ChatGPT, Canva, CapCut, Picsart, Duolingo, Gemini, Claude.
- Software/VPN: Windows, Office 365, Kaspersky, Proton VPN, Nord VPN, Express VPN.
- Syrian services: Syriatel, MTN, Sham Cash, internet bills, bank transfers, Smart Touch, satellite internet, passport booking, electricity bills, ECSC bills, Yalla Go, Raken.

This is intentionally a starting point, not a final sales catalog.
