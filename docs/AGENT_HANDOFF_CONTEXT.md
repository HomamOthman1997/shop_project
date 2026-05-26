# Agent Handoff Context

This file is a compact project memory for future Codex/AI sessions. It should be referenced instead of pasting the full conversation.

Last updated:
- 2026-05-26

## Current Product Direction

We are building the whole commerce system as an API-first platform.

Active product areas:
- Numbers
- Cards
- Digital products
- Proxies
- Owner/reseller operations

Primary UI today:
- Telegram bots
- Telegram Mini App for Numbers ordering and account workflows.

Architecture decision:
- Do not rewrite everything into a standalone website first.
- Every major product area must eventually have a web surface on `phantom-app.net`.
- Every major product area must expose or be ready to expose an API suitable for:
  - Telegram bots
  - Telegram Mini App
  - future web dashboard
  - admin panel
  - customer-built bots and partner integrations
- Build shared backend/API layers first, then use them from every client.

Canonical decision doc:
- `docs/platform/API_FIRST_PRODUCT_STRATEGY.md`

## Current Repo State Summary

Repository:
- `shop_project`
- main branch is used for production-oriented work.

Important recent commits:
- `11f1f7e Add SMS-Ready and PVA Pins providers`
- `ba23fe9 feat: add landing page handler at root path for phantom-app.net`
- `efc905f Obfuscate new provider display names`

