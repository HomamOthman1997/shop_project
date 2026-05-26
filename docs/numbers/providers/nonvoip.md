# non-VoIP Provider API

Status: documented from supplied non-VoIP reference and current adapter  
Adapter: `services/numbers/providers/nonvoip_provider.py`  
Provider codes: `nonvoip`, `nonvoip_s6`

## Naming

`nonvoip_s6` is not a separate provider integration. It is a second public lane that points to the same provider object.

## Base And Auth

Base URL:

```text
https://www.non-voip.com/api/reseller
```

Auth:

- JSON POST requests.
- Local settings: `nonvoip_key` and `nonvoip_email`.
- Optional override: `nonvoip_base_url`.

## Current Adapter Commands

| Operation | Command/path | Params |
| --- | --- | --- |
| List services | `get_service_list` | account auth |
| Price by country/service | `get-prices` | `country_id` |
| Availability check | `limits` | `country_id` |
| Buy by numeric service/country | `get-number` | `application_id`, `country_id` |
| Buy by service id | `order_number` | `service_id` |
| SMS polling fallback | `get-sms`, fallback `get_messages` | `request_id` or `order_id` |
| Cancel | `set-status` with `reject`, fallback `close` | `id`, `status` |
| Refund fallback | `refund_number` | `id` |
| Transfer credit | `transfer_credit` | `email_to`, `amount`; reseller-only |

## Webhooks

Confirmed supplied non-VoIP webhook payload:

```json
{"id":"123","number":"15551234567","code":"123456","message":"Your code is 123456","date":"2026-05-25"}
```

Local route:

```text
POST /api/v1/provider-webhooks/nonvoip
POST /api/v1/provider-webhooks/nonvoip_s6
```

Normalizer:

- generic parser maps `id` to provider order id.
- maps `code`.
- maps root `message` as full SMS text.

## Missing Or Needs Live Verification

- Account profile webhook URL setup confirmation.
- One real webhook event for `nonvoip` and, if used, `nonvoip_s6`.
- Exact current cancellation/refund response examples for both `set-status` and `refund_number`.
- Account balance endpoint is not present in the supplied non-VoIP reseller docs. The adapter treats balance as unsupported unless non-VoIP support provides a documented command.
