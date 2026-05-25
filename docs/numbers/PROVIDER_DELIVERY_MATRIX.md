# Numbers Provider Delivery Matrix

Status: draft  
Last updated: 2026-05-25

Goal: classify how each upstream Numbers provider delivers inbound OTP/SMS so the backend can run webhook-first without guessing provider payloads.

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
| `smsready` | Exists, but no longer used for default refresh | Confirmed from supplied SMSReady docs: `new_sms` webhook with `order_id`, `number`, `code`, `full_sms` | Yes: `/api/v1/provider-webhooks/smsready` | Webhook confirmed and implemented | Configure dashboard webhook URL and token |
| `pvadeals` | Exists, but no longer used for default refresh | Confirmed in official docs: `sms_received`, `number_purchased`, `number_flagged` webhooks | Yes: `/api/v1/provider-webhooks/pvadeals` | Webhook confirmed and implemented | Configure dashboard webhook URL and token |
| `herosms` | Exists, but no longer used for default refresh | Probable: public HeroSMS client docs show `smsIncoming` webhook payload with `activationId`, `text`, `code` | Generic route: `/api/v1/provider-webhooks/herosms` | Route ready, provider-side setup needs live verification | Configure provider callback, then verify real `provider_webhook_events` |
| `pvapins` | Exists, but no longer used for default refresh | Not confirmed from API page; docs emphasize polling `get_sms.php` | Generic route: `/api/v1/provider-webhooks/pvapins` | Route ready, provider webhook capability unconfirmed | Ask support or find account dashboard webhook settings |
| `vaksms` | Exists, but no longer used for default refresh | Not confirmed; public API docs show `getSmsCode` polling path | Generic route: `/api/v1/provider-webhooks/vaksms` | Route ready, provider webhook capability unconfirmed | Ask support/docs for callback/webhook support |
| `smsman` | Exists, but no longer used for default refresh | Not confirmed; public technical docs expose `getSMS` polling | Generic route: `/api/v1/provider-webhooks/smsman` | Route ready, provider webhook capability unconfirmed | Ask support/docs for callback/webhook support |
| `smspool` | Exists, but no longer used for default refresh | Not confirmed from currently reviewed public docs | Generic route: `/api/v1/provider-webhooks/smspool` | Route ready, provider webhook capability unconfirmed | Check account/API docs or support |
| `textverified` | Exists, but no longer used for default refresh | Not confirmed from currently reviewed public docs | Generic route: `/api/v1/provider-webhooks/textverified` | Route ready, provider webhook capability unconfirmed | Check API reference/account settings |
| `telabot` | Exists, but no longer used for default refresh | Not confirmed from local docs/search | Generic route: `/api/v1/provider-webhooks/telabot` | Route ready, provider webhook capability unconfirmed | Check provider docs/support |
| `smsman_s6` | Same backend as `smsman` | Same as `smsman` | Generic route: `/api/v1/provider-webhooks/smsman_s6` | Alias; follows `smsman` | Do not classify separately |

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
- Customer webhook outbox/delivery worker.
- Internal support review queue for auto-refund failures.

Not done:

- Live provider dashboard configuration for all active providers.
- Real callback verification for HeroSMS, SMSPool, TextVerified, SMS-Man, VAK-SMS, PVAPins, and Telabot.
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