Current in-flight Numbers consolidation:
- Versioned Numbers API work lives under `services/numbers/api.py` and shared API services.
- Customer API key scopes include order create/read/refresh/resend/replace/rental-actions, quotes, account read, webhooks, and key management.
- Mini App temp purchase now uses the API quote/order service path where possible.
- Mini App rental and voice quote/create now use shared API quote tokens and `create_number_order_from_quote(...)` where possible.
- Mini App refresh delegates to the shared webhook-first API refresh service for temp, rental, and voice orders.
- Mini App resend/second-code delegates to the API resend service.
- Mini App replacement/alternate-provider actions delegate to the shared Numbers order service and use idempotency keys.
- Mini App rental SMS/finish/renew/wake/notes actions delegate to `order_rental_service`.
- Telegram rental SMS/finish/renew/wake/notes callbacks also delegate to `order_rental_service`; the handlers keep only Telegram callback UX and the Hero no-SMS safety pre-check before finish.
- `order_rental_service` accepts explicit `source` values so API, Mini App, and Telegram rental action events/check markers are distinguishable in order history.
- Mini App order cards now build from the shared `order_service.public_order_payload(...)` and add only Mini App UI fields such as labels, detail rows, Mini App recording URL, refresh flags, and second-code pricing.
- API, Mini App, and Telegram voice recording parsing/downloads now delegate to `order_recording_service`; route/handler layers handle auth, ownership, localization, Telegram sending, and response headers only.
- Telegram voice call check/waiter now delegates provider call fetching and recording URI extraction to `order_voice_service`; the remaining polling loop is a Telegram notification wrapper and should not be copied into API/Mini App routes.
- Rental no-SMS protection, provider close/cancel, wallet refund, guard scheduling, and global sweep now live in `order_rental_protection_service`; Telegram, Mini App, and versioned API rental creation delegate to it.
- Mini App legacy provider-direct rental action branches and manual cancel fallback code were removed after shared-service consolidation.
- Default provider SMS polling is disabled through `numbers_provider_sms_polling_enabled=False`.
- Provider inbound callbacks should use `https://phantom-app.net/api/v1/provider-webhooks/{provider}?token=<provider-webhook-token>`.
- Provider webhook processing updates temporary and rental orders, logs provider webhook audit events, and queues customer-facing `numbers.order.sms` webhooks.
- The active order UI is centered on receive status, code, resend availability, and refund status; no primary manual temp refund button should be reintroduced.
- Latest local validation for Numbers after public payload and voice recording service consolidation:
  - `python -m py_compile services/numbers/miniapp.py services/numbers/api_payloads.py services/numbers/order_service.py services/numbers/order_rental_service.py services/numbers/order_recording_service.py services/numbers/api.py` passed.
  - `python -m py_compile services/numbers/api.py services/numbers/miniapp.py services/numbers/order_recording_service.py tests/numbers/test_numbers_api.py tests/core/test_numbers_miniapp.py` passed.
  - `python -m py_compile services/numbers/handlers/core_numbers_buy.py services/numbers/order_recording_service.py services/numbers/api.py services/numbers/miniapp.py` passed.
  - `python -m py_compile services/numbers/order_recording_service.py services/numbers/miniapp.py services/numbers/handlers/core_numbers_buy.py tests/numbers/test_order_recording_service.py tests/core/test_numbers_miniapp.py` passed.
  - `python -m py_compile services/numbers/order_voice_service.py services/numbers/order_recording_service.py services/numbers/handlers/core_numbers_buy.py tests/numbers/test_order_voice_service.py tests/numbers/test_order_recording_service.py` passed.
  - `python -m py_compile services/numbers/handlers/core_numbers_buy.py services/numbers/order_rental_service.py` passed.
  - `python -m py_compile services/numbers/order_rental_service.py services/numbers/handlers/core_numbers_buy.py services/numbers/miniapp.py tests/numbers/test_rental_simulation_flow.py tests/core/test_numbers_miniapp.py` passed.
  - `python -m pytest tests/numbers/test_numbers_api.py::test_numbers_api_download_recording_is_owner_scoped tests/numbers/test_numbers_api.py::test_numbers_api_download_recording_returns_not_ready tests/core/test_numbers_miniapp.py::test_numbers_voice_order_payload_exposes_recording_download -q` passed with `3 passed`.
  - `python -m pytest tests/numbers/test_order_recording_service.py tests/core/test_numbers_miniapp.py::test_numbers_voice_recording_uri_accepts_provider_variants -q` passed with `3 passed`.
  - `python -m pytest tests/numbers/test_order_voice_service.py tests/numbers/test_order_recording_service.py -q` passed with `4 passed`.
  - `python -m pytest tests/numbers/test_numbers_order_rental_service.py tests/numbers/test_rental_protection.py -q` passed with `23 passed`.
  - `python -m pytest tests/numbers/test_rental_simulation_flow.py::test_simulated_rental_fetch_sms_finish_and_wake tests/numbers/test_rental_simulation_flow.py::test_simulated_rental_purchase_then_renew_after_two_hours -q` passed with `2 passed`.
  - `python -m pytest tests/numbers/test_numbers_order_rental_service.py tests/numbers/test_rental_simulation_flow.py::test_simulated_rental_fetch_sms_finish_and_wake tests/numbers/test_rental_simulation_flow.py::test_simulated_rental_purchase_then_renew_after_two_hours tests/core/test_numbers_miniapp.py::test_numbers_miniapp_rental_actions_use_shared_services -q` passed with `12 passed`.
  - `python -m py_compile services/numbers/order_rental_protection_service.py services/numbers/handlers/core_numbers_buy.py services/numbers/miniapp.py services/numbers/order_service.py` passed.
  - `python -m pytest tests/numbers/test_rental_protection.py tests/numbers/test_rental_simulation_flow.py tests/numbers/test_numbers_order_service.py tests/core/test_numbers_miniapp.py -q` passed with `101 passed`.
  - `python -m py_compile services/numbers/miniapp.py services/numbers/order_service.py services/numbers/order_rental_protection_service.py tests/core/test_numbers_miniapp.py` passed.
  - `python -m py_compile services/numbers/miniapp.py tests/core/test_numbers_miniapp.py` passed.
  - `python -m pytest tests/core/test_numbers_miniapp.py -q` passed with `58 passed`.
  - `python -m pytest tests/numbers tests/core/test_numbers_miniapp.py -q` passed with `385 passed`.
  - `git diff --check -- services/numbers/order_rental_service.py services/numbers/handlers/core_numbers_buy.py services/numbers/miniapp.py tests/numbers/test_rental_simulation_flow.py tests/core/test_numbers_miniapp.py docs/AGENT_HANDOFF_CONTEXT.md docs/numbers/README.md docs/numbers/API_CONTRACT.md docs/numbers/TELEGRAM_FLOW_AUDIT.md` passed with CRLF warnings only.
  - `python -m py_compile services/numbers/order_rental_service.py services/numbers/handlers/core_numbers_buy.py services/numbers/miniapp.py tests/numbers/test_rental_simulation_flow.py tests/core/test_numbers_miniapp.py` passed.
  - `python -m pytest tests/numbers/test_numbers_order_rental_service.py tests/numbers/test_rental_simulation_flow.py::test_simulated_rental_fetch_sms_finish_and_wake tests/numbers/test_rental_simulation_flow.py::test_simulated_rental_purchase_then_renew_after_two_hours tests/core/test_numbers_miniapp.py::test_numbers_miniapp_rental_actions_use_shared_services -q` passed with `12 passed`.
  - `python -m py_compile services/numbers/order_purchase_service.py services/numbers/handlers/core_numbers_buy.py tests/numbers/test_rental_simulation_flow.py tests/numbers/test_temp_refund_flow.py` passed.
  - `python -m pytest tests/numbers/test_rental_simulation_flow.py tests/numbers/test_temp_refund_flow.py -q` passed with `14 passed`.
  - `python -m pytest tests/numbers tests/core/test_numbers_miniapp.py -q` passed with `385 passed`.
  - `python -m py_compile services/numbers/order_service.py services/numbers/order_purchase_service.py services/numbers/handlers/core_numbers_buy.py tests/numbers/test_numbers_order_service.py tests/numbers/test_rental_simulation_flow.py tests/numbers/test_temp_refund_flow.py` passed.
  - `python -m pytest tests/numbers/test_numbers_order_service.py -q` passed with `13 passed`.
  - `python -m pytest tests/numbers/test_numbers_order_service.py tests/numbers/test_rental_simulation_flow.py tests/numbers/test_temp_refund_flow.py tests/core/test_numbers_miniapp.py -q` passed with `85 passed`.
  - `python -m py_compile services/numbers/order_service.py services/numbers/order_purchase_service.py` passed after API/Mini App charge helper extraction.
  - `python -m pytest tests/numbers/test_numbers_order_service.py -q` passed with `13 passed` after API/Mini App charge helper extraction.
  - `python -m py_compile services/numbers/order_charge_service.py services/numbers/order_service.py services/numbers/handlers/core_numbers_buy.py tests/numbers/test_numbers_order_service.py tests/numbers/test_rental_simulation_flow.py tests/numbers/test_temp_refund_flow.py` passed after shared charge helper extraction.
  - `python -m pytest tests/numbers/test_numbers_order_service.py tests/numbers/test_rental_simulation_flow.py tests/numbers/test_temp_refund_flow.py -q` passed with `27 passed` after shared charge helper extraction.
  - `python -m py_compile services/numbers/shared/temp_second_code.py services/numbers/order_resend_service.py services/numbers/handlers/core_numbers_buy.py services/numbers/order_charge_service.py` passed after second-code charge helper integration.
  - `python -m pytest tests/numbers/test_rental_simulation_flow.py::test_simulated_temp_second_code_flow tests/numbers/test_numbers_api.py::test_numbers_api_resend_order_uses_resend_service tests/core/test_numbers_miniapp.py::test_numbers_temp_order_payload_exposes_second_code_action -q` passed with `3 passed`.
  - `python -m pytest tests/numbers/test_numbers_order_service.py tests/numbers/test_rental_simulation_flow.py tests/numbers/test_temp_refund_flow.py tests/numbers/test_numbers_api.py tests/core/test_numbers_miniapp.py -q` passed with `109 passed`.
  - `python -m py_compile services/numbers/order_service.py` passed after consolidating unexpected post-charge provisioning rollback.
  - `python -m pytest tests/numbers/test_numbers_order_service.py tests/numbers/test_rental_simulation_flow.py tests/numbers/test_temp_refund_flow.py -q` passed with `27 passed` after consolidating unexpected post-charge provisioning rollback.
  - `python -m pytest tests/numbers tests/core/test_numbers_miniapp.py -q` passed with `385 passed` after consolidating unexpected post-charge provisioning rollback.
  - `git diff --check -- services/numbers/order_service.py docs/AGENT_HANDOFF_CONTEXT.md docs/numbers/README.md docs/numbers/API_CONTRACT.md docs/numbers/TELEGRAM_FLOW_AUDIT.md` passed with CRLF warnings only.
  - `python -m py_compile services/numbers/order_lifecycle_service.py services/numbers/order_service.py tests/numbers/test_numbers_order_lifecycle_service.py tests/numbers/test_numbers_order_service.py` passed after extracting order lifecycle orchestration.
  - `python -m pytest tests/numbers/test_numbers_order_service.py tests/numbers/test_numbers_order_lifecycle_service.py -q` passed with `17 passed` after extracting order lifecycle orchestration.
  - `python -m pytest tests/numbers/test_numbers_order_service.py tests/numbers/test_numbers_order_lifecycle_service.py tests/numbers/test_rental_simulation_flow.py tests/numbers/test_temp_refund_flow.py tests/numbers/test_numbers_api.py tests/core/test_numbers_miniapp.py -q` passed with `113 passed` after extracting order lifecycle orchestration.
  - `python -m pytest tests/numbers tests/core/test_numbers_miniapp.py -q` passed with `389 passed` after extracting order lifecycle orchestration.
  - `git diff --check -- services/numbers/order_lifecycle_service.py services/numbers/order_service.py tests/numbers/test_numbers_order_lifecycle_service.py docs/AGENT_HANDOFF_CONTEXT.md docs/numbers/README.md docs/numbers/API_CONTRACT.md docs/numbers/TELEGRAM_FLOW_AUDIT.md` passed with CRLF warnings only after extracting order lifecycle orchestration.
  - `node --check webapp/numbers/app.js` could not run locally because `node.exe` returned `Access is denied`.

