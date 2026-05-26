# Numbers Provider Delivery Matrix

Status: draft  
Last updated: 2026-05-26

Goal: classify how each upstream Numbers provider delivers inbound OTP/SMS so the backend can run webhook-first without guessing provider payloads.

Live provider testing is tracked in `docs/numbers/LIVE_PROVIDER_VERIFICATION.md`.

## Policy

- New backend behavior is webhook-first: `numbers_provider_sms_polling_enabled=false` by default and refresh does not poll providers when the order is marked as webhook delivery.
- Provider dashboard URLs should point to `https://phantom-app.net/api/v1/provider-webhooks/{provider}?token=<provider-webhook-token>`.
- Providers with confirmed bespoke payloads keep named routes (`smsready`, `pvadeals`); other providers use the generic `{provider}` route until a bespoke parser is justified.
- If a provider cannot be configured to send webhooks, either disable that provider for code-receiving products or explicitly re-enable polling for that provider/system after documenting the exception.
- Customer-facing webhooks are separate from provider inbound webhooks:
  - Provider inbound webhook: provider -> Phantom backend.
  - Customer webhook: Phantom backend -> customer bot/system.

## Current Classification

| Provider code | Legacy polling adapter | Webhook support evidence | Inbound handler implemented | Classification | Next action |
| --- | --- | --- | --- | --- | --- |
| `smsready` | Exists, but no longer used for default refresh | Confirmed from supplied SMSReady docs: `new_sms` webhook with `order_id`, `number`, `code`, `full_sms` | Yes: `/api/v1/provider-webhooks/smsready` | Webhook confirmed and implemented; local live API check blocked by network failure | Retry from Railway, configure dashboard webhook URL and token |
| `pvadeals` | Exists, but no longer used for default refresh | Confirmed in official docs: `sms_received`, `number_purchased`, `number_flagged` webhooks | Yes: `/api/v1/provider-webhooks/pvadeals` | Webhook confirmed and implemented; live order/cancel path verified, real SMS callback pending | Configure dashboard webhook URL and token |
| `herosms` | Exists, but no longer used for default refresh | Confirmed from supplied HeroSMS docs: incoming SMS webhook posts `activationId`, `service`, `text`, `code`, `country`, `receivedAt` | Generic route: `/api/v1/provider-webhooks/herosms` | Webhook confirmed and parser-compatible; live low-cost attempt returned `NO_NUMBERS` | Configure provider callback, then verify real `provider_webhook_events` |
| `pvapins` | Exists, but no longer used for default refresh | Not confirmed from supplied PVAPins page; docs emphasize polling `get_sms.php`; latest rent request docs use `get_number.php` with `is_rent=1` | Generic route: `/api/v1/provider-webhooks/pvapins` | Public docs look polling-only; provider should be disabled/quarantined unless support confirms callbacks | Ask support or find account dashboard webhook settings |
| `vaksms` | Exists, but no longer used for default refresh | Reviewed official V0/V1/V2 docs: no webhook/callback; SMS delivery uses `getStatus`, `getSmsCode`, `/user/check/{id}`, or rental inbox reads | Generic route: `/api/v1/provider-webhooks/vaksms` | Public docs look polling-only; provider should be disabled/quarantined unless support confirms callbacks | Ask support/docs for callback/webhook support before live cutover |
| `nonvoip` | Exists, but no longer used for default refresh | Confirmed from supplied non-VoIP API reference: profile-level webhook sends order `id`, `number`, `code`, `message`, `date` | Generic route: `/api/v1/provider-webhooks/nonvoip` | Webhook confirmed and parser-compatible; live order path verified, immediate refund returned `Not sufficient` | Keep immediate refund quarantined and verify real `provider_webhook_events` |
| `smspool` | Exists, but no longer used for default refresh | Reviewed official Postman collection: no webhook/callback entries; SMS delivery uses `sms/check`, rentals use `rental/retrieve_messages` | Generic route: `/api/v1/provider-webhooks/smspool` | Public docs look polling-only; provider should be disabled/quarantined unless support confirms callbacks | Ask support/account manager for webhook support |
| `textverified` | Exists, but no longer used for default refresh | Confirmed in official v2 Swagger: `v2.sms.received` webhook with `data.reservationId`, `data.smsContent`, `data.parsedCode` | Generic route with TextVerified parser: `/api/v1/provider-webhooks/textverified` | Webhook confirmed and implemented; live order/cancel path verified, real SMS callback pending | Configure TextVerified API Webhook Settings and verify signature/event processing |
| `telabot` | Exists, but no longer used for default refresh | Confirmed from supplied Tell A Bot docs: webhook URL receives `incoming_message` posts with `id`, `reply`, `pin`, `service`, and retry behavior | Generic route: `/api/v1/provider-webhooks/telabot` | Webhook confirmed and parser-compatible; live order/reject path verified, real SMS callback pending | Configure Account -> Profile webhook URL and verify real `provider_webhook_events` |
| `nonvoip_s6` | Same backend as `nonvoip` | Same as non-VoIP-backed `nonvoip` | Generic route: `/api/v1/provider-webhooks/nonvoip_s6` | Alias; follows `nonvoip` | Do not classify separately |

## Implementation State

Added:

- Provider inbound webhook foundation.
- SMSReady inbound endpoint.
- PVADeals inbound endpoint.
- Generic provider inbound endpoint.
- Webhook-first refresh path with provider polling disabled by default.
- Temporary and rental order updates from provider inbound SMS webhooks.
- Provider delivery strategy registry.
- Provider inbound webhook audit log: `provider_webhook_events`.
- Internal provider webhook audit API with replay support.
- Authenticated provider webhooks now acknowledge unmatched order events with HTTP 200 while keeping `reason=order_not_found` in the response/audit trail. This prevents provider dashboards from disabling callbacks after valid test/race events and keeps the event replayable.
- Customer webhook outbox/delivery worker.
- Internal support review queue for auto-refund failures.
- Shared rental no-SMS protection service: provider close/cancel, local wallet refund, background guard, and global sweep all read stored webhook state first and only use provider close APIs when a refund action is due.
- Mini App purchase no longer has provider-direct fallback helpers; all temp/rental/voice purchases must go through shared API quote/order services.

Not done:

- Live provider dashboard configuration for all active providers.
- Public/API docs do not currently confirm webhooks for SMSPool, VAK-SMS, and PVAPins.
- HeroSMS, TextVerified, non-VoIP, and Tell A Bot have documented webhook support, but still need live account-level delivery verification.
- Bespoke parser upgrades for providers whose real webhook payload does not fit the generic normalizer.

## Cutover Plan

1. Configure provider dashboards to the `phantom-app.net` callback URL.
2. Buy low-risk test numbers and verify `provider_webhook_events` reaches `processed`.
3. If a provider sends a different payload shape, add a provider-specific normalizer and replay unmatched events.
4. Keep customer-facing refresh as a database/status refresh, not an upstream SMS poll.
5. Disable or quarantine any active provider that cannot send webhook callbacks for code delivery.

## Operational Verification

Before fully trusting a provider, verify `provider_webhook_events` shows:

- `processed` events for real purchased orders.
- Low or zero `unmatched` events after dashboard URL configuration.
- No recurring `ignored/missing_code` pattern for valid SMS payloads.
- Customer-facing `numbers.order.sms` deliveries are queued after provider webhook processing.

If an event is `unmatched` because the order had not been persisted yet or the provider payload mapping changed, replay it through:

`POST /api/v1/numbers/ops/provider-webhook-events/{event_id}/replay`
