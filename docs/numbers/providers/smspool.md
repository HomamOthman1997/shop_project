# SMSPool Provider API

Status: confirmed polling-only for current account; enabled through provider-level polling exception
Adapter: `services/numbers/providers/smspool_provider.py`  
Provider code: `smspool`

## Base And Auth

Base URL:

```text
https://api.smspool.net
```

Auth:

- Most endpoints send `key` in form data.
- Local setting name: `smspool_key`.

## Temporary Numbers

| Operation | Method | Endpoint | Params |
| --- | --- | --- | --- |
| Pricing | POST form | `/request/pricing` | `key` |
| Purchase SMS | POST form | `/purchase/sms` | `key`, `service`, `country`, optional `state`, optional `pool` |
| Balance | POST form | `/request/balance` | `key` |
| SMS check | POST form fallback | `/sms/check`, fallback `/request/check` | `key`, `orderid` |
| Cancel | POST form fallback | `/sms/cancel`, fallback `/request/cancel` | `key`, `orderid` |

Local notes:

- Reuse mode sets `pool=foxtrot`.
- State targeting is best-effort and only sent when the UI selected a state.
- Pricing chooses the lowest nonzero matching service/country row.

## Rentals

SMSPool is not listed as normal finite rental in manager capabilities, but the adapter supports unlimited rental-style catalog/purchase flows.

| Operation | Method | Endpoint | Params |
| --- | --- | --- | --- |
| Rental catalog | POST form | `/rental/retrieve_all` | `key`, `type` |
| Purchase rental | POST form | `/purchase/rental` | `key`, `id`, `days` |
| Rental messages | POST form | `/rental/retrieve_messages` | `key`, `rental_code` |
| Rental info | POST form fallback | `/rental/info`, fallback `/rental/retrieve` | `key`, `rental_code` |
| Rental refund/finish | POST form fallback | `/rental/refund`, fallback `/rental/refund.php` | `key`, `rental_code` |

## Delivery Strategy

No webhook/callback entry was found in the reviewed SMSPool Postman collection, and the account was confirmed to have no webhook support. SMSPool must be treated as polling-only.

Local generic route exists only for future compatibility:

```text
POST /api/v1/provider-webhooks/smspool
```

## Missing Or Needs Live Verification

- Rental refund response examples and refund window policy.
- Whether `/sms/check` returns a stable message array for all products or can return a single text/code field.