Latest completed work:
- Numbers Telegram surface cleanup:
  - `numbers_main_menu(...)` is now an inline menu, not a ReplyKeyboard.
  - Numbers bot `/start`, post-language selection, and legacy cancel/back exits clear any reply keyboard and show only Mini App/account/top-up/support inline entries.
  - The Numbers bot no longer sends customers into Telegram number-type selection from `/start` or first-run language selection.
  - Stale Telegram number-flow callbacks (`flow:type:*`, rental add/menu, and country-entry back) are guarded for the real Numbers bot and return the Mini App inline menu unless `numbers_telegram_order_flow_enabled=True` is explicitly configured.
  - `numbers_telegram_order_flow_enabled` is now a real config setting and is documented in `.env.example` as `NUMBERS_TELEGRAM_ORDER_FLOW_ENABLED=false`.
  - Country suggestions are no longer Mini App-only logic. `services/numbers/country_suggestions_service.py` owns the shared cheap-country cache/ranking, the Mini App wraps it, and `/api/v1/numbers/country-suggestions` exposes it under `numbers:quotes` with the `numbers:country-suggestions` rate-limit bucket.
  - Temp replacement creation is no longer duplicated in `core_numbers_buy.py`. `order_service.request_replacement_order(...)` now accepts `source`, optional `telegram_bot_id`, and optional `telegram_wait`; API, Mini App, and Telegram use this service for same-provider replacement and alternate-provider replacement. Telegram keeps chat editing and waiter queueing only.
  - `number_type_kb(...)` itself hides temp/rental/voice Telegram buttons unless that explicit legacy flag is true.
  - Empty "My numbers" no longer offers Telegram "add number"; it offers the Mini App entry when configured plus the back action.
  - Balance/top-up remain available through Telegram inline callbacks for now; recharge method/back/cancel navigation no longer creates ReplyKeyboard buttons.
  - Validation: `python -m py_compile config.py keyboards/main_menu_kb.py keyboards/recharge_methods_keyboard.py handlers/start.py handlers/language.py handlers/main_menu.py services/numbers/keyboards/core_numbers_kb.py services/numbers/handlers/core_numbers.py services/numbers/handlers/core_numbers_buy.py tests/core/test_bot_menu_context.py tests/core/test_start_active_order_notice.py tests/core/test_language_handler.py tests/core/test_main_bot_sandbox_flows.py tests/numbers/test_rental_kb.py` passed.
  - Validation: `python -m pytest tests/numbers tests/core/test_numbers_miniapp.py tests/core/test_bot_menu_context.py tests/core/test_start_active_order_notice.py tests/core/test_language_handler.py tests/core/test_main_bot_sandbox_flows.py -q` passed with `444 passed`.
