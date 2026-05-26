# Numbers Mini App Migration Checklist

Last updated: 2026-05-26
Scope: moving customer-facing Numbers Telegram flows into `/mini/numbers`

## Status legend

- `[ ]` not started
- `[~]` partially done / usable but still open
- `[x]` done enough for current scope
- `[hold]` intentionally stays in Telegram or deferred engineering work

## Ground rules

- Keep Telegram for push notifications, owner/admin operations, and any flow that needs a chat reply thread.
- Keep provider internals hidden from customers unless the view is explicitly admin-only.
- Do not expose unavailable providers in the customer price list.
- Every customer-facing Arabic screen must be Arabic and RTL, except provider cards may use layout-specific LTR alignment when needed for price/name badges.
- A task is not closed until it is tested in the real Telegram Mini App webview, not only in a desktop browser.

## Already moved to the Mini App

- [x] Temporary number price check and purchase
  - Mini App price rows use the shared API quote-token format, purchase routes through `create_number_order_from_quote(...)`, legacy/non-API Mini App quote tokens are rejected, and old Mini App-only provider purchase helpers were removed.
- [x] Country suggestions
  - `country_suggestions_service` owns the shared cheap-country cache/ranking, the Mini App calls that service, and `/api/v1/numbers/country-suggestions` exposes the same behavior through `numbers:quotes`.
- [x] Rental number price check and purchase
  - Rental quote options use signed shared quote tokens, and purchase routes through the shared rental order creation path.
- [x] Call number price check and purchase
  - Voice quote rows use signed shared quote tokens, and purchase routes through the shared voice order creation path.
- [x] Best-choice provider display
- [x] Show other available providers
- [x] Hide unavailable providers from the customer UI
- [x] Provider success-rate display with star badge
- [x] My numbers / active orders view
- [x] Mini App order payload uses the shared public API order payload as its base.
  - Done means: provider obfuscation, public status, refund payload, action flags, and cost-hiding come from `order_service.public_order_payload(...)`; the Mini App layer only adds UI labels/detail rows, Mini App recording URL, refresh flags, and second-code display fields.
- [x] Order status refresh through the shared API service
  - Mini App refresh now calls `order_refresh_service.refresh_number_order(...)` for temporary, rental, and voice orders.
  - Refresh is webhook-first and does not poll providers when webhook delivery is active or global provider polling is disabled.
  - The active orders screen does a user-triggered/status refresh only; the old JavaScript auto-poll timer was removed.
- [x] Server-managed temporary refund flow
  - The Mini App no longer exposes a primary manual refund button for temp orders. Timeout/no-code refunds are handled by backend policy, provider-aware cancellation, wallet refund, and support-review escalation.
- [x] Refund state display
  - Customers can see refunded/pending-refund state on the order receive card.
- [x] Replacement number request
- [x] Alternate provider retry with suggested price
  - Mini App replacement/alternate actions now call the shared Numbers order service and use idempotency keys.
  - Telegram replacement/alternate callbacks also call the same service with `source=numbers_telegram`; Telegram keeps only refund precheck, chat message update, and waiter queueing.
- [x] Second-code request
  - Mini App now delegates to the API-level resend service. The order resets to waiting and the next code is expected through provider webhook delivery.
- [x] Rental SMS display/action
  - Rental SMS calls `order_rental_service` and reads stored webhook state instead of polling the provider.
- [x] Rental finish action
- [x] Rental renew action
- [x] Rental wake action
- [x] Rental notes/tags fetch
  - Rental finish/renew/wake/notes now call `order_rental_service`; the Mini App layer only handles Telegram auth and UI payload conversion.
- [x] Rental refund protection is server-managed; the Mini App does not advertise a manual cancel action.
  - Rental no-SMS guard/cancel/refund logic now delegates to `order_rental_protection_service`, the same backend service used by Telegram wrappers and API rental creation.
  - The unused Mini App manual cancel route implementation and dead frontend cancel/refund copy were removed; `/mini/numbers/api/orders/{order_id}/cancel` remains unregistered.
- [x] Call recording download when available
  - Download uses `order_recording_service` and already-stored recording URIs only; it does not poll provider call status before downloading.
- [x] Account screen
- [x] Wallet activity with order subject when `order_id` is available
- [x] Support ticket creation
- [x] Language switching
- [x] Numbers bot customer entry now opens the Mini App surface only
  - `/start`, language selection, legacy cancel/back, stale `flow:type:*` callbacks, and empty My Numbers no longer route the real Numbers bot into Telegram ordering.
  - Legacy temp/rental/voice Telegram order buttons require `NUMBERS_TELEGRAM_ORDER_FLOW_ENABLED=true`; the documented/default value is false.
- [x] Sticky bottom tabs
- [x] Two-column provider layout for non-best providers

## Must finish before calling the Mini App complete

### Selection UX

- [x] Replace native country select with a searchable modern dropdown.
  - Done means: works on mobile Telegram webview, supports `Any country`, and cannot be opened before service selection.
- [x] Replace native state select with a searchable modern dropdown.
  - Done means: appears only after United States is selected, defaults to `Any state`, and cannot leak across number modes.
- [x] Port Telegram smart country/state suggestions.
  - Done means: common/cheap countries and states are ranked ahead of the full list while search still works. Mini App now also asks the backend for service-specific cheap country suggestions.
- [x] Port inline-search parity for service, country, and state selection.
  - Done means: Mini App search covers aliases, prefixes, loose ordered matches, and common country/state shortcuts.

### Call Number Flow

