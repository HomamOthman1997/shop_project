# Digital Products Docs

Digital products covers game store, gift cards, eSIMs, topups, and related catalog/order flows.

## Active Decision

Digital products should become an API-first product area with:

- a web dashboard/client,
- Telegram bot and Mini App clients,
- documented APIs that can support customer-built bots,
- shared catalog, pricing, wallet, order, and fulfillment services.

## Current Direction

- Keep provider-specific source docs under `docs/providers/`.
- Keep generated historical analysis under `docs/archive/generated-reports/`.
- When Digital work resumes, create focused docs here instead of mixing it with Numbers or Cards.

## Likely API Areas

- catalog categories and search,
- product details and availability,
- price quotes,
- order creation,
- delivery/status webhooks where providers support them,
- polling only as a documented fallback,
- refund/recovery status,
- provider/admin diagnostics.

## Current Backend Contract

The frontend and Telegram Mini App must behave as API clients. They should not carry product lists, provider routing, prices, or fulfillment decisions locally.

Current API flow:

1. `GET /api/v1/digital/catalog`
   - Returns games from provider-backed catalog.
   - Returns operator-approved products from `data/digital_product_watchlist.csv`.
   - Returns product categories, including `syrian_services` / `خدمات سورية`.
   - Returns input fields per product so the frontend knows what to collect.
   - Marks products as `orderable=false` until a backend source/price exists.
   - Returns `source_diagnostics` as a backend health summary for source-sheet issues. It is not customer-facing copy.

2. `GET /api/v1/digital/source-diagnostics`
   - Requires an operator/admin key with `digital:sources:read`.
   - Returns detailed watchlist/source validation issues for admin tooling.
   - Intended for operators and backend checks, not public customer UI.

3. `GET /api/v1/digital/quotes`
   - `kind=game&game_id=...` returns game packages.
   - `kind=product&product_id=...` returns packages only from backend-defined provider sources.
   - Every quote includes a signed `quote_token`.
   - Product quotes group all known provider sources for the same package so the admin sees every execution option.

4. `POST /api/v1/digital/orders`
   - Accepts a signed `quote_token`.
   - Accepts `customer_data` for generic products.
   - Validates required input fields from the quote before charging.
   - Charges the wallet server-side.
   - Creates a manual fulfillment order and notifies admin with all provider options in the quote.

5. `POST /api/v1/digital/orders/{order_id}/manual-action`
   - Requires `digital:orders:manage`.
   - Admin-only action endpoint for manual fulfillment workflows.
   - Supports `claim`, `auto_api`, `future`, `complete`, and `refund`.
   - `claim` moves the order to processing and can notify the customer.
   - `auto_api` submits the cheapest available API provider option from the order quote.
   - `future` submits the cheapest G2Bulk Future option and stores private delivery lines for admin handling.
   - `complete` marks the order successful and can notify the customer.
   - `refund` uses the financial ledger refund path, so wallet refunds stay idempotent.
   - This scope is intentionally not included in customer-created API keys.

6. `GET /api/v1/digital/admin/orders`
   - Requires `digital:orders:manage`.
   - Lists manual fulfillment orders for admin tooling.
   - Supports `status=pending|processing|completed|refunded|all` and `limit`.
   - Non-super keys are restricted to their reseller scope.

Frontend rule: if the backend does not return a quote, the frontend cannot sell that package.