- Removed the old `SMS-Man` / `smsman` naming from active code, docs, tests, and provider docs.
- Renamed the provider integration to `nonvoip` / `nonvoip_s6` internally.
- Provider adapter file is now `services/numbers/providers/nonvoip_provider.py`.
- Provider test file is now `tests/numbers/test_nonvoip_provider.py`.
- Old `SMSMAN_*` settings were removed from code. Use `NONVOIP_*` settings instead.
- Customer-facing provider display names were tightened:
  - API/Mini App payloads expose `provider_id` and obfuscated display names only.
  - Quote tokens are signed but not encrypted, so quote token payloads now store public `provider_id`, not internal provider codes.
  - Server-side purchase flow maps public `provider_id` back to internal provider code during execution.
- Customer-facing Numbers order payloads were hardened:
  - Public API order payloads do not expose `base_price`.
  - Mini App order payloads no longer expose `base_price_label`.
  - Refund payloads expose only generic customer-safe reasons: `automatic_refund`, `refund_pending`, or empty string. Internal/provider refund causes remain for logs/support review only.
- `GET /api/v1/numbers/account` now returns `recent_activity` from the wallet ledger with customer-safe fields only:
  - exposed: `kind`, `label`, amount/balance labels, `created_at`, and `order_id`;
  - hidden: raw ledger `reason`, metadata, actors, provider names, and debug details.
