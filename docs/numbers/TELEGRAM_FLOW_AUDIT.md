# Numbers Telegram Flow Audit

Last updated: 2026-05-26

Purpose: prevent deleting backend logic that the Numbers Mini App still needs while we gradually retire Telegram-only customer UI.

## Current Rule

Do not delete `services/numbers/handlers/*` as a folder. Some files contain real shared backend behavior, not only Telegram callbacks.

## Shared Backend Logic

These parts are used by the Mini App and must stay available:

- `services/numbers/shared/temp_order.py`
  - Temporary-number timing, timeout, resend warranty, SMS code extraction, retry classification, and active-order checks.
  - Transitional source: `services/numbers/handlers/temp_order_utils.py`.
- `services/numbers/shared/provider_io.py`
  - Provider resend adapter and gated legacy SMS polling fallback.
  - Default code-delivery behavior is webhook-first. Polling is disabled unless `numbers_provider_sms_polling_enabled` is explicitly enabled.
  - Source of truth. `services/numbers/handlers/temp_provider_io.py` is now a compatibility wrapper.
- `services/numbers/shared/rental_policy.py`
  - Rental refund windows, safe cutoff, and no-SMS policy.
  - Source of truth. `services/numbers/handlers/rental_policy_utils.py` is now a compatibility wrapper.
- `services/numbers/shared/events.py`
  - Number order event logging, temp stats logging, and rental event logging.
  - Source of truth. `services/numbers/handlers/event_logging.py` is now a compatibility wrapper.
- `services/numbers/shared/temp_refund.py`
  - Temporary/call-number provider cancel, terminal provider-state classification, wallet refund finalization, and retryability decisions.
  - Used by both the Telegram flow and the Mini App.
- `services/numbers/shared/temp_second_code.py`
  - Temporary-number second-code provider resend, second-order charging, state update, and event logging.
  - Used by both the Telegram flow and the Mini App.
- `services/numbers/shared/temp_replacement.py`
  - Shared alternate-provider retry scoring and selection.
  - Used by both the Telegram flow and the Mini App.
- `services/numbers/order_service.py`, `order_refresh_service.py`, `order_resend_service.py`, `order_rental_service.py`
  - API-first temp/rental/voice order creation, webhook-first refresh, public order payloads, resend orchestration, replacement/alternate-provider retry, and rental actions.
  - Mini App purchase, replacement, alternate-provider retry, rental actions, and order-card public payloads call these services instead of Mini App-only provider logic.
  - Telegram rental SMS/finish/renew/wake/notes callbacks also call `order_rental_service`; callback handlers should not call rental provider adapters directly.
- `services/numbers/order_lifecycle_service.py`
  - Shared API/Mini App order lifecycle for temp/voice/rental creation: charge, provider provisioning, expected provider-failure propagation, and unexpected post-charge rollback.
  - Keeps quote/idempotency/customer-webhook concerns in `order_service.py` while isolating money-moving transaction semantics.
- `services/numbers/order_purchase_service.py`
  - Shared provider reservation and provider-failure refund handling for API/Mini App order creation, Telegram temp/voice/rental purchase callbacks, and Telegram temp replacement callbacks.
  - API routes, Mini App wrappers, and Telegram handlers should call this service instead of provider purchase adapters directly.
- `services/numbers/order_charge_service.py`
  - Shared wallet charge and charge-failure status/event handling for API/Mini App order creation, API/Mini App temp resend, Telegram temp/voice/rental purchase/replacement callbacks, and Telegram second-code resend.
  - Resend keeps provider-resend-specific behavior in `shared/temp_second_code.py` through an injected charge callback.
- `services/numbers/order_recording_service.py`
  - Shared voice recording provider-payload parsing, validation, provider download, and safe attachment filename selection.
  - API, Mini App, and Telegram recording download/send wrappers should use this service instead of calling providers directly.
- `services/numbers/order_voice_service.py`
  - Shared voice call provider read and recording URI extraction.
  - Telegram voice waiter/manual check wraps this service for chat-notification UX; API and Mini App refresh must stay state-read/webhook-first.
- `services/numbers/order_rental_protection_service.py`
  - Shared rental no-SMS protection service for provider close/cancel, provider-aware wallet refund, background guard scheduling, and restart/global sweep.
  - Telegram handlers and Mini App compatibility helpers should wrap this service instead of duplicating rental cancel/refund logic.
- `services/numbers/provider_webhooks.py`, `provider_webhook_service.py`, `provider_webhook_normalizer.py`
  - Provider inbound webhook routes, generic payload normalization, temp/rental order updates, audit logging, and customer webhook enqueueing.
