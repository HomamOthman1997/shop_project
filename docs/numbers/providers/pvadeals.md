# PVADeals Provider API

Status: documented from current adapter and supplied webhook/API notes  
Adapter: `services/numbers/providers/pvadeals_provider.py`  
Provider code: `pvadeals`

## Base And Auth

Base URL:

```text
https://prod-v3.pvadeals.com/v3/api
```

Auth:

- `Authorization: Bearer <api-key>`.
- Local setting name: `pvadeals_key`.
- Optional override: `pvadeals_base_url`.

## Endpoints Used By The Adapter

| Operation | Method | Path | Body/query |
| --- | --- | --- | --- |
| List services | GET | `/services/all` | none |
| Balance | GET | `/balance` | none |
| Buy temp number | POST | `/purchase` | JSON service/country payload |
| Read request/SMS | GET | `/request/{request_id}` | none |
| Flag/cancel request | POST | `/flag/{request_id}` | none |
| Reuse/resend | POST | `/reuse/{request_id}` | none |
| Buy LTR/rental | POST | `/purchase-ltr` | JSON service/country/duration payload |
| Read rental info | GET | `/request/{request_id}` | none |
| Renew rental | POST | `/renew-ltr/{request_id}` | none |

Current adapter behavior:

- Service discovery is cached.
- Rental options are derived from service fields like `LTR3price`, `LTR7price`, `LTR14price`, `LTR30price`.
- "All services" rental uses local constant `ALL_SERVICES_SERVICE_ID`.
- `finish_rental()` currently delegates to cancel/flag behavior where applicable.

## Webhooks

Confirmed supplied events:

- `sms_received`
- `number_purchased`
- `number_flagged`

Local route:

```text
POST /api/v1/provider-webhooks/pvadeals
```

Normalizer:

- accepts only `event = sms_received` for code delivery.
- maps `requestId` to provider order id.
- maps `code` and `message`.

## Missing Or Needs Live Verification

- Exact rental refund/cancel behavior from current PVADeals docs.
- Real account webhook payload sample for `sms_received`.
- Whether renew/cancel events need first-class support in our inbound webhook normalizer.

