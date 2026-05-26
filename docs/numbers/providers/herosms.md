# HeroSMS Provider API

Status: documented from supplied provider docs and current adapter  
Adapter: `services/numbers/providers/herosms_provider.py`  
Provider code: `herosms`

## Base And Auth

Base URL:

```text
https://hero-sms.com/stubs/handler_api.php
```

Auth:

- Handler-style query requests include the configured API key.
- Local setting name: `herosms_key`.
- Optional override: `herosms_base_url`.

## Temporary Numbers

| Operation | Action | Params |
| --- | --- | --- |
| List services | `getServicesList` | key |
| List countries | `getCountries` | key |
| Get prices | `getPrices` | `service`, optional `country` |
| Buy number | `getNumberV2`, fallback `getNumber` | `service`, `country` |
| Poll SMS/status | `getStatus` | `id` |
| Cancel/refund | `setStatus` status `-1`, fallback status `8`, fallback `cancelActivation` | `id` |
| Resend | `setStatus` status `3` | `id` |
| Balance | `getBalance` | key |

## Rentals

| Operation | Action | Params |
| --- | --- | --- |
| Rental prices/count | `serviceCountRent` | `service`, `country`, duration-related params |
| Rent number | `getRentNumber` | `service`, `country`, duration-related params |
| Rental SMS | `getAllSms` | `id`, `size`, `page` |
| Finish rental | `finishActivation` | `id` |

## Webhooks

Confirmed supplied webhook shape:

```json
{
  "activationId": "123456",
  "service": "tg",
  "text": "Your code is 12345",
  "code": "12345",
  "country": 2,
  "receivedAt": "2025-12-16T10:30:00.000000Z"
}
```

Provider behavior from supplied docs:

- Method: POST.
- Content-Type: `application/json`.
- Provider expects HTTP 200.
- Retries are performed when response is not 200.

Local route:

```text
POST /api/v1/provider-webhooks/herosms
```

Normalizer:

- generic parser maps `activationId` to provider order id.
- maps `code` and `text`.

## Missing Or Needs Live Verification

- Dashboard webhook URL setup path.
- One real webhook event captured in `provider_webhook_events`.
- Whether HeroSMS signs webhooks or only relies on source IP/account settings.

## Live Notes

- 2026-05-26: `getPrices` for a low-cost US service succeeded and exposed provider country id `187`.
- 2026-05-26: live buy attempt for that service returned `NO_NUMBERS`; this is classified as `provider_no_stock`.
- The adapter must not retry temporary buys without a numeric `country`, because HeroSMS rejects no-country buy calls with a misleading validation error.
