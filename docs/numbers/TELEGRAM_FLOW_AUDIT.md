# Numbers Telegram Flow Audit

Last updated: 2026-05-25

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
- `services/numbers/order_service.py`, `order_refresh_service.py`, `order_resend_service.py`
  - API-first temporary order creation, webhook-first refresh, public order payload, and resend orchestration.
- `services/numbers/provider_webhooks.py`, `provider_webhook_service.py`, `provider_webhook_normalizer.py`
  - Provider inbound webhook routes, generic payload normalization, temp/rental order updates, audit logging, and customer webhook enqueueing.
- `services/platform/webhooks.py`, `webhooks_api.py`, `webhook_delivery.py`
  - Customer-facing webhook registration, signing, delivery queue, and worker.

## Telegram-Only Candidates

These should be treated as customer Telegram UI/state handlers until proven otherwise:

- `services/numbers/handlers/core_numbers.py`
  - Telegram selection screens, callback handlers, inline buttons, and FSM transitions.
- `services/numbers/handlers/core_numbers_buy.py`
  - Telegram purchase screens and callback actions.
  - Warning: this file still contains logic duplicated or partially shared with the Mini App. Do not delete until the shared pieces are moved out and tests point to the shared modules.
- `services/numbers/handlers/numbers_inline.py`
  - Telegram inline search UI.
  - Search ranking behavior may still be useful as a reference for Mini App selector parity.
- `services/numbers/keyboards/core_numbers_kb.py`
  - Telegram keyboard construction.
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
- [x] Mini App has a backend route for service-specific country suggestions previously only available in the Telegram country flow.
- [x] Mini App active orders include recent backend order events for refund/check timelines.
- [x] Mini App exposes eligible rental cancel/refund instead of keeping the backend route hidden.
- [x] Extract duplicated temp/call refund service logic out of `core_numbers_buy.py`.
- [x] Extract duplicated temp second-code service logic out of `core_numbers_buy.py`.
- [x] Add API-level temp resend service and route.
- [x] Add provider inbound webhook routes for SMSReady, PVADeals, and generic provider callbacks.
- [x] Make provider webhook processing update temp and rental orders.
- [x] Gate legacy provider SMS polling behind `numbers_provider_sms_polling_enabled`.
- [x] Mini App active orders no longer poll rental/voice providers on page load.
- [x] Telegram recovery/rental SMS paths respect the global polling gate.
- [x] Temp replacement is covered in Mini App backend tests, including current-provider retry and alternate-provider retry.
- [x] Alternate-provider retry selection uses the shared Telegram scoring logic in the Mini App.
- [~] Extract duplicated temp replacement service logic out of `core_numbers_buy.py`.
  - Shared extraction now covers replacement order field resolution and alternate-provider scoring.
  - Remaining reason: Telegram replacement still edits the chat message and queues the Telegram waiter against the same message. Keep this as a wrapper until a live Telegram smoke test confirms an extracted shared service preserves that UX.

## Hard Stop Before Deletion

Before deleting any Telegram Numbers file:

- `rg "services\\.numbers\\.handlers\\.<module>"` must show no Mini App/backend imports.
- Existing Telegram tests that still cover fallback behavior must either pass against wrappers or be intentionally removed with a documented replacement.
- Mini App backend tests must cover the behavior that used to live in the deleted module.
- Railway/Telegram live smoke test must pass after deploy.
- Provider webhook callbacks must be verified live for active providers before deleting legacy polling/recovery code entirely.
