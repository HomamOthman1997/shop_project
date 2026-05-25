# Numbers Mini App Migration Checklist

Last updated: 2026-05-21
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
- [x] Rental number price check and purchase
- [x] Call number price check and purchase
- [x] Best-choice provider display
- [x] Show other available providers
- [x] Hide unavailable providers from the customer UI
- [x] Provider success-rate display with star badge
- [x] My numbers / active orders view
- [x] Temporary order refresh
- [x] Temporary cancel/refund action
  - Shared backend refund service now used by both Mini App and Telegram wrappers.
- [x] Busy state while refund/cancel is running
- [x] Replacement number request
- [x] Alternate provider retry with suggested price
  - Backend tests now cover current-provider replacement and alternate-provider replacement.
  - Alternate provider ranking now uses the same retry scoring helper as the Telegram flow.
- [x] Second-code request
  - Shared backend second-code service now used by both Mini App and Telegram wrappers.
- [x] Rental SMS fetch
- [x] Rental finish action
- [x] Rental renew action
- [x] Rental wake action
- [x] Rental notes/tags fetch
- [x] Rental cancel/refund action when eligible and no SMS was received
- [x] Call recording download when available
- [x] Account screen
- [x] Wallet activity with order subject when `order_id` is available
- [x] Support ticket creation
- [x] Language switching
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

- [x] Expand refund/recovery test matrix for temporary numbers and call numbers.
  - Cover: expired order, provider already refunded, missing activation, missing provider order id, empty provider response, provider 404/not found, provider cancel failed but retryable, provider cancel permanently failed, finance refund failed.
- [x] Confirm auto-refund behavior after timeout across providers.
  - Done means: no-code/no-call timeout checks provider first, refunds provider when needed, then refunds wallet idempotently.
- [x] Confirm manual/admin-side provider refund sync.
  - Done means: if provider/site already refunded or removed the activation, Mini App refresh/cancel can still close locally and credit the user when eligible.
- [x] Add visible order timeline/history for refund attempts.
  - Done means: customer sees that the app is checking provider/wallet instead of thinking the button is stuck. Mini App now includes recent backend order events when available.

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

## Deferred engineering work

- [x] Add `.env.example` with safe placeholder values.
- [x] Add `pyproject.toml` for lint/format/test configuration.
- [x] Add a global or Numbers-specific health route if Railway health checks need it.
- [hold] Split very large files such as `store_sections.py` and `custom_services.py`.
- [hold] Reduce global state in `bot_manager.py`.
- [x] Add broader CI coverage for Mini App backend routes and refund edge cases.

## Recommended execution order

1. Selection UX: searchable service/country/state dropdowns and no stale selection across modes.
2. Call number polish: timeline, empty state, recording preview/fallback validation.
3. Refund matrix: tests and edge-case handling for expired/already-refunded/missing provider records.
4. Wallet and recharge verification in live Telegram.
5. Branding/config audit on Railway.
6. Admin-only diagnostics for hidden providers.
7. Deferred engineering cleanup.