- `services/platform/webhooks.py`, `webhooks_api.py`, `webhook_delivery.py`
  - Customer-facing webhook registration, signing, delivery queue, and worker.

## Telegram-Only Candidates

These should be treated as customer Telegram UI/state handlers until proven otherwise:

- `services/numbers/handlers/core_numbers.py`
  - Telegram selection screens, callback handlers, inline buttons, and FSM transitions.
  - `/start`, first-run language selection, and legacy cancel/back paths no longer route customers into this flow on the Numbers bot; they show the Mini App inline entry menu instead.
  - Stale `flow:type:*`, rental add/menu, and country-entry back callbacks are guarded for the real Numbers bot and return the Mini App entry unless the explicit `numbers_telegram_order_flow_enabled=True` override is set.
- `services/numbers/handlers/core_numbers_buy.py`
  - Telegram purchase screens and callback actions.
  - Rental protection wrappers now delegate to `order_rental_protection_service`; keep the wrappers while Telegram callback tests and UX are still active.
  - Empty "My numbers" no longer exposes a Telegram add-number action; it links back to the Mini App entry when configured.
- `services/numbers/handlers/numbers_inline.py`
  - Telegram inline search UI.
  - Search ranking behavior may still be useful as a reference for Mini App selector parity.
- `services/numbers/keyboards/core_numbers_kb.py`
  - Telegram keyboard construction.
  - `number_type_kb(...)` no longer renders temp/rental/voice customer order buttons by default; it requires `numbers_telegram_order_flow_enabled=True`.
- `services/numbers/states/core_numbers_states.py`
  - Telegram FSM states.
- `services/numbers/handlers/temp_waiter_runtime.py`
  - Runtime waiter orchestration for Telegram notifications.
  - Keep while Telegram push notifications remain in use.
- `services/numbers/handlers/recovery_runtime.py`
  - Recovery loop orchestration.
  - Keep while Telegram notifications and recovery sweeps remain active. It now respects webhook-first delivery and skips provider SMS polling when polling is disabled.

## Safe Migration Order

1. Make Mini App imports use `services.numbers.shared.*`, never `services.numbers.handlers.*`.
2. Move implementation from transitional handler files into `services/numbers/shared/*`.
3. Leave handler modules as compatibility wrappers for Telegram tests and callbacks.
4. Move duplicated refund/replacement/second-code logic from `core_numbers_buy.py` into shared service modules.
5. After tests and live Mini App verification pass, delete only pure Telegram UI modules that have no shared imports.

## Progress