- `GET /api/v1/numbers/orders/{order_id}/recording` is now implemented on the versioned Numbers API:
  - uses `numbers:orders:read`;
  - scopes order lookup by API key owner/reseller;
  - supports voice orders only;
  - delegates validation/download/filename handling to `order_recording_service` and returns a no-store attachment response.
- `POST /api/v1/numbers/orders/{order_id}/refresh` now supports temp, rental, and voice orders:
  - temp remains webhook-first and only polls providers when polling is explicitly enabled and the order is not webhook-delivered;
  - rental and voice refresh return the current persisted state and record `api_last_refresh_*`, without calling provider polling APIs;
  - public voice order payloads now expose `calls_count`, `recording_available`, and versioned `recording_url` when a recording exists.
- Rental customer actions now have versioned Numbers API endpoints under `/api/v1/numbers/orders/{order_id}/rental/...`:
  - `sms` returns the stored/webhook-delivered rental SMS state and records an API check marker; it does not poll the provider.
  - `finish`, `renew`, `wake`, and `notes` call the shared rental backend service and return customer-safe public order payloads.
  - Rental renewal requires `Idempotency-Key` and uses API idempotency storage.
  - Public rental order payloads expose safe action flags and metadata: `can_finish`, `can_renew`, `can_wake`, `can_notes`, `duration_label`, `end_date`, `notes`, and `tags`.
- Versioned rental quote/create flow is now implemented:
  - `GET /api/v1/numbers/quotes?mode=rental&service=...&country=...&state=...` returns obfuscated providers and signed rental option quote tokens.
  - Rental quote tokens carry public `provider_id` plus option match metadata, not internal provider codes.
  - `POST /api/v1/numbers/orders` now routes quote mode `temp` or `rental` through shared order services.
  - Rental order creation uses `numbers:orders:create`, supports `Idempotency-Key`, charges the wallet, rents from the provider, stores webhook delivery/protection metadata, and returns a customer-safe public order payload.
- Versioned voice quote/create flow is now implemented:
  - `GET /api/v1/numbers/quotes?mode=voice&service=...&country=1&state=...` returns obfuscated providers and signed voice quote tokens.
  - Voice quote tokens carry public `provider_id`, not internal provider codes.
  - `POST /api/v1/numbers/orders` now routes quote mode `voice` through the shared order service.
  - Voice order creation uses `numbers:orders:create`, supports `Idempotency-Key`, charges the wallet, reserves a call-capable number, stores webhook delivery metadata, and returns a customer-safe public order payload.
- Versioned replacement/alternate-provider flow is now implemented:
  - `POST /api/v1/numbers/orders/{order_id}/replace` creates a new temp/voice order from an eligible closed order.
  - `POST /api/v1/numbers/orders/{order_id}/alternate` creates a temp replacement through a different provider when one is available.
  - Both endpoints use `numbers:orders:replace`, require `Idempotency-Key`, revalidate provider offers before charging, and store source order/retry reason metadata.
  - Public order payloads expose customer-safe replacement flags and alternate provider public IDs only.
- Mini App replacement/alternate-provider flow now reuses the shared versioned backend logic:
  - `/mini/numbers/api/orders/{order_id}/replace` and `/alternate` call `request_replacement_order(...)` instead of the older Mini App-only replacement path.
  - The frontend sends `Idempotency-Key` headers for both actions; the server also generates a stable fallback key for Telegram Mini App calls.
  - Responses are converted back to Mini App order payloads so the current receive/code UI keeps working.
