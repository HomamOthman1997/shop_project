# TextVerified Provider API

Status: documented from official v2 docs and current adapter  
Adapter: `services/numbers/providers/textverified_provider.py`  
Provider code: `textverified`

## Base And Auth

Base URL:

```text
https://www.textverified.com/api
```

Auth flow:

1. POST `/pub/v2/auth`.
2. Headers: `X-API-USERNAME`, `X-API-KEY`, `Content-Type: application/json`.
3. Response returns bearer `token`.
4. Subsequent requests use `Authorization: Bearer <token>`.

Local settings:

- `tv_user`
- `tv_key`

## Temporary Verification

| Operation | Method | Path | Body/query |
| --- | --- | --- | --- |
| Pricing | POST | `/pub/v2/pricing/verifications` | service/country/capability payload |
| Buy verification | POST | `/pub/v2/verifications` | service/country/capability/area-code payload |
| Poll SMS | GET | `/pub/v2/sms` | verification/reservation identifiers |
| Poll calls | GET | `/pub/v2/calls` | verification/reservation identifiers |
| Download recording | GET | recording URI returned by API | bearer auth where needed |
| Cancel verification | POST | `/pub/v2/verifications/{id}/cancel` | none |
| Reuse/resend | POST | `/pub/v2/verifications/{id}/reuse` | none |
| List services | GET | `/pub/v2/services` | `reservationType`, `numberType` |
| Account | GET | `/pub/v2/account/me` | none |

Local behavior:

- Supports SMS and voice capability pricing.
- Supports US state/area-code targeting.
- Follows HAL/link-style responses when the API returns links.

## Rentals

| Operation | Method | Path |
| --- | --- | --- |
| Rental pricing | POST | `/pub/v2/pricing/rentals` |
| Create rental | POST | `/pub/v2/reservations/rental` |
| Resolve reservation | GET | `/pub/v2/reservations/{reservation_id}` |
| Refund nonrenewable rental | POST | `/pub/v2/reservations/rental/nonrenewable/{reservation_id}/refund` |
| Refund renewable rental | POST | `/pub/v2/reservations/rental/renewable/{reservation_id}/refund` |
| Renew rental | POST | `/pub/v2/reservations/rental/renewable/{reservation_id}/renew` |
| Wake request | POST | `/pub/v2/wake-requests` |
| Rental notes/tags | GET | `/pub/v2/reservations/rental/{reservation_id}/user-notes` |

## Webhooks

Confirmed v2 webhook event:

```json
{
  "event": "v2.sms.received",
  "data": {
    "reservationId": "reservation-id",
    "smsContent": "Your code is 123456",
    "parsedCode": "123456"
  }
}
```

Official docs mention `X-Webhook-Signature`.

Local route:

```text
POST /api/v1/provider-webhooks/textverified
```

Normalizer:

- accepts only `event = v2.sms.received`.
- maps `data.reservationId`, `data.parsedCode`, `data.smsContent`.

## Missing Or Needs Live Verification

- Decide whether to implement TextVerified signature validation in addition to the shared `token` URL/header check.
- Real webhook event sample from account settings.
- Exact response body for rental SMS retrieval in current account, because adapter resolves details through reservation/sale links.