- [x] Mini App imports no longer point at `services.numbers.handlers.*`.
- [x] Provider SMS/resend helper implementation moved to `services/numbers/shared/provider_io.py`.
- [x] Rental policy implementation moved to `services/numbers/shared/rental_policy.py`.
- [x] Event logging implementation moved to `services/numbers/shared/events.py`.
- [x] `core_numbers_buy.py` imports those shared modules directly.
- [x] Move `temp_order_utils.py` implementation into `services/numbers/shared/temp_order.py`.
- [x] Move rental no-SMS protection/cancel/refund/guard/sweep logic into `services/numbers/order_rental_protection_service.py`.
- [x] Mini App has a backend route for service-specific country suggestions previously only available in the Telegram country flow.
- [x] Mini App active orders include recent backend order events for refund/check timelines.
- [x] Mini App keeps rental refund protection server-managed and does not advertise a manual cancel action.
- [x] Extract duplicated temp/call refund service logic out of `core_numbers_buy.py`.
- [x] Extract duplicated temp second-code service logic out of `core_numbers_buy.py`.
- [x] Add API-level temp resend service and route.
- [x] Add provider inbound webhook routes for SMSReady, PVADeals, and generic provider callbacks.
- [x] Make provider webhook processing update temp and rental orders.
- [x] Gate legacy provider SMS polling behind `numbers_provider_sms_polling_enabled`.
- [x] Mini App active orders no longer poll rental/voice providers on page load.
- [x] Mini App frontend no longer schedules an order auto-poll timer; status changes are refresh/open/webhook-state driven.
- [x] Numbers bot `/start`, post-language selection, and legacy cancel/back exits no longer open Telegram number-type selection; they clear ReplyKeyboard and show an inline Mini App/account/top-up/support menu.
- [x] Numbers bot top-up entry and payment method navigation use inline callbacks instead of reply-keyboard buttons.
- [x] Guard stale Numbers Telegram order callbacks so old inline messages cannot restart the customer order flow on the real Numbers bot.
- [x] Make `NUMBERS_TELEGRAM_ORDER_FLOW_ENABLED=false` an explicit config/default and require it before rendering legacy temp/rental/voice Telegram order buttons.
- [x] Remove Telegram "add number" from empty My Numbers and offer the Mini App entry instead.
- [x] Mini App manual refresh now delegates to `order_refresh_service.refresh_number_order(...)` for temp/rental/voice.
- [x] Mini App voice refresh no longer polls provider call status; recording availability is state/webhook driven.
- [x] API, Mini App, and Telegram voice recording parsing/downloads/sends use `order_recording_service`; wrappers no longer duplicate provider payload parsing, provider download, or filename logic.
- [x] Telegram voice waiter/manual check uses `order_voice_service` for provider call reads and recording URI extraction.
- [x] Telegram recovery/rental SMS paths respect the global polling gate.
- [x] Mini App temp/rental/voice purchase uses shared API quote tokens and shared order creation where possible.
- [x] Mini App purchase rejects legacy quote tokens instead of falling back to Mini App-only provider purchase helpers.
- [x] Old Mini App-only quote signing/resolution and provider-direct purchase helpers were deleted from `services/numbers/miniapp.py`.
- [x] Temp replacement is covered in Mini App route tests through the shared replacement service wrapper.
- [x] Mini App replacement and alternate-provider retry call the shared Numbers order service with idempotency keys.
- [x] Alternate-provider retry selection uses shared scoring logic through the shared order service.
- [x] Mini App order-card payloads now build from `order_service.public_order_payload(...)` and keep only UI-specific shaping in `miniapp.py`.
- [x] Mini App rental SMS/finish/renew/wake/notes call `order_rental_service`.
- [x] Telegram rental SMS/finish/renew/wake/notes callbacks call `order_rental_service`; provider-direct rental action logic no longer lives in `core_numbers_buy.py`.
- [x] Rental action wrappers pass explicit client source values (`numbers_api`, `numbers_miniapp`, `numbers_telegram`) into `order_rental_service` for cleaner order history/debugging.
- [x] Remove unreachable Mini App provider-direct rental action and manual cancel branches after shared-service consolidation.
- [x] Remove the unused Mini App manual cancel route implementation and frontend cancel/refund copy; customer refunds remain server-managed.
- [x] Move API/Mini App and Telegram purchase callbacks behind a shared provider provisioning service.
  - Done for Mini App purchase: temp/rental/voice use signed API quote tokens and shared order creation.
  - Done for Telegram rental follow-up actions: SMS/finish/renew/wake/notes use `order_rental_service`.
  - Done for Telegram purchase callbacks: temp/voice/rental provider reservation now goes through `order_purchase_service`; `core_numbers_buy.py` keeps charge orchestration, chat edits, localized messages, and waiter startup only.
  - Done for API/Mini App order creation: `order_service.py` delegates temp/voice/rental provider reservation to `order_purchase_service`.
  - Done for API/Mini App order creation, API/Mini App resend, Telegram purchase callbacks, Telegram replacement callbacks through `order_service.request_replacement_order(...)`, and Telegram second-code resend: wallet charge failures use `order_charge_service.charge_order_or_raise(...)`.
  - Done for API/Mini App order creation: temp/voice/rental use `order_lifecycle_service.execute_order_provisioning_transaction(...)` for charge + provision + unexpected rollback.
  - Remaining future cleanup: after live provider behavior is verified, consider reusing the lifecycle wrapper from Telegram purchase callbacks only if it simplifies the UI wrappers without hiding Telegram-specific waiter/chat behavior.
- [x] Extract duplicated temp replacement service logic out of `core_numbers_buy.py`.
  - Shared extraction now covers replacement order field resolution, alternate-provider scoring, API/Mini App replacement order creation, and Telegram replacement order creation.
  - Telegram replacement passes `source=numbers_telegram` and wait-message metadata to `order_service.request_replacement_order(...)`; the handler keeps only source-order refund precheck, trust gate for same-provider retry, chat editing, and waiter queueing.

## Hard Stop Before Deletion

Before deleting any Telegram Numbers file:

- `rg "services\\.numbers\\.handlers\\.<module>"` must show no Mini App/backend imports.
- Existing Telegram tests that still cover fallback behavior must either pass against wrappers or be intentionally removed with a documented replacement.
- Mini App backend tests must cover the behavior that used to live in the deleted module.
- Railway/Telegram live smoke test must pass after deploy.
- Provider webhook callbacks must be verified live for active providers before deleting legacy polling/recovery code entirely.
