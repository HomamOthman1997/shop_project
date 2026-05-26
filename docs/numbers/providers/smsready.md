# SMSReady Provider API

Status: documented from supplied provider docs and current adapter  
Adapter: `services/numbers/providers/smsready_provider.py`  
Provider code: `smsready`

## Base And Auth

Base URL:

```text
https://api.sms-ready.com/api/
```

Auth:

- Every upstream request sends `api_key`.
- Local setting name: `smsready_key`.
- Optional override: `smsready_base_url`.

## One-Time Numbers

| Operation | Method | Endpoint | Params |
| --- | --- | --- | --- |
| List services | GET | `get-services-for-one-time-numbers/` | `api_key` |
| List countries | GET | `get-countries-for-one-time-numbers/` | `api_key` |
| Get price | GET | `get-price-one-time-number/` | `api_key`, `service`, `country` |
| Order number | POST | `order-one-time-number/` | `api_key`, `service`, `country` |
| Refund order | POST | `refund-one-time-order/` | `api_key`, `order_id` |
| Resend order | POST | `resend-one-time-order/` | `api_key`, `order_id` |

Current adapter behavior:

- `get_sms()` intentionally returns no provider poll result because SMSReady delivery should arrive by webhook.
- `cancel()` maps to `refund-one-time-order/`.
- `resend()` maps to `resend-one-time-order/`.

## Long-Term Rentals

| Operation | Method | Endpoint | Params |
| --- | --- | --- | --- |
| List rental services | GET | `get-services-ltr/` | `api_key` |
| List rental countries | GET | `get-countries-for-long-term/` | `api_key` |
| Get rental prices | GET | `get-order-info-ltr/` | `api_key`, `service`, `country` |
| Create rental | POST | `order-ltr/` | `api_key`, `service`, `duration`, `country`, optional `mdn` |
| Release rental | POST | `release-ltr/` | `api_key`, `order_id` |
| Activate rental | POST | `activate-ltr/` | `api_key`, `order_id` |
| Toggle autorenew | POST | `autorenew-ltr/` | `api_key`, `order_id` |

## Webhooks

Confirmed events from supplied docs:

```json
{"event":"new_sms","message":{"order_id":51,"number":"18583056127","code":"245646","full_sms":"Here is your code: 245646"}}
```

```json
{"event":"ltr_renewal","message":{"order_id":51,"number":"18583056127","expires_at":"2023-06-30 23:59:59","cost":"12.00"}}
```

Local route:

```text
POST /api/v1/provider-webhooks/smsready
```

Normalizer:

- accepts only `event = new_sms` for code delivery.
- maps `message.order_id` to provider order id.
- maps `message.code` and `message.full_sms`.

## Missing Or Needs Live Verification

- Account dashboard callback URL configuration must be verified.
- Need one real `new_sms` event and one LTR-related event sample in `provider_webhook_events`.
- Account balance endpoint is not present in the supplied SMSReady docs. The adapter can price, buy, cancel, resend, and rent, but balance should be treated as unsupported unless SMSReady support provides a documented balance command.

## Live Notes

- 2026-05-26: local dry-run attempts failed to connect to `api.sms-ready.com:443` with a network-name error before price/order calls could complete.
- Retry this provider from Railway/production networking before marking it live-ready.