- Mini App purchase flow now reuses the shared versioned quote/order logic:
  - price rows for temp, rental, and voice use API quote-token signing and public `provider_id` payloads.
  - `/mini/numbers/api/purchase` routes API quote tokens through `create_number_order_from_quote(...)`.
  - the frontend sends `Idempotency-Key` on purchases; Mini App responses are converted back to the existing UI order payload.
  - legacy/non-API Mini App quote tokens are rejected by `/mini/numbers/api/purchase`; the route no longer falls back to Mini App-only provider purchase helpers.
  - the old Mini App-only quote signer/resolvers and direct provider purchase helpers were deleted from `services/numbers/miniapp.py`.
- Mini App rental action flow now reuses the shared rental backend service:
  - `/mini/numbers/api/orders/{order_id}/sms`, `/finish`, `/renew`, `/wake`, and `/notes` call `order_rental_service`.
  - The Mini App frontend sends idempotency headers for rental actions; renewal also uses backend idempotency storage.
  - Rental SMS/action responses are converted back to Mini App order payloads and do not introduce provider polling in the UI route.
- Telegram rental action cleanup:
  - `rent:sms`, `rent:finish`, `rent:renew`, `rent:wake`, and `rent:notes` callbacks call `order_rental_service` instead of provider adapters directly.
  - Telegram renew uses a stable idempotency key: `telegram:rental_renew:{user_id}:{order_id}`.
  - Telegram passes `source=numbers_telegram`; Mini App passes `source=numbers_miniapp`; API keeps the default `source=numbers_api`.
  - The Hero no-SMS cancel/refund pre-check remains in the Telegram finish callback until that provider-specific UX is validated behind the shared service.
- Purchase provider-provisioning cleanup:
  - `core_numbers_buy.py` no longer calls `buy_number_from_provider(...)` or `rent_number_from_provider(...)` directly.
  - `order_service.py` no longer calls `buy_number_from_provider(...)` or `rent_number_from_provider(...)` directly.
  - API/Mini App temp/voice/rental order creation, Telegram temp/voice/rental purchase, and Telegram temp replacement callbacks call `order_purchase_service` for provider reservation and refund-on-provider-failure handling.
  - `order_service.py` still owns quote resolution, order creation, idempotency, and customer webhook enqueueing.
  - `order_lifecycle_service.py` now owns the API/Mini App order lifecycle for temp/voice/rental creation: charge, provider provisioning, expected provider-failure propagation, and unexpected post-charge rollback.
  - `order_charge_service.py` owns wallet charge + charge-failure status/event handling for API/Mini App order creation, API/Mini App temp resend, Telegram temp/voice/rental purchase/replacement callbacks, and Telegram second-code resend.
  - `shared/temp_second_code.py` accepts an injected `charge_order_fn`, so resend keeps provider-resend-specific behavior while sharing wallet charge/failure handling.
  - Telegram code keeps state validation, chat edits, localized messages, and waiter startup at the edge.
  - Next backend cleanup should focus on either Telegram wrapper simplification or live webhook/provider behavior verification before attempting a larger transaction-style orchestration layer.
- Rental protection flow now reuses a shared backend service:
  - `services/numbers/order_rental_protection_service.py` owns rental SMS snapshot checks, provider close/cancel, no-SMS auto-refund, guard scheduling, and the restart/global sweep.
  - Telegram `core_numbers_buy.py` keeps thin wrappers for callback UX and tests, but delegates protection decisions to the shared service.
  - Mini App legacy rental guard/cancel helpers now delegate to the same service instead of carrying a second copy of provider close/refund logic.
  - Versioned rental order creation schedules the shared guard when a safe refund cutoff exists.
- Mini App shared-service cleanup:
  - removed unreachable provider-direct fallback branches from rental action routes after the early shared-service response;
  - removed the unused Mini App manual cancel route implementation entirely; `/mini/numbers/api/orders/{order_id}/cancel` is not registered.
  - removed unused Mini App frontend `cancel/refund` copy keys so no dead manual-refund affordance remains in the UI bundle.
  - removed the unused Mini App-only rental notes/tags sync helper after notes/tags moved behind `order_rental_service`.
- Mini App order payload cleanup:
  - `_order_payload(...)` now starts from `order_service.public_order_payload(...)` so public status, refund payload, provider obfuscation, action flags, and cost-hiding stay aligned with the versioned API.
  - Mini App-specific shaping is limited to UI labels/details, local recording URL, refresh flags, and second-code display fields.
- Mini App voice refresh cleanup:
  - `/mini/numbers/api/orders/{order_id}/refresh` now calls `order_refresh_service.refresh_number_order(...)` for every order mode.
  - removed Mini App provider polling for voice call/recording checks from refresh.
  - `/mini/numbers/api/orders/{order_id}/recording` downloads only already-stored recording URIs through `order_recording_service`; it no longer polls provider call status before download.