- [x] Improve Call number UI beyond the current basic flow.
  - Done means: clear timeline for waiting/checking/call received/refunded, smarter empty state, and clearer instructions before purchase.
- [x] Validate Call number fallback behavior in Mini App.
  - Done means: generic voice route, unavailable route, and recording-ready states are all tested against backend responses.
- [x] Add in-app recording preview if practical.
  - Done means: user can play recording in the Mini App, with download still available as fallback.

### Refund And Recovery Coverage

- [x] Move temporary order auto-refund to backend-managed flow.
  - Done means: refresh/timeout paths run provider-aware auto-refund and return refund state without a customer manual refund endpoint.
- [x] Provider inbound webhook support for temp and rental codes.
  - Done means: provider callbacks update orders by `provider + provider_order_id`, log audit events, and enqueue customer-facing `numbers.order.sms` webhooks.
- [x] Disable default provider SMS polling for Numbers code delivery.
  - Done means: `numbers_provider_sms_polling_enabled` defaults to false, Mini App order refresh does not poll providers, and Telegram recovery/rental SMS paths respect the same gate.
- [x] Expand refund/recovery test matrix for temporary numbers and call numbers.
  - Cover: expired order, provider already refunded, missing activation, missing provider order id, empty provider response, provider 404/not found, provider cancel failed but retryable, provider cancel permanently failed, finance refund failed.
- [x] Confirm auto-refund behavior after timeout across providers.
  - Done means: no-code/no-call timeout checks provider first, refunds provider when needed, then refunds wallet idempotently.
- [x] Confirm manual/admin-side provider refund sync.
  - Done means: if provider/site already refunded or removed the activation, Mini App refresh/server-managed refund can still close locally and credit the user when eligible.
- [x] Add visible order timeline/history for refund attempts.
  - Done means: customer sees that the app is checking provider/wallet instead of thinking the button is stuck. Mini App now includes recent backend order events when available.
- [x] Remove dead Mini App manual cancel/action branches after shared-service consolidation.
  - Done means: the Mini App rental action handlers no longer keep unreachable provider-direct fallback code after returning shared-service responses, and no unused customer cancel endpoint remains in `miniapp.py`.

### Wallet And Recharge

- [x] Wallet activity labels are good when an order is linked.
- [x] Improve wallet activity labels for entries without `order_id`.
  - Done means: external bot/source/service is shown when available, otherwise the generic label is still clear enough.
- [x] Recharge button/link exists.
- [ ] Verify balance/recharge opening live inside Telegram and Railway.
  - Done means: tapping balance and account recharge both open the intended bot link on mobile Telegram.
- [x] Decide whether to keep recharge in Telegram or build a native Mini App recharge flow.
  - Recommendation: keep proof/payment chat handling in Telegram unless there is a strong reason to duplicate it.

### Configuration And Branding

- [x] Numbers Mini App branding uses Phantom naming.
- [ ] Verify Railway env for the digital products bot username.
  - Expected: `digital_products_bot_username=PHanToOoM_SeaFarers_BOT`; local `.env.example` documents this, live Railway value still needs dashboard verification.
- [x] Audit remaining customer-facing `CyberZone Numbers` strings.
  - Done means: customer sees Phantom branding wherever this bot should be Phantom-branded.
- [ ] Confirm Mini App public URLs and feature flags in Railway after deploy.
  - Include: `NUMBERS_MINIAPP_ENABLED`, `NUMBERS_MINIAPP_PUBLIC_URL`, and related bot usernames.

### Visual QA

- [x] Provider cards use best provider full-width and other providers two per row.
- [x] Active order cards focus on receive state, code, resend availability, and refund status.
- [x] Provider cards show public provider IDs instead of real provider names.
- [ ] Test long provider names on real Telegram mobile webview.
  - Done means: no overlap with star badge, price, or buy button.
- [ ] Test Arabic RTL screens end to end.
  - Done means: selection forms are RTL, provider cards remain visually correct, and no English fallback appears in Arabic mode.
- [ ] Test sticky bottom tabs after long scrolling.
  - Done means: tabs stay pinned, labels remain readable, and content is not hidden behind them.
- [x] Add a small manual visual QA checklist for Telegram Mini App screenshots.

### Admin-Only Diagnostics

- [x] Add admin-only hidden-provider diagnostics.
  - Done means: admins can inspect why a provider was hidden without exposing low balance or provider errors to customers.
- [x] Add price/debug metadata only behind an admin guard.
  - Done means: customer payloads stay clean; operator payloads can explain filtering.

## Intentionally not moved

- [hold] Telegram push notifications for code received, timeout, refund, and support updates.
- [hold] Owner/admin provider management.
- [hold] Manual financial adjustments and sensitive refund operations.
- [hold] Support reply/solve workflow that depends on Telegram chat threads.
- [hold] Provider balance alerts and operational logs.
- [hold] Live provider webhook verification for every upstream provider.

## Deferred engineering work

- [x] Add `.env.example` with safe placeholder values.
- [x] Add `pyproject.toml` for lint/format/test configuration.
- [x] Add a global or Numbers-specific health route if Railway health checks need it.
- [hold] Split very large files such as `store_sections.py` and `custom_services.py`.
- [hold] Reduce global state in `bot_manager.py`.
- [x] Add broader CI coverage for Mini App backend routes and refund edge cases.

## Recommended execution order

1. Configure upstream provider dashboards to `https://phantom-app.net/api/v1/provider-webhooks/{provider}?token=...`.
2. Run live webhook verification per provider and replay/fix unmatched callbacks.
3. Wallet and recharge verification in live Telegram.
4. Branding/config audit on Railway.
5. Deferred engineering cleanup.
