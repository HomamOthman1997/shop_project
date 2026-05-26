# Numbers Docs

Numbers is the first API-first consolidation target.

## Active Docs

- `API_CONTRACT.md`: draft versioned Numbers API contract.
- `MINIAPP_MIGRATION_CHECKLIST.md`: current Telegram-to-Mini-App migration status.
- `TELEGRAM_FLOW_AUDIT.md`: what Telegram code can and cannot be deleted yet.
- `MINIAPP_VISUAL_QA.md`: manual visual QA checklist after deployments.
- `PROVIDER_DELIVERY_MATRIX.md`: provider webhook delivery/cutover status.
- `PROVIDER_TIMEOUT_RETRY_MATRIX.md`: provider timeout and retry policy.
- `providers/README.md`: local upstream API reference for every active Numbers provider.

## Current Direction

- The Numbers customer ordering surface is the Telegram Mini App, not Telegram reply-keyboard flows.
- Telegram customer buttons for Numbers are limited to inline Mini App/account/top-up/support entry points; first-run language and subscription checks remain intact.
- Legacy Telegram number-flow callbacks are guarded on the real Numbers bot and return customers to the Mini App entry unless an explicit `numbers_telegram_order_flow_enabled=True` / `NUMBERS_TELEGRAM_ORDER_FLOW_ENABLED=true` override is configured.
- The legacy `number_type_kb(...)` only renders temp/rental/voice Telegram buttons when that override is enabled.
- Keep Telegram notifications and support/account chat-thread workflows where they still fit.
- Move reusable purchase/refund/replacement/rental behavior into shared backend services before exposing or reusing it from clients.
- Expose stable APIs that can power the Mini App, future web dashboard, and customer-built bots.
- Never expose real provider names to customers unless the view is explicitly admin-only.
- Prefer provider webhooks for inbound SMS/code delivery. Provider polling is disabled by default and should only be re-enabled as a documented provider-level exception.
- Current polling-only provider exceptions are `pvapins`, `vaksms`, and `smspool`; these accounts do not support provider webhooks and must use provider SMS polling without turning global polling back on for every provider.
- Keep customer refund UX server-managed: the backend handles timeout checks, provider cancellation, wallet refund, and support-review escalation.

## Current Numbers API State