- Telegram voice recording cleanup:
  - Telegram voice recording file sending now uses `order_recording_service` for provider payload parsing, validation, provider download, and filename selection instead of keeping duplicate provider logic in `core_numbers_buy.py`.
- Telegram voice call check cleanup:
  - `core_numbers_buy.py` now calls `order_voice_service.voice_call_recording_state(...)` for provider call reads and recording URI extraction.
  - The polling wait loop remains Telegram-only for push-notification UX until a live Telegram smoke test and provider webhook/call event path replaces it.

Current versioned Numbers API coverage:
- Account/wallet:
  - `GET /api/v1/numbers/account`
- Catalog/quotes:
  - `GET /api/v1/numbers/catalog/bootstrap`
  - `GET /api/v1/numbers/quotes?mode=temp...`
  - `GET /api/v1/numbers/quotes?mode=rental...`
  - `GET /api/v1/numbers/quotes?mode=voice...`
- Orders:
  - `GET /api/v1/numbers/orders`
  - `GET /api/v1/numbers/orders/{order_id}`
  - `POST /api/v1/numbers/orders` for temp, rental, and voice quote tokens
  - `POST /api/v1/numbers/orders/{order_id}/refresh` for temp/rental/voice state
  - `POST /api/v1/numbers/orders/{order_id}/resend` for temp second-code
  - `POST /api/v1/numbers/orders/{order_id}/replace`
  - `POST /api/v1/numbers/orders/{order_id}/alternate`
  - `GET /api/v1/numbers/orders/{order_id}/recording` for voice recordings
  - `POST /api/v1/numbers/orders/{order_id}/rental/sms`
  - `POST /api/v1/numbers/orders/{order_id}/rental/finish`
  - `POST /api/v1/numbers/orders/{order_id}/rental/renew`
  - `POST /api/v1/numbers/orders/{order_id}/rental/wake`
  - `POST /api/v1/numbers/orders/{order_id}/rental/notes`
- Webhooks/API keys:
  - customer webhook management under `/api/v1/webhooks`
  - provider inbound webhooks under `/api/v1/provider-webhooks/{provider}`
  - customer API key management under `/api/v1/api-keys`
- Support/review:
  - refund review list/resolve endpoints
  - provider webhook audit list/replay endpoints

Numbers provider decisions:
- Provider real names should not be shown to end users unless explicitly approved.
- Customer-facing payloads and quote tokens must expose `provider_id` plus obfuscated display names only, never internal provider codes.
- Quote tokens are signed but not encrypted, so token payloads must also avoid real/internal provider names.
- Customer-facing order payloads must not expose internal cost fields (`base_price`, `base_price_label`) or raw provider refund/debug reasons.
- Rental quote/order payloads must not expose provider raw option metadata or internal provider names; quote token payloads remain signed-only, so use public `provider_id`.
- Versioned refresh endpoints should stay webhook-first. Do not add provider polling for rental/voice refresh unless explicitly re-approved.
- Versioned rental SMS endpoints should stay webhook-first/state-read only. Do not add provider SMS polling there; provider delivery should arrive through provider webhooks and stored order state.
- Account/wallet activity payloads must classify ledger reasons into public `kind`/`label` values and must not expose raw ledger metadata or provider/debug internals.
- `nonvoip` and `nonvoip_s6` display as `Golf` and `Hotel`.
- Newly added providers are internally named:
  - `smsready`
  - `pvapins`
- Their user-facing display names are obfuscated:
  - `smsready` -> `India`
  - `pvapins` -> `Juliet`
- Internal provider names, env vars, logs, tests, and class names may keep real/internal names for maintainability.

Provider credentials:
- Never commit provider keys or API secrets.
- Use environment variables/settings only.
- Relevant settings currently include:
  - `NONVOIP_KEY`
  - `NONVOIP_EMAIL`
  - `NONVOIP_BASE_URL`
  - `SMSREADY_KEY`
  - `SMSREADY_BASE_URL`
  - `PVAPINS_KEY`
  - `PVAPINS_BASE_URL`

## Current Domain Work

New domain:
- `phantom-app.net`

Current goal:
- It has or will have a simple landing page.
- Future direction is a complete web dashboard, but only after the backend/API is clean.

## Recommended Next Steps

Continue Numbers API/webhook consolidation and provider exposure hardening.

Goals:
- Keep provider real names hidden from all customer-facing API/Mini App surfaces.
- Review any remaining customer API payloads for internal identifiers, costs, provider errors, or debug fields.
- Create or formalize stable internal API endpoints for numbers workflows.
- Telegram Mini App should consume these APIs or shared service handlers instead of duplicating business flow logic.

Suggested API areas:
- Account/wallet:
  - user profile
  - balance
  - ledger entries
- Numbers catalog:
  - services
  - countries/states
  - temp price quotes
  - rental price quotes (implemented for versioned API)
  - voice price quotes (implemented for versioned API)
- Orders:
  - create temp order (implemented for versioned API)
  - create rental order (implemented for versioned API)
  - create voice order (implemented for versioned API)
  - refresh status without provider polling (implemented for temp/rental/voice)
  - server-managed timeout refund (implemented for temp refresh path)
  - resend/second-code (implemented for temp)
  - replacement/alternate provider (implemented for versioned API)
  - rental finish/renew/wake/notes (implemented for versioned API)
- Mini App API consolidation:
  - continue removing Mini App-only duplicate business logic after each workflow has a stable shared service
  - next cleanup should target the remaining Mini App-only UI wrappers and Telegram wrapper seams only after each route has a stable shared service and tests
  - keep recharge/support chat workflows in Telegram unless native proof/reply handling is designed
- Admin:
  - provider health
  - provider balances
  - failed orders
  - manual refunds
  - user/order lookup

Implementation preference:
- Reuse existing business logic in `services/numbers/miniapp.py`, `services/numbers/manager.py`, and shared modules.
- Avoid creating duplicate purchase/refund logic.
- Extract shared service functions first where needed, then expose HTTP endpoints.

## Important Existing Files

Numbers:
- `services/numbers/miniapp.py`
- `services/numbers/manager.py`
- `services/numbers/api.py`
- `services/numbers/api_payloads.py`
- `services/numbers/order_service.py`
- `services/numbers/order_refresh_service.py`
- `services/numbers/order_resend_service.py`
- `services/numbers/order_lifecycle_service.py`
- `services/numbers/order_rental_service.py`
- `services/numbers/order_charge_service.py`
- `services/numbers/order_purchase_service.py`
- `services/numbers/order_recording_service.py`
- `services/numbers/order_voice_service.py`
- `services/numbers/provider_factory.py`
- `services/numbers/providers/`
- `services/numbers/shared/`
- `services/numbers/keyboards/core_numbers_kb.py`

Provider alias/display:
- `utils/provider_alias.py`

Provider docs/runtime matrix:
- `docs/providers/runtime_provider_matrix.md`
- `scripts/provider_matrix_report.py`

Migration/context docs:
- `docs/platform/API_FIRST_PRODUCT_STRATEGY.md`
- `docs/numbers/MINIAPP_MIGRATION_CHECKLIST.md`
- `docs/numbers/TELEGRAM_FLOW_AUDIT.md`
- `docs/numbers/API_CONTRACT.md`
- `docs/numbers/PROVIDER_DELIVERY_MATRIX.md`
- `docs/PROJECT_CONTEXT.md`

## How To Use This File In Future Requests

In a new Codex request, write:

```text
Read docs/AGENT_HANDOFF_CONTEXT.md first and use it as the project context.
Continue from the API-first platform step.
```

If the UI supports file mentions, mention:

```text
[@docs/AGENT_HANDOFF_CONTEXT.md] Read this before starting.
```

If the session is outside this repo, paste only the relevant sections from this file, not the whole old conversation.

Token-saving rule:
- Prefer referencing this file by path instead of pasting it when working in the same repo.
- If starting a fresh chat outside the repo, paste only `Current Repo State Summary`, `Latest completed work`, and `Recommended Next Steps`.
- Do not attach old full conversations, provider HTML pages, or large docs unless the task specifically needs them.
- For narrow tasks, ask Codex to read only the files named in this handoff plus the files directly touched by the task.

## Notes For Future Agents

- User prefers Arabic conversation.
- Be direct and pragmatic.
- Do not reveal real provider names in user-facing UI.
- Do not commit runtime data files unless explicitly requested.
- Run targeted tests after provider/UI changes.
- Run full `pytest` before pushes when touching shared numbers logic.
- Live provider webhook verification is still separate from local tests.