- Versioned base path: `/api/v1/numbers`.
- Mini App path: `/mini/numbers/api`.
- Customer API key scopes now include quotes, account read, order read/create/refresh/resend/rental-actions, webhook management, and API key management.
- Versioned API supports bootstrap/catalog metadata, country suggestions, temporary quotes/orders, rental quotes/orders, voice quotes/orders, replacement/alternate-provider retry, rental actions, webhook-first refresh, explicit polling-only provider exceptions, temp resend, account/wallet snapshot, customer webhooks, provider inbound webhooks, and support-review endpoints.
- Versioned API bootstrap now includes `api.capabilities` and `api.actions`, a global endpoint/scope discovery catalog for customer-built bots and partner clients. It exposes only versioned API URLs and disabled submit reasons; Mini App URLs stay out of the public API catalog.
- Versioned API now exposes `GET /api/v1/numbers/docs`, a self-hosted human-readable API reference generated from the runtime OpenAPI schema and action catalog. This is the preferred quick reference for customer-built bots and partner clients.
- Versioned API now exposes `GET /api/v1/numbers/openapi.json`, generated from the same API discovery catalog, so external bots can inspect paths, scopes, auth, and idempotency requirements without reading Mini App internals.
- Versioned API now exposes read-only recharge/support discovery (`GET /api/v1/numbers/recharge`, `GET /api/v1/numbers/support`) with explicit disabled submit actions. These discovery payloads and the Mini App recharge/support forms share `services/numbers/customer_flows.py`; recharge proof submission and support ticket creation remain Mini App-only until their review/reply flows no longer depend on Telegram.
- `order_purchase_service` owns provider reservation and provider-failure refund handling for API/Mini App order creation, Telegram temp/voice/rental purchase callbacks, and Telegram temp replacement callbacks.
- API/Mini App temp/voice/rental order creation now runs money movement through `order_lifecycle_service`: charge, provider provisioning, expected provider-failure propagation, and unexpected post-charge rollback are one shared transaction-style path.
- Voice order listing/refresh, quote/create, and recording download are versioned.
- Voice recording provider-payload parsing, validation, download, and filename handling are centralized in `order_recording_service`; API, Mini App, and Telegram wrappers only handle auth/ownership, localization, Telegram sending, and response headers.
- Telegram voice call checking uses `order_voice_service` for provider call reads and recording URI extraction. The remaining call polling loop is a Telegram notification wrapper only and must not be copied into API or Mini App refresh routes.
- Mini App order refresh now calls the same shared refresh service for temp, rental, and voice orders; voice/rental refresh is state-read/webhook-first and does not poll upstream providers.
- Replacement and alternate-provider retry now have versioned endpoints with explicit scope, rate limit, and idempotency requirements.
- Mini App replacement and alternate-provider actions now call the shared replacement backend service and keep UI-specific Telegram auth/order payload formatting at the edge.
- Mini App temp/rental/voice purchase uses shared API quote tokens and `create_number_order_from_quote(...)`; legacy/non-API Mini App quote tokens are rejected, and the old direct provider purchase helpers were removed from the Mini App layer.
- Mini App temp/rental/voice price rows expose `purchase_action`; the frontend buys through that action contract and keeps direct `quote_token` use only as fallback compatibility.
- Mini App country suggestions and `/api/v1/numbers/country-suggestions` now share `country_suggestions_service`, so customer API clients and the Mini App use one cache/ranking path.
- Mini App rental SMS/finish/renew/wake/notes actions call `order_rental_service` and keep only Telegram auth plus UI payload formatting in the Mini App layer.
- Telegram rental SMS/finish/renew/wake/notes callbacks also call `order_rental_service`; Telegram keeps callback UX, localized messages, and the Hero no-SMS safety pre-check only.
- Temp replacement/alternate-provider creation is centralized in `order_service.request_replacement_order(...)` for API, Mini App, and Telegram. Telegram now passes `source=numbers_telegram` and wait-message metadata into the service instead of creating/charging/provisioning replacement orders directly.
- Telegram temp/voice/rental purchase and temp replacement callbacks now call `order_purchase_service` for provider reservation/refund-on-provider-failure; Telegram keeps only charge trigger state, chat edits, localized messages, and waiter startup.
- `order_service.py` now owns quote resolution, order creation, idempotency, and customer webhook enqueueing. Money-moving order lifecycle is delegated to `order_lifecycle_service`, wallet charging is delegated to `order_charge_service`, and provider reservation is delegated to `order_purchase_service`.
- `order_charge_service` owns wallet charge + charge-failure status/event handling for API/Mini App temp/voice/rental order creation, API/Mini App temp resend, Telegram temp/voice/rental purchase/replacement callbacks, and Telegram second-code resend.
- `shared/temp_second_code.py` accepts a `charge_order_fn` callback so resend keeps provider-resend-specific semantics while sharing wallet charge/failure handling.
- Rental action services record an explicit client source: `numbers_api`, `numbers_miniapp`, or `numbers_telegram`.
- Mini App order card payloads now start from the versioned API public order payload and add only UI-specific labels/details, Mini App recording links, refresh flags, and second-code display fields.
- Mini App navigation and global screen calls are backend-driven through the bootstrap `client.tabs` and `client.actions` contract. The frontend renders buy/orders/recharge/account/support tabs from that payload and uses action endpoint/method values for country suggestions, account, orders, prices, purchase, recharge, support, language switching, recharge submission, and support ticket submission.
- Public API order payloads now include `api_actions`, a versioned API action discovery contract for customer bots and partner clients. These actions expose only `/api/v1/numbers/...` endpoints, required scopes, disabled reasons, and `requires_idempotency_key`; they are separate from Mini App `actions`.
- Mini App order card buttons are server-driven through the order payload `actions` object. The backend owns enabled state, endpoint, method, translation key, confirmation/busy/success labels, and idempotency key for copy, refresh, second-code, replacement, alternate-provider, recording, and rental controls; the frontend renders and executes controls through that contract. It no longer synthesizes `/mini/numbers/api/orders/{id}/...` paths or action idempotency keys locally; `can_*` logic is only a render fallback for older payloads and is not an execution contract.
- Recharge and support customer workflows now have a shared service layer in `customer_flows.py`: payment-method normalization, recharge request creation/review delivery metadata, support category normalization, and support ticket creation/delivery are outside `miniapp.py`. Mini App routes keep Telegram `initData`, multipart parsing, and response shaping only; the public API keeps submit actions disabled but reads the same discovery data.
- Rental no-SMS protection is centralized in `order_rental_protection_service`: provider close/cancel, auto-refund, guard scheduling, and restart sweeps are shared by Telegram, Mini App compatibility paths, and versioned API rental creation.
- Manual customer cancel/refund is intentionally absent from the Mini App: the cancel route is not registered, the old route implementation was removed, and the UI bundle no longer carries unused cancel/refund button copy.
- Provider inbound callbacks use `https://phantom-app.net/api/v1/provider-webhooks/{provider}?token=<provider-webhook-token>` for webhook-capable providers. `pvapins`, `vaksms`, and `smspool` are polling-only exceptions and are not expected to call this route.
- Customer-facing webhooks support order creation, SMS/code received, resend requested, and refund events.
